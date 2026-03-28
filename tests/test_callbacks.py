"""Smoke tests for callback helper utilities."""

import unittest

from app.bot.callbacks import ApprovalCallbacksMixin


class CallbackHelpersTests(unittest.TestCase):
    """Verify callback parsing stays stable."""

    def test_parse_join_request_callback_data(self):
        action, user_id, is_join_request = ApprovalCallbacksMixin._parse_callback_data(
            "approve_join_12345"
        )

        self.assertEqual(action, "approve")
        self.assertEqual(user_id, "12345")
        self.assertTrue(is_join_request)

    def test_parse_member_update_callback_data(self):
        action, user_id, is_join_request = ApprovalCallbacksMixin._parse_callback_data(
            "reject_98765"
        )

        self.assertEqual(action, "reject")
        self.assertEqual(user_id, "98765")
        self.assertFalse(is_join_request)

    def test_get_pending_chat_id_prefers_serialized_chat_id(self):
        self.assertEqual(
            ApprovalCallbacksMixin._get_pending_chat_id({"chat_id": -100123456}),
            -100123456,
        )


if __name__ == "__main__":
    unittest.main()
