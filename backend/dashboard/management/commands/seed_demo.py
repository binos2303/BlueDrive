from datetime import timedelta
from pathlib import Path
import uuid

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from files.models import File
from folders.models import Folder
from security.aes_service import (
    build_file_aad,
    encrypt_bytes,
    generate_dek,
    get_master_key,
    wrap_dek,
)
from security.hash_service import sha256_hex


DEMO_PREFIX = "__DEMO__"
DEFAULT_PASSWORD = "Demo12345!"
USER_PREFIX = "demo_user_"
USER_COUNT = 10


class Command(BaseCommand):
    help = "Create demo users, folders and encrypted files for UI/performance testing."

    def add_arguments(self, parser):
        size = parser.add_mutually_exclusive_group()
        size.add_argument("--small", action="store_true", help="Create about 30 files per user.")
        size.add_argument("--large", action="store_true", help="Create about 500 files per user.")
        parser.add_argument("--password", default=DEFAULT_PASSWORD)
        parser.add_argument(
            "--clear-first",
            action="store_true",
            help="Remove existing __DEMO__ data for all demo users before seeding.",
        )

    def handle(self, *args, **options):
        file_count = 500 if options["large"] else 30
        password = options["password"]

        User = get_user_model()
        try:
            master_key = get_master_key()
        except Exception as exc:
            raise CommandError(
                "SECUREDRIVE_AES_KEY is not configured. Configure the project key before seeding encrypted demo files."
            ) from exc

        if options["clear_first"]:
            for index in range(1, USER_COUNT + 1):
                username = f"{USER_PREFIX}{index:02d}"
                user = User.objects.filter(username=username).first()
                if user:
                    self._clear_demo(user)

        created_users = []
        for index in range(1, USER_COUNT + 1):
            username = f"{USER_PREFIX}{index:02d}"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@example.local"},
            )
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
            created_users.append((user, created))

        total_files = 0
        total_folders = 0

        for user_index, (user, created) in enumerate(created_users, start=1):
            now = timezone.now()

            with transaction.atomic():
                folder_count = max(6, min(50, file_count // 8))
                roots = []

                for folder_index in range(folder_count):
                    root = Folder.objects.create(
                        owner=user,
                        folder_name=f"{DEMO_PREFIX} User {user_index:02d} Folder {folder_index + 1:02d}",
                        last_accessed_at=now - timedelta(
                            seconds=(user_index * 13) + (folder_index * 17)
                        ),
                    )
                    roots.append(root)

                nested = []
                for folder_index, root in enumerate(
                    roots[: min(10, len(roots))]
                ):
                    nested.append(
                        Folder.objects.create(
                            owner=user,
                            folder_name=f"{DEMO_PREFIX} User {user_index:02d} Subfolder {folder_index + 1:02d}",
                            parent=root,
                            last_accessed_at=now - timedelta(
                                minutes=(user_index * 2) + folder_index + 1
                            ),
                        )
                    )

                destinations = roots + nested

                # Keep 10 files directly in My Drive/root for every demo user.
                # The remaining files are distributed across folders/subfolders.
                root_file_count = min(10, file_count)

                for file_index in range(file_count):
                    if file_index < root_file_count:
                        folder = None
                        folder_label = "My Drive (root)"
                    else:
                        folder = destinations[
                            (file_index - root_file_count) % len(destinations)
                        ]
                        folder_label = folder.folder_name

                    name = (
                        f"{DEMO_PREFIX} User {user_index:02d} "
                        f"Document {file_index + 1:04d}.txt"
                    )
                    plaintext = (
                        f"SecureDrive demo file {file_index + 1}\n"
                        f"Owner: {user.username}\n"
                        f"User index: {user_index}\n"
                        f"Folder: {folder_label}\n"
                    ).encode("utf-8")

                    drive_file = File.objects.create(
                        owner=user,
                        folder=folder,
                        file_name=name,
                        file_size=len(plaintext),
                        mime_type="text/plain",
                        hash_sha256=sha256_hex(plaintext),
                        is_encrypted=True,
                        encryption_version=1,
                        last_accessed_at=now - timedelta(
                            seconds=(user_index * 7) + (file_index * 3)
                        ),
                    )

                    aad = build_file_aad(
                        owner_id=user.id,
                        file_id=drive_file.id,
                        version=drive_file.encryption_version,
                    )
                    dek = generate_dek()
                    ciphertext, nonce = encrypt_bytes(
                        plaintext,
                        dek,
                        aad,
                    )
                    wrapped_dek, dek_nonce = wrap_dek(
                        dek,
                        master_key,
                    )

                    drive_file.file_path.save(
                        f"{uuid.uuid4().hex}.enc",
                        ContentFile(ciphertext),
                        save=False,
                    )
                    drive_file.encryption_nonce = nonce
                    drive_file.wrapped_dek = wrapped_dek
                    drive_file.dek_nonce = dek_nonce
                    drive_file.save(
                        update_fields=[
                            "file_path",
                            "encryption_nonce",
                            "wrapped_dek",
                            "dek_nonce",
                            "updated_at",
                        ]
                    )

                total_folders += len(roots) + len(nested)
                total_files += file_count

        self.stdout.write(self.style.SUCCESS("Demo data created successfully."))
        self.stdout.write(f"Users: {USER_COUNT}")
        self.stdout.write(f"Files: {total_files}")
        self.stdout.write(f"Folders: {total_folders}")
        self.stdout.write(f"Password for all demo users: {password}")
        self.stdout.write(
            f"Usernames: {USER_PREFIX}01 ... {USER_PREFIX}{USER_COUNT:02d}"
        )
        self.stdout.write("Demo records are prefixed with __DEMO__.")

    def _clear_demo(self, user):
        demo_files = File.objects.filter(
            owner=user,
            file_name__startswith=DEMO_PREFIX,
        )

        for drive_file in demo_files.iterator():
            try:
                if drive_file.file_path:
                    drive_file.file_path.delete(save=False)
            except Exception:
                pass

        demo_files.delete()

        Folder.objects.filter(
            owner=user,
            folder_name__startswith=DEMO_PREFIX,
        ).delete()
