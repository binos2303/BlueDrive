import io
import zipfile
from datetime import timedelta
from cryptography.exceptions import InvalidTag
from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.core.files.base import ContentFile
import uuid
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.access import (
    active_tenant_ids,
    active_tenant_required as login_required,
    get_default_tenant,
)
from securedrive.frontend_redirects import redirect_to_frontend

from files.models import File
from files.models import UploadSession
from files.quota import (
    QuotaExceeded,
    QuotaStateError,
    finalize_upload_quota,
    reserve_upload_quota,
)
from files.services import clone_encrypted_file_with_quota, unique_copy_name
from files.forms import FileUploadForm
from security.aes_service import (
    build_file_aad,
    decrypt_bytes,
    encrypt_bytes,
    generate_dek,
    get_master_key,
    unwrap_dek,
    wrap_dek,
)
from security.hash_service import verify_sha256
from sharing.services import (
    can_edit_destination_folder,
    can_edit_folder,
    can_edit_folder_tree,
    can_view_folder,
    get_receiver_share_for_file,
    get_receiver_share_for_folder,
    is_descendant_or_same,
)

from .forms import FolderCreateForm
from .models import Folder
from logs.models import ActivityLog
from logs.services import get_last_activity, log_action


def _subtree(folder, *, include_deleted=None):
    """Return folder and all descendants owned by the same user."""
    result = [folder]
    index = 0
    while index < len(result):
        current = result[index]
        queryset = Folder.objects.filter(
            owner=folder.owner,
            tenant=folder.tenant,
            parent=current,
        )
        if include_deleted is True:
            queryset = queryset.filter(deleted_at__isnull=False)
        elif include_deleted is False:
            queryset = queryset.filter(deleted_at__isnull=True)
        result.extend(queryset)
        index += 1
    return result


def _folder_contains(source, candidate):
    """Return True when candidate is source or a descendant of source."""
    current = candidate
    while current is not None:
        if current.id == source.id:
            return True
        current = current.parent
    return False


def _unique_folder_name(owner, tenant, parent, original_name):
    candidate = f"{original_name} (copy)"
    number = 2
    while Folder.objects.filter(
        owner=owner,
        tenant=tenant,
        parent=parent,
        folder_name__iexact=candidate,
        deleted_at__isnull=True,
    ).exists():
        candidate = f"{original_name} (copy {number})"
        number += 1
    return candidate


@login_required
@require_POST
def folder_rename(request, folder_id):
    folder = get_object_or_404(
        Folder,
        id=folder_id,
        deleted_at__isnull=True,
    )
    if not can_edit_folder(folder, request.user):
        messages.error(request, "You do not have permission to rename this folder.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    folder_name = request.POST.get("folder_name", "").strip()
    if not folder_name:
        messages.error(request, "Folder name cannot be empty.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))
    if len(folder_name) > 255:
        messages.error(request, "Folder name is too long.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    duplicate = Folder.objects.filter(
        owner=folder.owner,
        tenant=folder.tenant,
        parent=folder.parent,
        folder_name__iexact=folder_name,
        deleted_at__isnull=True,
    ).exclude(id=folder.id).exists()
    if duplicate:
        messages.error(request, "A folder with this name already exists here.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    old_name = folder.folder_name
    folder.folder_name = folder_name
    folder.save(update_fields=["folder_name", "updated_at"])
    log_action(request.user, ActivityLog.Action.RENAME, f"Renamed folder from {old_name} to {folder.folder_name}", obj=folder)
    messages.success(request, "Folder renamed successfully.")
    return redirect("folder_open", folder_id=folder.parent_id) if folder.parent_id else redirect("shared_with_me" if folder.owner_id != request.user.id else "dashboard")


@login_required
@require_POST
def folder_delete(request, folder_id):
    folder = get_object_or_404(
        Folder,
        id=folder_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=True,
    )
    deleted_time = timezone.now()
    subtree = _subtree(folder, include_deleted=False)
    folder_ids = [item.id for item in subtree]

    with transaction.atomic():
        Folder.objects.filter(id__in=folder_ids, owner=request.user, tenant=folder.tenant).update(deleted_at=deleted_time)
        File.objects.filter(
            owner=request.user,
            tenant=folder.tenant,
            folder_id__in=folder_ids,
            deleted_at__isnull=True,
        ).update(deleted_at=deleted_time)

    log_action(request.user, ActivityLog.Action.DELETE, f"Moved folder to Trash: {folder.folder_name}", obj=folder)
    messages.success(request, f'"{folder.folder_name}" moved to Trash.')
    return redirect("folder_open", folder_id=folder.parent_id) if folder.parent_id else redirect("dashboard")


@login_required
@require_POST
def folder_restore(request, folder_id):
    folder = get_object_or_404(
        Folder,
        id=folder_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=False,
    )

    if folder.parent_id and folder.parent.deleted_at is not None:
        messages.warning(request, "Restore the parent folder first.")
        return redirect("trash")

    subtree = _subtree(folder, include_deleted=True)
    folder_ids = [item.id for item in subtree]

    # Check every restored folder/file for live-name conflicts.
    restored_folder_ids = {item.id for item in subtree}
    for restored_folder in subtree:
        if Folder.objects.filter(
            owner=request.user,
            tenant=folder.tenant,
            parent=restored_folder.parent,
            folder_name__iexact=restored_folder.folder_name,
            deleted_at__isnull=True,
        ).exclude(id__in=restored_folder_ids).exists():
            messages.error(request, f'A folder named "{restored_folder.folder_name}" already exists at the destination.')
            return redirect("trash")

    for restored_file in File.objects.filter(
        owner=request.user,
        tenant=folder.tenant,
        folder_id__in=restored_folder_ids,
        deleted_at__isnull=False,
    ):
        if File.objects.filter(
            owner=request.user,
            tenant=folder.tenant,
            folder=restored_file.folder,
            file_name__iexact=restored_file.file_name,
            deleted_at__isnull=True,
        ).exists():
            messages.error(request, f'A file named "{restored_file.file_name}" already exists in a restored folder.')
            return redirect("trash")

    with transaction.atomic():
        Folder.objects.filter(id__in=folder_ids, owner=request.user, tenant=folder.tenant).update(deleted_at=None)
        File.objects.filter(
            owner=request.user,
            tenant=folder.tenant,
            folder_id__in=folder_ids,
            deleted_at__isnull=False,
        ).update(deleted_at=None)

    log_action(request.user, ActivityLog.Action.RESTORE, f"Restored folder: {folder.folder_name}", obj=folder)
    messages.success(request, f'"{folder.folder_name}" restored successfully.')
    return redirect("trash")


@login_required
@require_POST
def folder_delete_permanently(request, folder_id):
    folder = get_object_or_404(
        Folder,
        id=folder_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=False,
    )
    subtree = _subtree(folder, include_deleted=True)
    folder_ids = [item.id for item in subtree]
    files = File.objects.filter(owner=request.user, tenant=folder.tenant, folder_id__in=folder_ids)

    for file in files:
        try:
            if file.file_path:
                file.file_path.delete(save=False)
        except Exception:
            pass

    files.delete()
    folder_name = folder.folder_name
    Folder.objects.filter(id__in=folder_ids, owner=request.user, tenant=folder.tenant).delete()
    log_action(request.user, ActivityLog.Action.PERMANENT_DELETE, f"Permanently deleted folder: {folder_name}", obj=folder)
    messages.success(request, f'"{folder_name}" permanently deleted.')
    return redirect("trash")


@login_required
@require_POST
def folder_upload(request):
    """Upload a complete browser-selected directory tree (webkitdirectory)."""
    uploaded_files = request.FILES.getlist("files")
    relative_paths = request.POST.getlist("relative_paths")
    parent_id = request.POST.get("parent") or None
    parent = None
    if parent_id:
        parent = get_object_or_404(Folder, id=parent_id, deleted_at__isnull=True)
        if not can_edit_folder(parent, request.user):
            messages.error(request, "You do not have permission to upload a folder here.")
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))
    if not uploaded_files or len(uploaded_files) != len(relative_paths):
        messages.error(request, "The selected folder could not be read correctly.")
        return redirect("folder_open", folder_id=parent.id) if parent else redirect("dashboard")

    # Use the first path component as the new root folder name.
    parts = [path.replace("\\", "/").split("/") for path in relative_paths if path]
    root_name = parts[0][0] if parts and parts[0] else "Uploaded folder"
    root_name = root_name.strip() or "Uploaded folder"
    resource_owner = parent.owner if parent is not None else request.user
    tenant = parent.tenant if parent is not None else get_default_tenant(request.user)
    candidate = root_name
    number = 2
    while Folder.objects.filter(owner=resource_owner, tenant=tenant, parent=parent, folder_name__iexact=candidate, deleted_at__isnull=True).exists():
        candidate = f"{root_name} (copy {number})"
        number += 1

    folder_cache = {
        "": Folder.objects.create(
            tenant=tenant,
            owner=resource_owner,
            parent=parent,
            folder_name=candidate,
        )
    }
    uploaded_count = 0
    failed_count = 0

    try:
        for uploaded_file, relative_path in zip(uploaded_files, relative_paths):
            normalized = relative_path.replace("\\", "/").strip("/")
            components = [part for part in normalized.split("/") if part]
            if not components:
                failed_count += 1
                continue
            # Ignore the root component because it was created above.
            directory_parts = components[1:-1]
            current_key = ""
            current_folder = folder_cache[""]
            for component in directory_parts:
                current_key = f"{current_key}/{component}" if current_key else component
                if current_key not in folder_cache:
                    folder_cache[current_key] = Folder.objects.create(
                        tenant=tenant,
                        owner=resource_owner,
                        parent=current_folder,
                        folder_name=component,
                    )
                current_folder = folder_cache[current_key]

            post_data = request.POST.copy()
            post_data["folder"] = str(current_folder.id)
            one_file_data = request.FILES.copy()
            one_file_data.setlist("file_path", [uploaded_file])
            form = FileUploadForm(post_data, one_file_data, user=resource_owner)
            if not form.is_valid():
                failed_count += 1
                continue
            uploaded = form.cleaned_data["file_path"]
            if File.objects.filter(owner=resource_owner, tenant=tenant, folder=current_folder, file_name__iexact=uploaded.name, deleted_at__isnull=True).exists():
                failed_count += 1
                continue

            drive_file = None
            stored_name = None
            upload_session = None
            quota_reserved = False
            try:
                upload_session = UploadSession.objects.create(
                    tenant=tenant,
                    initiated_by=request.user,
                    target_folder=current_folder,
                    client_name=uploaded.name[:255],
                    expected_size_bytes=uploaded.size,
                    expires_at=timezone.now() + timedelta(hours=1),
                )
                reserve_upload_quota(upload_session.pk, request.user)
                quota_reserved = True
                uploaded.seek(0)
                plaintext = uploaded.read()
                drive_file = File(
                    tenant=tenant,
                    owner=resource_owner,
                    folder=current_folder,
                    file_name=uploaded.name,
                    file_size=uploaded.size,
                    mime_type=form.detected_mime_type,
                    hash_sha256=form.sha256,
                    is_encrypted=True,
                    encryption_version=1,
                )
                drive_file.save()
                aad = build_file_aad(owner_id=resource_owner.id, file_id=drive_file.id, version=drive_file.encryption_version)
                dek = generate_dek()
                ciphertext, nonce = encrypt_bytes(plaintext, dek, aad)
                wrapped_dek, dek_nonce = wrap_dek(dek, get_master_key())
                drive_file.file_path.save(f"{uuid.uuid4().hex}.enc", ContentFile(ciphertext), save=False)
                stored_name = drive_file.file_path.name
                drive_file.encryption_nonce = nonce
                drive_file.wrapped_dek = wrapped_dek
                drive_file.dek_nonce = dek_nonce
                drive_file.save(update_fields=["file_path", "encryption_nonce", "wrapped_dek", "dek_nonce", "updated_at"])
                with transaction.atomic():
                    finalize_upload_quota(
                        upload_session.pk,
                        completed=True,
                        actual_size_bytes=uploaded.size,
                        actor=request.user,
                    )
                    upload_session.file = drive_file
                    upload_session.state = UploadSession.State.COMPLETED
                    upload_session.completed_at = timezone.now()
                    upload_session.save(
                        update_fields=["file", "state", "completed_at", "updated_at"]
                    )
                quota_reserved = False
                uploaded_count += 1
            except (QuotaExceeded, QuotaStateError):
                failed_count += 1
                messages.error(
                    request,
                    f"{uploaded.name}: upload exceeds the available workspace quota or is not authorized.",
                )
                if quota_reserved and upload_session is not None:
                    finalize_upload_quota(
                        upload_session.pk,
                        completed=False,
                    )
                if upload_session is not None:
                    upload_session.state = UploadSession.State.FAILED
                    upload_session.failure_code = "quota_or_access_denied"
                    upload_session.save(
                        update_fields=["state", "failure_code", "updated_at"]
                    )
                if stored_name and drive_file is not None:
                    try:
                        drive_file.file_path.storage.delete(stored_name)
                    except Exception:
                        pass
                if drive_file is not None:
                    drive_file.delete()
            except Exception:
                failed_count += 1
                messages.error(request, f"{uploaded.name}: upload failed.")
                if quota_reserved and upload_session is not None:
                    finalize_upload_quota(
                        upload_session.pk,
                        completed=False,
                    )
                if upload_session is not None:
                    upload_session.state = UploadSession.State.FAILED
                    upload_session.failure_code = "upload_failed"
                    upload_session.save(
                        update_fields=["state", "failure_code", "updated_at"]
                    )
                if stored_name and drive_file is not None:
                    try:
                        drive_file.file_path.storage.delete(stored_name)
                    except Exception:
                        pass
                if drive_file is not None:
                    drive_file.delete()

        log_action(request.user, ActivityLog.Action.UPLOAD, f"Uploaded folder tree: {candidate}", obj=folder_cache[""])
    except Exception:
        folder_cache[""].delete()
        messages.error(request, "Folder upload could not be completed.")
        return redirect("folder_open", folder_id=parent.id) if parent else redirect("dashboard")

    # Folder upload completes silently; errors are still reported above.
    return redirect("folder_open", folder_id=parent.id) if parent else redirect("dashboard")


@login_required
@require_POST
def folder_create(request):
    parent_id = request.POST.get("parent") or None
    parent = None
    if parent_id:
        parent = get_object_or_404(Folder, id=parent_id, deleted_at__isnull=True)
        if not can_edit_folder(parent, request.user):
            messages.error(request, "You do not have permission to create a folder here.")
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    form_user = parent.owner if parent is not None else request.user
    form = FolderCreateForm(request.POST, user=form_user)
    if form.is_valid():
        folder = form.save(commit=False)
        resource_owner = parent.owner if parent is not None else request.user
        folder.owner = resource_owner
        folder.tenant = parent.tenant if parent is not None else get_default_tenant(request.user)
        folder.parent = parent
        if folder.parent is not None and folder.parent.deleted_at is not None:
            messages.error(request, "Invalid parent folder.")
            return redirect("dashboard")
        if Folder.objects.filter(
            owner=resource_owner,
            tenant=folder.tenant,
            parent=folder.parent,
            folder_name__iexact=folder.folder_name.strip(),
            deleted_at__isnull=True,
        ).exists():
            messages.error(request, "A folder with this name already exists here.")
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))
        folder.folder_name = folder.folder_name.strip()
        folder.save()
        log_action(request.user, ActivityLog.Action.CREATE_FOLDER, f"Created folder: {folder.folder_name}", obj=folder)
        messages.success(request, f'Folder "{folder.folder_name}" created successfully.')
        return redirect("folder_open", folder_id=folder.parent_id) if folder.parent_id else redirect("dashboard")

    messages.error(request, "Unable to create folder. Please check the folder name.")
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
@require_POST
def folder_create_api(request):
    """Create a folder and return JSON for the Next.js drive UI."""
    import json

    if not request.content_type or "application/json" not in request.content_type:
        return JsonResponse(
            {"error": "Content-Type must be application/json."},
            status=415,
        )

    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    name = data.get("name")
    parent_id = data.get("parent_id")

    if not isinstance(name, str) or not name.strip():
        return JsonResponse({"error": "Folder name is required."}, status=400)

    name = name.strip()
    if len(name) > 255 or "/" in name or "\\" in name:
        return JsonResponse({"error": "Invalid folder name."}, status=400)

    parent = None
    if parent_id not in (None, ""):
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid parent folder."}, status=400)

        parent = get_object_or_404(
            Folder,
            id=parent_id,
            deleted_at__isnull=True,
        )

        if not can_edit_folder(parent, request.user):
            return JsonResponse(
                {"error": "You do not have permission to create a folder here."},
                status=403,
            )

    resource_owner = parent.owner if parent else request.user
    tenant = parent.tenant if parent else get_default_tenant(request.user)

    if Folder.objects.filter(
        owner=resource_owner,
        tenant=tenant,
        parent=parent,
        folder_name__iexact=name,
        deleted_at__isnull=True,
    ).exists():
        return JsonResponse(
            {"error": "A folder with this name already exists here."},
            status=409,
        )

    try:
        with transaction.atomic():
            folder = Folder.objects.create(
                owner=resource_owner,
                tenant=tenant,
                parent=parent,
                folder_name=name,
            )
    except Exception:
        # Do not expose database details to the client.
        return JsonResponse(
            {"error": "Could not create the folder."},
            status=400,
        )

    log_action(
        request.user,
        ActivityLog.Action.CREATE_FOLDER,
        f"Created folder: {folder.folder_name}",
        obj=folder,
    )

    return JsonResponse(
        {
            "id": folder.id,
            "name": folder.folder_name,
            "parent_id": folder.parent_id,
            "type": "folder",
        },
        status=201,
    )


@login_required
def folder_download(request, folder_id):
    """Download a shared folder as a ZIP. Owner and shared recipients are allowed."""
    folder = get_object_or_404(Folder, id=folder_id)
    is_owner = folder.owner_id == request.user.id
    if not can_view_folder(folder, request.user):
        raise Http404

    if not is_owner and get_receiver_share_for_folder(folder, request.user) is None:
        raise Http404

    tree = _subtree(folder, include_deleted=False)
    folder_ids = [item.id for item in tree]

    files = File.objects.filter(
        owner=folder.owner,
        tenant=folder.tenant,
        folder_id__in=folder_ids,
    ).order_by("folder_id", "file_name")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for drive_file in files:
            if drive_file.deleted_at is not None:
                continue
            if not drive_file.file_path or not drive_file.is_encrypted:
                continue
            try:
                dek = unwrap_dek(
                    bytes(drive_file.wrapped_dek),
                    bytes(drive_file.dek_nonce),
                    get_master_key(),
                )
                aad = build_file_aad(
                    owner_id=drive_file.owner_id,
                    file_id=drive_file.id,
                    version=drive_file.encryption_version,
                )
                with drive_file.file_path.open("rb") as stored:
                    plaintext = decrypt_bytes(
                        stored.read(),
                        bytes(drive_file.encryption_nonce),
                        dek,
                        aad,
                    )
                if drive_file.hash_sha256 and not verify_sha256(plaintext, drive_file.hash_sha256):
                    raise ValueError("integrity")
                current = drive_file.folder
                parts = []
                while current is not None and current.id != folder.id:
                    parts.insert(0, current.folder_name)
                    current = current.parent
                archive_path = "/".join(parts + [drive_file.file_name])
                archive.writestr(archive_path, plaintext)
            except Exception:
                continue

    buffer.seek(0)
    log_action(request.user, ActivityLog.Action.DOWNLOAD, f"Downloaded folder: {folder.folder_name}", obj=folder)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{folder.folder_name}.zip",
        content_type="application/zip",
    )


@login_required
def folder_open(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    if not can_view_folder(folder, request.user):
        raise Http404

    log_action(
        request.user,
        ActivityLog.Action.VIEW,
        f"Opened folder: {folder.folder_name}",
        obj=folder,
    )
    return redirect_to_frontend("/drive", {"folder": folder_id})

@login_required
def folder_details(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    is_owner = folder.owner_id == request.user.id
    share = None
    if not can_view_folder(folder, request.user):
        raise Http404
    if not is_owner:
        # A shared resource follows the same lifecycle rule as the drive view:
        # once the owner moves it to Trash, recipients must lose all access,
        # including metadata/details endpoints.
        if folder.deleted_at is not None:
            raise Http404
        share = get_receiver_share_for_folder(folder, request.user)
        if share is None:
            raise Http404

    activity = get_last_activity(folder)
    descendants = _subtree(folder, include_deleted=False)
    descendant_ids = [item.id for item in descendants]
    folder_count = max(len(descendants) - 1, 0)
    file_count = File.objects.filter(
        owner=folder.owner,
        tenant=folder.tenant,
        folder_id__in=descendant_ids,
        deleted_at__isnull=True,
    ).count()

    ancestors = []

    if is_owner or not share or share.folder_id != folder.id:
        current = folder.parent
        reverse_ancestors = []

        while current is not None:
            # Preserve the existing shared-folder access boundary.
            if (
                not is_owner
                and share
                and current.id == share.folder_id
            ):
                break

            reverse_ancestors.append({
                "id": current.id,
                "name": current.folder_name,
            })
            current = current.parent

        ancestors = list(reversed(reverse_ancestors))

    parts = [item["name"] for item in ancestors]

    location_root = "My Drive" if is_owner else "Shared with me"
    location = location_root + (
        " / " + " / ".join(parts) if parts else ""
    )
    return JsonResponse({
        "type": "folder",
        "name": folder.folder_name,
        "owner": folder.owner.username,
        "created_at": folder.created_at.strftime("%b %d, %Y, %I:%M %p"),
        "modified_at": folder.updated_at.strftime("%b %d, %Y, %I:%M %p"),
        "location": location,
        "ancestors": ancestors,
        "folder_count": folder_count,
        "file_count": file_count,
        "access": "Owner" if is_owner else share.permission_label,
        "shared_by": None if is_owner else share.owner.username,
        "last_action": activity.get_action_display() if activity else "No recorded action",
    })

@login_required
def trash_folder_open(request, folder_id):
    get_object_or_404(
        Folder,
        id=folder_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=False,
    )
    return redirect_to_frontend("/drive/trash", {"folder": folder_id})

@login_required
@require_POST
def folder_copy(request, folder_id):
    folder = get_object_or_404(
        Folder,
        id=folder_id,
        deleted_at__isnull=True,
    )
    if not can_edit_folder_tree(folder, request.user):
        messages.error(request, "You do not have permission to copy all contents of this folder.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    request.session["clipboard"] = {"type": "folder", "folder_id": folder.id}
    request.session.modified = True
    log_action(request.user, ActivityLog.Action.COPY, f"Copied folder to clipboard: {folder.folder_name}", obj=folder)
    messages.success(request, f'"{folder.folder_name}" copied to clipboard.')
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
@require_POST
def folder_cut(request, folder_id):
    folder = get_object_or_404(
        Folder,
        id=folder_id,
        deleted_at__isnull=True,
    )
    if not can_edit_folder_tree(folder, request.user):
        messages.error(request, "You do not have permission to move all contents of this folder.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    request.session["clipboard"] = {"type": "folder_cut", "folder_id": folder.id}
    request.session.modified = True
    log_action(request.user, ActivityLog.Action.CUT, f"Cut folder: {folder.folder_name}", obj=folder)
    messages.success(request, f'"{folder.folder_name}" has been cut.')
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
@require_POST
def folder_paste(request):
    clipboard = request.session.get("clipboard")
    if not clipboard or clipboard.get("type") not in {"folder", "folder_cut"}:
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    source = get_object_or_404(
        Folder,
        id=clipboard.get("folder_id"),
        deleted_at__isnull=True,
    )
    if not can_edit_folder_tree(source, request.user):
        messages.error(request, "You no longer have permission to edit all contents of this folder.")
        request.session.pop("clipboard", None)
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    source_share = get_receiver_share_for_folder(source, request.user) if source.owner_id != request.user.id else None
    shared_root = source_share.folder if source_share and source_share.folder_id else None

    folder_id = request.POST.get("folder_id")
    destination = None
    if folder_id:
        destination = get_object_or_404(
            Folder,
            id=folder_id,
            tenant=source.tenant,
            deleted_at__isnull=True,
        )

    if source.owner_id != request.user.id:
        if not can_edit_destination_folder(destination, request.user, shared_root=shared_root):
            messages.error(request, "Editors can only paste shared folders inside the shared folder.")
            return redirect(request.META.get("HTTP_REFERER", "shared_with_me"))
        if destination is not None and destination.owner_id != source.owner_id:
            messages.error(request, "The destination is not part of the shared resource.")
            return redirect(request.META.get("HTTP_REFERER", "shared_with_me"))

    if destination and is_descendant_or_same(destination, source):
        messages.error(request, "A folder cannot be moved or copied into itself or one of its descendants.")
        return redirect("folder_open", folder_id=destination.id)

    if source.parent_id == (destination.id if destination else None):
        messages.info(request, "Folder is already in this location.")
        request.session.pop("clipboard", None)
        return redirect("folder_open", folder_id=destination.id) if destination else redirect("dashboard")

    if clipboard["type"] == "folder_cut":
        if Folder.objects.filter(
            owner=source.owner,
            tenant=source.tenant,
            parent=destination,
            folder_name__iexact=source.folder_name,
            deleted_at__isnull=True,
        ).exclude(id=source.id).exists():
            messages.error(request, "A folder with the same name already exists in the destination.")
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))
        source.parent = destination
        source.save(update_fields=["parent", "updated_at"])
        request.session.pop("clipboard", None)
        log_action(request.user, ActivityLog.Action.MOVE, f"Moved folder: {source.folder_name}", obj=source)
        messages.success(request, f'"{source.folder_name}" moved successfully.')
        return redirect("folder_open", folder_id=destination.id) if destination else redirect("dashboard")

    if source.owner_id != request.user.id:
        messages.error(
            request,
            "Copying a shared folder requires a workspace quota allocation for your account.",
        )
        return redirect(request.META.get("HTTP_REFERER", "shared_with_me"))

    tenant = destination.tenant if destination is not None else source.tenant
    root_name = _unique_folder_name(source.owner, tenant, destination, source.folder_name)
    created_files = []
    try:
        with transaction.atomic():
            folder_map = {source.id: Folder.objects.create(
                tenant=tenant,
                owner=source.owner,
                folder_name=root_name,
                parent=destination,
            )}
            original_tree = _subtree(source, include_deleted=False)
            for original in original_tree[1:]:
                parent_copy = folder_map[original.parent_id]
                folder_map[original.id] = Folder.objects.create(
                    tenant=tenant,
                    owner=source.owner,
                    folder_name=original.folder_name,
                    parent=parent_copy,
                )
            for original in original_tree:
                target_folder = folder_map[original.id]
                for source_file in File.objects.filter(
                    owner=source.owner,
                    tenant=source.tenant,
                    folder=original,
                    deleted_at__isnull=True,
                ):
                    file_name = source_file.file_name
                    if File.objects.filter(
                        owner=source.owner,
                        tenant=tenant,
                        folder=target_folder,
                        file_name__iexact=file_name,
                        deleted_at__isnull=True,
                    ).exists():
                        file_name = unique_copy_name(
                            File, "file_name", file_name, folder=target_folder, owner=source.owner
                        )
                    created_files.append(
                        clone_encrypted_file_with_quota(
                            source_file,
                            owner=source.owner,
                            folder=target_folder,
                            file_name=file_name,
                            tenant=tenant,
                        )
                    )
    except (QuotaExceeded, QuotaStateError):
        for created_file in created_files:
            if created_file.file_path:
                created_file.file_path.delete(save=False)
        messages.error(request, "The workspace or member quota does not allow this folder copy.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))
    except InvalidTag:
        for created_file in created_files:
            try:
                if created_file.file_path:
                    created_file.file_path.delete(save=False)
            except Exception:
                pass
        messages.error(request, "A file failed integrity verification. Folder copy was cancelled.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))
    except Exception:
        for created_file in created_files:
            try:
                if created_file.file_path:
                    created_file.file_path.delete(save=False)
            except Exception:
                pass
        messages.error(request, "Could not copy the folder.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    request.session.pop("clipboard", None)
    log_action(request.user, ActivityLog.Action.COPY, f"Copied folder tree: {source.folder_name}", obj=folder_map[source.id])
    messages.success(request, f'"{source.folder_name}" copied successfully.')
    return redirect("folder_open", folder_id=destination.id) if destination else redirect("dashboard")
