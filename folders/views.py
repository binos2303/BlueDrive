from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.shortcuts import get_object_or_404, render
from .forms import FolderCreateForm
from .models import Folder
from files.models import File
from django.http import Http404
from sharing.services import get_receiver_share_for_folder

@login_required
def folder_create(request):

    if request.method != "POST":
        return redirect("dashboard")

    form = FolderCreateForm(
        request.POST,
        user=request.user
    )

    if form.is_valid():

        folder = form.save(commit=False)

        folder.owner = request.user

        if folder.parent is not None:

            if folder.parent.owner != request.user:

                return redirect("dashboard")

        folder.save()

    return redirect("dashboard")

@login_required
def folder_open(request, folder_id):

    folder = get_object_or_404(
        Folder,
        id=folder_id,
    )

    is_owner = folder.owner_id == request.user.id
    shared_access = None

    if not is_owner:
        shared_access = get_receiver_share_for_folder(
            folder,
            request.user,
        )

        # Không tiết lộ folder có tồn tại cho user không có quyền.
        if shared_access is None:
            raise Http404

    subfolders = Folder.objects.filter(
        owner=folder.owner,
        parent=folder
    ).order_by("folder_name")

    files = File.objects.filter(
        owner=folder.owner,
        folder=folder,
        deleted_at__isnull=True
    ).order_by("-created_at")

    all_folders = Folder.objects.filter(
        owner=request.user
    ).order_by("folder_name")

    breadcrumbs = []

    current = folder

    while current is not None:
        breadcrumbs.insert(0, current)

        # Receiver chỉ thấy breadcrumb từ folder được chia sẻ trở xuống.
        if (
            not is_owner
            and current.id == shared_access.folder_id
        ):
            break

        current = current.parent

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "current_folder": folder,
            "folders": subfolders,
            "files": files,
            "all_folders": all_folders,
            "breadcrumbs": breadcrumbs,
                        "is_shared_access": not is_owner,
            "shared_permission": (
                shared_access.permission
                if shared_access else None
            ),
        }
    )