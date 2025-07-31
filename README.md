# 🤖 TK-Signal Bot - Telegram Member Management System

# TEST
```

```
บอท Telegram สำหรับจัดการสมาชิกกลุ่มอัตโนมัติด้วย Google Sheets API พร้อมระบบหมดอายุและการจัดการแบบ Multi-Admin

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)
![Google Sheets](https://img.shields.io/badge/Google-Sheets-green.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)

---

## 📋 สารบัญ

1. [คุณสมบัติหลัก](#-คุณสมบัติหลัก)
2. [การติดตั้งและตั้งค่า](#-การติดตั้งและตั้งค่า)
3. [การใช้งาน](#-การใช้งาน)
4. [Docker Deployment](#-docker-deployment)
5. [คำสั่งที่รองรับ](#-คำสั่งที่รองรับ)
6. [การจัดการสมาชิก](#-การจัดการสมาชิก)
7. [ระบบ Private Reply](#-ระบบ-private-reply)
8. [การแก้ไขปัญหา](#-การแก้ไขปัญหา)

---

## 🚀 คุณสมบัติหลัก

### 🔗 การเชื่อมต่อ Google Sheets
- ✅ อ่านและจัดเก็บข้อมูลสมาชิกใน Google Sheets
- ✅ อัปเดตข้อมูลสมาชิกอัตโนมัติ
- ✅ ใช้ User ID เป็นตัวระบุหลักสำหรับการจัดการ
- ✅ บันทึกประวัติการเข้า-ออกกลุ่ม

### 👥 การจัดการสมาชิกขั้นสูง
- 🔄 ตรวจสอบและอัปเดต username เมื่อมีการเปลี่ยนแปลง
- ⏰ ลบสมาชิกที่หมดอายุออกจากกลุ่มอัตโนมัติ
- 📅 ตรวจสอบวันหมดอายุตามที่กำหนด (ปรับได้)
- 🆔 รองรับ Multi-Admin (หลายแอดมิน)

### 💬 ระบบ Private Reply
- 🔒 ตอบกลับคำสั่งแอดมินแบบส่วนตัว
- 🔄 Fallback ไป Admin Group เมื่อส่งไม่ได้
- 🆘 ระบบแนะนำเริ่มสนทนากับบอท

### 🔗 ระบบ Invite Link ขั้นสูง
- ⏱️ `/invitelink <จำนวน> <หน่วย>` - กำหนดระยะเวลาเอง
- 📅 `/invitelink1month` - 1 เดือน
- 🗓️ `/invitelink1year` - 1 ปี
- ♾️ `/invitelinknoexpire` - ไม่หมดอายุ
- ⏰ Link หมดอายุใน 30 นาที (ความปลอดภัย)

### 🐳 Docker Support
- 📦 Docker Compose สำหรับ Development & Production
- 🔧 Management Script (`docker-run.sh`)
- 📊 Health Checks & Monitoring
- 🔄 Auto-restart & Log rotation

---

## 📊 รูปแบบข้อมูลใน Google Sheet

| Username | User ID | Expiredate | First Name | Last Name | Join Date |
|----------|---------|------------|------------|-----------|-----------|
| @john_doe | 123456789 | 2025-12-31 23:59:59 | John | Doe | 2025-01-30 14:15:30 |

**คอลัมน์ที่จำเป็น:**
- `Username`: ชื่อผู้ใช้ Telegram (เช่น @john_doe)
- `User ID`: Telegram User ID (สำคัญสำหรับการลบสมาชิก)
- `Expiredate`: วันที่หมดอายุ (รูปแบบ: YYYY-MM-DD HH:MM:SS)
- `First Name`: ชื่อจริง
- `Last Name`: นามสกุล
- `Join Date`: วันที่เข้าร่วม

---

## 🛠️ การติดตั้งและตั้งค่า

### วิธีที่ 1: การติดตั้งแบบดั้งเดิม

#### 1. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

#### 2. สร้าง Google Service Account
1. ไปที่ [Google Cloud Console](https://console.cloud.google.com/)
2. สร้างโปรเจ็กต์ใหม่หรือเลือกโปรเจ็กต์ที่มีอยู่
3. เปิดใช้งาน Google Sheets API และ Google Drive API
4. สร้าง Service Account และดาวน์โหลดไฟล์ JSON
5. เปลี่ยนชื่อไฟล์เป็น `credentials.json` และวางในโฟลเดอร์โปรเจ็กต์

#### 3. สร้าง Telegram Bot
1. ติดต่อ [@BotFather](https://t.me/BotFather) ใน Telegram
2. ใช้คำสั่ง `/newbot` เพื่อสร้างบอทใหม่
3. เก็บ Bot Token ที่ได้รับ

#### 4. ตั้งค่า Environment Variables
สร้างไฟล์ `.env`:
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
CHECK_INTERVAL_VALUE=1
CHECK_INTERVAL_UNIT=days
DEFAULT_EXPIRE_DAYS=31
DEFAULT_EXPIRE_YEARS=1
TIMEZONE=Asia/Bangkok
```

#### 5. ตั้งค่า Google Sheet
1. สร้าง Google Sheet ใหม่
2. เพิ่ม Service Account email เป็น Editor ของ Sheet
3. สร้างหัวข้อคอลัมน์ตามรูปแบบที่กำหนด
4. คัดลอก Sheet ID จาก URL และใส่ใน `.env`

### วิธีที่ 2: Docker Deployment (แนะนำ)

#### Quick Start
```bash
# Clone repository
git clone <repository-url>
cd Bot_telegram_t

# Setup environment
cp .env.example .env
# แก้ไข .env และใส่ credentials.json

# Start with Docker
./docker-run.sh dev
```

---

## 🐳 Docker Deployment

### การใช้งาน Docker

#### Development Mode
```bash
./docker-run.sh dev          # เริ่มโหมด development
./docker-run.sh logs         # ดู logs แบบ real-time
./docker-run.sh status       # ดูสถานะ container
./docker-run.sh stop         # หยุด bot
```

#### Production Mode
```bash
./docker-run.sh prod         # เริ่มโหมด production
./docker-run.sh update       # อัปเดตและรีสตาร์ท
./docker-run.sh cleanup      # ล้างข้อมูล Docker
```

#### Manual Docker Compose
```bash
# Development
docker compose up -d
docker compose logs -f

# Production
docker compose -f docker-compose.prod.yml up -d
```

### Docker Features
- ✅ Multi-stage deployment (dev/prod)
- ✅ Health checks & monitoring
- ✅ Auto-restart on failure
- ✅ Log rotation & management
- ✅ Resource limits
- ✅ Security hardening

---

## 💻 การใช้งาน

### เริ่มต้นบอท
```bash
python main.py
```

### การเพิ่มบอทเข้ากลุ่ม
1. เพิ่มบอทเข้าไปในกลุ่ม Telegram
2. ให้สิทธิ์ Admin แก่บอท (จำเป็นสำหรับการลบสมาชิก)
3. ใช้คำสั่ง `/start` ในกลุ่มเพื่อเริ่มต้นการทำงาน

---

## 🔧 คำสั่งที่รองรับ

### 📋 คำสั่งทั่วไป
| คำสั่ง | คำอธิบาย | สิทธิ์ |
|--------|----------|-------|
| `/start` | เริ่มต้นการทำงาน | ทุกคน |
| `/help` | แสดงความช่วยเหลือ | แอดมิน |
| `/status` | แสดงสถานะระบบ | แอดมิน |

### 👥 การจัดการสมาชิก
| คำสั่ง | รูปแบบ | ตัวอย่าง |
|--------|--------|----------|
| `/addmember` | `@user user_id expire_date` | `/addmember @john 123 2025-12-31 23:59:59` |
| `/removemember` | `user_id` | `/removemember 123456789` |
| `/updateexpire` | `user_id new_date` | `/updateexpire 123 2025-12-31 23:59:59` |
| `/listmembers` | `[หน้า]` | `/listmembers` หรือ `/listmembers 2` |
| `/listexpired` | - | `/listexpired` |

### 🔗 Invite Links
| คำสั่ง | รูปแบบ | ตัวอย่าง |
|--------|--------|----------|
| `/invitelink` | `<จำนวน> <หน่วย>` | `/invitelink 30 days` |
| `/invitelink1month` | - | `/invitelink1month` |
| `/invitelink1year` | - | `/invitelink1year` |
| `/invitelinknoexpire` | - | `/invitelinknoexpire` |

**หน่วยที่รองรับ:** `days`, `months`, `years` (ทั้งเอกพจน์และพหูพจน์)

### 🛠️ เครื่องมือแอดมิน
| คำสั่ง | รูปแบบ | ตัวอย่าง |
|--------|--------|----------|
| `/checknow` | - | `/checknow` |
| `/setcheckinterval` | `<ค่า> <หน่วย>` | `/setcheckinterval 2 hours` |
| `/listadmins` | - | `/listadmins` |

---

## 👥 การจัดการสมาชิก

### 🚀 การเพิ่มสมาชิกอัตโนมัติ

เมื่อแอดมินเพิ่มสมาชิกผ่าน Telegram UI บอทจะ:

✅ **เพิ่มข้อมูลใน Google Sheet อัตโนมัติ**  
✅ **ตั้งวันหมดอายุเริ่มต้น** (1 ปีหรือตามที่กำหนด)  
✅ **แจ้งเตือนแอดมิน** แบบ private chat  
✅ **บันทึก First Name & Last Name**  

### 📝 การเพิ่มสมาชิกด้วยคำสั่ง
```bash
/addmember @username user_id expire_date

# ตัวอย่าง
/addmember @john_doe 123456789 2025-12-31 23:59:59
```

### 🔗 การใช้ Invite Link
```bash
# กำหนดระยะเวลาเอง
/invitelink 7 days        # 7 วัน
/invitelink 3 months      # 3 เดือน
/invitelink 2 years       # 2 ปี

# ใช้ preset
/invitelink1month         # 1 เดือน
/invitelink1year          # 1 ปี
/invitelinknoexpire       # ไม่หมดอายุ
```

**คุณสมบัติ Invite Link:**
- ⏰ ลิงก์หมดอายุใน 30 นาที
- 👤 สมาชิกได้รับวันหมดอายุตามที่กำหนด
- 🔄 แจ้งเตือนแอดมินเมื่อมีคนเข้าใหม่

### 📊 การดูรายชื่อสมาชิก
```bash
/listmembers              # หน้าแรก (20 คน)
/listmembers 2            # หน้าที่ 2
/listexpired              # เฉพาะที่หมดอายุ
```

### 🗑️ การลบสมาชิก
```bash
/removemember 123456789   # ลบทั้งจากกลุ่มและ Google Sheet
/checknow                 # ตรวจสอบและลบที่หมดอายุ
```

---

## 🔒 ระบบ Private Reply

### การทำงาน
1. **แอดมินใช้คำสั่งในกลุ่ม**
2. **บอทส่งผลลัพธ์ไป Private Chat**
3. **หากส่งไม่ได้ → ส่งไป Admin Group**

### การเริ่มรับ Private Messages
- คลิกลิงก์ในข้อความ fallback
- หรือส่ง `/start` ให้บอทในแชทส่วนตัว

### Multi-Admin Support
```env
ADMIN_USER_ID=6238237547,5691827566,NEW_ADMIN_ID
```

---

## ⚙️ การตั้งค่าขั้นสูง

### การปรับช่วงเวลาตรวจสอบ
```bash
# ด้วยคำสั่ง (ชั่วคราว)
/setcheckinterval 30 minutes
/setcheckinterval 2 hours
/setcheckinterval 1 days

# ใน .env (ถาวร)
CHECK_INTERVAL_VALUE=2
CHECK_INTERVAL_UNIT=hours
```

### การตั้งค่าวันหมดอายุเริ่มต้น
```env
DEFAULT_EXPIRE_DAYS=31     # วัน (สำหรับเพิ่มแบบปกติ)
DEFAULT_EXPIRE_YEARS=1     # ปี (สำหรับ invite link)
```

### Timezone
```env
TIMEZONE=Asia/Bangkok
```

---

## 🔍 การแก้ไขปัญหา

### ปัญหาที่พบบ่อย

#### 1. "bot can't initiate conversation with a user"
**แก้ไข:** แอดมินต้องส่ง `/start` ให้บอทในแชทส่วนตัวก่อน

#### 2. Google Sheets API Error
**ตรวจสอบ:**
- ไฟล์ `credentials.json` ถูกต้อง
- Service Account มีสิทธิ์ Editor
- API ถูกเปิดใช้งาน

#### 3. บอทไม่ตอบสนอง
**ตรวจสอบ:**
- `TELEGRAM_BOT_TOKEN` ถูกต้อง
- บอทมีสิทธิ์ Admin ในกลุ่ม
- ไฟล์ `.env` โหลดถูกต้อง

#### 4. Permission Denied
**แก้ไข:**
- ให้สิทธิ์ Admin กับบอทในกลุ่ม
- อนุญาตให้ดูประวัติข้อความ

### การ Debug
```python
# เปิด DEBUG logging
import logging
logging.basicConfig(level=logging.DEBUG)
```

### การตรวจสอบสถานะ
```bash
# ด้วยคำสั่ง
/status

# ด้วย Docker
./docker-run.sh status
docker compose logs -f
```

---

## 📁 โครงสร้างไฟล์

```
Bot_telegram_t/
├── main.py                          # ไฟล์หลัก
├── telegram_bot.py                  # Logic ของบอท
├── google_sheets.py                 # จัดการ Google Sheets
├── config.py                        # การกำหนดค่า
├── requirements.txt                 # Dependencies
├── .env                            # Environment variables
├── credentials.json                # Google Service Account
├── how_to_use_bot_tksignal.md      # คู่มือการใช้งาน
├── how_to_setup_system_bot_api.md  # คู่มือการติดตั้ง
├── Dockerfile                      # Docker image config
├── docker-compose.yml              # Docker compose (dev)
├── docker-compose.prod.yml         # Docker compose (prod)
├── docker-run.sh                   # Docker management script
├── .dockerignore                   # Docker ignore rules
└── README.md                       # เอกสารนี้
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
.env.*
!.env.example

# Credentials
credentials.json
*.json

# Python
__pycache__/
*.pyc
venv/
env/

# Docker
.dockerignore

# Logs
*.log
logs/
```

---

## 📈 Performance & Monitoring

### Resource Usage
- **Memory:** ~50-100MB
- **CPU:** Minimal (event-driven)
- **Network:** ขึ้นกับการใช้งาน API

### Monitoring
- Health checks ใน Docker
- Log rotation
- Error tracking
- Auto-restart on failure

---

## 🚀 Deployment Options

### 1. Local Development
```bash
python main.py
```

### 2. Docker (Recommended)
```bash
./docker-run.sh dev      # Development
./docker-run.sh prod     # Production
```

### 3. VPS/Server
```bash
# systemd service
sudo systemctl enable tksignal-bot
sudo systemctl start tksignal-bot
```

### 4. Cloud Platforms
- **AWS ECS/EKS**
- **Google Cloud Run**
- **Azure Container Instances**
- **DigitalOcean App Platform**

---

## 📞 ติดต่อสอบถาม

หากมีปัญหาการใช้งาน กรุณาติดต่อแอดมินระบบ **Phone 0924157139**

---

## 📜 License

MIT License - ใช้งานได้อย่างอิสระ

---

## 🔄 Version History

- **v2.0** - Multi-admin, Private replies, Docker support, Advanced invite links
- **v1.5** - Auto member tracking, Timezone support
- **v1.0** - Basic member management with Google Sheets

---

**🎯 TK-Signal Bot - Automated Telegram Group Management Made Easy**