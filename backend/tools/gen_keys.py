"""One-shot helper sinh secret ngẫu nhiên cho SecureDrive.

Chạy:
    python tools/gen_keys.py

Output là Base64 string, paste vào file .env tương ứng.
KHÔNG commit .env vào git.
"""
import base64
import secrets


def _b64(nbytes: int) -> str:
    return base64.b64encode(secrets.token_bytes(nbytes)).decode("ascii")


if __name__ == "__main__":
    print("# Dán các dòng sau vào .env (KHÔNG commit file này lên git):")
    print(f"SECRET_KEY={secrets.token_urlsafe(50)}")
    print(f"SECUREDRIVE_AES_KEY={_b64(32)}      # system wrapping key (32 bytes)")
    print(f"SECUREDRIVE_PEPPER={_b64(32)}       # Argon2id pepper (32 bytes)")
    print("SECUREDRIVE_CURRENT_KEY_ID=1")
