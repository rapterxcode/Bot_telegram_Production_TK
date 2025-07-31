#!/usr/bin/env python3
"""
Telegram Member Management Bot
บอทจัดการสมาชิกกลุ่ม Telegram อัตโนมัติด้วย Google Sheets

คุณสมบัติหลัก:
- จัดเก็บและอัปเดตข้อมูลสมาชิกใน Google Sheets
- ตรวจสอบและอัปเดต username อัตโนมัติ
- ลบสมาชิกที่หมดอายุออกจากกลุ่มอัตโนมัติ (ทุกชั่วโมง)
"""

import sys
import asyncio
from telegram_bot import TelegramMemberBot

async def main():
    """ฟังก์ชันหลักในการเริ่มต้นบอท"""
    print("🚀 เริ่มต้นการทำงาน Telegram Member Management Bot")
    print("📋 กำลังโหลดการตั้งค่า...")
    
    bot = TelegramMemberBot()
    
    try:
        # เริ่มการทำงานของบอท (async method สำหรับ v22.0)
        await bot.run()
    except KeyboardInterrupt:
        print("\n🛑 หยุดการทำงานโดยผู้ใช้")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())