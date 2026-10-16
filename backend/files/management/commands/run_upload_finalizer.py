"""Continuously process completed multipart uploads for local development.

Run this in a separate terminal from `python manage.py runserver`:
    python manage.py run_upload_finalizer

Production should run the same worker as a supervised service/container.
"""
import time
from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Continuously run the SecureDrive upload finalization worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=2.0,
            help="Seconds between finalization sweeps (minimum 0.5).",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        if interval < 0.5:
            raise CommandError("--interval must be at least 0.5 seconds.")

        self.stdout.write(self.style.SUCCESS("SecureDrive upload finalizer is running; press Ctrl+C to stop."))
        try:
            while True:
                try:
                    output = StringIO()
                    call_command("finalize_uploads", stdout=output, stderr=self.stderr)
                    result = output.getvalue().strip()
                    if result and "Finalized: 0; retrying: 0; failed: 0" not in result:
                        self.stdout.write(result)
                except KeyboardInterrupt:
                    raise
                except Exception as error:
                    # Keep the supervised local worker alive across transient DB/storage outages.
                    self.stderr.write(
                        self.style.ERROR(
                            f"Upload finalization sweep failed ({type(error).__name__}); retrying."
                        )
                    )
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("SecureDrive upload finalizer stopped.")
