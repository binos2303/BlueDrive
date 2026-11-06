from django.contrib.contenttypes.models import ContentType

from .models import ActivityLog


def log_action(user, action, description="", *, obj=None, workspace=None, metadata=None):
    """Write an immutable audit event, optionally linked to a resource."""
    if not getattr(user, "is_authenticated", False):
        return

    # Make a private event snapshot. Never depend on mutable objects for the
    # name shown later in audit (the object may be renamed or deleted).
    details = dict(metadata) if isinstance(metadata, dict) else {}
    if obj is not None:
        resource_name = getattr(obj, "file_name", None) or getattr(obj, "folder_name", None)
        if isinstance(resource_name, str):
            details.setdefault("resource_name", resource_name[:200])
            details.setdefault("resource_kind", "file" if hasattr(obj, "file_name") else "folder")
    kwargs = {
        "user": user,
        "action": action,
        "description": description[:500],
        "metadata": details,
    }
    if workspace is not None:
        kwargs["workspace_id"] = workspace.pk
        kwargs["tenant_id"] = workspace.tenant_id
    if obj is not None:
        kwargs["content_type"] = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        kwargs["object_id"] = obj.pk
        kwargs["tenant_id"] = getattr(obj, "tenant_id", kwargs.get("tenant_id"))
        # Resource events become queryable by workspace without depending on
        # free-form descriptions or JSON metadata.
        workspace_id = getattr(obj, "workspace_id", None)
        if workspace_id is None and obj.__class__.__name__ == "Workspace":
            workspace_id = obj.pk
        if workspace_id is not None:
            kwargs["workspace_id"] = workspace_id

    return ActivityLog.objects.create(**kwargs)


def get_last_activity(obj):
    """Return the latest audit event explicitly linked to *obj*."""
    if obj is None or obj.pk is None:
        return None
    content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    return (
        ActivityLog.objects
        .filter(content_type=content_type, object_id=obj.pk)
        .select_related("user")
        .first()
    )
