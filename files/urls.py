from django.urls import path

from . import views


urlpatterns = [

    path(
        "drive/upload/",
        views.file_upload,
        name="file_upload"
    ),
    path(
        "drive/files/<int:file_id>/download/",
        views.file_download,
        name="file_download",
    ),
        path(
        "drive/files/<int:file_id>/trash/",
        views.file_move_to_trash,
        name="file_move_to_trash",
    ),
    path(
        "drive/trash/",
        views.trash,
        name="trash",
    ),
    path(
        "drive/files/<int:file_id>/restore/",
        views.file_restore,
        name="file_restore",
    ),
    path(
        "drive/files/<int:file_id>/delete/",
        views.file_delete_permanently,
        name="file_delete_permanently",
    ),
        path(
        "drive/files/<int:file_id>/rename/",
        views.file_rename,
        name="file_rename",
    ),

    path(
        "drive/files/<int:file_id>/move/",
        views.file_move,
        name="file_move",
    ),
]