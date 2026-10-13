from django.conf import settings

from .base import StorageConfigurationError
from .s3_compatible import S3CompatibleStorageAdapter


def get_storage_adapter():
    """Build the configured provider adapter without exposing SDK details."""
    if not getattr(settings, "SECUREDRIVE_STORAGE_ENDPOINT_URL", ""):
        raise StorageConfigurationError("Object storage is not configured.")

    return S3CompatibleStorageAdapter(
        endpoint_url=settings.SECUREDRIVE_STORAGE_ENDPOINT_URL,
        bucket=settings.SECUREDRIVE_STORAGE_BUCKET,
        region=settings.SECUREDRIVE_STORAGE_REGION,
        addressing_style=settings.SECUREDRIVE_STORAGE_ADDRESSING_STYLE,
        access_key_id=settings.SECUREDRIVE_STORAGE_ACCESS_KEY_ID,
        secret_access_key=settings.SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY,
        tls_verify=settings.SECUREDRIVE_STORAGE_TLS_VERIFY,
        ca_bundle=settings.SECUREDRIVE_STORAGE_CA_BUNDLE,
        connect_timeout=settings.SECUREDRIVE_STORAGE_CONNECT_TIMEOUT,
        read_timeout=settings.SECUREDRIVE_STORAGE_READ_TIMEOUT,
        max_attempts=settings.SECUREDRIVE_STORAGE_MAX_ATTEMPTS,
        retry_base_seconds=settings.SECUREDRIVE_STORAGE_RETRY_BASE_SECONDS,
        retry_max_seconds=settings.SECUREDRIVE_STORAGE_RETRY_MAX_SECONDS,
        max_presigned_url_seconds=settings.SECUREDRIVE_STORAGE_PRESIGN_MAX_SECONDS,
        server_side_encryption=settings.SECUREDRIVE_STORAGE_SSE,
        kms_key_id=settings.SECUREDRIVE_STORAGE_KMS_KEY_ID,
    )
