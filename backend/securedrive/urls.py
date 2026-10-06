from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
urlpatterns = [
    path('', include('dashboard.urls')),
    path('admin/', admin.site.urls),
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