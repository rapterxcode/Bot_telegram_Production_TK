# TK-Signal Bot

Telegram bot สำหรับจัดการสมาชิกกลุ่มด้วย Google Sheets โดยรองรับ invite link หลายแบบ, join-request approval, การเพิ่มสมาชิกผ่านแอดมิน, และการตรวจสมาชิกหมดอายุ

## Features

- จัดเก็บสมาชิกใน Google Sheets
- รองรับหลายแอดมินผ่าน `ADMIN_USER_ID` แบบคั่น comma
- สร้าง invite link แบบกำหนดเอง, 1 เดือน, 1 ปี, และไม่หมดอายุ
- รับ join request แล้วให้แอดมิน approve/reject
- ลบสมาชิกที่หมดอายุออกจากกลุ่มและจากชีต
- รันได้ทั้ง local และ Docker

## Project Structure

```text
app/
  main.py
  bot/
    application.py
    callbacks.py
    events.py
    invites.py
    logging_config.py
    member_commands.py
    notifications.py
    telegram_bot.py
  core/
    config.py
  services/
    google_sheets.py

Dockerfile
docker-compose.yml
docker-run.sh
PROJECT_MEMORY.md
requirements.txt
```

แก้โค้ดหลักใน `app/...` เท่านั้น โดยตอนนี้ `app/bot/telegram_bot.py` ทำหน้าที่เป็น orchestrator หลัก และแยก `application`, `notifications`, `logging`, `invites`, `callbacks`, `member commands`, และ `membership events` ออกเป็นโมดูลย่อยแล้ว

## Google Sheet Contract

โค้ดคาดหวัง worksheet ที่มี header อย่างน้อยดังนี้

| Column | Header |
|---|---|
| A | `Username` |
| B | `User ID` |
| C | `Expiredate` |
| D | timestamp ตอนเพิ่มข้อมูล |
| E | `First Name` |
| F | `Last Name` |

หมายเหตุ: การลบแถวใน service ยังอิง `sheetId = 0` ดังนั้นควรใช้ worksheet เป้าหมายเป็นชีตแรกของไฟล์

## Environment Variables

ตัวอย่างอยู่ใน [`.env.example`](./.env.example)

ค่าที่โค้ดใช้จริง:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USER_ID`
- `GROUP_CHAT_ID`
- `GROUP_CHAT_ID_FOR_ADMIN`
- `GOOGLE_SHEETS_ID`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `WORKSHEET_NAME`
- `TIMEZONE`
- `CHECK_INTERVAL_VALUE`
- `CHECK_INTERVAL_UNIT`
- `DEFAULT_EXPIRE_DAYS`
- `INVITE_LINK_EXPIRE_MINUTES`
- `INVITE_LINK_1MONTH_DAYS`
- `INVITE_LINK_1YEAR_DAYS`
- `INVITE_LINK_NOEXPIRE`

## Local Setup

1. ติดตั้ง dependencies

```bash
pip install -r requirements.txt
```

2. สร้างไฟล์ `.env` จาก `.env.example`

3. วาง `credentials.json` ของ Google service account ไว้ที่ root โปรเจกต์

4. แชร์ Google Sheet ให้ service account มีสิทธิ์แก้ไข

5. รันบอท

```bash
python -m app.main
```

## Docker

ใช้ compose ไฟล์เดียวคือ [docker-compose.yml](./docker-compose.yml)

รันแบบ script:

```bash
./docker-run.sh dev
./docker-run.sh prod
./docker-run.sh logs
./docker-run.sh status
./docker-run.sh stop
```

รันแบบ manual:

```bash
docker compose up -d
APP_ENV_FILE=.env.production ENVIRONMENT=production docker compose --profile production up -d
```

Docker image ใช้ entrypoint เป็น:

```bash
python -m app.main
```

## Bot Commands

- `/start`
- `/help`
- `/status`
- `/checknow`
- `/listexpired`
- `/addmember`
- `/removemember`
- `/listmembers`
- `/pendingmembers`
- `/updateexpire`
- `/setcheckinterval`
- `/invitelink`
- `/invitelink1month`
- `/invitelink1year`
- `/invitelinknoexpire`
- `/listadmins`

## Known Caveats

- `pending_members`, invite link metadata, และ notification tracking ยังเก็บใน memory ของ process เท่านั้น ถ้า bot restart ข้อมูลส่วนนี้จะหาย
- มี helper สำหรับ job queue อยู่แล้ว แต่ใน startup ปัจจุบันยังไม่ได้ schedule งานตรวจสมาชิกหมดอายุอัตโนมัติทันที
- การตอบกลับผลคำสั่งส่งไปที่ `GROUP_CHAT_ID_FOR_ADMIN` เป็นหลัก ไม่ได้ DM หาแอดมินโดยตรงทุกกรณี
- บาง log/message ในโค้ดยังมี Unicode เดิมอยู่ ถ้า console ไม่ใช่ UTF-8 อาจแสดงผลเพี้ยนได้

## Cleanup Notes

- เอกสารหลักสำหรับคนใช้งานอยู่ที่ไฟล์นี้
- เอกสารสำหรับ AI/dev context อยู่ที่ [PROJECT_MEMORY.md](./PROJECT_MEMORY.md)
- เลิกใช้ legacy root modules แล้ว ให้เรียกผ่าน `python -m app.main` และ import จาก `app/...` เท่านั้น
- phase แรกของการแยก `telegram_bot.py` ทำแล้ว: logging setup, notifications, และ handler registration ถูกย้ายออกเป็นโมดูลย่อย
- phase ถัดมาทำแล้ว: invite handlers, approval callbacks, member/admin commands, และ membership events ถูกแยกออกจากไฟล์หลัก
