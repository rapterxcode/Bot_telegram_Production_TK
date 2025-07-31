# 🚀 TK-Signal Bot - คู่มือการ Setup ระบบ

คู่มือการติดตั้งและกำหนดค่าระบบบอทจัดการสมาชิกตั้งแต่เริ่มต้น

---

## 📋 สารบัญ
1. [ความต้องการของระบบ](#ความต้องการของระบบ)
2. [สร้าง Telegram Bot](#สร้าง-telegram-bot)
3. [ตั้งค่า Google Sheets API](#ตั้งค่า-google-sheets-api)
4. [การติดตั้งโปรแกรม](#การติดตั้งโปรแกรม)
5. [การกำหนดค่าไฟล์ .env](#การกำหนดค่าไฟล์-env)
6. [ทดสอบการทำงาน](#ทดสอบการทำงาน)
7. [การ Deploy](#การ-deploy)
8. [การแก้ไขปัญหา](#การแก้ไขปัญหา)

---

## 💻 ความต้องการของระบบ

### ซอฟต์แวร์ที่จำเป็น
- **Python 3.8+** (แนะนำ 3.9 หรือใหม่กว่า)
- **pip** (Python package manager)
- **git** (สำหรับดาวน์โหลดโค้ด)

### บัญชีที่ต้องมี
- **Telegram Account** (สำหรับสร้างบอท)
- **Google Account** (สำหรับ Google Sheets API)
- **Server/VPS** (สำหรับรันบอท 24/7)

---

## 🤖 สร้าง Telegram Bot

### Step 1: สร้างบอทใหม่

1. **เปิด Telegram แล้วค้นหา:** `@BotFather`

2. **ส่งคำสั่ง:** `/newbot`

3. **ตั้งชื่อบอท:**
   ```
   TK-Signal Member Manager
   ```

4. **ตั้ง Username:**
   ```
   tksignal_manager_bot
   ```
   *(ต้องลงท้ายด้วย bot และไม่ซ้ำกับบอทอื่น)*

5. **เก็บ Bot Token:**
   ```
   7960624897:AAHXJ6QgYfAJEHvIGP-oWXhk8KOVdspRULo
   ```
   ⚠️ **สำคัญ:** เก็บ Token นี้ไว้อย่างปลอดภัย!

### Step 2: ตั้งค่าบอท

1. **ตั้งคำอธิบาย:**
   ```
   /setdescription
   ```
   ```
   🤖 บอทจัดการสมาชิกกลุ่ม TK-Signal
   ✅ ตรวจสอบการหมดอายุอัตโนมัติ
   📊 จัดเก็บข้อมูลใน Google Sheets
   ```

2. **ตั้งคำสั่ง:**
   ```
   /setcommands
   ```
   ```
   start - เริ่มต้นการทำงาน
   help - แสดงความช่วยเหลือ
   status - สถานะระบบ
   listmembers - รายชื่อสมาชิก
   addmember - เพิ่มสมาชิก
   removemember - ลบสมาชิก
   updateexpire - อัปเดตวันหมดอายุ
   checknow - ตรวจสอบหมดอายุทันที
   ```

3. **เปิดใช้ Group Mode:**
   ```
   /setjoingroups
   Enable
   ```

4. **เปิดใช้ Group Privacy:**
   ```
   /setprivacy
   Disable
   ```

---

## 📊 ตั้งค่า Google Sheets API

### Step 1: สร้าง Google Cloud Project

1. **เข้าไปที่:** [Google Cloud Console](https://console.cloud.google.com/)

2. **สร้าง Project ใหม่:**
   - คลิก "New Project"
   - ชื่อ Project: `TK-Signal Bot`
   - คลิก "Create"

### Step 2: เปิดใช้งาน API

1. **ไปที่:** APIs & Services > Library

2. **ค้นหาและเปิดใช้งาน:**
   - **Google Sheets API**
   - **Google Drive API**

### Step 3: สร้าง Service Account

1. **ไปที่:** APIs & Services > Credentials

2. **คลิก:** "Create Credentials" > "Service Account"

3. **กรอกข้อมูล:**
   - Service Account Name: `tksignal-bot`
   - Service Account ID: `tksignal-bot`
   - คลิก "Create and Continue"

4. **ตั้งสิทธิ์:**
   - Role: `Editor`
   - คลิก "Continue" > "Done"

### Step 4: สร้าง JSON Key

1. **คลิกที่ Service Account ที่สร้าง**

2. **ไปแท็บ "Keys"**

3. **คลิก:** "Add Key" > "Create New Key"

4. **เลือก:** JSON Format

5. **ดาวน์โหลดไฟล์:** `tksignal-bot-xxxxxx.json`

6. **เปลี่ยนชื่อเป็น:** `credentials.json`

### Step 5: สร้าง Google Sheets

1. **เข้าไปที่:** [Google Sheets](https://sheets.google.com/)

2. **สร้าง Spreadsheet ใหม่:**
   - ชื่อ: `TK-Signal Members`

3. **ตั้งชื่อ Worksheet:**
   - เปลี่ยนจาก "Sheet1" เป็น "Members"

4. **สร้าง Header Row:**
   ```
   A1: Username
   B1: User ID  
   C1: Expiredate
   D1: First Name
   E1: Last Name
   F1: Join Date
   ```

5. **เก็บ Spreadsheet ID:**
   - จาก URL: `https://docs.google.com/spreadsheets/d/1cHur5J5jZhW7qMWyxHUgyE8-fJAFPMn53EeOXyJlVx0/edit`
   - ID คือ: `1cHur5J5jZhW7qMWyxHUgyE8-fJAFPMn53EeOXyJlVx0`

6. **แชร์ให้ Service Account:**
   - คลิก "Share"
   - เพิ่ม Email จาก `credentials.json` (client_email)
   - ตั้งสิทธิ์เป็น "Editor"

---

## 🔧 การติดตั้งโปรแกรม

### Step 1: ดาวน์โหลดโค้ด

```bash
# Clone repository (หรือดาวน์โหลด ZIP)
git clone https://github.com/your-repo/tk-signal-bot.git
cd tk-signal-bot

# หรือถ้าดาวน์โหลด ZIP
# แตกไฟล์และเข้าไปในโฟลเดอร์
```

### Step 2: ติดตั้ง Dependencies

```bash
# สร้าง Virtual Environment (แนะนำ)
python -m venv env

# เปิดใช้งาน Virtual Environment
# Windows:
env\Scripts\activate
# Linux/Mac:
source env/bin/activate

# ติดตั้ง packages
pip install -r requirements.txt
```

### Step 3: วางไฟล์ Credentials

```bash
# วางไฟล์ credentials.json ในโฟลเดอร์หลัก
cp /path/to/your/credentials.json ./credentials.json
```

---

## 🔐 การกำหนดค่าไฟล์ .env

### Step 1: สร้างไฟล์ .env

```bash
# สร้างไฟล์ .env ในโฟลเดอร์หลัก
touch .env
```

### Step 2: เพิ่มการกำหนดค่า

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=7960624897:AAHXJ6QgYfAJEHvIGP-oWXhk8KOVdspRULo
ADMIN_USER_ID=6238237547,5691827566
GROUP_CHAT_ID=-1002752840652
GROUP_CHAT_ID_FOR_ADMIN=-1002680454482

# Google Sheets Configuration
GOOGLE_SHEETS_ID=1cHur5J5jZhW7qMWyxHUgyE8-fJAFPMn53EeOXyJlVx0
GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json
WORKSHEET_NAME=Members

# Other Settings
CHECK_EXPIRY_INTERVAL=60
TIMEZONE=Asia/Bangkok
```

### Step 3: อธิบายแต่ละค่า

| ตัวแปร | คำอธิบาย | วิธีหาค่า |
|--------|----------|-----------|
| `TELEGRAM_BOT_TOKEN` | Token ของบอท | จาก @BotFather |
| `ADMIN_USER_ID` | User ID ของแอดมิน (คั่นด้วยคอมม่า) | จาก @userinfobot |
| `GROUP_CHAT_ID` | ID ของกลุ่มหลัก | เพิ่มบอทเข้ากลุ่ม แล้วส่ง `/start` |
| `GROUP_CHAT_ID_FOR_ADMIN` | ID ของกลุ่มแอดมิน | เพิ่มบอทเข้ากลุ่มแอดมิน แล้วส่ง `/start` |
| `GOOGLE_SHEETS_ID` | ID ของ Google Sheets | จาก URL ของ Sheets |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | ชื่อไฟล์ credentials | `credentials.json` |
| `WORKSHEET_NAME` | ชื่อแผ่นงาน | `Members` |

### วิธีหา Chat ID ของกลุ่ม

#### วิธีที่ 1: ใช้บอทที่มีอยู่
1. เพิ่ม @userinfobot เข้ากลุ่ม
2. ส่งข้อความ `/start` ในกลุ่ม
3. บอทจะแสดง Chat ID

#### วิธีที่ 2: ใช้ Telegram API
1. เพิ่มบอทเข้ากลุ่ม (ให้สิทธิ์แอดมิน)
2. ส่งข้อความใดๆ ในกลุ่ม
3. เข้าไปที่: `https://api.telegram.org/bot{BOT_TOKEN}/getUpdates`
4. หา Chat ID จาก response

#### วิธีที่ 3: ใช้การ Debug
1. รันบอทโดยไม่ตั้ง `GROUP_CHAT_ID`
2. ส่งข้อความ `/start` ในกลุ่ม
3. ดู log จะแสดง Chat ID

---

## 🧪 ทดสอบการทำงาน

### Step 1: ทดสอบ Configuration

```bash
# ทดสอบการโหลด config
python -c "import config; print('✅ Config loaded successfully'); print(f'Admin IDs: {config.ADMIN_USER_IDS}')"
```

### Step 2: ทดสอบ Google Sheets

```bash
# ทดสอบการเชื่อมต่อ Google Sheets
python -c "
from google_sheets import GoogleSheetsManager
sheets = GoogleSheetsManager()
try:
    sheets.get_all_members()
    print('✅ Google Sheets connection successful')
except Exception as e:
    print(f'❌ Google Sheets error: {e}')
"
```

### Step 3: รันบอท

```bash
# รันบอทในโหมดทดสอบ
python main.py
```

### Step 4: ทดสอบคำสั่งพื้นฐาน

1. **เพิ่มบอทเข้ากลุ่ม:**
   - ให้สิทธิ์ Admin
   - อนุญาตให้ดูประวัติข้อความ

2. **ทดสอบคำสั่ง:**
   ```
   /start     # ในกลุ่ม
   /status    # ตรวจสอบสถานะ
   /help      # ดูคำสั่งทั้งหมด
   ```

3. **ทดสอบการเพิ่มสมาชิก:**
   - เพิ่มสมาชิกใหม่เข้ากลุ่ม
   - ตรวจสอบใน Google Sheets

---

## 🚀 การ Deploy

### วิธีที่ 1: รันบน VPS/Server

#### ติดตั้ง systemd service (Linux)

1. **สร้างไฟล์ service:**
   ```bash
   sudo nano /etc/systemd/system/tksignal-bot.service
   ```

2. **เพิ่มเนื้อหา:**
   ```ini
   [Unit]
   Description=TK-Signal Bot
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/path/to/tk-signal-bot
   ExecStart=/path/to/tk-signal-bot/env/bin/python main.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. **เปิดใช้งาน:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable tksignal-bot
   sudo systemctl start tksignal-bot
   ```

4. **ตรวจสอบสถานะ:**
   ```bash
   sudo systemctl status tksignal-bot
   sudo journalctl -u tksignal-bot -f
   ```

### วิธีที่ 2: รันด้วย Docker (แนะนำ)

#### Quick Start
```bash
# Clone repository
git clone <repository-url>
cd Bot_telegram_t

# Setup environment files
cp .env.example .env
# แก้ไข .env และใส่ credentials.json

# Start with Docker
./docker-run.sh dev          # Development mode
./docker-run.sh prod         # Production mode
```

#### Docker Management Commands
```bash
./docker-run.sh build        # Build Docker image
./docker-run.sh dev          # Start development mode
./docker-run.sh prod         # Start production mode
./docker-run.sh logs         # View logs
./docker-run.sh status       # Check status
./docker-run.sh stop         # Stop bot
./docker-run.sh restart      # Restart bot
./docker-run.sh update       # Update and restart
./docker-run.sh cleanup      # Clean up Docker resources
```

#### Manual Docker Commands

#### สร้าง Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

#### สร้าง docker-compose.yml

```yaml
version: '3.8'

services:
  tksignal-bot:
    build: .
    container_name: tksignal-bot
    restart: unless-stopped
    volumes:
      - ./credentials.json:/app/credentials.json
      - ./.env:/app/.env
    environment:
      - PYTHONUNBUFFERED=1
```

#### รัน Docker

```bash
# Build และรัน
docker compose up -d

# ดู logs
docker compose logs -f
```

### วิธีที่ 3: รันด้วย PM2 (Node.js Process Manager)

```bash
# ติดตั้ง PM2
npm install -g pm2

# สร้างไฟล์ ecosystem
echo '{
  "apps": [{
    "name": "tksignal-bot",
    "script": "python",
    "args": "main.py",
    "cwd": "/path/to/tk-signal-bot",
    "interpreter": "/path/to/tk-signal-bot/env/bin/python",
    "restart_delay": 5000,
    "max_restarts": 10
  }]
}' > ecosystem.config.js

# รัน
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

---

## 🔍 การแก้ไขปัญหา

### ปัญหาที่พบบ่อย

#### 1. ModuleNotFoundError

**สาเหตุ:** ไม่ได้ติดตั้ง dependencies
```bash
# แก้ไข
pip install -r requirements.txt
```

#### 2. Google Sheets API Error

**สาเหตุ:** 
- ไฟล์ credentials.json ไม่ถูกต้อง
- Service Account ไม่มีสิทธิ์เข้าถึง

**แก้ไข:**
```bash
# ตรวจสอบไฟล์
ls -la credentials.json

# ตรวจสอบสิทธิ์ใน Google Sheets
# Share Sheets ให้กับ client_email ในไฟล์ credentials.json
```

#### 3. Telegram Bot Token Invalid

**สาเหตุ:** Token ผิดหรือบอทถูกลบ
```bash
# ตรวจสอบ Token
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"
```

#### 4. Permission Denied in Group

**สาเหตุ:** บอทไม่มีสิทธิ์แอดมิน
**แก้ไข:**
- เพิ่มบอทให้เป็นแอดมินในกลุ่ม
- อนุญาตให้ดูประวัติข้อความ

#### 5. Chat ID หาไม่เจอ

**แก้ไข:**
```python
# เพิ่มโค้ด debug ใน telegram_bot.py
import logging
logging.basicConfig(level=logging.INFO)

# ใน start_command หรือฟังก์ชันอื่น
logger.info(f"Chat ID: {update.effective_chat.id}")
logger.info(f"Chat Type: {update.effective_chat.type}")
```

### การ Debug

#### เปิด Logging ระดับ DEBUG

```python
# ในไฟล์ main.py หรือ telegram_bot.py
import logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
```

#### ตรวจสอบ Environment Variables

```bash
# แสดงค่า environment
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
print('TELEGRAM_BOT_TOKEN:', os.getenv('TELEGRAM_BOT_TOKEN')[:10] + '...')
print('ADMIN_USER_ID:', os.getenv('ADMIN_USER_ID'))
print('GROUP_CHAT_ID:', os.getenv('GROUP_CHAT_ID'))
"
```

---

## 📚 ไฟล์สำคัญ

```
tk-signal-bot/
├── main.py                 # ไฟล์หลัก
├── telegram_bot.py         # Logic ของบอท
├── google_sheets.py        # จัดการ Google Sheets
├── config.py              # การกำหนดค่า
├── requirements.txt        # Dependencies
├── .env                   # Environment variables
├── credentials.json       # Google API credentials
├── how_to_use_bot_tksignal.md        # คู่มือการใช้งาน
└── how_to_setup_system_bot_api.md    # คู่มือการติดตั้ง (ไฟล์นี้)
```

---

## 🔐 ความปลอดภัย

### ข้อควรระวัง

1. **ไม่แชร์ Token:** เก็บ `TELEGRAM_BOT_TOKEN` เป็นความลับ
2. **ไม่ commit credentials:** เพิ่ม `.env` และ `credentials.json` ใน `.gitignore`
3. **จำกัดสิทธิ์:** ให้แอดมินเท่าที่จำเป็น
4. **อัปเดตเป็นประจำ:** อัปเดต dependencies เป็นประจำ

### .gitignore แนะนำ

```gitignore
# Environment
.env
.env.local
.env.production

# Credentials
credentials.json
*.json

# Python
__pycache__/
*.pyc
venv/
env/

# IDE
.vscode/
.idea/

# Logs
*.log
logs/
```

---

## 📞 ติดต่อสอบถาม

หากมีปัญหาการติดตั้ง กรุณาติดต่อแอดมินระบบ Phone 0924157139

**Version:** 2.0  
**Last Updated:** 2025-07-30  
**Setup Guide By:** TK-Signal Team  
**Features:** Multi-Admin, Private Replies, Docker Support, Advanced Invite Links