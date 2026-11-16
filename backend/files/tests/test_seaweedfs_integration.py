"""Gate S3 thật; chỉ ghi/xóa key ngẫu nhiên do chính bài test tạo ở local."""
import base64
import hashlib
from http.client import HTTPConnection
import io
import os
import socket
import time
import unittest
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

from files.storage_adapters.base import MultipartPart, StorageIntegrityError, StorageNotFoundError
from files.storage_adapters.s3_compatible import S3CompatibleStorageAdapter


ENABLED = os.getenv("SEAWEEDFS_INTEGRATION") == "1"


class _LoopbackHTTPConnection(HTTPConnection):
    def connect(self):
        if self.host == "s3.localhost":
            # Windows có thể thiếu DNS .localhost; chỉ đổi địa chỉ TCP, giữ Host đã ký.
            self.sock = socket.create_connection(("127.0.0.1", self.port), self.timeout, self.source_address)
        else:
            super().connect()


def http(url, *, method="GET", body=None, headers=None):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "s3.localhost"} or parsed.username or parsed.password:
        raise AssertionError("Gate HTTP chỉ cho phép endpoint loopback development.")
    connection = _LoopbackHTTPConnection(parsed.hostname, parsed.port or 80, timeout=10)
    try:
        target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        connection.request(method, target, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    except OSError:
        raise AssertionError("Không kết nối được endpoint kiểm thử; URL được ẩn.") from None
    finally:
        connection.close()


class LoopbackHTTPTests(unittest.TestCase):
    def test_localhost_transport_preserves_signed_host_and_query_without_dns(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread
        from unittest.mock import patch

        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.update(host=self.headers["Host"], target=self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"local-test")

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            server.timeout = 5
            thread = Thread(target=server.handle_request, daemon=True)
            thread.start()
            try:
                # Mô phỏng resolver Windows chỉ nhận địa chỉ IP, không nhận s3.localhost.
                resolver = socket.getaddrinfo

                def resolve(host, *args, **kwargs):
                    self.assertEqual(host, "127.0.0.1")
                    return resolver(host, *args, **kwargs)

                with patch.object(socket, "getaddrinfo", side_effect=resolve):
                    status, _, payload = http(f"http://s3.localhost:{server.server_port}/bucket/key?fixture=one%2Ftwo")
                self.assertEqual((status, payload), (200, b"local-test"))
                self.assertEqual(received, {"host": f"s3.localhost:{server.server_port}", "target": "/bucket/key?fixture=one%2Ftwo"})
            finally:
                thread.join(timeout=10)

    def test_non_loopback_endpoint_is_rejected_before_connecting(self):
        from unittest.mock import patch
        with patch.object(socket, "create_connection") as connect:
            with self.assertRaises(AssertionError):
                http("http://outside.invalid/fixture")
            connect.assert_not_called()


def digest(payload):
    return base64.b64encode(hashlib.sha256(payload).digest()).decode()


@unittest.skipUnless(ENABLED, "BLOCKED: cần SeaweedFS thật và SEAWEEDFS_INTEGRATION=1.")
class SeaweedFSIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("SEAWEEDFS_ALLOW_TEST_WRITES") != "1":
            raise RuntimeError("Cần SEAWEEDFS_ALLOW_TEST_WRITES=1 cho bucket development.")
        cls.endpoint = os.environ["SEAWEED_S3_ENDPOINT"]
        cls.public = os.environ["SEAWEED_S3_PUBLIC_ENDPOINT"]
        for endpoint in (cls.endpoint, cls.public):
            parsed = urlsplit(endpoint)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "s3.localhost"}:
                raise RuntimeError("Gate này chỉ ghi dữ liệu ở endpoint loopback development.")
        cls.bucket = os.environ["SEAWEED_S3_BUCKET"]
        cls.credentials = {"aws_access_key_id": os.environ["SEAWEED_S3_ACCESS_KEY"], "aws_secret_access_key": os.environ["SEAWEED_S3_SECRET_KEY"]}
        cls.adapter = S3CompatibleStorageAdapter(endpoint_url=cls.endpoint, public_endpoint_url=cls.public,
            public_upload_endpoint=True, bucket=cls.bucket, access_key_id=cls.credentials["aws_access_key_id"],
            secret_access_key=cls.credentials["aws_secret_access_key"], max_attempts=1)
        cls.client = cls.adapter._client
        cls.client.head_bucket(Bucket=cls.bucket)
        cls.signer = boto3.client("s3", endpoint_url=cls.public, region_name="us-east-1", **cls.credentials,
                                  config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.signer.close()

    def key(self, purpose="staging"):
        key = self.adapter.create_object_key(purpose)
        self.addCleanup(self.adapter.delete_object, key)
        return key

    def multipart(self, key, **kwargs):
        response = self.client.create_multipart_upload(Bucket=self.bucket, Key=key,
            Metadata={"securedrive-upload-id": "seaweedfs-integration"}, **kwargs)
        upload_id = response["UploadId"]
        self.addCleanup(self.adapter.abort_multipart, key, upload_id)
        return upload_id

    def test_put_get_head_range_delete_metadata_and_full_sha256(self):
        payload = b"BlueDrive SeaweedFS gate\n" * 1024
        key = self.key("primary")
        stored = self.adapter.put_object(key, io.BytesIO(payload), size_bytes=len(payload), sha256_hex=hashlib.sha256(payload).hexdigest())
        self.assertEqual(stored.size_bytes, len(payload))
        self.assertEqual(stored.metadata["securedrive-sha256"], hashlib.sha256(payload).hexdigest())
        with self.adapter.open_object(key, version_id=stored.version_id) as body:
            self.assertEqual(body.read(), payload)
        response = self.client.get_object(Bucket=self.bucket, Key=key, Range="bytes=3-15")
        try:
            self.assertEqual(response["ResponseMetadata"]["HTTPStatusCode"], 206)
            self.assertEqual(response["ContentLength"], 13)
            self.assertEqual(response["ContentRange"], f"bytes 3-15/{len(payload)}")
            self.assertEqual(response["Body"].read(), payload[3:16])
        finally:
            response["Body"].close()
        with self.assertRaises(StorageIntegrityError):
            self.adapter.verify_object(key, expected_size=len(payload), expected_sha256="0" * 64)
        self.adapter.delete_object(key)
        with self.assertRaises(StorageNotFoundError):
            self.adapter.stat_object(key)

    def test_presigned_put_get_expired_and_tampered_signature(self):
        key, payload = self.key(), b"signed-upload"
        params = {"Bucket": self.bucket, "Key": key}
        put = self.signer.generate_presigned_url("put_object", Params=params, ExpiresIn=60)
        self.assertEqual(urlsplit(put).netloc, urlsplit(self.public).netloc)
        self.assertIn(http(put, method="PUT", body=payload)[0], (200, 201))
        get = self.signer.generate_presigned_url("get_object", Params=params, ExpiresIn=60)
        self.assertEqual(http(get)[2], payload)
        parsed = urlsplit(get)
        changed = [(key, "0" * 64 if key == "X-Amz-Signature" else value) for key, value in parse_qsl(parsed.query)]
        invalid = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(changed), ""))
        self.assertEqual(http(invalid)[0], 403)
        expires = self.signer.generate_presigned_url("get_object", Params=params, ExpiresIn=1)
        time.sleep(3)
        self.assertEqual(http(expires)[0], 403)

    def test_multipart_resume_complete_abort_and_worker_copy_contract(self):
        key, primary = self.key(), self.key("primary")
        session = uuid.uuid4().hex
        upload = self.adapter.initiate_multipart(key, upload_session_id=session)
        self.addCleanup(self.adapter.abort_multipart, key, upload.upload_id)
        chunks = (b"a" * (8 * 1024 * 1024), b"b" * 123)
        receipts = []
        for number, chunk in enumerate(chunks, 1):
            signed = self.adapter.create_part_upload_url(key, upload.upload_id, number, expires_in=60)
            self.assertEqual(urlsplit(signed.url).netloc, urlsplit(self.public).netloc)
            status, headers, _ = http(signed.url, method="PUT", body=chunk, headers=signed.required_headers)
            self.assertEqual(status, 200)
            receipts.append(MultipartPart(part_number=number, etag=headers["ETag"]))
            provider = self.adapter.list_uploaded_parts(key, upload.upload_id)
            self.assertEqual([(p.part_number, p.etag) for p in provider], [(p.part_number, p.etag) for p in receipts])
        payload = b"".join(chunks)
        stat = self.adapter.complete_multipart(key, upload.upload_id, receipts, expected_size=len(payload),
            expected_part_size=len(chunks[0]), expected_part_count=2, expected_upload_session_id=session)
        repeated = self.adapter.complete_multipart(key, upload.upload_id, receipts, expected_size=len(payload), expected_upload_session_id=session)
        self.assertEqual(repeated.etag, stat.etag)
        output = io.BytesIO()
        retrieved = self.adapter.download_to(key, output, max_bytes=len(payload))
        self.assertEqual(output.getvalue(), payload)
        self.adapter.publish_verified_object(key, primary, expected_size=len(payload), expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_session_id=session, expected_source_etag=retrieved.etag)
        with self.adapter.open_object(primary) as body:
            self.assertEqual(body.read(), payload)
        with self.assertRaises(StorageIntegrityError):
            self.adapter.publish_verified_object(key, primary, expected_size=len(payload), expected_sha256=hashlib.sha256(payload).hexdigest(),
                upload_session_id=session, expected_source_etag="wrong-etag")
        aborted_key = self.key()
        aborted = self.multipart(aborted_key)
        self.adapter.abort_multipart(aborted_key, aborted)
        self.adapter.abort_multipart(aborted_key, aborted)
        with self.assertRaises(ClientError):
            self.client.list_parts(Bucket=self.bucket, Key=aborted_key, UploadId=aborted)

    def test_per_part_checksum_correct_wrong_missing_and_changed_signed_header(self):
        key = self.key()
        chunks = (b"sha256-part\n" * (512 * 1024), b"inherited-sha256-tail\n")
        payload = b"".join(chunks)
        upload_id = self.multipart(key, ChecksumAlgorithm="SHA256")
        params = {"Bucket": self.bucket, "Key": key, "UploadId": upload_id}
        part_checksum = digest(chunks[0])
        signed_params = {**params, "PartNumber": 1, "ChecksumSHA256": part_checksum}
        signed = self.signer.generate_presigned_url("upload_part", Params=signed_params, ExpiresIn=60)
        query = dict(parse_qsl(urlsplit(signed).query))
        self.assertIn("x-amz-checksum-sha256", query.get("X-Amz-SignedHeaders", "").split(";"))
        for case, body, headers, expected_status, expected_code in (
            ("missing-signed-header", chunks[0], {}, 403, "SignatureDoesNotMatch"),
            ("changed-signed-header", chunks[0], {"x-amz-checksum-sha256": digest(b"changed")}, 403, "SignatureDoesNotMatch"),
            ("wrong-body-checksum", b"corrupt-bytes", {"x-amz-checksum-sha256": part_checksum}, 400, "BadDigest"),
        ):
            with self.subTest(case=case):
                status, _, error_body = http(signed, method="PUT", body=body, headers=headers)
                self.assertEqual(status, expected_status)
                self.assertEqual(ElementTree.fromstring(error_body).findtext("Code"), expected_code)
        self.assertEqual(self.client.list_parts(Bucket=self.bucket, Key=key, UploadId=upload_id).get("Parts", []), [])
        receipts = []
        for number, chunk in enumerate(chunks, 1):
            required_headers = {"x-amz-checksum-sha256": part_checksum}
            if number == 2:
                # PR #11403 cho phép part không ràng buộc header kế thừa SHA256 từ upload.
                signed = self.signer.generate_presigned_url("upload_part", Params={**params, "PartNumber": number}, ExpiresIn=60)
                inherited_query = dict(parse_qsl(urlsplit(signed).query))
                self.assertNotIn("x-amz-checksum-sha256", inherited_query.get("X-Amz-SignedHeaders", "").split(";"))
                required_headers = {}
            status, headers, _ = http(signed, method="PUT", body=chunk, headers=required_headers)
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("x-amz-checksum-sha256"), digest(chunk))
            receipts.append({"PartNumber": number, "ETag": headers["ETag"], "ChecksumSHA256": headers["x-amz-checksum-sha256"]})

        parts = self.client.list_parts(**params)["Parts"]
        self.assertEqual([(p["PartNumber"], p["ETag"], p["Size"]) for p in parts],
                         [(p["PartNumber"], p["ETag"], len(chunk)) for p, chunk in zip(receipts, chunks)])
        for part, receipt in zip(parts, receipts):
            # 4.53 thiếu checksum ở ListParts; bắt buộc kiểm receipt, Complete/Head và bytes bên dưới.
            if "ChecksumSHA256" in part:
                self.assertEqual(part["ChecksumSHA256"], receipt["ChecksumSHA256"])

        for case, checksum, expected_code in (("missing-completion-checksum", None, "InvalidRequest"),
                                               ("wrong-completion-checksum", digest(b"wrong-checksum"), "BadDigest")):
            manifest = [dict(receipt) for receipt in receipts]
            if checksum is None:
                del manifest[0]["ChecksumSHA256"]
            else:
                manifest[0]["ChecksumSHA256"] = checksum
            with self.subTest(case=case):
                with self.assertRaises(ClientError) as raised:
                    self.client.complete_multipart_upload(**params, MultipartUpload={"Parts": manifest})
                self.assertEqual(raised.exception.response["ResponseMetadata"]["HTTPStatusCode"], 400)
                self.assertEqual(raised.exception.response["Error"]["Code"], expected_code)
                self.assertEqual(self.client.list_parts(**params)["Parts"], parts)
                with self.assertRaises(ClientError) as unpublished:
                    self.client.head_object(Bucket=self.bucket, Key=key)
                self.assertEqual(unpublished.exception.response["ResponseMetadata"]["HTTPStatusCode"], 404)

        complete = self.client.complete_multipart_upload(**params, MultipartUpload={"Parts": receipts})
        head = self.client.head_object(Bucket=self.bucket, Key=key, VersionId=complete["VersionId"], ChecksumMode="ENABLED")
        composite = digest(b"".join(hashlib.sha256(chunk).digest() for chunk in chunks)) + "-2"
        self.assertEqual(complete.get("ChecksumSHA256"), composite)
        self.assertEqual(complete.get("ChecksumType"), "COMPOSITE")
        self.assertEqual(head.get("ChecksumSHA256"), composite)
        self.assertEqual(head.get("ChecksumType"), "COMPOSITE")
        self.assertEqual(head["ContentLength"], len(payload))
        with self.adapter.open_object(key, version_id=complete["VersionId"]) as body:
            downloaded = body.read()
        self.assertEqual(downloaded, payload)
        self.assertEqual(hashlib.sha256(downloaded).hexdigest(), hashlib.sha256(payload).hexdigest())
        # Composite SHA256 không được thay thế SHA256 toàn file trong adapter/finalizer.
        with self.assertRaises(StorageIntegrityError):
            self.adapter.verify_object(key, expected_size=len(payload), expected_sha256=hashlib.sha256(payload).hexdigest())

    def test_provider_enforces_copy_source_if_match(self):
        source, target = self.key(), self.key("primary")
        written = self.client.put_object(Bucket=self.bucket, Key=source, Body=b"conditional-copy", Metadata={"gate": "metadata"})
        params = {"Bucket": self.bucket, "Key": target, "CopySource": {"Bucket": self.bucket, "Key": source}}
        with self.assertRaises(ClientError) as raised:
            self.client.copy_object(**params, CopySourceIfMatch='"wrong-source-etag"')
        self.assertEqual(raised.exception.response["ResponseMetadata"]["HTTPStatusCode"], 412)
        self.client.copy_object(**params, CopySourceIfMatch=written["ETag"], MetadataDirective="COPY")
        self.assertEqual(self.adapter.stat_object(target).metadata.get("gate"), "metadata")

    def test_version_pinning_copy_and_delete_all_versions(self):
        self.assertEqual(self.client.get_bucket_versioning(Bucket=self.bucket).get("Status"), "Enabled")
        key = self.key("primary")
        first = self.client.put_object(Bucket=self.bucket, Key=key, Body=b"first")["VersionId"]
        second = self.client.put_object(Bucket=self.bucket, Key=key, Body=b"second")["VersionId"]
        self.assertNotEqual(first, second)
        self.assertNotIn(first, ("", "null"))
        with self.adapter.open_object(key, version_id=first) as body:
            self.assertEqual(body.read(), b"first")
        signed = self.adapter.create_download_url(key, expires_in=60, version_id=first)
        self.assertEqual(http(signed.url)[2], b"first")
        self.adapter.delete_object(key)
        versions = self.client.list_object_versions(Bucket=self.bucket, Prefix=key)
        self.assertFalse(versions.get("Versions", []) + versions.get("DeleteMarkers", []))

    def test_anonymous_invalid_credentials_and_cross_bucket_are_denied(self):
        for config, credentials in ((Config(signature_version=UNSIGNED), {}),
                (Config(signature_version="s3v4"), {"aws_access_key_id": "invalid-gate-key", "aws_secret_access_key": "invalid-gate-secret"})):
            client = boto3.client("s3", endpoint_url=self.endpoint, region_name="us-east-1", config=config, **credentials)
            try:
                with self.assertRaises(ClientError) as raised:
                    client.head_bucket(Bucket=self.bucket)
                self.assertIn(raised.exception.response["ResponseMetadata"]["HTTPStatusCode"], (401, 403))
            finally:
                client.close()
        with self.assertRaises(ClientError) as raised:
            self.client.head_bucket(Bucket="outside-bluedrive-" + uuid.uuid4().hex)
        self.assertEqual(raised.exception.response["ResponseMetadata"]["HTTPStatusCode"], 403)
        existing_cors = self.client.get_bucket_cors(Bucket=self.bucket)["CORSRules"]
        for operation, params in ((self.client.put_bucket_versioning, {"VersioningConfiguration": {"Status": "Enabled"}}),
                                   (self.client.put_bucket_cors, {"CORSConfiguration": {"CORSRules": existing_cors}})):
            with self.subTest(case="bucket-administration-denied"), self.assertRaises(ClientError) as raised:
                operation(Bucket=self.bucket, **params)
            self.assertEqual(raised.exception.response["ResponseMetadata"]["HTTPStatusCode"], 403)

    def test_cors_preflight_and_exposed_upload_receipts(self):
        origin = os.environ["FRONTEND_ORIGINS"].split(",")[0]
        key = self.key()
        signed = self.signer.generate_presigned_url("put_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=60)
        status, headers, _ = http(signed, method="OPTIONS", headers={"Origin": origin, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type,x-amz-checksum-sha256"})
        self.assertIn(status, (200, 204))
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)
        status, headers, _ = http(signed, method="PUT", body=b"cors", headers={"Origin": origin})
        self.assertEqual(status, 200)
        exposed = {value.strip().lower() for value in headers.get("Access-Control-Expose-Headers", "").split(",")}
        self.assertTrue({"etag", "x-amz-checksum-sha256"} <= exposed)
        _, rejected, _ = http(signed, method="OPTIONS", headers={"Origin": "https://unapproved.invalid", "Access-Control-Request-Method": "PUT"})
        self.assertNotIn(rejected.get("Access-Control-Allow-Origin"), ("*", "https://unapproved.invalid"))
