"""Hash & HMAC utilities cho SecureDrive.

Dùng cho:
- Chunk deduplication: SHA-256 của plaintext chunk.
- Tamper-evident audit log chain: SHA-256 liên kết các entry.
- Capability token cho share links: HMAC-SHA256.
"""
import hashlib
import hmac


def sha256_hex(data: bytes) -> str:
    """SHA-256 trả hex string, dùng cho chunk dedup / integrity check."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes")
    return hashlib.sha256(bytes(data)).hexdigest()


def verify_sha256(data: bytes, expected_hex: str) -> bool:
    """So sánh SHA-256 constant-time, chống timing attack."""
    if not isinstance(expected_hex, str):
        raise TypeError("expected_hex must be str")
    return hmac.compare_digest(sha256_hex(data), expected_hex)


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    """HMAC-SHA256 — dùng cho integrity tag và token signing."""
    if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
        raise ValueError("key must be at least 16 bytes")
    if not isinstance(message, (bytes, bytearray)):
        raise TypeError("message must be bytes")
    return hmac.new(bytes(key), bytes(message), hashlib.sha256).digest()


def audit_chain_hash(prev_hash: bytes, payload: bytes) -> bytes:
    """Hash chain cho audit log — mỗi entry chứa SHA-256 của entry trước.

    Cho phép phát hiện log bị sửa (admin hoặc attacker edit lại log).
    """
    if not isinstance(prev_hash, (bytes, bytearray)) or len(prev_hash) != 32:
        raise ValueError("prev_hash must be exactly 32 bytes")
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    return hashlib.sha256(bytes(prev_hash) + bytes(payload)).digest()
