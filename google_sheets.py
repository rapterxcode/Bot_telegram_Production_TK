import json
from datetime import datetime, timezone
from typing import List, Dict, Optional
import pytz
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import config


class GoogleSheetsManager:
    def __init__(self):
        self.credentials = None
        self.service = None
        self.spreadsheet_id = config.GOOGLE_SHEETS_ID
        self.authenticate()

    def authenticate(self):
        """Google Sheets API การยืนยันตัวตน"""
        try:
            self.credentials = Credentials.from_service_account_file(
                config.GOOGLE_SERVICE_ACCOUNT_FILE, 
                scopes=config.REQUIRED_SCOPES
            )
            self.service = build('sheets', 'v4', credentials=self.credentials)
            print("✅ เชื่อมต่อ Google Sheets API สำเร็จ")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการเชื่อมต่อ Google Sheets: {e}")
            raise

    def get_all_members(self) -> List[Dict]:
        """อ่านข้อมูลสมาชิกทั้งหมดจาก Google Sheet"""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=config.SHEET_RANGE
            ).execute()
            
            values = result.get('values', [])
            if not values:
                return []

            # สมมติว่าแถวแรกเป็น header
            headers = values[0]
            members = []
            
            for row in values[1:]:
                # ป้องกันข้อมูลไม่ครบ
                while len(row) < len(headers):
                    row.append('')
                
                member = {}
                for i, header in enumerate(headers):
                    member[header] = row[i] if i < len(row) else ''
                
                # ตรวจสอบว่ามีข้อมูลสำคัญครบถ้วน
                if member.get('User ID') and member.get('Username'):
                    members.append(member)
            
            return members
            
        except HttpError as e:
            print(f"❌ ข้อผิดพลาดในการอ่านข้อมูล: {e}")
            return []

    def update_username(self, user_id: str, new_username: str) -> bool:
        """อัปเดต username ใน Google Sheet โดยใช้ User ID เป็นตัวระบุ"""
        try:
            # อ่านข้อมูลทั้งหมดเพื่อหาแถวที่ต้องการอัปเดต
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=config.SHEET_RANGE
            ).execute()
            
            values = result.get('values', [])
            if not values:
                return False

            headers = values[0]
            user_id_col = -1
            username_col = -1
            
            # หาตำแหน่งคอลัมน์
            for i, header in enumerate(headers):
                if header == 'User ID':
                    user_id_col = i
                elif header == 'Username':
                    username_col = i
            
            if user_id_col == -1 or username_col == -1:
                print("❌ ไม่พบคอลัมน์ User ID หรือ Username")
                return False

            # หาแถวที่มี User ID ตรงกัน
            for row_index, row in enumerate(values[1:], start=2):  # เริ่มจากแถวที่ 2
                if row_index <= len(values) and len(row) > user_id_col:
                    if row[user_id_col] == str(user_id):
                        # อัปเดต username
                        cell_range = f"{config.WORKSHEET_NAME}!{chr(65 + username_col)}{row_index}"
                        body = {'values': [[new_username]]}
                        
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.spreadsheet_id,
                            range=cell_range,
                            valueInputOption='RAW',
                            body=body
                        ).execute()
                        
                        print(f"✅ อัปเดต username สำหรับ User ID {user_id} เป็น {new_username}")
                        return True
            
            print(f"❌ ไม่พบ User ID {user_id} ใน Google Sheet")
            return False
            
        except HttpError as e:
            print(f"❌ ข้อผิดพลาดในการอัปเดต username: {e}")
            return False

    def get_expired_members(self) -> List[Dict]:
        """ค้นหาสมาชิกที่หมดอายุแล้ว"""
        members = self.get_all_members()
        expired_members = []
        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
        
        for member in members:
            expire_date_str = member.get('Expiredate', '')
            if expire_date_str:
                # ข้ามสมาชิกที่ไม่หมดอายุ
                if expire_date_str == "no_expire" or expire_date_str == config.INVITE_LINK_NOEXPIRE:
                    continue
                    
                try:
                    # แปลงวันที่หมดอายุเป็น datetime object
                    expire_date = datetime.strptime(expire_date_str, '%Y-%m-%d %H:%M:%S')
                    expire_date = pytz.timezone(config.TIMEZONE).localize(expire_date)
                    
                    # ตรวจสอบว่าหมดอายุแล้วหรือไม่
                    if expire_date <= current_time:
                        expired_members.append(member)
                        
                except ValueError as e:
                    print(f"❌ รูปแบบวันที่ไม่ถูกต้องสำหรับสมาชิก {member.get('Username', 'Unknown')}: {expire_date_str}")
        
        return expired_members

    def remove_member_from_sheet(self, user_id: str) -> bool:
        """ลบข้อมูลสมาชิกจาก Google Sheet (เมื่อถูกลบออกจากกลุ่มแล้ว)"""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=config.SHEET_RANGE
            ).execute()
            
            values = result.get('values', [])
            if not values:
                return False

            headers = values[0]
            user_id_col = -1
            
            # หาตำแหน่งคอลัมน์ User ID
            for i, header in enumerate(headers):
                if header == 'User ID':
                    user_id_col = i
                    break
            
            if user_id_col == -1:
                return False

            # หาแถวที่มี User ID ตรงกัน
            for row_index, row in enumerate(values[1:], start=2):
                if len(row) > user_id_col and row[user_id_col] == str(user_id):
                    # ลบแถว
                    request = {
                        'deleteDimension': {
                            'range': {
                                'sheetId': 0,  # Sheet1 มี ID = 0
                                'dimension': 'ROWS',
                                'startIndex': row_index - 1,  # 0-indexed
                                'endIndex': row_index
                            }
                        }
                    }
                    
                    self.service.spreadsheets().batchUpdate(
                        spreadsheetId=self.spreadsheet_id,
                        body={'requests': [request]}
                    ).execute()
                    
                    print(f"✅ ลบข้อมูลสมาชิก User ID {user_id} จาก Google Sheet")
                    return True
            
            return False
            
        except HttpError as e:
            print(f"❌ ข้อผิดพลาดในการลบข้อมูลจาก Sheet: {e}")
            return False

    def add_member(self, username: str, user_id: str, expire_date: str) -> bool:
        """เพิ่มสมาชิกใหม่ใน Google Sheet"""
        try:
            # อ่านข้อมูลปัจจุบันเพื่อหาแถวว่างถัดไป
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=config.SHEET_RANGE
            ).execute()
            
            values = result.get('values', [])
            next_row = len(values) + 1  # แถวถัดไปที่จะเพิ่มข้อมูล
            
            # ข้อมูลที่จะเพิ่ม
            current_time = datetime.now(pytz.timezone(config.TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
            new_row = [
                username,           # Username
                user_id,           # User ID  
                expire_date,       # Expiredate
                current_time,      # Datetime (UTC)
                "",                # First Name (ว่าง)
                ""                 # Last Name (ว่าง)
            ]
            
            # เพิ่มข้อมูลในแถวใหม่
            range_name = f"{config.WORKSHEET_NAME}!A{next_row}:F{next_row}"
            body = {'values': [new_row]}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            
            print(f"✅ เพิ่มสมาชิก {username} (ID: {user_id}) สำเร็จ")
            return True
            
        except HttpError as e:
            print(f"❌ ข้อผิดพลาดในการเพิ่มสมาชิก: {e}")
            return False

    def add_member_with_details(self, username: str, user_id: str, expire_date: str, 
                               first_name: str = "", last_name: str = "") -> bool:
        """เพิ่มสมาชิกใหม่ใน Google Sheet พร้อมข้อมูลครบถ้วน"""
        try:
            # ตรวจสอบว่าสมาชิกมีอยู่แล้วหรือไม่
            existing_members = self.get_all_members()
            if any(member.get('User ID') == user_id for member in existing_members):
                print(f"⚠️ สมาชิก {username} (ID: {user_id}) มีอยู่ใน Sheet แล้ว")
                return True  # ถือว่าสำเร็จเพราะข้อมูลมีอยู่แล้ว
            
            # อ่านข้อมูลปัจจุบันเพื่อหาแถวว่างถัดไป
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=config.SHEET_RANGE
            ).execute()
            
            values = result.get('values', [])
            next_row = len(values) + 1  # แถวถัดไปที่จะเพิ่มข้อมูล
            
            # ข้อมูลที่จะเพิ่ม
            current_time = datetime.now(pytz.timezone(config.TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
            new_row = [
                username,           # Username
                user_id,           # User ID  
                expire_date,       # Expiredate
                current_time,      # Datetime (UTC)
                first_name,        # First Name
                last_name          # Last Name
            ]
            
            # เพิ่มข้อมูลในแถวใหม่
            range_name = f"{config.WORKSHEET_NAME}!A{next_row}:F{next_row}"
            body = {'values': [new_row]}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            
            print(f"✅ เพิ่มสมาชิก {username} (ID: {user_id}) สำเร็จ (Auto-add)")
            return True
            
        except HttpError as e:
            print(f"❌ ข้อผิดพลาดในการเพิ่มสมาชิก (Auto-add): {e}")
            return False

    def update_member_expire_date(self, user_id: str, new_expire_date: str) -> bool:
        """อัปเดตวันหมดอายุของสมาชิก"""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=config.SHEET_RANGE
            ).execute()
            
            values = result.get('values', [])
            if not values:
                return False

            headers = values[0]
            user_id_col = -1
            expire_date_col = -1
            
            # หาตำแหน่งคอลัมน์
            for i, header in enumerate(headers):
                if header == 'User ID':
                    user_id_col = i
                elif header == 'Expiredate':
                    expire_date_col = i
            
            if user_id_col == -1 or expire_date_col == -1:
                print("❌ ไม่พบคอลัมน์ User ID หรือ Expiredate")
                return False

            # หาแถวที่มี User ID ตรงกัน
            for row_index, row in enumerate(values[1:], start=2):  # เริ่มจากแถวที่ 2
                if row_index <= len(values) and len(row) > user_id_col:
                    if row[user_id_col] == str(user_id):
                        # อัปเดตวันหมดอายุ
                        cell_range = f"{config.WORKSHEET_NAME}!{chr(65 + expire_date_col)}{row_index}"
                        body = {'values': [[new_expire_date]]}
                        
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.spreadsheet_id,
                            range=cell_range,
                            valueInputOption='RAW',
                            body=body
                        ).execute()
                        
                        print(f"✅ อัปเดตวันหมดอายุสำหรับ User ID {user_id} เป็น {new_expire_date}")
                        return True
            
            print(f"❌ ไม่พบ User ID {user_id} ใน Google Sheet")
            return False
            
        except HttpError as e:
            print(f"❌ ข้อผิดพลาดในการอัปเดตวันหมดอายุ: {e}")
            return False