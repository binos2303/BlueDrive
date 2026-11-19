"""Hợp đồng CSE v1 của fixture Personal, xác minh dữ liệu công khai trước khi cấp quyền."""
import json
import re
import struct
import time
from pathlib import Path
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q

from accounts.access import active_membership, get_organization_identity
from files.validators import MAX_UPLOAD_SIZE

SCHEME = "cse_v1"
LEGACY_SCHEMES = {"", "aes-gcm", "aes-256-gcm"}
CHUNK = 1024 * 1024
PREFIX = 152
MAX_WIRE = PREFIX + MAX_UPLOAD_SIZE + 16 * (MAX_UPLOAD_SIZE // CHUNK)


def fail():
    raise ValidationError("CSE authorization or metadata is invalid.")


def hex_bytes(value, size):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % (size * 2), value):
        fail()
    return bytes.fromhex(value)


def uuid_bytes(value):
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        fail()
    if str(parsed) != value:
        fail()
    return parsed.bytes


def verify(public, signature, message):
    raw = hex_bytes(signature, 64)
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), hex_bytes(public, 65))
        key.verify(utils.encode_dss_signature(int.from_bytes(raw[:32]), int.from_bytes(raw[32:])),
                   message, ec.ECDSA(hashes.SHA256()))
    except (ValueError, InvalidSignature):
        fail()


def message(domain, *values):
    return json.dumps([domain, *values], separators=(",", ":"), ensure_ascii=True).encode("ascii")


def enabled():
    # Module phục vụ không có quyền cấp capability fixture, kể cả khi process kế thừa biến môi trường.
    config = getattr(settings, "CSE_FIXTURE", None)
    database = settings.DATABASES["default"]
    return bool(config and settings.SETTINGS_MODULE == "securedrive.cse_fixture_settings"
                and database["HOST"] == "127.0.0.1" and database["NAME"].startswith("bluedrive_p6_fixture_"))


def is_cohort(tenant, workspace):
    if tenant is None or workspace is None or not enabled():
        return False
    config = settings.CSE_FIXTURE
    return str(tenant.pk) == config["tenant"] and str(workspace.pk) == config["workspace"]


def requires_cse(tenant, workspace):
    return is_cohort(tenant, workspace) and settings.CSE_FIXTURE.get("required") is True


def directory(tenant, workspace):
    if not enabled():
        fail()
    config = settings.CSE_FIXTURE
    try:
        with Path(config["directory"]).open("rb") as stream:
            raw = stream.read(32_769)
        if len(raw) > 32_768:
            fail()
        proof = json.loads(raw)
        payload = hex_bytes(proof["payload"], len(proof["payload"]) // 2)
        verify(config["pin"], proof["signature"], payload)
        domain, state = json.loads(payload)
        issued = state["issued"]
        expires = state["expires"]
        now = int(time.time())
        if (domain != "BlueDrive/development/directory/v1" or state["tenant"] != str(tenant.pk)
                or state["workspace"] != str(workspace.pk) or type(issued) is not int
                or type(expires) is not int or not issued <= now < expires <= issued + 4 * 3600):
            fail()
    except (OSError, UnicodeError, KeyError, TypeError, ValueError):
        fail()
    return proof, state


def authorize_owner(user, tenant, workspace, folder=None):
    if (not is_cohort(tenant, workspace) or not user.is_active or user.is_staff or user.is_superuser
            or tenant.kind != "personal" or tenant.personal_owner_id != user.pk
            or tenant.status != "active" or workspace.tenant_id != tenant.pk or not workspace.is_default
            or workspace.owned_identity_id is not None or workspace.status != "active"
            or folder is not None or get_organization_identity(user) is not None
            or active_membership(user, tenant.pk) is None):
        fail()


def fixture_storage(connection):
    config = settings.CSE_FIXTURE
    if (connection is None or connection.cluster.kind != "platform"
            or connection.endpoint_url != config["endpoint"]
            or connection.public_endpoint_url != config["public_endpoint"]
            or connection.bucket != config["bucket"]):
        fail()


def producer(state, key_id, *, active=True):
    try:
        key = state["devices"][key_id]
        if active and key["status"] != "active":
            fail()
        return key
    except (KeyError, TypeError):
        fail()


def validate_envelope(envelope, kind, key_id, epoch):
    if (not isinstance(envelope, dict) or set(envelope) != {"kind", "key_id", "epoch", "suite", "enc", "ct"}
            or envelope["kind"] != kind or envelope["key_id"] != key_id
            or type(envelope["epoch"]) is not int or envelope["epoch"] != epoch
            or envelope["suite"] != "0010:0001:0002"):
        fail()
    hex_bytes(envelope["enc"], 65)
    hex_bytes(envelope["ct"], 48)
    return [kind, key_id, epoch, envelope["suite"], envelope["enc"], envelope["ct"]]


def validate_manifest(meta, state, tenant, workspace, wire_size, digest, *, write):
    expected = {"format", "file", "version", "logical_size", "prefix", "producer", "epoch",
                "signature", "manifest_signature", "device", "recovery", "recovery_proof"}
    if not write and isinstance(meta, dict) and "rewrapped" in meta:
        expected.add("rewrapped")
    if (not isinstance(meta, dict) or set(meta) != expected
            or meta["format"] != SCHEME):
        fail()
    logical = meta["logical_size"]
    if type(logical) is not int or not 0 <= logical <= MAX_UPLOAD_SIZE:
        fail()
    count = (logical + CHUNK - 1) // CHUNK
    prefix = hex_bytes(meta["prefix"], PREFIX)
    ids = tenant.pk.bytes + workspace.pk.bytes + uuid_bytes(meta["file"]) + uuid_bytes(meta["version"])
    if (prefix[:16] != b"BLUDCSE1" + struct.pack(">HHI", 1, 104, 0)
            or prefix[16:80] != ids or prefix[80:96] != struct.pack(">QII", logical, CHUNK, count)
            or wire_size != PREFIX + logical + 16 * count):
        fail()
    key_id = meta["producer"]
    key_bytes = uuid_bytes(key_id)
    key = producer(state, key_id, active=write)
    epoch = key["epoch"]
    if type(meta["epoch"]) is not int or meta["epoch"] != epoch:
        fail()
    verify(key["sign"], meta["signature"], b"BlueDrive/CSE/sign/v1\0" + key_bytes + prefix + hex_bytes(digest, 32))
    recovery = state["recovery"]
    verify(recovery["sign"], meta["recovery_proof"], message(
        "BlueDrive/personal-cse/recovery-check/v1", str(tenant.pk), str(workspace.pk),
        recovery["key_id"], recovery["generation"]))
    recipient = validate_envelope(meta["device"], "device", key_id, epoch)
    recovery_envelope = validate_envelope(meta["recovery"], "personal", recovery["key_id"], recovery["generation"])
    verify(key["sign"], meta["manifest_signature"], message(
        "BlueDrive/personal-cse/manifest/v1", str(tenant.pk), str(workspace.pk), meta["file"], meta["version"],
        logical, wire_size, digest, key_id, epoch, recipient, recovery_envelope))
    return prefix


def validate_rewrap(grant, state, version, device_id):
    if not isinstance(grant, dict) or set(grant) != {"envelope", "signature"}:
        fail()
    uuid_bytes(device_id)
    entry = producer(state, device_id)
    tenant, workspace = state["tenant"], state["workspace"]
    recovery = state["recovery"]
    meta = version.cse_metadata
    envelope = validate_envelope(grant["envelope"], "device", device_id, entry["epoch"])
    verify(recovery["sign"], grant["signature"], message(
        "BlueDrive/personal-cse/rewrap/v1", tenant, workspace, meta["file"], meta["version"],
        version.sha256, recovery["key_id"], recovery["generation"], envelope))


def authorize_write(user, tenant, workspace, folder, meta, size, digest, connection=None, *, pinned=False):
    authorize_owner(user, tenant, workspace, folder)
    if (not settings.CSE_FIXTURE.get("writer") or getattr(settings, "SECUREDRIVE_UPLOAD_SCANNER", "")
            or not settings.CSE_FIXTURE.get("allow_unscanned")):
        fail()
    if pinned:
        fixture_storage(connection)
    _, state = directory(tenant, workspace)
    return validate_manifest(meta, state, tenant, workspace, size, digest, write=True)


def is_cse(version):
    return bool(version and (version.encryption_scheme == SCHEME or getattr(version, "cse_metadata", None)))


def is_cse_file(file):
    return file.versions.filter(
        Q(encryption_scheme=SCHEME) | ~Q(cse_metadata={}), is_current=True
    ).exists()
