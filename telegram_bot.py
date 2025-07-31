import asyncio
import logging
from datetime import datetime
from typing import Dict, List
import pytz
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeDefault
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    ChatMemberHandler,
    ChatJoinRequestHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler
)
from telegram.error import TelegramError, Forbidden, BadRequest
import config
from google_sheets import GoogleSheetsManager


# กำหนดค่า logging สำหรับทุก modules
def setup_global_logging():
    """ตั้งค่า global logging ให้เก็บ log จากทุกที่ลงไฟล์เท่านั้น"""
    import os
    from logging.handlers import RotatingFileHandler
    
    # สร้าง formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # สร้างไดเรกทอรี logs
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # ตั้งค่า root logger เพื่อครอบคลุมทุก logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # ป้องกันการเพิ่ม handler ซ้ำ
    if root_logger.handlers:
        root_logger.handlers.clear()
    
    # Console handler (สำหรับแสดงใน terminal)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler หลัก (เก็บทุก log จากทุก module)
    file_handler = logging.FileHandler(
        os.path.join(log_dir, 'application.log'),
        mode='a',
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Rotating file handler สำหรับจำกัดขนาดไฟล์
    rotating_handler = RotatingFileHandler(
        os.path.join(log_dir, 'application_rotating.log'),
        maxBytes=100*1024*1024,  # 100MB
        backupCount=5,
        encoding='utf-8'
    )
    rotating_handler.setLevel(logging.INFO)
    rotating_handler.setFormatter(formatter)
    root_logger.addHandler(rotating_handler)
    
    # File handler เฉพาะสำหรับ telegram_bot
    telegram_bot_handler = logging.FileHandler(
        os.path.join(log_dir, 'telegram_bot.log'),
        mode='a',
        encoding='utf-8'
    )
    telegram_bot_handler.setLevel(logging.INFO)
    telegram_bot_handler.setFormatter(formatter)
    
    # เพิ่ม filter เพื่อเก็บเฉพาะ log จาก telegram_bot
    telegram_bot_handler.addFilter(lambda record: record.name.startswith('telegram_bot') or record.name == '__main__')
    root_logger.addHandler(telegram_bot_handler)
    
    # สร้าง logger สำหรับ telegram_bot module
    telegram_logger = logging.getLogger(__name__)
    
    return telegram_logger

logger = setup_global_logging()
logger.info("🚀 Global Logging initialized - logs saved to files and displayed in console")


class TelegramMemberBot:
    def __init__(self):
        self.application = None
        self.sheets_manager = GoogleSheetsManager()
        self.group_chat_id = config.GROUP_CHAT_ID if config.GROUP_CHAT_ID != 0 else None
        
        # เก็บข้อมูล invite links ที่สร้าง (ชั่วคราวในหน่วยความจำ)
        self.invite_link_expires = {}  # {invite_link: expire_days}
        
        # เก็บข้อมูลประเภทการเข้าร่วมล่าสุด (สำหรับกำหนดประเภทสมาชิกใหม่) - เลิกใช้แล้ว
        self.recent_join_type = "default"  # deprecated - ใช้ invite_link_expires แทน
        
        # เก็บ mapping ระหว่าง invite link กับข้อมูลการตั้งค่า
        self.active_invite_links = {}  # {link_url: {type, days, period_name}}
        
        # เก็บข้อมูลสมาชิกที่รออนุมัติ {user_id: {username, first_name, last_name, join_type, expire_date_str, timestamp}}
        self.pending_members = {}
        
        # เก็บข้อมูลการแจ้งเตือนที่ส่งไปแล้ว (ป้องกันการแจ้งเตือนซ้ำ)
        self.sent_notifications = set()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /start"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /start หรือเริ่มต้นใช้งานบอท")

        if update.effective_chat.type == 'private':
            # ตรวจสอบ start parameter
            start_param = context.args[0] if context.args else None
            
            if config.is_admin(update.effective_user.id):
                if start_param == "admin":
                    await update.message.reply_text(
                        "✅ เริ่มสนทนาสำเร็จ!\n\n"
                        "🤖 สวัสดีแอดมิน! ตอนนี้บอทสามารถส่งข้อความส่วนตัวให้คุณได้แล้ว\n\n"
                        f"🎯 กลุ่มเป้าหมาย: {config.GROUP_CHAT_ID}\n"
                        f"📊 Google Sheet: {config.WORKSHEET_NAME}\n"
                        f"👥 แอดมินทั้งหมด: {len(config.get_admin_list())} คน\n\n"
                        "💡 เคล็ดลับ: ใช้คำสั่งในกลุ่มแล้วรับผลลัพธ์ที่นี่!\n"
                        "พิมพ์ /help เพื่อดูคำสั่งทั้งหมด"
                    )
                else:
                    await update.message.reply_text(
                        "🤖 สวัสดีแอดมิน! ฉันเป็นบอทจัดการสมาชิกกลุ่ม\n"
                        f"กลุ่มเป้าหมาย: {config.GROUP_CHAT_ID}\n"
                        "บอทพร้อมใช้งานแล้ว!\n\n"
                        "💡 ตอนนี้คุณสามารถรับข้อความส่วนตัวจากบอทได้แล้ว"
                    )
            else:
                await update.message.reply_text(
                    "🤖 สวัสดี! ฉันเป็นบอทจัดการสมาชิกกลุ่ม\n"
                    "เฉพาะแอดมินเท่านั้นที่สามารถใช้งานบอทนี้ได้"
                )
        else:
            # อัปเดต group_chat_id หากไม่ได้ตั้งค่าไว้ใน config
            if not self.group_chat_id:
                self.group_chat_id = update.effective_chat.id
            
            await update.message.reply_text(
                "✅ บอทพร้อมใช้งานแล้ว!\n"
                "ฉันจะช่วยจัดการสมาชิกและตรวจสอบการหมดอายุอัตโนมัติ\n\n"
                "💡 **สำหรับแอดมิน:** เริ่มสนทนากับบอทในแชทส่วนตัวเพื่อรับผลลัพธ์คำสั่งแบบส่วนตัว"
            )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /status - แสดงสถานะการทำงาน"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /status หรือตรวจสอบสถานะระบบ")
        
        try:
            members = self.sheets_manager.get_all_members()
            expired_members = self.sheets_manager.get_expired_members()
            
            # ข้อมูลช่วงเวลาการตรวจสอบ
            unit_display = {
                'seconds': 'วินาที',
                'minutes': 'นาที',
                'hours': 'ชั่วโมง',
                'days': 'วัน'
            }
            
            interval_seconds = config.get_check_interval_seconds()
            interval_text = f"{config.CHECK_INTERVAL_VALUE} {unit_display.get(config.CHECK_INTERVAL_UNIT, config.CHECK_INTERVAL_UNIT)}"
            
            status_text = (
                f"📊 สถานะระบบ\n"
                f"👥 สมาชิกทั้งหมด: {len(members)} คน\n"
                f"⚠️ หมดอายุแล้ว: {len(expired_members)} คน\n"
                f"🏷️ กลุ่มเป้าหมาย: {config.GROUP_CHAT_ID}\n"
                f"📋 ชีท: {config.WORKSHEET_NAME}\n"
                f"⏰ ตรวจสอบทุกๆ: {interval_text} ({interval_seconds} วินาที)\n"
                f"🕐 ตรวจสอบล่าสุด: {datetime.now(pytz.timezone(config.TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            await self.send_safe_message(context, admin_group_id, status_text)
            
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ เกิดข้อผิดพลาด: {str(e)}"
            )

    async def check_now_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /checknow - ตรวจสอบสมาชิกหมดอายุทันที (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /checknow หรือตรวจสอบสมาชิกหมดอายุทันที")
        
        try:
            await self.check_expired_members(context)
            await self.send_safe_message(context, admin_group_id, "✅ ตรวจสอบเสร็จสิ้น")
        except Exception as e:
            await self.send_safe_message(context, admin_group_id, f"❌ เกิดข้อผิดพลาด: {str(e)}")

    async def list_expired_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /listexpired - แสดงรายชื่อสมาชิกที่หมดอายุ (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /listexpired หรือแสดงรายชื่อสมาชิกหมดอายุ")
        
        try:
            expired_members = self.sheets_manager.get_expired_members()
            
            if not expired_members:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="✅ ไม่มีสมาชิกที่หมดอายุ"
                )
                return
            
            message = "⚠️ **รายชื่อสมาชิกหมดอายุ:**\n\n"
            for i, member in enumerate(expired_members, 1):
                username = member.get('Username', 'Unknown')
                user_id_member = member.get('User ID', 'Unknown')
                expire_date = member.get('Expiredate', 'Unknown')
                message += f"{i}. {username} (ID: `{user_id_member}`)\n   หมดอายุ: {expire_date}\n\n"
            
            if len(message) > 4000:  # จำกัดความยาวข้อความ
                message = message[:4000] + "...\n\n*รายการยาวเกินไป แสดงเพียงบางส่วน*"
            
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=message
            )
            
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ เกิดข้อผิดพลาด: {str(e)}"
            )

    async def add_member_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /addmember - เพิ่มข้อมูลสมาชิกใน Google Sheet (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /addmember หรือเพิ่มข้อมูลสมาชิกใน Google Sheet")
        
        if not config.is_admin(update.effective_user.id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
            )
            return
        
        # ตรวจสอบรูปแบบคำสั่ง
        if len(context.args) < 3:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="📝 รูปแบบคำสั่ง:\n"
                     "/addmember @username user_id expire_date\n\n"
                     "ตัวอย่าง:\n"
                     "/addmember @john_doe 123456789 2024-12-31 23:59:59"
            )
            return
        
        try:
            username = context.args[0]
            member_user_id = context.args[1]
            expire_date = " ".join(context.args[2:])  # รวมวันที่และเวลา
            
            # ตรวจสอบรูปแบบ username
            if not username.startswith('@'):
                username = f"@{username}"
            
            # ตรวจสอบรูปแบบวันที่
            try:
                datetime.strptime(expire_date, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="❌ รูปแบบวันที่ไม่ถูกต้อง\n"
                         "ใช้รูปแบบ: YYYY-MM-DD HH:MM:SS\n"
                         "ตัวอย่าง: 2024-12-31 23:59:59"
                )
                return
            
            # เพิ่มสมาชิกเข้ากลุ่ม Telegram โดยตรง
            target_group_id = config.GROUP_CHAT_ID
            
            try:
                # ยกเลิกการแบนก่อน (ในกรณีที่เคยถูกแบน)
                await context.bot.unban_chat_member(
                    chat_id=target_group_id,
                    user_id=int(member_user_id),
                    only_if_banned=True
                )
                
                # สร้าง invite link ที่เพิ่มสมาชิกโดยตรง (ไม่ต้องอนุมัติ)
                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=target_group_id,
                    member_limit=1,
                    creates_join_request=False
                )
                
                # ส่งลิงก์ให้สมาชิกเพื่อเข้ากลุ่ม
                await context.bot.send_message(
                    chat_id=int(member_user_id),
                    text=f"🎉 คุณได้รับอนุมัติให้เข้าร่วมกลุ่ม!\n"
                         f"📅 หมดอายุสมาชิกภาพ: {expire_date}\n"
                         f"🔗 คลิกลิงก์เพื่อเข้าร่วม: {invite_link.invite_link}\n"
                         f"📋 กรุณาปฏิบัติตามกฎของกลุ่ม"
                )
                
                
            except Exception as e:
                print(f"❌ ข้อผิดพลาดในการเพิ่มสมาชิกเข้ากลุ่ม: {e}")
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"❌ ไม่สามารถเพิ่มสมาชิกเข้ากลุ่มได้: {str(e)}\n"
                         f"💡 ตรวจสอบว่าบอทมีสิทธิ์ admin และสามารถเชิญสมาชิกได้"
                )
                return
            
            # เพิ่มข้อมูลใน Google Sheet
            success = self.sheets_manager.add_member(username, member_user_id, expire_date)
            
            if success:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"✅ เพิ่มสมาชิกสำเร็จ!\n"
                         f"👤 Username: {username}\n"
                         f"🆔 User ID: {member_user_id}\n"
                         f"📅 หมดอายุ: {expire_date}\n"
                         f"📊 วิธีการ: ส่งลิงก์เชิญ + บันทึกใน Google Sheet"
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="❌ ส่งลิงก์เชิญสำเร็จ แต่ไม่สามารถบันทึกข้อมูลใน Google Sheet ได้"
                )
                
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ เกิดข้อผิดพลาด: {str(e)}"
            )

    async def invite_link_1month_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /invitelink1month - สร้าง invite link สำหรับสมาชิก 1 เดือน (เฉพาะแอดมิน)"""
        await self._create_invite_link(update, context, days=config.INVITE_LINK_1MONTH_DAYS, period_name="1 เดือน", link_type="1month")

    async def invite_link_1year_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /invitelink1year - สร้าง invite link สำหรับสมาชิก 1 ปี (เฉพาะแอดมิน)"""
        await self._create_invite_link(update, context, days=config.INVITE_LINK_1YEAR_DAYS, period_name="1 ปี", link_type="1year")

    async def invite_link_no_expire_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /invitelinknoexpire - สร้าง invite link สำหรับสมาชิกไม่หมดอายุ (เฉพาะแอดมิน)"""
        await self._create_invite_link(update, context, days=None, period_name="ไม่หมดอายุ", link_type="noexpire")

    async def invite_link_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /invitelink - สร้าง invite link กำหนดระยะเวลาเอง (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /invitelink หรือสร้างลิงก์เชิญกำหนดเอง")
        
        user_id = update.effective_user.id
        
        if not config.is_admin(user_id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
            )
            return

        # ตรวจสอบการใช้งานคำสั่ง
        if not context.args or len(context.args) < 2:
            help_text = (
                "📋 วิธีใช้คำสั่ง /invitelink:\n\n"
                "รูปแบบ: /invitelink <จำนวน> <หน่วย>\n\n"
                "หน่วยที่รองรับ:\n"
                "• days หรือ day - วัน\n"
                "• months หรือ month - เดือน  \n"
                "• years หรือ year - ปี\n\n"
                "ตัวอย่าง:\n"
                "• /invitelink 7 days - 7 วัน\n"
                "• /invitelink 3 months - 3 เดือน\n"
                "• /invitelink 2 years - 2 ปี\n"
                "• /invitelink 15 day - 15 วัน\n"
                "• /invitelink 1 year - 1 ปี"
            )
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=help_text
            )
            return

        try:
            # แปลงค่าและหน่วย
            amount = int(context.args[0])
            unit = context.args[1].lower()
            
            # ตรวจสอบค่าที่ใส่
            if amount <= 0:
                await self.send_safe_message(
                    context=context,
                    user_id=admin_group_id,
                    text="❌ จำนวนต้องมากกว่า 0"
                )
                return

            # คำนวณจำนวนวัน
            if unit in ['day', 'days']:
                days = amount
                period_name = f"{amount} วัน"
            elif unit in ['month', 'months']:
                days = amount * 30  # ประมาณ 30 วันต่อเดือน
                period_name = f"{amount} เดือน"
            elif unit in ['year', 'years']:
                days = amount * 365  # 365 วันต่อปี
                period_name = f"{amount} ปี"
            else:
                await self.send_safe_message(
                    context=context,
                    user_id=admin_group_id,
                    text="❌ หน่วยไม่ถูกต้อง\nใช้ได้เฉพาะ: days, months, years"
                )
                return

            # ตรวจสอบขีดจำกัด (ป้องกันค่าที่มากเกินไป)
            if days > 3650:  # ไม่เกิน 10 ปี
                await self.send_safe_message(
                    context=context,
                    user_id=admin_group_id,
                    text="❌ ระยะเวลาไม่ควรเกิน 10 ปี"
                )
                return

            # สร้าง invite link
            await self._create_invite_link(update, context, days=days, period_name=period_name, link_type="custom")

        except ValueError:
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text="❌ จำนวนต้องเป็นตัวเลข\nตัวอย่าง: /invitelink 30 days"
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ เกิดข้อผิดพลาด: {str(e)}"
            )

    async def _create_invite_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE, days: int = None, period_name: str = "", link_type: str = "default"):
        """ฟังก์ชันช่วยสร้าง invite link พร้อมกำหนดระยะเวลา"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /invitelink หรือสร้างลิงก์เชิญกำหนดเอง")
        
        user_id = update.effective_user.id
        
        if not config.is_admin(user_id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
            )
            return
        
        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
        
        if not target_group_id:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ ไม่พบ Group Chat ID"
            )
            return
        
        try:
            # คำนวณวันหมดอายุสำหรับสมาชิกใหม่
            from datetime import datetime, timedelta
            import pytz
            
            current_time = datetime.now(pytz.timezone(config.TIMEZONE))
            
            # ตรวจสอบว่าเป็น no expire หรือไม่
            if days is None:
                expire_date_str = "no_expire"
            else:
                future_expire_date = current_time + timedelta(days=days)
                expire_date_str = future_expire_date.strftime('%Y-%m-%d %H:%M:%S')
            
            # คำนวณเวลาหมดอายุของ link (ใช้ timezone จาก config)
            link_expire_time = current_time + timedelta(minutes=config.INVITE_LINK_EXPIRE_MINUTES)
            
            # ดึงข้อมูล admin ที่สร้าง link
            admin_user = update.effective_user
            admin_username = f"@{admin_user.username}" if admin_user.username else f"User_{admin_user.id}"
            
            # สร้าง Link Name
            link_name = f"Bot Invite for {admin_username} ({period_name})"
            
            # สร้าง invite link แบบต้อง approve ก่อนเข้ากลุ่ม
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=target_group_id,
                expire_date=int(link_expire_time.timestamp()),  # หมดอายุตามที่กำหนด
                member_limit=None,  # ไม่จำกัดจำนวน
                name=link_name,
                creates_join_request=True  # ต้อง approve ก่อนเข้ากลุ่ม
            )
            
            # เก็บข้อมูล invite link พร้อมประเภท
            link_url = invite_link.invite_link
            self.invite_link_expires[link_url] = {
                'days': days if days is not None else "no_expire",
                'type': link_type,
                'period_name': period_name,
                'created_time': current_time,
                'expire_time': link_expire_time
            }
            
            # เก็บใน active_invite_links สำหรับการค้นหาที่ง่ายขึ้น
            self.active_invite_links[link_url] = {
                'type': link_type,
                'days': days if days is not None else "no_expire",
                'period_name': period_name
            }
            
            logger.info(f"📝 Stored invite link: {link_url} with type: {link_type}, days: {days}")
            
            # ทำความสะอาด invite links ที่หมดอายุแล้ว
            self._cleanup_expired_invite_links()
            
            # สร้างข้อความตามประเภท
            if days is None:
                # สำหรับ no expire
                message = (
                    f"🔗 **Invite Link ของกลุ่ม ({period_name}):**\n"
                    f"{invite_link.invite_link}\n\n"
                    f"⚠️ **ลิงก์หมดอายุ:** {config.INVITE_LINK_EXPIRE_MINUTES} นาที\n"
                    f"⏰ **หมดอายุเวลา:** {link_expire_time.strftime('%d/%m/%Y %H:%M:%S')} ({config.TIMEZONE})\n\n"
                    f"ℹ️ **Flow การทำงาน:**\n"
                    f"1️⃣ สมาชิกกดลิงก์ → ส่ง join request (ยังไม่เข้ากลุ่ม)\n"
                    f"2️⃣ แอดมินได้แจ้งเตือนพร้อมปุ่ม approve/reject\n"
                    f"3️⃣ อนุมัติ → อนุญาตเข้ากลุ่ม + เพิ่มเข้า Google Sheets (ไม่หมดอายุ)\n"
                    f"4️⃣ ปฏิเสธ → ปฏิเสธคำขอเข้ากลุ่ม\n\n"
                    f"⚙️ ใช้ค่า: `{config.INVITE_LINK_NOEXPIRE}` จาก .env\n"
                    f"💾 แชร์ลิงก์นี้เพื่อเชิญสมาชิกถาวร"
                )
            else:
                # สำหรับมีวันหมดอายุ
                message = (
                    f"🔗 **Invite Link ของกลุ่ม ({period_name}):**\n"
                    f"{invite_link.invite_link}\n\n"
                    f"⚠️ **ลิงก์หมดอายุ:** {config.INVITE_LINK_EXPIRE_MINUTES} นาที\n"
                    f"⏰ **หมดอายุเวลา:** {link_expire_time.strftime('%d/%m/%Y %H:%M:%S')} ({config.TIMEZONE})\n\n"
                    f"ℹ️ **Flow การทำงาน:**\n"
                    f"1️⃣ สมาชิกกดลิงก์ → ส่ง join request (ยังไม่เข้ากลุ่ม)\n"
                    f"2️⃣ แอดมินได้แจ้งเตือนพร้อมปุ่ม approve/reject\n"
                    f"3️⃣ อนุมัติ → อนุญาตเข้ากลุ่ม + เพิ่มเข้า Google Sheets (หมดอายุ {expire_date_str})\n"
                    f"4️⃣ ปฏิเสธ → ปฏิเสธคำขอเข้ากลุ่ม\n\n"
                    f"⏳ ระยะเวลา: {period_name} ({days} วัน)\n"
                    f"⚙️ ใช้ค่า: `{days} วัน` จาก .env\n"
                    f"💾 แชร์ลิงก์นี้เพื่อเชิญสมาชิก {period_name}"
                )
            
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=message
            )
            
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ ไม่สามารถสร้าง invite link ได้: {str(e)}"
            )
    
    def _cleanup_expired_invite_links(self):
        """ทำความสะอาด invite links ที่หมดอายุแล้ว"""
        from datetime import datetime
        import pytz
        
        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
        expired_links = []
        
        for link, info in self.invite_link_expires.items():
            if 'expire_time' in info and current_time > info['expire_time']:
                expired_links.append(link)
        
        # ลบ links ที่หมดอายุ
        for link in expired_links:
            del self.invite_link_expires[link]
            if link in self.active_invite_links:
                del self.active_invite_links[link]
            logger.info(f"🧹 Cleaned up expired invite link: {link}")
        
        if expired_links:
            logger.info(f"🧹 Cleaned up {len(expired_links)} expired invite links")

    async def remove_member_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /removemember - ลบสมาชิกออกจากกลุ่มและ Google Sheet (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /removemember หรือลบสมาชิกออกจากกลุ่มและ Google Sheet")
        
        user_id = update.effective_user.id
        
        if not config.is_admin(user_id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
            )
            return
        
        # ตรวจสอบรูปแบบคำสั่ง
        if len(context.args) != 1:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="📝 รูปแบบคำสั่ง:\n"
                     "/removemember user_id\n\n"
                     "ตัวอย่าง:\n"
                     "/removemember 123456789"
            )
            return
        
        try:
            member_user_id = context.args[0]
            target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
            
            if not target_group_id:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="❌ ไม่พบ Group Chat ID"
                )
                return
            
            # ค้นหาข้อมูลสมาชิกใน Google Sheet ก่อน
            members = self.sheets_manager.get_all_members()
            member_info = None
            
            for member in members:
                if member.get('User ID') == member_user_id:
                    member_info = member
                    break
            
            if not member_info:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"❌ ไม่พบสมาชิก User ID: {member_user_id} ใน Google Sheet"
                )
                return
            
            username = member_info.get('Username', 'Unknown')
            
            # ลบสมาชิกออกจากกลุ่ม Telegram
            try:
                await context.bot.ban_chat_member(
                    chat_id=target_group_id,
                    user_id=int(member_user_id)
                )
                
                # ยกเลิกการแบนทันที (เพื่อให้สามารถเข้าร่วมใหม่ได้ในอนาคต)
                await context.bot.unban_chat_member(
                    chat_id=target_group_id,
                    user_id=int(member_user_id)
                )
                
                # ลบข้อมูลจาก Google Sheet
                sheet_success = self.sheets_manager.remove_member_from_sheet(member_user_id)
                
                if sheet_success:
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=f"✅ ลบสมาชิกสำเร็จ!\n"
                             f"👤 Username: {username}\n"
                             f"🆔 User ID: {member_user_id}\n"
                             f"📋 ลบออกจากกลุ่มและ Google Sheet แล้ว"
                    )
                    
                    # ส่งข้อความแจ้งเตือนในกลุ่ม
                    try:
                        await context.bot.send_message(
                            chat_id=admin_group_id,
                            text=f"🚫 สมาชิก {username} ถูกลบออกจากกลุ่มโดยแอดมิน"
                        )
                    except Exception as notify_error:
                        logger.error(f"Cannot send notification to group: {notify_error}")
                        
                else:
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=f"⚠️ ลบออกจากกลุ่มสำเร็จ แต่ไม่สามารถลบข้อมูลจาก Google Sheet ได้\n"
                             f"👤 Username: {username}\n"
                             f"🆔 User ID: {member_user_id}"
                    )
                
            except Forbidden:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="❌ บอทไม่มีสิทธิ์ลบสมาชิกคนนี้"
                )
            except BadRequest as e:
                if "User not found" in str(e):
                    # ลบข้อมูลจาก Sheet เฉยๆ เพราะไม่อยู่ในกลุ่มแล้ว
                    sheet_success = self.sheets_manager.remove_member_from_sheet(member_user_id)
                    if sheet_success:
                        await context.bot.send_message(
                            chat_id=admin_group_id,
                            text=f"ℹ️ สมาชิกไม่อยู่ในกลุ่มแล้ว แต่ลบข้อมูลจาก Google Sheet แล้ว\n"
                                 f"👤 Username: {username}\n"
                                 f"🆔 User ID: {member_user_id}"
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=admin_group_id,
                            text=f"❌ สมาชิกไม่อยู่ในกลุ่ม และไม่สามารถลบข้อมูลจาก Google Sheet ได้"
                        )
                else:
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=f"❌ ข้อผิดพลาดในการลบสมาชิก: {str(e)}"
                    )
                    
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ เกิดข้อผิดพลาด: {str(e)}"
            )

    async def list_members_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /listmembers - แสดงรายชื่อสมาชิกทั้งหมด (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /listmembers หรือแสดงรายชื่อสมาชิกทั้งหมด")
        
        try:
            members = self.sheets_manager.get_all_members()
            
            if not members:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="ℹ️ ไม่มีสมาชิกใน Google Sheet"
                )
                return
            
            # แบ่งข้อมูลออกเป็นหน้าๆ ละ 20 คน
            page_size = 20
            total_pages = (len(members) + page_size - 1) // page_size
            
            # ดูว่าผู้ใช้ระบุหน้าไหม
            page = 1
            if context.args and context.args[0].isdigit():
                page = max(1, min(int(context.args[0]), total_pages))
            
            start_idx = (page - 1) * page_size
            end_idx = min(start_idx + page_size, len(members))
            page_members = members[start_idx:end_idx]
            
            message = f"👥 รายชื่อสมาชิก (หน้า {page}/{total_pages}):\n\n"
            
            for i, member in enumerate(page_members, start=start_idx + 1):
                username = member.get('Username', 'Unknown')
                user_id_member = member.get('User ID', 'Unknown')
                expire_date = member.get('Expiredate', 'Unknown')
                
                # ตรวจสอบสถานะหมดอายุ
                try:
                    expire_dt = datetime.strptime(expire_date, '%Y-%m-%d %H:%M:%S')
                    current_dt = datetime.now(pytz.timezone(config.TIMEZONE)).replace(tzinfo=None)
                    status = "⚠️ หมดอายุ" if expire_dt <= current_dt else "✅ ปกติ"
                except:
                    status = "❓ ไม่ระบุ"
                
                message += f"{i}. {username} (ID: {user_id_member})\n"
                message += f"   หมดอายุ: {expire_date} {status}\n\n"
            
            if total_pages > 1:
                message += f"\n📄 ใช้ /listmembers หน้า เพื่อดูหน้าอื่น\nเช่น: /listmembers 2"
            
            if len(message) > 4000:  # จำกัดความยาวข้อความ
                message = message[:4000] + "...\n\nรายการยาวเกินไป แสดงเพียงบางส่วน"
            
            await self.send_safe_message(
                context=context,
                user_id=admin_group_id,
                text=message
            )
            
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ เกิดข้อผิดพลาด: {str(e)}"
            )

    async def pending_members_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /pendingmembers - แสดงรายการสมาชิกรออนุมัติ (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /pendingmembers หรือแสดงรายการสมาชิกรออนุมัติ")
        
        if not config.is_admin(update.effective_user.id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
            )
            return
        
        if not self.pending_members:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="📋 **รายการรออนุมัติ**\n\n✅ ไม่มีสมาชิกรออนุมัติ"
            )
            return
        
        message = f"📋 **รายการสมาชิกรออนุมัติ** ({len(self.pending_members)} คน):\n\n"
        
        for i, (user_id_pending, member_info) in enumerate(self.pending_members.items(), 1):
            username = member_info['username']
            first_name = member_info['first_name']
            last_name = member_info['last_name']
            timestamp = member_info['timestamp']
            expire_date = member_info['expire_date_str']
            join_type = member_info['join_type']
            
            member_display_name = f"{first_name} {last_name}".strip() or username
            
            message += (
                f"{i}. **{member_display_name}**\n"
                f"   🏷️ Username: {username}\n"
                f"   �� User ID: `{user_id_pending}`\n"
                f"   ⏰ เวลา: {timestamp} ({config.TIMEZONE})\n"
                f"   📅 หมดอายุ: {expire_date}\n"
                f"   🏷️ ประเภท: {join_type}\n\n"
            )
        
        # สร้างปุ่มสำหรับแต่ละสมาชิก
        keyboard = []
        for user_id_pending, member_info in self.pending_members.items():
            username = member_info['username']
            keyboard.append([
                InlineKeyboardButton(f"✅ อนุมัติ {username}", callback_data=f"approve_{user_id_pending}"),
                InlineKeyboardButton(f"❌ ปฏิเสธ {username}", callback_data=f"reject_{user_id_pending}")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if len(message) > 4000:  # จำกัดความยาวข้อความ
            message = message[:4000] + "...\n\nรายการยาวเกินไป แสดงเพียงบางส่วน"
        
        await context.bot.send_message(
            chat_id=admin_group_id,
            text=message,
            reply_markup=reply_markup
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /help - แสดงคำสั่งที่รองรับ"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /help หรือแสดงความช่วยเหลือ")
        
        if config.is_admin(update.effective_user.id):
            help_text = f"""
�� **บอทจัดการสมาชิกกลุ่ม - Admin Panel**

**📋 คำสั่งทั่วไป:**
• /start - เริ่มต้นการทำงาน
• /help - แสดงความช่วยเหลือ
• /status - สถานะระบบ

**👥 จัดการสมาชิก:**
• /addmember @user 123456789 2024-12-31 23:59:59
• /removemember 123456789
• /updateexpire 123456789 2025-06-15 23:59:59
• /listmembers [หน้า]
• /pendingmembers - รายการรออนุมัติ
• /listexpired

**🔧 เครื่องมือแอดมิน:**
• /checknow - ตรวจสอบหมดอายุทันที
• /setcheckinterval - ตั้งช่วงเวลาตรวจสอบ
• /invitelink <จำนวน> <หน่วย> - สร้างลิงก์เชิญกำหนดเอง
• /invitelink1month - สร้างลิงก์เชิญ (1 เดือน)
• /invitelink1year - สร้างลิงก์เชิญ (1 ปี)
• /invitelinknoexpire - สร้างลิงก์เชิญ (ไม่หมดอายุ)
• /listadmins - แสดงรายชื่อแอดมิน

**🎯 กลุ่มเป้าหมาย:** `{config.GROUP_CHAT_ID}`
**📊 Google Sheet:** `{config.WORKSHEET_NAME}`
**👥 แอดมิน:** {len(config.get_admin_list())} คน

───────────────────────────────
**📖 ตัวอย่างการใช้งาน:**

📝 `/addmember @john_doe 123456789 2024-12-31 23:59:59`
🗑️ `/removemember 123456789`  
📅 `/updateexpire 123456789 2025-06-15 23:59:59`
👥 `/listmembers` หรือ `/listmembers 2`
⏳ `/pendingmembers` - รายการรออนุมัติ
⚠️ `/listexpired`
🔍 `/checknow`
⏰ `/setcheckinterval 30 minutes`
🔗 `/invitelink 30 days` - สร้างลิงก์เชิญ 30 วัน
🔗 `/invitelink 6 months` - สร้างลิงก์เชิญ 6 เดือน
🔗 `/invitelink1month` - สร้างลิงก์เชิญ 1 เดือน
🔗 `/invitelink1year` - สร้างลิงก์เชิญ 1 ปี
🔗 `/invitelinknoexpire` - สร้างลิงก์เชิญไม่หมดอายุ

**💡 เคล็ดลับสำหรับแอดมิน:**
• เพิ่มสมาชิกผ่าน Telegram UI ปกติ → บอทบันทึกอัตโนมัติ
• หา User ID ได้จาก @userinfobot
• วันหมดอายุเริ่มต้น: {config.DEFAULT_EXPIRE_DAYS} วัน
• รูปแบบวันที่: YYYY-MM-DD HH:MM:SS
            """
        else:
            help_text = """
🤖 **บอทจัดการสมาชิกกลุ่ม**

**คำสั่งที่รองรับ:**
/start - เริ่มต้นการทำงาน
/help - แสดงความช่วยเหลือ

**ฟีเจอร์หลัก:**
🔄 ตรวจสอบสมาชิกหมดอายุทุกชั่วโมง
👤 อัปเดต username อัตโนมัติ  
📊 จัดเก็บข้อมูลใน Google Sheets
🚀 เพิ่มสมาชิกอัตโนมัติเมื่อแอดมิน add ผ่าน UI

ℹ️ เฉพาะแอดมินเท่านั้นที่สามารถใช้คำสั่งจัดการได้
💬 ติดต่อแอดมินเพื่อขอความช่วยเหลือ
            """
        
        await update.message.reply_text(help_text)

    async def update_expire_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /updateexpire - อัปเดตวันหมดอายุของสมาชิก (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /updateexpire หรืออัปเดตวันหมดอายุของสมาชิก")
        
        user_id = update.effective_user.id
        
        if not config.is_admin(user_id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
            )
            return
        
        # ตรวจสอบรูปแบบคำสั่ง
        if len(context.args) < 2:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="📝 รูปแบบคำสั่ง:\n"
                     "/updateexpire user_id new_expire_date\n\n"
                     "ตัวอย่าง:\n"
                     "/updateexpire 123456789 2024-12-31 23:59:59"
            )
            return
        
        try:
            member_user_id = context.args[0]
            new_expire_date = " ".join(context.args[1:])  # รวมวันที่และเวลา
            
            # ตรวจสอบรูปแบบวันที่
            try:
                datetime.strptime(new_expire_date, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="❌ รูปแบบวันที่ไม่ถูกต้อง\n"
                         "ใช้รูปแบบ: YYYY-MM-DD HH:MM:SS\n"
                         "ตัวอย่าง: 2024-12-31 23:59:59"
                )
                return
            
            # ค้นหาข้อมูลสมาชิกก่อน
            members = self.sheets_manager.get_all_members()
            member_info = None
            
            for member in members:
                if member.get('User ID') == member_user_id:
                    member_info = member
                    break
            
            if not member_info:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"❌ ไม่พบสมาชิก User ID: {member_user_id} ใน Google Sheet"
                )
                return
            
            username = member_info.get('Username', 'Unknown')
            
            # อัปเดตวันหมดอายุ
            success = self.sheets_manager.update_member_expire_date(member_user_id, new_expire_date)
            
            if success:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"✅ อัปเดตวันหมดอายุสำเร็จ!\n"
                         f"👤 Username: {username}\n"
                         f"🆔 User ID: {member_user_id}\n"
                         f"📅 วันหมดอายุใหม่: {new_expire_date}"
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="❌ ไม่สามารถอัปเดตวันหมดอายุได้"
                )
                
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ เกิดข้อผิดพลาด: {str(e)}"
            )

    async def list_admins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /listadmins - แสดงรายชื่อแอดมินทั้งหมด (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /listadmins หรือแสดงรายชื่อแอดมินทั้งหมด")
        
        try:
            admin_list = config.get_admin_list()
            message = f"👥 รายชื่อแอดมินทั้งหมด ({len(admin_list)} คน):\n\n"
            
            for i, admin_id in enumerate(admin_list, 1):
                message += f"{i}. ID: `{admin_id}`\n"
            
            await self.send_safe_message(context, admin_group_id, message, 'Markdown')
            
        except Exception as e:
            await self.send_safe_message(context, admin_group_id, f"❌ เกิดข้อผิดพลาด: {str(e)}")


    async def set_check_interval_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """คำสั่ง /setcheckinterval - ตั้งค่าช่วงเวลาการตรวจสอบ (เฉพาะแอดมิน)"""
        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
        if admin_group_id:
            await context.bot.send_message(chat_id=admin_group_id, text="🚀 มีการใช้คำสั่ง /setcheckinterval หรือตั้งช่วงเวลาการตรวจสอบ")
        
        user_id = update.effective_user.id
        
        if not config.is_admin(user_id):
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้"
            )
            return
        
        # ตรวจสอบรูปแบบคำสั่ง
        if len(context.args) != 2:
            current_interval = config.get_check_interval_seconds()
            unit_display = {
                'seconds': 'วินาที',
                'minutes': 'นาที', 
                'hours': 'ชั่วโมง',
                'days': 'วัน'
            }
            
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"📝 **การตั้งค่าช่วงเวลาการตรวจสอบ**\n\n"
                     f"**ปัจจุบัน:** {config.CHECK_INTERVAL_VALUE} {unit_display.get(config.CHECK_INTERVAL_UNIT, config.CHECK_INTERVAL_UNIT)}\n"
                     f"({current_interval} วินาที)\n\n"
                     f"**รูปแบบคำสั่ง:**\n"
                     f"`/setcheckinterval ค่า หน่วย`\n\n"
                     f"**หน่วยที่รองรับ:**\n"
                     f"• `seconds` - วินาที\n"
                     f"• `minutes` - นาที\n" 
                     f"• hours - ชั่วโมง\n"
                     f"• days - วัน\n\n"
                     f"ตัวอย่าง:\n"
                     f"/setcheckinterval 30 minutes\n"
                     f"/setcheckinterval 2 hours\n"
                     f"/setcheckinterval 1 days"
            )
            return
        
        try:
            value = int(context.args[0])
            unit = context.args[1].lower()
            
            # ตรวจสอบหน่วยเวลา
            valid_units = ['seconds', 'minutes', 'hours', 'days']
            if unit not in valid_units:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=f"❌ หน่วยเวลาไม่ถูกต้อง\n"
                         f"ใช้ได้เฉพาะ: {', '.join(valid_units)}"
                )
                return
            
            # ตรวจสอบค่าที่สมเหตุสมผล
            if value <= 0:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="❌ ค่าช่วงเวลาต้องมากกว่า 0"
                )
                return
            
            # ตรวจสอบขีดจำกัด (ป้องกันการตั้งค่าที่อาจทำให้ระบบล่ม)
            total_seconds = value * {
                'seconds': 1,
                'minutes': 60,
                'hours': 3600,
                'days': 86400
            }[unit]
            
            if total_seconds < 10:  # น้อยกว่า 10 วินาที อาจมากเกินไป
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="⚠️ ช่วงเวลาสั้นเกินไป (ต้องมากกว่า 10 วินาที)"
                )
                return
            
            if total_seconds > 2592000:  # มากกว่า 30 วัน
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text="⚠️ ช่วงเวลายาวเกินไป (ต้องไม่เกิน 30 วัน)"
                )
                return
            
            # อัปเดตค่าใน config (ชั่วคราว - จะใช้ได้จนกว่าจะรีสตาร์ทบอท)
            config.CHECK_INTERVAL_VALUE = value
            config.CHECK_INTERVAL_UNIT = unit
            
            # รีสตาร์ท job queue
            if self.application.job_queue:
                # หยุด job เก่า
                current_jobs = self.application.job_queue.get_jobs_by_name("check_expired_members")
                for job in current_jobs:
                    job.schedule_removal()
                
                # สร้าง job ใหม่
                new_interval = config.get_check_interval_seconds()
                self.application.job_queue.run_repeating(
                    self.check_expired_members,
                    interval=new_interval,
                    first=10,
                    name="check_expired_members"
                )
            
            unit_display = {
                'seconds': 'วินาที',
                'minutes': 'นาที',
                'hours': 'ชั่วโมง', 
                'days': 'วัน'
            }
            
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"✅ ตั้งค่าช่วงเวลาสำเร็จ!\n\n"
                     f"ช่วงเวลาใหม่: {value} {unit_display[unit]}\n"
                     f"({total_seconds} วินาที)\n\n"
                     f"⚠️ หมายเหตุ: การตั้งค่านี้จะใช้ได้จนกว่าจะรีสตาร์ทบอท\n"
                     f"หากต้องการให้ถาวร ให้แก้ไขในไฟล์ config.py"
            )
            
        except ValueError:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text="❌ ค่าช่วงเวลาต้องเป็นตัวเลข"
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id=admin_group_id,
                text=f"❌ เกิดข้อผิดพลาด: {str(e)}"
            )

    async def track_chat_member_updates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ติดตามการเปลี่ยนแปลงสมาชิกในกลุ่ม (เฉพาะ invite link approval)"""
        result = await self.handle_chat_member_update(update.chat_member, context)
        if result:
            logger.info(f"Chat member update handled: {result}")

    async def handle_chat_member_update(self, chat_member_update, context):
        """จัดการการเปลี่ยนแปลงสถานะสมาชิก - เฉพาะ invite link approval และ username updates"""
        if not chat_member_update:
            return None

        old_member = chat_member_update.old_chat_member
        new_member = chat_member_update.new_chat_member
        user = new_member.user  # ใช้ user จาก new_member
        user_id = str(user.id)
        username = f"@{user.username}" if user.username else f"User_{user.id}"
        first_name = user.first_name or ""
        last_name = user.last_name or ""

        # ตรวจสอบการเพิ่มสมาชิกใหม่เข้ากลุ่ม
        if (old_member.status in ['left', 'kicked'] and 
            new_member.status in ['member', 'administrator', 'creator']):
            
            # ตรวจสอบว่าเป็นการเพิ่มในกลุ่มเป้าหมายหรือไม่
            target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
            if chat_member_update.chat.id == target_group_id:
                
                # ตรวจสอบว่ามีข้อมูลใน Google Sheet แล้วหรือไม่
                existing_members = self.sheets_manager.get_all_members()
                member_exists = any(member.get('User ID') == user_id for member in existing_members)
                
                # ตรวจสอบว่าอยู่ใน pending list แล้วหรือไม่ (ป้องกันการแจ้งเตือนซ้ำ)
                if user_id in self.pending_members:
                    logger.info(f"User {username} (ID: {user_id}) already in pending list, skipping duplicate notification")
                    return f"User already in pending list: {user_id}"
                
                if not member_exists:
                    # ตรวจสอบว่าเป็นการเพิ่มโดย admin หรือไม่
                    added_by_admin = False
                    if hasattr(chat_member_update, 'from_user') and chat_member_update.from_user:
                        added_by_user_id = chat_member_update.from_user.id
                        # ตรวจสอบว่าผู้เพิ่มเป็น admin หรือไม่
                        if config.is_admin(added_by_user_id):
                            added_by_admin = True
                    
                    if added_by_admin:
                        # เพิ่มโดย admin - เพิ่มเข้า Google Sheet โดยตรงด้วยอายุ default
                        from datetime import datetime, timedelta
                        import pytz
                        
                        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
                        expire_days = config.DEFAULT_EXPIRE_DAYS
                        default_expire = current_time + timedelta(days=expire_days)
                        expire_date_str = default_expire.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # เพิ่มเข้า Google Sheet ทันที
                        success = self.sheets_manager.add_member_with_details(
                            username, user_id, expire_date_str, first_name, last_name
                        )
                        
                        if success:
                            # แจ้งแอดมินว่าเพิ่มสำเร็จ
                            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
                            if admin_group_id:
                                await context.bot.send_message(
                                    chat_id=admin_group_id,
                                    text=f"✅ แอดมินเพิ่มสมาชิกใหม่ - บันทึกข้อมูลอัตโนมัติ\n"
                                         f"👤 Username: {username}\n"
                                         f"🆔 User ID: {user_id}\n"
                                         f"📅 หมดอายุ: {expire_date_str}\n"
                                         f"📊 วิธีการ: เพิ่มโดยแอดมินใน Telegram"
                                )
                            return f"Auto-added to Google Sheet: {username}"
                        else:
                            # ถ้าเพิ่มใน Google Sheet ไม่สำเร็จ แจ้งแอดมิน
                            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
                            if admin_group_id:
                                await context.bot.send_message(
                                    chat_id=admin_group_id,
                                    text=f"⚠️ แอดมินเพิ่มสมาชิกใหม่ แต่บันทึกข้อมูลไม่สำเร็จ\n"
                                         f"👤 Username: {username}\n"
                                         f"🆔 User ID: {user_id}\n"
                                         f"💡 กรุณาใช้คำสั่ง /addmember เพื่อเพิ่มข้อมูลด้วยตนเอง"
                                )
                    else:
                        # ไม่ใช่การเพิ่มโดย admin - ใส่ใน pending list สำหรับการอนุมัติ
                        from datetime import datetime, timedelta
                        import pytz
                        
                        # ตั้งค่าวันหมดอายุตามประเภทการเข้าร่วมล่าสุด
                        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
                        
                        # กำหนดวันหมดอายุตามประเภท invite link ที่ใช้จริง
                        # หาข้อมูล invite link ที่ใช้ (สำหรับกรณีนี้ไม่มี join_request object)
                        # ใช้วิธี fallback ตาม recent_join_type
                        join_type = "default"
                        
                        if self.recent_join_type == "1month":
                            expire_days = config.INVITE_LINK_1MONTH_DAYS
                            default_expire = current_time + timedelta(days=expire_days)
                            expire_date_str = default_expire.strftime('%Y-%m-%d %H:%M:%S')
                            join_type = self.recent_join_type
                        elif self.recent_join_type == "1year":
                            expire_days = config.INVITE_LINK_1YEAR_DAYS
                            default_expire = current_time + timedelta(days=expire_days)
                            expire_date_str = default_expire.strftime('%Y-%m-%d %H:%M:%S')
                            join_type = self.recent_join_type
                        elif self.recent_join_type == "noexpire":
                            expire_date_str = config.INVITE_LINK_NOEXPIRE
                            join_type = self.recent_join_type
                        else:
                            # สำหรับการเข้าแบบปกติหรือ custom
                            expire_days = config.DEFAULT_EXPIRE_DAYS
                            default_expire = current_time + timedelta(days=expire_days)
                            expire_date_str = default_expire.strftime('%Y-%m-%d %H:%M:%S')
                        
                        logger.info(f"⚙️ Member update - Type: {join_type}, Expire: {expire_date_str}")
                        
                        # เพิ่มใน pending list
                        self.pending_members[user_id] = {
                            'username': username,
                            'first_name': first_name,
                            'last_name': last_name,
                            'join_type': join_type,
                            'expire_date_str': expire_date_str,
                            'timestamp': current_time.strftime('%d/%m/%Y %H:%M:%S')
                        }
                        
                        # รีเซ็ตประเภทการเข้าร่วมกลับเป็น default หลังจากใช้แล้ว
                        self.recent_join_type = "default"
                    
                        # แจ้งเตือนแอดมินด้วยปุ่ม approve/reject (เฉพาะการเข้าผ่าน invite link)
                        await self.notify_all_admins_with_buttons(context, user_id, username, first_name, last_name, expire_date_str)
                    
                    logger.info(f"New member added to pending list: {username} (ID: {user_id})")
                    return f"New member pending approval: {user_id}"

        # ตรวจสอบการเปลี่ยนแปลง username
        elif old_member and new_member and old_member.status == new_member.status:
            old_username = old_member.user.username
            new_username = new_member.user.username

            if old_username != new_username and new_username:
                # อัปเดต username ใน Google Sheets
                success = self.sheets_manager.update_username(user_id, f"@{new_username}")
                if success:
                    logger.info(f"Updated username for user {user_id}: {old_username} -> @{new_username}")
                    return f"Username updated: {user_id}"

        return None

    async def handle_chat_join_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """จัดการคำขอเข้าร่วมกลุ่ม (Chat Join Request)"""
        logger.info("🔔 Received chat join request")
        
        if not update.chat_join_request:
            logger.warning("No chat_join_request in update")
            return
        
        join_request = update.chat_join_request
        user = join_request.from_user
        user_id = str(user.id)
        username = f"@{user.username}" if user.username else f"User_{user.id}"
        first_name = user.first_name or ""
        last_name = user.last_name or ""
        
        logger.info(f"👤 Join request from: {username} (ID: {user_id})")
        logger.info(f"🎯 Request for chat ID: {join_request.chat.id}")
        
        # ตรวจสอบว่าเป็นการขอเข้าในกลุ่มเป้าหมายหรือไม่
        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
        logger.info(f"🎯 Target group ID: {target_group_id}")
        
        if join_request.chat.id != target_group_id:
            logger.info(f"❌ Chat ID mismatch. Expected: {target_group_id}, Got: {join_request.chat.id}")
            return
        
        # ตรวจสอบว่ามีข้อมูลใน Google Sheet แล้วหรือไม่
        existing_members = self.sheets_manager.get_all_members()
        member_exists = any(member.get('User ID') == user_id for member in existing_members)
        
        logger.info(f"📊 Member exists in sheet: {member_exists}")
        
        # ตรวจสอบว่าอยู่ใน pending list แล้วหรือไม่ (ป้องกันการแจ้งเตือนซ้ำ)
        """ if user_id in self.pending_members:
            logger.info(f"User {username} (ID: {user_id}) already in pending list, skipping duplicate notification")
            return """
        
        if not member_exists:
            # กำหนดวันหมดอายุตามประเภท invite link ที่ใช้จริง
            from datetime import datetime, timedelta
            import pytz
            
            current_time = datetime.now(pytz.timezone(config.TIMEZONE))
            
            # หาข้อมูล invite link ที่ใช้จาก join_request
            invite_link_used = None
            link_info = None
            join_type = "default"
            
            # ทำความสะอาด links ที่หมดอายุก่อน
            self._cleanup_expired_invite_links()
            
            # ตรวจสอบ invite_link จาก join_request
            if hasattr(join_request, 'invite_link') and join_request.invite_link:
                if hasattr(join_request.invite_link, 'invite_link'):
                    invite_link_used = join_request.invite_link.invite_link
                else:
                    invite_link_used = str(join_request.invite_link)
                logger.info(f"🔗 Invite link found in join_request: {invite_link_used}")
            else:
                logger.info("📭 No invite_link found in join_request")
            
            # ตรวจสอบในรายการ invite links ทั้งหมด
            active_links = list(self.active_invite_links.keys())
            logger.info(f"📚 Available active invite links: {len(active_links)} links")
            for link in active_links:
                logger.info(f"   - {link}: {self.active_invite_links[link]}")
            
            # ลองหาจาก exact match ก่อน
            if invite_link_used and invite_link_used in self.active_invite_links:
                link_info = self.active_invite_links[invite_link_used]
                logger.info(f"✅ Exact match found for {invite_link_used}: {link_info}")
            
            # หากไม่เจอให้ลองใช้ partial matching (เผื่อมี query parameters)
            elif invite_link_used and not link_info:
                for stored_link, stored_info in self.active_invite_links.items():
                    if invite_link_used in stored_link or stored_link in invite_link_used:
                        link_info = stored_info
                        logger.info(f"🔍 Partial match found: {stored_link} matches {invite_link_used}")
                        break
            
            # หากยังไม่เจอ ให้ใช้ link ที่สร้างล่าสุด (ภายใน 5 นาที)
            if not link_info and self.invite_link_expires:
                recent_threshold = current_time - timedelta(minutes=5)
                recent_links = []
                
                for link, info in self.invite_link_expires.items():
                    if info.get('created_time', current_time) > recent_threshold:
                        recent_links.append((link, info))
                
                if recent_links:
                    # เอา link ล่าสุด
                    latest_link = max(recent_links, key=lambda x: x[1].get('created_time', current_time))
                    link_info = {
                        'type': latest_link[1]['type'],
                        'days': latest_link[1]['days'],
                        'period_name': latest_link[1]['period_name']
                    }
                    invite_link_used = latest_link[0]
                    logger.info(f"🕐 Using recent link (within 5 min): {invite_link_used} with info: {link_info}")
            
            if link_info:
                # ใช้ข้อมูลจาก invite link ที่ใช้จริง
                days = link_info['days']
                join_type = link_info['type']
                
                if days == "no_expire":
                    expire_date_str = config.INVITE_LINK_NOEXPIRE
                else:
                    default_expire = current_time + timedelta(days=days)
                    expire_date_str = default_expire.strftime('%Y-%m-%d %H:%M:%S')
                
                logger.info(f"✅ Final result - Type: {join_type}, Days: {days}, Expire: {expire_date_str}")
            else:
                # Fallback สุดท้าย: ใช้ค่า default
                expire_days = config.DEFAULT_EXPIRE_DAYS
                default_expire = current_time + timedelta(days=expire_days)
                expire_date_str = default_expire.strftime('%Y-%m-%d %H:%M:%S')
                
                logger.info(f"⚠️ Using default fallback - Type: {join_type}, Days: {expire_days}, Expire: {expire_date_str}")
            
            # เพิ่มใน pending list พร้อม join_request object
            self.pending_members[user_id] = {
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'join_type': join_type,
                'expire_date_str': expire_date_str,
                'timestamp': current_time.strftime('%d/%m/%Y %H:%M:%S'),
                'join_request': join_request  # เก็บ join request object
            }
            
            # รีเซ็ตประเภทการเข้าร่วมกลับเป็น default หลังจากใช้แล้ว
            self.recent_join_type = "default"
            
            # แจ้งเตือนแอดมินด้วยปุ่ม approve/reject
            logger.info(f"📤 Sending notification to admin group for user {user_id}")
            await self.notify_all_admins_with_join_request_buttons(context, user_id, username, first_name, last_name, expire_date_str)
            
            logger.info(f"✅ New join request added to pending list: {username} (ID: {user_id})")
        else:
            logger.info(f"ℹ️ User {username} (ID: {user_id}) already exists in sheet, skipping")

    async def send_safe_message(self, context, user_id: int, text: str, parse_mode: str = None, fallback_to_admin_group: bool = True):
        """ส่งข้อความไปยังกลุ่มแอดมินเท่านั้น"""
        try:
            # ส่งไปยังกลุ่มแอดมินเท่านั้น
            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
            if admin_group_id:
                await context.bot.send_message(
                    chat_id=admin_group_id,
                    text=text,
                    parse_mode=parse_mode
                )
                return True
            else:
                logger.error("GROUP_CHAT_ID_FOR_ADMIN not configured")
                return False
        except Exception as e:
            logger.error(f"Cannot send message to admin group: {e}")
            return False

    async def notify_all_admins(self, message: str, parse_mode: str = None):
        """ส่งข้อความไปยังกลุ่มแอดมิน"""
        if hasattr(self, 'application') and self.application:
            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
            if admin_group_id:
                try:
                    await self.application.bot.send_message(
                        chat_id=admin_group_id,
                        text=message,
                        parse_mode=parse_mode
                    )
                    logger.info("Notification sent to admin group")
                except Exception as e:
                    logger.error(f"Cannot send message to admin group: {e}")
            else:
                logger.error("GROUP_CHAT_ID_FOR_ADMIN not configured")

    async def notify_all_admins_with_buttons(self, context, user_id: str, username: str, first_name: str, last_name: str, expire_date_str: str):
        """ส่งข้อความไปยังกลุ่มแอดมินพร้อมปุ่ม approve/reject"""
        try:
            # ตรวจสอบว่าอยู่ใน pending list แล้วหรือไม่ (ป้องกันการแจ้งเตือนซ้ำ)
            if user_id not in self.pending_members:
                logger.warning(f"User {user_id} not found in pending_members, skipping notification")
                return
            
            # ตรวจสอบว่าได้ส่งการแจ้งเตือนไปแล้วหรือไม่ (ป้องกันการแจ้งเตือนซ้ำ)
            notification_key = f"member_update_{user_id}"
            if notification_key in self.sent_notifications:
                logger.info(f"Notification for user {user_id} already sent, skipping duplicate")
                return
            
            # สร้างปุ่ม approve/reject
            keyboard = [
                [
                    InlineKeyboardButton("✅ อนุมัติ", callback_data=f"approve_{user_id}"),
                    InlineKeyboardButton("❌ ปฏิเสธ", callback_data=f"reject_{user_id}")
                ],
                [InlineKeyboardButton("📋 รายการรออนุมัติ", callback_data="pending_list")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # สร้างข้อความแจ้งเตือน
            member_display_name = f"{first_name} {last_name}".strip() or username
            message = (
                f"👤 **สมาชิกใหม่รออนุมัติ**\n\n"
                f"👤 ชื่อ: {member_display_name}\n"
                f"🏷️ Username: {username}\n"
                f"🆔 User ID: `{user_id}`\n"
                f"📅 วันหมดอายุ: {expire_date_str}\n\n"
                f"📝 **กดปุ่มด้านล่างเพื่อตัดสินใจ:**\n"
                f"✅ อนุมัติ → เพิ่มเข้า Google Sheets\n"
                f"❌ ปฏิเสธ → kick ออกจากกลุ่มทันที"
            )
            
            # ส่งไปยังกลุ่มแอดมินเท่านั้น
            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
            if admin_group_id:
                try:
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=message,
                        reply_markup=reply_markup
                    )
                    
                    # บันทึกว่าส่งการแจ้งเตือนแล้ว
                    self.sent_notifications.add(notification_key)
                    logger.info(f"Notification sent to admin group for user {user_id} (member update)")
                    
                except Exception as group_error:
                    logger.error(f"Cannot send message to admin group: {group_error}")
            else:
                logger.error("GROUP_CHAT_ID_FOR_ADMIN not configured")
            
        except Exception as e:
            logger.error(f"Error in notify_all_admins_with_buttons: {e}")

    async def notify_all_admins_with_join_request_buttons(self, context, user_id: str, username: str, first_name: str, last_name: str, expire_date_str: str):
        """ส่งข้อความไปยังกลุ่มแอดมินพร้อมปุ่ม approve/reject สำหรับ join request"""
        logger.info(f"🔔 Starting notification process for user {user_id}")
        
        try:
            # ตรวจสอบว่าอยู่ใน pending list แล้วหรือไม่ (ป้องกันการแจ้งเตือนซ้ำ)
            if user_id not in self.pending_members:
                logger.warning(f"User {user_id} not found in pending_members, skipping notification")
                return
            
            # ตรวจสอบว่าได้ส่งการแจ้งเตือนไปแล้วหรือไม่ (ป้องกันการแจ้งเตือนซ้ำ)
            notification_key = f"join_request_{user_id}"
            if notification_key in self.sent_notifications:
                logger.info(f"Notification for user {user_id} already sent, skipping duplicate")
                return
            
            # สร้างปุ่ม approve/reject
            keyboard = [
                [
                    InlineKeyboardButton("✅ อนุมัติ", callback_data=f"approve_join_{user_id}"),
                    InlineKeyboardButton("❌ ปฏิเสธ", callback_data=f"reject_join_{user_id}")
                ],
                [InlineKeyboardButton("📋 รายการรออนุมัติ", callback_data="pending_list")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # สร้างข้อความแจ้งเตือน
            member_display_name = f"{first_name} {last_name}".strip() or username
            message = (
                f"🔔 คำขอเข้าร่วมกลุ่มใหม่\n\n"
                f"👤 ชื่อ: {member_display_name}\n"
                f"🏷️ Username: {username}\n"
                f"🆔 User ID: {user_id}\n"
                f"📅 วันหมดอายุ: {expire_date_str}\n\n"
                f"📝 กดปุ่มด้านล่างเพื่อตัดสินใจ:\n"
                f"✅ อนุมัติ → อนุญาตเข้ากลุ่ม + เพิ่มเข้า Google Sheets\n"
                f"❌ ปฏิเสธ → ปฏิเสธคำขอเข้ากลุ่ม"
            )
            
            # ส่งไปยังกลุ่มแอดมินเท่านั้น
            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
            logger.info(f"🎯 Admin group ID: {admin_group_id}")
            
            if admin_group_id:
                try:
                    logger.info(f"📤 Attempting to send message to admin group {admin_group_id}")
                    await context.bot.send_message(
                        chat_id=admin_group_id,
                        text=message,
                        reply_markup=reply_markup
                    )
                    
                    # บันทึกว่าส่งการแจ้งเตือนแล้ว
                    self.sent_notifications.add(notification_key)
                    logger.info(f"✅ Notification sent to admin group for user {user_id} (join request)")
                    
                except Exception as group_error:
                    logger.error(f"❌ Cannot send message to admin group: {group_error}")
            else:
                logger.error("❌ GROUP_CHAT_ID_FOR_ADMIN not configured")
            
        except Exception as e:
            logger.error(f"Error in notify_all_admins_with_join_request_buttons: {e}")

    async def notify_admin_new_member(self, username: str, user_id: str, expire_date: str, member_type: str = "ไม่ระบุ"):
        """แจ้งเตือนแอดมินเมื่อมีสมาชิกใหม่เข้าร่วม"""
        try:
            message = (
                f"👤 สมาชิกใหม่เข้าร่วมกลุ่ม\n\n"
                f"Username: {username}\n"
                f"User ID: {user_id}\n"
                f"🏷️ ประเภท: {member_type}\n"
                f"📅 วันหมดอายุ: {expire_date}\n\n"
                f"💡 สมาชิกได้รับการตั้งค่าอัตโนมัติตาม invite link ที่ใช้"
            )
            
            # ส่งข้อความไปยังแอดมินทุกคน
            await self.notify_all_admins(message)
            
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")

    async def handle_approval_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """จัดการ callback จากปุ่ม approve/reject"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if not config.is_admin(user_id):
            await query.edit_message_text("❌ คุณไม่มีสิทธิ์ใช้ฟังก์ชันนี้")
            return
        
        # แยกข้อมูลจาก callback_data
        if query.data == "pending_list":
            await self.show_pending_list_callback(update, context)
            return
        
        # ตรวจสอบว่าเป็น join request หรือ chat member update
        if "join_" in query.data:
            action_parts = query.data.split("_")
            action = action_parts[0]  # approve หรือ reject
            member_user_id = action_parts[2]  # user_id
            is_join_request = True
        else:
            action, member_user_id = query.data.split("_", 1)
            is_join_request = False
        
        if member_user_id not in self.pending_members:
            await query.edit_message_text("❌ ไม่พบข้อมูลสมาชิกรออนุมัติ")
            return
        
        member_info = self.pending_members[member_user_id]
        username = member_info['username']
        first_name = member_info['first_name']
        last_name = member_info['last_name']
        expire_date_str = member_info['expire_date_str']
        
        if action == "approve":
            if is_join_request:
                # อนุมัติ join request - อนุญาตเข้ากลุ่ม + เพิ่มเข้า Google Sheets
                join_request = member_info.get('join_request')
                if join_request:
                    try:
                        # อนุมัติ join request
                        await context.bot.approve_chat_join_request(
                            chat_id=join_request.chat.id,
                            user_id=int(member_user_id)
                        )
                        
                        # เพิ่มเข้า Google Sheets
                        success = self.sheets_manager.add_member_with_details(
                            username, member_user_id, expire_date_str, first_name, last_name
                        )
                        
                        if success:
                            # ลบออกจาก pending list
                            del self.pending_members[member_user_id]
                            
                            # ล้างข้อมูลการแจ้งเตือน
                            notification_key = f"join_request_{member_user_id}"
                            if notification_key in self.sent_notifications:
                                self.sent_notifications.remove(notification_key)
                            
                            # อัปเดตข้อความ
                            await query.edit_message_text(
                                f"✅ อนุมัติคำขอเข้าร่วมสำเร็จ\n\n"
                                f"👤 {username}\n"
                                f"🆔 User ID: {member_user_id}\n"
                                f"📅 วันหมดอายุ: {expire_date_str}\n"
                                f"🎉 อนุญาตเข้ากลุ่มและเพิ่มเข้า Google Sheets แล้ว\n\n"
                                f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
                            )
                            
                            logger.info(f"Join request approved: {username} (ID: {member_user_id})")
                        else:
                            await query.edit_message_text(
                                f"⚠️ อนุมัติเข้ากลุ่มแล้ว แต่เกิดข้อผิดพลาด\n\n"
                                f"👤 {username}\n"
                                f"✅ อนุญาตเข้ากลุ่มสำเร็จ\n"
                                f"❌ ไม่สามารถเพิ่มใน Google Sheets ได้\n"
                                f"💡 กรุณาเพิ่มด้วยตนเองหรือลองใหม่"
                            )
                    except Exception as approve_error:
                        logger.error(f"Error approving join request for {member_user_id}: {approve_error}")
                        
                        # ล้างข้อมูลการแจ้งเตือนแม้จะเกิดข้อผิดพลาด
                        notification_key = f"join_request_{member_user_id}"
                        if notification_key in self.sent_notifications:
                            self.sent_notifications.remove(notification_key)
                        
                        await query.edit_message_text(
                            f"❌ เกิดข้อผิดพลาด\n\n"
                            f"👤 {username}\n"
                            f"❌ ไม่สามารถอนุมัติคำขอเข้าร่วมได้\n"
                            f"💡 {str(approve_error)}"
                        )
                else:
                    await query.edit_message_text("❌ ไม่พบข้อมูล join request")
            else:
                # อนุมัติสมาชิก - เพิ่มเข้า Google Sheets (กรณีเข้ากลุ่มแล้ว)
                success = self.sheets_manager.add_member_with_details(
                    username, member_user_id, expire_date_str, first_name, last_name
                )
                
                if success:
                    # ลบออกจาก pending list
                    del self.pending_members[member_user_id]
                    
                    # ล้างข้อมูลการแจ้งเตือน
                    notification_key = f"member_update_{member_user_id}"
                    if notification_key in self.sent_notifications:
                        self.sent_notifications.remove(notification_key)
                    
                    # อัปเดตข้อความ
                    await query.edit_message_text(
                        f"✅ อนุมัติสมาชิกสำเร็จ\n\n"
                        f"👤 {username}\n"
                        f"🆔 User ID: {member_user_id}\n"
                        f"📅 วันหมดอายุ: {expire_date_str}\n\n"
                        f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
                    )
                    
                    logger.info(f"Member approved: {username} (ID: {member_user_id})")
                else:
                    # ล้างข้อมูลการแจ้งเตือนแม้จะเกิดข้อผิดพลาด
                    notification_key = f"member_update_{member_user_id}"
                    if notification_key in self.sent_notifications:
                        self.sent_notifications.remove(notification_key)
                    
                    await query.edit_message_text(
                        f"❌ เกิดข้อผิดพลาด\n\n"
                        f"ไม่สามารถเพิ่มสมาชิก {username} ใน Google Sheets\n"
                        f"กรุณาลองใหม่อีกครั้ง"
                    )
                
        elif action == "reject":
            if is_join_request:
                # ปฏิเสธ join request - ปฏิเสธคำขอเข้าร่วม
                join_request = member_info.get('join_request')
                if join_request:
                    try:
                        # ปฏิเสธ join request
                        await context.bot.decline_chat_join_request(
                            chat_id=join_request.chat.id,
                            user_id=int(member_user_id)
                        )
                        # Unban ทันที เพื่อให้ user ส่ง join request ใหม่ได้
                        await context.bot.unban_chat_member(
                            chat_id=join_request.chat.id,
                            user_id=int(member_user_id)
                        )
                        # ลบออกจาก pending list
                        del self.pending_members[member_user_id]
                        
                        # ล้างข้อมูลการแจ้งเตือน
                        notification_key = f"join_request_{member_user_id}"
                        if notification_key in self.sent_notifications:
                            self.sent_notifications.remove(notification_key)
                        
                        # อัปเดตข้อความ
                        await query.edit_message_text(
                            f"❌ ปฏิเสธคำขอเข้าร่วมสำเร็จ\n\n"
                            f"👤 {username}\n"
                            f"🆔 User ID: {member_user_id}\n"
                            f"🚫 ปฏิเสธคำขอเข้ากลุ่มแล้ว\n\n"
                            f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
                        )
                        
                        logger.info(f"Join request declined: {username} (ID: {member_user_id})")
                        
                    except Exception as decline_error:
                        logger.error(f"Error declining join request for {member_user_id}: {decline_error}")
                        
                        # ล้างข้อมูลการแจ้งเตือนแม้จะเกิดข้อผิดพลาด
                        notification_key = f"join_request_{member_user_id}"
                        if notification_key in self.sent_notifications:
                            self.sent_notifications.remove(notification_key)
                        
                        await query.edit_message_text(
                            f"❌ เกิดข้อผิดพลาด\n\n"
                            f"👤 {username}\n"
                            f"❌ ไม่สามารถปฏิเสธคำขอเข้าร่วมได้\n"
                            f"💡 {str(decline_error)}"
                        )
                else:
                    await query.edit_message_text("❌ ไม่พบข้อมูล join request")
            else:
                # ปฏิเสธสมาชิก - kick ออกจากกลุ่ม (กรณีเข้ากลุ่มแล้ว)
                target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
                
                try:
                    # ตรวจสอบว่าบอทมีสิทธิ์ admin ในกลุ่มหรือไม่
                    bot_member = await context.bot.get_chat_member(target_group_id, context.bot.id)
                    if bot_member.status not in ['administrator', 'creator']:
                        await query.edit_message_text(
                            f"⚠️ ไม่สามารถปฏิเสธสมาชิกได้\n\n"
                            f"👤 {username}\n"
                            f"❌ บอทไม่มีสิทธิ์ admin ในกลุ่ม\n"
                            f"💡 กรุณาให้สิทธิ์ admin แก่บอทเพื่อ kick สมาชิก"
                        )
                        return
                    
                    # Kick สมาชิกออกจากกลุ่ม
                    await context.bot.ban_chat_member(
                        chat_id=target_group_id,
                        user_id=int(member_user_id)
                    )
                    
                    # Unban ทันที (เพื่อให้สามารถเข้าได้อีกในอนาคต)
                    await context.bot.unban_chat_member(
                        chat_id=target_group_id,
                        user_id=int(member_user_id)
                    )
                    
                    # ลบออกจาก pending list
                    del self.pending_members[member_user_id]
                    
                    # ล้างข้อมูลการแจ้งเตือน
                    # (commented out for debugging or future use)
                    # notification_key = f"member_update_{member_user_id}"
                    # if notification_key in self.sent_notifications:
                    #     self.sent_notifications.remove(notification_key)
                    
                    # อัปเดตข้อความ
                    await query.edit_message_text(
                        f"❌ ปฏิเสธสมาชิกสำเร็จ\n\n"
                        f"👤 {username}\n"
                        f"🆔 User ID: {member_user_id}\n"
                        f"🚪 ถูก kick ออกจากกลุ่มแล้ว\n\n"
                        f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
                    )
                    
                    logger.info(f"Member rejected and kicked: {username} (ID: {member_user_id})")
                    
                except Exception as kick_error:
                    logger.error(f"Error kicking member {member_user_id}: {kick_error}")
                    
                    # ลบออกจาก pending list แต่แจ้งว่า kick ไม่สำเร็จ
                    del self.pending_members[member_user_id]
                    
                    # ล้างข้อมูลการแจ้งเตือน
                    notification_key = f"member_update_{member_user_id}"
                    if notification_key in self.sent_notifications:
                        self.sent_notifications.remove(notification_key)
                    
                    await query.edit_message_text(
                        f"⚠️ ปฏิเสธสมาชิก (บางส่วน)\n\n"
                        f"👤 {username}\n"
                        f"🆔 User ID: {member_user_id}\n"
                        f"❌ ไม่สามารถ kick ออกจากกลุ่มได้\n"
                        f"💡 อาจต้อง kick ด้วยตนเอง\n\n"
                        f"ดำเนินการโดย: {query.from_user.first_name or 'Admin'}"
                    )

    async def show_pending_list_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """แสดงรายการสมาชิกรออนุมัติ"""
        query = update.callback_query
        
        if not self.pending_members:
            await query.edit_message_text("📋 รายการรออนุมัติ\n\n✅ ไม่มีสมาชิกรออนุมัติ")
            return
        
        message = "📋 รายการสมาชิกรออนุมัติ\n\n"
        
        for user_id, member_info in self.pending_members.items():
            username = member_info['username']
            timestamp = member_info['timestamp']
            expire_date = member_info['expire_date_str']
            
            message += (
                f"👤 {username}\n"
                f"🆔 ID: {user_id}\n"
                f"⏰ เวลา: {timestamp} ({config.TIMEZONE})\n"
                f"📅 หมดอายุ: {expire_date}\n"
                f"---\n"
            )
        
        # สร้างปุ่มสำหรับแต่ละสมาชิก
        keyboard = []
        for user_id, member_info in self.pending_members.items():
            username = member_info['username']
            keyboard.append([
                InlineKeyboardButton(f"✅ อนุมัติ {username}", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton(f"❌ ปฏิเสธ {username}", callback_data=f"reject_{user_id}")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    async def check_expired_members(self, context: ContextTypes.DEFAULT_TYPE):
        """ตรวจสอบและลบสมาชิกที่หมดอายุ (จะถูกเรียกทุกชั่วโมง)"""
        # ใช้ group_chat_id จาก config หรือที่ตั้งค่าไว้
        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
        
        if not target_group_id:
            logger.warning("Group chat ID not set, cannot remove expired members")
            return

        try:
            expired_members = self.sheets_manager.get_expired_members()
            
            if not expired_members:
                logger.info("No expired members found")
                return

            logger.info(f"Found {len(expired_members)} expired members")
            
            for member in expired_members:
                user_id = member.get('User ID')
                expire_date = member.get('Expiredate', '')
                
                # ข้ามสมาชิกที่ไม่หมดอายุ (no_expire หรือ INVITE_LINK_NOEXPIRE)
                if expire_date == "no_expire" or expire_date == config.INVITE_LINK_NOEXPIRE:
                    logger.info(f"Skipping user {user_id} (no expire: {expire_date})")
                    continue
                username = member.get('Username', 'Unknown')
                
                if user_id:
                    try:
                        # ลบสมาชิกออกจากกลุ่ม
                        await context.bot.ban_chat_member(
                            chat_id=target_group_id,
                            user_id=int(user_id)
                        )
                        
                        # ยกเลิกการแบนทันที (เพื่อให้สามารถเข้าร่วมใหม่ได้ในอนาคต)
                        await context.bot.unban_chat_member(
                            chat_id=target_group_id,
                            user_id=int(user_id)
                        )
                        
                        # ลบข้อมูลจาก Google Sheet
                        self.sheets_manager.remove_member_from_sheet(user_id)
                        
                        logger.info(f"Removed expired member: {username} (ID: {user_id})")
                        
                        # ส่งข้อความแจ้งเตือนในกลุ่ม
                        await context.bot.send_message(
                            chat_id=target_group_id,
                            text=f"⚠️ สมาชิก {username} ถูกลบออกจากกลุ่มเนื่องจากหมดอายุ"
                        )
                        
                        # แจ้งเตือนไปยังแอดมินทุกคนใน private chat
                        try:
                            await self.notify_all_admins(f"🚫 ลบสมาชิกหมดอายุ: {username} (ID: {user_id})")
                        except Exception as admin_notify_error:
                            logger.error(f"Cannot notify admin: {admin_notify_error}")
                        
                        # หน่วงเวลาเล็กน้อยเพื่อป้องกัน rate limiting
                        await asyncio.sleep(1)
                        
                    except Forbidden:
                        logger.error(f"Bot doesn't have permission to remove user {user_id}")
                    except BadRequest as e:
                        if "User not found" in str(e):
                            logger.info(f"User {user_id} already left the group")
                            # ลบออกจาก sheet เนื่องจากไม่อยู่ในกลุ่มแล้ว
                            self.sheets_manager.remove_member_from_sheet(user_id)
                        else:
                            logger.error(f"Error removing user {user_id}: {e}")
                    except Exception as e:
                        logger.error(f"Unexpected error removing user {user_id}: {e}")

        except Exception as e:
            logger.error(f"Error in check_expired_members: {e}")

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """จัดการข้อผิดพลาด"""
        logger.error(f"Update {update} caused error {context.error}")

    async def setup_handlers(self):
        """ตั้งค่า handlers สำหรับบอท"""
        if not self.application:
            return

        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("checknow", self.check_now_command))
        self.application.add_handler(CommandHandler("listexpired", self.list_expired_command))
        self.application.add_handler(CommandHandler("addmember", self.add_member_command))
        self.application.add_handler(CommandHandler("removemember", self.remove_member_command))
        self.application.add_handler(CommandHandler("listmembers", self.list_members_command))
        self.application.add_handler(CommandHandler("pendingmembers", self.pending_members_command))
        self.application.add_handler(CommandHandler("updateexpire", self.update_expire_command))
        self.application.add_handler(CommandHandler("setcheckinterval", self.set_check_interval_command))
        self.application.add_handler(CommandHandler("invitelink", self.invite_link_command))
        self.application.add_handler(CommandHandler("invitelink1month", self.invite_link_1month_command))
        self.application.add_handler(CommandHandler("invitelink1year", self.invite_link_1year_command))
        self.application.add_handler(CommandHandler("invitelinknoexpire", self.invite_link_no_expire_command))
        self.application.add_handler(CommandHandler("listadmins", self.list_admins_command))
        
        # Chat member handler สำหรับติดตามการเปลี่ยนแปลง username
        self.application.add_handler(ChatMemberHandler(
            self.track_chat_member_updates, 
            ChatMemberHandler.CHAT_MEMBER
        ))
        
        # Chat join request handler สำหรับจัดการคำขอเข้าร่วม
        self.application.add_handler(ChatJoinRequestHandler(self.handle_chat_join_request))
        
        # Callback query handler สำหรับปุ่ม approve/reject
        self.application.add_handler(CallbackQueryHandler(self.handle_approval_callback))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
        
        # ตั้งค่า Bot Commands สำหรับ suggested commands
        await self.setup_bot_commands()
        
    async def setup_bot_commands(self):
        """ตั้งค่า Bot Commands สำหรับ suggested commands"""
        try:
            from telegram import BotCommand
            
            # กำหนดคำสั่งสำหรับแอดมิน
            admin_commands = [
                BotCommand("start", "🚀 เริ่มต้นการทำงาน"),
                BotCommand("help", "❓ แสดงความช่วยเหลือ"),
                BotCommand("status", "📊 สถานะระบบ"),
                BotCommand("checknow", "🔍 ตรวจสอบสมาชิกหมดอายุทันที"),
                BotCommand("listexpired", "⚠️ รายชื่อสมาชิกหมดอายุ"),
                BotCommand("addmember", "➕ เพิ่มสมาชิกใหม่"),
                BotCommand("removemember", "🗑️ ลบสมาชิก"),
                BotCommand("listmembers", "👥 รายชื่อสมาชิกทั้งหมด"),
                BotCommand("pendingmembers", "⏳ รายการรออนุมัติ"),
                BotCommand("updateexpire", "📅 อัปเดตวันหมดอายุ"),
                BotCommand("setcheckinterval", "⏰ ตั้งช่วงเวลาตรวจสอบ"),
                BotCommand("invitelink", "🔗 สร้างลิงก์เชิญกำหนดเอง"),
                BotCommand("invitelink1month", "🔗 สร้างลิงก์เชิญ (1 เดือน)"),
                BotCommand("invitelink1year", "🔗 สร้างลิงก์เชิญ (1 ปี)"),
                BotCommand("invitelinknoexpire", "🔗 สร้างลิงก์เชิญ (ไม่หมดอายุ)"),
                BotCommand("listadmins", "👑 รายชื่อแอดมิน")
            ]
            
            # กำหนดคำสั่งสำหรับผู้ใช้ทั่วไป
            user_commands = [
                BotCommand("start", "🚀 เริ่มต้นการทำงาน"),
                BotCommand("help", "❓ แสดงความช่วยเหลือ")
            ]
            
            # ตั้งค่า commands สำหรับบอท
            await self.application.bot.set_my_commands(
                commands=admin_commands,
                scope=BotCommandScopeDefault()
            )
            
            logger.info("✅ Bot commands setup complete")
            
        except Exception as e:
            logger.error(f"Error setting up bot commands: {e}")
    
    async def _setup_job_queue(self, job_queue, interval_seconds):
        """ตั้งค่า job queue ใน async context"""
        try:
            job_queue.run_repeating(
                self.check_expired_members,
                interval=interval_seconds,
                first=10,  # เริ่มหลังจาก 10 วินาที
                name="check_expired_members"
            )
            
            # แสดงข้อมูลการตั้งค่า
            unit_display = {
                'seconds': 'วินาที',
                'minutes': 'นาที',
                'hours': 'ชั่วโมง',
                'days': 'วัน'
            }
            
            logger.info(f"✅ Job queue ตรวจสอบสมาชิกหมดอายุติดตั้งเรียบร้อย")
            logger.info(f"⏰ ช่วงเวลา: ทุกๆ {config.CHECK_INTERVAL_VALUE} {unit_display.get(config.CHECK_INTERVAL_UNIT, config.CHECK_INTERVAL_UNIT)}")
        except Exception as e:
            logger.error(f"Error setting up job queue: {e}")

    async def run(self):
        """เริ่มการทำงานของบอท"""
        if not config.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
            return

        try:
            # สร้าง Application
            self.application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
            
            # ตั้งค่า handlers
            await self.setup_handlers()
            
            logger.info("🚀 Starting Telegram Member Management Bot...")
            
            # เริ่มการทำงาน (async method สำหรับ v22.0)
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            
            # รอจนกว่าจะหยุด (ใช้ asyncio.Event)
            stop_event = asyncio.Event()
            
            # ตั้งค่า signal handler สำหรับ graceful shutdown
            def signal_handler():
                stop_event.set()
            
            try:
                await stop_event.wait()
            except KeyboardInterrupt:
                logger.info("🛑 Received interrupt signal")
            finally:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            
        except Exception as e:
            logger.error(f"Error in run method: {e}")
            if self.application:
                try:
                    await self.application.updater.stop()
                    await self.application.stop()
                    await self.application.shutdown()
                except Exception as shutdown_error:
                    logger.error(f"Error during shutdown: {shutdown_error}")
            raise

    async def stop(self):
        """หยุดการทำงานของบอท"""
        if self.application:
            try:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
                logger.info("🛑 Bot stopped")
            except Exception as e:
                logger.error(f"Error stopping bot: {e}")


if __name__ == "__main__":
    bot = TelegramMemberBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")