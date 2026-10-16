from django.urls import path

from . import views, upload_api

urlpatterns = [
    path("files/api/uploads/", upload_api.create_upload, name="api-upload-create"),
    path("files/api/uploads/<uuid:upload_id>/", upload_api.upload_status, name="api-upload-status"),
    path("files/api/uploads/<uuid:upload_id>/parts/<int:part_number>/authorization/", upload_api.authorize_part, name="api-upload-part-authorization"),
    path("files/api/uploads/<uuid:upload_id>/parts/authorizations/", upload_api.authorize_parts, name="api-upload-parts-authorization-batch"),
    path("files/api/uploads/<uuid:upload_id>/complete/", upload_api.complete_upload, name="api-upload-complete"),
    path("files/api/uploads/<uuid:upload_id>/abort/", upload_api.abort_upload, name="api-upload-abort"),
    path("drive/upload/", views.file_upload, name="file_upload"),
    path("drive/files/<int:file_id>/view/", views.file_view, name="file_view"),
    path("drive/files/<int:file_id>/details/", views.file_details, name="file_details"),
    path("drive/files/<int:file_id>/download/", views.file_download, name="file_download"),
    path("drive/files/<int:file_id>/trash/", views.file_move_to_trash, name="file_move_to_trash"),
    path("drive/trash/", views.trash, name="trash"),
    path("drive/trash/bulk-action/", views.trash_bulk_action, name="trash_bulk_action"),
    path("drive/files/<int:file_id>/restore/", views.file_restore, name="file_restore"),
    path("drive/files/<int:file_id>/delete/", views.file_delete_permanently, name="file_delete_permanently"),
    path("drive/files/<int:file_id>/rename/", views.file_rename, name="file_rename"),
    path("files/<int:file_id>/move/", views.file_move, name="file_move"),
    path("files/<int:file_id>/copy/", views.file_copy, name="file_copy"),
    path("files/paste/", views.file_paste, name="file_paste"),
    path("file/<int:file_id>/cut/", views.file_cut, name="file_cut"),
]
