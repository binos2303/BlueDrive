from django.urls import path

from . import views


urlpatterns = [
    path(
        "drive/create-folder/",
        views.folder_create,
        name="folder_create"
    ),
    path(
        "drive/folder/<int:folder_id>/",
        views.folder_open,
        name="folder_open"
    ),
]