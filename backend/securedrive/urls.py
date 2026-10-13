from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from .frontend_redirects import redirect_admin, redirect_admin_subpath

urlpatterns = [
    path('', include('dashboard.urls')),
    path('admin/', redirect_admin, name='admin-console'),
    path('admin/<path:subpath>', redirect_admin_subpath, name='legacy-admin-subpath'),
    path('accounts/', include('accounts.urls')),
    path('', include('folders.urls')),
    path('', include('files.urls')),
    path('', include('sharing.urls')),

]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
