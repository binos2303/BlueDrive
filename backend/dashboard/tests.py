from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

@override_settings(NEXTJS_FRONTEND_URL="http://127.0.0.1:3000")
class FrontendRedirectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="sort_user",
            password="TestPass123!",
        )
        self.client.force_login(self.user)

    def test_dashboard_redirects_to_nextjs_drive(self):
        response = self.client.get(reverse("dashboard"), {"sort": "name", "direction": "asc"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://127.0.0.1:3000/drive")

    def test_recent_redirects_to_nextjs_recent_page(self):
        response = self.client.get(reverse("recent"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://127.0.0.1:3000/drive/recent")

    def test_search_redirect_preserves_query_for_nextjs(self):
        response = self.client.get(reverse("search"), {"q": "folder name"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "http://127.0.0.1:3000/drive?q=folder+name",
        )
