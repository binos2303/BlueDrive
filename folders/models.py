from django.db import models
from django.contrib.auth.models import User


class Folder(models.Model):
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    folder_name = models.CharField(
        max_length=255
    )

    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.folder_name