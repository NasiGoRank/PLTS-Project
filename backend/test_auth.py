import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import bearer_token, require_authenticated_user


class BearerTokenTests(unittest.TestCase):
    def test_extracts_bearer_token(self):
        self.assertEqual(bearer_token("Bearer user-token"), "user-token")

    def test_rejects_missing_or_malformed_token(self):
        self.assertIsNone(bearer_token(None))
        self.assertIsNone(bearer_token(""))
        self.assertIsNone(bearer_token("user-token"))
        self.assertIsNone(bearer_token("Basic user-token"))
        self.assertIsNone(bearer_token("Bearer "))


class RequireAuthenticatedUserTests(unittest.TestCase):
    def test_rejects_missing_token(self):
        with self.assertRaises(HTTPException) as ctx:
            require_authenticated_user(None)

        self.assertEqual(ctx.exception.status_code, 401)

    @patch("api.STORE")
    def test_verifies_valid_token(self, store):
        store.verify_access_token.return_value = {"id": "user-1", "email": "ops@example.com"}

        user = require_authenticated_user("Bearer valid-token")

        self.assertEqual(user["id"], "user-1")
        store.verify_access_token.assert_called_once_with("valid-token")

    @patch("api.STORE")
    def test_rejects_invalid_token(self, store):
        store.verify_access_token.side_effect = RuntimeError("bad token")

        with self.assertRaises(HTTPException) as ctx:
            require_authenticated_user("Bearer invalid-token")

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertNotIn("bad token", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
