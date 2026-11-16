"""Gắn Platform vào Connection đã được Runtime Qualification; không tạo kết nối giả."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from infrastructure.connections import activate_binding, ConnectionRejected
from infrastructure.models import PlatformStorageBinding, StorageConnectionRevision


class Command(BaseCommand):
    help = 'Prepare verified Platform storage once. Dry-run unless --apply is supplied.'

    def add_arguments(self, parser):
        parser.add_argument('--operator', required=True)
        parser.add_argument('--profile-id', default='platform-seaweedfs-v1')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        from accounts.platform_admin import is_platform_super_admin
        actor = get_user_model().objects.filter(username=options['operator'], is_active=True).first()
        if actor is None or not is_platform_super_admin(actor):
            raise CommandError('An active Platform Super Admin is required.')
        rows = list(StorageConnectionRevision.objects.select_related('cluster').filter(
            cluster__kind='platform', cluster__tenant__isnull=True,
            profile_id=options['profile_id'], state='ready', last_error_code=''
        ).order_by('-revision')[:2])
        qualified = [row for row in rows if row.cluster.state == 'ready' and
                     row.probes.filter(mode='runtime', state='succeeded').exists()]
        if not qualified:
            raise CommandError('No READY Platform revision with succeeded runtime probe.')
        target = qualified[0]
        previous = PlatformStorageBinding.objects.filter(pk='primary').first()
        self.stdout.write(f'VERIFIED CONNECTION: revision={target.revision}, cluster={target.cluster.slug}')
        self.stdout.write(f'CURRENT BINDING: {previous.connection_id if previous else "none"}')
        if not options['apply']:
            self.stdout.write('DRY RUN: no changes. Use --apply after checking target.')
            return
        try:
            binding, unchanged = activate_binding(
                target, actor, None, previous.generation if previous else 0,
                'Prepare internal Platform SeaweedFS runtime after successful verification',
            )
        except ConnectionRejected as exc:
            raise CommandError(f'Binding rejected: {exc.code}') from None
        self.stdout.write(self.style.SUCCESS(
            f'PLATFORM BINDING READY: revision={target.revision}, generation={binding.generation}, unchanged={unchanged}'
        ))
        self.stdout.write('Routing flag is unchanged; enable it separately after application smoke tests.')
