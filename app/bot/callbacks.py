"""Approval callback handlers for the Telegram bot."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.core import config


logger = logging.getLogger(__name__)


class ApprovalCallbacksMixin:
    """Encapsulate admin callback flows for approval and rejection."""

    async def handle_approval_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Handle approve/reject callback actions."""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        if not config.is_admin(user_id):
            await query.edit_message_text("คุณไม่มีสิทธิ์ใช้งานฟังก์ชันนี้")
            return

        if query.data == "pending_list":
            await self.show_pending_list_callback(update, context)
            return

        action, member_user_id, is_join_request = self._parse_callback_data(query.data)
        if member_user_id not in self.pending_members:
            await query.edit_message_text("ไม่พบข้อมูลสมาชิกรออนุมัติ")
            return

        member_info = self.pending_members[member_user_id]
        username = member_info["username"]
        first_name = member_info["first_name"]
        last_name = member_info["last_name"]
        expire_date_str = member_info["expire_date_str"]

        if action == "approve":
            if is_join_request:
                await self._approve_join_request(
                    query=query,
                    context=context,
                    member_user_id=member_user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    expire_date_str=expire_date_str,
                    member_info=member_info,
                )
            else:
                await self._approve_member_update(
                    query=query,
                    member_user_id=member_user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    expire_date_str=expire_date_str,
                )
            return

        if action == "reject":
            if is_join_request:
                await self._reject_join_request(
                    query=query,
                    context=context,
                    member_user_id=member_user_id,
                    username=username,
                    member_info=member_info,
                )
            else:
                await self._reject_member_update(
                    query=query,
                    context=context,
                    member_user_id=member_user_id,
                    username=username,
                )

    async def _approve_join_request(
        self,
        *,
        query,
        context,
        member_user_id: str,
        username: str,
        first_name: str,
        last_name: str,
        expire_date_str: str,
        member_info: dict,
    ):
        chat_id = self._get_pending_chat_id(member_info)
        if chat_id is None:
            await query.edit_message_text("ไม่พบข้อมูลคำขอเข้าร่วมกลุ่ม")
            return

        try:
            await context.bot.approve_chat_join_request(
                chat_id=chat_id,
                user_id=int(member_user_id),
            )

            success = self.sheets_manager.add_member_with_details(
                username,
                member_user_id,
                expire_date_str,
                first_name,
                last_name,
            )

            if success:
                self.discard_pending_member(member_user_id)
                self.clear_notification_sent(f"join_request_{member_user_id}")

                await query.edit_message_text(
                    "อนุมัติคำขอเข้าร่วมสำเร็จ\n\n"
                    f"Username: {username}\n"
                    f"User ID: {member_user_id}\n"
                    f"วันหมดอายุ: {expire_date_str}\n"
                    "เพิ่มเข้ากลุ่มและบันทึกลง Google Sheets เรียบร้อยแล้ว\n\n"
                    f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
                )
                logger.info("Join request approved: %s (ID: %s)", username, member_user_id)
                return

            await query.edit_message_text(
                "อนุมัติเข้ากลุ่มแล้ว แต่บันทึกข้อมูลไม่สำเร็จ\n\n"
                f"Username: {username}\n"
                "อนุญาตเข้ากลุ่มสำเร็จแล้ว\n"
                "แต่ไม่สามารถเพิ่มลง Google Sheets ได้\n"
                "กรุณาเพิ่มข้อมูลด้วยตนเองหรือลองใหม่อีกครั้ง"
            )
        except Exception as approve_error:
            logger.error(
                "Error approving join request for %s: %s",
                member_user_id,
                approve_error,
            )
            self.clear_notification_sent(f"join_request_{member_user_id}")

            await query.edit_message_text(
                "เกิดข้อผิดพลาด\n\n"
                f"Username: {username}\n"
                "ไม่สามารถอนุมัติคำขอเข้าร่วมได้\n"
                f"รายละเอียด: {approve_error}"
            )

    async def _approve_member_update(
        self,
        *,
        query,
        member_user_id: str,
        username: str,
        first_name: str,
        last_name: str,
        expire_date_str: str,
    ):
        success = self.sheets_manager.add_member_with_details(
            username,
            member_user_id,
            expire_date_str,
            first_name,
            last_name,
        )

        if success:
            self.discard_pending_member(member_user_id)
            self.clear_notification_sent(f"member_update_{member_user_id}")

            await query.edit_message_text(
                "อนุมัติสมาชิกสำเร็จ\n\n"
                f"Username: {username}\n"
                f"User ID: {member_user_id}\n"
                f"วันหมดอายุ: {expire_date_str}\n\n"
                f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
            )
            logger.info("Member approved: %s (ID: %s)", username, member_user_id)
            return

        self.clear_notification_sent(f"member_update_{member_user_id}")
        await query.edit_message_text(
            "เกิดข้อผิดพลาด\n\n"
            f"ไม่สามารถเพิ่มสมาชิก {username} ลง Google Sheets ได้\n"
            "กรุณาลองใหม่อีกครั้ง"
        )

    async def _reject_join_request(
        self,
        *,
        query,
        context,
        member_user_id: str,
        username: str,
        member_info: dict,
    ):
        chat_id = self._get_pending_chat_id(member_info)
        if chat_id is None:
            await query.edit_message_text("ไม่พบข้อมูลคำขอเข้าร่วมกลุ่ม")
            return

        try:
            await context.bot.decline_chat_join_request(
                chat_id=chat_id,
                user_id=int(member_user_id),
            )
            await context.bot.unban_chat_member(
                chat_id=chat_id,
                user_id=int(member_user_id),
            )

            self.discard_pending_member(member_user_id)
            self.clear_notification_sent(f"join_request_{member_user_id}")

            await query.edit_message_text(
                "ปฏิเสธคำขอเข้าร่วมสำเร็จ\n\n"
                f"Username: {username}\n"
                f"User ID: {member_user_id}\n"
                "ปฏิเสธคำขอเข้ากลุ่มเรียบร้อยแล้ว\n\n"
                f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
            )
            logger.info("Join request declined: %s (ID: %s)", username, member_user_id)
        except Exception as decline_error:
            logger.error(
                "Error declining join request for %s: %s",
                member_user_id,
                decline_error,
            )
            self.clear_notification_sent(f"join_request_{member_user_id}")

            await query.edit_message_text(
                "เกิดข้อผิดพลาด\n\n"
                f"Username: {username}\n"
                "ไม่สามารถปฏิเสธคำขอเข้าร่วมได้\n"
                f"รายละเอียด: {decline_error}"
            )

    async def _reject_member_update(
        self,
        *,
        query,
        context,
        member_user_id: str,
        username: str,
    ):
        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID

        try:
            bot_member = await context.bot.get_chat_member(
                target_group_id,
                context.bot.id,
            )
            if bot_member.status not in ["administrator", "creator"]:
                await query.edit_message_text(
                    "ไม่สามารถปฏิเสธสมาชิกได้\n\n"
                    f"Username: {username}\n"
                    "บอทยังไม่มีสิทธิ์แอดมินในกลุ่ม\n"
                    "กรุณาให้สิทธิ์แอดมินแก่บอทก่อนเพื่อให้ระบบนำสมาชิกออกได้"
                )
                return

            await context.bot.ban_chat_member(
                chat_id=target_group_id,
                user_id=int(member_user_id),
            )
            await context.bot.unban_chat_member(
                chat_id=target_group_id,
                user_id=int(member_user_id),
            )

            self.discard_pending_member(member_user_id)
            self.clear_notification_sent(f"member_update_{member_user_id}")

            await query.edit_message_text(
                "ปฏิเสธสมาชิกสำเร็จ\n\n"
                f"Username: {username}\n"
                f"User ID: {member_user_id}\n"
                "นำสมาชิกออกจากกลุ่มเรียบร้อยแล้ว\n\n"
                f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
            )
            logger.info("Member rejected and kicked: %s (ID: %s)", username, member_user_id)
        except Exception as kick_error:
            logger.error("Error kicking member %s: %s", member_user_id, kick_error)
            self.discard_pending_member(member_user_id)
            self.clear_notification_sent(f"member_update_{member_user_id}")

            await query.edit_message_text(
                "ปฏิเสธสมาชิกบางส่วนสำเร็จ\n\n"
                f"Username: {username}\n"
                f"User ID: {member_user_id}\n"
                "ไม่สามารถนำสมาชิกออกจากกลุ่มได้\n"
                "กรุณาตรวจสอบและนำออกด้วยตนเองหากจำเป็น\n\n"
                f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
            )

    async def show_pending_list_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Show the current list of pending members."""
        del context
        query = update.callback_query

        if not self.pending_members:
            await query.edit_message_text(
                "รายการรออนุมัติ\n\nไม่มีสมาชิกที่รออนุมัติในขณะนี้"
            )
            return

        message = "รายการสมาชิกรออนุมัติ\n\n"

        for user_id, member_info in self.pending_members.items():
            username = member_info["username"]
            timestamp = member_info["timestamp"]
            expire_date = member_info["expire_date_str"]

            message += (
                f"Username: {username}\n"
                f"User ID: {user_id}\n"
                f"เวลา: {timestamp} ({config.TIMEZONE})\n"
                f"วันหมดอายุ: {expire_date}\n"
                "--------------------\n"
            )

        keyboard = self._build_pending_keyboard()
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    @staticmethod
    def _parse_callback_data(callback_data: str):
        if "join_" in callback_data:
            action_parts = callback_data.split("_")
            return action_parts[0], action_parts[2], True
        action, member_user_id = callback_data.split("_", 1)
        return action, member_user_id, False

    @staticmethod
    def _get_pending_chat_id(member_info: dict):
        chat_id = member_info.get("chat_id")
        if chat_id is not None:
            return chat_id

        join_request = member_info.get("join_request")
        if join_request:
            return join_request.chat.id

        return None

    def _build_pending_keyboard(self):
        keyboard = []
        for user_id, member_info in self.pending_members.items():
            username = member_info["username"]
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"อนุมัติ {username}",
                        callback_data=self.build_pending_callback_data(
                            "approve",
                            user_id,
                            member_info,
                        ),
                    ),
                    InlineKeyboardButton(
                        f"ปฏิเสธ {username}",
                        callback_data=self.build_pending_callback_data(
                            "reject",
                            user_id,
                            member_info,
                        ),
                    ),
                ]
            )
        return keyboard
