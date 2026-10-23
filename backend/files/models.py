import uuid

from django.db import models
from django.contrib.auth.models import User
from django.db.models.functions import Coalesce, Lower
from folders.models import Folder
from django.db.models import Q


class File(models.Model):

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="files",
    )

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.PROTECT,
        related_name="files",
    )

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="files",
    )

    folder = models.ForeignKey(
        Folder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="files",
    )

    # ==========================
    # File metadata
    # ==========================

    file_name = models.CharField(
        max_length=255,
    )

    file_path = models.FileField(
        upload_to="uploads/",
    )

    file_size = models.BigIntegerField(
        default=0,
    )

    mime_type = models.CharField(
        max_length=100,
        blank=True,
    )

    hash_sha256 = models.CharField(
        max_length=64,
        blank=True,
    )

    # ==========================
    # Encryption
    # ==========================

    is_encrypted = models.BooleanField(
        default=False,
    )

    # Nonce của AES-GCM dùng để mã hóa file
    encryption_nonce = models.BinaryField(
        null=True,
        blank=True,
        editable=False,
    )

    # DEK được mã hóa bằng KEK
    wrapped_dek = models.BinaryField(
        null=True,
        blank=True,
        editable=False,
    )

    # Nonce dùng để wrap DEK
    dek_nonce = models.BinaryField(
        null=True,
        blank=True,
        editable=False,
    )

    # Version của encryption scheme
    encryption_version = models.PositiveSmallIntegerField(
        default=1,
        editable=False,
    )

    # ==========================
    # Trash
    # ==========================

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )
    purge_after = models.DateTimeField(null=True, blank=True)

    # ==========================
    # Timestamps
    # ==========================

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    last_accessed_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                models.F("workspace"),
                Coalesce(
                    "folder",
                    models.Value(-1, output_field=models.BigIntegerField()),
                ),
                Lower("file_name"),
                condition=Q(deleted_at__isnull=True),
                name="file_live_sibling_name_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="file_tenant_id_uniq",
            ),
            models.UniqueConstraint(
                fields=["workspace", "id"],
                name="file_workspace_id_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "folder", "deleted_at"],
                name="file_tenant_folder_del_idx",
            ),
            models.Index(
                fields=["workspace", "folder", "deleted_at"],
                name="file_ws_folder_del_idx",
            ),
            models.Index(
                fields=["tenant", "owner", "deleted_at"],
                name="file_tenant_owner_del_idx",
            ),
            models.Index(
                fields=["workspace", "owner", "deleted_at"],
                name="file_ws_owner_del_idx",
            ),
            models.Index(
                fields=["tenant", "purge_after"],
                condition=Q(deleted_at__isnull=False),
                name="file_purge_after_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        # Existing callers may not provide a workspace. Infer it from the
        # destination folder, or fall back to the tenant's default workspace.
        if self.workspace_id is None and self.tenant_id:
            if self.folder_id:
                self.workspace_id = Folder.objects.filter(
                    pk=self.folder_id
                ).values_list("workspace_id", flat=True).first()
            if self.workspace_id is None:
                from accounts.models import Tenant
                from accounts.access import get_default_workspace
                tenant = Tenant.objects.get(pk=self.tenant_id)
                self.workspace_id = get_default_workspace(tenant).pk
        super().save(*args, **kwargs)

    def __str__(self):
        return self.file_name


class FileVersion(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        UPLOADING = "uploading", "Uploading"
        VERIFYING = "verifying", "Verifying"
        SCANNING = "scanning", "Scanning"
        AVAILABLE = "available", "Available"
        QUARANTINED = "quarantined", "Quarantined"
        FAILED = "failed", "Failed"
        DELETING = "deleting", "Deleting"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="file_versions",
    )
    file = models.ForeignKey(
        File,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    state = models.CharField(max_length=20, choices=State.choices)
    size_bytes = models.PositiveBigIntegerField()
    mime_type = models.CharField(max_length=100, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    is_current = models.BooleanField(default=False)
    is_encrypted = models.BooleanField(default=False)
    encryption_scheme = models.CharField(max_length=32, blank=True)
    encryption_version = models.PositiveSmallIntegerField(default=1)
    encryption_nonce = models.BinaryField(null=True, blank=True, editable=False)
    wrapped_dek = models.BinaryField(null=True, blank=True, editable=False)
    dek_nonce = models.BinaryField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    state__in=[
                        "pending",
                        "uploading",
                        "verifying",
                        "scanning",
                        "available",
                        "quarantined",
                        "failed",
                        "deleting",
                        "deleted",
                    ]
                ),
                name="file_version_state_valid_check",
            ),
            models.UniqueConstraint(
                fields=["tenant", "file", "version_number"],
                name="file_version_number_uniq",
            ),
            models.UniqueConstraint(
                fields=["file"],
                condition=Q(state="available", is_current=True),
                name="file_one_current_version_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="version_tenant_id_uniq",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gte=0),
                name="file_version_size_nonnegative_check",
            ),
            models.CheckConstraint(
                condition=Q(encryption_version__gte=1),
                name="file_version_enc_version_positive_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "file", "version_number"],
                name="version_tenant_file_num_idx",
            ),
        ]


class StorageConfig(models.Model):
    class Provider(models.TextChoices):
        LOCAL = "local", "Local filesystem"
        S3 = "s3", "S3"
        MINIO = "minio", "MinIO"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        READ_ONLY = "read_only", "Read only"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="storage_configs",
    )
    provider = models.CharField(max_length=16, choices=Provider.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    endpoint = models.URLField(max_length=512, blank=True)
    credential_ref = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "provider"],
                name="storage_tenant_provider_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="storage_tenant_id_uniq",
            ),
            models.CheckConstraint(
                condition=Q(provider__in=["local", "s3", "minio"]),
                name="storage_provider_valid_check",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "read_only", "disabled"]),
                name="storage_status_valid_check",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="storage_tenant_status_idx"),
        ]


class StorageLocation(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        AVAILABLE = "available", "Available"
        DELETE_PENDING = "delete_pending", "Delete pending"
        DELETED = "deleted", "Deleted"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="storage_locations",
    )
    file_version = models.ForeignKey(
        FileVersion,
        on_delete=models.PROTECT,
        related_name="storage_locations",
    )
    storage_config = models.ForeignKey(
        StorageConfig,
        on_delete=models.PROTECT,
        related_name="locations",
    )
    object_ref = models.CharField(max_length=512)
    state = models.CharField(max_length=20, choices=State.choices)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    checksum = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["storage_config", "object_ref"],
                name="storage_object_ref_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="location_tenant_id_uniq",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__isnull=True) | Q(size_bytes__gte=0),
                name="location_size_nonnegative_check",
            ),
            models.CheckConstraint(
                condition=Q(
                    state__in=[
                        "pending",
                        "available",
                        "delete_pending",
                        "deleted",
                        "error",
                    ]
                ),
                name="location_state_valid_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "file_version", "state"],
                name="location_tenant_version_idx",
            ),
            models.Index(
                fields=["state", "updated_at"],
                name="location_reconcile_idx",
            ),
        ]


class UploadSession(models.Model):
    class State(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        UPLOADING = "uploading", "Uploading"
        VERIFYING = "verifying", "Verifying"
        SCANNING = "scanning", "Scanning"
        AVAILABLE = "available", "Available"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="upload_sessions",
    )
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.PROTECT,
        related_name="upload_sessions",
    )
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="upload_sessions",
    )
    target_folder = models.ForeignKey(
        Folder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="upload_sessions",
    )
    file = models.ForeignKey(
        File,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="upload_sessions",
    )
    client_name = models.CharField(max_length=255)
    expected_size_bytes = models.PositiveBigIntegerField()
    expected_sha256 = models.CharField(max_length=64, blank=True)
    # Server-owned S3 multipart identity. Never returned to the browser.
    object_key = models.CharField(max_length=512, blank=True)
    final_object_key = models.CharField(max_length=512, blank=True)
    provider_upload_id = models.CharField(max_length=512, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True)
    part_manifest = models.JSONField(default=list, blank=True)
    received_bytes = models.PositiveBigIntegerField(default=0)
    actual_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.INITIATED,
    )
    failure_code = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(received_bytes__lte=models.F("expected_size_bytes")),
                name="upload_received_within_expected_check",
            ),
            models.CheckConstraint(
                condition=Q(
                    state__in=[
                        "initiated",
                        "uploading",
                        "verifying",
                        "scanning",
                        "available",
                        "completed",
                        "failed",
                        "canceled",
                        "expired",
                    ]
                ),
                name="upload_state_valid_check",
            ),
            models.UniqueConstraint(
                fields=["tenant", "id"],
                name="upload_tenant_id_uniq",
            ),
            models.UniqueConstraint(
                fields=["workspace", "id"],
                name="upload_workspace_id_uniq",
            ),
            models.UniqueConstraint(
                fields=["tenant", "initiated_by", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="upload_idempotency_key_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "state", "expires_at"],
                name="upload_tenant_state_exp_idx",
            ),
            models.Index(
                fields=["workspace", "state", "expires_at"],
                name="upload_ws_state_exp_idx",
            ),
            models.Index(
                fields=["initiated_by", "state", "created_at"],
                name="upload_user_state_created_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.workspace_id is None and self.tenant_id:
            if self.target_folder_id:
                self.workspace_id = Folder.objects.filter(
                    pk=self.target_folder_id
                ).values_list("workspace_id", flat=True).first()
            if self.workspace_id is None:
                from accounts.models import Tenant
                from accounts.access import get_default_workspace
                tenant = Tenant.objects.get(pk=self.tenant_id)
                self.workspace_id = get_default_workspace(tenant).pk
        super().save(*args, **kwargs)


class UploadFinalizationJob(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    upload_session = models.OneToOneField(UploadSession, on_delete=models.CASCADE, related_name="finalization_job")
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class QuotaReservation(models.Model):
    class State(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        CONSUMED = "consumed", "Consumed"
        RELEASED = "released", "Released"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.PROTECT,
        related_name="quota_reservations",
    )
    upload_session = models.ForeignKey(
        UploadSession,
        on_delete=models.PROTECT,
        related_name="quota_reservations",
    )
    quota_account = models.ForeignKey(
        "accounts.QuotaAccount",
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    reserved_bytes = models.PositiveBigIntegerField()
    state = models.CharField(max_length=16, choices=State.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["upload_session", "quota_account"],
                name="reservation_upload_account_uniq",
            ),
            models.CheckConstraint(
                condition=Q(state__in=["reserved", "consumed", "released"]),
                name="reservation_state_valid_check",
            ),
            models.CheckConstraint(
                condition=Q(reserved_bytes__gte=0),
                name="reservation_size_nonnegative_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["quota_account", "state"],
                name="reservation_account_state_idx",
            ),
        ]
