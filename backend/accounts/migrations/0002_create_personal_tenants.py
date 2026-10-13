from django.conf import settings
from django.db import migrations


def create_personal_tenants(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Tenant = apps.get_model("accounts", "Tenant")
    Membership = apps.get_model("accounts", "Membership")
    QuotaAccount = apps.get_model("accounts", "QuotaAccount")
    database = schema_editor.connection.alias

    tenants = []
    memberships = []
    quota_accounts = []
    for user in User.objects.using(database).only("pk", "username").iterator(
        chunk_size=500
    ):
        tenant = Tenant(
            kind="personal",
            name=f"{user.username}'s Drive"[:255],
            personal_owner_id=user.pk,
            status="active",
        )
        tenants.append(tenant)
        memberships.append(
            Membership(
                tenant_id=tenant.pk,
                user_id=user.pk,
                role="owner",
                status="active",
            )
        )
        quota_accounts.append(
            QuotaAccount(
                tenant_id=tenant.pk,
                scope="tenant",
                limit_bytes=None,
                used_bytes=0,
                reserved_bytes=0,
            )
        )
        if len(tenants) == 500:
            Tenant.objects.using(database).bulk_create(tenants, batch_size=500)
            Membership.objects.using(database).bulk_create(
                memberships, batch_size=500
            )
            QuotaAccount.objects.using(database).bulk_create(
                quota_accounts, batch_size=500
            )
            tenants.clear()
            memberships.clear()
            quota_accounts.clear()

    if tenants:
        Tenant.objects.using(database).bulk_create(tenants, batch_size=500)
        Membership.objects.using(database).bulk_create(
            memberships, batch_size=500
        )
        QuotaAccount.objects.using(database).bulk_create(
            quota_accounts, batch_size=500
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(create_personal_tenants),
    ]
