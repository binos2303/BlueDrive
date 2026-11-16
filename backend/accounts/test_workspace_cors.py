"""The real browser preflight must permit the SPA's Workspace selector."""
from django.test import SimpleTestCase, override_settings


@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:3000"])
class WorkspaceCorsTests(SimpleTestCase):
    def test_workspace_browsing_quota_and_upload_preflights(self):
        for path, method in [
            ("/drive/api/items/", "GET"),
            ("/accounts/api/me/quota/", "GET"),
            ("/files/api/uploads/", "POST"),
        ]:
            with self.subTest(path=path):
                response = self.client.options(
                    path,
                    HTTP_ORIGIN="http://localhost:3000",
                    HTTP_ACCESS_CONTROL_REQUEST_METHOD=method,
                    HTTP_ACCESS_CONTROL_REQUEST_HEADERS="x-workspace-id,content-type,x-csrftoken,idempotency-key",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:3000")
                self.assertEqual(response["Access-Control-Allow-Credentials"], "true")
                allowed = {header.strip().lower() for header in response["Access-Control-Allow-Headers"].split(",")}
                self.assertTrue({"x-workspace-id", "content-type", "x-csrftoken", "idempotency-key"}.issubset(allowed))

    def test_untrusted_origin_is_not_granted_workspace_api_access(self):
        response = self.client.options(
            "/files/api/uploads/",
            HTTP_ORIGIN="https://untrusted.example.invalid",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="x-workspace-id",
        )
        self.assertNotIn("Access-Control-Allow-Origin", response)
