"""Read-only diagnostics for private search and transfer histories."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from files.models import UploadFinalizationJob, UploadSession
from logs.models import ActivityLog, SearchHistory


class Command(BaseCommand):
    help = "Show per-user history and upload pipeline counts (does not change data)."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Exact username to inspect")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError("No such account.")
        events = ActivityLog.objects.filter(user=user)
        history = SearchHistory.objects.filter(user=user)
        uploads = UploadSession.objects.filter(initiated_by=user)
        self.stdout.write(f"User ID: {user.pk}")
        self.stdout.write(f"SearchHistory records: {history.count()}")
        self.stdout.write(f"Legacy SEARCH activity records: {events.filter(action=ActivityLog.Action.SEARCH).count()}")
        self.stdout.write(f"UPLOAD events: {events.filter(action=ActivityLog.Action.UPLOAD).count()}")
        self.stdout.write(f"DOWNLOAD events: {events.filter(action=ActivityLog.Action.DOWNLOAD).count()}")
        self.stdout.write(f"Other activity events: {events.exclude(action__in=[ActivityLog.Action.SEARCH, ActivityLog.Action.UPLOAD, ActivityLog.Action.DOWNLOAD]).count()}")
        self.stdout.write(f"Upload sessions: {uploads.count()}")
        for state, count in sorted({
            state: uploads.filter(state=state).count()
            for state in UploadSession.State.values
        }.items()):
            if count:
                self.stdout.write(f"  Upload state {state}: {count}")
        jobs = UploadFinalizationJob.objects.filter(upload_session__initiated_by=user)
        for state in UploadFinalizationJob.State.values:
            count = jobs.filter(state=state).count()
            if count:
                self.stdout.write(f"  Finalization job {state}: {count}")
        self.stdout.write("This command does not backfill historical audit events or show private search terms.")
