from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.services import get_personal_tenant


@receiver(post_save, sender=get_user_model())
def create_personal_tenant_for_new_user(sender, instance, created, **kwargs):
    if created:
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
