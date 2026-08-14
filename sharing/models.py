from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q

from files.models import File
from folders.models import Folder


class Share(models.Model):

    class Permission(models.TextChoices):
        READ = "read", "View details"
        DOWNLOAD = "download", "Download"

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="shared_by_me",
    )

    receiver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="shared_with_me",
    )

    # Một Share chỉ áp dụng cho file hoặc folder.
    # Cho phép null để hỗ trợ cả hai loại.
    file = models.ForeignKey(
        File,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    folder = models.ForeignKey(
        Folder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    permission = models.CharField(
        max_length=20,
        choices=Permission.choices,
        default=Permission.READ,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            # Không cho phép record không có đối tượng hoặc có cả file và folder.
            models.CheckConstraint(
                check=(
                    Q(file__isnull=False, folder__isnull=True)
                    | Q(file__isnull=True, folder__isnull=False)
                ),
                name="share_requires_exactly_one_item",
            ),

            # Một người nhận chỉ có một quyền trên một file.
            models.UniqueConstraint(
                fields=["file", "receiver"],
                name="unique_file_receiver_share",
            ),

            # Một người nhận chỉ có một quyền trên một folder.
            models.UniqueConstraint(
                fields=["folder", "receiver"],
                name="unique_folder_receiver_share",
            ),
        ]

    @property
    def shared_item(self):
        """Trả về file hoặc folder được chia sẻ."""
        return self.file or self.folder

    @property
    def item_type(self):
        return "file" if self.file_id else "folder"

    def __str__(self):
        return (
            f"{self.shared_item} -> {self.receiver.username}"
        )