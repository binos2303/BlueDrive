"""Session-authenticated control plane for browser-to-S3 multipart uploads."""
import hashlib
import io
import json
import re
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

from accounts.access import active_membership, get_default_tenant
from files.models import File, UploadFinalizationJob, UploadSession
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
    return get_object_or_404(
        UploadSession.objects.select_related("tenant", "target_folder"),
        pk=upload_id,
        initiated_by=request.user,
        tenant_id__in=[m.tenant_id for m in active_membership_list(request.user)],
    )


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


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_upload(request):
    data = request.data
    try:
        name = str(data.get("name", ""))
        validate_filename(name)
        size = int(data.get("size_bytes", -1))
        if size < 0 or size > MAX_UPLOAD_SIZE:
            raise ValidationError("File size is outside the supported limit.")
        sha256 = str(data.get("sha256", "")).lower()
        if not _SHA256.fullmatch(sha256):
            raise ValidationError("Checksum must be a SHA-256 hex digest.")
    except (ValueError, ValidationError):
        return Response({"detail": "Invalid file name, size, or checksum."}, status=400)

    folder = None
    folder_id = data.get("folder_id")
    if folder_id:
        folder = get_object_or_404(Folder, pk=folder_id, deleted_at__isnull=True)
        if not can_edit_folder(folder, request.user):
            return Response({"detail": "Destination is unavailable."}, status=404)
        tenant = folder.tenant
    else:
        try:
            tenant = get_default_tenant(request.user)
        except Exception:
            return Response({"detail": "No active workspace is available."}, status=403)

    if active_membership(request.user, tenant.pk) is None:
        return Response({"detail": "Destination is not writable."}, status=404)

    idem = request.headers.get("Idempotency-Key", "")[:128]
    if idem:
        existing = UploadSession.objects.filter(tenant=tenant, initiated_by=request.user, idempotency_key=idem).first()
        if existing:
            if existing.expected_size_bytes != size or existing.client_name != name or existing.expected_sha256 != sha256 or existing.target_folder_id != getattr(folder, "pk", None):
                return Response({"detail": "Idempotency key was already used for another upload."}, status=409)
            if existing.expires_at <= timezone.now():
                return Response({"detail": "Upload session expired; start a new upload."}, status=409)
            try:
                _initialize_upload_session(existing, request.user, get_storage_adapter())
            except QuotaExceeded:
                return Response({"detail": "Available storage quota is insufficient."}, status=413)
            except StorageError:
                return Response({"detail": "Upload initialization is temporarily unavailable."}, status=503)
            return Response({"upload_id": str(existing.pk), "state": existing.state, "part_size": PART_SIZE, "expires_at": existing.expires_at}, status=200)

    try:
        adapter = get_storage_adapter()
        object_key = adapter.create_object_key("quarantine")
    except StorageError:
        return Response({"detail": "Object storage is not available."}, status=503)
    try:
        session = UploadSession.objects.create(
            tenant=tenant, initiated_by=request.user, target_folder=folder,
            client_name=name, expected_size_bytes=size, expected_sha256=sha256,
            expires_at=timezone.now() + timedelta(hours=1), idempotency_key=idem,
            object_key=object_key,
        )
    except IntegrityError:
        if not idem:
            raise
        existing = get_object_or_404(UploadSession, tenant=tenant, initiated_by=request.user, idempotency_key=idem)
        if existing.expected_size_bytes != size or existing.client_name != name or existing.expected_sha256 != sha256 or existing.target_folder_id != getattr(folder, "pk", None):
            return Response({"detail": "Idempotency key was already used for another upload."}, status=409)
        if existing.expires_at <= timezone.now():
            return Response({"detail": "Upload session expired; start a new upload."}, status=409)
        try:
            _initialize_upload_session(existing, request.user, adapter)
        except QuotaExceeded:
            return Response({"detail": "Available storage quota is insufficient."}, status=413)
        except StorageError:
            return Response({"detail": "Upload initialization is temporarily unavailable."}, status=503)
        return Response({"upload_id": str(existing.pk), "state": existing.state, "part_size": PART_SIZE, "expires_at": existing.expires_at}, status=200)
    try:
        _initialize_upload_session(session, request.user, adapter)
    except QuotaExceeded:
        session.state = UploadSession.State.FAILED
        session.failure_code = "quota_exceeded"
        session.save(update_fields=["state", "failure_code", "updated_at"])
        return Response({"detail": "Available storage quota is insufficient."}, status=413)
    except Exception:
        try:
            if session.provider_upload_id:
                adapter.abort_multipart(session.object_key, session.provider_upload_id)
            adapter.delete_object(session.object_key)
        except Exception:
            pass
        session.state = UploadSession.State.FAILED
        session.failure_code = "storage_setup_failed"
        session.save(update_fields=["state", "failure_code", "updated_at"])
        try:
            finalize_upload_quota(session.pk, completed=False)
        except QuotaStateError:
            pass
        return Response({"detail": "Upload could not be initialized."}, status=503)
    return Response({"upload_id": str(session.pk), "state": session.state, "part_size": PART_SIZE, "expires_at": session.expires_at}, status=201)


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
