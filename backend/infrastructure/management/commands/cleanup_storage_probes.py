from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from infrastructure.connection_probes import cleanup_probe
from infrastructure.connections import ConnectionRejected
from infrastructure.models import StorageConnectionProbe


class Command(BaseCommand):
    help = 'Clean only server-owned expired LAB verification fixtures.'

    def add_arguments(self,parser):
        parser.add_argument('--limit',type=int,default=100)

    def handle(self,*args,**options):
        limit = options['limit']
        if not 1 <= limit <= 1000:
            raise CommandError('limit must be 1–1000')
        query = Q(state='cleanup_pending') | Q(state__in=['creating','awaiting_browser','cleaning'],expires_at__lte=timezone.now())
        cleaned = pending = 0
        for probe in StorageConnectionProbe.objects.filter(query).select_related('connection__cluster').order_by('expires_at')[:limit]:
            try:
                cleanup_probe(probe,recover_expired=True)
                cleaned += 1
            except ConnectionRejected:
                pending += 1
        self.stdout.write(f'Storage fixture cleanup: {cleaned}; pending: {pending}')
