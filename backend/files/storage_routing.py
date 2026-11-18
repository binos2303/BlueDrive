"""Ghim target một lần; không chọn lại binding khi đọc hoặc hoàn tất upload."""
from django.conf import settings
from django.db import transaction

from accounts.models import Tenant
from files.models import StorageConfig
from files.storage_adapters.base import StorageConfigurationError


class OrganizationStorageRequired(StorageConfigurationError):
    code = 'organization_storage_unavailable'


class StorageBindingUnavailable(StorageConfigurationError):
    code = 'storage_binding_unavailable'


class StorageScopeMismatch(StorageConfigurationError):
    code = 'storage_scope_mismatch'


def requires_organization_storage(tenant):
    """Ownership bền vững, không vai trò người upload, xác định kho Enterprise."""
    if tenant.kind != Tenant.Kind.BUSINESS:
        return False
    return bool(tenant.provisioning_key) or tenant.organization_identities.exists()


def require_legacy_destination(tenant):
    """Đường legacy không biết binding nên không được ghi dữ liệu Organization."""
    if requires_organization_storage(tenant):
        raise OrganizationStorageRequired('Organization uploads require a verified storage connection.')


def _check_owner(connection, tenant):
    cluster = connection.cluster
    if tenant.kind == 'business' and (cluster.kind != 'enterprise' or cluster.tenant_id != tenant.pk):
        raise StorageScopeMismatch('Pinned storage ownership is unavailable.')
    if tenant.kind == 'personal' and cluster.kind != 'platform':
        raise StorageScopeMismatch('Pinned storage ownership is unavailable.')


@transaction.atomic
def upload_target(tenant, workspace):
    if workspace.tenant_id != tenant.pk:
        raise StorageScopeMismatch('Storage destination is unavailable.')
    if not settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED:
        require_legacy_destination(tenant)
        return {}
    from infrastructure.models import PlatformStorageBinding, StorageBinding
    locked = Tenant.objects.select_for_update().get(pk=tenant.pk)
    if locked.status != 'active' or workspace.tenant_id != locked.pk:
        raise StorageScopeMismatch('Storage destination is unavailable.')
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
        raise StorageBindingUnavailable('No verified storage binding is available for new uploads.')
    _check_owner(connection,locked)
    if config is None:
        config, _ = StorageConfig.objects.get_or_create(tenant=locked,provider=connection.cluster.provider,
            defaults={'endpoint':connection.endpoint_url,'status':'active'})
    if config.status != 'active' or config.tenant_id != locked.pk:
        raise StorageBindingUnavailable('Storage destination is not writable.')
    return {'storage_config':config,'storage_connection':connection,'endpoint_config_version':connection.revision}


def validate_upload_storage(session, *, cleanup=False, lock=False):
    """Đối chiếu revision đã ghim. Publication khóa các hàng cấu hình trước commit."""
    connection = None
    if session.storage_connection_id is not None:
        if lock:
            from infrastructure.models import StorageConnectionRevision
            connection = StorageConnectionRevision.objects.select_for_update(
                of=('self',), no_key=True,
            ).select_related('cluster').get(pk=session.storage_connection_id)
            session.storage_connection = connection
        else:
            connection = session.storage_connection
        _check_owner(connection, session.tenant)
    config = session.storage_config if session.storage_config_id else None
    if lock and config is not None:
        config = StorageConfig.objects.select_for_update(no_key=True).get(pk=config.pk)
        session.storage_config = config
    if connection is None:
        # Bật routing thì mọi phiên upload phải ghim revision; không đọc kho mặc định.
        if settings.SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED:
            raise StorageConfigurationError('Upload has no verified storage connection.')
        if not cleanup and getattr(session, 'tenant', None) is not None:
            require_legacy_destination(session.tenant)
        _check_legacy_endpoint(config)
        return None
    if session.endpoint_config_version != connection.revision or config is None or config.tenant_id != session.tenant_id:
        raise StorageConfigurationError('Pinned upload storage is unavailable.')
    if not cleanup and (connection.state != 'ready' or config.status != 'active'):
        raise StorageConfigurationError('Pinned upload storage is not writable.')
    return connection


def adapter_for_upload(session, *, fallback, cleanup=False):
    connection = validate_upload_storage(session, cleanup=cleanup)
    if connection is None:
        return fallback()
    from files.storage_adapters import get_storage_adapter
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
