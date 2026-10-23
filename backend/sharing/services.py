from .models import Share
from accounts.access import (
    active_membership,
    can_access_workspace,
    can_edit_workspace_content,
    has_active_membership,
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

    while current is not None:
        if current.deleted_at is not None:
            return True
        # A malformed cross-workspace parent chain must never inherit a share.
        if (
            current.tenant_id != folder.tenant_id
            or current.workspace_id != folder.workspace_id
        ):
            return True
        current = current.parent

    return False


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

    if (
        drive_file.folder.workspace_id != drive_file.workspace_id
        or drive_file.folder.tenant_id != drive_file.tenant_id
        or _folder_has_deleted_ancestor(drive_file.folder)
    ):
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
    """Return True for an authorized workspace member or direct share recipient."""
    if drive_file.deleted_at is not None:
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
    if drive_file.deleted_at is not None:
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
    """Return True for an authorized workspace member or direct share recipient."""
    if folder.deleted_at is not None:
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
    if folder.deleted_at is not None:
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

    while current is not None:
        if current.id == ancestor.id:
            return True
        current = current.parent

    return False


def can_edit_folder_tree(folder, user):
    """
    Return True when the user can edit the complete live subtree
    rooted at `folder`.

    The owner can always edit the tree while the root is live.

    For a shared tree, every live folder in the subtree must resolve
    to an Editor permission. This deliberately respects direct child
    shares: a Viewer share on a child overrides an inherited Editor
    share and therefore prevents an operation that requires editing
    the complete tree.
    """
    if folder is None:
        return False

    if folder.owner_id == user.id:
        return (
            not _folder_has_deleted_ancestor(folder)
            and _owner_can_edit_workspace_resource(folder, user)
        )

    if _folder_has_deleted_ancestor(folder):
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