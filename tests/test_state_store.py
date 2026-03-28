"""Tests for persisted bot runtime state."""

import shutil
import unittest
from datetime import datetime
from pathlib import Path

from app.services.state_store import BotStateStore


class BotStateStoreTests(unittest.TestCase):
    """Verify JSON state round-trips cleanly."""

    def test_save_and_load_state_round_trip(self):
        state_dir = Path("tests") / "_tmp_state_store"
        if state_dir.exists():
            shutil.rmtree(state_dir)

        try:
            store = BotStateStore(state_dir / "bot_state.json")
            created_time = datetime(2026, 3, 28, 9, 0, 0)
            expire_time = datetime(2026, 3, 28, 9, 30, 0)

            store.save_state(
                invite_link_expires={
                    "https://t.me/+abc": {
                        "type": "1month",
                        "days": 31,
                        "period_name": "1 month",
                        "created_time": created_time,
                        "expire_time": expire_time,
                    }
                },
                active_invite_links={
                    "https://t.me/+abc": {
                        "type": "1month",
                        "days": 31,
                        "period_name": "1 month",
                    }
                },
                pending_members={
                    "123": {
                        "username": "@member",
                        "first_name": "Test",
                        "last_name": "User",
                        "join_type": "1month",
                        "expire_date_str": "2026-04-28 09:00:00",
                        "timestamp": "28/03/2026 09:00:00",
                        "chat_id": "-1009876543210",
                        "approval_mode": "join_request",
                    }
                },
                sent_notifications={"join_request_123"},
                last_sync_snapshot={
                    "sync_source": "bot_api_sync",
                    "sheet_total_after": 10,
                    "sync_time": "2026-03-28 09:15:00",
                },
            )

            snapshot = store.load_state()

            self.assertEqual(
                snapshot.invite_link_expires["https://t.me/+abc"]["created_time"],
                created_time,
            )
            self.assertEqual(
                snapshot.invite_link_expires["https://t.me/+abc"]["expire_time"],
                expire_time,
            )
            self.assertEqual(snapshot.pending_members["123"]["chat_id"], -1009876543210)
            self.assertEqual(snapshot.sent_notifications, {"join_request_123"})
            self.assertEqual(snapshot.last_sync_snapshot["sync_source"], "bot_api_sync")
        finally:
            if state_dir.exists():
                shutil.rmtree(state_dir)


if __name__ == "__main__":
    unittest.main()
