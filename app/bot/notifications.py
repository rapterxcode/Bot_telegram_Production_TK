"""Admin notification helpers for the Telegram bot."""

from typing import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core import config


class AdminNotifier:
    """Send admin notifications while sharing mutable bot state."""

    def __init__(
        self,
        logger,
        pending_members,
        sent_notifications,
        get_application: Callable[[], object],
        mark_notification_sent: Callable[[str], None],
    ):
        self.logger = logger
        self.pending_members = pending_members
        self.sent_notifications = sent_notifications
        self.get_application = get_application
        self.mark_notification_sent = mark_notification_sent

    async def send_safe_message(
        self,
        context,
        user_id: int,
        text: str,
        parse_mode: str = None,
        fallback_to_admin_group: bool = True,
    ):
        """Send messages to the admin group."""
        del user_id, fallback_to_admin_group

        try:
            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
            if admin_group_id:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=text,
                    parse_mode=parse_mode,
                )
                return True

            self.logger.error("GROUP_CHAT_ID_FOR_ADMIN not configured")
            return False
        except Exception as exc:
            self.logger.error("Cannot send message to admin group: %s", exc)
            return False

    async def notify_all_admins(self, message: str, parse_mode: str = None):
        """Send a message to the configured admin group."""
        application = self.get_application()
        if not application:
            self.logger.error("Application not initialized for admin notification")
            return

        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if not admin_group_id:
            self.logger.error("GROUP_CHAT_ID_FOR_ADMIN not configured")
            return

        try:
            await application.bot.send_message(
                chat_id=admin_group_id,
                text=message,
                parse_mode=parse_mode,
            )
            self.logger.info("Notification sent to admin group")
        except Exception as exc:
            self.logger.error("Cannot send message to admin group: %s", exc)

    async def notify_all_admins_with_buttons(
        self,
        context,
        user_id: str,
        username: str,
        first_name: str,
        last_name: str,
        expire_date_str: str,
    ):
        """Send an approval prompt for members added through member updates."""
        try:
            if user_id not in self.pending_members:
                self.logger.warning(
                    "User %s not found in pending_members, skipping notification",
                    user_id,
                )
                return

            notification_key = f"member_update_{user_id}"
            if notification_key in self.sent_notifications:
                self.logger.info(
                    "Notification for user %s already sent, skipping duplicate",
                    user_id,
                )
                return

            keyboard = [
                [
                    InlineKeyboardButton("อนุมัติ", callback_data=f"approve_{user_id}"),
                    InlineKeyboardButton("ปฏิเสธ", callback_data=f"reject_{user_id}"),
                ],
                [
                    InlineKeyboardButton(
                        "ดูรายการรออนุมัติ",
                        callback_data="pending_list",
                    )
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            member_display_name = f"{first_name} {last_name}".strip() or username
            message = (
                "มีสมาชิกใหม่รออนุมัติ\n\n"
                f"ชื่อ: {member_display_name}\n"
                f"Username: {username}\n"
                f"User ID: {user_id}\n"
                f"วันหมดอายุ: {expire_date_str}\n\n"
                "กดปุ่มด้านล่างเพื่อดำเนินการ\n"
                "อนุมัติ: เพิ่มลง Google Sheets\n"
                "ปฏิเสธ: นำออกจากกลุ่มทันที"
            )

            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
            if admin_group_id:
                try:
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=message,
                        reply_markup=reply_markup,
                    )
                    self.mark_notification_sent(notification_key)
                    self.logger.info(
                        "Notification sent to admin group for user %s (member update)",
                        user_id,
                    )
                except Exception as group_error:
                    self.logger.error(
                        "Cannot send message to admin group: %s",
                        group_error,
                    )
            else:
                self.logger.error("GROUP_CHAT_ID_FOR_ADMIN not configured")

        except Exception as exc:
            self.logger.error("Error in notify_all_admins_with_buttons: %s", exc)

    async def notify_all_admins_with_join_request_buttons(
        self,
        context,
        user_id: str,
        username: str,
        first_name: str,
        last_name: str,
        expire_date_str: str,
    ):
        """Send an approval prompt for join requests."""
        self.logger.info("Starting notification process for user %s", user_id)

        try:
            if user_id not in self.pending_members:
                self.logger.warning(
                    "User %s not found in pending_members, skipping notification",
                    user_id,
                )
                return

            notification_key = f"join_request_{user_id}"
            if notification_key in self.sent_notifications:
                self.logger.info(
                    "Notification for user %s already sent, skipping duplicate",
                    user_id,
                )
                return

            keyboard = [
                [
                    InlineKeyboardButton(
                        "อนุมัติ",
                        callback_data=f"approve_join_{user_id}",
                    ),
                    InlineKeyboardButton(
                        "ปฏิเสธ",
                        callback_data=f"reject_join_{user_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "ดูรายการรออนุมัติ",
                        callback_data="pending_list",
                    )
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            member_display_name = f"{first_name} {last_name}".strip() or username
            message = (
                "มีคำขอเข้าร่วมกลุ่มใหม่\n\n"
                f"ชื่อ: {member_display_name}\n"
                f"Username: {username}\n"
                f"User ID: {user_id}\n"
                f"วันหมดอายุ: {expire_date_str}\n\n"
                "กดปุ่มด้านล่างเพื่อดำเนินการ\n"
                "อนุมัติ: อนุญาตเข้ากลุ่มและเพิ่มลง Google Sheets\n"
                "ปฏิเสธ: ปฏิเสธคำขอเข้ากลุ่ม"
            )

            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
            self.logger.info("Admin group ID: %s", admin_group_id)

            if admin_group_id:
                try:
                    self.logger.info(
                        "Attempting to send message to admin group %s",
                        admin_group_id,
                    )
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=message,
                        reply_markup=reply_markup,
                    )
                    self.mark_notification_sent(notification_key)
                    self.logger.info(
                        "Notification sent to admin group for user %s (join request)",
                        user_id,
                    )
                except Exception as group_error:
                    self.logger.error(
                        "Cannot send message to admin group: %s",
                        group_error,
                    )
            else:
                self.logger.error("GROUP_CHAT_ID_FOR_ADMIN not configured")

        except Exception as exc:
            self.logger.error(
                "Error in notify_all_admins_with_join_request_buttons: %s",
                exc,
            )

    async def notify_admin_new_member(
        self,
        username: str,
        user_id: str,
        expire_date: str,
        member_type: str = "ไม่ระบุ",
    ):
        """Notify admins when a new member is accepted."""
        try:
            message = (
                "มีสมาชิกใหม่เข้าร่วมกลุ่ม\n\n"
                f"Username: {username}\n"
                f"User ID: {user_id}\n"
                f"ประเภท: {member_type}\n"
                f"วันหมดอายุ: {expire_date}\n\n"
                "ระบบตั้งค่าจาก invite link ที่ใช้งานล่าสุดให้แล้ว"
            )
            await self.notify_all_admins(message)
        except Exception as exc:
            self.logger.error("Error notifying admin: %s", exc)
