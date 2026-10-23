
from django.urls import path
from . import views
from .drive_api import (
    drive_items_move_api,
    drive_items_duplicate_api,
    drive_items_trash_api,
    drive_items_restore_api,
    drive_items_delete_api,
    drive_items_star_api,
    drive_folder_tree_api,
    drive_items_share_api,
)

urlpatterns = [
    path("drive/api/items/", views.drive_items_api, name="drive_items_api"),
    path(
        "drive/api/items/move/",
        drive_items_move_api,
        name="drive_items_move_api",
    ),
    path(
        "drive/api/items/duplicate/",
        drive_items_duplicate_api,
        name="drive_items_duplicate_api",
    ),
    path(
        "drive/api/items/trash/",
        drive_items_trash_api,
        name="drive_items_trash_api",
    ),
    path(
        "drive/api/items/restore/",
        drive_items_restore_api,
        name="drive_items_restore_api",
    ),
    path(
        "drive/api/items/delete/",
        drive_items_delete_api,
        name="drive_items_delete_api",
    ),
    path(
        "drive/api/items/star/",
        drive_items_star_api,
        name="drive_items_star_api",
    ),
    path(
        "drive/api/folder-tree/",
        drive_folder_tree_api,
        name="drive_folder_tree_api",
    ),
    path(
        "drive/api/items/share/",
        drive_items_share_api,
        name="drive_items_share_api",
    ),
    path("", views.dashboard, name="dashboard"),
    path("recent/", views.recent, name="recent"),
    path("search/", views.search, name="search"),
    path("drive/bulk-action/", views.bulk_action, name="bulk_action"),
    path("drive/bulk-paste/", views.bulk_paste, name="bulk_paste"),
]
