from django.db import models
from django.contrib.auth.models import User
from folders.models import Folder


class File(models.Model):
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    folder = models.ForeignKey(
        Folder,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    file_name = models.CharField(
        max_length=255
    )
    file_path = models.FileField(
        upload_to='uploads/'
    )

    file_size = models.BigIntegerField(
        default=0
    )
    mime_type = models.CharField(
            max_length=100,
            blank=True
    )

    is_encrypted = models.BooleanField(
        default=False
    )
     # Nonce riêng cho từng file mã hóa AES-GCM.
    # Không phải secret, nhưng bắt buộc để giải mã chính xác.
    encryption_nonce = models.BinaryField(
        null=True,
        blank=True,
        editable=False,
    )

    # Dành cho việc đổi key/thuật toán trong tương lai.
    encryption_version = models.PositiveSmallIntegerField(
        default=0,
        editable=False,
    )
    hash_sha256 = models.CharField(
        max_length=64,
        blank=True
    )
        # None: file đang hoạt động.
    # Có thời gian: file nằm trong Thùng rác và không thể download.
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )
    
    def __str__(self):
        return self.file_name