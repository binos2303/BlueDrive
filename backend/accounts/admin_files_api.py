"""Read-only platform file inventory.

This API intentionally returns metadata only. It must never expose file bytes,
MinIO object references, presigned URLs, encryption material, or storage secrets.
"""
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from files.models import File, FileVersion, StorageLocation
from files.permanent_delete import permanently_delete_files
from .api_views import require_csrf
from .admin_api import IsPlatformAdmin
from .models import PlatformAdminAuditEvent
from .platform_admin import is_platform_super_admin


DOCUMENT_EXTENSIONS = (".pdf", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".odt", ".ods")
ARCHIVE_EXTENSIONS = (".zip", ".rar", ".7z", ".tar", ".gz")
FILE_TYPES = ("all", "document", "image", "video", "audio", "archive", "other")


def _ends_in(extensions):
    matcher = Q()
    for extension in extensions:
        matcher |= Q(file_name__iendswith=extension)
    return matcher


def _file_type_q(file_type):
    image = Q(mime_type__istartswith="image/") | _ends_in((".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"))
    video = Q(mime_type__istartswith="video/") | _ends_in((".mp4", ".mov", ".webm", ".avi"))
    audio = Q(mime_type__istartswith="audio/") | _ends_in((".mp3", ".wav", ".ogg", ".flac"))
    archive = Q(mime_type__in=("application/zip", "application/x-7z-compressed", "application/x-rar-compressed", "application/x-tar", "application/gzip")) | _ends_in(ARCHIVE_EXTENSIONS)
    document = Q(mime_type__istartswith="text/") | Q(mime_type="application/pdf") | Q(mime_type__icontains="officedocument") | Q(mime_type__icontains="msword") | Q(mime_type__icontains="ms-excel") | Q(mime_type__icontains="ms-powerpoint") | _ends_in(DOCUMENT_EXTENSIONS)
    categories = {"document": document, "image": image, "video": video, "audio": audio, "archive": archive}
    if file_type == "other":
        return ~(document | image | video | audio | archive)
    return categories.get(file_type, Q())


def _parse_uuid(value, name):
    if not value:
        return None, None
    try:
        return UUID(value), None
    except (TypeError, AttributeError, ValueError):
        return None, Response({"detail": f"Invalid {name}."}, status=400)


def _serialize_file(file):
    is_org = file.tenant.kind == "business"
    return {
        "id": file.pk,
        "name": file.file_name,
        "size_bytes": file.file_size,
        "mime_type": file.mime_type,
        "owner": {"id": file.owner_id, "username": file.owner.get_username()},
        "scope": "organization" if is_org else ("my_drive" if file.workspace.is_default else "workspace"),
        "organization": {"id": str(file.tenant_id), "name": file.tenant.name} if is_org else None,
        "workspace": {"id": str(file.workspace_id), "name": file.workspace.name},
        "folder": {"id": file.folder_id, "name": file.folder.folder_name} if file.folder_id else None,
        "lifecycle": "trash" if file.deleted_at else "active",
        "version_state": getattr(file, "current_version_state", None),
        "current_version": getattr(file, "current_version_number", None),
        "version_count": getattr(file, "version_count", None),
        "is_encrypted": file.is_encrypted,
        "created_at": file.created_at.isoformat(),
        "updated_at": file.updated_at.isoformat(),
        "deleted_at": file.deleted_at.isoformat() if file.deleted_at else None,
    }


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_files_view(request):
    """Paginated file metadata across all tenants, with strict filter validation."""
    params = request.query_params
    query = params.get("q", "").strip()[:120]
    scope = params.get("scope", "all")
    lifecycle = params.get("status", "active")
    file_type = params.get("type", "all")
    sort = params.get("sort", "newest")
    if scope not in ("all", "my_drive", "workspace", "organization") or lifecycle not in ("all", "active", "trash") or file_type not in FILE_TYPES:
        return Response({"detail": "Invalid file filters."}, status=400)
    ordering = {"newest": ("-created_at", "-pk"), "oldest": ("created_at", "pk"),
                "name": ("file_name", "pk"), "largest": ("-file_size", "-pk"), "updated": ("-updated_at", "-pk")}
    if sort not in ordering:
        return Response({"detail": "Invalid sorting option."}, status=400)
    try:
        page = int(params.get("page", "1"))
        if page < 1 or page > 100000:
            raise ValueError
    except (ValueError, TypeError):
        return Response({"detail": "Invalid page."}, status=400)
    workspace_id, error = _parse_uuid(params.get("workspace_id"), "workspace_id")
    if error is not None:
        return error
    tenant_id, error = _parse_uuid(params.get("tenant_id"), "tenant_id")
    if error is not None:
        return error
    owner_id = params.get("owner_id")
    if owner_id:
        try:
            owner_id = int(owner_id)
            if owner_id <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return Response({"detail": "Invalid owner_id."}, status=400)

    files = File.objects.all()
    if scope == "organization":
        files = files.filter(tenant__kind="business")
    elif scope == "my_drive":
        files = files.filter(tenant__kind="personal", workspace__is_default=True)
    elif scope == "workspace":
        files = files.filter(tenant__kind="personal", workspace__is_default=False)
    if workspace_id:
        files = files.filter(workspace_id=workspace_id)
    if tenant_id:
        files = files.filter(tenant_id=tenant_id)
    if owner_id:
        files = files.filter(owner_id=owner_id)
    if query:
        files = files.filter(Q(file_name__icontains=query) | Q(owner__username__icontains=query)
                             | Q(workspace__name__icontains=query) | Q(tenant__name__icontains=query))
    if file_type != "all":
        files = files.filter(_file_type_q(file_type))
    # Summary respects all filters other than lifecycle, allowing the UI to
    # show active vs trash counts while switching tabs without fabricated data.
    summary = files.aggregate(
        active=Count("pk", filter=Q(deleted_at__isnull=True)),
        trash=Count("pk", filter=Q(deleted_at__isnull=False)),
        active_bytes=Sum("file_size", filter=Q(deleted_at__isnull=True)),
    )
    if lifecycle == "active":
        files = files.filter(deleted_at__isnull=True)
    elif lifecycle == "trash":
        files = files.filter(deleted_at__isnull=False)

    count = files.count()
    current = FileVersion.objects.filter(file_id=OuterRef("pk"), is_current=True).order_by("-version_number")
    files = files.select_related("owner", "tenant", "workspace", "folder").annotate(
        current_version_state=Subquery(current.values("state")[:1]),
        current_version_number=Subquery(current.values("version_number")[:1]),
        version_count=Count("versions", distinct=True),
    ).order_by(*ordering[sort])
    page_size = 20
    results = files[(page - 1) * page_size:page * page_size]
    return Response({
        "count": count, "page": page, "page_size": page_size,
        "summary": {"active": summary["active"], "trash": summary["trash"],
                    "active_metadata_bytes": summary["active_bytes"] or 0},
        "results": [_serialize_file(file) for file in results],
        "permissions": {"can_manage_files": is_platform_super_admin(request.user)},
    })


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_file_detail_view(request, file_id):
    """Safe metadata, version timeline, and logical storage states; no file content."""
    file = File.objects.select_related("owner", "tenant", "workspace", "folder").filter(pk=file_id).first()
    if file is None:
        return Response({"detail": "File not found."}, status=404)
    versions_qs = FileVersion.objects.filter(file=file)
    version_count = versions_qs.count()
    versions = list(versions_qs.order_by("-version_number", "-created_at")[:30])
    locations = StorageLocation.objects.filter(
        file_version_id__in=[version.id for version in versions],
    ).select_related("storage_config").order_by("id")
    locations_by_version = {}
    for location in locations:
        locations_by_version.setdefault(location.file_version_id, []).append({
            "provider": location.storage_config.provider,
            "state": location.state,
            "verified_at": location.verified_at.isoformat() if location.verified_at else None,
        })
    result = _serialize_file(file)
    result.update({
        "last_accessed_at": file.last_accessed_at.isoformat() if file.last_accessed_at else None,
        "purge_after": file.purge_after.isoformat() if file.purge_after else None,
        "version_count": version_count,
        "versions": [
            {"id": str(version.id), "number": version.version_number,
             "state": version.state, "is_current": version.is_current,
             "size_bytes": version.size_bytes, "mime_type": version.mime_type,
             "created_at": version.created_at.isoformat(),
             "verified_at": version.verified_at.isoformat() if version.verified_at else None,
             "storage": locations_by_version.get(version.id, [])}
            for version in versions
        ],
        "versions_limit": 30,
    })
    return Response(result)


ACTIONS = {"trash", "restore", "purge"}


def _validate_admin_file_action(data):
    """Strict operation contract: no accidental mass action or implicit purge."""
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    expected = {"action", "reason", "confirm_name"} if action == "purge" else {"action", "reason"}
    if action not in ACTIONS or set(data) != expected:
        return None
    reason = data.get("reason")
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        return None
    if action == "purge" and (not isinstance(data.get("confirm_name"), str) or len(data["confirm_name"]) > 255):
        return None
    return action, reason.strip(), data.get("confirm_name")


def _audit_file_action(actor, drive_file, action, reason, **extra):
    """Only operational identifiers; never store object refs or file bytes."""
    return PlatformAdminAuditEvent.objects.create(
        actor=actor, target_user=drive_file.owner,
        action=action, reason=reason,
        metadata={
            "file_id": drive_file.pk,
            "tenant_id": str(drive_file.tenant_id),
            "workspace_id": str(drive_file.workspace_id),
            **extra,
        },
    )


def _live_parent_chain(drive_file):
    """A trashed or cross-workspace ancestor must never be bypassed by restore."""
    folder = drive_file.folder
    seen = set()
    while folder is not None:
        if (folder.pk in seen or folder.deleted_at is not None
                or folder.tenant_id != drive_file.tenant_id
                or folder.workspace_id != drive_file.workspace_id):
            return False
        seen.add(folder.pk)
        folder = folder.parent
    return True


@require_csrf
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsPlatformAdmin])
def admin_file_action_view(request, file_id):
    """Super Admin-only single-file lifecycle recovery/cleanup.

    Platform Admins keep read-only inventory access. No content is returned.
    Purge reuses the existing storage+quota service and requires typed confirmation.
    """
    if not is_platform_super_admin(request.user):
        return Response({"detail": "Only a Super Admin can modify user files."}, status=403)
    validated = _validate_admin_file_action(request.data)
    if validated is None:
        return Response({"detail": "Provide action and a reason (8–500 characters). Purge also requires confirm_name."}, status=400)
    action, reason, confirm_name = validated

    # A row lock prevents competing admin operations and DB updates during
    # irreversible storage cleanup. This one-file action is deliberately not bulk.
    with transaction.atomic():
        drive_file = File.objects.select_for_update(of=("self",)).select_related(
            "owner", "folder", "tenant", "workspace",
        ).filter(pk=file_id).first()
        if drive_file is None:
            return Response({"detail": "File not found."}, status=404)
        if action == "trash":
            if drive_file.deleted_at is not None:
                return Response({"detail": "File is already in Trash."}, status=409)
            if not _live_parent_chain(drive_file):
                return Response({"detail": "Cannot move a file with a trashed parent folder."}, status=409)
            drive_file.deleted_at = timezone.now()
            drive_file.save(update_fields=["deleted_at", "updated_at"])
            _audit_file_action(request.user, drive_file, PlatformAdminAuditEvent.Action.FILE_TRASH, reason)
            return Response({"id": drive_file.pk, "lifecycle": "trash"})

        if drive_file.deleted_at is None:
            return Response({"detail": "File must be in Trash."}, status=409)
        if action == "restore":
            if not _live_parent_chain(drive_file):
                return Response({"detail": "Restore the parent folder before restoring this file."}, status=409)
            if File.objects.filter(
                workspace_id=drive_file.workspace_id,
                folder_id=drive_file.folder_id,
                file_name__iexact=drive_file.file_name,
                deleted_at__isnull=True,
            ).exclude(pk=drive_file.pk).exists():
                return Response({"detail": "A file with this name already exists in the destination."}, status=409)
            drive_file.deleted_at = None
            drive_file.purge_after = None
            try:
                # The workspace name-uniqueness constraint remains the final
                # safeguard if a concurrent upload/rename wins the same name.
                with transaction.atomic():
                    drive_file.save(update_fields=["deleted_at", "purge_after", "updated_at"])
                    _audit_file_action(request.user, drive_file, PlatformAdminAuditEvent.Action.FILE_RESTORE, reason)
            except IntegrityError:
                return Response({"detail": "A file with this name already exists in the destination."}, status=409)
            return Response({"id": drive_file.pk, "lifecycle": "active"})

        # For permanent deletion the client must explicitly type the exact file
        # name. Neither the API nor the UI supports permanent bulk deletion.
        if confirm_name != drive_file.file_name:
            return Response({"detail": "The confirmation name does not match this file."}, status=400)
        _audit_file_action(
            request.user, drive_file,
            PlatformAdminAuditEvent.Action.FILE_PURGE_REQUESTED, reason,
        )
        try:
            permanently_delete_files([drive_file])
        except Exception:
            # The existing service retains metadata and marks failed storage
            # locations for retry. Never expose object refs or exception text.
            _audit_file_action(
                request.user, drive_file,
                PlatformAdminAuditEvent.Action.FILE_PURGE_FAILED, reason,
            )
            return Response({
                "detail": "Storage cleanup failed or could not be confirmed. File metadata was retained where possible; check storage health before retrying."
            }, status=503)
        _audit_file_action(
            request.user, drive_file,
            PlatformAdminAuditEvent.Action.FILE_PURGE_SUCCEEDED, reason,
        )
        return Response({"id": file_id, "lifecycle": "purged"})
