import io
import uuid

from cryptography.exceptions import InvalidTag
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.shortcuts import render
from django.http import FileResponse, Http404
from sharing.models import Share

from security.aes_service import (
    build_file_aad,
    decrypt_bytes,
    encrypt_bytes,
)

from .forms import (
    FileMoveForm,
    FileRenameForm,
    FileUploadForm,
)
from .models import File


@login_required
def file_upload(request):

    if request.method != "POST":
        return redirect("dashboard")

    form = FileUploadForm(
        request.POST,
        request.FILES,
        user=request.user,
    )

    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(
                    request,
                    f"Upload rejected: {error}",
                )

        return redirect("dashboard")

    uploaded_file = form.cleaned_data["file_path"]
    folder = form.cleaned_data["folder"]

    if folder is not None and folder.owner != request.user:
        messages.error(request, "Upload rejected: invalid folder.")
        return redirect("dashboard")

    # AESGCM encrypt() hoạt động trên bytes.
    # Với giới hạn upload 100 MB hiện tại, xử lý trong RAM vẫn phù hợp.
    uploaded_file.seek(0)
    plaintext = uploaded_file.read()

    aad = build_file_aad(
        request.user.id,
        form.sha256,
    )

    ciphertext, nonce = encrypt_bytes(
        plaintext,
        aad,
    )

    drive_file = form.save(commit=False)
    drive_file.owner = request.user
    drive_file.file_name = uploaded_file.name
    drive_file.file_size = uploaded_file.size
    drive_file.mime_type = form.detected_mime_type
    drive_file.hash_sha256 = form.sha256
    drive_file.is_encrypted = True
    drive_file.encryption_nonce = nonce
    drive_file.encryption_version = 1

    stored_name = None

    try:
        with transaction.atomic():
            # Không dùng tên file gốc trên storage để giảm lộ metadata.
            # Đuôi .enc nhắc rằng dữ liệu trên disk là ciphertext.
            encrypted_name = f"{uuid.uuid4().hex}.enc"

            drive_file.file_path.save(
                encrypted_name,
                ContentFile(ciphertext),
                save=False,
            )

            stored_name = drive_file.file_path.name
            drive_file.save()

    except Exception:
        # Storage và database không cùng transaction.
        # Nếu DB lỗi sau khi ghi storage, xóa ciphertext mồ côi.
        if stored_name:
            drive_file.file_path.storage.delete(stored_name)

        messages.error(
            request,
            "Upload could not be completed.",
        )

        return redirect("dashboard")

    messages.success(
        request,
        "File uploaded, encrypted, and validated successfully.",
    )


    return redirect("dashboard")


@login_required
def file_download(request, file_id):
    """
    Owner hoặc receiver có quyền download mới lấy được plaintext.
    Không tiết lộ sự tồn tại của file cho user không có quyền.
    """
    drive_file = get_object_or_404(
        File,
        id=file_id,
        deleted_at__isnull=True,
    )

    is_owner = drive_file.owner_id == request.user.id

    if not is_owner:
        share = Share.objects.filter(
            file=drive_file,
            receiver=request.user,
        ).first()

        if (
            share is None
            or share.permission != Share.Permission.DOWNLOAD
        ):
            raise Http404

    if (
        not drive_file.is_encrypted
        or not drive_file.encryption_nonce
        or drive_file.encryption_version != 1
    ):
        raise Http404

    # AAD luôn dùng owner gốc của file, không dùng receiver.
    aad = build_file_aad(
        drive_file.owner_id,
        drive_file.hash_sha256,
    )

    try:
        with drive_file.file_path.open("rb") as stored_file:
            ciphertext = stored_file.read()

        plaintext = decrypt_bytes(
            ciphertext,
            bytes(drive_file.encryption_nonce),
            aad,
        )

    except InvalidTag:
        messages.error(
            request,
            "File integrity verification failed.",
        )
        return redirect("dashboard")

    response = FileResponse(
        io.BytesIO(plaintext),
        as_attachment=True,
        filename=drive_file.file_name,
        content_type=drive_file.mime_type,
    )

    response["Content-Length"] = str(drive_file.file_size)
    response["X-Content-Type-Options"] = "nosniff"

    return response

@login_required
def file_move_to_trash(request, file_id):
    """Chỉ đánh dấu xóa; ciphertext vẫn giữ để người dùng có thể khôi phục."""
    if request.method != "POST":
        return redirect("dashboard")

    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        deleted_at__isnull=True,
    )

    drive_file.deleted_at = timezone.now()
    drive_file.save(update_fields=["deleted_at"])

    messages.success(
        request,
        "File moved to Trash. You can restore it later.",
    )

    return redirect("dashboard")


@login_required
def trash(request):
    """Hiển thị riêng các file đã xóa của chính user hiện tại."""
    files = File.objects.filter(
        owner=request.user,
        deleted_at__isnull=False,
    ).order_by("-deleted_at")

    return render(
        request,
        "files/trash.html",
        {"files": files},
    )


@login_required
def file_restore(request, file_id):
    """Khôi phục file về folder ban đầu hoặc My Drive."""
    if request.method != "POST":
        return redirect("trash")

    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        deleted_at__isnull=False,
    )

    drive_file.deleted_at = None
    drive_file.save(update_fields=["deleted_at"])

    messages.success(request, "File restored successfully.")

    return redirect("trash")


@login_required
def file_delete_permanently(request, file_id):
    """
    Xóa ciphertext khỏi storage rồi xóa bản ghi database.
    Hành động này không thể khôi phục.
    """
    if request.method != "POST":
        return redirect("trash")

    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        deleted_at__isnull=False,
    )

    try:
        # Chỉ xóa file thuộc record của chính user đã được xác thực ở trên.
        if drive_file.file_path:
            drive_file.file_path.delete(save=False)

        drive_file.delete()

    except Exception:
        messages.error(
            request,
            "Could not permanently delete the file.",
        )
        return redirect("trash")

    messages.success(
        request,
        "File permanently deleted.",
    )

    return redirect("trash")


@login_required
def file_rename(request, file_id):
    """Đổi tên hiển thị của file thuộc chính user hiện tại."""
    if request.method != "POST":
        return redirect("dashboard")

    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        deleted_at__isnull=True,
    )

    form = FileRenameForm(
        request.POST,
        instance=drive_file,
    )

    if form.is_valid():
        form.save()

        messages.success(
            request,
            "File renamed successfully.",
        )
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(
                    request,
                    f"Could not rename file: {error}",
                )

    return redirect("dashboard")


@login_required
def file_move(request, file_id):
    """Di chuyển file sang folder hợp lệ của chính user."""
    if request.method != "POST":
        return redirect("dashboard")

    drive_file = get_object_or_404(
        File,
        id=file_id,
        owner=request.user,
        deleted_at__isnull=True,
    )

    form = FileMoveForm(
        request.POST,
        instance=drive_file,
        user=request.user,
    )

    if form.is_valid():
        # Queryset trong form chỉ chứa folder của request.user.
        form.save()

        messages.success(
            request,
            "File moved successfully.",
        )
    else:
        messages.error(
            request,
            "Could not move file.",
        )

    return redirect("dashboard")