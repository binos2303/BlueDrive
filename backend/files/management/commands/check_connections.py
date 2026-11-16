"""Kiểm tra PostgreSQL và S3 bằng object probe riêng, không chạm dữ liệu người dùng."""
import hashlib
import io
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from files.storage_adapters import get_storage_adapter


class Command(BaseCommand):
    help = "Test the PostgreSQL connection and perform a temporary S3 write/read/delete probe."

    def handle(self, *args, **options):
        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone()[0] != 1:
                    raise RuntimeError("Unexpected SQL probe result")
        except Exception as error:
            raise CommandError(
                f"PostgreSQL connection failed ({type(error).__name__}). "
                "Check DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD and that PostgreSQL is running."
            ) from None
        self.stdout.write(self.style.SUCCESS("PostgreSQL: connected and SELECT 1 succeeded."))

        adapter = None
        object_key = None
        cleanup_failed = False
        probe = f"SecureDrive connectivity probe {uuid.uuid4()}".encode("utf-8")
        digest = hashlib.sha256(probe).hexdigest()
        try:
            adapter = get_storage_adapter()
            object_key = adapter.create_object_key("quarantine")
            stat = adapter.put_object(
                object_key,
                io.BytesIO(probe),
                size_bytes=len(probe),
                sha256_hex=digest,
            )
            if stat.size_bytes != len(probe):
                raise RuntimeError("Stored probe size did not match")
            body = adapter.open_object(object_key)
            try:
                round_trip = body.read(len(probe) + 1)
            finally:
                body.close()
            if round_trip != probe:
                raise RuntimeError("Stored probe bytes did not match")
        except Exception as error:
            if isinstance(error, CommandError):
                raise
            raise CommandError(
                f"S3 API check failed ({type(error).__name__}). "
                "Check SECUREDRIVE_STORAGE_ENDPOINT_URL, bucket, credentials, network access and bucket permissions."
            ) from None
        finally:
            if adapter is not None and object_key is not None:
                try:
                    adapter.delete_object(object_key)
                except Exception:
                    cleanup_failed = True
                    self.stderr.write(self.style.WARNING(
                        "Warning: the temporary S3 probe object could not be deleted. "
                        "Check bucket permissions and remove the probe object if it remains."
                    ))

        if cleanup_failed:
            raise CommandError("S3 probe cleanup failed; connection qualification is incomplete.")
        self.stdout.write(self.style.SUCCESS(
            "S3: connected; temporary object write/read and cleanup verified."
        ))
        self.stdout.write(self.style.SUCCESS("All connection probes passed."))
