"""Kiểm chứng tenant boundary, schema và concurrency của inventory S1."""
import threading
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Membership, PlatformAdminIdentity, Tenant, Workspace
from files.models import File, FileVersion, StorageConfig, StorageLocation
from infrastructure.models import (
    ClusterAuditEvent, ClusterOperationJob, NodeDisk, ServerPool,
    StorageAccessGrant, StorageBinding, StorageCluster, StorageNode, TopologyLayout,
)


class InventoryFixture:
    def setUp(self):
        users = get_user_model()
        self.root = users.objects.create_superuser(username='scc-root', email='root@example.invalid', password='fixture-pass')
        self.owner = users.objects.create_user(username='scc-owner-a')
        self.other_owner = users.objects.create_user(username='scc-owner-b')
        self.viewer = users.objects.create_user(username='scc-viewer-a')
        self.tenant = Tenant.objects.create(kind='business', name='Organization A', slug='scc-org-a')
        self.other_tenant = Tenant.objects.create(kind='business', name='Organization B', slug='scc-org-b')
        self.owner_member = Membership.objects.create(tenant=self.tenant, user=self.owner, role='owner')
        self.other_member = Membership.objects.create(tenant=self.other_tenant, user=self.other_owner, role='owner')
        self.viewer_member = Membership.objects.create(tenant=self.tenant, user=self.viewer, role='member')
        StorageAccessGrant.objects.create(membership=self.owner_member, permission='storage.view', granted_by=self.owner, reason='Explicit S1 inventory access')
        StorageAccessGrant.objects.create(membership=self.other_member, permission='storage.view', granted_by=self.other_owner, reason='Explicit S1 inventory access')
        self.platform = StorageCluster.objects.create(kind='platform', slug='platform-main', display_name='Platform infrastructure', created_by=self.root)
        self.cluster = StorageCluster.objects.create(kind='enterprise', tenant=self.tenant, slug='org-main', display_name='Private Organization A', created_by=self.owner)
        self.other = StorageCluster.objects.create(kind='enterprise', tenant=self.other_tenant, slug='org-main', display_name='Private Organization B', created_by=self.other_owner)
        self.pool = ServerPool.objects.create(cluster=self.cluster, name='Pool A')
        self.other_pool = ServerPool.objects.create(cluster=self.other, name='Pool B')
        self.node = StorageNode.objects.create(cluster=self.cluster, pool=self.pool, hostname='host-a', private_ips=['10.10.0.1'])
        self.other_node = StorageNode.objects.create(cluster=self.other, pool=self.other_pool, hostname='host-b')
        self.disk = NodeDisk.objects.create(node=self.node, stable_disk_id='disk-a', mount_path='/mnt/data', capacity_bytes=1024)
        self.config = StorageConfig.objects.create(tenant=self.tenant, provider='s3', endpoint='https://private.example.invalid', credential_ref='secret-store/never-return-this')
        self.other_config = StorageConfig.objects.create(tenant=self.other_tenant, provider='s3')
        self.client.force_login(self.owner)

    def path(self, suffix='', *, cluster=None, tenant=None, platform=False):
        if platform:
            base = '/accounts/api/admin/storage/'
        else:
            base = f'/accounts/api/tenants/{(tenant or self.tenant).pk}/storage/'
        if cluster is None:
            return base + suffix
        return base + f'clusters/{cluster.pk}/' + suffix

    def ready(self, cluster=None):
        cluster = cluster or self.cluster
        StorageCluster.objects.filter(pk=cluster.pk).update(state='ready', verified_at=timezone.now())
        cluster.refresh_from_db()
        return cluster


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True)
class InventoryApiTests(InventoryFixture, TestCase):
    def test_flag_off_hides_inventory_for_both_scopes(self):
        with override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=False):
            self.assertEqual(self.client.get(self.path('clusters/')).status_code, 404)
            self.client.force_login(self.root)
            self.assertEqual(self.client.get(self.path('clusters/', platform=True)).status_code, 404)

    def test_platform_admin_only_sees_platform_clusters(self):
        self.client.force_login(self.root)
        response = self.client.get(self.path('clusters/', platform=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.json()['results']], [str(self.platform.pk)])
        self.assertNotIn('Private Organization', response.content.decode())
        self.assertEqual(self.client.get(self.path(cluster=self.cluster, platform=True)).status_code, 404)

    def test_dedicated_platform_identity_can_view_own_scope_without_personal_tenant(self):
        operator = get_user_model().objects.create_user(username='scc-dedicated', is_staff=True)
        PlatformAdminIdentity.objects.create(user=operator, invited_by=self.root, status='active')
        self.client.force_login(operator)
        self.assertFalse(Tenant.objects.filter(personal_owner=operator).exists())
        self.assertEqual(self.client.get(self.path('clusters/', platform=True)).status_code, 200)
        self.assertEqual(self.client.get(self.path('clusters/')).status_code, 403)

    def test_platform_role_cannot_use_org_grants_to_cross_boundary(self):
        membership = Membership.objects.create(tenant=self.tenant, user=self.root, role='member')
        StorageAccessGrant.objects.create(membership=membership, permission='storage.view', granted_by=self.owner, reason='Boundary regression fixture')
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(self.path('clusters/')).status_code, 403)

    def test_plain_staff_and_ordinary_user_cannot_use_platform_inventory(self):
        staff = get_user_model().objects.create_user(username='scc-plain-staff', is_staff=True)
        for user in (staff, self.viewer):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.path('clusters/', platform=True)).status_code, 404)

    def test_organization_listing_and_query_cannot_change_tenant_scope(self):
        response = self.client.get(self.path('clusters/'), {'tenant_id':str(self.other_tenant.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.json()['results']], [str(self.cluster.pk)])
        self.assertNotIn('never-return-this', response.content.decode())

    def test_all_object_routes_reject_other_organization(self):
        for suffix in ('', 'topology/', 'nodes/', 'disks/', 'events/', 'operations/', f'nodes/{self.other_node.pk}/'):
            with self.subTest(suffix=suffix):
                response = self.client.get(self.path(suffix, cluster=self.other))
                self.assertEqual(response.status_code, 404)
                self.assertNotIn('Private Organization B', response.content.decode())
        self.assertEqual(self.client.get(self.path('clusters/', tenant=self.other_tenant)).status_code, 404)

    def test_child_node_cannot_be_requested_through_another_cluster(self):
        self.assertEqual(self.client.get(self.path(f'nodes/{self.other_node.pk}/', cluster=self.cluster)).status_code, 404)
        self.assertEqual(self.client.get(self.path(f'nodes/{self.node.pk}/', cluster=self.cluster)).json()['disk_count'], 1)

    def test_owner_admin_and_workspace_roles_do_not_implicitly_grant_storage_access(self):
        StorageAccessGrant.objects.filter(membership=self.owner_member).delete()
        self.assertEqual(self.client.get(self.path('clusters/')).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.path('clusters/')).status_code, 404)

    def test_explicit_delegation_does_not_grant_content_or_other_permissions(self):
        StorageAccessGrant.objects.create(membership=self.viewer_member, permission='storage.view', granted_by=self.owner, reason='Read infrastructure only')
        self.client.force_login(self.viewer)
        response = self.client.get(self.path('capabilities/'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['permissions'], {'storage.view':True, 'storage.configure':False, 'storage.operate':False, 'storage.approve':False, 'storage.monitor':False})
        self.assertFalse(response.json()['operations_enabled'])
        self.assertFalse(response.json()['routing_enabled'])
        self.assertFalse(response.json()['runtime_probes_enabled'])
        with override_settings(SECUREDRIVE_STORAGE_RUNTIME_PROBES_ENABLED=True):
            self.assertTrue(self.client.get(self.path('capabilities/')).json()['runtime_probes_enabled'])

    def test_revoked_grant_or_suspended_membership_tenant_user_lose_access(self):
        for model, pk, field, value in (
            (Membership, self.owner_member.pk, 'status', 'suspended'),
            (Tenant, self.tenant.pk, 'status', 'suspended'),
            (get_user_model(), self.owner.pk, 'is_active', False),
        ):
            with self.subTest(model=model.__name__):
                old = model.objects.values_list(field, flat=True).get(pk=pk)
                model.objects.filter(pk=pk).update(**{field:value})
                self.assertIn(self.client.get(self.path('clusters/')).status_code, (403,404))
                model.objects.filter(pk=pk).update(**{field:old})
        StorageAccessGrant.objects.filter(membership=self.owner_member).delete()
        self.assertEqual(self.client.get(self.path('clusters/')).status_code, 404)

    def test_anonymous_access_denied(self):
        self.client.logout()
        self.assertIn(self.client.get(self.path('clusters/')).status_code, (401,403))

    def test_pagination_is_stable_bounded_and_scope_filtered(self):
        for number in range(4):
            StorageCluster.objects.create(kind='enterprise', tenant=self.tenant, slug=f'page-{number}', display_name=f'Page {number}', created_by=self.owner)
        response = self.client.get(self.path('clusters/'), {'page_size':2, 'q':'Page'})
        self.assertEqual(response.json()['count'], 4)
        self.assertTrue(response.json()['has_more'])
        second = self.client.get(self.path('clusters/'), {'page_size':2, 'page':2, 'q':'Page'}).json()
        self.assertFalse(second['has_more'])
        self.assertTrue({row['id'] for row in second['results']}.isdisjoint(row['id'] for row in response.json()['results']))
        for params in ({'page':0}, {'page_size':101}, {'page_size':'bad'}, {'page':100001}):
            self.assertEqual(self.client.get(self.path('clusters/'), params).status_code, 400)

    def test_topology_is_unknown_even_with_registered_nodes_and_verified_connection(self):
        self.ready()
        response = self.client.get(self.path('topology/', cluster=self.cluster))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['health']['status'], 'unknown')
        self.assertIsNone(payload['health']['observed_at'])
        self.assertTrue(payload['health']['stale'])
        self.assertEqual(payload['nodes'][0]['health']['source'], 'not_collected')
        self.assertEqual(payload['disks'][0]['capacity_source'], 'inventory')
        self.assertEqual(payload['pools'][0]['node_ids'], [str(self.node.pk)])

    def test_layout_is_viewer_specific_and_cannot_leak_opaque_json(self):
        TopologyLayout.objects.create(cluster=self.cluster, owner_user=self.other_owner, positions={str(self.node.pk):{'x':99,'y':99}})
        shared = TopologyLayout.objects.create(cluster=self.cluster, revision=5, positions={str(self.node.pk):{'x':12,'y':13}, str(self.other_node.pk):{'x':1,'y':2}, 'secret':'do-not-return'}, viewport={'x':0,'y':0,'zoom':1,'secret':'do-not-return'})
        first = self.client.get(self.path('topology/', cluster=self.cluster)).json()['layout']
        self.assertEqual(first['positions'], {str(self.node.pk):{'x':12,'y':13}})
        self.assertEqual(first['scope'], 'shared')
        TopologyLayout.objects.create(cluster=self.cluster, owner_user=self.owner, revision=2, positions={str(self.node.pk):{'x':1,'y':2}})
        second = self.client.get(self.path('topology/', cluster=self.cluster)).json()['layout']
        self.assertEqual(second['revision'], 2)
        self.assertEqual(second['scope'], 'personal')
        self.cluster.refresh_from_db()
        shared.refresh_from_db()
        self.assertEqual(self.cluster.revision, 0)
        self.assertEqual(shared.revision, 5)

    def test_audit_and_node_json_are_projected_without_secrets(self):
        StorageNode.objects.filter(pk=self.node.pk).update(labels={'zone':'west','credential_ref':'do-not-return'})
        ClusterAuditEvent.objects.create(cluster=self.cluster, actor=self.owner, action='inventory.registered', before={'state':'draft','secret_access_key':'do-not-return'}, after={'revision':1,'credential_ref':'do-not-return'})
        for suffix in ('topology/', 'events/'):
            response = self.client.get(self.path(suffix, cluster=self.cluster))
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('do-not-return', response.content.decode())
            self.assertNotIn('secret-store', response.content.decode())
        event = self.client.get(self.path('events/', cluster=self.cluster)).json()['results'][0]
        self.assertEqual(event['before'], {'state':'draft'})
        self.assertEqual(event['after'], {'revision':1})

    def test_malformed_inventory_json_does_not_leak_or_crash_snapshot(self):
        StorageNode.objects.filter(pk=self.node.pk).update(private_ips={'credential':'do-not-return'}, labels=['do-not-return'])
        TopologyLayout.objects.create(cluster=self.cluster, positions={str(self.node.pk):{'x':10**400,'y':0}}, viewport={'x':0,'y':0,'zoom':'do-not-return'})
        response = self.client.get(self.path('topology/', cluster=self.cluster))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['nodes'][0]['private_ips'], [])
        self.assertEqual(response.json()['layout']['positions'], {})
        self.assertNotIn('do-not-return', response.content.decode())

    def test_operation_lookup_is_scoped_and_does_not_expose_idempotency(self):
        job = ClusterOperationJob.objects.create(cluster=self.other, kind='maintenance', requested_by=self.other_owner, idempotency_key='private-idempotency-value')
        self.assertEqual(self.client.get(self.path(f'operations/{job.pk}/', cluster=self.cluster)).status_code, 404)
        self.client.force_login(self.other_owner)
        response = self.client.get(self.path(f'operations/{job.pk}/', cluster=self.other, tenant=self.other_tenant))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['dry_run'])
        self.assertNotIn('private-idempotency-value', response.content.decode())

    def test_reads_do_not_create_layout_job_or_mutate_inventory(self):
        before = (TopologyLayout.objects.count(), ClusterOperationJob.objects.count(), StorageCluster.objects.get(pk=self.cluster.pk).revision)
        for suffix in ('topology/', 'nodes/', 'disks/', 'events/', 'operations/'):
            self.assertEqual(self.client.get(self.path(suffix, cluster=self.cluster)).status_code, 200)
        after = (TopologyLayout.objects.count(), ClusterOperationJob.objects.count(), StorageCluster.objects.get(pk=self.cluster.pk).revision)
        self.assertEqual(before, after)
        for method in ('post','patch','delete'):
            self.assertEqual(getattr(self.client, method)(self.path(cluster=self.cluster), data={}, content_type='application/json').status_code, 405)

    def test_topology_query_count_does_not_grow_per_node_or_disk(self):
        url = self.path('topology/', cluster=self.cluster)
        self.client.get(url)
        with CaptureQueriesContext(connection) as small:
            self.client.get(url)
        extra = StorageNode.objects.bulk_create([StorageNode(cluster=self.cluster, pool=self.pool, hostname=f'node-{i}') for i in range(40)])
        NodeDisk.objects.bulk_create([NodeDisk(node=node, stable_disk_id='disk', mount_path='/mnt') for node in extra])
        with CaptureQueriesContext(connection) as large:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['nodes']), 41)
        self.assertLessEqual(len(large), len(small) + 1)

    def test_large_snapshot_requires_paginated_lists_instead_of_silent_truncation(self):
        StorageNode.objects.bulk_create([StorageNode(cluster=self.cluster, hostname=f'large-{i}') for i in range(500)])
        response = self.client.get(self.path('topology/', cluster=self.cluster))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['code'], 'topology_snapshot_too_large')
        listing = self.client.get(self.path('nodes/', cluster=self.cluster), {'page_size':100})
        self.assertEqual(listing.json()['count'], 501)
        self.assertEqual(len(listing.json()['results']), 100)


class InventoryConstraintTests(InventoryFixture, TestCase):
    def rejects(self, callback):
        with self.assertRaises(IntegrityError), transaction.atomic():
            callback()

    def test_owner_scope_and_business_tenant_are_database_invariants(self):
        self.rejects(lambda: StorageCluster.objects.create(kind='platform', tenant=self.tenant, slug='bad1', display_name='Bad', created_by=self.root))
        self.rejects(lambda: StorageCluster.objects.create(kind='enterprise', slug='bad2', display_name='Bad', created_by=self.root))
        self.rejects(lambda: StorageCluster.objects.create(kind='enterprise', tenant=self.owner.personal_tenant, slug='bad3', display_name='Bad', created_by=self.owner))
        self.rejects(lambda: StorageCluster.objects.filter(pk=self.cluster.pk).update(tenant=self.other_tenant))

    def test_platform_slug_and_org_slug_uniqueness_use_distinct_owner_namespaces(self):
        self.rejects(lambda: StorageCluster.objects.create(kind='platform', slug=self.platform.slug, display_name='Duplicate', created_by=self.root))
        self.rejects(lambda: StorageCluster.objects.create(kind='enterprise', tenant=self.tenant, slug=self.cluster.slug, display_name='Duplicate', created_by=self.owner))
        self.assertEqual(StorageCluster.objects.filter(slug='org-main').count(), 2)

    def test_node_pool_cannot_cross_cluster_even_without_full_clean(self):
        self.rejects(lambda: StorageNode.objects.create(cluster=self.cluster, pool=self.other_pool, hostname='bad-pool'))

    def test_agent_identity_is_unique_across_clusters(self):
        identity = uuid.uuid4()
        StorageNode.objects.create(cluster=self.cluster, hostname='agent-a', agent_identity=identity)
        self.rejects(lambda: StorageNode.objects.create(cluster=self.other, hostname='agent-b', agent_identity=identity))

    def test_storage_permission_must_be_valid_and_owner_delegated(self):
        self.rejects(lambda: StorageAccessGrant.objects.create(membership=self.viewer_member, permission='storage.root', granted_by=self.owner, reason='Invalid permission'))
        self.rejects(lambda: StorageAccessGrant.objects.create(membership=self.viewer_member, permission='storage.view', granted_by=self.other_owner, reason='Wrong organization owner'))
        self.rejects(lambda: StorageAccessGrant.objects.create(membership=self.owner_member, permission='storage.view', granted_by=self.owner, reason='Duplicate permission'))

    def test_unknown_cluster_cannot_receive_active_binding(self):
        self.rejects(lambda: StorageBinding.objects.create(tenant=self.tenant, scope='tenant', cluster=self.cluster, storage_config=self.config, state='active', active_since=timezone.now()))
        self.rejects(lambda: StorageCluster.objects.filter(pk=self.cluster.pk).update(state='ready'))

    def test_binding_config_and_workspace_must_have_same_tenant(self):
        self.ready()
        with self.assertRaises(ValidationError):
            StorageBinding(cluster=self.cluster, scope='tenant').full_clean()
        other_workspace = self.other_tenant.workspaces.get(is_default=True)
        self.rejects(lambda: StorageBinding.objects.create(tenant=self.tenant, scope='tenant', cluster=self.cluster, storage_config=self.other_config))
        self.rejects(lambda: StorageBinding.objects.create(tenant=self.tenant, scope='workspace', workspace=other_workspace, cluster=self.cluster, storage_config=self.config))
        self.rejects(lambda: StorageBinding.objects.create(tenant=self.tenant, scope='tenant', cluster=self.other, storage_config=self.config))

    def test_one_active_cluster_per_organization_across_workspace_bindings(self):
        self.ready()
        another = StorageCluster.objects.create(kind='enterprise', tenant=self.tenant, slug='another', display_name='Another', created_by=self.owner, state='ready', verified_at=timezone.now())
        first = Workspace.objects.create(tenant=self.tenant, name='First', slug='first')
        second = Workspace.objects.create(tenant=self.tenant, name='Second', slug='second')
        StorageBinding.objects.create(tenant=self.tenant, scope='workspace', workspace=first, cluster=self.cluster, storage_config=self.config, state='active', active_since=timezone.now())
        self.rejects(lambda: StorageBinding.objects.create(tenant=self.tenant, scope='workspace', workspace=second, cluster=another, storage_config=self.config, state='active', active_since=timezone.now()))

    def test_binding_uniqueness_and_legacy_config_protection(self):
        self.ready()
        StorageBinding.objects.create(tenant=self.tenant, scope='tenant', cluster=self.cluster, storage_config=self.config, state='active', active_since=timezone.now())
        self.rejects(lambda: StorageBinding.objects.create(tenant=self.tenant, scope='tenant', cluster=self.cluster, storage_config=self.config, state='active', active_since=timezone.now()))
        with self.assertRaises(ProtectedError):
            self.config.delete()
        self.rejects(lambda: StorageConfig.objects.create(tenant=self.tenant, provider='s3'))

    def test_layouts_are_unique_per_viewer_or_shared_scope(self):
        TopologyLayout.objects.create(cluster=self.cluster)
        self.rejects(lambda: TopologyLayout.objects.create(cluster=self.cluster))
        TopologyLayout.objects.create(cluster=self.cluster, owner_user=self.owner)
        self.rejects(lambda: TopologyLayout.objects.create(cluster=self.cluster, owner_user=self.owner))
        TopologyLayout.objects.create(cluster=self.cluster, owner_user=self.viewer)

    def test_operation_constraints_prevent_real_work_and_conflicting_claims(self):
        self.rejects(lambda: ClusterOperationJob.objects.create(cluster=self.cluster, kind='maintenance', requested_by=self.owner, dry_run=False))
        self.rejects(lambda: ClusterOperationJob.objects.create(cluster=self.cluster, kind='maintenance', requested_by=self.owner, state='running'))
        ClusterOperationJob.objects.create(cluster=self.cluster, kind='maintenance', requested_by=self.owner, state='running', plan_hash='a'*64)
        self.rejects(lambda: ClusterOperationJob.objects.create(cluster=self.cluster, kind='expand_pool', requested_by=self.owner, state='validating', plan_hash='b'*64))
        ClusterOperationJob.objects.filter(cluster=self.cluster).update(state='needs_attention')
        self.rejects(lambda: ClusterOperationJob.objects.create(cluster=self.cluster, kind='expand_pool', requested_by=self.owner, state='validating', plan_hash='b'*64))
        ClusterOperationJob.objects.create(cluster=self.cluster, kind='expand_pool', requested_by=self.owner)

    def test_no_physical_cascade_or_invalid_hardware_metadata(self):
        with self.assertRaises(ProtectedError):
            self.cluster.delete()
        with self.assertRaises(ProtectedError):
            self.tenant.delete()
        self.rejects(lambda: NodeDisk.objects.create(node=self.node, stable_disk_id='negative', mount_path='/mnt/negative', capacity_bytes=-1))
        self.node.private_ips = ['http://169.254.169.254/metadata']
        with self.assertRaises(ValidationError):
            self.node.full_clean()


class InventoryConcurrencyTests(InventoryFixture, TransactionTestCase):
    serialized_rollback = True

    def race(self, callback):
        self.assertEqual(connection.vendor, 'postgresql')
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()
        def worker(number):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    callback(number)
                result = 'created'
            except IntegrityError:
                result = 'conflict'
            except Exception as error:
                result = type(error).__name__
            finally:
                connections.close_all()
            with lock:
                outcomes.append(result)
        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ['created', 'conflict'])

    def test_same_agent_identity_has_one_winner_on_two_connections(self):
        identity = uuid.uuid4()
        self.race(lambda number: StorageNode.objects.create(cluster_id=self.cluster.pk, hostname=f'racing-{number}', agent_identity=identity))
        self.assertEqual(StorageNode.objects.filter(agent_identity=identity).count(), 1)

    def test_only_one_active_operation_is_committed(self):
        self.race(lambda number: ClusterOperationJob.objects.create(cluster_id=self.cluster.pk, requested_by_id=self.owner.pk, kind='maintenance', state='running', plan_hash='a'*64))
        self.assertEqual(ClusterOperationJob.objects.filter(cluster=self.cluster).count(), 1)

    def test_same_idempotency_key_has_one_operation(self):
        self.race(lambda number: ClusterOperationJob.objects.create(cluster_id=self.cluster.pk, requested_by_id=self.owner.pk, kind='maintenance', idempotency_key='same-operation'))
        self.assertEqual(ClusterOperationJob.objects.filter(cluster=self.cluster, idempotency_key='same-operation').count(), 1)

    def test_two_cluster_bindings_cannot_activate_concurrently(self):
        self.ready()
        another = StorageCluster.objects.create(kind='enterprise', tenant=self.tenant, slug='race-cluster', display_name='Other target', created_by=self.owner, state='ready', verified_at=timezone.now())
        workspaces = [Workspace.objects.create(tenant=self.tenant, name=f'Race {i}', slug=f'race-{i}') for i in range(2)]
        targets = [self.cluster, another]
        self.race(lambda number: StorageBinding.objects.create(tenant_id=self.tenant.pk, scope='workspace', workspace_id=workspaces[number].pk, cluster_id=targets[number].pk, storage_config_id=self.config.pk, state='active', active_since=timezone.now()))
        self.assertEqual(StorageBinding.objects.filter(tenant=self.tenant, state='active').count(), 1)

    @override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True)
    def test_two_owner_forms_have_one_effective_update_and_audit(self):
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.owner)
        statuses = []
        def update(number):
            desired = ['storage.view'] if number == 0 else ['storage.view','storage.monitor']
            response = clients[number].patch(self.path(f'access/{self.viewer_member.pk}/'), {'permissions':desired, 'expected_permissions':[], 'reason':'Concurrent owner delegation'}, content_type='application/json')
            statuses.append(response.status_code)
            if response.status_code == 409:
                raise IntegrityError('Optimistic permission conflict')
            self.assertEqual(response.status_code, 200)
        self.race(update)
        self.assertCountEqual(statuses, [200,409])
        self.assertEqual(ClusterAuditEvent.objects.filter(tenant=self.tenant, action='storage.access.changed').count(), 1)


class InventoryMigrationTests(TransactionTestCase):
    serialized_rollback = True

    def test_schema_roundtrip_preserves_legacy_location_and_version_id(self):
        owner = get_user_model().objects.create_user(username='scc-migration-legacy')
        tenant = owner.personal_tenant
        config = StorageConfig.objects.create(tenant=tenant, provider='s3', endpoint='https://legacy.example.invalid', credential_ref='legacy-ref')
        file = File.objects.create(tenant=tenant, owner=owner, file_name='legacy.txt', file_size=3)
        version = FileVersion.objects.create(tenant=tenant, file=file, version_number=1, is_current=True, state='available', size_bytes=3)
        location = StorageLocation.objects.create(tenant=tenant, file_version=version, storage_config=config, object_ref='primary/legacy-sentinel', provider_version_id='legacy-version-sentinel', state='available')
        targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
        try:
            MigrationExecutor(connection).migrate([('infrastructure', None)])
            self.assertTrue(StorageConfig.objects.filter(pk=config.pk, credential_ref='legacy-ref').exists())
            self.assertEqual(StorageLocation.objects.filter(pk=location.pk).values_list('provider_version_id',flat=True).get(), 'legacy-version-sentinel')
        finally:
            MigrationExecutor(connection).migrate(targets)
        location.refresh_from_db()
        self.assertEqual(location.object_ref, 'primary/legacy-sentinel')
        self.assertEqual(location.provider_version_id, 'legacy-version-sentinel')
        self.assertEqual(StorageCluster.objects.count(), 0)


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True)
class InventoryAccessApiTests(InventoryFixture, TestCase):
    def access_path(self, member=None):
        return self.path(f'access/{(member or self.viewer_member).pk}/')

    def change(self, desired, expected, **extra):
        return self.client.patch(self.access_path(), {'permissions':desired, 'expected_permissions':expected, 'reason':'Explicit owner delegation', **extra}, content_type='application/json')

    def test_owner_can_explicitly_bootstrap_own_storage_access(self):
        StorageAccessGrant.objects.filter(membership=self.owner_member).delete()
        self.assertEqual(self.client.get(self.path('clusters/')).status_code, 404)
        response = self.client.get(self.access_path(self.owner_member))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['permissions'], [])
        response = self.client.patch(self.access_path(self.owner_member), {'permissions':['storage.view'], 'expected_permissions':[], 'reason':'Owner enables own inventory access'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(self.path('clusters/')).status_code, 200)

    def test_owner_delegates_audits_and_revokes_without_platform_help(self):
        self.assertEqual(self.change(['storage.view'], []).status_code, 200)
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.get(self.path('clusters/')).status_code, 200)
        history = self.client.get(self.path('access/events/'))
        self.assertEqual(history.status_code, 200)
        event = history.json()['results'][0]
        self.assertEqual(event['before'], {'permissions':[]})
        self.assertEqual(event['after'], {'permissions':['storage.view']})
        self.assertEqual(self.change([], ['storage.view']).status_code, 200)
        self.assertEqual(viewer.get(self.path('clusters/')).status_code, 404)

    def test_idempotent_retry_and_stale_owner_form(self):
        self.assertEqual(self.change(['storage.view'], []).status_code, 200)
        self.assertTrue(self.change(['storage.view'], []).json()['unchanged'])
        response = self.change(['storage.view','storage.monitor'], [])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'storage_access_conflict')
        self.assertEqual(self.client.get(self.path('access/events/')).json()['count'], 1)

    def test_member_admin_and_platform_admin_cannot_delegate(self):
        admin = get_user_model().objects.create_user(username='scc-org-admin')
        member = Membership.objects.create(tenant=self.tenant, user=admin, role='admin')
        StorageAccessGrant.objects.create(membership=member, permission='storage.configure', granted_by=self.owner, reason='Configure does not delegate permissions')
        for actor in (admin, self.viewer, self.root):
            self.client.force_login(actor)
            self.assertIn(self.change(['storage.view'], []).status_code, (403,404))
        self.assertFalse(StorageAccessGrant.objects.filter(membership=self.viewer_member).exists())

    def test_cross_tenant_target_and_payload_cannot_escalate(self):
        response = self.client.patch(self.access_path(self.other_member), {'permissions':['storage.view'],'expected_permissions':[], 'reason':'Try another organization'}, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.change(['storage.view'], [], tenant_id=str(self.other_tenant.pk)).status_code, 400)
        for desired in (['storage.root'], ['storage.view','storage.view'], ['storage.view',True], 'storage.view'):
            self.assertEqual(self.change(desired, []).status_code, 400)
        self.assertFalse(StorageAccessGrant.objects.filter(membership=self.viewer_member).exists())

    def test_access_mutation_requires_session_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        body = {'permissions':['storage.view'],'expected_permissions':[], 'reason':'CSRF verified delegation'}
        self.assertEqual(browser.patch(self.access_path(), body, content_type='application/json').status_code, 403)
        browser.get('/accounts/api/csrf/')
        response = browser.patch(self.access_path(), body, content_type='application/json', HTTP_X_CSRFTOKEN=browser.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)

    def test_grant_cannot_activate_suspended_user_but_revoke_still_works(self):
        self.assertEqual(self.change(['storage.view'], []).status_code, 200)
        Membership.objects.filter(pk=self.viewer_member.pk).update(status='suspended')
        self.assertEqual(self.change(['storage.view','storage.monitor'], ['storage.view']).status_code, 404)
        self.assertEqual(self.change([], ['storage.view']).status_code, 200)
        self.assertFalse(StorageAccessGrant.objects.filter(membership=self.viewer_member).exists())

    def test_disabled_feature_rejects_permission_mutations(self):
        with override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=False):
            self.assertEqual(self.change(['storage.view'], []).status_code, 404)
        self.assertFalse(StorageAccessGrant.objects.filter(membership=self.viewer_member).exists())
