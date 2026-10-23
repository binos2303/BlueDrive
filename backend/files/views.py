import io
import uuid
import re
import unicodedata
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from securedrive.frontend_redirects import redirect_to_frontend
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from accounts.access import (
    active_tenant_ids,
    active_tenant_required as login_required,
    can_edit_workspace_content,
    get_default_tenant,
    resolve_request_workspace,
)
from folders.models import Folder
from sharing.services import (
    can_edit_destination_folder,
    can_edit_file,
    can_edit_folder,
    can_view_file,
    get_receiver_share_for_file,
)
from security.hash_service import verify_sha256
from security.aes_service import (
    build_file_aad,
    decrypt_bytes,
    encrypt_bytes,
    generate_dek,
    get_master_key,
    unwrap_dek,
    wrap_dek,
)

from .forms import FileRenameForm, FileUploadForm
from .models import File, FileVersion, StorageLocation, UploadSession
from .services import (
    clone_encrypted_file_with_quota,
    unique_copy_name,
    unique_upload_name,
)
from logs.models import ActivityLog
from logs.services import get_last_activity, log_action
from .quota import (
    QuotaExceeded,
    QuotaStateError,
    finalize_upload_quota,
    reserve_upload_quota,
)


@login_required
def file_upload(request):
    if request.method != "POST":
        return redirect("dashboard")

    uploaded_files = request.FILES.getlist("file_path")
    if not uploaded_files:
        messages.error(request, "Please select at least one file.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    folder_id = request.POST.get("folder") or request.POST.get("folder_id")
    folder = None
    if folder_id:
        folder = get_object_or_404(
            Folder,
            id=folder_id,
            deleted_at__isnull=True,
        )
        if not can_edit_folder(folder, request.user):
            messages.error(request, "You do not have permission to upload into this folder.")
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    uploaded_count = 0
    failed_count = 0

    for uploaded_file in uploaded_files:
        # Reuse the existing validation pipeline for every selected file.
        post_data = request.POST.copy()
        post_data["folder"] = str(folder.id) if folder else ""
        one_file_data = request.FILES.copy()
        one_file_data.setlist("file_path", [uploaded_file])
        form = FileUploadForm(
            post_data,
            one_file_data,
            user=folder.owner if folder is not None else request.user,
        )

        if not form.is_valid():
            failed_count += 1
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, f"{uploaded_file.name}: {error}")
            continue

        uploaded = form.cleaned_data["file_path"]
        target_folder = form.cleaned_data["folder"]
        if target_folder is not None and (
            target_folder.deleted_at is not None
            or not can_edit_folder(target_folder, request.user)
        ):
            failed_count += 1
            messages.error(request, f"{uploaded.name}: invalid destination folder.")
            continue

        resource_owner = target_folder.owner if target_folder is not None else request.user
        if target_folder is not None:
            tenant = target_folder.tenant
            workspace = target_folder.workspace
            requested_workspace_id = request.POST.get("workspace_id")
            if requested_workspace_id and str(requested_workspace_id) != str(workspace.pk):
                failed_count += 1
                messages.error(request, f"{uploaded.name}: destination belongs to a different workspace.")
                continue
        else:
            try:
                tenant = get_default_tenant(request.user)
                workspace = resolve_request_workspace(request, tenant)
                if workspace is not None:
                    tenant = workspace.tenant
            except Exception:
                tenant = None
                workspace = None
            if tenant is None or workspace is None or not can_edit_workspace_content(request.user, workspace):
                failed_count += 1
                messages.error(request, f"{uploaded.name}: editor access to an active workspace is required.")
                continue

        upload_name = unique_upload_name(
            File,
            "file_name",
            uploaded.name,
            folder=target_folder,
            owner=resource_owner,
            workspace=workspace,
        )

        drive_file = None
        stored_name = None
        upload_session = None
        quota_reserved = False
        try:
            upload_session = UploadSession.objects.create(
                tenant=tenant,
                workspace=workspace,
                initiated_by=request.user,
                target_folder=target_folder,
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
                workspace=workspace,
                owner=resource_owner,
                folder=target_folder,
                file_name=upload_name,
                file_size=uploaded.size,
                mime_type=form.detected_mime_type,
                hash_sha256=form.sha256,
                is_encrypted=True,
                encryption_version=1,
            )
            drive_file.save()

            aad = build_file_aad(
                owner_id=resource_owner.id,
                file_id=drive_file.id,
                version=drive_file.encryption_version,
            )
            dek = generate_dek()
            ciphertext, nonce = encrypt_bytes(plaintext, dek, aad)
            wrapped_dek, dek_nonce = wrap_dek(dek, get_master_key())

            drive_file.file_path.save(
                f"{uuid.uuid4().hex}.enc",
                ContentFile(ciphertext),
                save=False,
            )
            stored_name = drive_file.file_path.name
            drive_file.encryption_nonce = nonce
            drive_file.wrapped_dek = wrapped_dek
            drive_file.dek_nonce = dek_nonce
            drive_file.save(update_fields=[
                "file_path", "encryption_nonce", "wrapped_dek", "dek_nonce", "updated_at"
            ])
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

            log_action(request.user, ActivityLog.Action.UPLOAD, f"Uploaded and encrypted {drive_file.file_name}", obj=drive_file)
            log_action(request.user, ActivityLog.Action.ENCRYPT, f"Encrypted {drive_file.file_name} with AES-256-GCM", obj=drive_file)
            uploaded_count += 1
        except (QuotaExceeded, QuotaStateError):
            failed_count += 1
            if stored_name and drive_file is not None:
                drive_file.file_path.storage.delete(stored_name)
            if drive_file is not None:
                drive_file.delete()
            messages.error(
                request,
                f"{uploaded.name}: upload exceeds the available workspace quota or is not authorized.",
            )
            if upload_session is not None:
                if quota_reserved:
                    finalize_upload_quota(
                        upload_session.pk,
                        completed=False,
                    )
                upload_session.state = UploadSession.State.FAILED
                upload_session.failure_code = "quota_or_access_denied"
                upload_session.save(update_fields=["state", "failure_code", "updated_at"])
        except Exception:
            failed_count += 1
            if stored_name and drive_file is not None:
                try:
                    drive_file.file_path.storage.delete(stored_name)
                except Exception:
                    pass
            if drive_file is not None:
                drive_file.delete()
            if upload_session is not None:
                if quota_reserved:
                    finalize_upload_quota(
                        upload_session.pk,
                        completed=False,
                        actor=request.user,
                    )
                upload_session.state = UploadSession.State.FAILED
                upload_session.failure_code = "upload_failed"
                upload_session.save(update_fields=["state", "failure_code", "updated_at"])
            messages.error(request, f"{uploaded.name}: upload could not be completed.")

    if uploaded_count:
        messages.success(request, f"{uploaded_count} file(s) uploaded and encrypted successfully.")
    if failed_count:
        messages.warning(request, f"{failed_count} file(s) were not uploaded.")

    if folder is not None:
        return redirect("folder_open", folder_id=folder.id)
    return redirect("dashboard")


def _get_accessible_file(file_id, user):
    """
    Resolve file access without treating soft-delete as permanent deletion.

    Owner:
      - can access only live files through normal file endpoints.
    Shared receiver:
      - may access live files while the Share exists.
      - a soft-deleted file is unavailable to recipients until restored.
      - shared access always permits view and download.
    """
    drive_file = get_object_or_404(File, id=file_id)

    is_owner = drive_file.owner_id == user.id
    share = None if is_owner else get_receiver_share_for_file(drive_file, user)
    if not can_view_file(drive_file, user):
        raise Http404

    return drive_file, is_owner, share


def _current_primary_storage_location(drive_file, version=None):
    """Return the current version's active PRIMARY location, if one exists."""
    from .models import StorageLocation

    if version is None:
        version = drive_file.versions.filter(is_current=True).first()
    if version is None:
        return None

    return (
        StorageLocation.objects.filter(
            tenant_id=drive_file.tenant_id,
            file_version=version,
            state=StorageLocation.State.AVAILABLE,
            object_ref__startswith="primary/",
        )
        .select_related("storage_config")
        .order_by("-created_at")
        .first()
    )


def _download_block_reason(drive_file):
    """Return a user-safe reason unless the current version is published to PRIMARY."""
    versions = drive_file.versions.all()
    if not versions.exists():
        # Compatibility for legacy local-media files that predate StorageLocation.
        return None if drive_file.file_path else "File storage is unavailable. Contact support."

    version = versions.filter(is_current=True).first()
    if version is None:
        return "This file is still being prepared. Try again later."
    if version.state == "scanning":
        return "This file is being security-scanned and cannot be downloaded yet."
    if version.state == "quarantined":
        return "This file was quarantined by a security check. Contact support if you think this is a mistake."
    if version.state == "failed":
        return "This file could not be prepared for download. Contact support."
    if version.state != "available":
        return "This file is still being prepared. Try again later."

    location = _current_primary_storage_location(drive_file, version)
    if location is None:
        # Do not make a STAGING, QUARANTINE, or legacy FINAL object downloadable.
        return "This file has not been published to primary storage yet. Contact support if the problem persists."
    if location.storage_config is None or location.storage_config.status != "active":
        return "This file's storage is temporarily unavailable. Retry later."
    return None


def _unavailable_download_response(request, reason, *, is_owner=True):
    if "application/json" in request.headers.get("Accept", ""):
        response = JsonResponse({"detail": reason}, status=409)
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response
    messages.warning(request, reason)
    return redirect("dashboard" if is_owner else "shared_with_me")


def _download_failure_response(request, *, is_owner, status, reason):
    if "application/json" in request.headers.get("Accept", ""):
        response = JsonResponse({"detail": reason}, status=status)
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response
    messages.error(request, reason)
    return redirect("dashboard" if is_owner else "shared_with_me")


def _safe_content_type(mime_type):
    """Return only a simple, syntactically safe media type; otherwise force download."""
    candidate = (mime_type or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", candidate):
        return "application/octet-stream"
    return candidate


def _safe_download_filename(filename):
    name = (filename or "download").replace("/", "_").replace("\\", "_")
    name = "".join(
        character
        for character in name
        if unicodedata.category(character) not in {"Cc", "Cf"}
    ).strip()
    return name[:255] or "download"


def _decrypt_file(drive_file):
    """Read a live file, decrypting legacy encrypted objects only when required.

    New uploads are intentionally stored as plaintext for the current MVP phase.
    Existing encrypted files remain readable using their persisted DEK metadata.
    The name is retained for compatibility with preview/share/copy callers.
    """
    current_version = drive_file.versions.filter(is_current=True).first()
    # If either metadata layer says encrypted, never downgrade to plaintext mode.
    version_is_encrypted = bool(
        drive_file.is_encrypted
        or (current_version is not None and current_version.is_encrypted)
    )
    try:
        if current_version is None:
            # Legacy files may still be stored in Django MEDIA_ROOT.
            if not drive_file.file_path:
                raise Http404
            with drive_file.file_path.open("rb") as stored_file:
                stored_bytes = stored_file.read()
            expected_sha256 = drive_file.hash_sha256
            encryption_nonce = drive_file.encryption_nonce
            wrapped_dek = drive_file.wrapped_dek
            dek_nonce = drive_file.dek_nonce
            encryption_version = drive_file.encryption_version
        else:
            if current_version.state != FileVersion.State.AVAILABLE:
                raise Http404
            location = _current_primary_storage_location(drive_file, current_version)
            if (
                location is None
                or location.storage_config is None
                or location.storage_config.status != "active"
            ):
                raise Http404
            from .storage_adapters import get_storage_adapter

            with get_storage_adapter().open_object(location.object_ref) as stored_file:
                stored_bytes = stored_file.read()
            expected_sha256 = current_version.sha256 or drive_file.hash_sha256
            encryption_nonce = current_version.encryption_nonce or drive_file.encryption_nonce
            wrapped_dek = current_version.wrapped_dek or drive_file.wrapped_dek
            dek_nonce = current_version.dek_nonce or drive_file.dek_nonce
            encryption_version = current_version.encryption_version or drive_file.encryption_version

        if version_is_encrypted:
            if not encryption_nonce or not wrapped_dek or not dek_nonce:
                raise Http404
            master_key = get_master_key()
            dek = unwrap_dek(bytes(wrapped_dek), bytes(dek_nonce), master_key)
            aad = build_file_aad(
                owner_id=drive_file.owner_id,
                file_id=drive_file.id,
                version=encryption_version,
            )
            plaintext = decrypt_bytes(stored_bytes, bytes(encryption_nonce), dek, aad)
        else:
            plaintext = stored_bytes

        if expected_sha256 and not verify_sha256(plaintext, expected_sha256):
            raise InvalidTag
        return plaintext
    except (InvalidTag, Http404):
        raise
    except Exception as exc:
        # Keep the original storage/configuration exception available for server
        # logging and let the download/preview view turn it into a safe response.
        raise exc


@login_required
def file_view(request, file_id):
    """
    View a file inline.

    Owners and shared recipients can view live files.
    Shared access also permits downloading through the download endpoint.
    """
    drive_file, is_owner, _share = _get_accessible_file(file_id, request.user)
    block_reason = _download_block_reason(drive_file)
    if block_reason:
        return _unavailable_download_response(
            request, block_reason, is_owner=is_owner
        )
    mime_type = _safe_content_type(drive_file.mime_type)
    if mime_type not in {
        "image/jpeg", "image/png", "image/gif", "image/webp", "text/plain",
    }:
        return _unavailable_download_response(
            request,
            "Preview is not available for this file type. Download the file instead.",
            is_owner=is_owner,
        )
    try:
        plaintext = _decrypt_file(drive_file)
    except InvalidTag:
        return _download_failure_response(
            request, is_owner=is_owner, status=422,
            reason="File integrity verification failed. Download was blocked.",
        )
    except Http404:
        return _download_failure_response(
            request, is_owner=is_owner, status=404,
            reason="The stored file is unavailable. Contact support.",
        )
    except Exception:
        return _download_failure_response(
            request, is_owner=is_owner, status=503,
            reason="The file could not be prepared for preview. Retry later.",
        )

    if is_owner:
        File.objects.filter(pk=drive_file.pk).update(
            last_accessed_at=timezone.now()
        )

    log_action(
        request.user,
        ActivityLog.Action.VIEW,
        f"Viewed {drive_file.file_name}",
        obj=drive_file,
    )

    response = FileResponse(
        io.BytesIO(plaintext),
        as_attachment=False,
        filename=_safe_download_filename(drive_file.file_name),
        content_type=mime_type,
    )
    response["Content-Length"] = str(len(plaintext))
    response["Content-Disposition"] = content_disposition_header(
        False, _safe_download_filename(drive_file.file_name)
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = "sandbox"
    return response


@login_required
def file_details(request, file_id):
    drive_file, is_owner, share = _get_accessible_file(file_id, request.user)
    activity = get_last_activity(drive_file)
    location = _file_location(drive_file, is_owner=is_owner, share=share)
    return JsonResponse({
        "type": "file",
        "name": drive_file.file_name,
        "owner": drive_file.owner.username,
        "size": drive_file.file_size,
        "mime_type": drive_file.mime_type or "Unknown",
        "created_at": drive_file.created_at.strftime(
            "%b %d, %Y, %I:%M %p"
        ),
        "modified_at": drive_file.updated_at.strftime(
            "%b %d, %Y, %I:%M %p"
        ),
        "location": location,
        "encrypted": bool(drive_file.is_encrypted),
        "access": (
            "Owner"
            if is_owner
            else share.permission_label
        ),
        "permission": (
            None
            if is_owner
            else share.permission
        ),
        "shared_by": (
            None
            if is_owner
            else share.owner.username
        ),
        "last_action": (
            activity.get_action_display()
            if activity
            else "No recorded action"
        ),
        "hash_sha256": drive_file.hash_sha256 or None,
    })


def _file_location(drive_file, *, is_owner=True, share=None):
    parts = []
    shared_root_id = share.folder_id if share and share.folder_id else None
    current = drive_file.folder
    while current is not None:
        if not is_owner and current.id == shared_root_id:
            break
        parts.insert(0, current.folder_name)
        current = current.parent
    location_root = "My Drive" if is_owner else "Shared with me"
    return location_root + (" / " + " / ".join(parts) if parts else "")


@login_required
def file_download(request, file_id):
    drive_file, is_owner, _share = _get_accessible_file(
        file_id,
        request.user,
    )

    block_reason = _download_block_reason(drive_file)
    if block_reason:
        return _unavailable_download_response(
            request, block_reason, is_owner=is_owner
        )

    current_version = drive_file.versions.filter(is_current=True).first()
    was_encrypted = bool(
        drive_file.is_encrypted
        or (current_version is not None and current_version.is_encrypted)
    )
    try:
        plaintext = _decrypt_file(drive_file)
    except InvalidTag:
        return _download_failure_response(
            request, is_owner=is_owner, status=422,
            reason="File integrity verification failed. Download was blocked.",
        )
    except Http404:
        return _download_failure_response(
            request, is_owner=is_owner, status=404,
            reason="The stored file is unavailable. Contact support.",
        )
    except Exception:
        return _download_failure_response(
            request, is_owner=is_owner, status=503,
            reason="The file could not be prepared for download. Retry later.",
        )

    response = FileResponse(
        io.BytesIO(plaintext),
        as_attachment=True,
        filename=_safe_download_filename(drive_file.file_name),
        content_type="application/octet-stream",
    )
    response["Content-Disposition"] = content_disposition_header(
        True, _safe_download_filename(drive_file.file_name)
    )

    if is_owner:
        File.objects.filter(pk=drive_file.pk).update(
            last_accessed_at=timezone.now()
        )

    log_action(
        request.user,
        ActivityLog.Action.DOWNLOAD,
        f"Downloaded {drive_file.file_name}",
        obj=drive_file,
    )
    if was_encrypted:
        log_action(
            request.user,
            ActivityLog.Action.DECRYPT,
            f"Decrypted {drive_file.file_name} for download",
            obj=drive_file,
        )
    response["Content-Length"] = str(len(plaintext))
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required
@require_POST
def file_move_to_trash(request, file_id):
    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=True,
    )
    if not can_edit_workspace_content(request.user, drive_file.workspace):
        messages.error(request, "Editor access to this workspace is required.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))
    drive_file.deleted_at = timezone.now()
    drive_file.save(update_fields=["deleted_at", "updated_at"])
    log_action(request.user, ActivityLog.Action.DELETE, f"Moved file to Trash: {drive_file.file_name}", obj=drive_file)
    messages.success(request, "File moved to Trash. You can restore it later.")

    current_folder_id = request.POST.get("current_folder_id")
    if current_folder_id:
        return redirect("folder_open", folder_id=current_folder_id)
    return redirect("dashboard")


@login_required
def trash(request):
    return redirect_to_frontend("/drive/trash")

@login_required
@require_POST
def file_restore(request, file_id):
    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=False,
    )

    if not can_edit_workspace_content(request.user, drive_file.workspace):
        messages.error(request, "Editor access to this workspace is required.")
        return redirect("trash")

    if drive_file.folder_id and drive_file.folder.deleted_at is not None:
        messages.warning(
            request,
            "The parent folder is still in Trash. Restore the parent folder first.",
        )
        return redirect("trash")

    conflict = File.objects.filter(
        owner=request.user,
        tenant=drive_file.tenant,
        workspace=drive_file.workspace,
        folder=drive_file.folder,
        file_name__iexact=drive_file.file_name,
        deleted_at__isnull=True,
    ).exists()
    if conflict:
        messages.error(
            request,
            "A file with the same name already exists in the destination folder.",
        )
        return redirect("trash")

    drive_file.deleted_at = None
    drive_file.save(update_fields=["deleted_at", "updated_at"])
    log_action(request.user, ActivityLog.Action.RESTORE, f"Restored file: {drive_file.file_name}", obj=drive_file)
    messages.success(request, "File restored successfully.")
    return redirect("trash")


@login_required
@require_POST
def file_delete_permanently(request, file_id):
    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=False,
    )
    if not can_edit_workspace_content(request.user, drive_file.workspace):
        messages.error(request, "Editor access to this workspace is required.")
        return redirect("trash")
    file_name = drive_file.file_name
    try:
        from .permanent_delete import permanently_delete_files
        permanently_delete_files([drive_file])
    except Exception:
        messages.error(
            request,
            "Could not permanently delete the file from storage. The file metadata was retained so you can retry.",
        )
        return redirect("trash")
    log_action(
        request.user,
        ActivityLog.Action.PERMANENT_DELETE,
        f"Permanently deleted file: {file_name}",
    )
    messages.success(request, "File permanently deleted.")
    return redirect("trash")


@login_required
@require_POST
def trash_bulk_action(request):
    """Restore or permanently delete multiple top-level Trash items safely."""
    action = request.POST.get("action", "").strip().lower()
    file_ids = []
    folder_ids = []
    for key, target in (("file_ids", file_ids), ("folder_ids", folder_ids)):
        for value in request.POST.getlist(key):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in target:
                target.append(value)

    tenant_ids = active_tenant_ids(request.user)
    files = list(File.objects.filter(owner=request.user, tenant__in=tenant_ids, id__in=file_ids, deleted_at__isnull=False))
    folders = list(Folder.objects.filter(owner=request.user, tenant__in=tenant_ids, id__in=folder_ids, deleted_at__isnull=False))
    if len(files) != len(file_ids) or len(folders) != len(folder_ids):
        messages.error(request, "One or more selected Trash items are no longer available.")
        return redirect("trash")
    if not files and not folders:
        messages.warning(request, "No items selected.")
        return redirect("trash")
    if any(not can_edit_workspace_content(request.user, item.workspace) for item in [*files, *folders]):
        messages.error(request, "Editor access to every selected workspace is required.")
        return redirect("trash")

    def subtree(root):
        result = [root]
        index = 0
        while index < len(result):
            result.extend(Folder.objects.filter(
                owner=request.user, tenant=result[index].tenant,
                workspace=result[index].workspace, parent=result[index],
                deleted_at__isnull=False,
            ))
            index += 1
        return result

    if action == "restore":
        for folder in folders:
            if folder.parent_id and folder.parent.deleted_at is not None:
                messages.error(request, f'Restore the parent folder before restoring "{folder.folder_name}".')
                return redirect("trash")
            tree = subtree(folder)
            ids = {item.id for item in tree}
            for item in tree:
                if Folder.objects.filter(
                    owner=request.user, tenant=item.tenant, workspace=item.workspace,
                    parent=item.parent, folder_name__iexact=item.folder_name,
                    deleted_at__isnull=True,
                ).exclude(id__in=ids).exists():
                    messages.error(request, f'A folder named "{item.folder_name}" already exists at the destination.')
                    return redirect("trash")
            for item in File.objects.filter(
                owner=request.user, tenant=folder.tenant, workspace=folder.workspace,
                folder_id__in=ids, deleted_at__isnull=False,
            ):
                if File.objects.filter(
                    owner=request.user, tenant=item.tenant, workspace=item.workspace,
                    folder=item.folder, file_name__iexact=item.file_name,
                    deleted_at__isnull=True,
                ).exists():
                    messages.error(request, f'A file named "{item.file_name}" already exists in the destination folder.')
                    return redirect("trash")
        for item in files:
            if item.folder_id and item.folder.deleted_at is not None:
                messages.error(request, f'Restore the parent folder before restoring "{item.file_name}".')
                return redirect("trash")
            if File.objects.filter(
                owner=request.user, tenant=item.tenant, workspace=item.workspace,
                folder=item.folder, file_name__iexact=item.file_name,
                deleted_at__isnull=True,
            ).exists():
                messages.error(request, f'A file named "{item.file_name}" already exists in the destination folder.')
                return redirect("trash")
        with transaction.atomic():
            for folder in folders:
                ids = [item.id for item in subtree(folder)]
                Folder.objects.filter(
                    owner=request.user, tenant=folder.tenant,
                    workspace=folder.workspace, id__in=ids,
                ).update(deleted_at=None)
                File.objects.filter(
                    owner=request.user, tenant=folder.tenant,
                    workspace=folder.workspace, folder_id__in=ids,
                    deleted_at__isnull=False,
                ).update(deleted_at=None)
            File.objects.filter(
                owner=request.user, tenant__in=tenant_ids, id__in=file_ids,
            ).update(deleted_at=None)
        log_action(request.user, ActivityLog.Action.RESTORE, f"Restored {len(files)} file(s) and {len(folders)} folder(s) from Trash")
        messages.success(request, "Selected items restored successfully.")
        return redirect("trash")

    if action == "permanent_delete":
        try:
            from .permanent_delete import permanently_delete_files
            trees = []
            for root_folder in _top_level_folders(folders):
                tree_items = [root_folder]
                index = 0
                while index < len(tree_items):
                    tree_items.extend(Folder.objects.filter(
                        owner=request.user,
                        tenant=root_folder.tenant,
                        workspace=root_folder.workspace,
                        parent=tree_items[index],
                    ))
                    index += 1
                trees.append(tree_items)
            tree_by_id = {item.pk: item for tree_items in trees for item in tree_items}
            tree_ids = list(tree_by_id)
            nested_files = File.objects.filter(
                owner=request.user,
                tenant__in=tenant_ids,
                folder_id__in=tree_ids,
            ).select_related("folder")
            files_by_id = {
                item.pk: item
                for item in [*files, *list(nested_files)]
            }
            permanently_delete_files(files_by_id.values())
            if tree_ids:
                workspace_ids = {item.workspace_id for item in tree_by_id.values()}
                UploadSession.objects.filter(
                    target_folder_id__in=tree_ids,
                    workspace_id__in=workspace_ids,
                ).update(target_folder=None)
                Folder.objects.filter(
                    owner=request.user,
                    tenant__in=tenant_ids,
                    id__in=tree_ids,
                ).delete()
        except Exception:
            messages.error(request, "Could not permanently delete all selected storage objects. Metadata was retained where cleanup failed; retry after checking storage.")
            return redirect("trash")
        log_action(request.user, ActivityLog.Action.PERMANENT_DELETE, f"Permanently deleted {len(files)} file(s) and {len(folders)} folder(s) from Trash")
        messages.success(request, "Selected items permanently deleted.")
        return redirect("trash")

    messages.error(request, "Unknown Trash action.")
    return redirect("trash")


@login_required
@require_POST
def file_rename(request, file_id):
    drive_file = get_object_or_404(
        File,
        id=file_id,
        deleted_at__isnull=True,
    )
    if not can_edit_file(drive_file, request.user):
        messages.error(request, "You do not have permission to rename this file.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    form = FileRenameForm(request.POST, instance=drive_file)
    if form.is_valid():
        new_name = form.cleaned_data["file_name"]
        duplicate = File.objects.filter(
            owner=drive_file.owner,
            tenant=drive_file.tenant,
            workspace=drive_file.workspace,
            folder=drive_file.folder,
            file_name__iexact=new_name,
            deleted_at__isnull=True,
        ).exclude(id=drive_file.id).exists()
        if duplicate:
            messages.error(request, "A file with this name already exists in this folder.")
        else:
            old_name = drive_file.file_name
            form.save()
            log_action(request.user, ActivityLog.Action.RENAME, f"Renamed file from {old_name} to {drive_file.file_name}", obj=drive_file)
            messages.success(request, "File renamed successfully.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, f"Could not rename file: {error}")

    current_folder_id = request.POST.get("current_folder_id")
    if current_folder_id:
        return redirect("folder_open", folder_id=current_folder_id)
    return redirect("shared_with_me" if drive_file.owner_id != request.user.id else "dashboard")


@login_required
@require_POST
def file_move(request, file_id):
    drive_file = get_object_or_404(
        File,
        id=file_id,
        deleted_at__isnull=True,
    )
    if not can_edit_file(drive_file, request.user):
        messages.error(request, "You do not have permission to move this file.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    share = get_receiver_share_for_file(drive_file, request.user) if drive_file.owner_id != request.user.id else None
    shared_root = share.folder if share and share.folder_id else None

    folder_id = request.POST.get("folder_id")
    destination = None
    if folder_id:
        destination = get_object_or_404(
            Folder,
            id=folder_id,
            owner=drive_file.owner,
            tenant=drive_file.tenant,
            deleted_at__isnull=True,
        )

    if destination is not None and destination.workspace_id != drive_file.workspace_id:
        messages.error(request, "Files cannot be moved across workspaces.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    if drive_file.owner_id != request.user.id:
        if not can_edit_destination_folder(destination, request.user, shared_root=shared_root):
            messages.error(request, "Editors can only move shared files inside the shared folder.")
            return redirect(request.META.get("HTTP_REFERER", "shared_with_me"))

    if drive_file.folder_id == (destination.id if destination else None):
        messages.info(request, "File is already in this folder.")
        return redirect("folder_open", folder_id=destination.id) if destination else redirect("dashboard")

    duplicate = File.objects.filter(
        owner=drive_file.owner,
        tenant=drive_file.tenant,
        workspace=drive_file.workspace,
        folder=destination,
        file_name__iexact=drive_file.file_name,
        deleted_at__isnull=True,
    ).exclude(id=drive_file.id).exists()
    if duplicate:
        messages.error(request, "A file with the same name already exists in the destination folder.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    drive_file.folder = destination
    drive_file.save(update_fields=["folder", "updated_at"])
    log_action(request.user, ActivityLog.Action.MOVE, f"Moved file: {drive_file.file_name}", obj=drive_file)
    messages.success(request, f'"{drive_file.file_name}" moved successfully.')
    return redirect("folder_open", folder_id=destination.id) if destination else redirect("dashboard")


@login_required
@require_POST
def file_copy(request, file_id):
    drive_file = get_object_or_404(
        File,
        id=file_id,
        deleted_at__isnull=True,
    )
    if not can_edit_file(drive_file, request.user):
        messages.error(request, "You do not have permission to copy this file.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))
    if not drive_file.is_encrypted or not drive_file.file_path:
        messages.error(request, "This file cannot be copied because its encryption data is incomplete.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    request.session["clipboard"] = {"type": "file", "file_id": drive_file.id}
    request.session.modified = True
    log_action(request.user, ActivityLog.Action.COPY, f"Copied file to clipboard: {drive_file.file_name}", obj=drive_file)
    messages.success(request, f'"{drive_file.file_name}" copied to clipboard.')
    current_folder_id = request.POST.get("current_folder_id")
    if current_folder_id:
        return redirect("folder_open", folder_id=current_folder_id)
    return redirect("shared_with_me" if drive_file.owner_id != request.user.id else "dashboard")


@login_required
@require_POST
def file_cut(request, file_id):
    drive_file = get_object_or_404(
        File,
        id=file_id,
        deleted_at__isnull=True,
    )
    if not can_edit_file(drive_file, request.user):
        messages.error(request, "You do not have permission to move this file.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    request.session["clipboard"] = {"type": "file_cut", "file_id": drive_file.id}
    request.session.modified = True
    log_action(request.user, ActivityLog.Action.CUT, f"Cut file: {drive_file.file_name}", obj=drive_file)
    messages.success(request, f'"{drive_file.file_name}" has been cut.')
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
@require_POST
def file_paste(request):
    clipboard = request.session.get("clipboard")
    if not clipboard:
        messages.warning(request, "Clipboard is empty.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    clipboard_type = clipboard.get("type")
    folder_id = request.POST.get("folder_id")
    destination = None
    if folder_id:
        destination = get_object_or_404(
            Folder,
            id=folder_id,
            deleted_at__isnull=True,
        )

    if clipboard_type in {"file", "file_cut"}:
        source_file = get_object_or_404(
            File,
            id=clipboard.get("file_id"),
            deleted_at__isnull=True,
        )
        if not can_edit_file(source_file, request.user):
            messages.error(request, "You no longer have permission to edit this file.")
            request.session.pop("clipboard", None)
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))

        source_share = get_receiver_share_for_file(source_file, request.user) if source_file.owner_id != request.user.id else None
        shared_root = source_share.folder if source_share and source_share.folder_id else None
        if source_file.owner_id != request.user.id and not can_edit_destination_folder(
            destination, request.user, shared_root=shared_root
        ):
            messages.error(request, "Editors can only paste shared files inside the shared folder.")
            return redirect(request.META.get("HTTP_REFERER", "shared_with_me"))

        if destination is not None and destination.owner_id != source_file.owner_id:
            messages.error(request, "The destination is not part of the shared resource.")
            return redirect(request.META.get("HTTP_REFERER", "shared_with_me"))
        if destination is not None and destination.workspace_id != source_file.workspace_id:
            messages.error(request, "Files cannot be copied or moved across workspaces.")
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))

        same_folder = source_file.folder_id == (destination.id if destination else None)
        if clipboard_type == "file_cut" and same_folder:
            messages.info(request, "File is already in this folder.")
            request.session.pop("clipboard", None)
            return redirect("folder_open", folder_id=destination.id) if destination else redirect("dashboard")

        copy_name = source_file.file_name
        if clipboard_type == "file":
            duplicate = File.objects.filter(
                owner=source_file.owner,
                tenant=source_file.tenant,
                workspace=source_file.workspace,
                folder=destination,
                file_name__iexact=copy_name,
                deleted_at__isnull=True,
            ).exists()
            if duplicate:
                copy_name = unique_copy_name(
                    File,
                    "file_name",
                    source_file.file_name,
                    folder=destination,
                    owner=source_file.owner,
                    workspace=source_file.workspace,
                )

        if clipboard_type == "file_cut":
            source_file.folder = destination
            source_file.save(update_fields=["folder", "updated_at"])
            request.session.pop("clipboard", None)
            log_action(request.user, ActivityLog.Action.MOVE, f"Moved file: {source_file.file_name}", obj=source_file)
            messages.success(request, f'"{source_file.file_name}" moved successfully.')
        else:
            if source_file.owner_id != request.user.id:
                messages.error(
                    request,
                    "Copying a shared file requires a workspace quota allocation for your account.",
                )
                return redirect(request.META.get("HTTP_REFERER", "shared_with_me"))
            try:
                new_file = clone_encrypted_file_with_quota(
                    source_file,
                    owner=source_file.owner,
                    folder=destination,
                    file_name=copy_name,
                    tenant=source_file.tenant,
                )
            except (QuotaExceeded, QuotaStateError):
                messages.error(request, "The workspace or member quota does not allow this file copy.")
                return redirect(request.META.get("HTTP_REFERER", "dashboard"))
            except InvalidTag:
                messages.error(request, "File integrity verification failed. Copy was cancelled.")
                return redirect(request.META.get("HTTP_REFERER", "dashboard"))
            except Exception:
                messages.error(request, "Could not copy the file.")
                return redirect(request.META.get("HTTP_REFERER", "dashboard"))
            request.session.pop("clipboard", None)
            log_action(request.user, ActivityLog.Action.COPY, f"Created copied file: {new_file.file_name}", obj=new_file)
            messages.success(request, f'"{new_file.file_name}" pasted successfully.')

        return redirect("folder_open", folder_id=destination.id) if destination else redirect("dashboard")

    if clipboard_type in {"folder", "folder_cut"}:
        from folders.views import folder_paste
        return folder_paste(request)

    request.session.pop("clipboard", None)
    messages.error(request, "Invalid clipboard data.")
    return redirect("dashboard")
