from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from files.models import File
from folders.models import Folder


DEMO_PREFIX = "__DEMO__"
USER_PREFIX = "demo_user_"
USER_COUNT = 10


class Command(BaseCommand):
    help = "Remove __DEMO__ folders/files created by seed_demo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=None,
            help="Clear only one demo user. Without this option all 10 demo users are cleared.",
        )
        parser.add_argument(
            "--delete-users",
            action="store_true",
            help="Also delete the demo users after clearing their demo data.",
        )

    def handle(self, *args, **options):
        username = options["username"]

        User = get_user_model()

        if username:
            users = User.objects.filter(username=username)
            if not users.exists():
                raise CommandError(f'User "{username}" does not exist.')
        else:
            users = User.objects.filter(
                username__startswith=USER_PREFIX,
            )

        users = list(users)

        if not users:
            self.stdout.write("No demo users found.")
            return

        total_files = 0
        total_folders = 0

        for user in users:
            demo_files = File.objects.filter(
                owner=user,
                file_name__startswith=DEMO_PREFIX,
            )
            file_count = demo_files.count()

            for drive_file in demo_files.iterator():
                try:
                    if drive_file.file_path:
                        drive_file.file_path.delete(save=False)
                except Exception:
                    pass

            demo_files.delete()

            demo_folders = Folder.objects.filter(
                owner=user,
                folder_name__startswith=DEMO_PREFIX,
            )
            folder_count = demo_folders.count()
            demo_folders.delete()

            total_files += file_count
            total_folders += folder_count

            if options["delete_users"]:
                user.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {total_files} demo files and "
                f"{total_folders} demo folders for {len(users)} demo users."
            )
        )
