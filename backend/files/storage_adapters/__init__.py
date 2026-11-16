"""Storage backends behind a provider-neutral interface."""


def get_storage_adapter(*, connection=None, bucket=None):
    """Load the configured provider only when a storage operation is requested."""
    from .factory import get_storage_adapter as build_adapter

    if connection is None and bucket is None:
        return build_adapter()
    return build_adapter(connection=connection,bucket=bucket)

__all__ = ["get_storage_adapter"]
