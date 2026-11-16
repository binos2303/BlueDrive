# S3-compatible storage adapter — hướng dẫn MinIO lịch sử

> **Tài liệu lịch sử, không thực thi các bước MinIO bên dưới.** Từ 16/11/2026, [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) chọn SeaweedFS-only, bỏ lộ trình MinIO/cutover. Các file Compose/CORS/policy MinIO được dẫn đã bị xóa trong diff có sẵn trước P0. Xem [runbook SeaweedFS](../infra/seaweedfs/README.md) và [P0 baseline](REFACTOR_P0_BASELINE_2026-11-16.md); adapter S3 vẫn được giữ. Không suy ra quyền dừng/xóa dữ liệu runtime hiện tại.

The adapter uses AWS-maintained `boto3` against the S3 API. Application services depend on the `StorageAdapter` interface in `backend/files/storage_adapters/base.py`; SDK calls live in `s3_compatible.py`. The same interface can be implemented for another S3-compatible service without moving provider calls into file views or models.

## Current integration boundary

The direct upload endpoints use the adapter for multipart authorization/completion and private object reads/writes. Legacy Django `FileField` uploads still use `MEDIA_ROOT`. The current multipart flow verifies bytes in private `staging/`, then publishes an unencrypted application object in private `primary/`; deployment-side S3 encryption is configured separately. Previously application-encrypted files retain their decryption path. Never return staging/quarantine references or signed URLs in logs or analytics.

The S3 API abstraction is like a standard electrical outlet: the application calls the same storage operations while a different provider implementation handles its own connection details.

## Start a local MinIO service

From PowerShell in `backend`, set temporary development credentials in the current process. Do not use production credentials or commit them:

```powershell
$env:MINIO_ROOT_USER = 'sd-local-admin'
$env:MINIO_ROOT_PASSWORD = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:SECUREDRIVE_STORAGE_ACCESS_KEY_ID = 'sd-local-app'
$env:SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
docker compose -f minio-compose.yml up -d
```

Ports bind to loopback. In the same PowerShell session (with the MinIO Client `mc` installed), create the private bucket and least-privilege application identity. The variables created above stay in that session. Commands read credentials from process environment variables rather than embedding values:

```powershell
mc alias set local http://127.0.0.1:9000 $env:MINIO_ROOT_USER $env:MINIO_ROOT_PASSWORD
mc mb --ignore-existing local/securedrive-dev
mc admin policy create local securedrive-app minio-dev-policy.json
mc admin user add local $env:SECUREDRIVE_STORAGE_ACCESS_KEY_ID $env:SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY
mc admin policy attach local securedrive-app --user $env:SECUREDRIVE_STORAGE_ACCESS_KEY_ID
```

If the policy or user already exists on a retained local volume, reuse that test identity rather than re-creating it. The pinned community server image is only an S3 API contract-test target; verify image availability, supported release, CORS, KMS and lifecycle behavior with the selected deployment before enabling browser-direct uploads. To stop and remove the local object data after you have finished with it, use `docker compose -f minio-compose.yml down -v`; this removes the local MinIO volume.

Set the Django adapter configuration in the same PowerShell session, then install dependencies and run the opt-in integration tests:

```powershell
$env:SECUREDRIVE_STORAGE_ENDPOINT_URL = 'http://127.0.0.1:9000'
$env:SECUREDRIVE_STORAGE_BUCKET = 'securedrive-dev'
$env:SECUREDRIVE_STORAGE_REGION = 'us-east-1'
$env:SECUREDRIVE_STORAGE_TLS_VERIFY = 'true'
$env:SECUREDRIVE_MINIO_INTEGRATION = 'true'
$env:SECUREDRIVE_MINIO_TIMEOUT_TEST_ENDPOINT = 'http://127.0.0.1:8666'
$env:SECUREDRIVE_MINIO_TIMEOUT_UPSTREAM = 'minio:9000'
python -m pip install -r requirements.txt
python manage.py test files.tests.test_storage_adapter files.tests.test_minio_storage_integration
```

The timeout integration test injects downstream latency through the local Toxiproxy service and checks that retries stop at the configured bound. MinIO-specific tests are skipped unless `SECUREDRIVE_MINIO_INTEGRATION=true`. Never use a public MinIO playground: the test suite writes and deletes objects.

## Deployment settings and secrets

Set `SECUREDRIVE_STORAGE_ENDPOINT_URL`, `SECUREDRIVE_STORAGE_BUCKET`, `SECUREDRIVE_STORAGE_REGION`, and `SECUREDRIVE_STORAGE_ADDRESSING_STYLE` in the deployment environment (`path` for MinIO, typically `virtual` for AWS S3). Supply both `SECUREDRIVE_STORAGE_ACCESS_KEY_ID` and `SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY` from a secret manager, or omit both and use the runtime's standard workload identity/credential chain. A half-configured pair is rejected. No credential is stored in `StorageConfig` or exposed to the browser.

Use HTTPS endpoints and certificate verification in deployment. For a private CA, configure `SECUREDRIVE_STORAGE_CA_BUNDLE` with a mounted CA file. Production settings reject an HTTP endpoint or disabled TLS verification. Keep the bucket private; the adapter never sends a public ACL. Do not grant anonymous access. Give the runtime identity only object-scoped `GetObject`, `PutObject`, `DeleteObject`, `AbortMultipartUpload`, and `ListMultipartUploadParts` access to the required quarantine/final prefixes. Some S3 services return `403` instead of `404` for a missing object unless the identity also has `ListBucket`; the adapter intentionally does not reinterpret `403` as missing because it may indicate wrong credentials. Grant `ListBucket` only on the configured bucket if typed missing-object behavior is required, and verify this against that provider. Add multipart enumeration only to a separate reconciler identity if it is needed. Do not grant bucket policy/ACL administration to the application. The local MinIO policy is limited to its disposable test bucket and is not a production IAM/KMS policy.

Configure connection/read timeouts, `SECUREDRIVE_STORAGE_MAX_ATTEMPTS`, and capped exponential backoff with jitter for retryable operations. The SDK-level retry count is one so it does not multiply the adapter's bounded policy. Initiate and complete/put operations are not blindly retried after ambiguous failures; callers reconcile with the persisted upload ID, server-generated key and `HeadObject`. Deleting and aborting an already-absent object/upload are safe to repeat. Logs contain only operation, retryability and attempt count; never add signed URLs, credentials, raw provider responses, or content metadata.

PostgreSQL and object storage are not one transaction. The caller must persist its server-generated object key and pending state before writing. After a storage success/DB failure, retry or delete that deterministic object reference through an outbox/reconciler; after a DB success/storage failure, keep the location unavailable and retry/mark it for cleanup. An ambiguous multipart-initiate response is not retried because it can create an orphan upload; expire incomplete uploads with a bucket lifecycle rule and reconcile them from persisted upload state.

Set `SECUREDRIVE_STORAGE_SSE=AES256` or `aws:kms` only when supported and approved for the selected storage deployment. With `aws:kms`, set `SECUREDRIVE_STORAGE_KMS_KEY_ID` to a non-secret key reference and grant only the required `kms:GenerateDataKey`/`kms:Decrypt` actions on that key to the service identity. Key policy, quarantine retention, SSE-KMS support and restore remain operational decisions in ADR-0001.

`GET /drive/files/{id}/download-url/` issues a short-lived, version-pinned download authorization for an accessible, available, unencrypted current version in active primary storage. StorageLocation.provider_version_id comes from verified publication, not a later HEAD of the latest object. Application-encrypted files, legacy local files and locations without a trustworthy pin retain Django-mediated download. See [download configuration, compatibility and verification](PRESIGNED_DOWNLOAD_2026-11-07.md).

When using versioned storage, runtime IAM also needs bucket-scoped ListBucketVersions and object-scoped GetObjectVersion/DeleteObjectVersion. The adapter purges exact-key versions and delete markers in bounded API batches for staging cleanup and permanent deletion; ordinary DeleteObject alone is insufficient. Apply migration 0016 and deploy version-aware cleanup before enabling bucket versioning. Turning the direct-download feature flag off does not undo bucket versioning or remove these IAM requirements. The 08/11 local rollout uses a scoped application identity; the old operator identity remains outside runtime configuration.

Protocol references: [Boto3 multipart initiation](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/create_multipart_upload.html), [Boto3 presigned URLs](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/generate_presigned_url.html), and the [MinIO S3 API compatibility matrix](https://docs.min.io/aistor/developers/s3-api-compatibility/). Confirm behavior against the exact deployed MinIO release; protocol compatibility does not guarantee identical deployment limits or CORS/KMS features.

## Replacing MinIO later

SeaweedFS dùng lại adapter S3 hiện có, không thêm implementation/provider riêng. Giữ typed errors, key/checksum/version contract, retry và private-object guarantees. Runbook và công cụ manifest hiện hành nằm trong [quy trình Platform](../infra/seaweedfs/README.md) và [ADR-0008](ADR-0008-platform-storage-copy-and-publication.md). Hướng dẫn MinIO ở trên chỉ còn phục vụ nguồn/rollback và contract tests; đổi endpoint không di chuyển object hoặc credential.

## Upload API and workers

The Next.js client calls Django at `/files/api/uploads/`, requests one short-lived URL per part, and sends each part with an 8 MiB target size and at most three concurrent requests. It retries transient part failures at most three times. Re-running an interrupted task uses its opaque server session and overwrites its parts; it never saves signed URLs. A successful S3 completion puts the session into `verifying` and atomically creates a database finalization job. The scheduled `finalize_uploads` command validates the complete object, applies the existing server-side AES-GCM format, writes and verifies the final object, then commits file metadata and quota as `available`. Optional scanner integration is a trusted callable selected by `SECUREDRIVE_UPLOAD_SCANNER`; empty configuration skips scanning without representing a clean verdict.

For local upload CORS, apply the loopback development policy with `mc cors set local/securedrive-dev minio-dev-cors.xml` from `backend/`. For deployment, use only the deployed frontend origin, `PUT`, signed request headers and exposed `ETag`; do not reuse the localhost origin or allow public reads. Native download navigation does not require a GET CORS grant or reading attachment headers in JavaScript. TLS is required for deployed storage endpoints. Schedule `python manage.py finalize_uploads` and `python manage.py cleanup_uploads`; the database jobs provide recovery across web process restarts, while no Celery/task-queue dependency is introduced. The browser computes SHA-256 through Web Crypto before upload; this reads the current 100 MiB bounded file into memory.
