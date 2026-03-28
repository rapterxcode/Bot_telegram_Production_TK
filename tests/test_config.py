"""Smoke tests for runtime configuration helpers."""

import unittest

from app.core import config


class ConfigTests(unittest.TestCase):
    """Verify lightweight config helpers without touching the environment."""

    def test_get_check_interval_seconds_uses_current_unit(self):
        original_value = config.CHECK_INTERVAL_VALUE
        original_unit = config.CHECK_INTERVAL_UNIT

        try:
            config.CHECK_INTERVAL_VALUE = 2
            config.CHECK_INTERVAL_UNIT = "hours"
            self.assertEqual(config.get_check_interval_seconds(), 7200)
        finally:
            config.CHECK_INTERVAL_VALUE = original_value
            config.CHECK_INTERVAL_UNIT = original_unit

    def test_is_admin_uses_loaded_admin_ids(self):
        original_admin_ids = config.ADMIN_USER_IDS

        try:
            config.ADMIN_USER_IDS = [111, 222]
            self.assertTrue(config.is_admin(111))
            self.assertFalse(config.is_admin(333))
        finally:
            config.ADMIN_USER_IDS = original_admin_ids


if __name__ == "__main__":
    unittest.main()
