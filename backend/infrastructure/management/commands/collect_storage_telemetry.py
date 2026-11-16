"""Collector chỉ đọc, không khởi chạy tự động cùng web server."""
import time
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from infrastructure.models import StorageCluster
from infrastructure.prometheus import MonitoringError, profile_for
from infrastructure.telemetry import collect, sweep_stale


class Command(BaseCommand):
    help = 'Collect approved storage monitoring profiles once, or watch with --watch.'

    def add_arguments(self,parser):
        parser.add_argument('--watch',action='store_true')
        parser.add_argument('--interval',type=int,default=30)

    def handle(self,*args,**options):
        if not settings.SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED or not settings.SECUREDRIVE_STORAGE_MONITORING_ENABLED:
            raise CommandError('Storage monitoring is disabled.')
        if not 15 <= options['interval'] <= 60:
            raise CommandError('Interval must be 15–60 seconds.')
        registry = settings.SECUREDRIVE_STORAGE_MONITORING_PROFILES
        if not isinstance(registry,dict) or len(registry) > 100:
            raise CommandError('Monitoring profile registry is invalid.')
        try:
            ids = [uuid.UUID(value['cluster_id']) for value in registry.values()]
        except (KeyError,ValueError,TypeError,AttributeError):
            raise CommandError('Monitoring profile cluster identities are invalid.') from None
        if not ids or len(set(ids)) != len(ids) or StorageCluster.objects.filter(pk__in=ids).count() != len(ids):
            raise CommandError('Provide one approved profile per existing cluster.')
        try:
            while True:
                failures = 0
                for cluster in StorageCluster.objects.select_related('tenant').filter(pk__in=ids):
                    try:
                        plan = profile_for(cluster)
                        success = plan is not None and collect(cluster,plan)
                        if not success: failures += 1
                        self.stdout.write(f'{cluster.pk}: '+('collected' if success else 'unavailable'))
                    except MonitoringError as error:
                        failures += 1
                        self.stderr.write(f'{cluster.pk}: {error.code}')
                sweep_stale()
                if not options['watch']:
                    if failures: raise CommandError('Some monitoring profiles could not be collected.')
                    return
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            return
