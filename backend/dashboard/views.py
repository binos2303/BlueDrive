from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from urllib.parse import urlencode
from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone

from django.db.models import Prefetch
from django.contrib.contenttypes.models import ContentType

from files.models import File
from folders.models import Folder
from sharing.models import Share
from logs.models import ActivityLog
from logs.services import log_action
from files.services import clone_encrypted_file, unique_copy_name
from cryptography.exceptions import InvalidTag


SORT_OPTIONS = {
    "name": {"label": "Name", "folder": "folder_name", "file": "file_name"},
    "modified": {"label": "Modified", "folder": "updated_at", "file": "updated_at"},
    "size": {"label": "Size", "folder": "folder_name", "file": "file_size"},
    "type": {"label": "Type", "folder": "folder_name", "file": "mime_type"},
}


def _sort_drive_queryset(queryset, resource_type, sort_key, direction):
    option = SORT_OPTIONS.get(sort_key, SORT_OPTIONS["name"])
    field = option[resource_type]
    prefix = "-" if direction == "desc" else ""
    return queryset.order_by(f"{prefix}{field}", "folder_name" if resource_type == "folder" else "file_name")


def _sort_context(request):
    sort_key = request.GET.get("sort", "name")
    if sort_key not in SORT_OPTIONS:
        sort_key = "name"
    direction = request.GET.get("direction", "asc")
    if direction not in {"asc", "desc"}:
        direction = "asc"
    return {
        "sort_key": sort_key,
        "sort_direction": direction,
        "sort_options": SORT_OPTIONS,
    }

@login_required
def dashboard(request):

    # Các share do user hiện tại tạo
    my_shares = Share.objects.filter(
        owner=request.user
    ).select_related(
        "receiver"
    )

    folders = Folder.objects.filter(
        owner=request.user,
        parent__isnull=True,
        deleted_at__isnull=True
    ).prefetch_related(
        Prefetch(
            "share_set",
            queryset=my_shares,
            to_attr="my_shares"
        )
    )
    sort = _sort_context(request)
    folders = _sort_drive_queryset(folders, "folder", sort["sort_key"], sort["sort_direction"])

    files = File.objects.filter(
        owner=request.user,
        deleted_at__isnull=True,
        folder__isnull=True
    ).prefetch_related(
        Prefetch(
            "share_set",
            queryset=my_shares,
            to_attr="my_shares"
        )
    )
    files = _sort_drive_queryset(files, "file", sort["sort_key"], sort["sort_direction"])

    all_folders = Folder.objects.filter(
        owner=request.user,
        deleted_at__isnull=True
    ).order_by("folder_name")

    return render(
        request,
        "drive/index.html",
        {
            "folders": folders,
            "files": files,
            "all_folders": all_folders,
            "current_folder": None,
            "breadcrumbs": [],
            "is_shared_access": False,
            **sort,
        }
    )


@login_required
def recent(request):
    """Show the owner's recently accessed live files and folders."""
    recent_files = File.objects.filter(
        owner=request.user,
        deleted_at__isnull=True,
        last_accessed_at__isnull=False,
    ).select_related("folder").order_by("-last_accessed_at")[:50]

    recent_folders = list(Folder.objects.filter(
        owner=request.user,
        deleted_at__isnull=True,
        last_accessed_at__isnull=False,
    ).select_related("parent").order_by("-last_accessed_at")[:50])
    recent_files = list(recent_files)

    file_ct = ContentType.objects.get_for_model(File)
    folder_ct = ContentType.objects.get_for_model(Folder)
    resource_ids = [item.id for item in recent_files + recent_folders]
    activities = (
        ActivityLog.objects
        .filter(
            content_type__in=[file_ct, folder_ct],
            object_id__in=resource_ids,
        )
        .select_related("user")
        .order_by("-created_at")
    )
    activity_map = {}
    for activity in activities:
        key = (activity.content_type_id, activity.object_id)
        activity_map.setdefault(key, activity)

    for item in recent_files:
        activity = activity_map.get((file_ct.id, item.id))
        item.recent_action = activity.get_action_display() if activity else "Opened"
    for item in recent_folders:
        activity = activity_map.get((folder_ct.id, item.id))
        item.recent_action = activity.get_action_display() if activity else "Opened"

    return render(
        request,
        "recent/index.html",
        {
            "recent_files": recent_files,
            "recent_folders": recent_folders,
            "all_folders": Folder.objects.filter(owner=request.user, deleted_at__isnull=True).order_by("folder_name"),
            "is_shared_access": False,
        },
    )

@login_required
def search(request):
    """
    Search the owner's files and folders, including soft-deleted items.

    Trash items remain searchable until permanent deletion. The template
    marks them as In Trash and routes the user to the appropriate Trash view.
    """
    query = request.GET.get("q", "").strip()[:100]

    if not query:
        return redirect("dashboard")

    sort = _sort_context(request)
    files = File.objects.filter(
        owner=request.user,
        file_name__icontains=query,
    ).select_related("folder")
    files = _sort_drive_queryset(files, "file", sort["sort_key"], sort["sort_direction"])[:50]

    folders = Folder.objects.filter(
        owner=request.user,
        folder_name__icontains=query,
    )
    folders = _sort_drive_queryset(folders, "folder", sort["sort_key"], sort["sort_direction"])[:50]

    return render(
        request,
        "search/index.html",
        {
            "query": query,
            "files": files,
            "folders": folders,
            "all_folders": Folder.objects.filter(owner=request.user, deleted_at__isnull=True).order_by("folder_name"),
            "is_shared_access": False,
            **sort,
        },
    )


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
        current = Folder.objects.filter(pk=current).values_list("parent_id", flat=True).first()
    return False


@login_required
@require_POST
def bulk_action(request):
    """Secure multi-select operations for files and folders owned by the current user."""
    action = request.POST.get("action", "").strip().lower()
    file_ids = _parse_ids(request, "file_ids")
    folder_ids = _parse_ids(request, "folder_ids")
    current_folder_id = request.POST.get("current_folder_id") or None

    if not file_ids and not folder_ids:
        messages.warning(request, "No items selected.")
        return _redirect_bulk_result(request, current_folder_id)

    files = list(File.objects.filter(
        id__in=file_ids,
        owner=request.user,
        deleted_at__isnull=True,
    ).select_related("folder"))
    folders = list(Folder.objects.filter(
        id__in=folder_ids,
        owner=request.user,
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
                    stack.extend(Folder.objects.filter(owner=request.user, parent=current, deleted_at__isnull=True))
                ids = [item.id for item in subtree]
                Folder.objects.filter(owner=request.user, id__in=ids).update(deleted_at=deleted_time)
                File.objects.filter(owner=request.user, folder_id__in=ids, deleted_at__isnull=True).update(deleted_at=deleted_time)
            File.objects.filter(owner=request.user, id__in=[file.id for file in direct_files]).update(deleted_at=deleted_time)
        log_action(request.user, ActivityLog.Action.DELETE,
                   f"Moved {len(direct_files)} file(s) and {len(top_folders)} folder(s) to Trash")
        messages.success(request, "Selected items moved to Trash.")
        return _redirect_bulk_result(request, current_folder_id)

    if action == "move":
        destination_id = request.POST.get("destination_id") or None
        destination = None
        if destination_id:
            destination = get_object_or_404(Folder, id=destination_id, owner=request.user, deleted_at__isnull=True)

        for folder in top_folders:
            if destination and _folder_contains_ids(folder, destination.id):
                messages.error(request, "A folder cannot be moved into itself or one of its descendants.")
                return _redirect_bulk_result(request, current_folder_id)
            if Folder.objects.filter(owner=request.user, parent=destination,
                                     folder_name__iexact=folder.folder_name,
                                     deleted_at__isnull=True).exclude(id=folder.id).exists():
                messages.error(request, f'A folder named "{folder.folder_name}" already exists at the destination.')
                return _redirect_bulk_result(request, current_folder_id)
        for file in direct_files:
            if File.objects.filter(owner=request.user, folder=destination,
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
    destination = None
    if destination_id:
        destination = get_object_or_404(Folder, id=destination_id, owner=request.user, deleted_at__isnull=True)

    source_files = list(File.objects.filter(
        owner=request.user, id__in=clipboard.get("files", []), deleted_at__isnull=True
    ).select_related("folder"))
    source_folders = list(Folder.objects.filter(
        owner=request.user, id__in=clipboard.get("folders", []), deleted_at__isnull=True
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
            if Folder.objects.filter(owner=request.user, parent=destination, folder_name__iexact=folder.folder_name, deleted_at__isnull=True).exclude(id=folder.id).exists():
                messages.error(request, f'A folder named "{folder.folder_name}" already exists at the destination.')
                return _redirect_drive(request, destination.id)
        for file in source_files:
            if File.objects.filter(owner=request.user, folder=destination, file_name__iexact=file.file_name, deleted_at__isnull=True).exclude(id=file.id).exists():
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
        with transaction.atomic():
            for source in top_folders:
                root_name = source.folder_name
                if Folder.objects.filter(owner=request.user, parent=destination, folder_name__iexact=root_name, deleted_at__isnull=True).exists():
                    root_name = _unique_copy_folder_name(request.user, destination, root_name)
                folder_map = {source.id: Folder.objects.create(owner=request.user, folder_name=root_name, parent=destination)}
                tree = _owned_subtree(source, request.user)
                for original in tree[1:]:
                    folder_map[original.id] = Folder.objects.create(owner=request.user, folder_name=original.folder_name, parent=folder_map[original.parent_id])
                for original in tree:
                    target = folder_map[original.id]
                    for source_file in File.objects.filter(owner=request.user, folder=original, deleted_at__isnull=True):
                        name = source_file.file_name
                        if File.objects.filter(owner=request.user, folder=target, file_name__iexact=name, deleted_at__isnull=True).exists():
                            name = unique_copy_name(File, "file_name", name, folder=target, owner=request.user)
                        clone_encrypted_file(source_file, owner=request.user, folder=target, file_name=name)
            for source_file in source_files:
                name = source_file.file_name
                if File.objects.filter(owner=request.user, folder=destination, file_name__iexact=name, deleted_at__isnull=True).exists():
                    name = unique_copy_name(File, "file_name", name, folder=destination, owner=request.user)
                clone_encrypted_file(source_file, owner=request.user, folder=destination, file_name=name)
    except InvalidTag:
        messages.error(request, "File integrity verification failed. Copy was cancelled.")
        return _redirect_drive(request, destination.id if destination else None)
    except Exception:
        messages.error(request, "Could not paste the selected items.")
        return _redirect_drive(request, destination.id if destination else None)

    request.session.pop("clipboard", None)
    log_action(request.user, ActivityLog.Action.COPY, "Pasted copied multi-selection")
    messages.success(request, "Selected items pasted successfully.")
    return _redirect_drive(request, destination.id if destination else None)


def _owned_subtree(folder, owner):
    result = [folder]
    index = 0
    while index < len(result):
        current = result[index]
        result.extend(Folder.objects.filter(owner=owner, parent=current, deleted_at__isnull=True))
        index += 1
    return result


def _unique_copy_folder_name(owner, parent, original_name):
    candidate = f"{original_name} (copy)"
    number = 2
    while Folder.objects.filter(owner=owner, parent=parent, folder_name__iexact=candidate, deleted_at__isnull=True).exists():
        candidate = f"{original_name} (copy {number})"
        number += 1
    return candidate
