"""Layout là preference; không cho phép PATCH biến thành lệnh hạ tầng."""
import threading
from unittest.mock import patch

from django.db import connections
from django.test import Client, TestCase, TransactionTestCase, override_settings

from infrastructure.models import ClusterAuditEvent, StorageAccessGrant, TopologyLayout
from infrastructure.tests import InventoryFixture


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED=True)
class LayoutApiTests(InventoryFixture,TestCase):
    def payload(self,**values):
        return {'scope':'personal','expected_revision':0,'positions':{str(self.node.pk):{'x':123,'y':85}},'viewport':{'x':1,'y':2,'zoom':.8},**values}

    def save(self,body=None,cluster=None):
        return self.client.patch(self.path('layout/',cluster=cluster or self.cluster),body or self.payload(),content_type='application/json')

    def test_personal_layout_roundtrip_changes_no_inventory_or_storage(self):
        revision = self.cluster.revision
        pool = self.node.pool_id
        with patch('files.storage_adapters.get_storage_adapter',side_effect=AssertionError('Layout must not call storage')):
            response = self.save()
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['layout']['revision'],1)
        result = self.client.get(self.path('topology/',cluster=self.cluster)).json()
        self.assertEqual(result['layout']['positions'],self.payload()['positions'])
        self.assertEqual(result['layout_revisions'],{'personal':1,'shared':0})
        self.node.refresh_from_db(); self.cluster.refresh_from_db()
        self.assertEqual((self.cluster.revision,self.node.pool_id),(revision,pool))

    def test_unchanged_retry_is_idempotent_but_stale_change_conflicts(self):
        self.assertEqual(self.save().status_code,200)
        replay = self.save()
        self.assertEqual(replay.status_code,200)
        self.assertTrue(replay.json()['unchanged'])
        self.assertEqual(self.save(self.payload(viewport={'x':0,'y':0,'zoom':1})).status_code,409)
        self.assertEqual(TopologyLayout.objects.get().revision,1)

    def test_own_layout_does_not_change_shared_or_another_viewer_layout(self):
        shared = TopologyLayout.objects.create(cluster=self.cluster,revision=8,positions={str(self.node.pk):{'x':10,'y':10}})
        self.assertEqual(self.save().status_code,200)
        shared.refresh_from_db(); self.assertEqual(shared.revision,8)
        self.client.force_login(self.other_owner)
        self.assertEqual(self.save().status_code,404)
        self.client.force_login(self.root)
        self.assertIn(self.save().status_code,(403,404))

    def test_viewer_can_save_own_layout_but_cannot_change_shared_layout(self):
        StorageAccessGrant.objects.create(membership=self.viewer_member,permission='storage.view',granted_by=self.owner,reason='Layout view preference test')
        self.client.force_login(self.viewer)
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.save(self.payload(scope='shared')).status_code,403)

    def test_shared_layout_requires_explicit_configure_and_is_audited_once(self):
        self.assertEqual(self.save(self.payload(scope='shared')).status_code,403)
        StorageAccessGrant.objects.create(membership=self.owner_member,permission='storage.configure',granted_by=self.owner,reason='Shared layout permission test')
        self.assertEqual(self.save(self.payload(scope='shared')).status_code,200)
        self.assertEqual(self.save(self.payload(scope='shared')).status_code,200)
        self.assertEqual(ClusterAuditEvent.objects.filter(action='storage.layout.shared_updated').count(),1)

    def test_layout_rejects_unknown_nodes_extra_fields_and_nonfinite_or_boolean_coordinates(self):
        invalid = [self.payload(positions={str(self.other_node.pk):{'x':0,'y':0}}),self.payload(positions={str(self.node.pk):{'x':True,'y':0}}),self.payload(positions={str(self.node.pk):{'x':10**100,'y':0}}),self.payload(viewport={'x':0,'y':0,'zoom':5}),self.payload(expected_revision=True),self.payload(scope='organization'),self.payload(commands=['remove node']),self.payload(positions={str(self.node.pk):{'x':0,'y':0,'pool_id':str(self.other_pool.pk)}})]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.save(body).status_code,400)
        self.assertFalse(TopologyLayout.objects.exists())

    def test_flag_off_and_missing_csrf_cannot_save(self):
        with override_settings(SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED=False):
            self.assertEqual(self.save().status_code,404)
        browser = Client(enforce_csrf_checks=True); browser.force_login(self.owner)
        self.assertEqual(browser.patch(self.path('layout/',cluster=self.cluster),self.payload(),content_type='application/json').status_code,403)

    def test_inspector_filters_remain_inside_the_cluster_and_validate_uuid(self):
        for suffix in ('disks/','events/'):
            path = self.path(suffix,cluster=self.cluster)
            self.assertEqual(self.client.get(path,{'node_id':str(self.other_node.pk)}).status_code,404)
            self.assertEqual(self.client.get(path,{'node_id':'invalid'}).status_code,400)
        result = self.client.get(self.path('disks/',cluster=self.cluster),{'node_id':str(self.node.pk)})
        self.assertEqual([row['id'] for row in result.json()['results']],[str(self.disk.pk)])


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True,SECUREDRIVE_STORAGE_TOPOLOGY_ENABLED=True)
class LayoutConcurrencyTests(InventoryFixture,TransactionTestCase):
    serialized_rollback = True

    def test_two_windows_cannot_overwrite_each_other_from_revision_zero(self):
        barrier = threading.Barrier(2); results = []; errors = []
        def worker(x):
            try:
                connections.close_all()
                browser = Client(); browser.force_login(self.owner)
                barrier.wait(timeout=10)
                response = browser.patch(self.path('layout/',cluster=self.cluster),{'scope':'personal','expected_revision':0,'positions':{str(self.node.pk):{'x':x,'y':0}},'viewport':{'x':0,'y':0,'zoom':1}},content_type='application/json')
                results.append(response.status_code)
            except Exception as error:
                errors.append(type(error).__name__)
            finally:
                connections.close_all()
        threads = [threading.Thread(target=worker,args=(x,),daemon=True) for x in (10,20)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors,[])
        self.assertEqual(sorted(results),[200,409])
        self.assertEqual(TopologyLayout.objects.get().revision,1)
