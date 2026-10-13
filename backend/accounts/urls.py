from django.urls import path

from . import api_views, views


urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("api/csrf/", api_views.csrf_token_view, name="api-csrf"),
    path("api/register/", api_views.register_api_view, name="api-register"),
    path("api/login/", api_views.login_api_view, name="api-login"),
    path("api/me/", api_views.current_account_view, name="api-current-account"),
    path("api/logout/", api_views.logout_api_view, name="api-logout"),
    path(
        "api/tenants/<uuid:tenant_id>/memberships/<uuid:membership_id>/suspend/",
        api_views.suspend_tenant_member_view,
        name="api-suspend-tenant-member",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/memberships/<uuid:membership_id>/restore/",
        api_views.restore_tenant_member_view,
        name="api-restore-tenant-member",
    ),
]