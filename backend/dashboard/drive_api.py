"""JSON endpoints for the Next.js Drive file browser.

The classic Django templates use redirect-based bulk actions. These endpoints
provide explicit JSON responses for the SPA while reusing the same ownership,
tenant and folder-tree rules.
"""
import hashlib
import json
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import active_tenant_required as login_required, get_default_tenant
from files.models import File
from files.quota import QuotaExceeded, QuotaStateError
from files.services import unique_copy_name
from folders.models import Folder
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


def _items_for_operation(payload, request, tenant):
    try:
        file_ids = _positive_ids(payload, "file_ids")
        folder_ids = _positive_ids(payload, "folder_ids")
    except ValueError as error:
        return None, JsonResponse({"detail": str(error)}, status=400)
    if not file_ids and not folder_ids:
        return None, JsonResponse({"detail": "Select at least one file or folder."}, status=400)

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
    if len(files) != len(file_ids) or len(folders) != len(folder_ids):
        return None, JsonResponse({"detail": "One or more selected items are no longer available or accessible."}, status=404)

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
    tenant = get_default_tenant(request.user)
    if tenant is None:
        raise Http404
    selected, error = _items_for_operation(payload, request, tenant)
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
    log_action(request.user, ActivityLog.Action.MOVE, f"Moved {len(direct_files)} file(s) and {len(top_folders)} folder(s)")
    return JsonResponse({"detail": f"Moved {moved_count} item(s).", "count": moved_count})


def _duplicate_encrypted_file(source_file, *, actor, tenant, target_folder, target_name):
    """Re-encrypt a duplicate for its new file ID and store it with current MinIO finalization."""
    from files.finalization import finalize_verified_upload
    from files.models import FileVersion, StorageLocation, UploadSession
    from files.quota import finalize_upload_quota, reserve_upload_quota
    from files.storage_adapters import get_storage_adapter
    from files.views import _decrypt_file

    plaintext = _decrypt_file(source_file)
    session = UploadSession.objects.create(
        tenant=tenant,
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
    tenant = get_default_tenant(request.user)
    if tenant is None:
        raise Http404
    selected, error = _items_for_operation(payload, request, tenant)
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
                    owner=request.user,
                    folder_name=_unique_copy_folder_name(request.user, tenant, source_folder.parent, source_folder.folder_name),
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
                        folder=original,
                        deleted_at__isnull=True,
                    ).select_related("folder")
                    for source_file in source_files_in_folder:
                        duplicated, object_key = _duplicate_encrypted_file(
                            source_file,
                            actor=request.user,
                            tenant=tenant,
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
                )
                duplicated, object_key = _duplicate_encrypted_file(
                    source_file,
                    actor=request.user,
                    tenant=tenant,
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

    log_action(request.user, ActivityLog.Action.COPY, f"Duplicated {created_count} Drive item(s)")
    return JsonResponse({"detail": f"Duplicated {created_count} item(s).", "count": created_count})
