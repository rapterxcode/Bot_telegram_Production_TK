"""Main Telegram bot orchestrator."""

import asyncio

from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, ContextTypes

from app.bot.application import (
    register_handlers,
    setup_bot_commands as configure_bot_commands,
)
from app.bot.callbacks import ApprovalCallbacksMixin
from app.bot.events import MembershipEventsMixin
from app.bot.invites import InviteHandlersMixin
from app.bot.logging_config import setup_global_logging
from app.bot.member_commands import MemberManagementMixin
from app.bot.notifications import AdminNotifier
from app.bot.reconciliation import MemberSyncMixin
from app.core import config
from app.services.google_sheets import GoogleSheetsManager
from app.services.state_store import BotStateStore


logger = setup_global_logging(__name__)
logger.info("Global logging initialized")

POLLING_ALLOWED_UPDATES = [
    "message",
    "callback_query",
    "chat_member",
    "chat_join_request",
    "my_chat_member",
]


class TelegramMemberBot(
    MemberManagementMixin,
    MemberSyncMixin,
    MembershipEventsMixin,
    InviteHandlersMixin,
    ApprovalCallbacksMixin,
):
    """Coordinate bot state, lifecycle, and shared commands."""

    def __init__(self):
        self.application = None
        self.sheets_manager = GoogleSheetsManager()
        self.group_chat_id = config.GROUP_CHAT_ID if config.GROUP_CHAT_ID != 0 else None
        self.state_store = BotStateStore()

        state_snapshot = self.state_store.load_state()

        self.invite_link_expires = state_snapshot.invite_link_expires
        self.recent_join_type = "default"
        self.active_invite_links = state_snapshot.active_invite_links
        self.pending_members = state_snapshot.pending_members
        self.sent_notifications = state_snapshot.sent_notifications
        self.last_sync_snapshot = state_snapshot.last_sync_snapshot

        self.notifier = AdminNotifier(
            logger=logger,
            pending_members=self.pending_members,
            sent_notifications=self.sent_notifications,
            get_application=lambda: self.application,
            mark_notification_sent=self.mark_notification_sent,
        )
        self._cleanup_expired_invite_links()

    def save_runtime_state(self):
        """Persist runtime state that must survive restarts."""
        try:
            self.state_store.save_state(
                invite_link_expires=self.invite_link_expires,
                active_invite_links=self.active_invite_links,
                pending_members=self.pending_members,
                sent_notifications=self.sent_notifications,
                last_sync_snapshot=self.last_sync_snapshot,
            )
        except Exception as exc:
            logger.error("Failed to persist runtime state: %s", exc)

    def store_pending_member(self, user_id: str, member_info: dict):
        """Store or replace a pending member record."""
        self.pending_members[user_id] = member_info
        self.save_runtime_state()

    def discard_pending_member(self, user_id: str):
        """Remove a pending member record when it exists."""
        removed_member = self.pending_members.pop(user_id, None)
        if removed_member is not None:
            self.save_runtime_state()
        return removed_member

    def mark_notification_sent(self, notification_key: str):
        """Track a notification key to avoid duplicate admin prompts."""
        if notification_key not in self.sent_notifications:
            self.sent_notifications.add(notification_key)
            self.save_runtime_state()

    def clear_notification_sent(self, notification_key: str):
        """Clear a notification key so a prompt can be re-sent if needed."""
        if notification_key in self.sent_notifications:
            self.sent_notifications.remove(notification_key)
            self.save_runtime_state()

    def store_last_sync_snapshot(self, snapshot: dict):
        """Persist the latest sync snapshot for faster status checks."""
        self.last_sync_snapshot = dict(snapshot)
        self.save_runtime_state()

    def store_invite_link_metadata(
        self,
        invite_link: str,
        invite_link_expire_info: dict,
        active_link_info: dict,
    ):
        """Store invite-link metadata used by join-request approval flows."""
        self.invite_link_expires[invite_link] = invite_link_expire_info
        self.active_invite_links[invite_link] = active_link_info
        self.save_runtime_state()

    def is_join_request_pending(self, member_info: dict) -> bool:
        """Return True when a pending member originated from a join request."""
        return (
            member_info.get("approval_mode") == "join_request"
            or member_info.get("chat_id") is not None
            or member_info.get("join_request") is not None
        )

    def build_pending_callback_data(
        self,
        action: str,
        member_user_id: str,
        member_info: dict,
    ) -> str:
        """Build callback data that preserves whether the item is a join request."""
        if self.is_join_request_pending(member_info):
            return f"{action}_join_{member_user_id}"
        return f"{action}_{member_user_id}"

    def reschedule_expired_member_job(self, interval_seconds: int) -> bool:
        """Create or replace the repeating job that removes expired members."""
        if not self.application or not self.application.job_queue:
            logger.warning("Job queue is not available, cannot schedule expiry checks")
            return False

        existing_jobs = self.application.job_queue.get_jobs_by_name(
            "check_expired_members"
        )
        for job in existing_jobs:
            job.schedule_removal()

        self.application.job_queue.run_repeating(
            self.check_expired_members,
            interval=interval_seconds,
            first=10,
            name="check_expired_members",
        )
        logger.info(
            "Job queue configured for every %s %s",
            config.CHECK_INTERVAL_VALUE,
            config.CHECK_INTERVAL_UNIT,
        )
        return True

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start."""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /start",
            )

        if update.effective_chat.type == "private":
            start_param = context.args[0] if context.args else None

            if config.is_admin(update.effective_user.id):
                if start_param == "admin":
                    await update.message.reply_text(
                        "พร้อมใช้งานแล้ว\n\n"
                        "ยินดีต้อนรับผู้ดูแลระบบ\n"
                        "บอทเชื่อมต่อกับระบบเรียบร้อย และพร้อมช่วยจัดการสมาชิกในกลุ่ม\n\n"
                        f"กลุ่มเป้าหมาย: {config.GROUP_CHAT_ID}\n"
                        f"Google Sheet: {config.WORKSHEET_NAME}\n"
                        f"จำนวนแอดมินที่ตั้งค่าไว้: {len(config.get_admin_list())} คน\n\n"
                        "พิมพ์ /help เพื่อดูคำสั่งทั้งหมด"
                    )
                else:
                    await update.message.reply_text(
                        "บอทพร้อมใช้งานแล้ว\n"
                        f"กลุ่มเป้าหมาย: {config.GROUP_CHAT_ID}\n"
                        "คุณสามารถเริ่มใช้งานคำสั่งสำหรับดูแลสมาชิกได้ทันที"
                    )
            else:
                await update.message.reply_text(
                    "สวัสดีครับ\n"
                    "บอทนี้ใช้สำหรับจัดการสมาชิกกลุ่ม\n"
                    "คำสั่งส่วนใหญ่สงวนไว้สำหรับผู้ดูแลระบบ"
                )
            return

        if not self.group_chat_id:
            self.group_chat_id = update.effective_chat.id

        await update.message.reply_text(
            "บอทพร้อมใช้งานแล้ว\n"
            "ระบบนี้ช่วยจัดการสมาชิกในกลุ่ม ตรวจสอบสมาชิกหมดอายุ "
            "และช่วยให้แอดมินดูแลข้อมูลได้สะดวกขึ้น\n\n"
            "หากคุณเป็นแอดมิน พิมพ์ /help เพื่อดูคำสั่งทั้งหมด"
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status."""
        del update
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /status",
            )

        try:
            snapshot = {}
            if config.STATUS_USE_CACHED_SNAPSHOT:
                snapshot = self.build_cached_status_snapshot()

            if not snapshot:
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
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=f"ตรวจสอบสถานะไม่สำเร็จ: {exc}",
            )

    async def check_now_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /checknow."""
        del update
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /checknow",
            )

        try:
            await self.check_expired_members(context)
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text="ตรวจสอบสมาชิกหมดอายุเรียบร้อยแล้ว",
            )
        except Exception as exc:
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=f"เกิดข้อผิดพลาดระหว่างตรวจสอบสมาชิก: {exc}",
            )

    async def list_expired_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /listexpired."""
        del update
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /listexpired",
            )

        try:
            expired_members = self.sheets_manager.get_expired_members()

            if not expired_members:
                await self.send_safe_message(
                    context=context,
                    user_id=admin_group_id,
                    text="ไม่พบสมาชิกที่หมดอายุในขณะนี้",
                )
                return

            message = "รายชื่อสมาชิกที่หมดอายุ\n\n"
            for index, member in enumerate(expired_members, 1):
                username = member.get("Username", "Unknown")
                user_id_member = member.get("User ID", "Unknown")
                expire_date = member.get("Expiredate", "Unknown")
                message += (
                    f"{index}. {username}\n"
                    f"   User ID: {user_id_member}\n"
                    f"   วันหมดอายุ: {expire_date}\n\n"
                )

            if len(message) > 4000:
                message = message[:4000] + "\n\nรายการยาวเกินไป จึงแสดงเพียงบางส่วน"

            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=message,
            )
        except Exception as exc:
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=f"เกิดข้อผิดพลาด: {exc}",
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help."""
        del context
        if config.is_admin(update.effective_user.id):
            help_text = (
                "คู่มือคำสั่งสำหรับแอดมิน\n\n"
                "คำสั่งทั่วไป\n"
                "/start - เริ่มต้นใช้งานบอท\n"
                "/help - แสดงคู่มือคำสั่ง\n"
                "/status - ดูสถานะล่าสุดจาก snapshot\n"
                "/statuslive - ตรวจสอบสถานะสดจาก Telegram\n\n"
                "คำสั่งจัดการสมาชิก\n"
                "/addmember @username user_id expire_date\n"
                "/removemember user_id\n"
                "/updateexpire user_id YYYY-MM-DD HH:MM:SS\n"
                "/listmembers [page]\n"
                "/pendingmembers\n"
                "/listexpired\n\n"
                "คำสั่งดูแลระบบ\n"
                "/checknow\n"
                "/syncmembers\n"
                "/fullsyncmembers\n"
                "/setcheckinterval 30 minutes\n"
                "/invitelink 30 days\n"
                "/invitelink1month\n"
                "/invitelink1year\n"
                "/invitelinknoexpire\n"
                "/listadmins\n\n"
                f"กลุ่มเป้าหมาย: {config.GROUP_CHAT_ID}\n"
                f"Google Sheet: {config.WORKSHEET_NAME}\n"
                f"จำนวนแอดมินที่ตั้งค่าไว้: {len(config.get_admin_list())} คน"
            )
        else:
            help_text = (
                "คู่มือการใช้งานบอท\n\n"
                "คำสั่งที่ใช้งานได้\n"
                "/start - เริ่มต้นใช้งาน\n"
                "/help - ดูคำอธิบายการใช้งาน\n\n"
                "บอทนี้ใช้สำหรับช่วยดูแลสมาชิกในกลุ่ม เช่น\n"
                "- ตรวจสอบสมาชิกหมดอายุ\n"
                "- อัปเดตข้อมูลสมาชิกใน Google Sheet\n"
                "- รองรับการอนุมัติสมาชิกโดยผู้ดูแลระบบ"
            )

        await update.message.reply_text(help_text)

    async def send_safe_message(
        self,
        context,
        user_id: int,
        text: str,
        parse_mode: str = None,
        fallback_to_admin_group: bool = True,
    ):
        return await self.notifier.send_safe_message(
            context=context,
            user_id=user_id,
            text=text,
            parse_mode=parse_mode,
            fallback_to_admin_group=fallback_to_admin_group,
        )

    async def notify_all_admins(self, message: str, parse_mode: str = None):
        await self.notifier.notify_all_admins(message=message, parse_mode=parse_mode)

    async def notify_all_admins_with_buttons(
        self,
        context,
        user_id: str,
        username: str,
        first_name: str,
        last_name: str,
        expire_date_str: str,
    ):
        await self.notifier.notify_all_admins_with_buttons(
            context=context,
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            expire_date_str=expire_date_str,
        )

    async def notify_all_admins_with_join_request_buttons(
        self,
        context,
        user_id: str,
        username: str,
        first_name: str,
        last_name: str,
        expire_date_str: str,
    ):
        await self.notifier.notify_all_admins_with_join_request_buttons(
            context=context,
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            expire_date_str=expire_date_str,
        )

    async def notify_admin_new_member(
        self,
        username: str,
        user_id: str,
        expire_date: str,
        member_type: str = "ไม่ระบุ",
    ):
        await self.notifier.notify_admin_new_member(
            username=username,
            user_id=user_id,
            expire_date=expire_date,
            member_type=member_type,
        )

    async def check_expired_members(self, context: ContextTypes.DEFAULT_TYPE):
        """Remove expired members from Telegram and Sheets."""
        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if not target_group_id:
            logger.warning("Group chat ID not set, cannot remove expired members")
            return

        try:
            expired_members = self.sheets_manager.get_expired_members()
            if not expired_members:
                logger.info("No expired members found")
                return

            logger.info("Found %s expired members", len(expired_members))

            for member in expired_members:
                user_id = member.get("User ID")
                expire_date = member.get("Expiredate", "")

                if expire_date in {"no_expire", config.INVITE_LINK_NOEXPIRE}:
                    logger.info("Skipping user %s (no expire: %s)", user_id, expire_date)
                    continue

                username = member.get("Username", "Unknown")
                if not user_id:
                    continue

                try:
                    await context.bot.ban_chat_member(
                        chat_id=target_group_id,
                        user_id=int(user_id),
                    )
                    await context.bot.unban_chat_member(
                        chat_id=target_group_id,
                        user_id=int(user_id),
                    )
                    self.sheets_manager.remove_member_from_sheet(
                        user_id,
                        remove_reason="Membership expired",
                        actor="system",
                        source="expired_member_cleanup",
                        note="Automatically removed because membership expired",
                    )

                    logger.info("Removed expired member: %s (ID: %s)", username, user_id)

                    if admin_group_id:
                        await context.bot.send_message(
                            chat_id=admin_group_id,
                            text=f"ลบสมาชิก {username} ออกจากกลุ่มเนื่องจากหมดอายุแล้ว",
                        )

                    try:
                        await self.notify_all_admins(
                            f"ลบสมาชิกหมดอายุแล้ว: {username} (ID: {user_id})"
                        )
                    except Exception as admin_notify_error:
                        logger.error("Cannot notify admin: %s", admin_notify_error)

                    await asyncio.sleep(1)
                except Forbidden:
                    logger.error("Bot doesn't have permission to remove user %s", user_id)
                except BadRequest as exc:
                    if "User not found" in str(exc):
                        logger.info("User %s already left the group", user_id)
                        self.sheets_manager.remove_member_from_sheet(
                            user_id,
                            remove_reason="User already left group before expiry cleanup",
                            actor="system",
                            source="expired_member_cleanup",
                            note="Marked removed during expiry cleanup because user was already absent",
                        )
                    else:
                        logger.error("Error removing user %s: %s", user_id, exc)
                except Exception as exc:
                    logger.error("Unexpected error removing user %s: %s", user_id, exc)
        except Exception as exc:
            logger.error("Error in check_expired_members: %s", exc)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error("Update %s caused error %s", update, context.error)

    async def setup_handlers(self):
        if not self.application:
            return
        register_handlers(self.application, self)
        await self.setup_bot_commands()

    async def setup_bot_commands(self):
        await configure_bot_commands(self.application, logger)

    async def _setup_job_queue(self, job_queue, interval_seconds):
        del job_queue
        try:
            self.reschedule_expired_member_job(interval_seconds)
        except Exception as exc:
            logger.error("Error setting up job queue: %s", exc)

    async def run(self):
        """Start the Telegram bot."""
        if not config.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
            return

        try:
            self.application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
            await self.setup_handlers()
            await self._setup_job_queue(
                self.application.job_queue,
                config.get_check_interval_seconds(),
            )

            logger.info("Starting Telegram Member Management Bot")

            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                allowed_updates=POLLING_ALLOWED_UPDATES,
                drop_pending_updates=True,
            )

            stop_event = asyncio.Event()
            try:
                await stop_event.wait()
            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
            finally:
                await self.stop()
        except Exception as exc:
            logger.error("Error in run method: %s", exc)
            if self.application:
                try:
                    await self.stop()
                except Exception as shutdown_error:
                    logger.error("Error during shutdown: %s", shutdown_error)
            raise

    async def stop(self):
        """Stop the Telegram bot."""
        if not self.application:
            return

        try:
            if self.application.updater:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Bot stopped")
        except Exception as exc:
            logger.error("Error stopping bot: %s", exc)


if __name__ == "__main__":
    bot = TelegramMemberBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as exc:
        logger.error("Bot crashed: %s", exc)
