"""One rename policy shared by the Next.js JSON endpoint and legacy form views."""
from django.db import IntegrityError, transaction

from files.forms import FileRenameForm
from files.models import File
from folders.models import Folder
from logs.models import ActivityLog
from logs.services import log_action
from sharing.services import can_edit_file, can_edit_folder


class RenameError(Exception):
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def rename_resource(*, resource, actor, name: str) -> bool:
    """Rename metadata only, preserving object references, hashes and quota.

    Returns False for a no-op. The database constraint remains the final arbiter
    when concurrent requests rename different objects to the same name.
    """
    if not isinstance(name, str):
        raise RenameError("Name must be a string.")
    if not isinstance(resource, (File, Folder)):
        raise ValueError("Only files or folders can be renamed")

    with transaction.atomic():
        model = type(resource)
        resource = model.objects.select_for_update().filter(
            pk=resource.pk, deleted_at__isnull=True,
        ).first()
        if resource is None:
            raise RenameError("Item not found.", 404)
        allowed = can_edit_file(resource, actor) if isinstance(resource, File) else can_edit_folder(resource, actor)
        if not allowed:
            raise RenameError("You do not have permission to rename this item.", 403)

        # ModelForm.is_valid() assigns cleaned values to its instance, so capture
        # the original name before constructing/validating the form.
        previous = resource.file_name if isinstance(resource, File) else resource.folder_name
        if isinstance(resource, File):
            name = name.strip()
            if File.objects.filter(
                workspace_id=resource.workspace_id, folder_id=resource.folder_id,
                deleted_at__isnull=True, file_name__iexact=name,
            ).exclude(pk=resource.pk).exists():
                raise RenameError("An item with this name already exists in this folder.", 409)
            form = FileRenameForm({"file_name": name}, instance=resource)
            if not form.is_valid():
                messages = [message for problems in form.errors.values() for message in problems]
                raise RenameError(" ".join(messages) or "Invalid file name.")
            name = form.cleaned_data["file_name"]
            field = "file_name"
            siblings = File.objects.filter(
                workspace_id=resource.workspace_id, folder_id=resource.folder_id,
                deleted_at__isnull=True, file_name__iexact=name,
            )
        else:
            name = name.strip()
            if not name or len(name) > 255:
                raise RenameError("Folder name must be between 1 and 255 characters.")
            if name in (".", "..") or any(ch in name for ch in "/\\\x00\r\n"):
                raise RenameError("Folder name contains invalid characters.")
            field = "folder_name"
            siblings = Folder.objects.filter(
                workspace_id=resource.workspace_id, parent_id=resource.parent_id,
                deleted_at__isnull=True, folder_name__iexact=name,
            )

        if previous == name:
            return False
        if siblings.exclude(pk=resource.pk).exists():
            raise RenameError("An item with this name already exists in this folder.", 409)
        setattr(resource, field, name)
        try:
            # Isolated savepoint: an IntegrityError does not poison this outer
            # transaction and is converted to a predictable API conflict.
            with transaction.atomic():
                resource.save(update_fields=[field, "updated_at"])
        except IntegrityError as exc:
            raise RenameError("An item with this name already exists in this folder.", 409) from exc
        label = "file" if isinstance(resource, File) else "folder"
        log_action(actor, ActivityLog.Action.RENAME,
                   f"Renamed {label} from {previous} to {name}", obj=resource)
        return True
