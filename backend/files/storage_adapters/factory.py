from django.conf import settings

from .base import StorageConfigurationError
from .s3_compatible import S3CompatibleStorageAdapter


def get_storage_adapter(*, connection=None, bucket=None):
    """Build the configured provider adapter without exposing SDK details."""
    if connection is not None:
        import os
        from infrastructure.connection_profiles import build_client
        return S3CompatibleStorageAdapter(
            endpoint_url=connection.endpoint_url, public_endpoint_url=connection.public_endpoint_url,
            bucket=bucket or connection.bucket, region=connection.region, addressing_style='path',
            access_key_id=os.environ.get(connection.access_key_env,''),
            secret_access_key=os.environ.get(connection.secret_key_env,''),
            tls_verify=True, ca_bundle=connection.ca_bundle, connect_timeout=2, read_timeout=5,
            max_attempts=2, server_side_encryption=connection.server_side_encryption,
            kms_key_id=connection.kms_key_id, client=build_client(connection), public_upload_endpoint=True,
        )
    if bucket is not None:
        raise StorageConfigurationError('Bucket overrides require a pinned connection.')
    # Các caller bỏ quên connection không được âm thầm dùng endpoint toàn cục.
    if settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED:
        raise StorageConfigurationError('A verified storage connection is required.')
    if not getattr(settings, "SECUREDRIVE_STORAGE_ENDPOINT_URL", ""):
        raise StorageConfigurationError("Object storage is not configured.")

    return S3CompatibleStorageAdapter(
        endpoint_url=settings.SECUREDRIVE_STORAGE_ENDPOINT_URL,
        public_endpoint_url=settings.SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL,
        public_upload_endpoint=bool(settings.SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL),
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
