"""Session-authenticated control plane for browser-to-S3 multipart uploads."""
import hashlib
import io
import json
import re
import logging
logger = logging.getLogger(__name__)
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.access import (
    active_membership, can_access_workspace, get_default_tenant, get_default_workspace,
    resolve_request_workspace,
)
from files.models import File, QuotaReservation, UploadFinalizationJob, UploadSession
from files.quota import QuotaExceeded, QuotaStateError, finalize_upload_quota, reserve_upload_quota
from files.services import unique_upload_name
from files.storage_adapters import get_storage_adapter
from files.storage_adapters.base import StorageError
from folders.models import Folder
from sharing.services import can_edit_folder
from .validators import MAX_UPLOAD_SIZE, validate_filename

PART_SIZE = 8 * 1024 * 1024
PRESIGN_SECONDS = 180
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _owned_session(request, upload_id):
    session = get_object_or_404(
        UploadSession.objects.select_related("tenant", "target_folder", "workspace"),
        pk=upload_id,
        initiated_by=request.user,
        tenant_id__in=[m.tenant_id for m in active_membership_list(request.user)],
    )
    if not can_access_workspace(request.user, session.workspace):
        # Membership may have been revoked after the upload was initialized.
        from django.http import Http404
        raise Http404
    return session


def active_membership_list(user):
    from accounts.access import active_memberships
    return active_memberships(user)


def _initialize_upload_session(session, user, adapter):
    if session.state != UploadSession.State.INITIATED:
        return
    reserve_upload_quota(session.pk, user)
    if session.expected_size_bytes == 0:
        adapter.put_object(session.object_key, io.BytesIO(b""), size_bytes=0, sha256_hex=hashlib.sha256(b"").hexdigest())
    elif not session.provider_upload_id:
        multipart = adapter.initiate_multipart(
            session.object_key, upload_session_id=str(session.pk), content_type="application/octet-stream"
        )
        session.provider_upload_id = multipart.upload_id
    session.state = UploadSession.State.UPLOADING
    session.save(update_fields=["provider_upload_id", "state", "updated_at"])


def _release_reserved_quota_after_setup_failure(upload_session_id, actor):
    """Release quota only when this upload has a complete active reservation.

    Reservation creation is atomic. For example, a quota-exceeded exception
    rolls back reservation writes, so attempting to finalize a nonexistent
    reservation would only create a second, misleading error.
    """
    states = list(
        QuotaReservation.objects.filter(upload_session_id=upload_session_id)
        .order_by("quota_account_id")
        .values_list("state", flat=True)
    )
    if not states:
        logger.debug(
            "No quota reservation to release for upload session_id=%s",
            upload_session_id,
        )
        return False

    if not all(state == QuotaReservation.State.RESERVED for state in states):
        logger.warning(
            "Skipping quota release for upload session_id=%s because reservation states are not all active: %s",
            upload_session_id,
            ",".join(states),
        )
        return False

    finalize_upload_quota(upload_session_id, completed=False, actor=actor)
    return True


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_upload(request):
    """Create or resume a browser-to-S3 multipart upload session."""
    data = request.data

    # Keep the request contract used by the existing frontend:
    # {"name": str, "size_bytes": int, "sha256": hex, "folder_id": optional}
    try:
        name = data.get("name", "")
        if not isinstance(name, str):
            raise ValidationError("Invalid file name.")
        validate_filename(name)

        raw_size = data.get("size_bytes", -1)
        if isinstance(raw_size, bool):
            raise ValidationError("Invalid file size.")
        size = int(raw_size)
        if size < 0 or size > MAX_UPLOAD_SIZE:
            raise ValidationError("File size is outside the supported limit.")

        sha256 = data.get("sha256", "")
        if not isinstance(sha256, str):
            raise ValidationError("Invalid checksum.")
        sha256 = sha256.lower()
        if not _SHA256.fullmatch(sha256):
            raise ValidationError("Checksum must be a SHA-256 hex digest.")
    except (TypeError, ValueError, ValidationError):
        return Response(
            {"detail": "Invalid file name, size, or checksum."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Resolve the tenant and workspace server-side. The explicit workspace
    # selector is independently authorized by membership/role; it may belong
    # to a collaborator's tenant rather than the uploader's personal tenant.
    folder = None
    folder_id = data.get("folder_id")
    if folder_id:
        folder = get_object_or_404(
            Folder.objects.select_related("tenant", "workspace"),
            pk=folder_id,
            deleted_at__isnull=True,
        )
        if not can_edit_folder(folder, request.user):
            return Response(
                {"detail": "Destination is unavailable."},
                status=status.HTTP_404_NOT_FOUND,
            )
        tenant = folder.tenant
        workspace = folder.workspace
    else:
        try:
            tenant = get_default_tenant(request.user)
            workspace = resolve_request_workspace(request, tenant, data)
            if workspace is None:
                return Response(
                    {"detail": "Workspace is unavailable or not accessible."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            tenant = workspace.tenant
        except Exception:
            logger.exception(
                "Unable to resolve default tenant/workspace for user_id=%s",
                request.user.pk,
            )
            return Response(
                {"detail": "No active workspace is available."},
                status=status.HTTP_403_FORBIDDEN,
            )

    if active_membership(request.user, tenant.pk) is None or not can_access_workspace(request.user, workspace):
        return Response(
            {"detail": "Destination is not writable."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # The database column is max_length=128; do not use 255 here.
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()[:128]

    def conflict_for_existing(session, message):
        return Response(
            {
                "detail": message,
                "upload_id": str(session.pk),
                "state": session.state,
                "failure_code": session.failure_code or None,
            },
            status=status.HTTP_409_CONFLICT,
        )

    def response_for_session(session, response_status):
        return Response(
            {
                "upload_id": str(session.pk),
                "state": session.state,
                "part_size": PART_SIZE,
                "expires_at": session.expires_at,
            },
            status=response_status,
        )

    def payload_matches(session):
        return (
            session.expected_size_bytes == size
            and session.client_name == name
            and session.expected_sha256 == sha256
            and session.target_folder_id == getattr(folder, "pk", None)
            and session.workspace_id == workspace.pk
        )

    def existing_session_response(session):
        if not payload_matches(session):
            return conflict_for_existing(
                session,
                "Idempotency key was already used for another upload.",
            )
        if session.state == UploadSession.State.FAILED:
            return conflict_for_existing(
                session,
                "The previous upload failed. Start a new upload with a new Idempotency-Key.",
            )
        if session.state in (
            UploadSession.State.CANCELED,
            UploadSession.State.EXPIRED,
        ) or session.expires_at <= timezone.now():
            return conflict_for_existing(
                session,
                "Upload session is no longer active. Start a new upload with a new Idempotency-Key.",
            )

        try:
            _initialize_upload_session(session, request.user, adapter)
        except QuotaExceeded:
            logger.warning("Upload quota exceeded for session_id=%s", session.pk)
            return Response(
                {"detail": "Available storage quota is insufficient."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        except StorageError:
            logger.exception(
                "Storage error while initializing existing session_id=%s",
                session.pk,
            )
            return Response(
                {"detail": "Upload initialization is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception(
                "Unexpected error while initializing existing session_id=%s",
                session.pk,
            )
            return Response(
                {"detail": "Unable to initialize upload session."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        session.refresh_from_db()
        if session.state == UploadSession.State.FAILED:
            return conflict_for_existing(
                session,
                "The previous upload failed. Start a new upload with a new Idempotency-Key.",
            )
        if session.state == UploadSession.State.INITIATED:
            return Response(
                {"detail": "Upload session is not ready.", "upload_id": str(session.pk)},
                status=status.HTTP_409_CONFLICT,
            )
        return response_for_session(session, status.HTTP_200_OK)

    # Reuse an existing idempotent session when the client supplied a key.
    if idempotency_key:
        existing = UploadSession.objects.filter(
            tenant=tenant,
            initiated_by=request.user,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            try:
                adapter = get_storage_adapter()
            except Exception:
                logger.exception("Storage adapter unavailable for user_id=%s", request.user.pk)
                return Response(
                    {"detail": "Object storage is not available."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return existing_session_response(existing)

    # Create the object key through the configured adapter; do not invent a key format.
    try:
        adapter = get_storage_adapter()
        object_key = adapter.create_object_key("staging")
    except StorageError:
        logger.exception("Object storage unavailable for user_id=%s", request.user.pk)
        return Response(
            {"detail": "Object storage is not available."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception:
        logger.exception("Unable to prepare storage for user_id=%s", request.user.pk)
        return Response(
            {"detail": "Object storage is not available."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        session = UploadSession.objects.create(
            tenant=tenant,
            workspace=workspace,
            initiated_by=request.user,
            target_folder=folder,
            client_name=name,
            expected_size_bytes=size,
            expected_sha256=sha256,
            expires_at=timezone.now() + timedelta(hours=1),
            idempotency_key=idempotency_key,
            object_key=object_key,
        )
    except IntegrityError:
        # A concurrent request may have won the idempotency-key race.
        if not idempotency_key:
            logger.exception("UploadSession insert failed without an idempotency key")
            return Response(
                {"detail": "Unable to create upload session."},
                status=status.HTTP_409_CONFLICT,
            )
        existing = UploadSession.objects.filter(
            tenant=tenant,
            initiated_by=request.user,
            idempotency_key=idempotency_key,
        ).first()
        if existing is None:
            logger.exception(
                "UploadSession uniqueness conflict but no matching row was found; user_id=%s",
                request.user.pk,
            )
            return Response(
                {"detail": "Unable to create upload session."},
                status=status.HTTP_409_CONFLICT,
            )
        return existing_session_response(existing)

    try:
        _initialize_upload_session(session, request.user, adapter)
    except QuotaExceeded:
        logger.warning("Upload quota exceeded for session_id=%s", session.pk)
        session.state = UploadSession.State.FAILED
        session.failure_code = "quota_exceeded"
        session.save(update_fields=["state", "failure_code", "updated_at"])
        # reserve_upload_quota() is atomic and raised before creating a
        # reservation. Do not finalize quota here: there is nothing to release.
        return Response(
            {"detail": "Available storage quota is insufficient.", "failure_code": "quota_exceeded"},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    except Exception:
        logger.exception(
            "Upload initialization failed for session_id=%s, user_id=%s",
            session.pk,
            request.user.pk,
        )
        try:
            if session.provider_upload_id:
                adapter.abort_multipart(session.object_key, session.provider_upload_id)
            adapter.delete_object(session.object_key)
        except Exception:
            logger.exception("Storage cleanup failed for session_id=%s", session.pk)

        try:
            session.refresh_from_db()
            session.state = UploadSession.State.FAILED
            session.failure_code = "storage_setup_failed"
            session.save(update_fields=["state", "failure_code", "updated_at"])
        except Exception:
            logger.exception("Could not mark session failed, session_id=%s", session.pk)

        try:
            _release_reserved_quota_after_setup_failure(session.pk, request.user)
        except Exception:
            logger.exception("Unable to release quota after setup failure, session_id=%s", session.pk)

        return Response(
            {
                "detail": "Upload could not be initialized.",
                "upload_id": str(session.pk),
                "failure_code": "storage_setup_failed",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    session.refresh_from_db()
    if session.state != UploadSession.State.UPLOADING:
        logger.error(
            "Session initialization returned unexpected state: session_id=%s state=%s",
            session.pk,
            session.state,
        )
        return Response(
            {"detail": "Upload session is not ready.", "upload_id": str(session.pk), "state": session.state},
            status=status.HTTP_409_CONFLICT,
        )

    return response_for_session(session, status.HTTP_201_CREATED)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def authorize_part(request, upload_id, part_number):
    session = _owned_session(request, upload_id)
    if session.state != UploadSession.State.UPLOADING or session.expires_at <= timezone.now():
        return Response({"detail": "Upload session is not active."}, status=409)
    part_count = (session.expected_size_bytes + PART_SIZE - 1) // PART_SIZE
    if part_number < 1 or part_number > part_count:
        return Response({"detail": "Part number is outside the session bounds."}, status=400)
    try:
        signed = get_storage_adapter().create_part_upload_url(session.object_key, session.provider_upload_id, part_number, expires_in=PRESIGN_SECONDS)
    except StorageError:
        return Response({"detail": "Could not authorize this upload part."}, status=503)
    # Do not log or persist this response: the URL is a short-lived bearer credential.
    return Response({"url": signed.url, "method": signed.method, "headers": signed.required_headers, "expires_in": PRESIGN_SECONDS})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def authorize_parts(request, upload_id):
    """Issue a batch of short-lived S3 multipart PUT URLs to the session owner."""
    session = _owned_session(request, upload_id)
    if session.state != UploadSession.State.UPLOADING or session.expires_at <= timezone.now():
        return Response({"detail": "Upload session is not active."}, status=409)

    raw_parts = request.data.get("part_numbers")
    # A batch avoids one Django round-trip per chunk. Bound the request even though
    # the current product limit (100 MiB / 8 MiB) needs at most 13 parts.
    if not isinstance(raw_parts, list) or not raw_parts or len(raw_parts) > 1000:
        return Response({"detail": "Provide between 1 and 1000 part numbers."}, status=400)
    if any(type(number) is not int for number in raw_parts):
        return Response({"detail": "Part numbers must be integers."}, status=400)
    if len(set(raw_parts)) != len(raw_parts):
        return Response({"detail": "Part numbers must be unique."}, status=400)

    part_count = (session.expected_size_bytes + PART_SIZE - 1) // PART_SIZE
    if any(number < 1 or number > part_count for number in raw_parts):
        return Response({"detail": "A part number is outside the upload session bounds."}, status=400)

    try:
        adapter = get_storage_adapter()
        signed_parts = []
        for part_number in sorted(raw_parts):
            signed = adapter.create_part_upload_url(
                session.object_key,
                session.provider_upload_id,
                part_number,
                expires_in=PRESIGN_SECONDS,
            )
            signed_parts.append({
                "part_number": part_number,
                "url": signed.url,
                "method": signed.method,
                "headers": signed.required_headers,
                "expires_in": PRESIGN_SECONDS,
            })
    except StorageError:
        return Response({"detail": "Could not authorize upload parts."}, status=503)

    # These URLs are bearer credentials: never persist or log them.
    return Response({"parts": signed_parts, "expires_in": PRESIGN_SECONDS})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def upload_status(request, upload_id):
    session = _owned_session(request, upload_id)
    if session.state in (UploadSession.State.INITIATED, UploadSession.State.UPLOADING) and session.expires_at <= timezone.now():
        session.state = UploadSession.State.EXPIRED
        session.failure_code = "expired"
        session.save(update_fields=["state", "failure_code", "updated_at"])
        try:
            adapter = get_storage_adapter()
            if session.provider_upload_id:
                adapter.abort_multipart(session.object_key, session.provider_upload_id)
            if session.object_key:
                adapter.delete_object(session.object_key)
        except StorageError:
            pass
        try:
            finalize_upload_quota(session.pk, completed=False, actor=request.user)
        except QuotaStateError:
            pass
    return Response({"upload_id": str(session.pk), "state": session.state, "expected_size_bytes": session.expected_size_bytes, "expected_sha256": session.expected_sha256, "actual_size_bytes": session.actual_size_bytes, "failure_code": session.failure_code or None})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def abort_upload(request, upload_id):
    session = _owned_session(request, upload_id)
    with transaction.atomic():
        session = UploadSession.objects.select_for_update().get(pk=session.pk)
        if session.state in (UploadSession.State.COMPLETED, UploadSession.State.AVAILABLE):
            return Response({"detail": "Completed uploads cannot be canceled."}, status=409)
        if session.state in (UploadSession.State.CANCELED, UploadSession.State.FAILED):
            return Response({"state": session.state})
        session.state = UploadSession.State.CANCELED
        session.save(update_fields=["state", "updated_at"])
    cleanup_pending = False
    try:
        storage = get_storage_adapter()
        if session.provider_upload_id:
            storage.abort_multipart(session.object_key, session.provider_upload_id)
        storage.delete_object(session.object_key)
    except StorageError:
        cleanup_pending = True
    finalize_upload_quota(session.pk, completed=False, actor=request.user)
    if cleanup_pending:
        return Response({"state": session.state, "cleanup_pending": True}, status=202)
    return Response({"state": session.state})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def complete_upload(request, upload_id):
    session = _owned_session(request, upload_id)
    if session.state in (UploadSession.State.COMPLETED, UploadSession.State.AVAILABLE):
        return Response({"upload_id": str(session.pk), "state": session.state, "file_id": session.file_id})
    if session.state in (UploadSession.State.VERIFYING, UploadSession.State.SCANNING):
        return Response({"upload_id": str(session.pk), "state": session.state}, status=202)
    if session.state != UploadSession.State.UPLOADING or session.expires_at <= timezone.now():
        return Response({"detail": "Upload session is not completable."}, status=409)
    manifest = request.data.get("parts")
    if not isinstance(manifest, list) or (not manifest and session.expected_size_bytes != 0) or (manifest and session.expected_size_bytes == 0):
        return Response({"detail": "A completed part manifest is required."}, status=400)
    try:
        from .storage_adapters.base import MultipartPart
        parts = [MultipartPart(part_number=int(p["part_number"]), etag=str(p["etag"])) for p in manifest]
        numbers = [part.part_number for part in parts]
        if numbers != sorted(set(numbers)) or any(not part.etag or len(part.etag) > 256 or "\r" in part.etag or "\n" in part.etag for part in parts):
            raise ValueError("Invalid multipart manifest.")
    except (KeyError, TypeError, ValueError):
        return Response({"detail": "Invalid multipart manifest."}, status=400)
    with transaction.atomic():
        locked = UploadSession.objects.select_for_update().get(pk=session.pk)
        if locked.state == UploadSession.State.UPLOADING:
            locked.part_manifest = [{"part_number": part.part_number, "etag": part.etag} for part in parts]
            locked.state = UploadSession.State.VERIFYING
            locked.save(update_fields=["part_manifest", "state", "updated_at"])
            UploadFinalizationJob.objects.get_or_create(upload_session=locked)
    return Response({"upload_id": str(session.pk), "state": UploadSession.State.VERIFYING}, status=202)
