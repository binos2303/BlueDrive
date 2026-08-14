from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from files.models import File
from folders.models import Folder


@login_required
def dashboard(request):

    folders = Folder.objects.filter(
        owner=request.user,
        parent__isnull=True
    ).order_by("folder_name")

    files = File.objects.filter(
        owner=request.user,
        deleted_at__isnull=True,
        folder__isnull=True
    ).order_by("-created_at")

    all_folders = Folder.objects.filter(
        owner=request.user
    ).order_by("folder_name")

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "folders": folders,
            "files": files,
            "all_folders": all_folders,
        }
    )

@login_required
def search(request):
    """
    Tìm theo tên file/folder của chính user hiện tại.

    Không tìm file trong Thùng rác và giới hạn kết quả để tránh
    truy vấn quá nặng khi dữ liệu lớn.
    """
    query = request.GET.get("q", "").strip()
        # Không có từ khóa thì quay về My Drive.
    if not query:
        return redirect("dashboard")

    # Giới hạn độ dài input từ URL.
    query = query[:100]

    files = File.objects.none()
    folders = Folder.objects.none()

    if query:
        files = File.objects.filter(
            owner=request.user,
            deleted_at__isnull=True,
            file_name__icontains=query,
        ).order_by("-created_at")[:50]

        folders = Folder.objects.filter(
            owner=request.user,
            folder_name__icontains=query,
        ).order_by("folder_name")[:50]

    return render(
        request,
        "dashboard/search.html",
        {
            "query": query,
            "files": files,
            "folders": folders,
        },
    )