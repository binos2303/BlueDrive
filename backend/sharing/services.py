from .models import Share
from files.models import File
from accounts.access import (
    active_membership,
    can_access_workspace,
    can_edit_workspace_content,
    has_active_membership,
    workspace_role_for_user,
)
from accounts.models import Membership, Tenant, Workspace


def _resource_tenant_is_active(resource):
    return resource.tenant.status == Tenant.Status.ACTIVE


def _resource_workspace_is_active(resource):
    workspace = getattr(resource, "workspace", None)
    return bool(
        workspace is not None
        and workspace.status == Workspace.Status.ACTIVE
        and workspace.tenant_id == resource.tenant_id
    )


def _owner_can_view_workspace_resource(resource, user):
    return (
        _resource_tenant_is_active(resource)
        and _resource_workspace_is_active(resource)
        and active_membership(user, resource.tenant_id) is not None
        and can_access_workspace(user, resource.workspace)
    )


def _owner_can_edit_workspace_resource(resource, user):
    return (
        _owner_can_view_workspace_resource(resource, user)
        and can_edit_workspace_content(user, resource.workspace)
    )


def _receiver_membership_allows(resource, user):
    if active_membership(user, resource.tenant_id) is not None:
        return True
    return not Membership.objects.filter(
        user_id=getattr(user, "pk", None),
        tenant_id=resource.tenant_id,
    ).exists()


def get_folder_ancestor_ids(folder):
    """Return the current folder followed by all of its ancestors."""
    folder_ids = []
    current = folder

    while current is not None:
        folder_ids.append(current.id)
        current = current.parent

    return folder_ids


def _folder_has_deleted_ancestor(folder):
    """Return True when this folder or one of its ancestors is in Trash."""
    current = folder
    visited = set()

    while current is not None:
        # Fail closed on a corrupt/cyclic tree, not just deleted parents.
        if current.pk in visited:
            return True
        visited.add(current.pk)
        if current.deleted_at is not None:
            return True
        # A malformed cross-workspace parent chain must never grant access.
        if (
            current.tenant_id != folder.tenant_id
            or current.workspace_id != folder.workspace_id
        ):
            return True
        current = current.parent

    return False


def _file_has_inaccessible_parent(drive_file):
    """Block every authorization path when a file's folder chain is unusable.

    A file can remain individually live while a parent is in Trash (or a
    malformed database row references a folder from another workspace).
    Neither Workspace membership nor a direct share may bypass that boundary.
    """
    folder = drive_file.folder
    return bool(
        folder is not None
        and (
            folder.tenant_id != drive_file.tenant_id
            or folder.workspace_id != drive_file.workspace_id
            or _folder_has_deleted_ancestor(folder)
        )
    )


def get_receiver_share_for_folder(folder, user):
    """
    Return the effective share for a folder.

    A direct share on the current folder has priority over inherited
    shares from its parents. A deleted folder tree is not accessible.
    """
    if folder is None or _folder_has_deleted_ancestor(folder):
        return None
    if (
        not _resource_tenant_is_active(folder)
        or not _resource_workspace_is_active(folder)
        or not has_active_membership(user)
        or not _receiver_membership_allows(folder, user)
    ):
        return None

    folder_ids = get_folder_ancestor_ids(folder)

    shares = (
        Share.objects
        .filter(
            receiver=user,
            owner_id=folder.owner_id,
            tenant_id=folder.tenant_id,
            folder_id__in=folder_ids,
        )
        .select_related(
            "owner",
            "receiver",
            "folder",
        )
    )

    shares_by_folder = {
        share.folder_id: share
        for share in shares
    }

    for folder_id in folder_ids:
        share = shares_by_folder.get(folder_id)
        if share is not None:
            return share

    return None


def get_receiver_share_for_file(drive_file, user):
    """
    Return the effective share for a file.

    A direct file share has priority over an inherited folder share.
    A file inside a deleted folder tree is inaccessible.
    """
    if drive_file is None:
        return None

    if drive_file.deleted_at is not None:
        return None
    if (
        not _resource_tenant_is_active(drive_file)
        or not _resource_workspace_is_active(drive_file)
        or not has_active_membership(user)
        or not _receiver_membership_allows(drive_file, user)
    ):
        return None

    if drive_file.folder is None:
        direct_share = (
            Share.objects
            .filter(
                receiver=user,
                owner_id=drive_file.owner_id,
                tenant_id=drive_file.tenant_id,
                file=drive_file,
            )
            .select_related(
                "owner",
                "receiver",
                "file",
            )
            .first()
        )
        return direct_share

    if _file_has_inaccessible_parent(drive_file):
        return None

    direct_share = (
        Share.objects
        .filter(
            receiver=user,
            owner_id=drive_file.owner_id,
            tenant_id=drive_file.tenant_id,
            file=drive_file,
        )
        .select_related(
            "owner",
            "receiver",
            "file",
        )
        .first()
    )

    if direct_share is not None:
        return direct_share

    return get_receiver_share_for_folder(
        drive_file.folder,
        user,
    )


def can_view_file(drive_file, user):
    """Authorize a live file with a live, correctly scoped folder chain."""
    if drive_file is None or drive_file.deleted_at is not None or _file_has_inaccessible_parent(drive_file):
        return False
    # Workspace members can collaborate on workspace files without requiring
    # a separate Share row for every item. My Drive remains private because its
    # default workspace is only assigned to its owner.
    if _owner_can_view_workspace_resource(drive_file, user):
        return True
    return get_receiver_share_for_file(drive_file, user) is not None


def can_edit_file(drive_file, user):
    """
    Return True when the user can modify the file.

    Owner:
        Full access.

    Editor:
        Can modify.

    Viewer:
        Read/download only.
    """
    if drive_file is None or drive_file.deleted_at is not None or _file_has_inaccessible_parent(drive_file):
        return False
    if _owner_can_edit_workspace_resource(drive_file, user):
        return True

    share = get_receiver_share_for_file(
        drive_file,
        user,
    )

    return (
        share is not None
        and share.permission == Share.Permission.EDITOR
    )


def can_view_folder(folder, user):
    """A folder with any deleted or invalid ancestor is not visible."""
    if folder is None or _folder_has_deleted_ancestor(folder):
        return False
    if _owner_can_view_workspace_resource(folder, user):
        return True
    return get_receiver_share_for_folder(folder, user) is not None


def can_edit_folder(folder, user):
    """
    Return True when the user can modify the folder.

    Owner:
        Full access.

    Editor:
        Can modify.

    Viewer:
        Read-only.
    """
    if folder is None or _folder_has_deleted_ancestor(folder):
        return False
    if _owner_can_edit_workspace_resource(folder, user):
        return True

    share = get_receiver_share_for_folder(
        folder,
        user,
    )

    return (
        share is not None
        and share.permission == Share.Permission.EDITOR
    )


def is_descendant_or_same(candidate, ancestor):
    """
    Return True when candidate is the same folder as ancestor or is
    located anywhere below it in the folder tree.

    Used to prevent moving/copying a folder into itself or one of
    its descendants.
    """
    if candidate is None or ancestor is None:
        return False

    current = candidate
    visited = set()

    while current is not None:
        if current.pk in visited:
            # Corrupt cycles must not hang move/copy permission checks.
            return False
        visited.add(current.pk)
        if current.pk == ancestor.pk:
            return True
        current = current.parent

    return False


def can_edit_folder_tree(folder, user):
    """
    Return True when the user can edit the complete live subtree
    rooted at `folder`.

    Workspace Editors/Admins can edit the live tree regardless of its creator.

    For a shared tree, every live folder in the subtree must resolve
    to an Editor permission. This deliberately respects direct child
    shares: a Viewer share on a child overrides an inherited Editor
    share and therefore prevents an operation that requires editing
    the complete tree.
    """
    if folder is None:
        return False

    if _folder_has_deleted_ancestor(folder):
        return False
    if _owner_can_edit_workspace_resource(folder, user):
        return True
    if folder.owner_id == user.id:
        return False

    root_share = get_receiver_share_for_folder(
        folder,
        user,
    )

    if (
        root_share is None
        or root_share.permission != Share.Permission.EDITOR
    ):
        return False

    # Check every live descendant. This protects tree operations such
    # as copy/cut from silently modifying content the user can only view.
    pending = [folder]

    while pending:
        current = pending.pop()

        children = (
            current.__class__.objects
            .filter(
                owner=folder.owner,
                tenant=folder.tenant,
                workspace=folder.workspace,
                parent=current,
                deleted_at__isnull=True,
            )
        )

        for child in children:
            child_share = get_receiver_share_for_folder(
                child,
                user,
            )

            if (
                child_share is None
                or child_share.permission != Share.Permission.EDITOR
            ):
                return False

            pending.append(child)

    return True


def can_edit_destination_folder(
    folder,
    user,
    *,
    shared_root=None,
):
    """
    Return True when `folder` can be used as a destination by `user`.

    Owner:
        Any live folder owned by the user.

    Shared Editor:
        The destination must be inside the shared root and the user
        must have effective Editor permission on that destination.

    Viewer:
        Never allowed to use a shared folder as an edit destination.

    `folder=None` represents the user's drive root. A shared Editor
    cannot paste a shared tree into My Drive, so it returns False.
    """
    if folder is None:
        return False

    if _folder_has_deleted_ancestor(folder):
        return False

    if folder.owner_id == user.id:
        if not _owner_can_edit_workspace_resource(folder, user):
            return False
        if shared_root is not None:
            return is_descendant_or_same(folder, shared_root)
        return True

    if shared_root is None:
        return can_edit_folder(folder, user)

    if folder.owner_id != shared_root.owner_id:
        return False

    if not is_descendant_or_same(folder, shared_root):
        return False

    return can_edit_folder(folder, user)

def upsert_direct_share(*, resource, receiver, owner, permission):
    """Upsert one grant and report a *real* change under a row lock.

    Caller must use transaction.atomic. Identical repeated shares are no-ops
    and should not generate an activity event or an email notification.
    """
    from .models import Share

    if resource.__class__.__name__ == "File":
        target = {"file": resource}
    elif resource.__class__.__name__ == "Folder":
        target = {"folder": resource}
    else:
        raise ValueError("Only files and folders may be directly shared")
    share, created = Share.objects.select_for_update().get_or_create(
        **target, receiver=receiver,
        defaults={"tenant": resource.tenant, "owner": owner, "permission": permission},
    )
    if created:
        return "created", None
    previous_permission = share.permission
    if previous_permission == permission:
        return "unchanged", previous_permission
    share.permission = permission
    share.save(update_fields=["permission"])
    return "permission_changed", previous_permission

def can_manage_direct_share(resource, actor):
    """Only the file/folder owner with current Workspace edit rights manages grants."""
    from files.cse import is_cse_file
    from files.models import File
    if resource is None or resource.owner_id != actor.pk or resource.deleted_at is not None:
        return False
    if not _owner_can_edit_workspace_resource(resource, actor):
        return False
    if isinstance(resource, File):
        if is_cse_file(resource):
            return False
        folder = resource.folder
    else:
        folder = resource
    return folder is None or not _folder_has_deleted_ancestor(folder)


def change_direct_share_permission(*, share, actor, permission):
    """Requires a locked Share row inside transaction.atomic(). Audit real changes."""
    from logs.models import ActivityLog
    from logs.services import log_action

    if permission not in {Share.Permission.VIEWER, Share.Permission.EDITOR}:
        raise ValueError("Unsupported permission")
    previous = share.permission
    if previous == permission:
        return False
    resource = share.file if share.file_id else share.folder
    kind = share.item_type
    name = resource.file_name if share.file_id else resource.folder_name
    share.permission = permission
    share.save(update_fields=["permission"])
    log_action(
        actor, ActivityLog.Action.SHARE,
        f"Changed access to {name} for {share.receiver.username} from {previous} to {permission}",
        obj=resource,
        metadata={
            "operation": "permission_changed", "recipient_username": share.receiver.get_username(),
            "recipient_email": share.receiver.email, "permission": permission,
            "previous_permission": previous, "shared_count": 1,
            "resource_names": [name], "resource_kinds": [kind],
            "resource_changes": [{"name": name, "kind": kind, "operation": "permission_changed",
                                  "permission": permission, "previous_permission": previous}],
        },
    )
    return True


def revoke_direct_share(*, share, actor):
    """Requires a locked Share row inside transaction.atomic()."""
    from logs.models import ActivityLog
    from logs.services import log_action

    resource = share.file if share.file_id else share.folder
    kind = share.item_type
    name = resource.file_name if share.file_id else resource.folder_name
    recipient = share.receiver
    permission = share.permission
    share.delete()
    log_action(
        actor, ActivityLog.Action.REVOKE_SHARE,
        f"Revoked access to {name} for {recipient.username}",
        obj=resource,
        metadata={
            "operation": "revoked", "recipient_username": recipient.get_username(),
            "recipient_email": recipient.email, "permission": permission,
            "shared_count": 1, "resource_names": [name], "resource_kinds": [kind],
            "resource_changes": [{"name": name, "kind": kind, "operation": "revoked", "permission": permission}],
        },
    )


def describe_resource_access(resource, user, *, share=None):
    """Consistent details metadata for owners, workspace members and shares.

    Only call this after can_view_file/can_view_folder has authorized the item.
    A Workspace role is not a global platform role; direct share access is
    independent and may grant Editor to a recipient outside the Workspace.
    """
    if resource.owner_id == user.pk:
        return {"access": "Owner", "permission": None, "shared_by": None}

    role = workspace_role_for_user(user, resource.workspace)
    is_file = resource.__class__.__name__ == "File"
    editable = can_edit_file(resource, user) if is_file else can_edit_folder(resource, user)
    effective_permission = Share.Permission.EDITOR if editable else Share.Permission.VIEWER

    if role is not None:
        # A direct Editor grant can exceed a Viewer Workspace role; reflect
        # effective access rather than reporting a misleading Viewer label.
        if role == "viewer" and editable:
            label = "Editor (direct share)"
        else:
            label = f"Workspace {role.title()}"
        return {
            "access": label, "permission": effective_permission,
            "shared_by": share.owner.get_username() if share is not None else None,
        }
    return {
        "access": share.permission_label if share is not None else "Viewer",
        "permission": effective_permission,
        "shared_by": share.owner.get_username() if share is not None else None,
    }
