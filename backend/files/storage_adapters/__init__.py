"""Storage backends behind a provider-neutral interface."""


def get_storage_adapter():
    """Load the configured provider only when a storage operation is requested."""
    from .factory import get_storage_adapter as build_adapter

    return build_adapter()

__all__ = ["get_storage_adapter"]
