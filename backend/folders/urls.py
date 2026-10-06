from django.urls import path

from . import views

urlpatterns = [
    path("folder/<int:folder_id>/rename/", views.folder_rename, name="folder_rename"),
    path("folder/<int:folder_id>/delete/", views.folder_delete, name="folder_delete"),
    path("drive/create-folder/", views.folder_create, name="folder_create"),
    path("drive/folder/<int:folder_id>/", views.folder_open, name="folder_open"),
    path("drive/folder/<int:folder_id>/details/", views.folder_details, name="folder_details"),
    path("drive/folder/<int:folder_id>/download/", views.folder_download, name="folder_download"),
    path("folder/<int:folder_id>/restore/", views.folder_restore, name="folder_restore"),
    path("folder/<int:folder_id>/delete-permanently/", views.folder_delete_permanently, name="folder_delete_permanently"),
    path("trash/folder/<int:folder_id>/", views.trash_folder_open, name="trash_folder_open"),
    path("folders/<int:folder_id>/copy/", views.folder_copy, name="folder_copy"),
    path("folders/<int:folder_id>/cut/", views.folder_cut, name="folder_cut"),
    path("folders/paste/", views.folder_paste, name="folder_paste"),
    path("drive/folder-upload/", views.folder_upload, name="folder_upload"),
]
