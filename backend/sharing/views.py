from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404
import io
import zipfile
from accounts.access import (
    active_tenant_ids,
    active_tenant_required as login_required,
)
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from securedrive.frontend_redirects import redirect_to_frontend

from files.models import File
from folders.models import Folder
from .services import (
    get_receiver_share_for_file, get_receiver_share_for_folder, upsert_direct_share,
    can_manage_direct_share, change_direct_share_permission, revoke_direct_share,
)
from logs.models import ActivityLog
from logs.services import log_action
from security.aes_service import build_file_aad, decrypt_bytes, get_master_key, unwrap_dek
from security.hash_service import verify_sha256

from .forms import FileShareForm
from .models import Share


@login_required
@require_POST
def share_file(request, file_id):
    """Share a file with a recipient using Viewer or Editor permission."""
    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=True,
    )

    if not can_manage_direct_share(drive_file, request.user):
        messages.error(request, "You cannot manage sharing for this item.")
        return redirect("dashboard")

    form = FileShareForm(
        request.POST,
        owner=request.user,
    )

    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(
                    request,
                    f"Could not share file: {error}",
                )

        return redirect(
            request.META.get(
                "HTTP_REFERER",
                "dashboard",
            )
        )

    receiver = form.cleaned_data["username"]
    permission = form.cleaned_data["permission"]

    with transaction.atomic():
        operation, previous_permission = upsert_direct_share(
            resource=drive_file, receiver=receiver, owner=request.user, permission=permission,
        )
        if operation != "unchanged":
            log_action(
                request.user, ActivityLog.Action.SHARE,
                f"{operation} file {drive_file.file_name} for {receiver.get_username()}",
                obj=drive_file,
                metadata={
                    "operation": operation,
                    "recipient_username": receiver.get_username(),
                    "recipient_email": receiver.email,
                    "permission": permission,
                    "previous_permission": previous_permission if operation == "permission_changed" else None,
                    "resource_names": [drive_file.file_name],
                    "resource_kinds": ["file"],
                    "resource_changes": [{"name": drive_file.file_name, "kind": "file",
                        "operation": operation, "permission": permission,
                        "previous_permission": previous_permission if operation == "permission_changed" else None}],
                    "shared_count": 1,
                },
            )

    permission_label = dict(
        Share.Permission.choices
    ).get(
        permission,
        "Viewer",
    )


    notify = messages.info if operation == "unchanged" else messages.success
    notify(request, f"{'Already shared with' if operation == 'unchanged' else 'Updated access for' if operation == 'permission_changed' else 'Shared with'} {receiver.username} as {permission_label}.")

    return redirect(
        request.META.get(
            "HTTP_REFERER",
            "dashboard",
        )
    )


@login_required
@require_POST
def share_folder(request, folder_id):
    """Share a folder with a recipient using Viewer or Editor permission."""
    folder = get_object_or_404(
        Folder,
        id=folder_id,
        owner=request.user,
        tenant__in=active_tenant_ids(request.user),
        deleted_at__isnull=True,
    )

    if not can_manage_direct_share(folder, request.user):
        messages.error(request, "You cannot manage sharing for this item.")
        return redirect("dashboard")

    form = FileShareForm(
        request.POST,
        owner=request.user,
    )

    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(
                    request,
                    f"Could not share folder: {error}",
                )

        return redirect(
            request.META.get(
                "HTTP_REFERER",
                "dashboard",
            )
        )

    receiver = form.cleaned_data["username"]
    permission = form.cleaned_data["permission"]

    with transaction.atomic():
        operation, previous_permission = upsert_direct_share(
            resource=folder, receiver=receiver, owner=request.user, permission=permission,
        )
        if operation != "unchanged":
            log_action(
                request.user, ActivityLog.Action.SHARE,
                f"{operation} folder {folder.folder_name} for {receiver.get_username()}",
                obj=folder,
                metadata={
                    "operation": operation,
                    "recipient_username": receiver.get_username(),
                    "recipient_email": receiver.email,
                    "permission": permission,
                    "previous_permission": previous_permission if operation == "permission_changed" else None,
                    "resource_names": [folder.folder_name],
                    "resource_kinds": ["folder"],
                    "resource_changes": [{"name": folder.folder_name, "kind": "folder",
                        "operation": operation, "permission": permission,
                        "previous_permission": previous_permission if operation == "permission_changed" else None}],
                    "shared_count": 1,
                },
            )

    permission_label = dict(
        Share.Permission.choices
    ).get(
        permission,
        "Viewer",
    )


    notify = messages.info if operation == "unchanged" else messages.success
    notify(request, f"{'Already shared with' if operation == 'unchanged' else 'Updated access for' if operation == 'permission_changed' else 'Shared with'} {receiver.username} as {permission_label}.")

    return redirect(
        request.META.get(
            "HTTP_REFERER",
            "dashboard",
        )
    )

@login_required
@require_POST
def change_share_permission(request, share_id):
    """Legacy form endpoint backed by the same audited service as the JSON API."""
    permission = request.POST.get("permission", "").strip()
    if permission not in {Share.Permission.VIEWER, Share.Permission.EDITOR}:
        messages.error(request, "Invalid sharing permission.")
        return redirect("shared_with_me")

    with transaction.atomic():
        share = get_object_or_404(
            Share.objects.select_for_update(of=("self",)).select_related(
                "file__tenant", "file__workspace", "file__folder",
                "folder__tenant", "folder__workspace", "folder__parent", "receiver",
            ),
            id=share_id, owner=request.user, tenant__in=active_tenant_ids(request.user),
        )
        resource = share.file if share.file_id else share.folder
        if not can_manage_direct_share(resource, request.user):
            messages.error(request, "You cannot manage sharing for this item.")
            return redirect("shared_with_me")
        changed = change_direct_share_permission(share=share, actor=request.user, permission=permission)

    messages.success(request, "Sharing permission updated." if changed else "Sharing permission was not changed.")
    return redirect("shared_with_me")


@login_required
def shared_with_me(request):
    return redirect_to_frontend("/drive/shared")

@login_required
@require_POST
def revoke_share(request, share_id):
    """Legacy form endpoint; revoke atomically through the common service."""
    with transaction.atomic():
        share = get_object_or_404(
            Share.objects.select_for_update(of=("self",)).select_related(
                "file__tenant", "file__workspace", "file__folder",
                "folder__tenant", "folder__workspace", "folder__parent", "receiver",
            ),
            id=share_id, owner=request.user, tenant__in=active_tenant_ids(request.user),
        )
        resource = share.file if share.file_id else share.folder
        if not can_manage_direct_share(resource, request.user):
            messages.error(request, "You cannot manage sharing for this item.")
            return redirect("shared_with_me")
        revoke_direct_share(share=share, actor=request.user)

    messages.success(request, "Access revoked.")
    return redirect("shared_with_me")


@login_required
@require_POST
def bulk_download_shared(request):
    """Download multiple files shared with the current user in one ZIP."""
    raw_ids = request.POST.getlist("file_ids")
    ids = []
    for value in raw_ids:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in ids:
            ids.append(value)
    if not ids:
        messages.warning(request, "No files selected.")
        return redirect("shared_with_me")

    files = list(File.objects.filter(id__in=ids).select_related("owner", "folder"))
    if len(files) != len(ids) or any(
        drive_file.deleted_at is not None
        or (drive_file.folder_id and drive_file.folder.deleted_at is not None)
        for drive_file in files
    ):
        messages.error(request, "One or more selected files are unavailable or in Trash.")
        return redirect("shared_with_me")

    payloads = []
    for drive_file in files:
        from .services import get_receiver_share_for_file
        share = get_receiver_share_for_file(drive_file, request.user)
        if share is None:
            messages.error(request, f'You do not have access to "{drive_file.file_name}".')
            return redirect("shared_with_me")
        try:
            dek = unwrap_dek(bytes(drive_file.wrapped_dek), bytes(drive_file.dek_nonce), get_master_key())
            aad = build_file_aad(owner_id=drive_file.owner_id, file_id=drive_file.id, version=drive_file.encryption_version)
            with drive_file.file_path.open("rb") as stored_file:
                plaintext = decrypt_bytes(stored_file.read(), bytes(drive_file.encryption_nonce), dek, aad)
            if drive_file.hash_sha256 and not verify_sha256(plaintext, drive_file.hash_sha256):
                raise ValueError("integrity")
            payloads.append((drive_file.file_name, plaintext))
        except Exception:
            messages.error(request, f'Could not prepare "{drive_file.file_name}" for download.')
            return redirect("shared_with_me")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        used = set()
        for name, content in payloads:
            candidate = name
            number = 1
            while candidate in used:
                number += 1
                if "." in name:
                    stem, ext = name.rsplit(".", 1)
                    candidate = f"{stem} ({number}).{ext}"
                else:
                    candidate = f"{name} ({number})"
            used.add(candidate)
            archive.writestr(candidate, content)
    buffer.seek(0)
    log_action(request.user, ActivityLog.Action.DOWNLOAD, f"Downloaded {len(payloads)} shared file(s) as ZIP")
    response = FileResponse(buffer, as_attachment=True, filename="SecureDrive-shared-files.zip", content_type="application/zip")
    response["X-Content-Type-Options"] = "nosniff"
    return response