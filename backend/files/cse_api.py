"""Chỉ trả ciphertext đã ghim sau xác thực thiết bị."""
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.access import resolve_request_workspace
from logs.models import ActivityLog
from logs.services import log_action
from files import cse
from files.models import File, FileVersion
from files.storage_adapters import get_storage_adapter
from files.storage_routing import adapter_for_location
from files.views import _current_primary_storage_location, _download_block_reason
from files.views import _download_endpoint_is_cookie_isolated, _safe_download_filename

DOWNLOAD_SALT = "bluedrive.cse.fixture.download.v1"


def private_response(payload, status=200):
    return Response(payload, status=status, headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})


def download_challenge(request, drive_file, version):
    return signing.dumps(download_scope(request, drive_file, version), salt=DOWNLOAD_SALT)


def download_scope(request, drive_file, version):
    session_binding = salted_hmac(DOWNLOAD_SALT, request.session.session_key or "").hexdigest()
    return [session_binding, str(request.user.pk), str(drive_file.pk), str(version.pk)]


def verified_location(drive_file, version, state):
    location = _current_primary_storage_location(drive_file, version)
    if (not location or not location.provider_version_id or location.provider_version_id == "null"
            or not location.verified_at or not version.verified_at or location.checksum != version.sha256
            or str(version.crypto_version_id) != version.cse_metadata.get("version")):
        cse.fail()
    cse.fixture_storage(location.storage_connection)
    cse.validate_manifest(version.cse_metadata, state, drive_file.tenant, drive_file.workspace,
                          location.size_bytes, version.sha256, write=False)
    return location


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def trusted_directory(request):
    workspace = resolve_request_workspace(request)
    if workspace is None:
        raise Http404
    if not cse.is_cohort(workspace.tenant, workspace):
        return private_response({"eligible": False})
    try:
        cse.authorize_owner(request.user, workspace.tenant, workspace)
        proof, _ = cse.directory(workspace.tenant, workspace)
    except ValidationError as exc:
        raise Http404 from exc
    return private_response({"eligible": True, "proof": proof, "required": cse.requires_cse(workspace.tenant, workspace)})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def authorize_download(request, file_id):
    drive_file = File.objects.select_related("tenant", "workspace").filter(
        pk=file_id, owner=request.user, deleted_at__isnull=True).first()
    if drive_file is None:
        raise Http404
    version = drive_file.versions.filter(is_current=True).first()
    if (_download_block_reason(drive_file) or not cse.is_cse(version)
            or version.encryption_scheme != cse.SCHEME):
        raise Http404
    if request.headers.get("X-Workspace-ID"):
        selected = resolve_request_workspace(request, drive_file.tenant)
        if selected is None or selected.pk != drive_file.workspace_id:
            raise Http404
    try:
        cse.authorize_owner(request.user, drive_file.tenant, drive_file.workspace, drive_file.folder_id)
        proof, state = cse.directory(drive_file.tenant, drive_file.workspace)
        token = request.data.get("challenge")
        if not isinstance(token, str) or len(token) > 512:
            cse.fail()
        claim = signing.loads(token, salt=DOWNLOAD_SALT, max_age=45)
        if claim != download_scope(request, drive_file, version):
            cse.fail()
        device_id = request.data.get("device")
        cse.uuid_bytes(device_id)
        key = cse.producer(state, device_id)
        cse.verify(key["sign"], request.data.get("signature"), cse.message(
            "BlueDrive/personal-cse/download/v1", token, device_id))
        location = verified_location(drive_file, version, state)
        connection = location.storage_connection
        if not _download_endpoint_is_cookie_isolated(request, connection.public_endpoint_url):
            cse.fail()
    except (signing.BadSignature, ValidationError) as exc:
        raise Http404 from exc

    filename = _safe_download_filename(drive_file.file_name)
    try:
        adapter = adapter_for_location(location, fallback=get_storage_adapter)
        stored = adapter.stat_object(location.object_ref, version_id=location.provider_version_id)
        if stored.version_id != location.provider_version_id or stored.size_bytes != location.size_bytes:
            return private_response({"detail": "The pinned ciphertext does not match its manifest."}, 422)
        signed = adapter.create_download_url(location.object_ref, expires_in=settings.SECUREDRIVE_DOWNLOAD_URL_SECONDS,
                                             download_name=filename, version_id=location.provider_version_id)
    except Exception:
        return private_response({"detail": "Ciphertext download is temporarily unavailable."}, 503)

    File.objects.filter(pk=drive_file.pk).update(last_accessed_at=timezone.now())
    log_action(request.user, ActivityLog.Action.DOWNLOAD, "Authorized ciphertext download", obj=drive_file,
               metadata={"transport": "cse", "version_id": str(version.pk), "event": "authorization_issued"})
    return private_response({"url": signed.url, "filename": filename, "wire_size": location.size_bytes,
                             "digest": version.sha256,
                             "metadata": {key: value for key, value in version.cse_metadata.items() if key != "rewrapped"},
                             "grant": version.cse_metadata.get("rewrapped", {}).get(device_id), "proof": proof,
                             "provider_version_id": location.provider_version_id})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def save_recovery_rewrap(request, file_id):
    with transaction.atomic():
        drive_file = File.objects.select_for_update().filter(
            pk=file_id, owner=request.user, deleted_at__isnull=True).first()
        if drive_file is None or _download_block_reason(drive_file):
            raise Http404
        version = FileVersion.objects.select_for_update().filter(
            file=drive_file, is_current=True, encryption_scheme=cse.SCHEME).first()
        if not version:
            raise Http404
        try:
            cse.authorize_owner(request.user, drive_file.tenant, drive_file.workspace, drive_file.folder_id)
            _, state = cse.directory(drive_file.tenant, drive_file.workspace)
            verified_location(drive_file, version, state)
            key_id = request.data.get("device")
            grant = request.data.get("grant")
            cse.validate_rewrap(grant, state, version, key_id)
            current = version.cse_metadata.get("rewrapped", {})
            if not isinstance(current, dict) or (key_id not in current and len(current) >= 16):
                cse.fail()
        except (ValidationError, KeyError, TypeError) as exc:
            raise Http404 from exc
        if current.get(key_id) != grant:
            version.cse_metadata = {**version.cse_metadata, "rewrapped": {**current, key_id: grant}}
            version.save(update_fields=["cse_metadata"])
    return private_response({"stored": True})
