import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Admin User IDs - อ่านจาก environment variable
def parse_admin_ids():
    """แปลง ADMIN_USER_ID จาก string เป็น list ของ integers"""
    admin_ids = []
    admin_env = os.getenv('ADMIN_USER_ID', '')
    
    if admin_env:
        # แยก ID ที่คั่นด้วยคอมม่า
        for id_str in admin_env.split(','):
            try:
                admin_id = int(id_str.strip())
                if admin_id > 0:  # ตรวจสอบว่าเป็น ID ที่ถูกต้อง
                    admin_ids.append(admin_id)
            except ValueError:
                print(f"Warning: Invalid admin ID '{id_str.strip()}' in ADMIN_USER_ID")
    
    return admin_ids

ADMIN_USER_IDS = parse_admin_ids()

# สำหรับ backward compatibility
ADMIN_USER_ID = ADMIN_USER_IDS[0] if ADMIN_USER_IDS else 0

# แสดงข้อมูลแอดมินที่โหลดได้
if ADMIN_USER_IDS:
    print(f"✅ Loaded {len(ADMIN_USER_IDS)} admin(s): {ADMIN_USER_IDS}")
else:
    print("⚠️  Warning: No admin users configured. Please set ADMIN_USER_ID in .env file")

GROUP_CHAT_ID = int(os.getenv('GROUP_CHAT_ID', 0))
GROUP_CHAT_ID_FOR_ADMIN = int(os.getenv('GROUP_CHAT_ID_FOR_ADMIN', 0))  # กลุ่มสำหรับแอดมิน

# Google Sheets Configuration
GOOGLE_SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID')
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
WORKSHEET_NAME = os.getenv('WORKSHEET_NAME', 'Members')

SHEET_RANGE = f'{WORKSHEET_NAME}!A:F'

REQUIRED_SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

TIMEZONE = os.getenv('TIMEZONE', 'Asia/Bangkok')

# การตั้งค่าช่วงเวลาการตรวจสอบสมาชิกหมดอายุ
CHECK_INTERVAL_VALUE = int(os.getenv('CHECK_INTERVAL_VALUE', 1))        # ค่าช่วงเวลา
CHECK_INTERVAL_UNIT = os.getenv('CHECK_INTERVAL_UNIT', 'hours')   # หน่วยเวลา: seconds, minutes, hours, days

# การตั้งค่าสำหรับการเพิ่มสมาชิกอัตโนมัติ
DEFAULT_EXPIRE_DAYS = int(os.getenv('DEFAULT_EXPIRE_DAYS', 31))  # วันหมดอายุเริ่มต้นเมื่อเพิ่มสมาชิกใหม่

# การตั้งค่า Invite Link
INVITE_LINK_EXPIRE_MINUTES = int(os.getenv('INVITE_LINK_EXPIRE_MINUTES', 30))  # นาทีที่ invite link จะหมดอายุ
INVITE_LINK_1MONTH_DAYS = int(os.getenv('INVITE_LINK_1MONTH_DAYS', 31))  # วันสำหรับ /invitelink1month
INVITE_LINK_1YEAR_DAYS = int(os.getenv('INVITE_LINK_1YEAR_DAYS', 365))  # วันสำหรับ /invitelink1year
INVITE_LINK_NOEXPIRE = os.getenv('INVITE_LINK_NOEXPIRE', 'no_expire')  # ค่าสำหรับ /invitelinknoexpire

def get_check_interval_seconds():
    """แปลงหน่วยเวลาเป็นวินาที"""
    unit_multipliers = {
        'seconds': 1,
        'minutes': 60,
        'hours': 3600,
        'days': 86400
    }
    
    if CHECK_INTERVAL_UNIT not in unit_multipliers:
        raise ValueError(f"Invalid interval unit: {CHECK_INTERVAL_UNIT}. Use: seconds, minutes, hours, days")
    
    return CHECK_INTERVAL_VALUE * unit_multipliers[CHECK_INTERVAL_UNIT]

def is_admin(user_id):
    """ตรวจสอบว่าผู้ใช้เป็นแอดมินหรือไม่"""
    return int(user_id) in ADMIN_USER_IDS

def get_admin_list():
    """ได้รายชื่อแอดมินทั้งหมด"""
    return ADMIN_USER_IDS.copy()