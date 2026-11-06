"""One-time, maintenance-only move of legacy shared workspace charges to dedicated quotas.

DRY RUN by default. Stop upload workers and all writes before --apply.
No file objects or data are deleted. Aborts on active reservations or conflicting counters.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from accounts.models import QuotaAccount, Tenant, Workspace
from files.models import File, QuotaReservation, UploadSession


class Command(BaseCommand):
    help = "Reconcile legacy non-default workspace quota and reservations (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Commit changes after offline maintenance checks.")

    def handle(self, *args, **options):
        workspace_qs = Workspace.objects.filter(is_default=False).order_by("tenant_id", "id")
        missing = workspace_qs.exclude(quota_accounts__scope=QuotaAccount.Scope.WORKSPACE)
        count = missing.count()
        self.stdout.write(f"Legacy workspaces without dedicated accounts: {count}")
        for ws in missing[:20]:
            usage = File.objects.filter(workspace_id=ws.pk).aggregate(size=Sum("file_size"))["size"] or 0
            self.stdout.write(f"  {ws.pk}  {ws.name}  logical_used={usage} bytes")
        if count > 20:
            self.stdout.write(f"  ... and {count - 20} more")
        if not count:
            return
        # Refuse to migrate with any in-flight quota reservations; changing
        # their account while a worker is finalizing would race and double-count.
        pending = QuotaReservation.objects.filter(
            state=QuotaReservation.State.RESERVED,
            upload_session__workspace__in=missing,
        ).count()
        if pending:
            raise CommandError(
                f"Found {pending} active shared workspace quota reservations. "
                "Stop uploads and release/finalize expired sessions before retrying."
            )
        if not options["apply"]:
            self.stdout.write(self.style.WARNING("DRY RUN only. Stop all app/worker writes, back up PostgreSQL, then run --apply."))
            return

        with transaction.atomic():
            # Lock existing quota counters; block concurrent reserve and change.
            locked_accounts = {
                row.pk: row for row in QuotaAccount.objects.select_for_update().order_by("pk")
            }
            if QuotaReservation.objects.filter(
                state=QuotaReservation.State.RESERVED,
                upload_session__workspace__in=missing,
            ).exists():
                raise CommandError("An in-flight reservation appeared during reconciliation.")
            completed = 0
            for ws in missing.select_related("tenant"):
                # The logical usage policy includes Trash; versions are not
                # yet materialized as user-accessible separate quota charges.
                size = File.objects.filter(workspace_id=ws.pk).aggregate(value=Sum("file_size"))["value"] or 0
                if size < 0:
                    raise CommandError(f"Invalid file size for workspace {ws.pk}.")
                workspace_quota = QuotaAccount.objects.create(
                    tenant=ws.tenant, workspace=ws, scope=QuotaAccount.Scope.WORKSPACE,
                    limit_bytes=100 * 1024 * 1024, used_bytes=size,
                )
                files = list(File.objects.filter(workspace_id=ws.pk).values_list("pk", flat=True))
                consumed = list(QuotaReservation.objects.select_for_update().filter(
                    state=QuotaReservation.State.CONSUMED,
                    upload_session__workspace_id=ws.pk,
                    upload_session__file_id__in=files,
                ).select_related("upload_session", "quota_account"))
                moved_amounts = defaultdict(int)
                for reservation in consumed:
                    actual = reservation.upload_session.actual_size_bytes
                    actual = int(actual if actual is not None else reservation.upload_session.file.file_size)
                    if reservation.quota_account.scope in (QuotaAccount.Scope.TENANT, QuotaAccount.Scope.MEMBER):
                        moved_amounts[reservation.quota_account_id] += actual
                        if reservation.quota_account.scope == QuotaAccount.Scope.TENANT:
                            reservation.quota_account = workspace_quota
                            reservation.save(update_fields=["quota_account"])
                        else:
                            # Keep history but do not re-charge the uploader.
                            reservation.state = QuotaReservation.State.RELEASED
                            reservation.save(update_fields=["state"])
                # Historic tenant usage may include legacy files without upload sessions.
                default_tenant = QuotaAccount.objects.filter(
                    tenant=ws.tenant, scope=QuotaAccount.Scope.TENANT,
                ).first()
                if default_tenant and moved_amounts.get(default_tenant.pk, 0) > size:
                    raise CommandError(
                        f"Workspace {ws.pk} has multiple charged file versions; "
                        "manual reconciliation is required before applying quota migration."
                    )
                if default_tenant and size > moved_amounts.get(default_tenant.pk, 0):
                    moved_amounts[default_tenant.pk] += size - moved_amounts[default_tenant.pk]
                for pk, amount in moved_amounts.items():
                    account = locked_accounts.get(pk)
                    if account is None or account.used_bytes < amount:
                        raise CommandError(
                            f"Inconsistent legacy counters for workspace {ws.pk}; "
                            "nothing was committed. Reconcile source metadata first."
                        )
                    account.used_bytes -= amount
                    account.save(update_fields=["used_bytes", "updated_at"])
                completed += 1
            self.stdout.write(self.style.SUCCESS(f"Initialized {completed} workspace quota accounts."))
