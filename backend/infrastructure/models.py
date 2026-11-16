"""Inventory hạ tầng; các bản ghi này không thực thi thao tác trên storage."""
import ipaddress
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


STORAGE_PERMISSIONS = ('storage.view', 'storage.configure', 'storage.operate', 'storage.approve', 'storage.monitor')
ACTIVE_OPERATION_STATES = ['validating', 'approved', 'running', 'verifying', 'needs_attention']
STORAGE_ALERT_CODES = ['collector_unavailable','telemetry_stale','read_quorum_lost','write_quorum_lost','disk_failures','nodes_unavailable','capacity_warning','capacity_critical']


class StorageAccessGrant(models.Model):
    membership = models.ForeignKey('accounts.Membership', on_delete=models.PROTECT, related_name='storage_grants')
    permission = models.CharField(max_length=32, choices=[(value, value) for value in STORAGE_PERMISSIONS])
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['membership', 'permission'], name='scc_grant_member_perm_uniq'),
            models.CheckConstraint(condition=Q(permission__in=STORAGE_PERMISSIONS), name='scc_grant_permission_valid'),
        ]


class StorageCluster(models.Model):
    class Kind(models.TextChoices):
        PLATFORM = 'platform', 'Platform'
        ENTERPRISE = 'enterprise', 'Organization'

    class State(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        UNVERIFIED = 'unverified', 'Unverified'
        READY = 'ready', 'Verified connection'
        RETIRED = 'retired', 'Retired inventory'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Platform là chủ quản cố định; không mượn tenant cá nhân của một admin.
    kind = models.CharField(max_length=16, choices=Kind.choices)
    tenant = models.ForeignKey('accounts.Tenant', on_delete=models.PROTECT, null=True, blank=True, related_name='storage_clusters')
    display_name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100)
    provider = models.CharField(max_length=16, choices=[('s3', 'SeaweedFS (S3 API)')], default='s3')
    edition = models.CharField(max_length=80, blank=True)
    provider_version = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    verified_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind='platform', tenant__isnull=True) | Q(kind='enterprise', tenant__isnull=False), name='scc_cluster_owner_valid'),
            models.CheckConstraint(condition=Q(provider='s3'), name='scc_cluster_provider_valid'),
            models.CheckConstraint(condition=Q(state__in=['draft', 'unverified', 'ready', 'retired']), name='scc_cluster_state_valid'),
            models.CheckConstraint(condition=~Q(state='ready') | Q(verified_at__isnull=False), name='scc_cluster_ready_verified'),
            models.UniqueConstraint(fields=['kind', 'slug'], condition=Q(kind='platform'), name='scc_platform_cluster_slug_uniq'),
            models.UniqueConstraint(fields=['tenant', 'slug'], condition=Q(kind='enterprise'), name='scc_org_cluster_slug_uniq'),
        ]
        ordering = ['display_name', 'id']

    def clean(self):
        super().clean()
        if self.kind == self.Kind.ENTERPRISE and self.tenant_id and self.tenant.kind != 'business':
            raise ValidationError({'tenant': 'Organization storage requires a business tenant.'})


class ServerPool(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(StorageCluster, on_delete=models.PROTECT, related_name='pools')
    name = models.CharField(max_length=200)
    generation = models.PositiveBigIntegerField(default=1)
    desired_status = models.CharField(max_length=16, choices=[('registered', 'Registered'), ('retired', 'Retired')], default='registered')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cluster', 'name'], name='scc_pool_name_uniq'),
            models.UniqueConstraint(fields=['cluster', 'id'], name='scc_pool_cluster_id_uniq'),
            models.CheckConstraint(condition=Q(desired_status__in=['registered', 'retired']), name='scc_pool_state_valid'),
        ]
        ordering = ['name', 'id']


def validate_private_ips(value):
    if not isinstance(value, list) or len(value) > 16:
        raise ValidationError('Provide at most 16 IP addresses.')
    try:
        for address in value:
            if not isinstance(address, str):
                raise ValueError
            ipaddress.ip_address(address)
    except ValueError:
        raise ValidationError('Invalid IP address.') from None


class StorageNode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(StorageCluster, on_delete=models.PROTECT, related_name='nodes')
    pool = models.ForeignKey(ServerPool, on_delete=models.PROTECT, related_name='nodes', null=True, blank=True)
    agent_identity = models.UUIDField(null=True, blank=True, unique=True)
    hostname = models.CharField(max_length=253)
    private_ips = models.JSONField(default=list, validators=[validate_private_ips], blank=True)
    labels = models.JSONField(default=dict, blank=True)
    inventory_status = models.CharField(max_length=16, choices=[('registered', 'Registered'), ('retired', 'Retired')], default='registered')
    last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cluster', 'hostname'], name='scc_node_hostname_uniq'),
            models.CheckConstraint(condition=Q(inventory_status__in=['registered', 'retired']), name='scc_node_state_valid'),
        ]
        ordering = ['hostname', 'id']

    def clean(self):
        super().clean()
        if self.pool_id and self.pool.cluster_id != self.cluster_id:
            raise ValidationError({'pool': 'Pool must belong to the node cluster.'})
        if not isinstance(self.labels, dict) or len(self.labels) > 32 or any(
            not isinstance(key, str) or len(key) > 64 or not isinstance(value, str) or len(value) > 200
            for key, value in self.labels.items()
        ):
            raise ValidationError({'labels': 'Provide up to 32 short text labels.'})


class NodeDisk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey(StorageNode, on_delete=models.PROTECT, related_name='disks')
    stable_disk_id = models.CharField(max_length=255)
    mount_path = models.CharField(max_length=1024)
    capacity_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=[('unknown', 'Unknown'), ('retired', 'Retired inventory')], default='unknown')
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['node', 'stable_disk_id'], name='scc_disk_stable_id_uniq'),
            models.CheckConstraint(condition=Q(state__in=['unknown', 'retired']), name='scc_disk_state_valid'),
        ]
        ordering = ['stable_disk_id', 'id']


class StorageBinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('accounts.Tenant', on_delete=models.PROTECT, related_name='storage_bindings')
    scope = models.CharField(max_length=16, choices=[('tenant', 'Tenant'), ('workspace', 'Workspace')])
    workspace = models.ForeignKey('accounts.Workspace', on_delete=models.PROTECT, null=True, blank=True, related_name='storage_bindings')
    cluster = models.ForeignKey(StorageCluster, on_delete=models.PROTECT, related_name='bindings')
    storage_config = models.ForeignKey('files.StorageConfig', on_delete=models.PROTECT, related_name='bindings')
    connection = models.ForeignKey('StorageConnectionRevision', on_delete=models.PROTECT, null=True, blank=True, related_name='organization_bindings')
    state = models.CharField(max_length=16, choices=[('draft', 'Draft'), ('active', 'Active'), ('retired', 'Retired')], default='draft')
    active_since = models.DateTimeField(null=True, blank=True)
    generation = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(scope='tenant', workspace__isnull=True) | Q(scope='workspace', workspace__isnull=False), name='scc_binding_scope_valid'),
            models.CheckConstraint(condition=Q(state__in=['draft', 'active', 'retired']), name='scc_binding_state_valid'),
            models.CheckConstraint(condition=~Q(state='active') | Q(active_since__isnull=False), name='scc_binding_active_since'),
            models.UniqueConstraint(fields=['tenant'], condition=Q(state='active', scope='tenant'), name='scc_active_tenant_binding_uniq'),
            models.UniqueConstraint(fields=['workspace'], condition=Q(state='active', scope='workspace'), name='scc_active_workspace_bind_uniq'),
        ]

    def clean(self):
        super().clean()
        if self.workspace_id and self.workspace.tenant_id != self.tenant_id:
            raise ValidationError({'workspace': 'Workspace must belong to the binding tenant.'})
        if self.storage_config_id and self.storage_config.tenant_id != self.tenant_id:
            raise ValidationError({'storage_config': 'Storage configuration must belong to the binding tenant.'})
        if self.cluster_id and self.tenant_id:
            if self.tenant.kind == 'business' and (self.cluster.kind != 'enterprise' or self.cluster.tenant_id != self.tenant_id):
                raise ValidationError({'cluster': 'Organization storage must belong to the same organization.'})
            if self.tenant.kind == 'personal' and self.cluster.kind != 'platform':
                raise ValidationError({'cluster': 'Personal storage requires Platform infrastructure.'})
            if self.state == 'active' and (self.cluster.state != 'ready' or self.cluster.verified_at is None or not self.storage_config_id or self.storage_config.status != 'active'):
                raise ValidationError({'state': 'Active binding requires a verified cluster and active configuration.'})


class TopologyLayout(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(StorageCluster, on_delete=models.PROTECT, related_name='layouts')
    owner_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    revision = models.PositiveBigIntegerField(default=0)
    positions = models.JSONField(default=dict, blank=True)
    viewport = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cluster', 'owner_user'], condition=Q(owner_user__isnull=False), name='scc_user_layout_uniq'),
            models.UniqueConstraint(fields=['cluster'], condition=Q(owner_user__isnull=True), name='scc_shared_layout_uniq'),
        ]


class ClusterOperationJob(models.Model):
    STATES = ['draft', 'validating', 'ready', 'awaiting_approval', 'approved', 'running', 'verifying', 'succeeded', 'failed', 'needs_attention', 'canceled', 'expired']
    ACTIVE_STATES = ACTIVE_OPERATION_STATES
    KINDS = ['verify_connection', 'deploy', 'maintenance', 'replace_node', 'expand_pool', 'decommission_pool']
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(StorageCluster, on_delete=models.PROTECT, related_name='operations')
    kind = models.CharField(max_length=32, choices=[(value, value) for value in KINDS])
    state = models.CharField(max_length=24, choices=[(value, value) for value in STATES], default='draft')
    idempotency_key = models.CharField(max_length=128, default=uuid.uuid4)
    plan_hash = models.CharField(max_length=64, blank=True)
    # S1 chỉ lưu kế hoạch; cấm ghi job thực thi cho đến gate provisioning.
    dry_run = models.BooleanField(default=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    expires_at = models.DateTimeField(null=True, blank=True)
    lease_version = models.PositiveBigIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cluster', 'kind', 'idempotency_key'], name='scc_operation_idempotency_uniq'),
            models.UniqueConstraint(fields=['cluster'], condition=Q(state__in=ACTIVE_OPERATION_STATES), name='scc_one_active_operation'),
            models.CheckConstraint(condition=Q(kind__in=['verify_connection', 'deploy', 'maintenance', 'replace_node', 'expand_pool', 'decommission_pool']), name='scc_operation_kind_valid'),
            models.CheckConstraint(condition=Q(state__in=['draft', 'validating', 'ready', 'awaiting_approval', 'approved', 'running', 'verifying', 'succeeded', 'failed', 'needs_attention', 'canceled', 'expired']), name='scc_operation_state_valid'),
            models.CheckConstraint(condition=Q(dry_run=True), name='scc_s1_operation_dry_run_only'),
            models.CheckConstraint(condition=Q(state='draft') | Q(plan_hash__regex=r'^[0-9a-f]{64}$'), name='scc_operation_plan_required'),
        ]
        ordering = ['-created_at', '-id']


class ClusterAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Quyền storage có audit theo tenant ngay cả khi chưa đăng ký cluster nào.
    cluster = models.ForeignKey(StorageCluster, on_delete=models.PROTECT, related_name='audit_events', null=True, blank=True)
    tenant = models.ForeignKey('accounts.Tenant', on_delete=models.PROTECT, related_name='storage_audit_events', null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=80)
    resource_ref = models.CharField(max_length=100, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.CheckConstraint(condition=Q(cluster__isnull=False, tenant__isnull=True) | Q(cluster__isnull=True, tenant__isnull=False), name='scc_audit_owner_valid'),
        ]
        indexes = [models.Index(fields=['tenant', '-created_at'], name='scc_access_audit_time_idx')]


class StorageConnectionRevision(models.Model):
    """Đích bất biến; chỉ lưu tên secret có phiên bản, không lưu giá trị secret."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(StorageCluster, on_delete=models.PROTECT, related_name='connections')
    revision = models.PositiveBigIntegerField()
    profile_id = models.CharField(max_length=100)
    request_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    request_digest = models.CharField(max_length=64)
    profile_digest = models.CharField(max_length=64)
    endpoint_url = models.URLField(max_length=512)
    public_endpoint_url = models.URLField(max_length=512)
    bucket = models.CharField(max_length=63)
    region = models.CharField(max_length=64, default='us-east-1')
    access_key_env = models.CharField(max_length=128)
    secret_key_env = models.CharField(max_length=128)
    allowed_networks = models.JSONField(default=list)
    resolved_ips = models.JSONField(default=list)
    ca_bundle = models.CharField(max_length=1024, blank=True)
    server_side_encryption = models.CharField(max_length=16, blank=True)
    kms_key_id = models.CharField(max_length=255, blank=True)
    lab = models.BooleanField(default=False)
    state = models.CharField(max_length=20, default='draft', choices=[(value,value) for value in ('draft','verifying','read_verified','ready','failed','disabled')])
    verification_generation = models.PositiveBigIntegerField(default=0)
    verification_started_at = models.DateTimeField(null=True, blank=True)
    read_verified_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-revision','id']
        constraints = [
            models.UniqueConstraint(fields=['cluster','revision'], name='scc_connection_revision_uniq'),
            models.CheckConstraint(condition=Q(revision__gte=1), name='scc_connection_revision_positive'),
            models.CheckConstraint(condition=Q(state__in=['draft','verifying','read_verified','ready','failed','disabled']), name='scc_connection_state_valid'),
            models.CheckConstraint(condition=~Q(state='ready') | Q(verified_at__isnull=False), name='scc_connection_ready_verified'),
            models.CheckConstraint(condition=~Q(state__in=['read_verified','ready']) | Q(read_verified_at__isnull=False), name='scc_connection_read_verified'),
        ]


class StorageConnectionProbe(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(StorageConnectionRevision, on_delete=models.PROTECT, related_name='probes')
    generation = models.PositiveBigIntegerField()
    cleanup_generation = models.PositiveBigIntegerField(default=0)
    state = models.CharField(max_length=24, choices=[(value,value) for value in ('creating','awaiting_browser','cleaning','cleanup_pending','succeeded','failed','expired')], default='creating')
    mode = models.CharField(max_length=12, choices=[('lab','LAB provisioning'),('runtime','Application runtime')], default='lab')
    bucket = models.CharField(max_length=63)
    object_key = models.CharField(max_length=512)
    object_version_id = models.CharField(max_length=1024, blank=True)
    expected_sha256 = models.CharField(max_length=64)
    browser_origin = models.URLField(max_length=512)
    bucket_created = models.BooleanField(default=False)
    checks = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(mode__in=['lab','runtime']), name='scc_probe_mode_valid'),
            models.UniqueConstraint(fields=['bucket'], condition=Q(mode='lab'), name='scc_lab_probe_bucket_uniq'),
            models.UniqueConstraint(fields=['connection'], condition=Q(state__in=['creating','awaiting_browser','cleaning','cleanup_pending']), name='scc_one_pending_probe'),
            models.CheckConstraint(condition=Q(state__in=['creating','awaiting_browser','cleaning','cleanup_pending','succeeded','failed','expired']), name='scc_probe_state_valid'),
        ]


class PlatformStorageBinding(models.Model):
    key = models.CharField(max_length=16, primary_key=True, default='primary', editable=False)
    connection = models.ForeignKey(StorageConnectionRevision, on_delete=models.PROTECT, related_name='platform_bindings')
    generation = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(key='primary'), name='scc_platform_binding_primary')]


class StorageTelemetrySnapshot(models.Model):
    """Chỉ một summary hiện tại; raw time-series thuộc TSDB bên ngoài."""
    cluster = models.OneToOneField(StorageCluster,on_delete=models.PROTECT,primary_key=True,related_name='telemetry_snapshot')
    profile_id = models.CharField(max_length=100,blank=True)
    profile_revision = models.PositiveBigIntegerField(default=0)
    profile_fingerprint = models.CharField(max_length=64,blank=True)
    source_profile_id = models.CharField(max_length=100,blank=True)
    generation = models.PositiveBigIntegerField(default=0)
    revision = models.PositiveBigIntegerField(default=0)
    stale_after_seconds = models.PositiveIntegerField(default=90)
    observed_at = models.DateTimeField(null=True,blank=True)
    last_success_at = models.DateTimeField(null=True,blank=True)
    last_attempted_at = models.DateTimeField(null=True,blank=True)
    last_error_code = models.CharField(max_length=64,blank=True)
    payload = models.JSONField(default=dict,blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(stale_after_seconds__gte=45,stale_after_seconds__lte=900),name='scc_telemetry_freshness_bounds')]


class StorageAlert(models.Model):
    CODES = STORAGE_ALERT_CODES
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    cluster = models.ForeignKey(StorageCluster,on_delete=models.PROTECT,related_name='storage_alerts')
    code = models.CharField(max_length=40,choices=[(value,value) for value in CODES])
    severity = models.CharField(max_length=16,choices=[('warning','Warning'),('critical','Critical')])
    revision = models.PositiveBigIntegerField(default=1)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True,blank=True)
    acknowledged_at = models.DateTimeField(null=True,blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='+')

    class Meta:
        ordering = ['-first_seen_at','id']
        constraints = [
            models.UniqueConstraint(fields=['cluster','code'],condition=Q(resolved_at__isnull=True),name='scc_active_alert_dedupe'),
            models.CheckConstraint(condition=Q(code__in=STORAGE_ALERT_CODES),name='scc_alert_code_valid'),
            models.CheckConstraint(condition=Q(severity__in=['warning','critical']),name='scc_alert_severity_valid'),
        ]
