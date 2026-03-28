"""Optional Telethon-powered full member sync helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict

import pytz

from app.core import config


logger = logging.getLogger(__name__)

SYNC_METADATA_HEADERS = [
    "Telegram Status",
    "Role",
    "In Group Now",
    "Sync Note",
    "Last Sync At",
    "Sync Source",
]

ADMIN_PARTICIPANT_TYPE_NAMES = {
    "ChannelParticipantAdmin",
    "ChannelParticipantCreator",
    "ChatParticipantAdmin",
    "ChatParticipantCreator",
}


class TelethonReconcileService:
    """Backfill full Telegram group membership using a Telethon user session."""

    def __init__(self, sheets_manager):
        self.sheets_manager = sheets_manager

    @staticmethod
    def is_configured() -> bool:
        """Return True when the env looks ready for a Telethon sync."""
        has_api_credentials = bool(config.TELETHON_API_ID and config.TELETHON_API_HASH)
        has_session = bool(config.TELETHON_SESSION_STRING or config.TELETHON_SESSION_NAME)
        return has_api_credentials and has_session

    @staticmethod
    def get_configuration_help() -> str:
        """Return a compact setup hint for the full sync command."""
        return (
            "กรุณาตั้งค่า TELETHON_API_ID, TELETHON_API_HASH และระบุ "
            "TELETHON_SESSION_STRING หรือ TELETHON_SESSION_NAME ก่อนใช้ "
            "/fullsyncmembers"
        )

    async def full_sync_members(self, group_chat_id: int) -> Dict[str, object]:
        """Run a full-member reconciliation using Telethon."""
        if not self.is_configured():
            raise RuntimeError(self.get_configuration_help())

        TelegramClient, StringSession = self._import_telethon_client()

        sync_time = datetime.now(pytz.timezone(config.TIMEZONE)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        sheet_members = self.sheets_manager.get_all_members()
        sheet_members_by_user_id = {
            str(member.get("User ID", "")).strip(): member
            for member in sheet_members
            if str(member.get("User ID", "")).strip()
        }

        snapshot = {
            "group_chat_id": group_chat_id,
            "sheet_total_before": len(sheet_members_by_user_id),
            "sheet_total_after": len(sheet_members_by_user_id),
            "group_member_count": 0,
            "group_admin_count": 0,
            "group_regular_member_count": 0,
            "rows_added_to_sheet": 0,
            "rows_updated_in_sheet": 0,
            "rows_unchanged_in_sheet": 0,
            "removed_from_sheet": [],
            "sync_time": sync_time,
            "sync_source": "telethon_full_sync",
        }

        session = (
            StringSession(config.TELETHON_SESSION_STRING)
            if config.TELETHON_SESSION_STRING
            else config.TELETHON_SESSION_NAME
        )
        client = TelegramClient(
            session,
            config.TELETHON_API_ID,
            config.TELETHON_API_HASH,
        )

        async with client:
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telethon session ยังไม่ได้รับการยืนยันตัวตน "
                    "กรุณา login ด้วย session นี้อย่างน้อยหนึ่งครั้งก่อนใช้ /fullsyncmembers"
                )

            entity = await client.get_entity(group_chat_id)
            seen_user_ids = set()
            member_payloads = []
            removal_payloads = []

            async for participant_user in client.iter_participants(entity):
                user_id = str(participant_user.id)
                seen_user_ids.add(user_id)

                role = self._derive_role(participant_user)
                if role == "admin":
                    snapshot["group_admin_count"] += 1
                else:
                    snapshot["group_regular_member_count"] += 1

                existing_member = sheet_members_by_user_id.get(user_id, {})
                member_payloads.append(
                    {
                        "Username": self.format_telegram_username(
                            participant_user,
                            fallback_username=existing_member.get("Username", ""),
                            fallback_user_id=user_id,
                        ),
                        "User ID": user_id,
                        "Expiredate": existing_member.get("Expiredate")
                        or config.SYNC_BACKFILL_EXPIREDATE,
                        "First Name": getattr(participant_user, "first_name", "") or "",
                        "Last Name": getattr(participant_user, "last_name", "") or "",
                        "Telegram Status": self._derive_telegram_status(participant_user),
                        "Role": role,
                        "Record Status": "active",
                        "In Group Now": "Yes",
                        "Join Source": existing_member.get("Join Source", "telethon_full_sync"),
                        "Invite Link Label": existing_member.get("Invite Link Label", ""),
                        "Expire Policy Days": existing_member.get("Expire Policy Days", ""),
                        "Joined At": existing_member.get("Joined At", ""),
                        "Approved By": existing_member.get("Approved By", ""),
                        "Approved At": existing_member.get("Approved At", ""),
                        "Added By": existing_member.get("Added By", "system"),
                        "Sync Note": "",
                        "Last Sync At": sync_time,
                        "Last Sync Result": "verified_in_group",
                        "Last Seen In Group At": sync_time,
                        "Removed At": "",
                        "Remove Reason": "",
                        "Sync Source": "telethon_full_sync",
                    }
                )

            missing_user_ids = [
                user_id
                for user_id in sheet_members_by_user_id
                if user_id not in seen_user_ids
            ]
            for user_id in missing_user_ids:
                removal_payloads.append(
                    {
                        "User ID": user_id,
                        "Record Status": "removed",
                        "In Group Now": "No",
                        "Last Sync At": sync_time,
                        "Last Sync Result": "removed_from_group",
                        "Sync Note": "Member not found during Telethon full sync",
                        "Removed At": sync_time,
                        "Remove Reason": "Missing from Telegram group during Telethon full sync",
                        "Sync Source": "telethon_full_sync",
                    }
                )
            sync_result = self.sheets_manager.bulk_sync_members(
                member_payloads,
                remove_user_ids=missing_user_ids,
                required_headers=SYNC_METADATA_HEADERS,
                removal_payloads=removal_payloads,
            )

            snapshot["rows_added_to_sheet"] = len(sync_result["added_user_ids"])
            snapshot["rows_updated_in_sheet"] = len(sync_result["updated_user_ids"])
            snapshot["rows_unchanged_in_sheet"] = len(sync_result["unchanged_user_ids"])
            removed_user_ids = set(sync_result["removed_user_ids"])
            snapshot["removed_from_sheet"] = [
                {
                    "user_id": user_id,
                    "username": sheet_members_by_user_id[user_id].get("Username", f"User_{user_id}"),
                }
                for user_id in missing_user_ids
                if user_id in removed_user_ids
            ]
            snapshot["group_member_count"] = len(seen_user_ids)
            snapshot["sheet_total_after"] = (
                snapshot["sheet_total_before"]
                + snapshot["rows_added_to_sheet"]
            )

            for removed_member in snapshot["removed_from_sheet"]:
                self.sheets_manager.append_audit_log(
                    user_id=removed_member["user_id"],
                    username=removed_member["username"],
                    action="full_sync_marked_removed",
                    old_value=sheet_members_by_user_id.get(removed_member["user_id"], {}),
                    new_value={
                        "Record Status": "removed",
                        "In Group Now": "No",
                        "Remove Reason": "Missing from Telegram group during Telethon full sync",
                    },
                    actor="system",
                    source="telethon_full_sync",
                    note="Full sync marked this member as removed because they were not returned by Telethon",
                )

        logger.info(
            "Telethon full sync completed: group=%s members=%s added=%s removed=%s",
            group_chat_id,
            snapshot["group_member_count"],
            snapshot["rows_added_to_sheet"],
            len(snapshot["removed_from_sheet"]),
        )
        return snapshot

    @staticmethod
    def format_telegram_username(
        telegram_user,
        fallback_username: str,
        fallback_user_id: str,
    ) -> str:
        """Return a normalized username-like display value."""
        if telegram_user and getattr(telegram_user, "username", None):
            return f"@{telegram_user.username}"
        if fallback_username:
            return fallback_username
        return f"User_{fallback_user_id}"

    @staticmethod
    def _derive_telegram_status(participant_user) -> str:
        participant = getattr(participant_user, "participant", None)
        participant_type_name = participant.__class__.__name__ if participant else ""
        if participant_type_name.endswith("Creator"):
            return "creator"
        if participant_type_name in ADMIN_PARTICIPANT_TYPE_NAMES:
            return "administrator"
        return "member"

    @staticmethod
    def _derive_role(participant_user) -> str:
        participant = getattr(participant_user, "participant", None)
        participant_type_name = participant.__class__.__name__ if participant else ""
        if participant_type_name in ADMIN_PARTICIPANT_TYPE_NAMES:
            return "admin"
        return "member"

    @staticmethod
    def _import_telethon_client():
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:
            raise RuntimeError(
                "ยังไม่ได้ติดตั้ง Telethon กรุณาติดตั้ง dependency นี้ก่อนใช้ /fullsyncmembers"
            ) from exc

        return TelegramClient, StringSession
