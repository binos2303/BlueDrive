from accounts.access import (
    active_tenant_required as login_required,
    can_edit_workspace_content,
    get_default_tenant,
    resolve_request_workspace,
)
from django.shortcuts import redirect, get_object_or_404
from django.http import Http404
from django.http import JsonResponse
from django.urls import reverse
from urllib.parse import urlencode
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce, Greatest
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone

from files.models import File
from folders.models import Folder
from sharing.models import Share
from sharing.services import (
    can_edit_file,
    can_edit_folder_tree,
    can_view_file,
    can_view_folder,
)
from dashboard.models import StarredItem
from logs.models import ActivityLog, SearchHistory
from logs.services import log_action
from files.services import clone_encrypted_file_with_quota, unique_copy_name
from files.quota import QuotaExceeded, QuotaStateError
from cryptography.exceptions import InvalidTag
from securedrive.frontend_redirects import redirect_to_frontend


def _shared_drive_items_response(request, query_text=""):
    """Return directly shared roots across all tenants, after per-item authorization.

    A recipient must not need a WorkspaceMembership in the sender's tenant to
    access an item that was explicitly shared with them. Permission helpers
    still verify that the source tenant/workspace and the share chain are live.
    """
    shares = Share.objects.filter(receiver=request.user).select_related(
        "owner", "tenant", "file", "file__owner", "file__folder",
        "folder", "folder__owner",
    ).order_by("-created_at", "pk")

    visible_files = []
    visible_folders = []
    seen_file_ids = set()
    seen_folder_ids = set()

    for share in shares:
        if share.file_id:
            drive_file = share.file
            if drive_file.pk in seen_file_ids or not can_view_file(drive_file, request.user):
                continue
            if query_text and query_text.casefold() not in drive_file.file_name.casefold():
                continue
            seen_file_ids.add(drive_file.pk)
            visible_files.append((share, drive_file))
        elif share.folder_id:
            folder = share.folder
            if folder.pk in seen_folder_ids or not can_view_folder(folder, request.user):
                continue
            if query_text and query_text.casefold() not in folder.folder_name.casefold():
                continue
            seen_folder_ids.add(folder.pk)
            visible_folders.append((share, folder))

    starred_file_ids = set(StarredItem.objects.filter(
        user=request.user, file_id__in=seen_file_ids,
    ).values_list("file_id", flat=True))
    starred_folder_ids = set(StarredItem.objects.filter(
        user=request.user, folder_id__in=seen_folder_ids,
    ).values_list("folder_id", flat=True))

    items = [
        _folder_item(
            folder,
            owner=share.owner.get_username(),
            starred=folder.pk in starred_folder_ids,
            can_manage=False,
        )
        for share, folder in visible_folders
    ]
    items.extend(
        _file_item(
            drive_file,
            owner=share.owner.get_username(),
            starred=drive_file.pk in starred_file_ids,
            can_manage=False,
        )
        for share, drive_file in visible_files
    )
    items.sort(key=lambda item: (item["type"] != "folder", item["name"].casefold(), item["id"]))

    if query_text:
        SearchHistory.objects.create(
            user=request.user,
            query=query_text,
            result_count=len(items),
        )
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.SEARCH,
            description="Searched directly shared Drive items.",
            metadata={"query_length": len(query_text), "result_count": len(items), "scope": "shared"},
        )

    return JsonResponse({"items": items, "query": query_text or None})


@login_required
@require_GET
def drive_items_api(request):
    """Return Drive items scoped to an authorized workspace or direct share."""
    view = request.GET.get("view", "drive")
    if view not in {"drive", "recent", "trash", "shared", "starred"}:
        raise Http404
    query_text = request.GET.get("q", "").strip()[:255]

    # Shared with me is intentionally cross-tenant: direct shares are a
    # separate authorization path from workspace membership. Each item is
    # checked by can_view_file/can_view_folder before any metadata is returned.
    if view == "shared":
        return _shared_drive_items_response(request, query_text)

    folder_id = request.GET.get("folder")
    folder = None
    tenant = None
    workspace = None
    if folder_id and view == "drive":
        try:
            folder_id = int(folder_id)
        except (TypeError, ValueError):
            raise Http404
        folder = Folder.objects.select_related(
            "tenant", "workspace", "owner", "parent",
        ).filter(pk=folder_id, deleted_at__isnull=True).first()
        # This also allows a recipient to browse a shared folder owned by a
        # different tenant while keeping an unshared folder indistinguishable
        # from a nonexistent one.
        if folder is None or not can_view_folder(folder, request.user):
            raise Http404
        tenant = folder.tenant
        workspace = folder.workspace
    else:
        tenant = get_default_tenant(request.user)
        if tenant is None:
            raise Http404
        workspace = resolve_request_workspace(request, tenant)
        if workspace is None:
            raise Http404
        tenant = workspace.tenant

    starred_entries = StarredItem.objects.filter(
        user=request.user,
        tenant=tenant,
    ).filter(Q(file__workspace=workspace) | Q(folder__workspace=workspace))
    starred_file_ids = set(starred_entries.filter(file__isnull=False).values_list("file_id", flat=True))
    starred_folder_ids = set(starred_entries.filter(folder__isnull=False).values_list("folder_id", flat=True))

    if query_text:
        # Search is scoped to exactly the active workspace; it never queries
        # other tenants/workspaces and permissions are rechecked per result.
        file_rows = list(File.objects.filter(
            tenant=tenant,
            workspace=workspace,
            deleted_at__isnull=True,
            file_name__icontains=query_text,
        ).filter(Q(folder__isnull=True) | Q(folder__deleted_at__isnull=True)).select_related(
            "owner", "folder"
        ).order_by("file_name", "pk")[:200])
        folder_rows = list(Folder.objects.filter(
            tenant=tenant,
            workspace=workspace,
            deleted_at__isnull=True,
            folder_name__icontains=query_text,
        ).filter(Q(parent__isnull=True) | Q(parent__deleted_at__isnull=True)).select_related(
            "owner", "parent"
        ).order_by("folder_name", "pk")[:200])
        items = []
        for row in folder_rows:
            if can_view_folder(row, request.user):
                owner_label = "Me" if row.owner_id == request.user.id else row.owner.get_username()
                items.append(_folder_item(
                    row,
                    owner=owner_label,
                    can_manage=can_edit_workspace_content(request.user, row.workspace),
                    starred=row.pk in starred_folder_ids,
                ))
        for row in file_rows:
            if can_view_file(row, request.user):
                owner_label = "Me" if row.owner_id == request.user.id else row.owner.get_username()
                items.append(_file_item(
                    row,
                    owner=owner_label,
                    can_manage=can_edit_workspace_content(request.user, row.workspace),
                    starred=row.pk in starred_file_ids,
                ))
        items.sort(key=lambda item: (item["type"] != "folder", item["name"].casefold()))
        SearchHistory.objects.create(
            user=request.user,
            tenant=tenant,
            workspace=workspace,
            query=query_text,
            result_count=len(items),
        )
        ActivityLog.objects.create(
            user=request.user,
            tenant=tenant,
            workspace=workspace,
            action=ActivityLog.Action.SEARCH,
            description="Searched workspace files.",
            metadata={"query_length": len(query_text), "result_count": len(items)},
        )
    elif view == "starred":
        entries = list(
            starred_entries.select_related(
                "file", "file__folder", "folder", "folder__parent"
            ).order_by("-created_at")
        )
        items = []
        stale_entry_ids = []
        for entry in entries:
            if entry.file_id:
                drive_file = entry.file
                is_live = drive_file.deleted_at is None and (
                    drive_file.folder_id is None or drive_file.folder.deleted_at is None
                )
                is_accessible = (
                    drive_file.tenant_id == tenant.id
                    and drive_file.workspace_id == workspace.pk
                    and can_view_file(drive_file, request.user)
                )
                if is_live and is_accessible:
                    items.append(_file_item(drive_file, starred=True))
                elif drive_file.deleted_at is None and not is_accessible:
                    stale_entry_ids.append(entry.pk)
            elif entry.folder_id:
                folder_item = entry.folder
                is_live = folder_item.deleted_at is None and (
                    folder_item.parent_id is None or folder_item.parent.deleted_at is None
                )
                is_accessible = (
                    folder_item.tenant_id == tenant.id
                    and folder_item.workspace_id == workspace.pk
                    and can_view_folder(folder_item, request.user)
                )
                if is_live and is_accessible:
                    items.append(_folder_item(folder_item, starred=True))
                elif folder_item.deleted_at is None and not is_accessible:
                    stale_entry_ids.append(entry.pk)
        if stale_entry_ids:
            StarredItem.objects.filter(user=request.user, tenant=tenant, pk__in=stale_entry_ids).delete()
    elif view == "trash":
        # Show only top-level trashed entries. Items inside a trashed folder are
        # represented by that folder instead of appearing as duplicate Trash rows.
        folders = Folder.objects.filter(
            tenant=tenant,
            workspace=workspace,
            deleted_at__isnull=False,
        ).filter(Q(parent__isnull=True) | Q(parent__deleted_at__isnull=True)).select_related(
            "owner"
        ).order_by("-deleted_at", "folder_name")
        files = File.objects.filter(
            tenant=tenant,
            workspace=workspace,
            deleted_at__isnull=False,
        ).filter(Q(folder__isnull=True) | Q(folder__deleted_at__isnull=True)).select_related(
            "owner"
        ).order_by("-deleted_at", "file_name")
        items = [
            _folder_item(
                item,
                starred=item.pk in starred_folder_ids,
                can_manage=can_edit_workspace_content(request.user, item.workspace),
            )
            for item in folders
            if can_edit_workspace_content(request.user, item.workspace)
        ]
        items.extend(
            _file_item(
                item,
                starred=item.pk in starred_file_ids,
                can_manage=can_edit_workspace_content(request.user, item.workspace),
            )
            for item in files
            if can_edit_workspace_content(request.user, item.workspace)
        )
    elif view == "recent":
        # Recent includes owned items and items accessible through a direct or
        # inherited share. Sort by the newest of access and content modification.
        share_rows = list(
            Share.objects.filter(receiver=request.user, tenant=tenant)
            .filter(Q(file__workspace=workspace) | Q(folder__workspace=workspace))
            .select_related("owner", "folder", "file")
        )
        direct_shared_file_ids = {row.file_id for row in share_rows if row.file_id}
        shared_folder_ids = set()
        for share in share_rows:
            if share.folder_id and share.folder.deleted_at is None:
                shared_folder_ids.update(
                    item.pk for item in _owned_subtree(share.folder, share.owner, tenant)
                    if item.deleted_at is None
                )

        file_queryset = File.objects.filter(
            tenant=tenant, workspace=workspace, deleted_at__isnull=True,
        ).filter(
            Q(folder__isnull=True) | Q(folder__deleted_at__isnull=True)
        ).select_related("owner", "folder").annotate(
            recent_activity_at=Greatest(
                Coalesce("last_accessed_at", "updated_at"), "updated_at"
            )
        ).order_by("-recent_activity_at")[:200]
        file_rows = [
            row for row in file_queryset
            if can_view_file(row, request.user)
        ]

        folder_queryset = Folder.objects.filter(
            tenant=tenant, workspace=workspace, deleted_at__isnull=True,
        ).filter(
            Q(parent__isnull=True) | Q(parent__deleted_at__isnull=True)
        ).select_related("owner", "parent").annotate(
            recent_activity_at=Greatest(
                Coalesce("last_accessed_at", "updated_at"), "updated_at"
            )
        ).order_by("-recent_activity_at")[:200]
        folder_rows = [
            row for row in folder_queryset
            if can_view_folder(row, request.user)
        ]
        recent_rows = [(row.recent_activity_at, "file", row) for row in file_rows]
        recent_rows.extend((row.recent_activity_at, "folder", row) for row in folder_rows)
        recent_rows.sort(key=lambda row: row[0], reverse=True)
        items = []
        for activity_at, item_type, row in recent_rows[:100]:
            is_shared = row.owner_id != request.user.id
            owner = row.owner.username if is_shared else "Me"
            can_manage = (
                not is_shared
                and can_edit_workspace_content(request.user, row.workspace)
            )
            if item_type == "file":
                items.append(_file_item(
                    row, owner=owner, modified=activity_at, can_manage=can_manage,
                    starred=row.pk in starred_file_ids,
                ))
            else:
                items.append(_folder_item(
                    row, owner=owner, modified=activity_at, can_manage=can_manage,
                    starred=row.pk in starred_folder_ids,
                ))
    elif view == "shared":
        shares = Share.objects.filter(
            receiver=request.user,
            tenant=tenant,
        ).filter(Q(file__workspace=workspace) | Q(folder__workspace=workspace)).select_related(
            "owner", "file", "file__owner", "file__folder", "folder", "folder__owner"
        )
        items = []
        for share in shares:
            if share.file_id:
                if (
                    share.file.workspace_id == workspace.pk
                    and share.file.deleted_at is None
                    and (share.file.folder_id is None or share.file.folder.deleted_at is None)
                    and can_view_file(share.file, request.user)
                ):
                    items.append(_file_item(share.file, owner=share.owner.username, can_manage=False, starred=share.file_id in starred_file_ids))
            elif (
                share.folder.workspace_id == workspace.pk
                and share.folder.deleted_at is None
                and can_view_folder(share.folder, request.user)
            ):
                items.append(_folder_item(share.folder, owner=share.owner.username, can_manage=False, starred=share.folder_id in starred_folder_ids))
    else:
        # A workspace is a collaborative area: members see the items owned by
        # all members who have stored content there. can_view_* is the actual
        # authorization check, so this does not expose My Drive to other users.
        folders = list(Folder.objects.filter(
            tenant=tenant,
            workspace=workspace,
            parent=folder,
            deleted_at__isnull=True,
        ).select_related("owner").order_by("folder_name"))
        files = list(File.objects.filter(
            tenant=tenant,
            workspace=workspace,
            folder=folder,
            deleted_at__isnull=True,
        ).select_related("owner", "folder").order_by("file_name"))
        items = [
            _folder_item(
                item,
                owner="Me" if item.owner_id == request.user.id else item.owner.get_username(),
                starred=item.pk in starred_folder_ids,
                can_manage=can_edit_folder_tree(item, request.user),
            )
            for item in folders
            if can_view_folder(item, request.user)
        ]
        items.extend(
            _file_item(
                item,
                owner="Me" if item.owner_id == request.user.id else item.owner.get_username(),
                starred=item.pk in starred_file_ids,
                can_manage=can_edit_file(item, request.user),
            )
            for item in files
            if can_view_file(item, request.user)
        )
    return JsonResponse({"items": items, "query": query_text or None})


def _owner_initials(owner):
    parts = owner.split()
    return "".join(part[0].upper() for part in parts[:2]) or "?"


def _file_item(item, *, owner="Me", modified=None, starred=False, can_manage=None):
    return {
        "id": item.id,
        "workspaceId": str(item.workspace_id),
        "name": item.file_name,
        "owner": owner,
        "ownerInitials": "Me" if owner == "Me" else _owner_initials(owner),
        "modified": (modified or item.updated_at).isoformat(),
        "size": item.file_size,
        "type": "image" if item.mime_type.startswith("image/") else "document",
        "starred": bool(starred),
        "canManage": owner == "Me" if can_manage is None else bool(can_manage),
    }


def _folder_item(item, *, owner="Me", modified=None, starred=False, can_manage=None):
    return {
        "id": -item.id,
        "folderId": item.id,
        "workspaceId": str(item.workspace_id),
        "name": item.folder_name,
        "owner": owner,
        "ownerInitials": "Me" if owner == "Me" else _owner_initials(owner),
        "modified": (modified or item.updated_at).isoformat(),
        "size": None,
        "type": "folder",
        "starred": bool(starred),
        "canManage": owner == "Me" if can_manage is None else bool(can_manage),
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
            workspace_id=source.workspace_id,
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
    workspace = resolve_request_workspace(request, tenant)
    if workspace is None:
        raise Http404("Workspace is unavailable or not accessible.")
    tenant = workspace.tenant

    if not file_ids and not folder_ids:
        messages.warning(request, "No items selected.")
        return _redirect_bulk_result(request, current_folder_id)

    files = list(File.objects.filter(
        id__in=file_ids,
        owner=request.user,
        tenant=tenant,
        workspace=workspace,
        deleted_at__isnull=True,
    ).select_related("folder"))
    folders = list(Folder.objects.filter(
        id__in=folder_ids,
        owner=request.user,
        tenant=tenant,
        workspace=workspace,
        deleted_at__isnull=True,
    ).select_related("parent"))

    # Never silently operate on IDs that are not owned by the current user.
    if len(files) != len(file_ids) or len(folders) != len(folder_ids):
        messages.error(request, "One or more selected items are not accessible in this workspace.")
        return _redirect_bulk_result(request, current_folder_id)
    if any(not can_edit_file(item, request.user) for item in files) or any(
        not can_edit_folder_tree(item, request.user) for item in folders
    ):
        messages.error(request, "Editor access to every selected item is required.")
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
                   f"{action.title()} {len(direct_files)} file(s) and {len(top_folders)} folder(s) to clipboard",
                   workspace=workspace)
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
                    stack.extend(Folder.objects.filter(
                        owner=request.user, tenant=tenant, workspace=workspace,
                        parent=current, deleted_at__isnull=True,
                    ))
                ids = [item.id for item in subtree]
                Folder.objects.filter(
                    owner=request.user, tenant=tenant, workspace=workspace, id__in=ids
                ).update(deleted_at=deleted_time)
                File.objects.filter(
                    owner=request.user, tenant=tenant, workspace=workspace,
                    folder_id__in=ids, deleted_at__isnull=True,
                ).update(deleted_at=deleted_time)
            File.objects.filter(
                owner=request.user, tenant=tenant, workspace=workspace,
                id__in=[file.id for file in direct_files],
            ).update(deleted_at=deleted_time)
        log_action(request.user, ActivityLog.Action.DELETE,
                   f"Moved {len(direct_files)} file(s) and {len(top_folders)} folder(s) to Trash",
                   workspace=workspace)
        messages.success(request, "Selected items moved to Trash.")
        return _redirect_bulk_result(request, current_folder_id)

    if action == "move":
        destination_id = request.POST.get("destination_id") or None
        destination = None
        if destination_id:
            destination = get_object_or_404(
                Folder, id=destination_id, owner=request.user, tenant=tenant,
                workspace=workspace, deleted_at__isnull=True,
            )

        for folder in top_folders:
            if destination and _folder_contains_ids(folder, destination.id):
                messages.error(request, "A folder cannot be moved into itself or one of its descendants.")
                return _redirect_bulk_result(request, current_folder_id)
            if Folder.objects.filter(owner=request.user, tenant=tenant, workspace=workspace,
                                     parent=destination, folder_name__iexact=folder.folder_name,
                                     deleted_at__isnull=True).exclude(id=folder.id).exists():
                messages.error(request, f'A folder named "{folder.folder_name}" already exists at the destination.')
                return _redirect_bulk_result(request, current_folder_id)
        for file in direct_files:
            if File.objects.filter(owner=request.user, tenant=tenant, workspace=workspace,
                                   folder=destination, file_name__iexact=file.file_name,
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
                   f"Moved {len(direct_files)} file(s) and {len(top_folders)} folder(s)",
                   workspace=workspace)
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
    workspace = resolve_request_workspace(request, tenant)
    if workspace is None:
        raise Http404("Workspace is unavailable or not accessible.")
    tenant = workspace.tenant
    destination = None
    if destination_id:
        destination = get_object_or_404(
            Folder, id=destination_id, owner=request.user, tenant=tenant,
            workspace=workspace, deleted_at__isnull=True,
        )

    source_files = list(File.objects.filter(
        owner=request.user, tenant=tenant, workspace=workspace,
        id__in=clipboard.get("files", []), deleted_at__isnull=True
    ).select_related("folder"))
    source_folders = list(Folder.objects.filter(
        owner=request.user, tenant=tenant, workspace=workspace,
        id__in=clipboard.get("folders", []), deleted_at__isnull=True
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
            if Folder.objects.filter(owner=request.user, tenant=tenant, workspace=workspace, parent=destination, folder_name__iexact=folder.folder_name, deleted_at__isnull=True).exclude(id=folder.id).exists():
                messages.error(request, f'A folder named "{folder.folder_name}" already exists at the destination.')
                return _redirect_drive(request, destination.id)
        for file in source_files:
            if File.objects.filter(owner=request.user, tenant=tenant, workspace=workspace, folder=destination, file_name__iexact=file.file_name, deleted_at__isnull=True).exclude(id=file.id).exists():
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
        log_action(request.user, ActivityLog.Action.MOVE, "Pasted moved multi-selection", workspace=workspace)
        messages.success(request, "Selected items moved successfully.")
        return _redirect_drive(request, destination.id if destination else None)

    try:
        created_files = []
        with transaction.atomic():
            for source in top_folders:
                root_name = source.folder_name
                if Folder.objects.filter(owner=request.user, tenant=tenant, workspace=workspace, parent=destination, folder_name__iexact=root_name, deleted_at__isnull=True).exists():
                    root_name = _unique_copy_folder_name(
                        request.user, tenant, destination, root_name, workspace=workspace
                    )
                folder_map = {source.id: Folder.objects.create(
                    tenant=tenant,
                    workspace=workspace,
                    owner=request.user,
                    folder_name=root_name,
                    parent=destination,
                )}
                tree = _owned_subtree(source, request.user, tenant)
                for original in tree[1:]:
                    folder_map[original.id] = Folder.objects.create(
                        tenant=tenant,
                        workspace=workspace,
                        owner=request.user,
                        folder_name=original.folder_name,
                        parent=folder_map[original.parent_id],
                    )
                for original in tree:
                    target = folder_map[original.id]
                    for source_file in File.objects.filter(owner=request.user, tenant=tenant, workspace=workspace, folder=original, deleted_at__isnull=True):
                        name = source_file.file_name
                        if File.objects.filter(owner=request.user, tenant=tenant, workspace=workspace, folder=target, file_name__iexact=name, deleted_at__isnull=True).exists():
                            name = unique_copy_name(File, "file_name", name, folder=target, owner=request.user, workspace=workspace)
                        created_files.append(clone_encrypted_file_with_quota(
                            source_file,
                            owner=request.user,
                            folder=target,
                            file_name=name,
                            tenant=tenant,
                        ))
            for source_file in source_files:
                name = source_file.file_name
                if File.objects.filter(owner=request.user, tenant=tenant, workspace=workspace, folder=destination, file_name__iexact=name, deleted_at__isnull=True).exists():
                    name = unique_copy_name(File, "file_name", name, folder=destination, owner=request.user, workspace=workspace)
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
    log_action(request.user, ActivityLog.Action.COPY, "Pasted copied multi-selection", workspace=workspace)
    messages.success(request, "Selected items pasted successfully.")
    return _redirect_drive(request, destination.id if destination else None)


def _owned_subtree(folder, owner, tenant):
    """Return only descendants that remain inside the root workspace."""
    result = [folder]
    index = 0
    while index < len(result):
        current = result[index]
        result.extend(
            Folder.objects.filter(
                owner=owner,
                tenant=tenant,
                workspace=folder.workspace,
                parent=current,
                deleted_at__isnull=True,
            )
        )
        index += 1
    return result


def _unique_copy_folder_name(owner, tenant, parent, original_name, *, workspace=None):
    if workspace is None and parent is not None:
        workspace = parent.workspace
    candidate = f"{original_name} (copy)"
    number = 2
    queryset = Folder.objects.filter(
        owner=owner,
        tenant=tenant,
        parent=parent,
        folder_name__iexact=candidate,
        deleted_at__isnull=True,
    )
    if workspace is not None:
        queryset = queryset.filter(workspace=workspace)
    while queryset.exists():
        candidate = f"{original_name} (copy {number})"
        number += 1
        queryset = Folder.objects.filter(
            owner=owner,
            tenant=tenant,
            parent=parent,
            folder_name__iexact=candidate,
            deleted_at__isnull=True,
        )
        if workspace is not None:
            queryset = queryset.filter(workspace=workspace)
    return candidate
