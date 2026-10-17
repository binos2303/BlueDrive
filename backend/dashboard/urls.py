
from django.urls import path
from . import views
from .drive_api import (
    drive_items_move_api,
    drive_items_duplicate_api,
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
    path("", views.dashboard, name="dashboard"),
    path("recent/", views.recent, name="recent"),
    path("search/", views.search, name="search"),
    path("drive/bulk-action/", views.bulk_action, name="bulk_action"),
    path("drive/bulk-paste/", views.bulk_paste, name="bulk_paste"),
]
