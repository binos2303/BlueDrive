from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path(
        "recent/",
        views.recent,
        name="recent",
    ),
    path(
        "search/",
        views.search,
        name="search",
    ),
    path("drive/bulk-action/", views.bulk_action, name="bulk_action"),
    path("drive/bulk-paste/", views.bulk_paste, name="bulk_paste"),
	
]