import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.exceptions import ImproperlyConfigured


# Key chỉ lấy từ biến môi trường, tuyệt đối không hard-code trong source.
KEY_ENV_NAME = "SECUREDRIVE_AES_KEY"

# AES-GCM nên dùng nonce 96-bit (12 byte).
NONCE_LENGTH = 12


def get_encryption_key() -> bytes:
    """
    Đọc AES-256 key từ biến môi trường.

    Key được lưu ở dạng Base64 để dễ đặt trong file .env,
    nhưng khi dùng phải giải mã thành đúng 32 byte.
    """
    encoded_key = os.getenv(KEY_ENV_NAME)

    if not encoded_key:
        raise ImproperlyConfigured(
            f"{KEY_ENV_NAME} is not configured."
        )

    try:
        key = base64.b64decode(
            encoded_key,
            validate=True,
        )
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{KEY_ENV_NAME} must be valid Base64."
        ) from exc

    # 32 bytes = AES-256.
    if len(key) != 32:
        raise ImproperlyConfigured(
            f"{KEY_ENV_NAME} must decode to exactly 32 bytes."
        )

    return key


def build_file_aad(user_id: int, sha256: str) -> bytes:
    """
    AAD không bị mã hóa nhưng được AES-GCM xác thực.

    Gắn file với owner và SHA-256 của plaintext. Nếu attacker
    đổi ciphertext giữa các user hoặc sửa metadata này, decrypt thất bại.
    """
    return (
        f"securedrive:file:v1:{user_id}:{sha256}"
    ).encode("utf-8")


def encrypt_bytes(
    plaintext: bytes,
    associated_data: bytes,
) -> tuple[bytes, bytes]:
    """
    Mã hóa plaintext bằng AES-256-GCM.

    Ciphertext trả về đã bao gồm authentication tag 16 byte.
    Nonce phải được lưu cùng bản ghi File để giải mã sau này.
    """
    nonce = os.urandom(NONCE_LENGTH)

    ciphertext = AESGCM(
        get_encryption_key()
    ).encrypt(
        nonce,
        plaintext,
        associated_data,
    )

    return ciphertext, nonce


def decrypt_bytes(
    ciphertext: bytes,
    nonce: bytes,
    associated_data: bytes,
) -> bytes:
    """
    Giải mã và xác thực integrity.

    Nếu key, nonce, AAD, hoặc ciphertext sai, AESGCM sẽ ném InvalidTag.
    Không được bỏ qua lỗi này.
    """
    return AESGCM(
        get_encryption_key()
    ).decrypt(
        nonce,
        ciphertext,
        associated_data,
    )