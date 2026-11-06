"""Safely keep Free and Workspace Starter as the only active quota presets.

Dry-run by default. Assigned legacy plans are archived (disabled) and retained;
unassigned plans are deleted. Never alters allocated quota sizes.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import QuotaAccount, StoragePlan, StoragePlanAuditEvent
from accounts.platform_admin import is_platform_super_admin

KEEP = frozenset({"free", "workspace-starter"})


class Command(BaseCommand):
    help = "Preview or clean obsolete quota plans without changing any existing user or workspace quota."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Perform the cleanup (default is preview only).")
        parser.add_argument("--actor", type=str, help="Super Admin username for required audit records during --apply.")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        actor = None
        if apply:
            if not opts.get("actor"):
                raise CommandError("--apply requires --actor SUPER_ADMIN_USERNAME for audit history.")
            actor = get_user_model().objects.filter(username=opts["actor"]).first()
            if actor is None or not is_platform_super_admin(actor):
                raise CommandError("--actor must refer to a currently authorized Super Admin.")

        with transaction.atomic():
            plans = list(StoragePlan.objects.select_for_update().order_by("code"))
            present = {plan.code for plan in plans}
            missing = KEEP - present
            if missing:
                raise CommandError("Missing required baseline presets: " + ", ".join(sorted(missing)))
            deleted = 0
            archived = 0
            for plan in plans:
                if plan.code in KEEP:
                    if apply and not plan.is_active:
                        before = self._snapshot(plan)
                        plan.is_active = True
                        plan.save(update_fields=["is_active", "updated_at"])
                        StoragePlanAuditEvent.objects.create(actor=actor, plan_code=plan.code,
                            action="updated", before=before, after=self._snapshot(plan),
                            reason="Restore required baseline quota preset")
                    continue
                count = QuotaAccount.objects.filter(plan=plan).count()
                if count:
                    if plan.is_active:
                        archived += 1
                    self.stdout.write(f"{plan.code}: {count} assigned quota(s) -> {'archive' if plan.is_active else 'already archived'}")
                    if apply and plan.is_active:
                        before = self._snapshot(plan)
                        plan.is_active = False
                        plan.save(update_fields=["is_active", "updated_at"])
                        StoragePlanAuditEvent.objects.create(actor=actor, plan_code=plan.code,
                            action="updated", before=before, after=self._snapshot(plan),
                            reason="Retire obsolete plan; preserve assigned quotas")
                else:
                    self.stdout.write(f"{plan.code}: unassigned -> delete")
                    if apply:
                        before = self._snapshot(plan)
                        code = plan.code
                        plan.delete()
                        StoragePlanAuditEvent.objects.create(actor=actor, plan_code=code,
                            action="deleted", before=before, after={},
                            reason="Remove obsolete unassigned preset")
                    deleted += 1
            self.stdout.write(f"{'APPLIED' if apply else 'DRY RUN'}: {deleted} removable, {archived} active assigned plan(s) to archive. Quota allocations unchanged.")

    @staticmethod
    def _snapshot(plan):
        return {"code": plan.code, "name": plan.name, "scope": plan.scope,
                "limit_bytes": plan.limit_bytes, "is_active": plan.is_active}
