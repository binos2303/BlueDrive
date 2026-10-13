import uuid
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from accounts.services import get_personal_tenant
from .models import File, UploadSession
from .quota import (
    finalize_upload_quota,
    reserve_upload_quota,
)
from security.aes_service import (
    build_file_aad,
    decrypt_bytes,
    encrypt_bytes,
    generate_dek,
    get_master_key,
    unwrap_dek,
    wrap_dek,
)



def unique_copy_name(model, field_name, original_name, *, folder=None, owner=None, exclude_id=None):
    """Return a collision-free copy name in the target folder."""
    if "." in original_name:
        stem, extension = original_name.rsplit(".", 1)
        suffix = f".{extension}"
    else:
        stem, suffix = original_name, ""

    candidate = f"{stem} (copy){suffix}"
    number = 2

    filters = {field_name: candidate}
    if owner is not None:
        filters["owner"] = owner
    if folder is not None:
        filters["folder"] = folder
    else:
        filters["folder__isnull"] = True

    if exclude_id is not None:
        queryset = model.objects.filter(**filters).exclude(id=exclude_id)
    else:
        queryset = model.objects.filter(**filters)

    while queryset.exists():
        candidate = f"{stem} (copy {number}){suffix}"
        filters[field_name] = candidate
        if exclude_id is not None:
            queryset = model.objects.filter(**filters).exclude(id=exclude_id)
        else:
            queryset = model.objects.filter(**filters)
        number += 1

    return candidate


def _clone_encrypted_file(source_file, *, owner, folder, file_name, tenant=None):
    """Clone a SecureDrive file with a fresh file ID, DEK and nonce."""
    if (
        not source_file.is_encrypted
        or not source_file.encryption_nonce
        or not source_file.wrapped_dek
        or not source_file.dek_nonce
        or not source_file.file_path
    ):
        raise ValueError("Source file encryption metadata is incomplete.")

    master_key = get_master_key()
    source_dek = unwrap_dek(
        bytes(source_file.wrapped_dek),
        bytes(source_file.dek_nonce),
        master_key,
    )
    source_aad = build_file_aad(
        owner_id=source_file.owner_id,
        file_id=source_file.id,
        version=source_file.encryption_version,
    )

    with source_file.file_path.open("rb") as stored_file:
        ciphertext = stored_file.read()

    plaintext = decrypt_bytes(
        ciphertext,
        bytes(source_file.encryption_nonce),
        source_dek,
        source_aad,
    )

    cloned = File(
        tenant=(
            folder.tenant
            if folder is not None
            else tenant or get_personal_tenant(owner)
        ),
        owner=owner,
        folder=folder,
        file_name=file_name,
        file_size=source_file.file_size,
        mime_type=source_file.mime_type,
        hash_sha256=source_file.hash_sha256,
        is_encrypted=True,
        encryption_version=source_file.encryption_version,
    )
    cloned.save()

    stored_name = None
    try:
        new_dek = generate_dek()
        new_aad = build_file_aad(
            owner_id=cloned.owner_id,
            file_id=cloned.id,
            version=cloned.encryption_version,
        )
        new_ciphertext, new_nonce = encrypt_bytes(
            plaintext,
            new_dek,
            new_aad,
        )
        wrapped_dek, dek_nonce = wrap_dek(new_dek, master_key)

        encrypted_name = f"{uuid.uuid4().hex}.enc"
        cloned.file_path.save(
            encrypted_name,
            ContentFile(new_ciphertext),
            save=False,
        )
        stored_name = cloned.file_path.name
        cloned.encryption_nonce = new_nonce
        cloned.wrapped_dek = wrapped_dek
        cloned.dek_nonce = dek_nonce
        cloned.save(update_fields=[
            "file_path",
            "encryption_nonce",
            "wrapped_dek",
            "dek_nonce",
            "updated_at",
        ])
        return cloned
    except Exception:
        if stored_name:
            try:
                cloned.file_path.storage.delete(stored_name)
            except Exception:
                pass
        cloned.delete()
        raise


def clone_encrypted_file_with_quota(
    source_file,
    *,
    owner,
    folder,
    file_name,
    tenant,
):
    """Copy a file while reserving and consuming the target tenant quota."""
    if owner.pk != source_file.owner_id:
        raise ValueError("A file copy must retain its current owner.")
    if tenant.pk != source_file.tenant_id:
        raise ValueError("A file copy cannot cross tenant boundaries.")
    if folder is not None and folder.tenant_id != tenant.pk:
        raise ValueError("The destination folder belongs to another tenant.")

    upload = UploadSession.objects.create(
        tenant=tenant,
        initiated_by=owner,
        target_folder=folder,
        client_name=file_name[:255],
        expected_size_bytes=source_file.file_size,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    reserved = False
    cloned = None
    try:
        reserve_upload_quota(upload.pk, owner)
        reserved = True
        upload.state = UploadSession.State.UPLOADING
        upload.save(update_fields=["state", "updated_at"])
        cloned = _clone_encrypted_file(
            source_file,
            owner=owner,
            folder=folder,
            file_name=file_name,
            tenant=tenant,
        )
        with transaction.atomic():
            finalize_upload_quota(
                upload.pk,
                completed=True,
                actual_size_bytes=cloned.file_size,
                actor=owner,
            )
            upload.file = cloned
            upload.state = UploadSession.State.COMPLETED
            upload.completed_at = timezone.now()
            upload.save(
                update_fields=["file", "state", "completed_at", "updated_at"]
            )
        return cloned
    except Exception:
        if cloned is not None:
            if cloned.file_path:
                cloned.file_path.delete(save=False)
            cloned.delete()
        if reserved:
            finalize_upload_quota(upload.pk, completed=False)
        upload.state = UploadSession.State.FAILED
        upload.failure_code = "copy_failed"
        upload.save(update_fields=["state", "failure_code", "updated_at"])
        raise


def unique_upload_name(model, field_name, original_name, *, folder=None, owner=None):
    """Return a collision-free upload name using (1), (2), ... suffixes."""
    from pathlib import PurePath

    path = PurePath(original_name)
    suffix = ''.join(path.suffixes)
    stem = original_name[:-len(suffix)] if suffix else original_name
    candidate = original_name
    number = 1

    while True:
        # Match File's case-insensitive live sibling-name constraint.
        filters = {f"{field_name}__iexact": candidate, "deleted_at__isnull": True}
        if owner is not None:
            filters["owner"] = owner
        if folder is not None:
            filters["folder"] = folder
        else:
            filters["folder__isnull"] = True
        if not model.objects.filter(**filters).exists():
            return candidate
        number += 1
        candidate = f"{stem} ({number}){suffix}"
