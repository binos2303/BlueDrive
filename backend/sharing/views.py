from django.contrib import messages
from django.http import FileResponse, Http404
import io
import zipfile
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from files.models import File
from folders.models import Folder
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
        deleted_at__isnull=True,
    )

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

    Share.objects.update_or_create(
        file=drive_file,
        receiver=receiver,
        defaults={
            "owner": request.user,
            "permission": permission,
        },
    )

    permission_label = dict(
        Share.Permission.choices
    ).get(
        permission,
        "Viewer",
    )

    log_action(
        request.user,
        ActivityLog.Action.SHARE,
        (
            f"Shared file {drive_file.file_name} "
            f"with {receiver.username} "
            f"as {permission_label}"
        ),
    )

    messages.success(
        request,
        (
            f"File shared with {receiver.username} "
            f"as {permission_label}."
        ),
    )

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
        deleted_at__isnull=True,
    )

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

    Share.objects.update_or_create(
        folder=folder,
        receiver=receiver,
        defaults={
            "owner": request.user,
            "permission": permission,
        },
    )

    permission_label = dict(
        Share.Permission.choices
    ).get(
        permission,
        "Viewer",
    )

    log_action(
        request.user,
        ActivityLog.Action.SHARE,
        (
            f"Shared folder {folder.folder_name} "
            f"with {receiver.username} "
            f"as {permission_label}"
        ),
    )

    messages.success(
        request,
        (
            f"Folder shared with {receiver.username} "
            f"as {permission_label}."
        ),
    )

    return redirect(
        request.META.get(
            "HTTP_REFERER",
            "dashboard",
        )
    )

@login_required
@require_POST
def change_share_permission(request, share_id):
    """Change Viewer/Editor permission. Only the original owner may do this."""
    share = get_object_or_404(
        Share,
        id=share_id,
        owner=request.user,
    )

    permission = request.POST.get("permission", "").strip()

    valid_permissions = {
        Share.Permission.VIEWER,
        Share.Permission.EDITOR,
    }

    if permission not in valid_permissions:
        messages.error(request, "Invalid sharing permission.")
        return redirect("shared_with_me")

    old_permission = share.permission

    if old_permission == permission:
        messages.info(request, "Sharing permission was not changed.")
        return redirect("shared_with_me")

    share.permission = permission
    share.save(update_fields=["permission"])

    item_name = (
        share.file.file_name
        if share.file_id
        else share.folder.folder_name
    )

    permission_label = dict(Share.Permission.choices).get(
        permission,
        "Viewer",
    )
    old_permission_label = dict(Share.Permission.choices).get(
        old_permission,
        "Viewer",
    )

    log_action(
        request.user,
        ActivityLog.Action.SHARE,
        (
            f"Changed access to {item_name} for "
            f"{share.receiver.username} from "
            f"{old_permission_label} to {permission_label}"
        ),
    )

    messages.success(
        request,
        (
            f"Access for {share.receiver.username} changed to "
            f"{permission_label}."
        ),
    )

    return redirect("shared_with_me")


@login_required
def shared_with_me(request):
    """
    Display resources shared with the user and resources shared by the user.

    Share records are retained for audit/history, while soft-deleted targets
    are shown as unavailable until the owner restores them or revokes access.
    """
    received_shares = (
        Share.objects
        .filter(receiver=request.user)
        .select_related("owner", "receiver", "file__folder", "folder")
        .order_by("-created_at")
    )

    sent_shares = (
        Share.objects
        .filter(owner=request.user)
        .select_related("owner", "receiver", "file__folder", "folder")
        .order_by("-created_at")
    )

    return render(
        request,
        "sharing/index.html",
        {
            "received_shares": received_shares,
            "sent_shares": sent_shares,
        },
    )


@login_required
@require_POST
def revoke_share(request, share_id):
    """Chỉ owner ban đầu mới có thể thu hồi quyền."""
    share = get_object_or_404(
        Share,
        id=share_id,
        owner=request.user,
    )

    receiver_name = share.receiver.username
    item_name = share.file.file_name if share.file_id else share.folder.folder_name
    share.delete()

    log_action(
        request.user,
        ActivityLog.Action.REVOKE_SHARE,
        f"Revoked access to {item_name} for {receiver_name}",
    )

    messages.success(request, f"Access revoked for {receiver_name}.")
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
