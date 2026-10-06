from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ActivityLog(models.Model):
    class Action(models.TextChoices):
        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"
        UPLOAD = "UPLOAD", "Upload"
        DOWNLOAD = "DOWNLOAD", "Download"
        VIEW = "VIEW", "View"
        COPY = "COPY", "Copy"
        CUT = "CUT", "Cut"
        MOVE = "MOVE", "Move"
        RENAME = "RENAME", "Rename"
        DELETE = "DELETE", "Move to Trash"
        RESTORE = "RESTORE", "Restore"
        PERMANENT_DELETE = "PERMANENT_DELETE", "Permanent delete"
        CREATE_FOLDER = "CREATE_FOLDER", "Create folder"
        ENCRYPT = "ENCRYPT", "Encrypt"
        DECRYPT = "DECRYPT", "Decrypt"
        SHARE = "SHARE", "Share"
        REVOKE_SHARE = "REVOKE_SHARE", "Revoke share"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    action = models.CharField(max_length=30, choices=Action.choices)
    description = models.TextField(blank=True)
    # Optional link to the resource affected by this event.
    # This lets Details show the exact last action instead of guessing
    # from the free-form description text.
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    object_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.action}"
