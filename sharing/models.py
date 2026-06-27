from django.db import models
from django.contrib.auth.models import User
from files.models import File


class Share(models.Model):

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='shared_by_me'
    )

    receiver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='shared_with_me'
    )

    file = models.ForeignKey(
        File,
        on_delete=models.CASCADE
    )

    permission = models.CharField(
        max_length=20,
        default='read'
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.file.file_name}"