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

    is_encrypted = models.BooleanField(
        default=False
    )

    hash_sha256 = models.CharField(
        max_length=64,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.file_name