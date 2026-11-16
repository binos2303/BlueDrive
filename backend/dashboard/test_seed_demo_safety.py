"""Lệnh seed phải dừng sớm khi thiếu mật khẩu và không ghi credential vào output."""
import io
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from dashboard.management.commands import seed_demo


class SeedDemoSafetyTests(SimpleTestCase):
    def test_missing_password_cannot_reach_cleanup_or_database(self):
        command = seed_demo.Command()
        with patch.dict("os.environ", {}, clear=True), \
                patch.object(seed_demo, "get_user_model") as user_model, \
                patch.object(seed_demo, "get_master_key") as master_key, \
                patch.object(command, "_clear_demo") as cleanup:
            with self.assertRaisesMessage(CommandError, "BLUEDRIVE_DEMO_PASSWORD"):
                command.handle(large=False, password=None, clear_first=True)
        user_model.assert_not_called()
        master_key.assert_not_called()
        cleanup.assert_not_called()

    def test_environment_password_is_accepted_without_printing_it(self):
        output = io.StringIO()
        command = seed_demo.Command(stdout=output)
        fake = "fixture-only-password"
        # Không tạo user/file: chỉ chạy đường admission và báo cáo của command.
        with patch.dict("os.environ", {"BLUEDRIVE_DEMO_PASSWORD": fake}, clear=True), \
                patch.object(seed_demo, "USER_COUNT", 0), \
                patch.object(seed_demo, "get_user_model") as user_model, \
                patch.object(seed_demo, "get_master_key", return_value=b"x" * 32):
            command.handle(large=False, password=None, clear_first=False)
        user_model.return_value.objects.get_or_create.assert_not_called()
        self.assertNotIn(fake, output.getvalue())
        self.assertNotIn("Password for", output.getvalue())
        self.assertIn("Demo data created successfully", output.getvalue())
