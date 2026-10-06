from django.db import models
from django.contrib.auth.models import User
from folders.models import Folder


class File(models.Model):

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

    def __str__(self):
        return self.file_name