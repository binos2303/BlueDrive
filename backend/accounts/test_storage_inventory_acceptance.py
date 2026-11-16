"""Kiểm tra điểm vào S1 trước khi có domain inventory."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


@override_settings(SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED=True)
class StorageInventoryAcceptanceTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username='storage-acceptance-admin', email='storage@example.invalid', password='fixture-password')
        self.client.force_login(self.admin)

    def test_platform_capabilities_are_explicitly_platform_scoped(self):
        response = self.client.get('/accounts/api/admin/storage/capabilities/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['scope'], 'platform')
        self.assertIsNone(response.json()['tenant_id'])
        self.assertTrue(response.json()['permissions']['storage.view'])
        self.assertFalse(response.json()['operations_enabled'])

    def test_platform_inventory_has_no_demo_cluster(self):
        response = self.client.get('/accounts/api/admin/storage/clusters/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [])
        self.assertEqual(response.json()['count'], 0)
