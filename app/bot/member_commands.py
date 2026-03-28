"""Member and admin command handlers for the Telegram bot."""

import logging
from datetime import datetime

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from app.core import config

logger = logging.getLogger(__name__)

UNIT_DISPLAY = {
    "seconds": "วินาที",
    "minutes": "นาที",
    "hours": "ชั่วโมง",
    "days": "วัน",
}


class MemberManagementMixin:
    """Encapsulate member-management and admin utility commands."""

    @staticmethod
    def _format_actor_label(actor_user) -> str:
        """Build a compact actor label for audit fields."""
        if not actor_user:
            return ""
        if getattr(actor_user, "username", None):
            return f"@{actor_user.username}"
        full_name = " ".join(
            part for part in [actor_user.first_name, actor_user.last_name] if part
        ).strip()
        return full_name or f"user_{actor_user.id}"

    async def add_member_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /addmember",
            )

        if not config.is_admin(update.effective_user.id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
            )
            return

        if len(context.args) < 3:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=(
                    "รูปแบบคำสั่ง:\n"
                    "/addmember @username user_id expire_date\n\n"
                    "ตัวอย่าง:\n"
                    "/addmember @john_doe 123456789 2024-12-31 23:59:59"
                ),
            )
            return

        try:
            username = context.args[0]
            member_user_id = context.args[1]
            expire_date = " ".join(context.args[2:])
            actor_label = self._format_actor_label(update.effective_user)

            if not username.startswith("@"):
                username = f"@{username}"

            try:
                datetime.strptime(expire_date, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=(
                        "รูปแบบวันที่ไม่ถูกต้อง\n"
                        "กรุณาใช้รูปแบบ: YYYY-MM-DD HH:MM:SS\n"
                        "ตัวอย่าง: 2024-12-31 23:59:59"
                    ),
                )
                return

            target_group_id = config.GROUP_CHAT_ID

            try:
                await context.bot.unban_chat_member(
                    chat_id=target_group_id,
                    user_id=int(member_user_id),
                    only_if_banned=True,
                )

                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=target_group_id,
                    member_limit=1,
                    creates_join_request=False,
                )

                await context.bot.send_message(
                    chat_id=int(member_user_id),
                    text=(
                        "คุณได้รับการอนุมัติให้เข้าร่วมกลุ่มแล้ว\n"
                        f"วันหมดอายุสมาชิก: {expire_date}\n"
                        f"ลิงก์เข้ากลุ่ม: {invite_link.invite_link}\n"
                        "กรุณาปฏิบัติตามกติกาของกลุ่ม"
                    ),
                )
            except Exception as exc:
                logger.error("Error adding member to Telegram group: %s", exc)
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=(
                        "ไม่สามารถเพิ่มสมาชิกเข้ากลุ่มได้: "
                        f"{exc}\n"
                        "กรุณาตรวจสอบว่าบอทมีสิทธิ์แอดมินและสามารถเชิญสมาชิกได้"
                    ),
                )
                return

            success = self.sheets_manager.add_member_with_details(
                username,
                member_user_id,
                expire_date,
                metadata={
                    "Record Status": "invited",
                    "In Group Now": "No",
                    "Join Source": "admin_invite",
                    "Invite Link Label": "manual_admin_invite",
                    "Added By": actor_label,
                    "Last Sync Result": "invite_sent",
                    "Sync Note": "Manual invite link was created and sent by admin",
                    "Sync Source": "manual_addmember",
                },
            )

            if success:
                self.sheets_manager.append_audit_log(
                    user_id=member_user_id,
                    username=username,
                    action="member_invited",
                    new_value={
                        "Username": username,
                        "User ID": member_user_id,
                        "Expiredate": expire_date,
                    },
                    actor=actor_label,
                    source="manual_addmember",
                    note="Admin created a one-time invite link for a member",
                )
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=(
                        "เพิ่มสมาชิกสำเร็จ\n"
                        f"Username: {username}\n"
                        f"User ID: {member_user_id}\n"
                        f"วันหมดอายุ: {expire_date}\n"
                        "ระบบได้ส่งลิงก์เชิญและบันทึกข้อมูลลง Google Sheet แล้ว"
                    ),
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="ส่งลิงก์เชิญสำเร็จ แต่ไม่สามารถบันทึกข้อมูลใน Google Sheet ได้",
                )
        except Exception as exc:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"เกิดข้อผิดพลาด: {exc}",
            )

    async def remove_member_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /removemember",
            )

        if not config.is_admin(update.effective_user.id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
            )
            return

        if len(context.args) != 1:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=(
                    "รูปแบบคำสั่ง:\n"
                    "/removemember user_id\n\n"
                    "ตัวอย่าง:\n"
                    "/removemember 123456789"
                ),
            )
            return

        try:
            member_user_id = context.args[0]
            target_group_id = self.group_chat_id or config.GROUP_CHAT_ID

            if not target_group_id:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="ไม่พบ Group Chat ID",
                )
                return

            members = self.sheets_manager.get_all_members(include_inactive=True)
            member_info = None
            for member in members:
                if member.get("User ID") == member_user_id:
                    member_info = member
                    break

            if not member_info:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"ไม่พบสมาชิก User ID: {member_user_id} ใน Google Sheet",
                )
                return

            username = member_info.get("Username", "Unknown")

            try:
                await context.bot.ban_chat_member(
                    chat_id=target_group_id,
                    user_id=int(member_user_id),
                )
                await context.bot.unban_chat_member(
                    chat_id=target_group_id,
                    user_id=int(member_user_id),
                )

                actor_label = self._format_actor_label(update.effective_user)
                sheet_success = self.sheets_manager.remove_member_from_sheet(
                    member_user_id,
                    remove_reason="Removed manually by admin",
                    actor=actor_label,
                    source="manual_remove_command",
                    note="Removed through /removemember",
                )

                if sheet_success:
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=(
                            "ลบสมาชิกสำเร็จ\n"
                            f"Username: {username}\n"
                            f"User ID: {member_user_id}\n"
                            "นำออกจากกลุ่มและลบออกจาก Google Sheet แล้ว"
                        ),
                    )
                    try:
                        await context.bot.send_message(
                            chat_id=admin_group_id,
                            text=f"สมาชิก {username} ถูกนำออกจากกลุ่มโดยแอดมิน",
                        )
                    except Exception as notify_error:
                        logger.error("Cannot send notification to group: %s", notify_error)
                else:
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=(
                            "นำออกจากกลุ่มสำเร็จ แต่ลบข้อมูลจาก Google Sheet ไม่สำเร็จ\n"
                            f"Username: {username}\n"
                            f"User ID: {member_user_id}"
                        ),
                    )
            except Forbidden:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="บอทไม่มีสิทธิ์นำสมาชิกคนนี้ออก",
                )
            except BadRequest as exc:
                if "User not found" in str(exc):
                    actor_label = self._format_actor_label(update.effective_user)
                    sheet_success = self.sheets_manager.remove_member_from_sheet(
                        member_user_id,
                        remove_reason="User already left group before manual removal",
                        actor=actor_label,
                        source="manual_remove_command",
                        note="Sheet record marked removed because Telegram user was already absent",
                    )
                    if sheet_success:
                        await context.bot.send_message(
                            chat_id=admin_group_id,
                            text=(
                                "สมาชิกไม่ได้อยู่ในกลุ่มแล้ว แต่ลบออกจาก Google Sheet ให้เรียบร้อยแล้ว\n"
                                f"Username: {username}\n"
                                f"User ID: {member_user_id}"
                            ),
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=admin_group_id,
                            text="สมาชิกไม่ได้อยู่ในกลุ่ม และไม่สามารถลบข้อมูลจาก Google Sheet ได้",
                        )
                else:
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=f"เกิดข้อผิดพลาดในการลบสมาชิก: {exc}",
                    )
        except Exception as exc:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"เกิดข้อผิดพลาด: {exc}",
            )

    async def list_members_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /listmembers",
            )

        try:
            members = self.sheets_manager.get_all_members()

            if not members:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="ยังไม่มีสมาชิกใน Google Sheet",
                )
                return

            page_size = 20
            total_pages = (len(members) + page_size - 1) // page_size
            page = 1
            if context.args and context.args[0].isdigit():
                page = max(1, min(int(context.args[0]), total_pages))

            start_idx = (page - 1) * page_size
            end_idx = min(start_idx + page_size, len(members))
            page_members = members[start_idx:end_idx]

            message = f"รายชื่อสมาชิก (หน้า {page}/{total_pages})\n\n"

            for index, member in enumerate(page_members, start=start_idx + 1):
                username = member.get("Username", "Unknown")
                user_id_member = member.get("User ID", "Unknown")
                expire_date = member.get("Expiredate", "Unknown")

                try:
                    expire_dt = datetime.strptime(expire_date, "%Y-%m-%d %H:%M:%S")
                    current_dt = datetime.now(pytz.timezone(config.TIMEZONE)).replace(
                        tzinfo=None
                    )
                    status = "หมดอายุแล้ว" if expire_dt <= current_dt else "ปกติ"
                except Exception:
                    status = "ไม่ระบุ"

                message += (
                    f"{index}. {username} (ID: {user_id_member})\n"
                    f"   วันหมดอายุ: {expire_date}\n"
                    f"   สถานะ: {status}\n\n"
                )

            if total_pages > 1:
                message += (
                    "\nใช้ /listmembers <เลขหน้า> เพื่อดูหน้าถัดไป\n"
                    "ตัวอย่าง: /listmembers 2"
                )

            if len(message) > 4000:
                message = message[:4000] + "\n\nรายการยาวเกินไป จึงแสดงเพียงบางส่วน"

            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=message,
            )
        except Exception as exc:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"เกิดข้อผิดพลาด: {exc}",
            )

    async def pending_members_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /pendingmembers",
            )

        if not config.is_admin(update.effective_user.id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
            )
            return

        if not self.pending_members:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="รายการรออนุมัติ\n\nไม่มีสมาชิกที่รออนุมัติ",
            )
            return

        message = f"รายการสมาชิกรออนุมัติ ({len(self.pending_members)} คน)\n\n"

        for index, (user_id_pending, member_info) in enumerate(self.pending_members.items(), 1):
            username = member_info["username"]
            first_name = member_info["first_name"]
            last_name = member_info["last_name"]
            timestamp = member_info["timestamp"]
            expire_date = member_info["expire_date_str"]
            join_type = member_info["join_type"]
            member_display_name = f"{first_name} {last_name}".strip() or username

            message += (
                f"{index}. {member_display_name}\n"
                f"   Username: {username}\n"
                f"   User ID: {user_id_pending}\n"
                f"   เวลา: {timestamp} ({config.TIMEZONE})\n"
                f"   วันหมดอายุ: {expire_date}\n"
                f"   ประเภท: {join_type}\n\n"
            )

        keyboard = []
        for user_id_pending, member_info in self.pending_members.items():
            username = member_info["username"]
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"อนุมัติ {username}",
                        callback_data=self.build_pending_callback_data(
                            "approve",
                            user_id_pending,
                            member_info,
                        ),
                    ),
                    InlineKeyboardButton(
                        f"ปฏิเสธ {username}",
                        callback_data=self.build_pending_callback_data(
                            "reject",
                            user_id_pending,
                            member_info,
                        ),
                    ),
                ]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)

        if len(message) > 4000:
            message = message[:4000] + "\n\nรายการยาวเกินไป จึงแสดงเพียงบางส่วน"

        await context.bot.send_message(
            chat_id=admin_group_id,
            text=message,
            reply_markup=reply_markup,
        )

    async def update_expire_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /updateexpire",
            )

        if not config.is_admin(update.effective_user.id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
            )
            return

        if len(context.args) < 2:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=(
                    "รูปแบบคำสั่ง:\n"
                    "/updateexpire user_id new_expire_date\n\n"
                    "ตัวอย่าง:\n"
                    "/updateexpire 123456789 2024-12-31 23:59:59"
                ),
            )
            return

        try:
            member_user_id = context.args[0]
            new_expire_date = " ".join(context.args[1:])

            try:
                datetime.strptime(new_expire_date, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=(
                        "รูปแบบวันที่ไม่ถูกต้อง\n"
                        "กรุณาใช้รูปแบบ: YYYY-MM-DD HH:MM:SS\n"
                        "ตัวอย่าง: 2024-12-31 23:59:59"
                    ),
                )
                return

            members = self.sheets_manager.get_all_members(include_inactive=True)
            member_info = None
            for member in members:
                if member.get("User ID") == member_user_id:
                    member_info = member
                    break

            if not member_info:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"ไม่พบสมาชิก User ID: {member_user_id} ใน Google Sheet",
                )
                return

            username = member_info.get("Username", "Unknown")
            success = self.sheets_manager.update_member_expire_date(
                member_user_id,
                new_expire_date,
            )

            if success:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=(
                        "อัปเดตวันหมดอายุสำเร็จ\n"
                        f"Username: {username}\n"
                        f"User ID: {member_user_id}\n"
                        f"วันหมดอายุใหม่: {new_expire_date}"
                    ),
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="ไม่สามารถอัปเดตวันหมดอายุได้",
                )
        except Exception as exc:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"เกิดข้อผิดพลาด: {exc}",
            )

    async def list_admins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        del update
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /listadmins",
            )

        try:
            admin_list = config.get_admin_list()
            message = f"รายชื่อแอดมินทั้งหมด ({len(admin_list)} คน)\n\n"
            for index, admin_id in enumerate(admin_list, 1):
                message += f"{index}. ID: {admin_id}\n"

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

    async def set_check_interval_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="มีการใช้งานคำสั่ง /setcheckinterval",
            )

        if not config.is_admin(update.effective_user.id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
            )
            return

        if len(context.args) != 2:
            current_interval = config.get_check_interval_seconds()
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=(
                    "การตั้งค่าช่วงเวลาตรวจสอบ\n\n"
                    f"ค่าปัจจุบัน: {config.CHECK_INTERVAL_VALUE} "
                    f"{UNIT_DISPLAY.get(config.CHECK_INTERVAL_UNIT, config.CHECK_INTERVAL_UNIT)}\n"
                    f"({current_interval} วินาที)\n\n"
                    "รูปแบบคำสั่ง:\n"
                    "/setcheckinterval <ค่า> <หน่วย>\n\n"
                    "หน่วยที่รองรับ:\n"
                    "- seconds = วินาที\n"
                    "- minutes = นาที\n"
                    "- hours = ชั่วโมง\n"
                    "- days = วัน\n\n"
                    "ตัวอย่าง:\n"
                    "/setcheckinterval 30 minutes\n"
                    "/setcheckinterval 2 hours\n"
                    "/setcheckinterval 1 days"
                ),
            )
            return

        try:
            value = int(context.args[0])
            unit = context.args[1].lower()
            valid_units = ["seconds", "minutes", "hours", "days"]

            if unit not in valid_units:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"หน่วยเวลาไม่ถูกต้อง\nใช้ได้เฉพาะ: {', '.join(valid_units)}",
                )
                return

            if value <= 0:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="ค่าช่วงเวลาต้องมากกว่า 0",
                )
                return

            total_seconds = value * {
                "seconds": 1,
                "minutes": 60,
                "hours": 3600,
                "days": 86400,
            }[unit]

            if total_seconds < 10:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="ช่วงเวลาสั้นเกินไป ต้องมากกว่า 10 วินาที",
                )
                return

            if total_seconds > 2592000:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="ช่วงเวลายาวเกินไป ต้องไม่เกิน 30 วัน",
                )
                return

            config.CHECK_INTERVAL_VALUE = value
            config.CHECK_INTERVAL_UNIT = unit

            if self.application and self.application.job_queue:
                new_interval = config.get_check_interval_seconds()
                self.reschedule_expired_member_job(new_interval)

            await context.bot.send_message(
                chat_id=admin_group_id,
                text=(
                    "ตั้งค่าช่วงเวลาสำเร็จ\n\n"
                    f"ค่าใหม่: {value} {UNIT_DISPLAY[unit]}\n"
                    f"({total_seconds} วินาที)\n\n"
                    "หมายเหตุ: ค่านี้จะมีผลจนกว่าจะรีสตาร์ตบอท\n"
                    "หากต้องการให้ถาวร กรุณาแก้ไขค่าที่ไฟล์ app/core/config.py "
                    "หรือไฟล์ environment"
                ),
            )
        except ValueError:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="ค่าช่วงเวลาต้องเป็นตัวเลข",
            )
        except Exception as exc:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"เกิดข้อผิดพลาด: {exc}",
            )
