"""Group membership reconciliation helpers."""

import asyncio
import logging
from datetime import datetime
from typing import List

import pytz
from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from app.core import config
from app.services.telethon_reconcile import TelethonReconcileService


logger = logging.getLogger(__name__)

SYNC_METADATA_HEADERS = [
    "Telegram Status",
    "Role",
    "In Group Now",
    "Sync Note",
    "Last Sync At",
    "Sync Source",
]

ACTIVE_CHAT_MEMBER_STATUSES = {"member", "administrator", "creator"}


class MemberSyncMixin:
    """Provide Bot API-based and optional Telethon-powered reconciliation."""

    async def sync_members_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Reconcile known sheet members against the current Telegram group."""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /syncmembers",
            )

        requester_id = update.effective_user.id
        if not config.is_admin(requester_id):
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id or requester_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่ง /syncmembers",
            )
            return

        try:
            snapshot = await self.inspect_group_members(
                context=context,
                apply_sheet_changes=True,
                remove_missing_from_sheet=True,
            )
            self.store_last_sync_snapshot(snapshot)
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id or requester_id,
                text=self.build_sync_summary(snapshot),
            )
        except Exception as exc:
            logger.exception("Error while syncing members")
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id or requester_id,
                text=f"ซิงก์สมาชิกไม่สำเร็จ: {exc}",
            )

    async def full_sync_members_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Run a full-member backfill using Telethon when configured."""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /fullsyncmembers",
            )

        requester_id = update.effective_user.id
        if not config.is_admin(requester_id):
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id or requester_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่ง /fullsyncmembers",
            )
            return

        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
        if not target_group_id:
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id or requester_id,
                text="ยังไม่ได้ตั้งค่า Group Chat ID",
            )
            return

        try:
            service = TelethonReconcileService(self.sheets_manager)
            snapshot = await service.full_sync_members(target_group_id)
            snapshot["status_origin"] = "full_sync"
            self.store_last_sync_snapshot(snapshot)
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id or requester_id,
                text=self.build_full_sync_summary(snapshot),
            )
        except Exception as exc:
            logger.exception("Error while running Telethon full sync")
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id or requester_id,
                text=f"ทำ full sync ไม่สำเร็จ: {exc}",
            )

    async def status_live_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Force a live status refresh instead of using the cached sync snapshot."""
        del update
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /statuslive",
            )

        try:
            snapshot = await self.inspect_group_members(
                context=context,
                apply_sheet_changes=False,
                remove_missing_from_sheet=False,
            )
            snapshot["status_origin"] = "live_lookup"
            self.store_last_sync_snapshot(snapshot)
            status_text = self.build_status_text(snapshot)
            await self.send_safe_message(context, admin_group_id, status_text)
        except Exception as exc:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"ตรวจสอบสถานะแบบสดไม่สำเร็จ: {str(exc)}",
            )

    async def inspect_group_members(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        apply_sheet_changes: bool,
        remove_missing_from_sheet: bool,
    ):
        """Inspect known sheet members against current Telegram membership."""
        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
        if not target_group_id:
            raise ValueError("ยังไม่ได้ตั้งค่า Group Chat ID")

        sync_time = self.get_current_sync_time()
        sheet_members = self.sheets_manager.get_all_members()
        sheet_user_ids = set()

        snapshot = {
            "group_chat_id": target_group_id,
            "sheet_total_before": len(sheet_members),
            "sheet_total_after": len(sheet_members),
            "sheet_in_group_count": 0,
            "sheet_admin_count": 0,
            "sheet_member_count": 0,
            "sheet_missing_from_group": [],
            "removed_from_sheet": [],
            "admins_auto_added_to_sheet": [],
            "admins_not_in_sheet": [],
            "group_admin_count": 0,
            "group_member_count": None,
            "possible_untracked_group_members": None,
            "rows_added_to_sheet": 0,
            "rows_updated_in_sheet": 0,
            "rows_unchanged_in_sheet": 0,
            "sync_time": sync_time,
            "sync_source": "bot_api_sync" if apply_sheet_changes else "bot_api_live_lookup",
            "status_origin": "live_lookup",
            "uses_bot_api_partial_reconciliation": True,
        }

        group_count_task = asyncio.create_task(
            self.safe_get_chat_member_count(context, target_group_id)
        )
        admin_members_task = asyncio.create_task(
            self.safe_get_chat_administrators(context, target_group_id)
        )

        member_user_ids = [
            str(member.get("User ID", "")).strip()
            for member in sheet_members
            if str(member.get("User ID", "")).strip()
        ]
        chat_members_by_user_id = await self.lookup_chat_members_by_user_id(
            context=context,
            chat_id=target_group_id,
            user_ids=member_user_ids,
        )

        snapshot["group_member_count"] = await group_count_task
        admin_members = await admin_members_task
        snapshot["group_admin_count"] = len(admin_members)

        member_payloads = []
        remove_user_ids = []

        for member in sheet_members:
            member_user_id = str(member.get("User ID", "")).strip()
            if not member_user_id:
                continue

            sheet_user_ids.add(member_user_id)
            chat_member = chat_members_by_user_id.get(member_user_id)
            telegram_status = self.get_chat_member_status(chat_member)
            in_group_now = self.is_chat_member_in_group(chat_member)

            if not in_group_now:
                missing_entry = {
                    "user_id": member_user_id,
                    "username": member.get("Username", "Unknown"),
                    "telegram_status": telegram_status or "unknown",
                }
                snapshot["sheet_missing_from_group"].append(missing_entry)

                if apply_sheet_changes and remove_missing_from_sheet:
                    remove_user_ids.append(member_user_id)
                continue

            role = self.derive_role_from_chat_member(chat_member)
            snapshot["sheet_in_group_count"] += 1
            if role == "admin":
                snapshot["sheet_admin_count"] += 1
            else:
                snapshot["sheet_member_count"] += 1

            if apply_sheet_changes:
                member_payloads.append(
                    self.build_member_sync_payload(
                        telegram_user=getattr(chat_member, "user", None),
                        fallback_member=member,
                        user_id=member_user_id,
                        expire_date=member.get("Expiredate", ""),
                        telegram_status=telegram_status,
                        role=role,
                        sync_time=sync_time,
                        sync_note="",
                        sync_source="bot_api_sync",
                    )
                )

        for admin_member in admin_members:
            admin_user_id = str(admin_member.user.id)
            if admin_user_id in sheet_user_ids:
                continue

            admin_entry = {
                "user_id": admin_user_id,
                "username": self.format_telegram_username(
                    admin_member.user,
                    fallback_username="",
                    fallback_user_id=admin_user_id,
                ),
                "telegram_status": getattr(admin_member, "status", "administrator"),
            }

            if apply_sheet_changes and config.SYNC_AUTO_ADD_MISSING_ADMINS_TO_SHEET:
                member_payloads.append(
                    self.build_member_sync_payload(
                        telegram_user=admin_member.user,
                        fallback_member={},
                        user_id=admin_user_id,
                        expire_date=config.SYNC_BACKFILL_EXPIREDATE,
                        telegram_status=admin_entry["telegram_status"],
                        role="admin",
                        sync_time=sync_time,
                        sync_note="Auto-added from Telegram admin list",
                        sync_source="bot_api_admin_backfill",
                    )
                )
                snapshot["admins_auto_added_to_sheet"].append(admin_entry)
                snapshot["sheet_total_after"] += 1
                snapshot["sheet_in_group_count"] += 1
                snapshot["sheet_admin_count"] += 1
                sheet_user_ids.add(admin_user_id)
                continue

            snapshot["admins_not_in_sheet"].append(admin_entry)

        if apply_sheet_changes:
            sync_result = self.sheets_manager.bulk_sync_members(
                member_payloads,
                remove_user_ids=remove_user_ids if remove_missing_from_sheet else [],
                required_headers=SYNC_METADATA_HEADERS,
            )
            snapshot["rows_added_to_sheet"] = len(sync_result["added_user_ids"])
            snapshot["rows_updated_in_sheet"] = len(sync_result["updated_user_ids"])
            snapshot["rows_unchanged_in_sheet"] = len(sync_result["unchanged_user_ids"])
            removed_user_ids = set(sync_result["removed_user_ids"])
            snapshot["removed_from_sheet"] = [
                member
                for member in snapshot["sheet_missing_from_group"]
                if member["user_id"] in removed_user_ids
            ]
            snapshot["sheet_total_after"] = (
                snapshot["sheet_total_before"]
                + snapshot["rows_added_to_sheet"]
                - len(snapshot["removed_from_sheet"])
            )

        if snapshot["group_member_count"] is not None:
            known_group_members = snapshot["sheet_in_group_count"] + len(
                snapshot["admins_not_in_sheet"]
            )
            snapshot["possible_untracked_group_members"] = max(
                0,
                snapshot["group_member_count"] - known_group_members,
            )

        return snapshot

    async def lookup_chat_members_by_user_id(
        self,
        *,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        user_ids: List[str],
    ) -> dict:
        """Fetch multiple Telegram chat members concurrently with a safe limit."""
        if not user_ids:
            return {}

        semaphore = asyncio.Semaphore(max(1, int(config.TELEGRAM_MEMBER_LOOKUP_CONCURRENCY)))

        async def _fetch_member(user_id: str):
            async with semaphore:
                chat_member = await self.safe_get_chat_member(
                    context=context,
                    chat_id=chat_id,
                    user_id=user_id,
                )
                return user_id, chat_member

        results = await asyncio.gather(*[_fetch_member(user_id) for user_id in user_ids])
        return {user_id: chat_member for user_id, chat_member in results}

    async def safe_get_chat_member_count(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ):
        """Return the chat member count or None when Telegram rejects the lookup."""
        try:
            return await context.bot.get_chat_member_count(chat_id)
        except Exception as exc:
            logger.error("Cannot get group member count: %s", exc)
            return None

    async def safe_get_chat_administrators(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ):
        """Return the admin list or an empty list when Telegram rejects the lookup."""
        try:
            return await context.bot.get_chat_administrators(chat_id)
        except Exception as exc:
            logger.error("Cannot get group administrators: %s", exc)
            return []

    def build_status_text(self, snapshot: dict) -> str:
        """Build the full status message from a cached or live snapshot."""
        missing_user_ids = {
            member["user_id"] for member in snapshot.get("sheet_missing_from_group", [])
        }
        expired_members = [
            member
            for member in self.sheets_manager.get_expired_members()
            if member.get("User ID") not in missing_user_ids
        ]
        return "\n".join(
            self.build_status_lines(
                snapshot=snapshot,
                expired_member_count=len(expired_members),
            )
        )

    def build_status_lines(self, snapshot: dict, expired_member_count: int):
        """Build a status payload using both sheet and Telegram data."""
        interval_seconds = config.get_check_interval_seconds()
        unit_display = {
            "seconds": "วินาที",
            "minutes": "นาที",
            "hours": "ชั่วโมง",
            "days": "วัน",
        }
        interval_text = (
            f"{config.CHECK_INTERVAL_VALUE} "
            f"{unit_display.get(config.CHECK_INTERVAL_UNIT, config.CHECK_INTERVAL_UNIT)}"
        )

        telethon_configured = "yes" if TelethonReconcileService.is_configured() else "no"
        status_origin = snapshot.get("status_origin", "live_lookup")
        sync_source = snapshot.get("sync_source", "unknown")
        status_source_map = {
            "cached_snapshot": "snapshot ล่าสุด",
            "live_lookup": "ตรวจสอบสดจาก Telegram",
            "sync_command": "ซิงก์สมาชิก",
            "full_sync": "Full sync ผ่าน Telethon",
        }
        sync_source_map = {
            "bot_api_sync": "Bot API sync",
            "bot_api_live_lookup": "Bot API live lookup",
            "telethon_full_sync": "Telethon full sync",
            "unknown": "ไม่ทราบ",
        }
        status_source_label = status_source_map.get(status_origin, status_origin)
        sync_source_label = sync_source_map.get(sync_source, sync_source)

        lines = [
            "สถานะระบบ",
            f"แหล่งข้อมูลสถานะ: {status_source_label}",
            f"แหล่งข้อมูลของการซิงก์ล่าสุด: {sync_source_label}",
            f"จำนวนแถวในชีต: {snapshot['sheet_total_after' if status_origin == 'cached_snapshot' else 'sheet_total_before']}",
            f"สมาชิกในชีตที่ยังอยู่ในกลุ่ม: {snapshot['sheet_in_group_count']}",
            f"แอดมินในชีตที่ยังอยู่ในกลุ่ม: {snapshot['sheet_admin_count']}",
            f"สมาชิกทั่วไปในชีตที่ยังอยู่ในกลุ่ม: {snapshot['sheet_member_count']}",
            f"สมาชิกในชีตที่หายจากกลุ่ม: {len(snapshot['sheet_missing_from_group'])}",
            f"สมาชิกหมดอายุที่ยังอยู่ในกลุ่ม: {expired_member_count}",
            (
                f"จำนวนสมาชิกในกลุ่ม Telegram: {snapshot['group_member_count']}"
                if snapshot["group_member_count"] is not None
                else "จำนวนสมาชิกในกลุ่ม Telegram: ไม่สามารถตรวจสอบได้"
            ),
            f"จำนวนแอดมินในกลุ่ม Telegram: {snapshot['group_admin_count']}",
            f"แอดมินที่อยู่ในกลุ่มแต่ยังไม่อยู่ในชีต: {len(snapshot['admins_not_in_sheet'])}",
            (
                "สมาชิกในกลุ่มที่อาจยังไม่ถูกติดตาม: "
                f"{snapshot['possible_untracked_group_members']}"
                if snapshot["possible_untracked_group_members"] is not None
                else "สมาชิกในกลุ่มที่อาจยังไม่ถูกติดตาม: ไม่สามารถตรวจสอบได้"
            ),
            f"ตั้งค่าให้เพิ่มแอดมินที่ตกหล่นอัตโนมัติหรือไม่: {'ใช่' if config.SYNC_AUTO_ADD_MISSING_ADMINS_TO_SHEET else 'ไม่ใช่'}",
            f"ตั้งค่า Telethon full sync แล้วหรือไม่: {'ใช่' if telethon_configured == 'yes' else 'ไม่ใช่'}",
            f"กลุ่มเป้าหมาย: {snapshot['group_chat_id']}",
            f"Google Sheet: {config.WORKSHEET_NAME}",
            f"รอบเวลาตรวจสอบ: {interval_text} ({interval_seconds} วินาที)",
            f"เวลาปัจจุบัน: {snapshot['sync_time']} ({config.TIMEZONE})",
        ]

        if status_origin == "cached_snapshot":
            lines.append(
                "หมายเหตุ: ตอนนี้แสดงข้อมูลจาก snapshot ล่าสุด หากต้องการตรวจสอบสดให้ใช้ /statuslive"
            )
        else:
            lines.append(
                "หมายเหตุ: Telegram Bot API ตรวจสอบสมาชิกที่เรารู้จักและรายชื่อแอดมินได้ "
                "แต่ไม่สามารถดึงสมาชิกทุกคนในกลุ่มได้โดยตรง"
            )
        return lines

    def build_sync_summary(self, snapshot: dict):
        """Summarize the result of a Bot API sync run for admins."""
        lines = [
            "ซิงก์สมาชิกเรียบร้อยแล้ว",
            f"จำนวนแถวในชีตก่อนซิงก์: {snapshot['sheet_total_before']}",
            f"จำนวนแถวในชีตหลังซิงก์: {snapshot['sheet_total_after']}",
            f"สมาชิกที่ยืนยันได้ว่ายังอยู่ในกลุ่ม: {snapshot['sheet_in_group_count']}",
            f"จำนวนแถวที่เพิ่มในชีต: {snapshot['rows_added_to_sheet']}",
            f"จำนวนแถวที่อัปเดตในชีต: {snapshot['rows_updated_in_sheet']}",
            f"จำนวนแถวที่ข้อมูลไม่เปลี่ยน: {snapshot['rows_unchanged_in_sheet']}",
            f"จำนวนผู้ใช้ที่ลบออกจากชีต: {len(snapshot['removed_from_sheet'])}",
            f"จำนวนแอดมินที่เพิ่มเข้าชีตอัตโนมัติ: {len(snapshot['admins_auto_added_to_sheet'])}",
            f"จำนวนแอดมินที่ยังไม่พบในชีต: {len(snapshot['admins_not_in_sheet'])}",
        ]

        if snapshot["group_member_count"] is not None:
            lines.append(
                f"จำนวนสมาชิกในกลุ่ม Telegram: {snapshot['group_member_count']}"
            )

        if snapshot["removed_from_sheet"]:
            lines.append("")
            lines.append("รายชื่อที่ถูกลบออกจากชีต:")
            for removed_member in snapshot["removed_from_sheet"][:20]:
                lines.append(
                    f"- {removed_member['username']} ({removed_member['user_id']}) "
                    f"[{removed_member['telegram_status']}]"
                )

        if snapshot["admins_auto_added_to_sheet"]:
            lines.append("")
            lines.append("แอดมินที่ถูกเพิ่มเข้าชีตอัตโนมัติ:")
            for admin_member in snapshot["admins_auto_added_to_sheet"][:20]:
                lines.append(
                    f"- {admin_member['username']} ({admin_member['user_id']})"
                )

        if snapshot["admins_not_in_sheet"]:
            lines.append("")
            lines.append("แอดมินที่ยังไม่พบในชีต:")
            for admin_member in snapshot["admins_not_in_sheet"][:20]:
                lines.append(
                    f"- {admin_member['username']} ({admin_member['user_id']})"
                )

        lines.append("")
        lines.append(
            "หมายเหตุ: รอบนี้ระบบเขียน Google Sheets แบบ batch และจำกัดจำนวนการเช็กสมาชิกพร้อมกัน "
            "เพื่อให้ซิงก์ได้เร็วขึ้น"
        )
        return "\n".join(lines)

    def build_full_sync_summary(self, snapshot: dict):
        """Summarize the result of a Telethon full sync run for admins."""
        lines = [
            "ทำ full sync เรียบร้อยแล้ว",
            f"แหล่งข้อมูลการซิงก์: {snapshot['sync_source']}",
            f"จำนวนแถวในชีตก่อนซิงก์: {snapshot['sheet_total_before']}",
            f"จำนวนแถวในชีตหลังซิงก์: {snapshot['sheet_total_after']}",
            f"จำนวนสมาชิกในกลุ่ม Telegram: {snapshot['group_member_count']}",
            f"จำนวนแอดมินในกลุ่ม Telegram: {snapshot['group_admin_count']}",
            f"จำนวนสมาชิกทั่วไปในกลุ่ม Telegram: {snapshot['group_regular_member_count']}",
            f"จำนวนแถวที่เพิ่มในชีต: {snapshot['rows_added_to_sheet']}",
            f"จำนวนแถวที่อัปเดตในชีต: {snapshot['rows_updated_in_sheet']}",
            f"จำนวนแถวที่ข้อมูลไม่เปลี่ยน: {snapshot['rows_unchanged_in_sheet']}",
            f"จำนวนแถวที่ลบออกจากชีต: {len(snapshot['removed_from_sheet'])}",
            f"กลุ่มเป้าหมาย: {snapshot['group_chat_id']}",
            f"เวลาที่ซิงก์: {snapshot['sync_time']}",
        ]

        if snapshot["removed_from_sheet"]:
            lines.append("")
            lines.append("รายชื่อที่ถูกลบออกจากชีต:")
            for member in snapshot["removed_from_sheet"][:20]:
                lines.append(f"- {member['username']} ({member['user_id']})")

        return "\n".join(lines)

    def build_cached_status_snapshot(self) -> dict:
        """Return the latest persisted sync snapshot marked as cached."""
        cached_snapshot = dict(getattr(self, "last_sync_snapshot", {}) or {})
        required_keys = {
            "sheet_total_before",
            "sheet_total_after",
            "sheet_in_group_count",
            "sheet_admin_count",
            "sheet_member_count",
            "sheet_missing_from_group",
            "group_admin_count",
            "group_chat_id",
            "sync_time",
        }
        if not required_keys.issubset(cached_snapshot):
            return {}
        if cached_snapshot:
            cached_snapshot["status_origin"] = "cached_snapshot"
        return cached_snapshot

    def build_member_sync_payload(
        self,
        *,
        telegram_user,
        fallback_member: dict,
        user_id: str,
        expire_date: str,
        telegram_status: str,
        role: str,
        sync_time: str,
        sync_note: str,
        sync_source: str,
    ) -> dict:
        """Build a worksheet payload for bulk sync writes."""
        return {
            "Username": self.format_telegram_username(
                telegram_user,
                fallback_username=fallback_member.get("Username", ""),
                fallback_user_id=user_id,
            ),
            "User ID": user_id,
            "Expiredate": expire_date,
            "First Name": getattr(telegram_user, "first_name", "") or "",
            "Last Name": getattr(telegram_user, "last_name", "") or "",
            **self.build_sync_metadata(
                telegram_status=telegram_status,
                role=role,
                sync_time=sync_time,
                sync_note=sync_note,
                sync_source=sync_source,
            ),
        }

    @staticmethod
    def build_sync_metadata(
        *,
        telegram_status: str,
        role: str,
        sync_time: str,
        sync_note: str,
        sync_source: str,
    ) -> dict:
        """Build a consistent sync metadata payload for sheet writes."""
        return {
            "Telegram Status": telegram_status,
            "Role": role,
            "In Group Now": "Yes",
            "Sync Note": sync_note,
            "Last Sync At": sync_time,
            "Sync Source": sync_source,
        }

    @staticmethod
    def get_current_sync_time() -> str:
        """Return the current time formatted for sync metadata."""
        return datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")

    async def safe_get_chat_member(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        user_id: str,
    ):
        """Return chat member info or None when the user cannot be resolved."""
        try:
            return await context.bot.get_chat_member(chat_id=chat_id, user_id=int(user_id))
        except BadRequest as exc:
            logger.info("Cannot resolve user %s in chat %s: %s", user_id, chat_id, exc)
            return None
        except Forbidden as exc:
            logger.error("Bot is not allowed to inspect user %s: %s", user_id, exc)
            return None

    @staticmethod
    def get_chat_member_status(chat_member):
        """Return the Telegram status string for a chat member result."""
        if not chat_member:
            return "not_found"
        return getattr(chat_member, "status", "unknown")

    @staticmethod
    def is_chat_member_in_group(chat_member):
        """Return True when the Telegram member status means the user is in the group."""
        if not chat_member:
            return False

        status = getattr(chat_member, "status", None)
        if status in ACTIVE_CHAT_MEMBER_STATUSES:
            return True
        if status == "restricted":
            return bool(getattr(chat_member, "is_member", False))
        return False

    @staticmethod
    def derive_role_from_chat_member(chat_member):
        """Convert Telegram member status to a role label."""
        status = getattr(chat_member, "status", None)
        if status in {"administrator", "creator"}:
            return "admin"
        if MemberSyncMixin.is_chat_member_in_group(chat_member):
            return "member"
        return "not_in_group"

    @staticmethod
    def format_telegram_username(
        telegram_user,
        fallback_username: str,
        fallback_user_id: str,
    ):
        """Return a normalized username-like display value."""
        if telegram_user and getattr(telegram_user, "username", None):
            return f"@{telegram_user.username}"
        if fallback_username:
            return fallback_username
        return f"User_{fallback_user_id}"
