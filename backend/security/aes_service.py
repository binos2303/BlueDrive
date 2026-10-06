import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.exceptions import ImproperlyConfigured


KEY_LENGTH = 32          # 256 bits
NONCE_LENGTH = 12        # 96 bits

MASTER_KEY_ENV = "SECUREDRIVE_AES_KEY"


def get_master_key():
    """
    Lấy Master Key/KEK từ environment.

    Master Key không được lưu trong database.
    """

    encoded = os.getenv(MASTER_KEY_ENV,"",).strip()

    if not encoded:
        raise ImproperlyConfigured(f"{MASTER_KEY_ENV} is not configured.")

    try:
        key = base64.b64decode(
            encoded,
            validate=True,
        )
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{MASTER_KEY_ENV} must be valid Base64."
        ) from exc

    if len(key) != KEY_LENGTH:
        raise ImproperlyConfigured(
            f"{MASTER_KEY_ENV} must decode to "
            f"{KEY_LENGTH} bytes."
        )

    return key


def generate_dek():
    """
    Tạo Data Encryption Key riêng cho từng file.
    """

    return os.urandom(KEY_LENGTH)


def generate_nonce():
    """
    Tạo nonce 96-bit cho AES-GCM.
    """

    return os.urandom(NONCE_LENGTH)


def build_file_aad(
    owner_id,
    file_id,
    version,
):
    """
    Tạo Additional Authenticated Data.

    Ciphertext được ràng buộc với:
    - owner
    - file ID
    - encryption version
    """

    if not isinstance(owner_id, int) or owner_id <= 0:
        raise ValueError("Invalid owner_id.")

    if not isinstance(file_id, int) or file_id <= 0:
        raise ValueError("Invalid file_id.")

    if not isinstance(version, int) or version <= 0:
        raise ValueError("Invalid encryption version.")

    return (
        f"SecureDrive:file:"
        f"owner={owner_id}:"
        f"file={file_id}:"
        f"version={version}"
    ).encode("utf-8")


def encrypt_bytes(
    plaintext,
    dek,
    aad,
):
    """
    Encrypt plaintext bằng AES-256-GCM.

    Returns:
        ciphertext, nonce
    """

    if not isinstance(
        plaintext,
        (bytes, bytearray),
    ):
        raise TypeError(
            "plaintext must be bytes."
        )

    if not isinstance(
        dek,
        (bytes, bytearray),
    ):
        raise TypeError(
            "dek must be bytes."
        )

    if len(dek) != KEY_LENGTH:
        raise ValueError(
            "DEK must be 32 bytes."
        )

    nonce = generate_nonce()

    ciphertext = AESGCM(
        bytes(dek)
    ).encrypt(
        nonce,
        bytes(plaintext),
        bytes(aad),
    )

    return ciphertext, nonce


def decrypt_bytes(
    ciphertext,
    nonce,
    dek,
    aad,
):
    """
    Decrypt ciphertext bằng AES-256-GCM.

    Nếu ciphertext bị sửa hoặc AAD/DEK sai,
    AES-GCM sẽ raise InvalidTag.
    """

    if not isinstance(
        ciphertext,
        (bytes, bytearray),
    ):
        raise TypeError(
            "ciphertext must be bytes."
        )

    if not isinstance(
        nonce,
        (bytes, bytearray),
    ):
        raise TypeError(
            "nonce must be bytes."
        )

    if not isinstance(
        dek,
        (bytes, bytearray),
    ):
        raise TypeError(
            "dek must be bytes."
        )

    if len(dek) != KEY_LENGTH:
        raise ValueError(
            "DEK must be 32 bytes."
        )

    if len(nonce) != NONCE_LENGTH:
        raise ValueError(
            "Nonce must be 12 bytes."
        )

    return AESGCM(
        bytes(dek)
    ).decrypt(
        bytes(nonce),
        bytes(ciphertext),
        bytes(aad),
    )


def wrap_dek(
    dek,
    master_key,
):
    """
    Dùng Master Key để bảo vệ DEK.

    Returns:
        wrapped_dek, dek_nonce
    """

    if len(dek) != KEY_LENGTH:
        raise ValueError(
            "DEK must be 32 bytes."
        )

    if len(master_key) != KEY_LENGTH:
        raise ValueError(
            "Master Key must be 32 bytes."
        )

    dek_nonce = generate_nonce()

    wrapped_dek = AESGCM(
        bytes(master_key)
    ).encrypt(
        dek_nonce,
        bytes(dek),
        b"SecureDrive:DEK:v1",
    )

    return wrapped_dek, dek_nonce


def unwrap_dek(
    wrapped_dek,
    dek_nonce,
    master_key,
):
    """
    Giải mã wrapped DEK bằng Master Key.
    """

    if len(master_key) != KEY_LENGTH:
        raise ValueError(
            "Master Key must be 32 bytes."
        )

    if len(dek_nonce) != NONCE_LENGTH:
        raise ValueError(
            "DEK nonce must be 12 bytes."
        )

    return AESGCM(
        bytes(master_key)
    ).decrypt(
        bytes(dek_nonce),
        bytes(wrapped_dek),
        b"SecureDrive:DEK:v1",
    )