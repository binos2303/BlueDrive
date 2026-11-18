from dataclasses import dataclass, field
from typing import BinaryIO, Protocol, Sequence


class StorageError(Exception):
    """Base class for sanitized storage operation failures."""


class StorageNotFoundError(StorageError):
    pass


class StorageRetryableError(StorageError):
    """A transient error; callers may retry within their own bounded policy."""


class StorageNonRetryableError(StorageError):
    pass


class StorageIntegrityError(StorageNonRetryableError):
    pass


class StorageConfigurationError(StorageNonRetryableError):
    pass


@dataclass(frozen=True, repr=False)
class ObjectStat:
    size_bytes: int
    etag: str = ""
    checksum_sha256: str = ""
    checksum_type: str = ""
    metadata: dict[str, str] = field(default_factory=dict, repr=False)
    version_id: str = ""


@dataclass(frozen=True, repr=False)
class MultipartUpload:
    upload_id: str


@dataclass(frozen=True, repr=False)
class PresignedRequest:
    url: str = field(repr=False)
    method: str
    required_headers: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class MultipartPart:
    part_number: int
    etag: str
    size_bytes: int = 0
    checksum_sha256: str = ""


class StorageAdapter(Protocol):
    """Provider-neutral object and multipart operations used by file services."""

    def create_object_key(self, purpose: str) -> str: ...

    def stat_object(self, object_key: str, *, version_id: str = "") -> ObjectStat: ...

    def verify_object(
        self,
        object_key: str,
        *,
        expected_size: int,
        expected_sha256: str | None = None,
        version_id: str = "",
    ) -> ObjectStat: ...

    def initiate_multipart(
        self, object_key: str, *, upload_session_id: str, content_type: str = ""
    ) -> MultipartUpload: ...

    def create_part_upload_url(
        self, object_key: str, upload_id: str, part_number: int, *, expires_in: int
    ) -> PresignedRequest: ...

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
    ) -> ObjectStat: ...

    def list_uploaded_parts(self, object_key: str, upload_id: str) -> list[MultipartPart]: ...

    def abort_multipart(self, object_key: str, upload_id: str) -> None: ...

    def create_download_url(
        self, object_key: str, *, expires_in: int, download_name: str | None = None, version_id: str = ""
    ) -> PresignedRequest: ...

    def open_object(self, object_key: str, *, version_id: str = "") -> BinaryIO: ...

    def download_to(
        self, object_key: str, destination: BinaryIO, *, max_bytes: int | None = None
    ) -> ObjectStat: ...

    def put_object(
        self,
        object_key: str,
        body: BinaryIO,
        *,
        size_bytes: int,
        sha256_hex: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> ObjectStat: ...

    def publish_verified_object(
        self,
        source_key: str,
        destination_key: str,
        *,
        expected_size: int,
        expected_sha256: str,
        upload_session_id: str,
        content_type: str = "application/octet-stream",
        expected_source_etag: str = "",
    ) -> ObjectStat: ...

    def quarantine_object(
        self,
        object_key: str,
        *,
        quarantine_key: str,
        expected_size: int,
        expected_sha256: str | None = None,
    ) -> ObjectStat: ...

    def delete_object(self, object_key: str) -> None: ...

    def list_exact_versions(self, object_key: str) -> list[dict[str, str]]: ...
