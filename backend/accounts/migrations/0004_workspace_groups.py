import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models.functions import Lower


def create_default_workspaces(apps, schema_editor):
    database = schema_editor.connection.alias
    Tenant = apps.get_model("accounts", "Tenant")
    Membership = apps.get_model("accounts", "Membership")
    Workspace = apps.get_model("accounts", "Workspace")
    WorkspaceMembership = apps.get_model("accounts", "WorkspaceMembership")

    for tenant in Tenant.objects.using(database).all().iterator(chunk_size=500):
        workspace, _ = Workspace.objects.using(database).get_or_create(
            tenant_id=tenant.pk,
            is_default=True,
            defaults={
                "name": "General",
                "slug": "general",
                "description": "Default workspace for existing data.",
                "status": "active",
            },
        )
        for membership in Membership.objects.using(database).filter(
            tenant_id=tenant.pk
        ).iterator(chunk_size=500):
            role = "admin" if membership.role in ("owner", "admin") else "editor"
            assignment_status = "revoked" if membership.status == "revoked" else "active"
            WorkspaceMembership.objects.using(database).get_or_create(
                workspace_id=workspace.pk,
                membership_id=membership.pk,
                defaults={
                    "role": role,
                    "status": assignment_status,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_quotaaccount_quota_tenant_id_uniq"),
    ]

    operations = [
        migrations.CreateModel(
            name="Workspace",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("active", "Active"), ("archived", "Archived")], default="active", max_length=16)),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_workspaces", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="workspaces", to="accounts.tenant")),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="Group",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("active", "Active"), ("archived", "Archived")], default="active", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_tenant_groups", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="groups", to="accounts.tenant")),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="WorkspaceMembership",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(choices=[("admin", "Workspace admin"), ("editor", "Editor"), ("viewer", "Viewer")], default="viewer", max_length=16)),
                ("status", models.CharField(choices=[("active", "Active"), ("revoked", "Revoked")], default="active", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_workspace_memberships", to=settings.AUTH_USER_MODEL)),
                ("membership", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workspace_assignments", to="accounts.membership")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="member_assignments", to="accounts.workspace")),
            ],
        ),
        migrations.CreateModel(
            name="GroupMembership",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("added_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_group_memberships", to=settings.AUTH_USER_MODEL)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="member_assignments", to="accounts.group")),
                ("membership", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="group_assignments", to="accounts.membership")),
            ],
        ),
        migrations.CreateModel(
            name="WorkspaceGroupAccess",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(choices=[("admin", "Workspace admin"), ("editor", "Editor"), ("viewer", "Viewer")], default="viewer", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_workspace_group_grants", to=settings.AUTH_USER_MODEL)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workspace_access_grants", to="accounts.group")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="group_access_grants", to="accounts.workspace")),
            ],
        ),
        migrations.AddConstraint(
            model_name="workspace",
            constraint=models.UniqueConstraint(fields=("tenant", "slug"), name="workspace_tenant_slug_uniq"),
        ),
        migrations.AddConstraint(
            model_name="workspace",
            constraint=models.UniqueConstraint(fields=("tenant", "id"), name="workspace_tenant_id_uniq"),
        ),
        migrations.AddConstraint(
            model_name="workspace",
            constraint=models.UniqueConstraint(condition=models.Q(("is_default", True)), fields=("tenant",), name="workspace_one_default_per_tenant"),
        ),
        migrations.AddConstraint(
            model_name="workspace",
            constraint=models.CheckConstraint(condition=models.Q(("status__in", ["active", "archived"])), name="workspace_status_valid_check"),
        ),
        migrations.AddIndex(
            model_name="workspace",
            index=models.Index(fields=["tenant", "status"], name="workspace_tenant_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="group",
            constraint=models.UniqueConstraint(models.F("tenant"), Lower("name"), name="group_tenant_name_ci_uniq"),
        ),
        migrations.AddConstraint(
            model_name="group",
            constraint=models.UniqueConstraint(fields=("tenant", "id"), name="group_tenant_id_uniq"),
        ),
        migrations.AddConstraint(
            model_name="group",
            constraint=models.CheckConstraint(condition=models.Q(("status__in", ["active", "archived"])), name="group_status_valid_check"),
        ),
        migrations.AddIndex(
            model_name="group",
            index=models.Index(fields=["tenant", "status"], name="group_tenant_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="workspacemembership",
            constraint=models.UniqueConstraint(fields=("workspace", "membership"), name="workspace_member_pair_uniq"),
        ),
        migrations.AddConstraint(
            model_name="workspacemembership",
            constraint=models.UniqueConstraint(fields=("workspace", "id"), name="workspace_member_id_uniq"),
        ),
        migrations.AddConstraint(
            model_name="workspacemembership",
            constraint=models.CheckConstraint(condition=models.Q(("role__in", ["admin", "editor", "viewer"])), name="workspace_member_role_valid"),
        ),
        migrations.AddConstraint(
            model_name="workspacemembership",
            constraint=models.CheckConstraint(condition=models.Q(("status__in", ["active", "revoked"])), name="workspace_member_status_valid"),
        ),
        migrations.AddIndex(
            model_name="workspacemembership",
            index=models.Index(fields=["workspace", "status", "role"], name="workspace_member_role_idx"),
        ),
        migrations.AddConstraint(
            model_name="groupmembership",
            constraint=models.UniqueConstraint(fields=("group", "membership"), name="group_member_pair_uniq"),
        ),
        migrations.AddConstraint(
            model_name="groupmembership",
            constraint=models.UniqueConstraint(fields=("group", "id"), name="group_member_id_uniq"),
        ),
        migrations.AddIndex(
            model_name="groupmembership",
            index=models.Index(fields=["group", "membership"], name="group_membership_lookup_idx"),
        ),
        migrations.AddConstraint(
            model_name="workspacegroupaccess",
            constraint=models.UniqueConstraint(fields=("workspace", "group"), name="workspace_group_pair_uniq"),
        ),
        migrations.AddConstraint(
            model_name="workspacegroupaccess",
            constraint=models.CheckConstraint(condition=models.Q(("role__in", ["admin", "editor", "viewer"])), name="workspace_group_role_valid"),
        ),
        migrations.AddIndex(
            model_name="workspacegroupaccess",
            index=models.Index(fields=["workspace", "role"], name="workspace_group_role_idx"),
        ),
        migrations.RunPython(create_default_workspaces, migrations.RunPython.noop),
    ]
