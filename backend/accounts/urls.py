from django.urls import path

from . import admin_api, api_views, settings_api, views, workspace_api


urlpatterns = [
    path("api/admin/access/", admin_api.admin_access_view, name="api-admin-access"),
    path("api/admin/users/", admin_api.admin_users_view, name="api-admin-users"),
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("api/csrf/", api_views.csrf_token_view, name="api-csrf"),
    path("api/register/", api_views.register_api_view, name="api-register"),
    path("api/login/", api_views.login_api_view, name="api-login"),
    path("api/me/", api_views.current_account_view, name="api-current-account"),
    path("api/me/quota/", settings_api.my_quota_view, name="api-my-quota"),
    path("api/me/activity/", settings_api.my_activity_view, name="api-my-activity"),
    path("api/me/search-history/", settings_api.my_search_history_view, name="api-my-search-history"),
    path("api/me/delete-data/", settings_api.delete_my_drive_data_view, name="api-delete-my-drive-data"),
    path("api/logout/", api_views.logout_api_view, name="api-logout"),
    path("api/workspaces/", workspace_api.my_workspaces_view, name="api-my-workspaces"),
    path(
        "api/workspaces/<uuid:workspace_id>/",
        workspace_api.my_workspace_detail_view,
        name="api-my-workspace-detail",
    ),
    path(
        "api/workspaces/<uuid:workspace_id>/invites/",
        workspace_api.create_workspace_invite_view,
        name="api-create-workspace-invite",
    ),
    path(
        "api/workspaces/<uuid:workspace_id>/activity/",
        workspace_api.workspace_activity_view,
        name="api-workspace-activity",
    ),
    path(
        "api/workspace-invites/preview/",
        workspace_api.preview_workspace_invite_view,
        name="api-preview-workspace-invite",
    ),
    path(
        "api/workspace-invites/accept/",
        workspace_api.accept_workspace_invite_view,
        name="api-accept-workspace-invite",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/members/",
        workspace_api.organization_members_view,
        name="api-organization-members",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/workspaces/",
        workspace_api.workspaces_view,
        name="api-organization-workspaces",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/workspaces/<uuid:workspace_id>/",
        workspace_api.workspace_detail_view,
        name="api-organization-workspace-detail",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/workspaces/<uuid:workspace_id>/members/",
        workspace_api.workspace_members_view,
        name="api-workspace-members",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/workspaces/<uuid:workspace_id>/members/<uuid:membership_id>/",
        workspace_api.workspace_member_detail_view,
        name="api-workspace-member-detail",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/workspaces/<uuid:workspace_id>/groups/",
        workspace_api.workspace_groups_view,
        name="api-workspace-groups",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/workspaces/<uuid:workspace_id>/groups/<uuid:group_id>/",
        workspace_api.workspace_group_detail_view,
        name="api-workspace-group-detail",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/groups/",
        workspace_api.groups_view,
        name="api-organization-groups",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/groups/<uuid:group_id>/",
        workspace_api.group_detail_view,
        name="api-organization-group-detail",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/groups/<uuid:group_id>/members/",
        workspace_api.group_members_view,
        name="api-group-members",
    ),
    path(
        "api/tenants/<uuid:tenant_id>/groups/<uuid:group_id>/members/<uuid:membership_id>/",
        workspace_api.group_member_detail_view,
        name="api-group-member-detail",
    ),
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