from __future__ import annotations

import hashlib
import os
import unicodedata
import zipfile
from pathlib import PurePath

from django.core.exceptions import ValidationError


MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_FILENAME_LENGTH = 255
READ_CHUNK_SIZE = 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_UNCOMPRESSED_SIZE = 500 * 1024 * 1024

ALLOWED_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

GENERIC_CLIENT_MIME_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
}

CLIENT_MIME_ALIASES = {
    ".jpg": {"image/jpeg", "image/pjpeg"},
    ".jpeg": {"image/jpeg", "image/pjpeg"},
    ".txt": {"text/plain"},
    ".zip": {
        "application/zip",
        "application/x-zip-compressed",
        "multipart/x-zip",
    },
}

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5",
    "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5",
    "LPT6", "LPT7", "LPT8", "LPT9",
}


def validate_filename(filename: str) -> str:
    if (
        not filename
        or filename != os.path.basename(filename)
        or "/" in filename
        or "\\" in filename
    ):
        raise ValidationError("The filename must not contain a path.")

    if len(filename) > MAX_FILENAME_LENGTH:
        raise ValidationError(
            "The filename must be at most 255 characters long."
        )

    if filename in {".", ".."} or filename.endswith((".", " ")):
        raise ValidationError("The filename has an unsafe ending.")

    if any(
        char in '<>:"/\\|?*'
        or unicodedata.category(char).startswith("C")
        for char in filename
    ):
        raise ValidationError(
            "The filename contains unsupported characters."
        )

    if PurePath(filename).stem.upper() in WINDOWS_RESERVED_NAMES:
        raise ValidationError(
            "The filename is reserved by the operating system."
        )

    extension = PurePath(filename).suffix.lower()

    if extension not in ALLOWED_FILE_TYPES:
        allowed = ", ".join(sorted(ALLOWED_FILE_TYPES))
        raise ValidationError(
            f"Unsupported file type. Allowed types: {allowed}."
        )

    return extension


def _read_prefix(uploaded_file, size=8192) -> bytes:
    uploaded_file.seek(0)
    prefix = uploaded_file.read(size)
    uploaded_file.seek(0)
    return prefix


def _validate_zip_container(
    uploaded_file,
    required_directory: str | None = None,
) -> None:
    uploaded_file.seek(0)

    try:
        with zipfile.ZipFile(uploaded_file) as archive:
            entries = archive.infolist()

            if len(entries) > MAX_ZIP_ENTRIES:
                raise ValidationError(
                    "ZIP archive contains too many entries."
                )

            if (
                sum(entry.file_size for entry in entries)
                > MAX_ZIP_UNCOMPRESSED_SIZE
            ):
                raise ValidationError(
                    "ZIP archive expands beyond the allowed limit."
                )

            names = {entry.filename for entry in entries}

            if required_directory and (
                "[Content_Types].xml" not in names
                or not any(
                    name.startswith(required_directory)
                    for name in names
                )
            ):
                raise ValidationError(
                    "File content does not match its Office document type."
                )

    except zipfile.BadZipFile as exc:
        raise ValidationError(
            "File content is not a valid ZIP container."
        ) from exc

    finally:
        uploaded_file.seek(0)


def detect_mime_type(uploaded_file, extension: str) -> str:
    prefix = _read_prefix(uploaded_file)
    expected_mime = ALLOWED_FILE_TYPES[extension]

    if extension == ".pdf":
        valid = prefix.startswith(b"%PDF-")

    elif extension == ".png":
        valid = prefix.startswith(b"\x89PNG\r\n\x1a\n")

    elif extension in {".jpg", ".jpeg"}:
        valid = prefix.startswith(b"\xff\xd8\xff")

    elif extension in {".zip", ".docx", ".xlsx", ".pptx"}:
        valid = prefix.startswith(
            (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
        )

        if valid:
            office_directories = {
                ".docx": "word/",
                ".xlsx": "xl/",
                ".pptx": "ppt/",
            }

            _validate_zip_container(
                uploaded_file,
                office_directories.get(extension),
            )

    else:  # .txt
        try:
            valid = (
                b"\x00" not in prefix
                and bool(prefix.decode("utf-8"))
            ) or uploaded_file.size == 0
        except UnicodeDecodeError:
            valid = False

    if not valid:
        raise ValidationError(
            "File content does not match its extension."
        )

    return expected_mime


def validate_client_mime_type(
    client_mime_type: str,
    extension: str,
    detected_mime_type: str,
) -> None:
    declared = (
        (client_mime_type or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    if declared in GENERIC_CLIENT_MIME_TYPES:
        return

    allowed = CLIENT_MIME_ALIASES.get(
        extension,
        {detected_mime_type},
    )

    if declared not in allowed:
        raise ValidationError(
            "The declared MIME type does not match the file content."
        )


def calculate_sha256(uploaded_file) -> str:
    digest = hashlib.sha256()

    uploaded_file.seek(0)

    try:
        for chunk in iter(
            lambda: uploaded_file.read(READ_CHUNK_SIZE),
            b"",
        ):
            digest.update(chunk)
    finally:
        uploaded_file.seek(0)

    return digest.hexdigest()