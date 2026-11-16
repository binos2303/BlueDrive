"""Chạy gate local bằng identity ứng dụng; không ghi presigned URL vào log."""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from files.storage_adapters.s3_compatible import S3CompatibleStorageAdapter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init-bucket", "test", "browser", "seed-restart", "verify-restart"))
    parser.add_argument("--config-dir", type=Path, default=Path(__file__).resolve().parent,
                        help="Thư mục cấu hình lab độc lập; mặc định giữ SeaweedFS Platform.")
    args = parser.parse_args()
    directory = args.config_dir.resolve()
    if not (directory / ".env").is_file() or not (directory / ".local/cors.json").is_file():
        raise ValueError("Thư mục cấu hình lab thiếu .env hoặc .local/cors.json.")
    load_dotenv(directory / ".env", override=True)
    if os.getenv("SEAWEEDFS_ALLOW_TEST_WRITES") != "1":
        raise ValueError("Cần SEAWEEDFS_ALLOW_TEST_WRITES=1.")
    endpoint, public = (os.environ[key] for key in ("SEAWEED_S3_ENDPOINT", "SEAWEED_S3_PUBLIC_ENDPOINT"))
    for value in (endpoint, public):
        if urlsplit(value).scheme != "http" or urlsplit(value).hostname not in {"localhost", "127.0.0.1", "s3.localhost"}:
            raise ValueError("Chỉ dùng loopback development.")
    bucket = os.environ["SEAWEED_S3_BUCKET"]
    if args.action == "init-bucket":
        client = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
            aws_access_key_id=os.environ["SEAWEED_S3_ADMIN_ACCESS_KEY"], aws_secret_access_key=os.environ["SEAWEED_S3_ADMIN_SECRET_KEY"],
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, connect_timeout=2, read_timeout=10, retries={"total_max_attempts": 1}))
        try:
            try:
                client.head_bucket(Bucket=bucket)
            except ClientError as error:
                if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                    raise
            else:
                raise ValueError("Bucket đã tồn tại; không tự sửa versioning/CORS. Kiểm tra cấu hình hiện có.")
            client.create_bucket(Bucket=bucket)
            client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
            cors = json.loads((directory / ".local/cors.json").read_text(encoding="utf-8"))
            client.put_bucket_cors(Bucket=bucket, CORSConfiguration=cors)
            print("Đã tạo bucket development riêng, bật versioning và CORS cụ thể.")
        finally:
            client.close()
        return 0
    if args.action == "test":
        os.environ["SEAWEEDFS_INTEGRATION"] = "1"
        suite = unittest.defaultTestLoader.loadTestsFromName("files.tests.test_seaweedfs_integration.SeaweedFSIntegrationTests")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1
    adapter = S3CompatibleStorageAdapter(endpoint_url=endpoint, public_endpoint_url=public, bucket=bucket,
        access_key_id=os.environ["SEAWEED_S3_ACCESS_KEY"], secret_access_key=os.environ["SEAWEED_S3_SECRET_KEY"], max_attempts=1)
    manifest = directory / ".local/restart-probe.json"
    payload = b"BlueDrive Task 01 restart persistence\n"
    sha = hashlib.sha256(payload).hexdigest()
    try:
        if args.action == "browser":
            key = adapter.create_object_key("staging")
            signer = boto3.client("s3", endpoint_url=public, region_name="us-east-1",
                aws_access_key_id=os.environ["SEAWEED_S3_ACCESS_KEY"], aws_secret_access_key=os.environ["SEAWEED_S3_SECRET_KEY"],
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
            try:
                import base64
                checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode()
                ticket = {"origin": os.environ["FRONTEND_ORIGINS"].split(",")[0], "payload": list(payload),
                    "checksum": checksum, "put": signer.generate_presigned_url("put_object", Params={"Bucket": bucket, "Key": key, "ChecksumSHA256": checksum}, ExpiresIn=60),
                    "get": signer.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60)}
                browser = subprocess.run(["node", str(Path(__file__).resolve().with_name("browser-smoke.mjs"))], input=json.dumps(ticket),
                    encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                if browser.returncode != 0:
                    raise ValueError("Browser gate chưa đạt.")
                print("PASS: Chrome truy cập đúng host đã ký, CORS cho phép PUT/GET và đọc ETag/checksum.")
            finally:
                signer.close()
                adapter.delete_object(key)
        elif args.action == "seed-restart":
            if manifest.exists():
                raise ValueError("Probe chưa dọn; chạy verify-restart trước.")
            key = adapter.create_object_key("primary")
            stat = adapter.put_object(key, io.BytesIO(payload), size_bytes=len(payload), sha256_hex=sha)
            if not stat.version_id or stat.version_id == "null":
                raise ValueError("Probe chưa có version bất biến; giữ object để kiểm tra, không nghiệm thu persistence.")
            manifest.write_text(json.dumps({"key": key, "version_id": stat.version_id, "bucket": bucket,
                "endpoint": endpoint, "size_bytes": len(payload), "sha256": sha}), encoding="utf-8")
            print("Đã ghi probe; chỉ restart các service Platform đã được duyệt rồi chạy verify-restart.")
        else:
            probe = json.loads(manifest.read_text(encoding="utf-8"))
            if (probe.get("bucket") != bucket or probe.get("endpoint") != endpoint
                    or probe.get("size_bytes") != len(payload) or probe.get("sha256") != sha
                    or not re.fullmatch(r"primary/[0-9a-f]{32}", probe.get("key", ""))
                    or not isinstance(probe.get("version_id"), str) or probe["version_id"] in {"", "null"}):
                raise ValueError("Manifest probe thiếu hoặc không khớp định danh; giữ object và manifest để đối chiếu.")
            with adapter.open_object(probe["key"], version_id=probe["version_id"]) as body:
                if body.read() != payload:
                    raise ValueError("Nội dung probe sau restart không khớp.")
            # Chỉ dọn version probe đã xác minh, không xóa các version khác cùng key.
            adapter._client.delete_object(Bucket=bucket, Key=probe["key"], VersionId=probe["version_id"])
            manifest.unlink()
            print("PASS: object/version/bucket còn nguyên sau restart; đã dọn đúng probe.")
    finally:
        adapter._client.close()
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        print("BLOCKED: gate local chưa đạt; thông tin kết nối/secret/URL được ẩn.", file=sys.stderr)
        code = 1
    sys.exit(code)
