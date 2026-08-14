from django.urls import path

from . import views


urlpatterns = [
    path(
        "drive/files/<int:file_id>/share/",
        views.share_file,
        name="share_file",
    ),

    path(
        "drive/shared-with-me/",
        views.shared_with_me,
        name="shared_with_me",
    ),

    path(
        "drive/shares/<int:share_id>/revoke/",
        views.revoke_share,
        name="revoke_share",
    ),
]