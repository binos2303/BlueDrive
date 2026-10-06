import uuid

from django.core.files.base import ContentFile

from security.aes_service import (
    build_file_aad,
    decrypt_bytes,
    encrypt_bytes,
    generate_dek,
    get_master_key,
    unwrap_dek,
    wrap_dek,
)

from .models import File


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


def clone_encrypted_file(source_file, *, owner, folder, file_name):
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


def unique_upload_name(model, field_name, original_name, *, folder=None, owner=None):
    """Return a collision-free upload name using (1), (2), ... suffixes."""
    from pathlib import PurePath

    path = PurePath(original_name)
    suffix = ''.join(path.suffixes)
    stem = original_name[:-len(suffix)] if suffix else original_name
    candidate = original_name
    number = 1

    while True:
        filters = {field_name: candidate, "deleted_at__isnull": True}
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
