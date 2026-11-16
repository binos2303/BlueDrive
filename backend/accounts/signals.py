from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.services import get_personal_tenant, starting_storage_plan
from accounts.platform_admin import is_platform_admin


@receiver(post_save, sender=get_user_model())
def create_personal_tenant_for_new_user(sender, instance, created, **kwargs):
    # Provisioned admins are created inactive with an unusable password.
    # They are staff before the first post_save, so they must never receive
    # the ordinary user's Personal Tenant during invitation.
    if created and not instance.is_staff and not instance.is_superuser:
        get_personal_tenant(instance)


from accounts.models import Membership, Tenant, WorkspaceMembership
from accounts.access import get_default_workspace


@receiver(post_save, sender=Membership)
def ensure_default_workspace_for_new_membership(sender, instance, created, **kwargs):
    if not created:
        return
    # A membership added to another user's personal tenant (for example when
    # accepting a Workspace invitation) must not grant access to its private
    # default/My Drive workspace. Business members also receive no implicit
    # access to a workspace; grants must be explicit and least-privilege.
    tenant = instance.tenant
    if tenant.kind == Tenant.Kind.PERSONAL and tenant.personal_owner_id != instance.user_id:
        return
    if instance.role == Membership.Role.MEMBER:
        return
    if instance.status == Membership.Status.REVOKED:
        assignment_status = WorkspaceMembership.Status.REVOKED
    else:
        assignment_status = WorkspaceMembership.Status.ACTIVE
    workspace = get_default_workspace(instance.tenant)
    role = (
        WorkspaceMembership.Role.ADMIN
        if instance.role in (Membership.Role.OWNER, Membership.Role.ADMIN)
        else WorkspaceMembership.Role.EDITOR
    )
    WorkspaceMembership.objects.get_or_create(
        workspace=workspace,
        membership=instance,
        defaults={"role": role, "status": assignment_status},
    )


@receiver(post_save, sender="accounts.Workspace")
def provision_new_workspace_quota(sender, instance, created, **kwargs):
    """Assign Workspace Starter to newly created non-default workspaces."""
    if created and not instance.is_default:
        from accounts.models import QuotaAccount, StoragePlan
        plan = starting_storage_plan(StoragePlan.Scope.WORKSPACE)
        QuotaAccount.objects.get_or_create(
            tenant=instance.tenant, workspace=instance,
            scope=QuotaAccount.Scope.WORKSPACE,
            defaults={"plan": plan, "limit_bytes": plan.limit_bytes},
        )
