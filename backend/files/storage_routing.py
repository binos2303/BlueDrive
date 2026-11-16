"""Ghim target một lần; không chọn lại binding khi đọc hoặc hoàn tất upload."""
from django.conf import settings
from django.db import transaction

from accounts.models import Tenant
from files.models import StorageConfig
from files.storage_adapters.base import StorageConfigurationError


def _check_owner(connection, tenant):
    cluster = connection.cluster
    if tenant.kind == 'business' and (cluster.kind != 'enterprise' or cluster.tenant_id != tenant.pk):
        raise StorageConfigurationError('Pinned storage ownership is unavailable.')
    if tenant.kind == 'personal' and cluster.kind != 'platform':
        raise StorageConfigurationError('Pinned storage ownership is unavailable.')


@transaction.atomic
def upload_target(tenant, workspace):
    if not settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED:
        return {}
    from infrastructure.models import PlatformStorageBinding, StorageBinding
    locked = Tenant.objects.select_for_update().get(pk=tenant.pk)
    if locked.status != 'active' or workspace.tenant_id != locked.pk:
        raise StorageConfigurationError('Storage destination is unavailable.')
    bindings = StorageBinding.objects.filter(tenant=locked,state='active').select_related('connection__cluster','storage_config')
    binding = bindings.filter(scope='workspace',workspace=workspace).first() or bindings.filter(scope='tenant').first()
    if binding is not None:
        connection = binding.connection
        config = binding.storage_config
    elif locked.kind == 'personal':
        platform = PlatformStorageBinding.objects.select_related('connection__cluster').filter(pk='primary').first()
        connection = platform.connection if platform else None
        config = None
    else:
        connection = config = None
    if connection is None or connection.state != 'ready' or connection.last_error_code or not connection.verified_at or connection.cluster.state != 'ready':
        raise StorageConfigurationError('No verified storage binding is available for new uploads.')
    _check_owner(connection,locked)
    if config is None:
        config, _ = StorageConfig.objects.get_or_create(tenant=locked,provider=connection.cluster.provider,
            defaults={'endpoint':connection.endpoint_url,'status':'active'})
    if config.status != 'active' or config.tenant_id != locked.pk:
        raise StorageConfigurationError('Storage destination is not writable.')
    return {'storage_config':config,'storage_connection':connection,'endpoint_config_version':connection.revision}


def adapter_for_upload(session, *, fallback, cleanup=False):
    if session.storage_connection_id is None:
        # Bật routing thì mọi phiên upload phải ghim revision; không đọc kho mặc định.
        if settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED:
            raise StorageConfigurationError('Upload has no verified storage connection.')
        _check_legacy_endpoint(session.storage_config if session.storage_config_id else None)
        return fallback()
    from files.storage_adapters import get_storage_adapter
    connection = session.storage_connection
    _check_owner(connection,session.tenant)
    if session.endpoint_config_version != connection.revision or session.storage_config_id is None or session.storage_config.tenant_id != session.tenant_id:
        raise StorageConfigurationError('Pinned upload storage is unavailable.')
    if not cleanup and (connection.state != 'ready' or session.storage_config.status != 'active'):
        raise StorageConfigurationError('Pinned upload storage is not writable.')
    return get_storage_adapter(connection=connection)


def adapter_for_location(location, *, fallback, cleanup=False):
    if location.storage_connection_id is None:
        # Không rơi về storage global khi cấu hình Platform đã bật định tuyến.
        if settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED:
            raise StorageConfigurationError('File has no pinned storage connection.')
        _check_legacy_endpoint(location.storage_config)
        return fallback()
    from files.storage_adapters import get_storage_adapter
    _check_owner(location.storage_connection,location.tenant)
    if not cleanup and (location.storage_connection.state == 'disabled' or location.storage_config.status == 'disabled'):
        raise StorageConfigurationError('Pinned file storage is unavailable.')
    return get_storage_adapter(connection=location.storage_connection)


def _check_legacy_endpoint(config):
    # Đổi endpoint mặc định không được chuyển ngầm việc đọc, ghi hoặc xóa dữ liệu cũ.
    if config is not None and config.endpoint and (
        config.endpoint.rstrip('/') != settings.SECUREDRIVE_STORAGE_ENDPOINT_URL.rstrip('/')
    ):
        raise StorageConfigurationError('Legacy storage requires its original connection.')
