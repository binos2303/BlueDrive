from accounts.access import active_tenant_required as login_required, get_default_tenant
from django.shortcuts import redirect, get_object_or_404
from django.http import Http404
from django.http import JsonResponse
from django.urls import reverse
from urllib.parse import urlencode
from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone

from files.models import File
from folders.models import Folder
from sharing.models import Share
from logs.models import ActivityLog
from logs.services import log_action
from files.services import clone_encrypted_file_with_quota, unique_copy_name
from files.quota import QuotaExceeded, QuotaStateError
from cryptography.exceptions import InvalidTag
from securedrive.frontend_redirects import redirect_to_frontend


@login_required
@require_GET
def drive_items_api(request):
    """Return live Drive items for the current user and default tenant."""
    tenant = get_default_tenant(request.user)
    if tenant is None:
        raise Http404

    view = request.GET.get("view", "drive")
    if view not in {"drive", "recent", "trash", "shared"}:
        raise Http404

    folder_id = request.GET.get("folder")
    folder = None
    if folder_id and view == "drive":
        try:
            folder_id = int(folder_id)
        except (TypeError, ValueError):
            raise Http404
        folder = get_object_or_404(
            Folder,
            id=folder_id,
            owner=request.user,
            tenant=tenant,
            deleted_at__isnull=True,
        )

    if view == "trash":
        folders = Folder.objects.filter(
            owner=request.user, tenant=tenant, deleted_at__isnull=False,
        ).select_related("owner").order_by("-deleted_at", "folder_name")
        files = File.objects.filter(
            owner=request.user, tenant=tenant, deleted_at__isnull=False,
        ).select_related("owner").order_by("-deleted_at", "file_name")
        items = [_folder_item(item) for item in folders]
        items.extend(_file_item(item) for item in files)
    elif view == "recent":
        files = File.objects.filter(
            owner=request.user,
            tenant=tenant,
            deleted_at__isnull=True,
            last_accessed_at__isnull=False,
        ).select_related("owner").order_by("-last_accessed_at")[:100]
        items = [_file_item(item, modified=item.last_accessed_at) for item in files]
    elif view == "shared":
        shares = Share.objects.filter(
            receiver=request.user,
            tenant=tenant,
        ).select_related("owner", "file", "file__owner", "file__folder", "folder", "folder__owner")
        items = []
        for share in shares:
            if share.file_id:
                if share.file.deleted_at is None and (share.file.folder_id is None or share.file.folder.deleted_at is None):
                    items.append(_file_item(share.file, owner=share.owner.username))
            elif share.folder.deleted_at is None:
                items.append(_folder_item(share.folder, owner=share.owner.username))
    else:
        folders = Folder.objects.filter(
            owner=request.user,
            tenant=tenant,
            parent=folder,
            deleted_at__isnull=True,
        ).select_related("owner").order_by("folder_name")
        files = File.objects.filter(
            owner=request.user,
            tenant=tenant,
            folder=folder,
            deleted_at__isnull=True,
        ).select_related("owner").order_by("file_name")
        items = [_folder_item(item) for item in folders]
        items.extend(_file_item(item) for item in files)
    return JsonResponse({"items": items})


def _owner_initials(owner):
    parts = owner.split()
    return "".join(part[0].upper() for part in parts[:2]) or "?"


def _file_item(item, *, owner="Me", modified=None):
    return {
        "id": item.id,
        "name": item.file_name,
        "owner": owner,
        "ownerInitials": "Me" if owner == "Me" else _owner_initials(owner),
        "modified": (modified or item.updated_at).isoformat(),
        "size": item.file_size,
        "type": "image" if item.mime_type.startswith("image/") else "document",
    }


def _folder_item(item, *, owner="Me"):
    return {
        "id": -item.id,
        "folderId": item.id,
        "name": item.folder_name,
        "owner": owner,
        "ownerInitials": "Me" if owner == "Me" else _owner_initials(owner),
        "modified": item.updated_at.isoformat(),
        "size": None,
        "type": "folder",
    }


@login_required
def dashboard(request):
    return redirect_to_frontend("/drive")


@login_required
def recent(request):
    return redirect_to_frontend("/drive/recent")


@login_required
def search(request):
    query = request.GET.get("q", "").strip()[:100]
    return redirect_to_frontend("/drive", {"q": query} if query else None)

def _redirect_drive(request, folder_id=None):
    return redirect("folder_open", folder_id=folder_id) if folder_id else redirect("dashboard")


def _redirect_bulk_result(request, folder_id=None):
    source = request.POST.get("source", "drive")
    if source == "search":
        query = request.POST.get("q", "")
        return redirect(f"{reverse('search')}?{urlencode({'q': query})}") if query else redirect("dashboard")
    if source == "recent":
        return redirect("recent")
    return _redirect_drive(request, folder_id)


def _parse_ids(request, key):
    values = request.POST.getlist(key)
    ids = []
    for value in values:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in ids:
            ids.append(value)
    return ids


def _top_level_folders(folders):
    selected = {folder.id: folder for folder in folders}
    result = []
    for folder in folders:
        parent = folder.parent
        nested = False
        while parent is not None:
            if parent.id in selected:
                nested = True
                break
            parent = parent.parent
        if not nested:
            result.append(folder)
    return result


def _folder_contains_ids(source, candidate_id):
    current = candidate_id
    while current:
        if current == source.id:
            return True
        current = Folder.objects.filter(
            pk=current,
            tenant_id=source.tenant_id,
        ).values_list("parent_id", flat=True).first()
    return False


@login_required
@require_POST
def bulk_action(request):
    """Secure multi-select operations for files and folders owned by the current user."""
    action = request.POST.get("action", "").strip().lower()
    file_ids = _parse_ids(request, "file_ids")
    folder_ids = _parse_ids(request, "folder_ids")
    current_folder_id = request.POST.get("current_folder_id") or None
    tenant = get_default_tenant(request.user)
    if tenant is None:
        raise Http404

    if not file_ids and not folder_ids:
        messages.warning(request, "No items selected.")
        return _redirect_bulk_result(request, current_folder_id)

    files = list(File.objects.filter(
        id__in=file_ids,
        owner=request.user,
        tenant=tenant,
        deleted_at__isnull=True,
    ).select_related("folder"))
    folders = list(Folder.objects.filter(
        id__in=folder_ids,
        owner=request.user,
        tenant=tenant,
        deleted_at__isnull=True,
    ).select_related("parent"))

    # Never silently operate on IDs that are not owned by the current user.
    if len(files) != len(file_ids) or len(folders) != len(folder_ids):
        messages.error(request, "One or more selected items are not accessible.")
        return _redirect_bulk_result(request, current_folder_id)

    top_folders = _top_level_folders(folders)
    top_folder_ids = {folder.id for folder in top_folders}

    # A file inside a selected folder is already covered by that folder operation.
    covered_file_ids = set()
    if top_folder_ids:
        for file in files:
            if file.folder_id and any(_folder_contains_ids(folder, file.folder_id) for folder in top_folders):
                covered_file_ids.add(file.id)
    direct_files = [file for file in files if file.id not in covered_file_ids]

    if action in {"copy", "cut"}:
        request.session["clipboard"] = {
            "type": "multi_cut" if action == "cut" else "multi",
            "files": [file.id for file in direct_files],
            "folders": [folder.id for folder in top_folders],
        }
        request.session.modified = True
        log_action(request.user, ActivityLog.Action.CUT if action == "cut" else ActivityLog.Action.COPY,
                   f"{action.title()} {len(direct_files)} file(s) and {len(top_folders)} folder(s) to clipboard")
        messages.success(request, f"Selected items added to clipboard.")
        return _redirect_bulk_result(request, current_folder_id)

    if action == "trash":
        deleted_time = timezone.now()
        with transaction.atomic():
            for folder in top_folders:
                subtree = []
                stack = [folder]
                while stack:
                    current = stack.pop()
                    subtree.append(current)
                    stack.extend(Folder.objects.filter(owner=request.user, tenant=tenant, parent=current, deleted_at__isnull=True))
                ids = [item.id for item in subtree]
                Folder.objects.filter(owner=request.user, tenant=tenant, id__in=ids).update(deleted_at=deleted_time)
                File.objects.filter(owner=request.user, tenant=tenant, folder_id__in=ids, deleted_at__isnull=True).update(deleted_at=deleted_time)
            File.objects.filter(owner=request.user, tenant=tenant, id__in=[file.id for file in direct_files]).update(deleted_at=deleted_time)
        log_action(request.user, ActivityLog.Action.DELETE,
                   f"Moved {len(direct_files)} file(s) and {len(top_folders)} folder(s) to Trash")
        messages.success(request, "Selected items moved to Trash.")
        return _redirect_bulk_result(request, current_folder_id)

    if action == "move":
        destination_id = request.POST.get("destination_id") or None
        destination = None
        if destination_id:
            destination = get_object_or_404(Folder, id=destination_id, owner=request.user, tenant=tenant, deleted_at__isnull=True)

        for folder in top_folders:
            if destination and _folder_contains_ids(folder, destination.id):
                messages.error(request, "A folder cannot be moved into itself or one of its descendants.")
                return _redirect_bulk_result(request, current_folder_id)
            if Folder.objects.filter(owner=request.user, tenant=tenant, parent=destination,
                                     folder_name__iexact=folder.folder_name,
                                     deleted_at__isnull=True).exclude(id=folder.id).exists():
                messages.error(request, f'A folder named "{folder.folder_name}" already exists at the destination.')
                return _redirect_bulk_result(request, current_folder_id)
        for file in direct_files:
            if File.objects.filter(owner=request.user, tenant=tenant, folder=destination,
                                   file_name__iexact=file.file_name,
                                   deleted_at__isnull=True).exclude(id=file.id).exists():
                messages.error(request, f'A file named "{file.file_name}" already exists at the destination.')
                return _redirect_bulk_result(request, current_folder_id)

        with transaction.atomic():
            for folder in top_folders:
                folder.parent = destination
                folder.save(update_fields=["parent", "updated_at"])
            for file in direct_files:
                file.folder = destination
                file.save(update_fields=["folder", "updated_at"])
        log_action(request.user, ActivityLog.Action.MOVE,
                   f"Moved {len(direct_files)} file(s) and {len(top_folders)} folder(s)")
        messages.success(request, "Selected items moved successfully.")
        return _redirect_bulk_result(request, destination.id if destination else None)

    messages.error(request, "Unknown bulk action.")
    return _redirect_bulk_result(request, current_folder_id)


@login_required
@require_POST
def bulk_paste(request):
    """Paste a multi-item clipboard created by bulk_action."""
    clipboard = request.session.get("clipboard")
    if not clipboard:
        messages.warning(request, "Clipboard is empty.")
        return _redirect_drive(request, request.POST.get("folder_id") or None)
    if clipboard.get("type") not in {"multi", "multi_cut"}:
        from files.views import file_paste
        return file_paste(request)

    destination_id = request.POST.get("folder_id") or None
    tenant = get_default_tenant(request.user)
    if tenant is None:
        raise Http404
    destination = None
    if destination_id:
        destination = get_object_or_404(Folder, id=destination_id, owner=request.user, tenant=tenant, deleted_at__isnull=True)

    source_files = list(File.objects.filter(
        owner=request.user, tenant=tenant, id__in=clipboard.get("files", []), deleted_at__isnull=True
    ).select_related("folder"))
    source_folders = list(Folder.objects.filter(
        owner=request.user, tenant=tenant, id__in=clipboard.get("folders", []), deleted_at__isnull=True
    ).select_related("parent"))
    if len(source_files) != len(clipboard.get("files", [])) or len(source_folders) != len(clipboard.get("folders", [])):
        messages.error(request, "One or more clipboard items are no longer available.")
        request.session.pop("clipboard", None)
        return _redirect_drive(request, destination.id if destination else None)

    top_folders = _top_level_folders(source_folders)
    cut = clipboard.get("type") == "multi_cut"

    if cut:
        for folder in top_folders:
            if destination and _folder_contains_ids(folder, destination.id):
                messages.error(request, "A folder cannot be moved into itself or one of its descendants.")
                return _redirect_drive(request, destination.id)
            if Folder.objects.filter(owner=request.user, tenant=tenant, parent=destination, folder_name__iexact=folder.folder_name, deleted_at__isnull=True).exclude(id=folder.id).exists():
                messages.error(request, f'A folder named "{folder.folder_name}" already exists at the destination.')
                return _redirect_drive(request, destination.id)
        for file in source_files:
            if File.objects.filter(owner=request.user, tenant=tenant, folder=destination, file_name__iexact=file.file_name, deleted_at__isnull=True).exclude(id=file.id).exists():
                messages.error(request, f'A file named "{file.file_name}" already exists at the destination.')
                return _redirect_drive(request, destination.id)
        with transaction.atomic():
            for folder in top_folders:
                folder.parent = destination
                folder.save(update_fields=["parent", "updated_at"])
            for file in source_files:
                file.folder = destination
                file.save(update_fields=["folder", "updated_at"])
        request.session.pop("clipboard", None)
        log_action(request.user, ActivityLog.Action.MOVE, "Pasted moved multi-selection")
        messages.success(request, "Selected items moved successfully.")
        return _redirect_drive(request, destination.id if destination else None)

    try:
        created_files = []
        with transaction.atomic():
            for source in top_folders:
                root_name = source.folder_name
                if Folder.objects.filter(owner=request.user, tenant=tenant, parent=destination, folder_name__iexact=root_name, deleted_at__isnull=True).exists():
                    root_name = _unique_copy_folder_name(request.user, tenant, destination, root_name)
                folder_map = {source.id: Folder.objects.create(
                    tenant=tenant,
                    owner=request.user,
                    folder_name=root_name,
                    parent=destination,
                )}
                tree = _owned_subtree(source, request.user, tenant)
                for original in tree[1:]:
                    folder_map[original.id] = Folder.objects.create(
                        tenant=tenant,
                        owner=request.user,
                        folder_name=original.folder_name,
                        parent=folder_map[original.parent_id],
                    )
                for original in tree:
                    target = folder_map[original.id]
                    for source_file in File.objects.filter(owner=request.user, tenant=tenant, folder=original, deleted_at__isnull=True):
                        name = source_file.file_name
                        if File.objects.filter(owner=request.user, tenant=tenant, folder=target, file_name__iexact=name, deleted_at__isnull=True).exists():
                            name = unique_copy_name(File, "file_name", name, folder=target, owner=request.user)
                        created_files.append(clone_encrypted_file_with_quota(
                            source_file,
                            owner=request.user,
                            folder=target,
                            file_name=name,
                            tenant=tenant,
                        ))
            for source_file in source_files:
                name = source_file.file_name
                if File.objects.filter(owner=request.user, tenant=tenant, folder=destination, file_name__iexact=name, deleted_at__isnull=True).exists():
                    name = unique_copy_name(File, "file_name", name, folder=destination, owner=request.user)
                created_files.append(clone_encrypted_file_with_quota(
                    source_file,
                    owner=request.user,
                    folder=destination,
                    file_name=name,
                    tenant=tenant,
                ))
    except (QuotaExceeded, QuotaStateError):
        for created_file in created_files:
            if created_file.file_path:
                created_file.file_path.delete(save=False)
        messages.error(request, "The workspace or member quota does not allow this copy.")
        return _redirect_drive(request, destination.id if destination else None)
    except InvalidTag:
        for created_file in created_files:
            if created_file.file_path:
                created_file.file_path.delete(save=False)
        messages.error(request, "File integrity verification failed. Copy was cancelled.")
        return _redirect_drive(request, destination.id if destination else None)
    except Exception:
        for created_file in created_files:
            if created_file.file_path:
                created_file.file_path.delete(save=False)
        messages.error(request, "Could not paste the selected items.")
        return _redirect_drive(request, destination.id if destination else None)

    request.session.pop("clipboard", None)
    log_action(request.user, ActivityLog.Action.COPY, "Pasted copied multi-selection")
    messages.success(request, "Selected items pasted successfully.")
    return _redirect_drive(request, destination.id if destination else None)


def _owned_subtree(folder, owner, tenant):
    result = [folder]
    index = 0
    while index < len(result):
        current = result[index]
        result.extend(Folder.objects.filter(owner=owner, tenant=tenant, parent=current, deleted_at__isnull=True))
        index += 1
    return result


def _unique_copy_folder_name(owner, tenant, parent, original_name):
    candidate = f"{original_name} (copy)"
    number = 2
    while Folder.objects.filter(owner=owner, tenant=tenant, parent=parent, folder_name__iexact=candidate, deleted_at__isnull=True).exists():
        candidate = f"{original_name} (copy {number})"
        number += 1
    return candidate
