"""Tests for Bot API-based reconciliation helpers."""

import unittest

from app.bot.reconciliation import MemberSyncMixin
from app.core import config


class DummyUser:
    """Minimal Telegram user double."""

    def __init__(self, user_id, username=None, first_name="", last_name=""):
        self.id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name


class DummyChatMember:
    """Minimal chat member object for helper tests."""

    def __init__(self, status, user=None, is_member=False):
        self.status = status
        self.user = user
        self.is_member = is_member


class FakeSheetsManager:
    """Capture reconciliation writes without touching Google Sheets."""

    def __init__(self, members):
        self.members = list(members)
        self.bulk_sync_calls = []

    def get_all_members(self, include_inactive=False):
        del include_inactive
        return list(self.members)

    def get_expired_members(self):
        return []

    def bulk_sync_members(
        self,
        member_payloads,
        remove_user_ids=None,
        required_headers=None,
        removal_payloads=None,
    ):
        self.bulk_sync_calls.append(
            {
                "member_payloads": list(member_payloads),
                "remove_user_ids": list(remove_user_ids or []),
                "required_headers": list(required_headers or []),
                "removal_payloads": list(removal_payloads or []),
            }
        )

        existing_user_ids = {str(member.get("User ID")) for member in self.members}
        payload_user_ids = [payload["User ID"] for payload in member_payloads]
        added_user_ids = [user_id for user_id in payload_user_ids if user_id not in existing_user_ids]
        updated_user_ids = [user_id for user_id in payload_user_ids if user_id in existing_user_ids]
        removed_user_ids = list(remove_user_ids or [])
        return {
            "added_user_ids": added_user_ids,
            "updated_user_ids": updated_user_ids,
            "unchanged_user_ids": [],
            "removed_user_ids": removed_user_ids,
        }


class FakeBot:
    """Minimal bot double for inspect_group_members."""

    def __init__(self, group_member_count, admin_members):
        self.group_member_count = group_member_count
        self.admin_members = admin_members

    async def get_chat_member_count(self, chat_id):
        del chat_id
        return self.group_member_count

    async def get_chat_administrators(self, chat_id):
        del chat_id
        return list(self.admin_members)


class FakeContext:
    """Expose a fake bot object through the expected context shape."""

    def __init__(self, bot):
        self.bot = bot


class DummySync(MemberSyncMixin):
    """Bind reconciliation helpers to fake sheets/chat member state."""

    def __init__(self, sheets_manager, chat_members):
        self.sheets_manager = sheets_manager
        self.chat_members = dict(chat_members)
        self.group_chat_id = -100123456
        self.last_sync_snapshot = {}

    async def safe_get_chat_member(self, context, chat_id, user_id):
        del context, chat_id
        return self.chat_members.get(str(user_id))

    def store_last_sync_snapshot(self, snapshot: dict):
        self.last_sync_snapshot = dict(snapshot)


class ReconciliationHelpersTests(unittest.TestCase):
    """Verify role and membership helpers stay stable."""

    def test_restricted_member_counts_as_in_group_when_is_member_true(self):
        chat_member = DummyChatMember(status="restricted", is_member=True)

        self.assertTrue(MemberSyncMixin.is_chat_member_in_group(chat_member))
        self.assertEqual(
            MemberSyncMixin.derive_role_from_chat_member(chat_member),
            "member",
        )

    def test_left_member_is_not_in_group(self):
        chat_member = DummyChatMember(status="left")

        self.assertFalse(MemberSyncMixin.is_chat_member_in_group(chat_member))
        self.assertEqual(
            MemberSyncMixin.derive_role_from_chat_member(chat_member),
            "not_in_group",
        )

    def test_build_status_lines_includes_partial_reconciliation_note(self):
        lines = DummySync(FakeSheetsManager([]), {}).build_status_lines(
            snapshot={
                "sheet_total_before": 10,
                "sheet_total_after": 10,
                "sheet_in_group_count": 8,
                "sheet_admin_count": 2,
                "sheet_member_count": 6,
                "sheet_missing_from_group": [{"user_id": "1"}],
                "group_member_count": 12,
                "group_admin_count": 3,
                "admins_not_in_sheet": [{"user_id": "2"}],
                "possible_untracked_group_members": 3,
                "group_chat_id": -100123456,
                "sync_time": "2026-03-28 16:00:00",
                "sync_source": "bot_api_live_lookup",
            },
            expired_member_count=1,
        )

        self.assertTrue(
            any("สมาชิกในกลุ่มที่อาจยังไม่ถูกติดตาม: 3" in line for line in lines)
        )
        self.assertTrue(any("Telegram Bot API" in line for line in lines))
        self.assertTrue(
            any("ตั้งค่า Telethon full sync แล้วหรือไม่:" in line for line in lines)
        )

    def test_build_cached_status_snapshot_marks_origin(self):
        sync = DummySync(FakeSheetsManager([]), {})
        sync.last_sync_snapshot = {
            "sync_source": "bot_api_sync",
            "sheet_total_before": 5,
            "sheet_total_after": 5,
            "sheet_in_group_count": 4,
            "sheet_admin_count": 1,
            "sheet_member_count": 3,
            "sheet_missing_from_group": [],
            "group_admin_count": 1,
            "group_chat_id": -100123456,
            "sync_time": "2026-03-28 16:00:00",
        }

        snapshot = sync.build_cached_status_snapshot()

        self.assertEqual(snapshot["status_origin"], "cached_snapshot")
        self.assertEqual(snapshot["sync_source"], "bot_api_sync")


class ReconciliationAsyncTests(unittest.IsolatedAsyncioTestCase):
    """Verify stateful reconciliation behavior."""

    async def test_inspect_group_members_auto_adds_missing_admins(self):
        original_auto_add = config.SYNC_AUTO_ADD_MISSING_ADMINS_TO_SHEET
        original_backfill_expire = config.SYNC_BACKFILL_EXPIREDATE
        config.SYNC_AUTO_ADD_MISSING_ADMINS_TO_SHEET = True
        config.SYNC_BACKFILL_EXPIREDATE = "no_expire"

        try:
            sheets_manager = FakeSheetsManager(
                [
                    {
                        "Username": "@member",
                        "User ID": "100",
                        "Expiredate": "2026-04-01 00:00:00",
                    }
                ]
            )
            known_user = DummyUser(100, "member", "Regular", "User")
            admin_user = DummyUser(200, "boss", "Boss", "Admin")
            sync = DummySync(
                sheets_manager=sheets_manager,
                chat_members={
                    "100": DummyChatMember(status="member", user=known_user),
                },
            )
            context = FakeContext(
                FakeBot(
                    group_member_count=2,
                    admin_members=[
                        DummyChatMember(status="administrator", user=admin_user),
                    ],
                )
            )

            snapshot = await sync.inspect_group_members(
                context=context,
                apply_sheet_changes=True,
                remove_missing_from_sheet=True,
            )

            self.assertEqual(snapshot["sheet_in_group_count"], 2)
            self.assertEqual(snapshot["sheet_admin_count"], 1)
            self.assertEqual(len(snapshot["admins_auto_added_to_sheet"]), 1)
            self.assertEqual(len(snapshot["admins_not_in_sheet"]), 0)
            self.assertEqual(snapshot["possible_untracked_group_members"], 0)
            self.assertEqual(snapshot["rows_added_to_sheet"], 1)
            self.assertEqual(snapshot["rows_updated_in_sheet"], 1)
            self.assertEqual(
                sheets_manager.bulk_sync_calls[0]["member_payloads"][1]["Sync Source"],
                "bot_api_admin_backfill",
            )
        finally:
            config.SYNC_AUTO_ADD_MISSING_ADMINS_TO_SHEET = original_auto_add
            config.SYNC_BACKFILL_EXPIREDATE = original_backfill_expire


if __name__ == "__main__":
    unittest.main()
