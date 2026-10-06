from django.urls import path

from . import views


urlpatterns = [
    path(
        "drive/files/<int:file_id>/share/",
        views.share_file,
        name="share_file",
    ),
    path(
        "drive/folders/<int:folder_id>/share/",
        views.share_folder,
        name="share_folder",
    ),
    path(
        "drive/shared-with-me/",
        views.shared_with_me,
        name="shared_with_me",
    ),
    path(
        "drive/shared-with-me/bulk-download/",
        views.bulk_download_shared,
        name="bulk_download_shared",
    ),
    path(
        "drive/shares/<int:share_id>/revoke/",
        views.revoke_share,
        name="revoke_share",
    ),
    path(
        "drive/shares/<int:share_id>/permission/",
        views.change_share_permission,
        name="change_share_permission",
    ),
]
