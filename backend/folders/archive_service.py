"""Permission-scoped folder ZIPs for both MinIO versions and legacy local files.

Build the archive before sending any bytes so a failed or quarantined object
cannot produce a misleadingly successful partial download.
"""
from __future__ import annotations

import tempfile
import unicodedata
import zipfile

from cryptography.exceptions import InvalidTag
from django.http import Http404

from files.models import File
from files.views import _decrypt_file, _download_block_reason
from sharing.services import can_view_file, can_view_folder
from .models import Folder


MAX_ARCHIVE_FILES = 500
MAX_ARCHIVE_FOLDERS = 1000
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024
SPOOL_MEMORY_BYTES = 8 * 1024 * 1024


class FolderArchiveError(Exception):
    """A safe HTTP error to return without leaking storage implementation details."""

    def __init__(self, detail: str, *, status: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def _zip_segment(value: str) -> str:
    """Reject unsafe ZIP member names instead of silently rewriting paths."""
    if (
        not value or value in {".", ".."}
        or "/" in value or "\\" in value or ":" in value
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise FolderArchiveError("Folder contains a name that is unsafe for a ZIP archive.", status=422)
    return value


def _visible_tree(root: Folder, actor):
    """Traverse all owners in the workspace, never crossing tenant or workspace."""
    folders = [root]
    paths = {root.pk: _zip_segment(root.folder_name) + "/"}
    visited = {root.pk}
    position = 0
    while position < len(folders):
        current = folders[position]
        position += 1
        children = Folder.objects.filter(
            tenant_id=root.tenant_id,
            workspace_id=root.workspace_id,
            parent_id=current.pk,
            deleted_at__isnull=True,
        ).order_by("folder_name", "pk")
        for child in children:
            if child.pk in visited:
                raise FolderArchiveError("Folder hierarchy is invalid.", status=422)
            visited.add(child.pk)
            if not can_view_folder(child, actor):
                continue
            if len(folders) >= MAX_ARCHIVE_FOLDERS:
                raise FolderArchiveError("This folder contains too many subfolders to download.", status=413)
            folders.append(child)
            paths[child.pk] = paths[current.pk] + _zip_segment(child.folder_name) + "/"
    return folders, paths


def build_folder_archive(root: Folder, actor):
    """Return (ready-to-stream file, included count, plaintext byte count).

    The caller owns the returned temporary file and FileResponse closes it.
    Any error closes it here before a response can be sent.
    """
    if not can_view_folder(root, actor):
        raise Http404

    folders, paths = _visible_tree(root, actor)
    file_rows = File.objects.filter(
        tenant_id=root.tenant_id,
        workspace_id=root.workspace_id,
        folder_id__in=[folder.pk for folder in folders],
        deleted_at__isnull=True,
    ).order_by("folder_id", "file_name", "pk")
    # A folder can be shared while some descendant resources are inaccessible.
    # Include only files the same user is authorized to download individually.
    visible_files = []
    declared_bytes = 0
    for drive_file in file_rows.iterator(chunk_size=100):
        if not can_view_file(drive_file, actor):
            continue
        visible_files.append(drive_file)
        if len(visible_files) > MAX_ARCHIVE_FILES:
            raise FolderArchiveError("This folder contains too many files to download.", status=413)
        declared_bytes += max(0, drive_file.file_size or 0)
        if declared_bytes > MAX_ARCHIVE_BYTES:
            raise FolderArchiveError("This folder is too large to download as one ZIP.", status=413)

    output = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b")
    total_bytes = 0
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for folder in folders:
                archive.writestr(paths[folder.pk], b"")
            for drive_file in visible_files:
                reason = _download_block_reason(drive_file)
                if reason:
                    raise FolderArchiveError("A file in this folder is not ready for download.", status=409)
                try:
                    plaintext = _decrypt_file(drive_file)
                except InvalidTag:
                    raise FolderArchiveError("File integrity verification failed. Folder download was blocked.", status=422) from None
                except Http404:
                    raise FolderArchiveError("A stored file in this folder is unavailable.", status=503) from None
                except Exception:
                    raise FolderArchiveError("Could not read a file in this folder. Retry later.", status=503) from None
                total_bytes += len(plaintext)
                if total_bytes > MAX_ARCHIVE_BYTES:
                    raise FolderArchiveError("This folder is too large to download as one ZIP.", status=413)
                archive.writestr(paths[drive_file.folder_id] + _zip_segment(drive_file.file_name), plaintext)
        output.seek(0)
        return output, len(visible_files), total_bytes
    except Exception:
        output.close()
        raise
