from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from files.models import File

from .forms import FileShareForm
from .models import Share





@login_required
def share_file(request, file_id):
    """Owner cấp hoặc cập nhật quyền cho một user khác."""
    if request.method != "POST":
        return redirect("dashboard")

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

        return redirect("dashboard")

    receiver = form.cleaned_data["username"]
    permission = form.cleaned_data["permission"]

    # Cấp lại quyền sẽ cập nhật quyền cũ, không tạo record trùng.
    Share.objects.update_or_create(
        file=drive_file,
        receiver=receiver,
        defaults={
            "owner": request.user,
            "permission": permission,
        },
    )

    messages.success(
        request,
        f"File shared with {receiver.username}.",
    )

    return redirect("dashboard")


@login_required
def shared_with_me(request):
    """Chỉ hiển thị share còn hiệu lực và file chưa nằm trong Trash."""
    shares = Share.objects.filter(
        receiver=request.user,
        file__deleted_at__isnull=True,
    ).select_related(
        "file",
        "owner",
    ).order_by("-created_at")

    return render(
        request,
        "sharing/shared_with_me.html",
        {"shares": shares},
    )


@login_required
def revoke_share(request, share_id):
    """Chỉ owner ban đầu mới có thể thu hồi quyền."""
    if request.method != "POST":
        return redirect("dashboard")

    share = get_object_or_404(
        Share,
        id=share_id,
        owner=request.user,
    )

    receiver_name = share.receiver.username
    share.delete()

    messages.success(
        request,
        f"Access revoked for {receiver_name}.",
    )

    return redirect("dashboard")