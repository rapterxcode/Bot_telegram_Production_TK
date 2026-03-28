"""Invite-link related handlers for the Telegram bot."""

import logging
from datetime import datetime, timedelta

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from app.core import config

logger = logging.getLogger(__name__)


class InviteHandlersMixin:
    """Encapsulate invite link commands and helpers."""

    async def invite_link_1month_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Create a 1-month invite link."""
        await self._create_invite_link(
            update,
            context,
            days=config.INVITE_LINK_1MONTH_DAYS,
            period_name="1 เดือน",
            link_type="1month",
        )

    async def invite_link_1year_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Create a 1-year invite link."""
        await self._create_invite_link(
            update,
            context,
            days=config.INVITE_LINK_1YEAR_DAYS,
            period_name="1 ปี",
            link_type="1year",
        )

    async def invite_link_no_expire_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Create a non-expiring membership invite link."""
        await self._create_invite_link(
            update,
            context,
            days=None,
            period_name="ไม่หมดอายุ",
            link_type="noexpire",
        )

    async def invite_link_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Create an invite link with a custom membership duration."""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /invitelink",
            )

        user_id = update.effective_user.id

        if not config.is_admin(user_id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
            )
            return

        if not context.args or len(context.args) < 2:
            help_text = (
                "วิธีใช้งานคำสั่ง /invitelink\n\n"
                "รูปแบบ: /invitelink <จำนวน> <หน่วย>\n\n"
                "หน่วยที่รองรับ:\n"
                "- day หรือ days = วัน\n"
                "- month หรือ months = เดือน\n"
                "- year หรือ years = ปี\n\n"
                "ตัวอย่าง:\n"
                "- /invitelink 7 days\n"
                "- /invitelink 3 months\n"
                "- /invitelink 2 years\n"
                "- /invitelink 15 day\n"
                "- /invitelink 1 year"
            )
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=help_text,
            )
            return

        try:
            amount = int(context.args[0])
            unit = context.args[1].lower()

            if amount <= 0:
                await self.send_safe_message(
                    context=context,
                    user_id=admin_group_id,
                    text="จำนวนต้องมากกว่า 0",
                )
                return

            if unit in ["day", "days"]:
                days = amount
                period_name = f"{amount} วัน"
            elif unit in ["month", "months"]:
                days = amount * 30
                period_name = f"{amount} เดือน"
            elif unit in ["year", "years"]:
                days = amount * 365
                period_name = f"{amount} ปี"
            else:
                await self.send_safe_message(
                    context=context,
                    user_id=admin_group_id,
                    text="หน่วยไม่ถูกต้อง ใช้ได้เฉพาะ days, months, years",
                )
                return

            if days > 3650:
                await self.send_safe_message(
                    context=context,
                    user_id=admin_group_id,
                    text="ระยะเวลาไม่ควรเกิน 10 ปี",
                )
                return

            await self._create_invite_link(
                update,
                context,
                days=days,
                period_name=period_name,
                link_type="custom",
            )

        except ValueError:
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text="จำนวนต้องเป็นตัวเลข ตัวอย่าง: /invitelink 30 days",
            )
        except Exception as exc:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"เกิดข้อผิดพลาด: {exc}",
            )

    async def _create_invite_link(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        days: int = None,
        period_name: str = "",
        link_type: str = "default",
    ):
        """Create an invite link and store its membership metadata."""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="กำลังสร้างลิงก์เชิญสมาชิก",
            )

        user_id = update.effective_user.id

        if not config.is_admin(user_id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
            )
            return

        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
        if not target_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="ไม่พบ Group Chat ID",
            )
            return

        try:
            current_time = datetime.now(pytz.timezone(config.TIMEZONE))

            if days is None:
                expire_date_str = "no_expire"
            else:
                future_expire_date = current_time + timedelta(days=days)
                expire_date_str = future_expire_date.strftime("%Y-%m-%d %H:%M:%S")

            link_expire_time = current_time + timedelta(
                minutes=config.INVITE_LINK_EXPIRE_MINUTES
            )

            admin_user = update.effective_user
            admin_username = (
                f"@{admin_user.username}"
                if admin_user.username
                else f"User_{admin_user.id}"
            )
            link_name = f"Bot Invite for {admin_username} ({period_name})"

            invite_link = await context.bot.create_chat_invite_link(
                chat_id=target_group_id,
                expire_date=int(link_expire_time.timestamp()),
                member_limit=None,
                name=link_name,
                creates_join_request=True,
            )

            link_url = invite_link.invite_link
            self.store_invite_link_metadata(
                link_url,
                {
                    "days": days if days is not None else "no_expire",
                    "type": link_type,
                    "period_name": period_name,
                    "created_time": current_time,
                    "expire_time": link_expire_time,
                },
                {
                    "type": link_type,
                    "days": days if days is not None else "no_expire",
                    "period_name": period_name,
                },
            )

            logger.info(
                "Stored invite link: %s with type: %s, days: %s",
                link_url,
                link_type,
                days,
            )

            self._cleanup_expired_invite_links()

            if days is None:
                message = (
                    f"ลิงก์เชิญสำหรับสมาชิกแบบ {period_name}\n"
                    f"{invite_link.invite_link}\n\n"
                    f"ลิงก์นี้จะหมดอายุใน {config.INVITE_LINK_EXPIRE_MINUTES} นาที\n"
                    "เวลาหมดอายุของลิงก์: "
                    f"{link_expire_time.strftime('%d/%m/%Y %H:%M:%S')} "
                    f"({config.TIMEZONE})\n\n"
                    "ลำดับการทำงาน\n"
                    "1. สมาชิกกดลิงก์และส่งคำขอเข้าร่วมกลุ่ม\n"
                    "2. แอดมินได้รับการแจ้งเตือนพร้อมปุ่มอนุมัติหรือปฏิเสธ\n"
                    "3. หากอนุมัติ ระบบจะเพิ่มเข้ากลุ่มและบันทึกลง Google Sheets\n"
                    "4. หากปฏิเสธ ระบบจะปฏิเสธคำขอเข้ากลุ่ม\n\n"
                    f"ค่าสมาชิกแบบไม่หมดอายุที่ใช้: {config.INVITE_LINK_NOEXPIRE}"
                )
            else:
                message = (
                    f"ลิงก์เชิญสำหรับสมาชิกแบบ {period_name}\n"
                    f"{invite_link.invite_link}\n\n"
                    f"ลิงก์นี้จะหมดอายุใน {config.INVITE_LINK_EXPIRE_MINUTES} นาที\n"
                    "เวลาหมดอายุของลิงก์: "
                    f"{link_expire_time.strftime('%d/%m/%Y %H:%M:%S')} "
                    f"({config.TIMEZONE})\n\n"
                    "ลำดับการทำงาน\n"
                    "1. สมาชิกกดลิงก์และส่งคำขอเข้าร่วมกลุ่ม\n"
                    "2. แอดมินได้รับการแจ้งเตือนพร้อมปุ่มอนุมัติหรือปฏิเสธ\n"
                    "3. หากอนุมัติ ระบบจะเพิ่มเข้ากลุ่มและบันทึกลง Google Sheets\n"
                    "4. หากปฏิเสธ ระบบจะปฏิเสธคำขอเข้ากลุ่ม\n\n"
                    f"ระยะเวลาสมาชิก: {period_name} ({days} วัน)\n"
                    f"วันหมดอายุที่จะถูกบันทึก: {expire_date_str}"
                )

            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=message,
            )

        except Exception as exc:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"ไม่สามารถสร้าง invite link ได้: {exc}",
            )

    def _cleanup_expired_invite_links(self):
        """Remove expired invite-link metadata from memory."""
        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
        expired_links = []

        for link, info in self.invite_link_expires.items():
            if "expire_time" in info and current_time > info["expire_time"]:
                expired_links.append(link)

        for link in expired_links:
            del self.invite_link_expires[link]
            if link in self.active_invite_links:
                del self.active_invite_links[link]
            logger.info("Cleaned up expired invite link: %s", link)

        if expired_links:
            self.save_runtime_state()
            logger.info("Cleaned up %s expired invite links", len(expired_links))
