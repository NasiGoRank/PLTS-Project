import os
import unittest
from unittest.mock import patch

from supabase_store import SupabaseStore


class SupabaseStoreEnvironmentTests(unittest.TestCase):
    def test_reads_optional_daily_rollup_table_name(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "sb_secret_server_key",
                "SUPABASE_DAILY_TABLE": "custom_site_daily",
            },
            clear=True,
        ), patch("supabase_store.create_client"):
            store = SupabaseStore.from_env()

        self.assertTrue(store.configured)
        self.assertEqual(store.config.daily_table, "custom_site_daily")

    def test_rejects_publishable_key_used_as_server_secret(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "sb_publishable_browser_key",
            },
            clear=True,
        ):
            store = SupabaseStore.from_env()

        self.assertFalse(store.configured)
        self.assertIn("publishable", store.config_error)
        self.assertIn("server secret", store.config_error)

    def test_rejects_legacy_anon_jwt_used_as_server_secret(self):
        anon_jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJyb2xlIjoiYW5vbiJ9."
            "signature"
        )
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": anon_jwt,
            },
            clear=True,
        ):
            store = SupabaseStore.from_env()

        self.assertFalse(store.configured)
        self.assertIn("anonymous JWT", store.config_error)


if __name__ == "__main__":
    unittest.main()
