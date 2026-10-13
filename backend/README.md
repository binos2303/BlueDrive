# SecureDrive

SecureDrive uses a Next.js frontend and Django backend for centralized file management. Next.js is the only user-facing UI; Django provides API and file-operation endpoints and redirects legacy page URLs to the configured Next.js origin.

## Core requirements

- Upload and download files.
- Centralized server-side storage.
- File management: copy, cut, paste, move, rename, trash, restore and permanent deletion.
- Folder management: create, open, copy, cut, paste/move, rename, trash, restore and permanent deletion.
- File encryption before storage using AES-256-GCM.
- Per-file Data Encryption Key (DEK), wrapped by a server-side master key.
- Authentication, authorization and optional file/folder sharing.
- MIME/content validation and upload-size limits.
- Activity/audit logging for important actions.

## Storage architecture

The database stores metadata and encryption metadata. Legacy form uploads still store encrypted content under Django `MEDIA_ROOT`. The browser multipart API stores incoming bytes in a private S3-compatible quarantine object, then a durable Django management-command worker validates and AES-GCM encrypts them before publishing final metadata. Downloads remain Django-mediated and read either legacy local content or final object-store ciphertext.

```text
Browser -- signed multipart parts --> private MinIO quarantine
   |                                      |
   `--> Django API (auth/quota/state)      `--> scheduled finalizer --> AES-GCM final object
```

See [the MinIO adapter guide](../docs/MINIO_STORAGE_ADAPTER.md) for local setup, integration tests, and deployment configuration.

## Encryption model

Each file receives a random 32-byte DEK. The file is encrypted with AES-256-GCM. The DEK is separately encrypted with the server master key and stored as `wrapped_dek`. AES-GCM AAD binds the ciphertext to the file owner, file ID and encryption version.

This is application/server-side encryption, not end-to-end encryption.

## Setup

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and provide local database and cryptographic secrets.
4. Generate a 32-byte Base64 master key, for example:

```bash
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

5. Apply migrations:

```bash
python manage.py migrate
```

6. Run checks:

```bash
python manage.py check
python manage.py test
```

7. Start locally:

```bash
python manage.py runserver
```

## Important security notes

- Never commit or submit `.env`.
- Never expose the master encryption key in source code.
- For production, use HTTPS and enable secure cookies/HSTS only when the deployment is actually behind HTTPS.
- The current implementation reads a complete file into memory during encryption/decryption. This is acceptable for the thesis scope and 100 MB upload limit, but a production-scale implementation should use chunked/streaming encryption.
# Direct multipart upload

Set `SECUREDRIVE_STORAGE_ENDPOINT_URL`, bucket and service-account credentials in the backend environment. Keep the bucket private. Allow only the frontend origin in bucket CORS for `PUT`, allow the signed request headers, and expose `ETag`; presigned URLs are short-lived bearer credentials. Production endpoints must use TLS and the service identity must be limited to the configured bucket and multipart/object operations.

Run `python manage.py finalize_uploads` repeatedly (for example, every minute) to verify downloaded quarantine bytes, run the optional configured scanner, encrypt using the existing AES-GCM service, publish the final private object, and commit quota. Run `python manage.py cleanup_uploads` regularly to abort expired multipart uploads and release reservations. Both commands are safe to re-run; monitor their summarized output and Django command exit status.

To enable the optional scanner, set `SECUREDRIVE_UPLOAD_SCANNER` to a trusted Python import path for a callable accepting `(plaintext_bytes, filename)` and returning exactly `True` only for a clean result. With the setting empty, SCANNING is skipped and the app does not claim a clean scan. This integration point is not itself an antivirus engine.
