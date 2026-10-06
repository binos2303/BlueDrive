# SecureDrive

SecureDrive is a Django-based centralized web file-management application for a university thesis project.

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

The database stores metadata and encryption metadata. The encrypted file content is stored under Django `MEDIA_ROOT` on the server. The original plaintext file is not persisted as a normal server file.

```text
Browser
   |
   v
Django application
   |--------------------> MySQL (metadata, wrapped DEK, nonce, hash)
   |
   `--------------------> MEDIA_ROOT/uploads/*.enc (ciphertext)
```

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
