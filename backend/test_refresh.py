import unittest

from api import refresh_authorized, refresh_payload


class RefreshAuthorizationTests(unittest.TestCase):
    def test_accepts_matching_bearer_token(self):
        self.assertTrue(refresh_authorized("Bearer scheduler-secret", "scheduler-secret"))

    def test_rejects_missing_malformed_and_incorrect_tokens(self):
        self.assertFalse(refresh_authorized(None, "scheduler-secret"))
        self.assertFalse(refresh_authorized("scheduler-secret", "scheduler-secret"))
        self.assertFalse(refresh_authorized("Bearer wrong-secret", "scheduler-secret"))


class RefreshPayloadTests(unittest.TestCase):
    def test_returns_safe_site_authentication_summary(self):
        state = {
            "last_success": True,
            "last_run_id": "run-123",
            "last_finished_at": "2026-07-11T12:00:00+00:00",
            "last_history_saved": False,
            "last_site_summary": {
                "huawei": {
                    "total": 19,
                    "success_count": 19,
                    "failed_count": 0,
                    "auth_error_count": 0,
                },
                "kehua": {
                    "total": 42,
                    "success_count": 40,
                    "failed_count": 2,
                    "auth_error_count": 1,
                },
            },
            "last_error": "sensitive upstream detail",
        }

        payload = refresh_payload(state)

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["run_id"], "run-123")
        self.assertFalse(payload["sites"]["huawei"]["authentication_error"])
        self.assertTrue(payload["sites"]["kehua"]["authentication_error"])
        self.assertNotIn("last_error", payload)
        self.assertNotIn("sensitive upstream detail", str(payload))


if __name__ == "__main__":
    unittest.main()
