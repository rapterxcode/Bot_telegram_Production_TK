"""Application registration helpers for the Telegram bot."""

from telegram import BotCommand, BotCommandScopeDefault
from telegram.ext import (
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    CommandHandler,
)


COMMAND_HANDLERS = [
    ("start", "start_command"),
    ("help", "help_command"),
    ("status", "status_command"),
    ("statuslive", "status_live_command"),
    ("checknow", "check_now_command"),
    ("syncmembers", "sync_members_command"),
    ("fullsyncmembers", "full_sync_members_command"),
    ("listexpired", "list_expired_command"),
    ("addmember", "add_member_command"),
    ("removemember", "remove_member_command"),
    ("listmembers", "list_members_command"),
    ("pendingmembers", "pending_members_command"),
    ("updateexpire", "update_expire_command"),
    ("setcheckinterval", "set_check_interval_command"),
    ("invitelink", "invite_link_command"),
    ("invitelink1month", "invite_link_1month_command"),
    ("invitelink1year", "invite_link_1year_command"),
    ("invitelinknoexpire", "invite_link_no_expire_command"),
    ("listadmins", "list_admins_command"),
]

ADMIN_COMMANDS = [
    BotCommand("start", "เริ่มต้นใช้งานบอท"),
    BotCommand("help", "ดูคู่มือคำสั่ง"),
    BotCommand("status", "ดูสถานะล่าสุดจาก snapshot"),
    BotCommand("statuslive", "ดูสถานะสดจาก Telegram"),
    BotCommand("checknow", "ตรวจสมาชิกหมดอายุทันที"),
    BotCommand("syncmembers", "ซิงก์ข้อมูลชีตกับกลุ่ม"),
    BotCommand("fullsyncmembers", "full sync สมาชิกผ่าน Telethon"),
    BotCommand("listexpired", "ดูรายชื่อสมาชิกหมดอายุ"),
    BotCommand("addmember", "เพิ่มสมาชิก"),
    BotCommand("removemember", "ลบสมาชิก"),
    BotCommand("listmembers", "ดูรายชื่อสมาชิกในชีต"),
    BotCommand("pendingmembers", "ดูรายการรออนุมัติ"),
    BotCommand("updateexpire", "แก้วันหมดอายุ"),
    BotCommand("setcheckinterval", "ตั้งรอบตรวจสอบ"),
    BotCommand("invitelink", "สร้างลิงก์เชิญแบบกำหนดเอง"),
    BotCommand("invitelink1month", "สร้างลิงก์สมาชิก 1 เดือน"),
    BotCommand("invitelink1year", "สร้างลิงก์สมาชิก 1 ปี"),
    BotCommand("invitelinknoexpire", "สร้างลิงก์ไม่หมดอายุ"),
    BotCommand("listadmins", "ดูรายชื่อแอดมิน"),
]


def register_handlers(application, bot):
    """Register all handlers for the bot application."""
    for command, handler_name in COMMAND_HANDLERS:
        application.add_handler(CommandHandler(command, getattr(bot, handler_name)))

    application.add_handler(
        ChatMemberHandler(bot.track_chat_member_updates, ChatMemberHandler.CHAT_MEMBER)
    )
    application.add_handler(ChatJoinRequestHandler(bot.handle_chat_join_request))
    application.add_handler(CallbackQueryHandler(bot.handle_approval_callback))
    application.add_error_handler(bot.error_handler)


async def setup_bot_commands(application, logger):
    """Configure Telegram suggested commands."""
    try:
        await application.bot.set_my_commands(
            commands=ADMIN_COMMANDS,
            scope=BotCommandScopeDefault(),
        )
        logger.info("Bot commands setup complete")
    except Exception as exc:
        logger.error("Error setting up bot commands: %s", exc)
