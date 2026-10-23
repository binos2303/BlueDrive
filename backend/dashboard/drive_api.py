"""JSON endpoints for the Next.js Drive file browser.

The classic Django templates use redirect-based bulk actions. These endpoints
provide explicit JSON responses for the SPA while reusing the same ownership,
tenant and folder-tree rules.
"""
import hashlib
import json
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib.auth import get_user_model
from django.views.decorators.http import require_GET
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import (
    active_tenant_required as login_required,
    can_edit_workspace_content,
    get_default_tenant,
    resolve_request_workspace,
)
from files.models import File, UploadSession
from files.permanent_delete import PermanentDeleteError, permanently_delete_files
from files.quota import QuotaExceeded, QuotaStateError
from files.services import unique_copy_name
from folders.models import Folder
from dashboard.models import StarredItem
from sharing.models import Share
from sharing.services import can_edit_file, can_edit_folder, can_view_file, can_view_folder
from logs.models import ActivityLog
from logs.services import log_action
from .views import _folder_contains_ids, _top_level_folders, _owned_subtree, _unique_copy_folder_name


def _json_payload(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, JsonResponse({"detail": "Invalid JSON request body."}, status=400)
    if not isinstance(payload, dict):
        return None, JsonResponse({"detail": "Request body must be an object."}, status=400)
    return payload, None


def _drive_context(request, payload=None):
    tenant = get_default_tenant(request.user)
    if tenant is None:
        raise Http404
    workspace = resolve_request_workspace(request, tenant, payload)
    if workspace is None:
        raise Http404("Workspace is unavailable or not accessible.")
    return workspace.tenant, workspace


def _positive_ids(payload, key):
    values = payload.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f"{key} must be a list of positive integer IDs.")
    result = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError(f"{key} must contain positive integer IDs.")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must contain positive integer IDs.")
        if number <= 0:
            raise ValueError(f"{key} must contain positive integer IDs.")
        if number not in result:
            result.append(number)
    return result


def _items_for_operation(payload, request, tenant, workspace):
    try:
        file_ids = _positive_ids(payload, "file_ids")
        folder_ids = _positive_ids(payload, "folder_ids")
    except ValueError as error:
        return None, JsonResponse({"detail": str(error)}, status=400)
    if not file_ids and not folder_ids:
        return None, JsonResponse({"detail": "Select at least one file or folder."}, status=400)

    files = list(File.objects.filter(
        id__in=file_ids,
        tenant=tenant,
        workspace=workspace,
        deleted_at__isnull=True,
    ).select_related("folder"))
    folders = list(Folder.objects.filter(
        id__in=folder_ids,
        tenant=tenant,
        workspace=workspace,
        deleted_at__isnull=True,
    ).select_related("parent"))
    if len(files) != len(file_ids) or len(folders) != len(folder_ids):
        return None, JsonResponse({"detail": "One or more selected items are no longer available or accessible."}, status=404)
    if any(not can_edit_file(item, request.user) for item in files) or any(
        not can_edit_folder(item, request.user) for item in folders
    ):
        return None, JsonResponse({"detail": "Editor access to the selected workspace is required."}, status=403)

    top_folders = _top_level_folders(folders)
    # If the selection includes a folder and one of its descendants' files, the
    # folder action already covers those files. Avoid processing them twice.
    direct_files = [
        item for item in files
        if not item.folder_id or not any(_folder_contains_ids(folder, item.folder_id) for folder in top_folders)
    ]
    return (file_ids, folder_ids, direct_files, top_folders), None


@login_required
@require_POST
def drive_items_move_api(request):
    """Move selected owned items to an optional destination folder (root = null)."""
    payload, error = _json_payload(request)
    if error:
        return error
    tenant, workspace = _drive_context(request, payload)
    selected, error = _items_for_operation(payload, request, tenant, workspace)
    if error:
        return error
    _file_ids, _folder_ids, direct_files, top_folders = selected

    destination_raw = payload.get("destination_folder_id")
    if destination_raw in (None, ""):
        destination_id = None
    else:
        try:
            destination_id = int(destination_raw)
        except (TypeError, ValueError):
            return JsonResponse({"detail": "Destination folder ID is invalid."}, status=400)
        if destination_id <= 0:
            return JsonResponse({"detail": "Destination folder ID is invalid."}, status=400)

    destination = None
    if destination_id is not None:
        destination = Folder.objects.filter(
            id=destination_id,
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            deleted_at__isnull=True,
        ).first()
        if destination is None:
            return JsonResponse({"detail": "Destination folder is unavailable or inaccessible."}, status=404)
    destination_parent_id = destination.id if destination else None

    for folder in top_folders:
        if folder.parent_id == destination_parent_id:
            continue
        if destination and _folder_contains_ids(folder, destination.id):
            return JsonResponse({"detail": f'Cannot move "{folder.folder_name}" into itself or one of its subfolders.'}, status=400)
        conflict = Folder.objects.filter(
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            parent=destination,
            folder_name__iexact=folder.folder_name,
            deleted_at__isnull=True,
        ).exclude(id=folder.id).exists()
        if conflict:
            return JsonResponse({"detail": f'A folder named "{folder.folder_name}" already exists at the destination.'}, status=409)

    for drive_file in direct_files:
        if drive_file.folder_id == destination_parent_id:
            continue
        conflict = File.objects.filter(
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            folder=destination,
            file_name__iexact=drive_file.file_name,
            deleted_at__isnull=True,
        ).exclude(id=drive_file.id).exists()
        if conflict:
            return JsonResponse({"detail": f'A file named "{drive_file.file_name}" already exists at the destination.'}, status=409)

    items_requiring_move = sum(folder.parent_id != destination_parent_id for folder in top_folders)
    items_requiring_move += sum(drive_file.folder_id != destination_parent_id for drive_file in direct_files)
    if items_requiring_move == 0:
        return JsonResponse({"detail": "The selected items are already in this folder.", "count": 0})

    try:
        with transaction.atomic():
            for folder in top_folders:
                if folder.parent_id != destination_parent_id:
                    folder.parent = destination
                    folder.save(update_fields=["parent", "updated_at"])
            for drive_file in direct_files:
                if drive_file.folder_id != destination_parent_id:
                    drive_file.folder = destination
                    drive_file.save(update_fields=["folder", "updated_at"])
    except IntegrityError:
        return JsonResponse({"detail": "A destination item with the same name appeared during the move. Refresh and try again."}, status=409)

    moved_count = len(top_folders) + len(direct_files)
    log_action(request.user, ActivityLog.Action.MOVE, f"Moved {len(direct_files)} file(s) and {len(top_folders)} folder(s)", workspace=workspace)
    return JsonResponse({"detail": f"Moved {moved_count} item(s).", "count": moved_count})


def _duplicate_encrypted_file(source_file, *, actor, tenant, workspace, target_folder, target_name):
    """Copy file contents through finalization into an independent MinIO object."""
    from files.finalization import finalize_verified_upload
    from files.models import FileVersion, StorageLocation, UploadSession
    from files.quota import finalize_upload_quota, reserve_upload_quota
    from files.storage_adapters import get_storage_adapter
    from files.views import _decrypt_file

    plaintext = _decrypt_file(source_file)
    session = UploadSession.objects.create(
        tenant=tenant,
        workspace=(target_folder.workspace if target_folder is not None else workspace),
        initiated_by=actor,
        target_folder=target_folder,
        client_name=target_name[:255],
        expected_size_bytes=len(plaintext),
        expected_sha256=hashlib.sha256(plaintext).hexdigest(),
        expires_at=timezone.now() + timedelta(hours=1),
        state=UploadSession.State.INITIATED,
    )
    reserved = False
    try:
        reserve_upload_quota(session.pk, actor)
        reserved = True
        session.refresh_from_db()
        session.state = UploadSession.State.VERIFYING
        session.save(update_fields=["state", "updated_at"])
        result = finalize_verified_upload(session, plaintext, actor)
        duplicated_file = File.objects.get(pk=result["file_id"], owner=actor, tenant=tenant)
        version = FileVersion.objects.filter(
            tenant=tenant,
            file=duplicated_file,
            state=FileVersion.State.AVAILABLE,
            is_current=True,
        ).first()
        location = None if version is None else StorageLocation.objects.filter(
            tenant=tenant,
            file_version=version,
            state=StorageLocation.State.AVAILABLE,
        ).select_related("storage_config").order_by("-created_at").first()
        if location is None:
            raise RuntimeError("New duplicate has no available MinIO location.")
        return duplicated_file, location.object_ref
    except Exception:
        # A final key may already exist if storage succeeded before a later DB error.
        final_key = UploadSession.objects.filter(pk=session.pk).values_list(
            "final_object_key", flat=True
        ).first() or session.final_object_key
        if final_key:
            try:
                get_storage_adapter().delete_object(final_key)
            except Exception:
                pass
        if reserved:
            try:
                finalize_upload_quota(session.pk, completed=False, actor=actor)
            except Exception:
                # The finalizer may already have consumed/released the reservation;
                # the surrounding transaction will roll back this failed duplicate.
                pass
        raise


def _cleanup_duplicate_objects(object_keys):
    if not object_keys:
        return
    try:
        from files.storage_adapters import get_storage_adapter
        storage = get_storage_adapter()
    except Exception:
        return
    for object_key in object_keys:
        try:
            storage.delete_object(object_key)
        except Exception:
            # Do not mask the primary request failure; a reconciliation job can
            # remove a remaining orphan object later.
            pass


@login_required
@require_POST
def drive_items_duplicate_api(request):
    """Duplicate files beside their originals and copy selected folder trees recursively."""
    payload, error = _json_payload(request)
    if error:
        return error
    tenant, workspace = _drive_context(request, payload)
    selected, error = _items_for_operation(payload, request, tenant, workspace)
    if error:
        return error
    _file_ids, _folder_ids, direct_files, top_folders = selected

    created_object_keys = []
    created_count = 0
    try:
        with transaction.atomic():
            # Build copied folders first. Each copied file is re-encrypted via the
            # same finalization service as an upload, so its new ID/AAD stays valid.
            for source_folder in top_folders:
                copied_root = Folder.objects.create(
                    tenant=tenant,
                    workspace=workspace,
                    owner=request.user,
                    folder_name=_unique_copy_folder_name(request.user, tenant, source_folder.parent, source_folder.folder_name, workspace=workspace),
                    parent=source_folder.parent,
                )
                tree = _owned_subtree(source_folder, request.user, tenant)
                folder_map = {source_folder.id: copied_root}
                for original in tree[1:]:
                    folder_map[original.id] = Folder.objects.create(
                        tenant=tenant,
                        owner=request.user,
                        folder_name=original.folder_name,
                        parent=folder_map[original.parent_id],
                    )
                created_count += len(tree)
                for original in tree:
                    target_folder = folder_map[original.id]
                    source_files_in_folder = File.objects.filter(
                        owner=request.user,
                        tenant=tenant,
                        workspace=workspace,
                        folder=original,
                        deleted_at__isnull=True,
                    ).select_related("folder")
                    for source_file in source_files_in_folder:
                        duplicated, object_key = _duplicate_encrypted_file(
                            source_file,
                            actor=request.user,
                            tenant=tenant,
                            workspace=workspace,
                            target_folder=target_folder,
                            target_name=source_file.file_name,
                        )
                        created_object_keys.append(object_key)
                        created_count += 1

            # Stand-alone files are duplicated in the same parent folder.
            for source_file in direct_files:
                copy_name = unique_copy_name(
                    File,
                    "file_name",
                    source_file.file_name,
                    folder=source_file.folder,
                    owner=request.user,
                    workspace=workspace,
                )
                duplicated, object_key = _duplicate_encrypted_file(
                    source_file,
                    actor=request.user,
                    tenant=tenant,
                    workspace=workspace,
                    target_folder=source_file.folder,
                    target_name=copy_name,
                )
                created_object_keys.append(object_key)
                created_count += 1
    except (QuotaExceeded, QuotaStateError):
        _cleanup_duplicate_objects(created_object_keys)
        return JsonResponse({"detail": "The workspace or member quota does not allow this duplicate."}, status=409)
    except InvalidTag:
        _cleanup_duplicate_objects(created_object_keys)
        return JsonResponse({"detail": "File integrity verification failed. No duplicate was completed."}, status=409)
    except Http404:
        _cleanup_duplicate_objects(created_object_keys)
        return JsonResponse({"detail": "One of the source files is unavailable and could not be duplicated."}, status=409)
    except IntegrityError:
        _cleanup_duplicate_objects(created_object_keys)
        return JsonResponse({"detail": "A naming conflict occurred while duplicating items. Refresh and retry."}, status=409)
    except Exception:
        _cleanup_duplicate_objects(created_object_keys)
        return JsonResponse({"detail": "Could not duplicate the selected items. Check server logs for details."}, status=500)

    log_action(request.user, ActivityLog.Action.COPY, f"Duplicated {created_count} Drive item(s)", workspace=workspace)
    return JsonResponse({"detail": f"Duplicated {created_count} item(s).", "count": created_count})


def _all_descendant_folders(root, owner, tenant):
    """Return a folder tree regardless of soft-delete state."""
    result = [root]
    index = 0
    while index < len(result):
        parent = result[index]
        result.extend(
            Folder.objects.filter(
                owner=owner,
                tenant=tenant,
                workspace=root.workspace,
                parent=parent,
            ).order_by("pk")
        )
        index += 1
    return result


def _items_in_trash(payload, request, tenant, workspace):
    try:
        file_ids = _positive_ids(payload, "file_ids")
        folder_ids = _positive_ids(payload, "folder_ids")
    except ValueError as error:
        return None, JsonResponse({"detail": str(error)}, status=400)
    if not file_ids and not folder_ids:
        return None, JsonResponse({"detail": "Select at least one Trash item."}, status=400)

    files = list(File.objects.filter(
        id__in=file_ids,
        tenant=tenant,
        workspace=workspace,
        deleted_at__isnull=False,
    ).select_related("folder"))
    folders = list(Folder.objects.filter(
        id__in=folder_ids,
        tenant=tenant,
        workspace=workspace,
        deleted_at__isnull=False,
    ).select_related("parent"))
    if len(files) != len(file_ids) or len(folders) != len(folder_ids):
        return None, JsonResponse({
            "detail": "One or more Trash items are no longer available or accessible."
        }, status=404)
    if not can_edit_workspace_content(request.user, workspace):
        return None, JsonResponse({"detail": "Editor access to the selected workspace is required."}, status=403)

    top_folders = _top_level_folders(folders)
    direct_files = [
        item for item in files
        if not item.folder_id or not any(
            _folder_contains_ids(folder, item.folder_id) for folder in top_folders
        )
    ]
    return (files, folders, direct_files, top_folders), None


@login_required
@require_POST
def drive_items_trash_api(request):
    """Soft-delete selected live files/folders for the Drive SPA."""
    payload, error = _json_payload(request)
    if error:
        return error
    tenant, workspace = _drive_context(request, payload)
    selected, error = _items_for_operation(payload, request, tenant, workspace)
    if error:
        return error
    _file_ids, _folder_ids, direct_files, top_folders = selected

    trash_time = timezone.now()
    subtree_folders = []
    for folder in top_folders:
        subtree_folders.extend(_owned_subtree(folder, request.user, tenant))
    subtree_by_id = {folder.pk: folder for folder in subtree_folders}
    subtree_ids = list(subtree_by_id)

    with transaction.atomic():
        folder_count = Folder.objects.filter(
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            id__in=subtree_ids,
            deleted_at__isnull=True,
        ).update(deleted_at=trash_time)
        nested_file_count = File.objects.filter(
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            folder_id__in=subtree_ids,
            deleted_at__isnull=True,
        ).update(deleted_at=trash_time)
        direct_file_count = File.objects.filter(
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            id__in=[item.pk for item in direct_files],
            deleted_at__isnull=True,
        ).update(deleted_at=trash_time)

    total = folder_count + nested_file_count + direct_file_count
    log_action(
        request.user,
        ActivityLog.Action.DELETE,
        f"Moved {direct_file_count + nested_file_count} file(s) and {folder_count} folder(s) to Trash",
        workspace=workspace,
    )
    return JsonResponse({"detail": f"Moved {total} item(s) to Trash.", "count": total})


@login_required
@require_POST
def drive_items_restore_api(request):
    """Restore selected top-level items from Trash, including trashed descendants."""
    payload, error = _json_payload(request)
    if error:
        return error
    tenant, workspace = _drive_context(request, payload)
    selected, error = _items_in_trash(payload, request, tenant, workspace)
    if error:
        return error
    _all_files, _all_folders, direct_files, top_folders = selected

    folder_trees = []
    for folder in top_folders:
        if folder.parent_id and folder.parent.deleted_at is not None:
            return JsonResponse({
                "detail": "Restore the parent folder before restoring this folder."
            }, status=409)
        folder_trees.append(_all_descendant_folders(folder, request.user, tenant))
    tree_by_id = {folder.pk: folder for tree in folder_trees for folder in tree}
    tree_ids = list(tree_by_id)

    # Check folder-name collisions before updating any records.
    seen_folder_names = set()
    for folder in tree_by_id.values():
        key = (folder.parent_id, folder.folder_name.casefold())
        if key in seen_folder_names:
            return JsonResponse({
                "detail": f'A folder named "{folder.folder_name}" conflicts inside the restored tree.'
            }, status=409)
        seen_folder_names.add(key)
        if Folder.objects.filter(
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            parent_id=folder.parent_id,
            folder_name__iexact=folder.folder_name,
            deleted_at__isnull=True,
        ).exclude(id__in=tree_ids).exists():
            return JsonResponse({
                "detail": f'A folder named "{folder.folder_name}" already exists at the destination.'
            }, status=409)

    subtree_files = list(File.objects.filter(
        owner=request.user,
        tenant=tenant,
        workspace=workspace,
        folder_id__in=tree_ids,
        deleted_at__isnull=False,
    ).select_related("folder"))
    files_to_restore = {item.pk: item for item in [*direct_files, *subtree_files]}
    file_names_seen = set()
    for drive_file in files_to_restore.values():
        if drive_file.folder_id in tree_by_id:
            # If its parent is restored along with this item, collision checks
            # include files in that same restored folder.
            pass
        elif drive_file.folder_id and drive_file.folder.deleted_at is not None:
            return JsonResponse({
                "detail": f'Restore the parent folder before restoring "{drive_file.file_name}".'
            }, status=409)
        key = (drive_file.folder_id, drive_file.file_name.casefold())
        if key in file_names_seen:
            return JsonResponse({
                "detail": f'A file named "{drive_file.file_name}" conflicts inside the restored tree.'
            }, status=409)
        file_names_seen.add(key)
        if File.objects.filter(
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            folder_id=drive_file.folder_id,
            file_name__iexact=drive_file.file_name,
            deleted_at__isnull=True,
        ).exclude(id__in=files_to_restore.keys()).exists():
            return JsonResponse({
                "detail": f'A file named "{drive_file.file_name}" already exists in the destination.'
            }, status=409)

    with transaction.atomic():
        folder_count = Folder.objects.filter(
            owner=request.user, tenant=tenant, workspace=workspace, id__in=tree_ids,
        ).update(deleted_at=None)
        file_count = File.objects.filter(
            owner=request.user,
            tenant=tenant,
            workspace=workspace,
            id__in=list(files_to_restore),
        ).update(deleted_at=None)

    total = folder_count + file_count
    log_action(
        request.user,
        ActivityLog.Action.RESTORE,
        f"Restored {file_count} file(s) and {folder_count} folder(s) from Trash",
        workspace=workspace,
    )
    return JsonResponse({"detail": f"Restored {total} item(s).", "count": total})


@login_required
@require_POST
def drive_items_delete_api(request):
    """Permanently delete Trash selections and their MinIO objects/metadata."""
    payload, error = _json_payload(request)
    if error:
        return error
    tenant, workspace = _drive_context(request, payload)
    selected, error = _items_in_trash(payload, request, tenant, workspace)
    if error:
        return error
    _all_files, _all_folders, direct_files, top_folders = selected

    folder_trees = [
        _all_descendant_folders(folder, request.user, tenant)
        for folder in top_folders
    ]
    tree_by_id = {folder.pk: folder for tree in folder_trees for folder in tree}
    tree_ids = list(tree_by_id)
    nested_files = list(File.objects.filter(
        owner=request.user,
        tenant=tenant,
        workspace=workspace,
        folder_id__in=tree_ids,
    ).select_related("folder"))
    files_by_id = {item.pk: item for item in [*direct_files, *nested_files]}

    try:
        permanently_delete_files(files_by_id.values())
    except PermanentDeleteError as error:
        return JsonResponse({
            "detail": "Some storage objects could not be deleted. Metadata was retained so the operation can be retried."
        }, status=503)
    except Exception:
        return JsonResponse({
            "detail": "Permanent deletion failed. No success was reported; check storage availability and retry."
        }, status=503)

    # Upload sessions keep their audit history, so detach their protected folder FK.
    if tree_ids:
        UploadSession.objects.filter(
            target_folder_id__in=tree_ids,
            workspace=workspace,
        ).update(target_folder=None)
    folder_count = len(tree_ids)
    if tree_ids:
        try:
            with transaction.atomic():
                Folder.objects.filter(
                    owner=request.user,
                    tenant=tenant,
                    workspace=workspace,
                    id__in=tree_ids,
                ).delete()
        except Exception:
            return JsonResponse({
                "detail": "File objects were deleted but folder metadata cleanup failed. Retry deleting the empty trashed folder."
            }, status=503)

    total = len(files_by_id) + len(tree_ids)
    log_action(
        request.user,
        ActivityLog.Action.PERMANENT_DELETE,
        f"Permanently deleted {len(files_by_id)} file(s) and {folder_count} folder record(s) from Trash",
        workspace=workspace,
    )
    return JsonResponse({"detail": f"Permanently deleted {total} item(s).", "count": total})


@login_required
@require_POST
def drive_items_star_api(request):
    """Add or remove personal Starred shortcuts for accessible live items."""
    payload, error = _json_payload(request)
    if error:
        return error
    tenant, workspace = _drive_context(request, payload)
    try:
        file_ids = _positive_ids(payload, "file_ids")
        folder_ids = _positive_ids(payload, "folder_ids")
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)
    if not file_ids and not folder_ids:
        return JsonResponse({"detail": "Select at least one file or folder."}, status=400)
    desired = payload.get("starred")
    if not isinstance(desired, bool):
        return JsonResponse({"detail": "The starred field must be true or false."}, status=400)

    # A Star can be applied to an owned item or an item directly shared with this
    # user. It never grants access; file/folder permission checks remain separate.
    candidate_files = File.objects.filter(
        id__in=file_ids, tenant=tenant, workspace=workspace, deleted_at__isnull=True,
    ).select_related("owner", "folder")
    allowed_file_ids = {
        item.pk for item in candidate_files
        if can_view_file(item, request.user)
    }

    candidate_folders = Folder.objects.filter(
        id__in=folder_ids, tenant=tenant, workspace=workspace, deleted_at__isnull=True,
    ).select_related("owner", "parent")
    allowed_folder_ids = {
        item.pk for item in candidate_folders
        if can_view_folder(item, request.user)
    }

    if len(allowed_file_ids) != len(file_ids) or len(allowed_folder_ids) != len(folder_ids):
        return JsonResponse({"detail": "One or more items are no longer available or accessible."}, status=404)

    with transaction.atomic():
        if desired:
            for drive_file in File.objects.filter(id__in=file_ids, tenant=tenant, workspace=workspace):
                StarredItem.objects.get_or_create(
                    tenant=tenant, user=request.user, file=drive_file,
                )
            for folder in Folder.objects.filter(id__in=folder_ids, tenant=tenant, workspace=workspace):
                StarredItem.objects.get_or_create(
                    tenant=tenant, user=request.user, folder=folder,
                )
        else:
            StarredItem.objects.filter(user=request.user, tenant=tenant, file_id__in=file_ids).delete()
            StarredItem.objects.filter(user=request.user, tenant=tenant, folder_id__in=folder_ids).delete()

    return JsonResponse({
        "detail": "Added to Starred." if desired else "Removed from Starred.",
        "count": len(file_ids) + len(folder_ids),
        "starred": desired,
    })


@login_required
@require_GET
def drive_folder_tree_api(request):
    """Return a nested tree of live folders owned by the active user/tenant."""
    tenant, workspace = _drive_context(request)
    folder_rows = Folder.objects.filter(
        tenant=tenant, workspace=workspace, deleted_at__isnull=True,
    ).select_related("parent", "owner").order_by("folder_name", "pk")
    rows = [
        {"id": row.id, "folder_name": row.folder_name, "parent_id": row.parent_id}
        for row in folder_rows if can_view_folder(row, request.user)
    ]
    nodes = {
        row["id"]: {
            "id": row["id"],
            "name": row["folder_name"],
            "parent_id": row["parent_id"],
            "children": [],
        }
        for row in rows
    }
    roots = []
    for row in rows:
        node = nodes[row["id"]]
        parent = nodes.get(row["parent_id"])
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
    return JsonResponse({"workspace_id": str(workspace.pk), "items": roots})


@login_required
@require_POST
def drive_items_share_api(request):
    """Share owned Drive items with an existing account identified by email."""
    payload, error = _json_payload(request)
    if error:
        return error
    tenant, workspace = _drive_context(request, payload)
    selected, error = _items_for_operation(payload, request, tenant, workspace)
    if error:
        return error
    _file_ids, _folder_ids, direct_files, top_folders = selected
    if any(item.owner_id != request.user.id for item in [*direct_files, *top_folders]):
        return JsonResponse({
            "detail": "Only the owner can create direct item shares. Invite people to the workspace to grant workspace-wide access."
        }, status=403)

    email = payload.get("email")
    if not isinstance(email, str):
        return JsonResponse({"detail": "Enter the recipient's email address."}, status=400)
    email = email.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"detail": "Enter a valid email address."}, status=400)
    if email == (request.user.email or "").strip().lower():
        return JsonResponse({"detail": "You cannot share an item with your own email address."}, status=400)

    User = get_user_model()
    recipients = User.objects.filter(email__iexact=email, is_active=True).order_by("pk")
    if not recipients.exists():
        return JsonResponse({"detail": "No active SecureDrive account uses this email. The recipient must register before sharing."}, status=404)
    if recipients.count() > 1:
        return JsonResponse({"detail": "More than one account uses this email address. Ask an administrator to resolve the duplicate email first."}, status=409)
    recipient = recipients.first()

    permission = payload.get("permission", Share.Permission.VIEWER)
    if permission not in {Share.Permission.VIEWER, Share.Permission.EDITOR}:
        return JsonResponse({"detail": "Permission must be viewer or editor."}, status=400)

    shared_count = 0
    with transaction.atomic():
        for drive_file in direct_files:
            Share.objects.update_or_create(
                file=drive_file,
                receiver=recipient,
                defaults={"tenant": tenant, "owner": request.user, "permission": permission},
            )
            shared_count += 1
        for folder in top_folders:
            Share.objects.update_or_create(
                folder=folder,
                receiver=recipient,
                defaults={"tenant": tenant, "owner": request.user, "permission": permission},
            )
            shared_count += 1

    permission_label = dict(Share.Permission.choices).get(permission, "Viewer")
    log_action(
        request.user,
        ActivityLog.Action.SHARE,
        f"Shared {shared_count} Drive item(s) with {recipient.email or recipient.username} as {permission_label}",
        workspace=workspace,
    )

    # Send a lightweight notification when SMTP is explicitly configured. Sharing
    # permissions remain valid if mail is unavailable; that failure is reported.
    notification_sent = False
    if getattr(settings, "EMAIL_HOST", ""):
        frontend_url = getattr(settings, "NEXTJS_FRONTEND_URL", "http://localhost:3000").rstrip("/")
        subject = f"{request.user.get_username()} shared items with you on SecureDrive"
        message = (
            f"{request.user.get_username()} shared {shared_count} item(s) with you as {permission_label}.\n\n"
            f"Open SecureDrive: {frontend_url}/drive/shared\n\n"
            "Sign in with this email address to access the shared items."
        )
        try:
            notification_sent = bool(send_mail(
                subject,
                message,
                getattr(settings, "DEFAULT_FROM_EMAIL", None),
                [recipient.email],
                fail_silently=True,
            ))
        except Exception:
            notification_sent = False

    detail = f"Shared {shared_count} item(s) with {recipient.email or recipient.username} as {permission_label}."
    if notification_sent:
        detail += " Email notification sent."
    else:
        detail += " Access was granted, but an email notification was not sent; configure and verify outgoing email to notify the recipient."
    return JsonResponse({
        "detail": detail,
        "count": shared_count,
        "email": recipient.email,
        "permission": permission,
        "notification_sent": notification_sent,
    })
