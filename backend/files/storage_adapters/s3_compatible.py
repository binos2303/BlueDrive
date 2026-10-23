import base64
import logging
import random
import re
import time
import uuid
from dataclasses import dataclass
from typing import BinaryIO, Callable, Sequence
from urllib.parse import quote, urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ConnectionClosedError,
    EndpointConnectionError,
    ProxyConnectionError,
    ReadTimeoutError,
)

from .base import (
    MultipartPart,
    MultipartUpload,
    ObjectStat,
    PresignedRequest,
    StorageConfigurationError,
    StorageError,
    StorageIntegrityError,
    StorageNonRetryableError,
    StorageNotFoundError,
    StorageRetryableError,
)

logger = logging.getLogger(__name__)

_RETRYABLE_CODES = {
    "408",
    "429",
    "500",
    "502",
    "503",
    "504",
    "InternalError",
    "RequestTimeout",
    "RequestTimeoutException",
    "SlowDown",
    "ServiceUnavailable",
    "Throttling",
    "ThrottlingException",
}
_NOT_FOUND_CODES = {"NoSuchKey", "NotFound", "404"}
_MISSING_UPLOAD_CODES = {"NoSuchUpload"}
_ACCESS_CODES = {
    "AccessDenied",
    "InvalidAccessKeyId",
    "InvalidToken",
    "SignatureDoesNotMatch",
    "ExpiredToken",
    "InvalidRegion",
}
_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
# Keep legacy prefixes accepted so existing database references remain readable.
# New uploads use staging/, validated objects are published under primary/, and
# rejected/failed completed uploads are retained under quarantine/.
_SERVER_OBJECT_KEY = re.compile(r"^(staging|primary|quarantine|final|preview)/[0-9a-f]{32}$")
_ALLOWED_KEY_PURPOSES = {"staging", "primary", "quarantine", "final", "preview"}


@dataclass(frozen=True)
class _RetrySettings:
    attempts: int
    base_seconds: float
    max_seconds: float


class S3CompatibleStorageAdapter:
    """S3 API adapter; SDK exceptions and credentials stay behind this boundary."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        region: str = "us-east-1",
        addressing_style: str = "path",
        access_key_id: str = "",
        secret_access_key: str = "",
        tls_verify: bool | str = True,
        ca_bundle: str = "",
        connect_timeout: float = 2,
        read_timeout: float = 10,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.1,
        retry_max_seconds: float = 1.0,
        max_presigned_url_seconds: int = 300,
        server_side_encryption: str = "",
        kms_key_id: str = "",
        client=None,
        sleep: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ):
        parsed = urlsplit(endpoint_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise StorageConfigurationError("Object storage endpoint must be an HTTP(S) URL.")
        if not bucket:
            raise StorageConfigurationError("Object storage bucket is required.")
        if addressing_style not in {"path", "virtual", "auto"}:
            raise StorageConfigurationError("S3 addressing style must be path, virtual, or auto.")
        if (access_key_id and not secret_access_key) or (secret_access_key and not access_key_id):
            raise StorageConfigurationError(
                "Both object storage credentials must be configured together."
            )
        if not 1 <= max_attempts <= 5 or connect_timeout <= 0 or read_timeout <= 0:
            raise StorageConfigurationError(
                "Object storage retry and timeout settings are invalid."
            )
        if not 0 <= retry_base_seconds <= retry_max_seconds <= 5:
            raise StorageConfigurationError("Object storage retry backoff settings are invalid.")
        if not 1 <= max_presigned_url_seconds <= 900:
            raise StorageConfigurationError(
                "Presigned URL lifetime must be between 1 and 900 seconds."
            )
        if server_side_encryption not in {"", "AES256", "aws:kms"}:
            raise StorageConfigurationError("Unsupported server-side encryption setting.")
        if server_side_encryption == "aws:kms" and not kms_key_id:
            raise StorageConfigurationError("A KMS key reference is required for KMS encryption.")

        self._endpoint_url = endpoint_url.rstrip("/")
        self._bucket = bucket
        self._max_presigned_url_seconds = max_presigned_url_seconds
        self._sse = server_side_encryption
        self._kms_key_id = kms_key_id
        self._retry = _RetrySettings(max_attempts, retry_base_seconds, retry_max_seconds)
        self._sleep = sleep
        self._random_uniform = random_uniform

        if client is not None:
            self._client = client
            return

        verify = ca_bundle or tls_verify
        client_args = {
            "service_name": "s3",
            "endpoint_url": self._endpoint_url,
            "region_name": region,
            "use_ssl": parsed.scheme == "https",
            "verify": verify,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style},
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                # Retry policy is implemented below so each operation has one bounded policy.
                retries={"total_max_attempts": 1, "mode": "standard"},
            ),
        }
        if access_key_id:
            client_args["aws_access_key_id"] = access_key_id
            client_args["aws_secret_access_key"] = secret_access_key
        self._client = boto3.client(**client_args)

    def create_object_key(self, purpose: str) -> str:
        if not isinstance(purpose, str) or purpose not in _ALLOWED_KEY_PURPOSES:
            raise StorageNonRetryableError("Unsupported object key purpose.")
        return f"{purpose}/{uuid.uuid4().hex}"

    def stat_object(self, object_key: str) -> ObjectStat:
        self._validate_object_key(object_key)
        response = self._call(
            "head_object",
            lambda: self._client.head_object(
                Bucket=self._bucket,
                Key=object_key,
                ChecksumMode="ENABLED",
            ),
        )
        return self._to_stat(response)

    def verify_object(
        self,
        object_key: str,
        *,
        expected_size: int,
        expected_sha256: str | None = None,
    ) -> ObjectStat:
        self._validate_object_key(object_key)
        stat = self.stat_object(object_key)
        if stat.size_bytes != expected_size:
            raise StorageIntegrityError("Stored object size does not match the expected size.")
        if expected_sha256:
            if not _SHA256_HEX.fullmatch(expected_sha256):
                raise StorageIntegrityError("Expected SHA-256 value is malformed.")
            if stat.checksum_type == "COMPOSITE":
                raise StorageIntegrityError(
                    "Composite multipart checksum cannot verify a full-object SHA-256."
                )
            if not stat.checksum_sha256:
                raise StorageIntegrityError("Storage did not return a SHA-256 checksum.")
            try:
                actual_hex = base64.b64decode(stat.checksum_sha256, validate=True).hex()
            except (ValueError, TypeError):
                raise StorageIntegrityError(
                    "Storage returned a malformed SHA-256 checksum."
                ) from None
            if actual_hex.lower() != expected_sha256.lower():
                raise StorageIntegrityError(
                    "Stored object checksum does not match the expected checksum."
                )
        return stat

    def initiate_multipart(
        self, object_key: str, *, upload_session_id: str, content_type: str = ""
    ) -> MultipartUpload:
        self._validate_object_key(object_key)
        if not upload_session_id:
            raise StorageNonRetryableError("An upload session identifier is required.")
        params = {
            "Bucket": self._bucket,
            "Key": object_key,
            "Metadata": {"securedrive-upload-id": str(upload_session_id)},
        }
        if content_type:
            params["ContentType"] = content_type
        params.update(self._sse_parameters())
        # Do not retry: an ambiguous successful initiate could create an orphaned multipart upload.
        response = self._call(
            "create_multipart_upload",
            lambda: self._client.create_multipart_upload(**params),
            idempotent=False,
        )
        return MultipartUpload(upload_id=response["UploadId"])

    def create_part_upload_url(
        self, object_key: str, upload_id: str, part_number: int, *, expires_in: int
    ) -> PresignedRequest:
        self._validate_object_key(object_key)
        if not upload_id:
            raise StorageNonRetryableError("Multipart upload identifier is required.")
        self._validate_expiry(expires_in)
        if not 1 <= part_number <= 10000:
            raise StorageNonRetryableError("Multipart part number is outside the allowed range.")
        try:
            url = self._client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": self._bucket,
                    "Key": object_key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=expires_in,
                HttpMethod="PUT",
            )
            return PresignedRequest(url=url, method="PUT")
        except BotoCoreError:
            raise StorageNonRetryableError(
                "Could not create a part upload authorization."
            ) from None

    def complete_multipart(
        self,
        object_key: str,
        upload_id: str,
        parts: Sequence[MultipartPart],
        *,
        expected_size: int,
        expected_part_size: int | None = None,
        expected_part_count: int | None = None,
        expected_upload_session_id: str | None = None,
    ) -> ObjectStat:
        self._validate_object_key(object_key)
        if not upload_id or expected_size < 0:
            raise StorageNonRetryableError(
                "Multipart upload identifier or expected size is invalid."
            )
        normalized = self._validate_manifest(parts)
        try:
            provider_parts = self._list_all_parts(object_key, upload_id)
        except StorageNotFoundError:
            return self._verify_completed_upload(
                object_key, expected_size, expected_upload_session_id
            )
        except StorageNonRetryableError as error:
            if getattr(error, "provider_code", "") not in _MISSING_UPLOAD_CODES:
                raise
            return self._verify_completed_upload(
                object_key, expected_size, expected_upload_session_id
            )
        if [(p.part_number, p.etag) for p in normalized] != [
            (p.part_number, p.etag) for p in provider_parts
        ]:
            raise StorageIntegrityError(
                "Multipart manifest does not match provider-confirmed parts."
            )
        if expected_part_count is not None and len(provider_parts) != expected_part_count:
            raise StorageIntegrityError("Provider part count does not match the upload session.")
        if expected_part_size is not None:
            if expected_part_size <= 0 or any(
                part.size_bytes != expected_part_size
                for part in provider_parts[:-1]
            ) or (provider_parts and not 0 < provider_parts[-1].size_bytes <= expected_part_size):
                raise StorageIntegrityError("Provider part sizes do not match the upload session.")
        if sum(part.size_bytes for part in provider_parts) != expected_size:
            raise StorageIntegrityError(
                "Provider-confirmed part sizes do not match the expected object size."
            )

        try:
            self._call(
                "complete_multipart_upload",
                lambda: self._client.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=object_key,
                    UploadId=upload_id,
                    MultipartUpload={
                        "Parts": [
                            {"PartNumber": part.part_number, "ETag": part.etag}
                            for part in normalized
                        ]
                    },
                ),
                idempotent=False,
            )
        except (StorageRetryableError, StorageNotFoundError) as completion_error:
            # Complete may have succeeded while its response was lost. HEAD resolves that ambiguity.
            try:
                return self._verify_completed_upload(
                    object_key, expected_size, expected_upload_session_id
                )
            except StorageNotFoundError:
                raise completion_error
            except StorageError:
                raise
        except StorageNonRetryableError as error:
            if getattr(error, "provider_code", "") not in _MISSING_UPLOAD_CODES:
                raise
            return self._verify_completed_upload(
                object_key, expected_size, expected_upload_session_id
            )
        return self._verify_completed_upload(
            object_key, expected_size, expected_upload_session_id
        )

    def abort_multipart(self, object_key: str, upload_id: str) -> None:
        self._validate_object_key(object_key)
        if not upload_id:
            return
        try:
            self._call(
                "abort_multipart_upload",
                lambda: self._client.abort_multipart_upload(
                    Bucket=self._bucket, Key=object_key, UploadId=upload_id
                ),
            )
        except StorageNotFoundError:
            # Repeated abort is safe after the provider has removed the multipart session.
            return
        except StorageNonRetryableError as error:
            if getattr(error, "provider_code", "") in _MISSING_UPLOAD_CODES:
                return
            raise

    def create_download_url(
        self, object_key: str, *, expires_in: int, download_name: str | None = None
    ) -> PresignedRequest:
        self._validate_object_key(object_key)
        self._validate_expiry(expires_in)
        params = {"Bucket": self._bucket, "Key": object_key}
        if download_name:
            safe_name = download_name.replace("\r", "").replace("\n", "")[:255]
            params["ResponseContentDisposition"] = (
                f"attachment; filename*=UTF-8''{quote(safe_name, safe='')}"
            )
        try:
            url = self._client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=expires_in, HttpMethod="GET"
            )
            return PresignedRequest(url=url, method="GET")
        except BotoCoreError:
            raise StorageNonRetryableError("Could not create a download authorization.") from None

    def open_object(self, object_key: str) -> BinaryIO:
        self._validate_object_key(object_key)
        response = self._call(
            "get_object",
            lambda: self._client.get_object(Bucket=self._bucket, Key=object_key),
        )
        return response["Body"]

    def download_to(self, object_key: str, destination: BinaryIO) -> ObjectStat:
        self._validate_object_key(object_key)
        if not destination.seekable():
            raise StorageNonRetryableError("Download destination must support safe retry reset.")
        for attempt in range(1, self._retry.attempts + 1):
            body = None
            try:
                destination.seek(0)
                destination.truncate(0)
                response = self._client.get_object(Bucket=self._bucket, Key=object_key)
                body = response["Body"]
                while True:
                    chunk = body.read(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
                destination.flush()
                if destination.tell() != int(response.get("ContentLength", -1)):
                    raise StorageIntegrityError(
                        "Downloaded object length does not match storage metadata."
                    )
                return self._to_stat(response)
            except (BotoCoreError, ClientError) as error:
                mapped = self._map_error(error)
                retryable = isinstance(mapped, StorageRetryableError)
                logger.warning(
                    "Object storage request failed",
                    extra={
                        "operation": "download_object",
                        "retryable": retryable,
                        "attempt": attempt,
                    },
                )
                if not retryable or attempt == self._retry.attempts:
                    raise mapped from None
                self._sleep(self._backoff(attempt))
            finally:
                if body is not None:
                    body.close()
        raise StorageRetryableError("Object storage download exhausted its retry policy.")

    def put_object(
        self,
        object_key: str,
        body: BinaryIO,
        *,
        size_bytes: int,
        sha256_hex: str,
        content_type: str = "application/octet-stream",
    ) -> ObjectStat:
        self._validate_object_key(object_key)
        if size_bytes < 0 or not _SHA256_HEX.fullmatch(sha256_hex):
            raise StorageNonRetryableError("Object size or checksum is invalid.")
        params = {
            "Bucket": self._bucket,
            "Key": object_key,
            "Body": body,
            "ContentLength": size_bytes,
            "ContentType": content_type or "application/octet-stream",
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(sha256_hex)).decode("ascii"),
            "Metadata": {"securedrive-sha256": sha256_hex.lower()},
        }
        params.update(self._sse_parameters())
        # Do not replay an ambiguous body write; resolve its outcome with HeadObject below.
        try:
            self._call("put_object", lambda: self._client.put_object(**params), idempotent=False)
        except StorageRetryableError as write_error:
            # Resolve a lost response without replaying a possibly completed body write.
            try:
                return self.verify_object(
                    object_key, expected_size=size_bytes, expected_sha256=sha256_hex
                )
            except StorageNotFoundError:
                raise write_error
        return self.verify_object(
            object_key, expected_size=size_bytes, expected_sha256=sha256_hex
        )

    def quarantine_object(
        self,
        object_key: str,
        *,
        quarantine_key: str,
        expected_size: int,
        expected_sha256: str | None = None,
    ) -> ObjectStat:
        self._validate_object_key(object_key)
        self._validate_object_key(quarantine_key)
        if expected_size < 0 or (expected_sha256 and not _SHA256_HEX.fullmatch(expected_sha256)):
            raise StorageNonRetryableError("Quarantine size or checksum is invalid.")
        if object_key == quarantine_key:
            raise StorageNonRetryableError("Quarantine source and destination must be different.")
        if not quarantine_key.startswith("quarantine/"):
            raise StorageNonRetryableError(
                "Quarantine destination must use a server-generated quarantine key."
            )
        try:
            self.verify_object(
                object_key, expected_size=expected_size, expected_sha256=expected_sha256
            )
        except StorageNotFoundError:
            # A stable server-persisted destination makes copy/delete retries idempotent.
            return self.verify_object(
                quarantine_key,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
        try:
            self._call(
                "copy_object",
                lambda: self._client.copy_object(
                    Bucket=self._bucket,
                    Key=quarantine_key,
                    CopySource={"Bucket": self._bucket, "Key": object_key},
                    MetadataDirective="COPY",
                    **self._sse_parameters(),
                ),
                idempotent=False,
            )
            quarantined = self.verify_object(
                quarantine_key,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
        except StorageError:
            # Source is retained on any uncertain copy outcome for reconciliation.
            raise
        self.delete_object(object_key)
        return quarantined

    def delete_object(self, object_key: str) -> None:
        self._validate_object_key(object_key)
        # S3 DeleteObject is idempotent, including when the object is already absent.
        self._call(
            "delete_object",
            lambda: self._client.delete_object(Bucket=self._bucket, Key=object_key),
        )

    def _list_all_parts(self, object_key: str, upload_id: str) -> list[MultipartPart]:
        parts = []
        marker = None
        while True:
            params = {"Bucket": self._bucket, "Key": object_key, "UploadId": upload_id}
            if marker is not None:
                params["PartNumberMarker"] = marker
            response = self._call("list_parts", lambda: self._client.list_parts(**params))
            parts.extend(
                MultipartPart(
                    part_number=item["PartNumber"],
                    etag=item["ETag"],
                    size_bytes=int(item.get("Size", 0)),
                    checksum_sha256=item.get("ChecksumSHA256", ""),
                )
                for item in response.get("Parts", [])
            )
            if not response.get("IsTruncated"):
                return parts
            marker = response.get("NextPartNumberMarker")

    @staticmethod
    def _validate_manifest(parts: Sequence[MultipartPart]) -> list[MultipartPart]:
        normalized = list(parts)
        if not normalized:
            raise StorageIntegrityError("Multipart completion requires at least one part.")
        numbers = [part.part_number for part in normalized]
        if numbers != sorted(set(numbers)) or numbers[0] < 1 or numbers[-1] > 10000:
            raise StorageIntegrityError("Multipart part numbers must be unique and ordered.")
        if any(not part.etag or "\r" in part.etag or "\n" in part.etag for part in normalized):
            raise StorageIntegrityError("Multipart part token is invalid.")
        return normalized

    def _verify_completed_upload(
        self,
        object_key: str,
        expected_size: int,
        expected_upload_session_id: str | None = None,
    ) -> ObjectStat:
        # Validate the SecureDrive session UUID stored in object metadata. This is
        # not the independent S3 Multipart UploadId used to complete the upload.
        stat = self.stat_object(object_key)
        if (
            expected_upload_session_id is not None
            and stat.metadata.get("securedrive-upload-id") != str(expected_upload_session_id)
        ):
            raise StorageIntegrityError("Completed object does not match the SecureDrive upload session.")
        if stat.size_bytes != expected_size:
            raise StorageIntegrityError("Completed object size does not match the expected size.")
        return stat

    def _to_stat(self, response: dict) -> ObjectStat:
        return ObjectStat(
            size_bytes=int(response.get("ContentLength", 0)),
            etag=str(response.get("ETag", "")).strip('"'),
            checksum_sha256=response.get("ChecksumSHA256", ""),
            checksum_type=response.get("ChecksumType", ""),
            metadata={
                str(key).lower(): str(value)
                for key, value in response.get("Metadata", {}).items()
            },
        )

    def _call(self, operation: str, call: Callable, *, idempotent: bool = True):
        attempts = self._retry.attempts if idempotent else 1
        for attempt in range(1, attempts + 1):
            try:
                return call()
            except StorageError:
                raise
            except (BotoCoreError, ClientError) as error:
                mapped = self._map_error(error)
                retryable = isinstance(mapped, StorageRetryableError)
                logger.warning(
                    "Object storage request failed",
                    extra={"operation": operation, "retryable": retryable, "attempt": attempt},
                )
                if not retryable or attempt == attempts:
                    raise mapped from None
                self._sleep(self._backoff(attempt))

    def _backoff(self, attempt: int) -> float:
        ceiling = min(
            self._retry.max_seconds,
            self._retry.base_seconds * (2 ** (attempt - 1)),
        )
        return self._random_uniform(0, ceiling)

    @staticmethod
    def _validate_object_key(object_key: str) -> None:
        if not isinstance(object_key, str) or not _SERVER_OBJECT_KEY.fullmatch(object_key):
            raise StorageNonRetryableError("Object key must be generated by the server.")

    @staticmethod
    def _map_error(error: Exception) -> StorageError:
        if isinstance(error, StorageError):
            return error
        if isinstance(error, ClientError):
            response = error.response or {}
            error_info = response.get("Error", {})
            code = str(error_info.get("Code", "Unknown"))
            status = int(response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)
            if code in _NOT_FOUND_CODES:
                return StorageNotFoundError("Object storage resource was not found.")
            if code in _MISSING_UPLOAD_CODES:
                mapped = StorageNonRetryableError("Multipart upload no longer exists.")
                mapped.provider_code = code
                return mapped
            if code in _RETRYABLE_CODES or status in {408, 429, 500, 502, 503, 504}:
                return StorageRetryableError("Object storage is temporarily unavailable.")
            if code in _ACCESS_CODES:
                return StorageNonRetryableError("Object storage rejected the configured identity.")
            mapped = StorageNonRetryableError("Object storage rejected the operation.")
            mapped.provider_code = code
            return mapped
        if isinstance(
            error,
            (
                ConnectTimeoutError,
                ReadTimeoutError,
                EndpointConnectionError,
                ProxyConnectionError,
                ConnectionClosedError,
            ),
        ):
            return StorageRetryableError("Object storage timed out or could not be reached.")
        if isinstance(error, BotoCoreError):
            return StorageNonRetryableError("Object storage SDK could not perform the operation.")
        return StorageNonRetryableError("Object storage operation failed.")

    def _sse_parameters(self) -> dict:
        if not self._sse:
            return {}
        params = {"ServerSideEncryption": self._sse}
        if self._sse == "aws:kms":
            params["SSEKMSKeyId"] = self._kms_key_id
        return params

    def _validate_expiry(self, expires_in: int) -> None:
        if not 1 <= expires_in <= self._max_presigned_url_seconds:
            raise StorageNonRetryableError("Presigned URL lifetime exceeds policy.")
