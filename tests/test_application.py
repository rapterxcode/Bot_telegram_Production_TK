"""Smoke tests for handler registration and polling configuration."""

import unittest

from app.bot.application import COMMAND_HANDLERS, register_handlers
from app.bot.telegram_bot import POLLING_ALLOWED_UPDATES


class FakeApplication:
    """Minimal application double for handler registration tests."""

    def __init__(self):
        self.handlers = []
        self.error_handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)

    def add_error_handler(self, handler):
        self.error_handlers.append(handler)


class DummyBot:
    """Expose the handler methods expected by register_handlers."""

    async def start_command(self, update, context):
        del update, context

    async def help_command(self, update, context):
        del update, context

    async def status_command(self, update, context):
        del update, context

    async def status_live_command(self, update, context):
        del update, context

    async def check_now_command(self, update, context):
        del update, context

    async def sync_members_command(self, update, context):
        del update, context

    async def full_sync_members_command(self, update, context):
        del update, context

    async def list_expired_command(self, update, context):
        del update, context

    async def add_member_command(self, update, context):
        del update, context

    async def remove_member_command(self, update, context):
        del update, context

    async def list_members_command(self, update, context):
        del update, context

    async def pending_members_command(self, update, context):
        del update, context

    async def update_expire_command(self, update, context):
        del update, context

    async def set_check_interval_command(self, update, context):
        del update, context

    async def invite_link_command(self, update, context):
        del update, context

    async def invite_link_1month_command(self, update, context):
        del update, context

    async def invite_link_1year_command(self, update, context):
        del update, context

    async def invite_link_no_expire_command(self, update, context):
        del update, context

    async def list_admins_command(self, update, context):
        del update, context

    async def track_chat_member_updates(self, update, context):
        del update, context

    async def handle_chat_join_request(self, update, context):
        del update, context

    async def handle_approval_callback(self, update, context):
        del update, context

    async def error_handler(self, update, context):
        del update, context


class ApplicationTests(unittest.TestCase):
    """Verify handler registration stays aligned with bot expectations."""

    def test_register_handlers_adds_commands_and_event_handlers(self):
        application = FakeApplication()
        register_handlers(application, DummyBot())

        self.assertEqual(len(application.handlers), len(COMMAND_HANDLERS) + 3)
        self.assertEqual(len(application.error_handlers), 1)

    def test_polling_allowed_updates_covers_required_member_events(self):
        self.assertIn("message", POLLING_ALLOWED_UPDATES)
        self.assertIn("callback_query", POLLING_ALLOWED_UPDATES)
        self.assertIn("chat_member", POLLING_ALLOWED_UPDATES)
        self.assertIn("chat_join_request", POLLING_ALLOWED_UPDATES)
        self.assertIn("my_chat_member", POLLING_ALLOWED_UPDATES)


if __name__ == "__main__":
    unittest.main()
