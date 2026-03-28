"""Google Sheets access helpers for member data."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import pytz
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core import config


logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("app.audit.google_sheets")


@dataclass
class MemberRowLocation:
    """Store the worksheet row number for a member."""

    row_number: int
    row_values: List[str]


@dataclass
class SheetSnapshot:
    """In-memory representation of the worksheet for a sync pass."""

    worksheet_name: str
    headers: List[str]
    rows: List[List[str]]
    member_locations: Dict[str, MemberRowLocation]


class GoogleSheetsManager:
    """Read and write member data in the Members and audit worksheets."""

    MEMBER_HEADERS = [
        "Username",
        "User ID",
        "First Name",
        "Last Name",
        "Role",
        "Telegram Status",
        "Record Status",
        "In Group Now",
        "Join Source",
        "Invite Link Label",
        "Expire Policy Days",
        "Expiredate",
        "Joined At",
        "Approved By",
        "Approved At",
        "Added By",
        "Datetime (UTC)",
        "Last Sync At",
        "Last Sync Result",
        "Sync Note",
        "Last Seen In Group At",
        "Removed At",
        "Remove Reason",
        "Sync Source",
    ]
    AUDIT_LOG_HEADERS = [
        "Event Time",
        "User ID",
        "Username",
        "Action",
        "Old Value",
        "New Value",
        "Actor",
        "Source",
        "Note",
    ]
    ACTIVE_RECORD_STATUSES = {"", "active"}
    ACTIVE_IN_GROUP_VALUES = {"", "yes"}

    def __init__(self, service=None, spreadsheet_id: Optional[str] = None):
        self.credentials = None
        self.service = service
        self.spreadsheet_id = spreadsheet_id or config.GOOGLE_SHEETS_ID
        self.worksheet_name = config.WORKSHEET_NAME
        self.audit_worksheet_name = config.AUDIT_WORKSHEET_NAME
        self._sheet_id_cache: Dict[str, int] = {}

        if self.service is None:
            self.authenticate()

    def authenticate(self):
        """Create an authenticated Google Sheets API client."""
        try:
            self.credentials = Credentials.from_service_account_file(
                config.GOOGLE_SERVICE_ACCOUNT_FILE,
                scopes=config.REQUIRED_SCOPES,
            )
            self.service = build("sheets", "v4", credentials=self.credentials)
            logger.info("Connected to Google Sheets API")
        except Exception:
            logger.exception("Failed to authenticate with Google Sheets")
            raise

    def get_all_members(self, *, include_inactive: bool = False) -> List[Dict]:
        """Return member rows, optionally including removed/history rows."""
        try:
            snapshot = self.load_sheet_snapshot(
                worksheet_name=self.worksheet_name,
                header_template=self.MEMBER_HEADERS,
            )
            members = []
            for row in snapshot.rows[1:]:
                padded_row = self._pad_row(row, len(snapshot.headers))
                member = {
                    header: padded_row[index]
                    for index, header in enumerate(snapshot.headers)
                }
                if not member.get("User ID") or not member.get("Username"):
                    continue
                if not include_inactive and not self._is_member_active(member):
                    continue
                members.append(member)

            return members
        except HttpError:
            logger.exception("Failed to read members from Google Sheets")
            return []
        except Exception:
            logger.exception("Unexpected failure reading members from Google Sheets")
            return []

    def get_expired_members(self) -> List[Dict]:
        """Return all members whose Expiredate is already in the past."""
        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
        expired_members = []

        for member in self.get_all_members():
            expire_date_str = member.get("Expiredate", "")
            if expire_date_str in {"", "no_expire", config.INVITE_LINK_NOEXPIRE}:
                continue

            try:
                expire_date = datetime.strptime(
                    expire_date_str,
                    "%Y-%m-%d %H:%M:%S",
                )
                expire_date = pytz.timezone(config.TIMEZONE).localize(expire_date)
            except ValueError:
                logger.warning(
                    "Skipping member %s with invalid Expiredate: %s",
                    member.get("User ID"),
                    expire_date_str,
                )
                continue

            if expire_date <= current_time:
                expired_members.append(member)

        return expired_members

    def add_member(self, username: str, user_id: str, expire_date: str) -> bool:
        """Insert or update a member row with default empty name fields."""
        return self.add_member_with_details(
            username=username,
            user_id=user_id,
            expire_date=expire_date,
        )

    def add_member_with_details(
        self,
        username: str,
        user_id: str,
        expire_date: str,
        first_name: str = "",
        last_name: str = "",
        metadata: Optional[Dict[str, object]] = None,
    ) -> bool:
        """Insert a new member or update the existing row matched by User ID."""
        metadata = dict(metadata or {})
        try:
            local_now = self._now_local_string()
            payload = {
                "Username": username,
                "User ID": str(user_id),
                "First Name": first_name,
                "Last Name": last_name,
                "Role": metadata.get("Role", ""),
                "Telegram Status": metadata.get("Telegram Status", ""),
                "Record Status": metadata.get("Record Status", "active"),
                "In Group Now": metadata.get("In Group Now", "Yes"),
                "Join Source": metadata.get("Join Source", "manual"),
                "Invite Link Label": metadata.get("Invite Link Label", ""),
                "Expire Policy Days": metadata.get("Expire Policy Days", ""),
                "Expiredate": expire_date,
                "Joined At": metadata.get("Joined At", local_now),
                "Approved By": metadata.get("Approved By", ""),
                "Approved At": metadata.get("Approved At", ""),
                "Added By": metadata.get("Added By", "system"),
                "Datetime (UTC)": metadata.get("Datetime (UTC)", self._now_utc_string()),
                "Last Sync At": metadata.get("Last Sync At", ""),
                "Last Sync Result": metadata.get("Last Sync Result", ""),
                "Sync Note": metadata.get("Sync Note", ""),
                "Last Seen In Group At": metadata.get("Last Seen In Group At", local_now),
                "Removed At": metadata.get("Removed At", ""),
                "Remove Reason": metadata.get("Remove Reason", ""),
                "Sync Source": metadata.get("Sync Source", ""),
            }

            self.upsert_member_record(payload)
            logger.info("Upserted member %s (user ID %s)", username, user_id)
            return True
        except HttpError:
            logger.exception("Failed to upsert member %s in Google Sheets", user_id)
            return False
        except Exception:
            logger.exception("Unexpected failure upserting member %s in Google Sheets", user_id)
            return False

    def update_username(self, user_id: str, new_username: str) -> bool:
        """Update Username for an existing member row."""
        return self._update_single_field(
            user_id=user_id,
            header_name="Username",
            new_value=new_username,
        )

    def update_member_expire_date(self, user_id: str, new_expire_date: str) -> bool:
        """Update Expiredate for an existing member row."""
        return self._update_single_field(
            user_id=user_id,
            header_name="Expiredate",
            new_value=new_expire_date,
        )

    def remove_member_from_sheet(
        self,
        user_id: str,
        *,
        removed_at: Optional[str] = None,
        remove_reason: str = "Removed from group",
        actor: str = "",
        source: str = "manual_remove",
        note: str = "",
        audit_action: str = "member_removed",
        last_seen_in_group_at: Optional[str] = None,
    ) -> bool:
        """Soft-delete a member row while preserving history fields."""
        existing_member = self.get_member_record(user_id, include_inactive=True)
        if not existing_member:
            logger.info(
                "User ID %s was not found in worksheet %s",
                user_id,
                self.worksheet_name,
            )
            return False

        removed_at = removed_at or self._now_local_string()
        last_seen_in_group_at = (
            last_seen_in_group_at
            or existing_member.get("Last Seen In Group At", "")
            or removed_at
        )
        update_success = self.update_member_fields(
            user_id,
            {
                "Record Status": "removed",
                "In Group Now": "No",
                "Last Seen In Group At": last_seen_in_group_at,
                "Removed At": removed_at,
                "Remove Reason": remove_reason,
                "Last Sync At": removed_at,
                "Last Sync Result": "removed",
                "Sync Note": note,
                "Sync Source": source,
            },
        )
        if not update_success:
            return False

        self.append_audit_log(
            user_id=user_id,
            username=existing_member.get("Username", ""),
            action=audit_action,
            old_value=existing_member,
            new_value={
                "Record Status": "removed",
                "In Group Now": "No",
                "Last Seen In Group At": last_seen_in_group_at,
                "Removed At": removed_at,
                "Remove Reason": remove_reason,
            },
            actor=actor,
            source=source,
            note=note or remove_reason,
        )
        logger.info("Marked member %s as removed", user_id)
        return True

    def ensure_headers(self, required_headers: List[str]) -> List[str]:
        """Ensure the worksheet header row contains the given headers."""
        snapshot = self.load_sheet_snapshot(
            worksheet_name=self.worksheet_name,
            header_template=self.MEMBER_HEADERS,
        )
        snapshot = self.ensure_headers_in_snapshot(
            snapshot,
            self.MEMBER_HEADERS + list(required_headers),
        )
        return snapshot.headers

    def update_member_fields(self, user_id: str, field_values: Dict[str, str]) -> bool:
        """Update one or more fields for an existing member row."""
        if not field_values:
            return True

        try:
            snapshot = self.load_sheet_snapshot(
                worksheet_name=self.worksheet_name,
                header_template=self.MEMBER_HEADERS,
            )
            snapshot = self.ensure_headers_in_snapshot(
                snapshot,
                self.MEMBER_HEADERS + list(field_values.keys()),
            )

            location = snapshot.member_locations.get(str(user_id))
            if not location:
                logger.info(
                    "User ID %s not found in worksheet %s",
                    user_id,
                    self.worksheet_name,
                )
                return False

            existing_row = self._pad_row(location.row_values, len(snapshot.headers))
            payload = {"User ID": str(user_id)}
            payload.update(field_values)
            updated_row = self._build_row_from_payload(
                headers=snapshot.headers,
                payload=payload,
                existing_row=existing_row,
            )

            if updated_row == existing_row:
                logger.info("Member fields for user %s already up to date", user_id)
                return True

            self._execute_value_batch_updates(
                worksheet_name=self.worksheet_name,
                value_updates=[
                    {
                        "range": self._build_row_range(
                            worksheet_name=self.worksheet_name,
                            row_number=location.row_number,
                            last_column_index=len(snapshot.headers) - 1,
                        ),
                        "values": [updated_row],
                    }
                ],
                action_name="update_member_fields",
                user_id=user_id,
                row_number=location.row_number,
            )
            logger.info("Updated member fields for user %s", user_id)
            return True
        except HttpError:
            logger.exception("Failed to update fields for user %s", user_id)
            return False
        except Exception:
            logger.exception("Unexpected failure updating fields for user %s", user_id)
            return False

    def bulk_sync_members(
        self,
        member_payloads: List[Dict[str, object]],
        *,
        remove_user_ids: Optional[List[str]] = None,
        required_headers: Optional[List[str]] = None,
        removal_payloads: Optional[List[Dict[str, object]]] = None,
    ) -> Dict[str, List[str]]:
        """Apply a sync diff using batched row updates."""
        snapshot = self.load_sheet_snapshot(
            worksheet_name=self.worksheet_name,
            header_template=self.MEMBER_HEADERS,
        )

        inferred_headers = list(required_headers or [])
        for payload in member_payloads:
            for header_name in payload:
                if header_name not in inferred_headers:
                    inferred_headers.append(header_name)
        for payload in removal_payloads or []:
            for header_name in payload:
                if header_name not in inferred_headers:
                    inferred_headers.append(header_name)

        snapshot = self.ensure_headers_in_snapshot(
            snapshot,
            self.MEMBER_HEADERS + inferred_headers,
        )

        next_row_number = len(snapshot.rows) + 1
        value_updates = []
        added_user_ids = []
        updated_user_ids = []
        unchanged_user_ids = []

        for payload in member_payloads:
            normalized_payload = self._normalize_member_payload(payload)
            user_id = normalized_payload.get("User ID", "")
            if not user_id:
                continue

            location = snapshot.member_locations.get(user_id)
            row_number = location.row_number if location else next_row_number
            existing_row = self._pad_row(
                location.row_values if location else [],
                len(snapshot.headers),
            )
            updated_row = self._build_row_from_payload(
                headers=snapshot.headers,
                payload=normalized_payload,
                existing_row=existing_row,
            )

            if location and updated_row == existing_row:
                unchanged_user_ids.append(user_id)
                continue

            value_updates.append(
                {
                    "range": self._build_row_range(
                        worksheet_name=self.worksheet_name,
                        row_number=row_number,
                        last_column_index=len(snapshot.headers) - 1,
                    ),
                    "values": [updated_row],
                }
            )

            if location:
                updated_user_ids.append(user_id)
            else:
                added_user_ids.append(user_id)
                snapshot.member_locations[user_id] = MemberRowLocation(
                    row_number=row_number,
                    row_values=updated_row,
                )
                next_row_number += 1

        removal_payloads = list(removal_payloads or [])
        for user_id in remove_user_ids or []:
            if any(str(payload.get("User ID", "")) == str(user_id) for payload in removal_payloads):
                continue
            removal_payloads.append(
                {
                    "User ID": str(user_id),
                    "Record Status": "removed",
                    "In Group Now": "No",
                    "Last Sync At": self._now_local_string(),
                    "Last Sync Result": "removed",
                    "Removed At": self._now_local_string(),
                    "Remove Reason": "Missing from Telegram group during sync",
                    "Sync Note": "Marked removed during member sync",
                    "Sync Source": "bot_api_sync",
                }
            )

        removed_user_ids = []
        for payload in removal_payloads:
            normalized_payload = self._normalize_member_payload(payload)
            user_id = normalized_payload.get("User ID", "")
            if not user_id:
                continue

            location = snapshot.member_locations.get(user_id)
            if not location:
                continue

            existing_row = self._pad_row(location.row_values, len(snapshot.headers))
            updated_row = self._build_row_from_payload(
                headers=snapshot.headers,
                payload=normalized_payload,
                existing_row=existing_row,
            )

            if updated_row != existing_row:
                value_updates.append(
                    {
                        "range": self._build_row_range(
                            worksheet_name=self.worksheet_name,
                            row_number=location.row_number,
                            last_column_index=len(snapshot.headers) - 1,
                        ),
                        "values": [updated_row],
                    }
                )
            removed_user_ids.append(user_id)

        self._execute_value_batch_updates(
            worksheet_name=self.worksheet_name,
            value_updates=value_updates,
            action_name="bulk_sync_member_rows",
            added_count=len(added_user_ids),
            updated_count=len(updated_user_ids),
            removed_count=len(removed_user_ids),
        )

        return {
            "added_user_ids": added_user_ids,
            "updated_user_ids": updated_user_ids,
            "unchanged_user_ids": unchanged_user_ids,
            "removed_user_ids": removed_user_ids,
        }

    def load_sheet_snapshot(
        self,
        *,
        worksheet_name: str,
        header_template: Optional[List[str]] = None,
    ) -> SheetSnapshot:
        """Load a worksheet once and index rows by user ID when possible."""
        self._ensure_worksheet_exists(worksheet_name)
        values = self._get_sheet_values(worksheet_name)
        if not values:
            if not header_template:
                raise ValueError(
                    f"Worksheet '{worksheet_name}' is empty and has no header row"
                )
            self._write_header_row(worksheet_name, header_template)
            values = [list(header_template)]

        headers = list(values[0])
        rows = [list(row) for row in values]
        member_locations = self._build_member_locations(headers, rows)
        return SheetSnapshot(
            worksheet_name=worksheet_name,
            headers=headers,
            rows=rows,
            member_locations=member_locations,
        )

    def ensure_headers_in_snapshot(
        self,
        snapshot: SheetSnapshot,
        required_headers: List[str],
    ) -> SheetSnapshot:
        """Ensure headers exist and keep the in-memory snapshot aligned."""
        seen_headers = set(snapshot.headers)
        missing_headers = []
        for header_name in required_headers:
            if not header_name or header_name in seen_headers:
                continue
            missing_headers.append(header_name)
            seen_headers.add(header_name)
        if not missing_headers:
            return snapshot

        updated_headers = list(snapshot.headers) + missing_headers
        header_range = (
            f"{snapshot.worksheet_name}!A1:{self._column_letter(len(updated_headers) - 1)}1"
        )
        self._execute_write_request(
            action_name="ensure_headers",
            execute_callable=lambda: self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=header_range,
                valueInputOption="RAW",
                body={"values": [updated_headers]},
            )
            .execute(),
            worksheet_name=snapshot.worksheet_name,
            added_headers=",".join(missing_headers),
        )

        logger.info(
            "Added worksheet headers to %s: %s",
            snapshot.worksheet_name,
            ", ".join(missing_headers),
        )
        snapshot.headers = updated_headers
        snapshot.rows[0] = updated_headers
        return snapshot

    def append_audit_log(
        self,
        *,
        user_id: str,
        username: str,
        action: str,
        old_value="",
        new_value="",
        actor: str = "",
        source: str = "",
        note: str = "",
        event_time: Optional[str] = None,
    ) -> bool:
        """Append a member audit log row to the audit worksheet."""
        try:
            snapshot = self.load_sheet_snapshot(
                worksheet_name=self.audit_worksheet_name,
                header_template=self.AUDIT_LOG_HEADERS,
            )
            snapshot = self.ensure_headers_in_snapshot(
                snapshot,
                self.AUDIT_LOG_HEADERS,
            )
            row_number = len(snapshot.rows) + 1
            row_values = [
                event_time or self._now_local_string(),
                str(user_id),
                username,
                action,
                self._serialize_audit_value(old_value),
                self._serialize_audit_value(new_value),
                actor,
                source,
                note,
            ]
            self._execute_write_request(
                action_name="append_audit_log",
                execute_callable=lambda: self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.spreadsheet_id,
                    range=self._build_row_range(
                        worksheet_name=self.audit_worksheet_name,
                        row_number=row_number,
                        last_column_index=len(snapshot.headers) - 1,
                    ),
                    valueInputOption="RAW",
                    body={"values": [row_values]},
                )
                .execute(),
                worksheet_name=self.audit_worksheet_name,
                user_id=user_id,
                action=action,
                row_number=row_number,
            )
            logger.info("Appended audit log for user %s action %s", user_id, action)
            return True
        except Exception:
            logger.exception("Failed to append audit log for user %s", user_id)
            return False

    def get_member_record(
        self,
        user_id: str,
        *,
        include_inactive: bool = True,
    ) -> Optional[Dict[str, str]]:
        """Return a single member record by user ID when present."""
        for member in self.get_all_members(include_inactive=include_inactive):
            if str(member.get("User ID")) == str(user_id):
                return member
        return None

    def upsert_member_record(self, payload: Dict[str, object]) -> Dict[str, object]:
        """Insert or update a member record in the Members worksheet."""
        snapshot = self.load_sheet_snapshot(
            worksheet_name=self.worksheet_name,
            header_template=self.MEMBER_HEADERS,
        )
        snapshot = self.ensure_headers_in_snapshot(snapshot, self.MEMBER_HEADERS)

        normalized_payload = self._normalize_member_payload(payload)
        user_id = normalized_payload.get("User ID", "")
        if not user_id:
            raise ValueError("User ID is required to upsert a member record")

        location = snapshot.member_locations.get(user_id)
        row_number = location.row_number if location else len(snapshot.rows) + 1
        existing_row = self._pad_row(
            location.row_values if location else [],
            len(snapshot.headers),
        )
        updated_row = self._build_row_from_payload(
            headers=snapshot.headers,
            payload=normalized_payload,
            existing_row=existing_row,
        )

        if location and updated_row == existing_row:
            return {"changed": False, "row_number": row_number, "created": False}

        self._execute_value_batch_updates(
            worksheet_name=self.worksheet_name,
            value_updates=[
                {
                    "range": self._build_row_range(
                        worksheet_name=self.worksheet_name,
                        row_number=row_number,
                        last_column_index=len(snapshot.headers) - 1,
                    ),
                    "values": [updated_row],
                }
            ],
            action_name="upsert_member_record",
            user_id=user_id,
            row_number=row_number,
        )
        return {
            "changed": True,
            "row_number": row_number,
            "created": location is None,
        }

    def _get_sheet_values(self, worksheet_name: str) -> List[List[str]]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{worksheet_name}!A:Z",
            )
            .execute()
        )
        return result.get("values", [])

    def _write_header_row(self, worksheet_name: str, headers: List[str]):
        header_range = (
            f"{worksheet_name}!A1:{self._column_letter(len(headers) - 1)}1"
        )
        self._execute_write_request(
            action_name="initialize_header_row",
            execute_callable=lambda: self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=header_range,
                valueInputOption="RAW",
                body={"values": [headers]},
            )
            .execute(),
            worksheet_name=worksheet_name,
        )

    def _ensure_worksheet_exists(self, worksheet_name: str):
        if worksheet_name in self._sheet_id_cache:
            return

        spreadsheet = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
        ).execute()
        for sheet in spreadsheet.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == worksheet_name:
                self._sheet_id_cache[worksheet_name] = properties["sheetId"]
                return

        self._execute_write_request(
            action_name="create_worksheet",
            execute_callable=lambda: self.service.spreadsheets()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": worksheet_name,
                                }
                            }
                        }
                    ]
                },
            )
            .execute(),
            worksheet_name=worksheet_name,
        )

        spreadsheet = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
        ).execute()
        for sheet in spreadsheet.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == worksheet_name:
                self._sheet_id_cache[worksheet_name] = properties["sheetId"]
                return

        raise ValueError(f"Worksheet '{worksheet_name}' not found")

    def _build_row_from_payload(
        self,
        *,
        headers: List[str],
        payload: Dict[str, str],
        existing_row: List[str],
    ) -> List[str]:
        normalized_payload = self._normalize_member_payload(payload)
        row = self._pad_row(existing_row, len(headers))
        preserved_utc = self._get_existing_value(headers, row, "Datetime (UTC)")

        defaults = {
            "Datetime (UTC)": normalized_payload.get(
                "Datetime (UTC)",
                preserved_utc or self._now_utc_string(),
            )
        }
        defaults.update(normalized_payload)

        for header_name, header_value in defaults.items():
            header_index = self._find_column_index(headers, header_name)
            if header_index is None:
                continue
            row[header_index] = header_value

        return row

    def _execute_value_batch_updates(
        self,
        *,
        worksheet_name: str,
        value_updates: List[Dict[str, object]],
        action_name: str,
        **context_fields,
    ):
        if not value_updates:
            return

        chunk_size = max(1, int(config.GOOGLE_SHEETS_BATCH_CHUNK_SIZE))
        for chunk_start in range(0, len(value_updates), chunk_size):
            chunk = value_updates[chunk_start : chunk_start + chunk_size]
            self._execute_write_request(
                action_name=action_name,
                execute_callable=lambda chunk=chunk: self.service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "valueInputOption": "RAW",
                        "data": chunk,
                    },
                )
                .execute(),
                worksheet_name=worksheet_name,
                chunk_index=(chunk_start // chunk_size) + 1,
                range_count=len(chunk),
                **context_fields,
            )

    def _execute_write_request(
        self,
        *,
        action_name: str,
        execute_callable: Callable[[], object],
        **context_fields,
    ):
        """Execute a write request with retry and audit logging."""
        attempts = max(1, int(config.GOOGLE_SHEETS_WRITE_RETRY_COUNT))
        delay_seconds = max(0.0, float(config.GOOGLE_SHEETS_WRITE_RETRY_DELAY_SECONDS))
        last_error = None

        for attempt_number in range(1, attempts + 1):
            try:
                result = execute_callable()
                audit_logger.info(
                    "google_sheets_write_success action=%s attempt=%s/%s %s",
                    action_name,
                    attempt_number,
                    attempts,
                    self._format_audit_context(context_fields),
                )
                return result
            except Exception as exc:
                last_error = exc
                audit_logger.warning(
                    "google_sheets_write_failure action=%s attempt=%s/%s error=%s %s",
                    action_name,
                    attempt_number,
                    attempts,
                    exc,
                    self._format_audit_context(context_fields),
                )
                if attempt_number >= attempts:
                    break

                logger.warning(
                    "Retrying Google Sheets write action %s (%s/%s) after error: %s",
                    action_name,
                    attempt_number,
                    attempts,
                    exc,
                )
                time.sleep(delay_seconds)

        audit_logger.error(
            "google_sheets_write_exhausted action=%s attempts=%s error=%s %s",
            action_name,
            attempts,
            last_error,
            self._format_audit_context(context_fields),
        )
        raise last_error

    def _build_member_locations(
        self,
        headers: List[str],
        rows: List[List[str]],
    ) -> Dict[str, MemberRowLocation]:
        member_locations = {}
        user_id_index = self._find_column_index(headers, "User ID")
        if user_id_index is None:
            return member_locations

        for row_number, row_values in enumerate(rows[1:], start=2):
            padded_row = self._pad_row(row_values, user_id_index + 1)
            user_id = padded_row[user_id_index]
            if not user_id:
                continue
            member_locations[str(user_id)] = MemberRowLocation(
                row_number=row_number,
                row_values=row_values,
            )
        return member_locations

    def _get_sheet_id(self, worksheet_name: str) -> int:
        self._ensure_worksheet_exists(worksheet_name)
        return self._sheet_id_cache[worksheet_name]

    def _build_row_range(
        self,
        *,
        worksheet_name: str,
        row_number: int,
        last_column_index: int,
    ) -> str:
        return (
            f"{worksheet_name}!A{row_number}:"
            f"{self._column_letter(last_column_index)}{row_number}"
        )

    def _update_single_field(
        self,
        user_id: str,
        header_name: str,
        new_value: str,
    ) -> bool:
        return self.update_member_fields(
            user_id=user_id,
            field_values={header_name: new_value},
        )

    @staticmethod
    def _normalize_member_payload(payload: Dict[str, object]) -> Dict[str, str]:
        normalized_payload = {}
        for key, value in payload.items():
            normalized_payload[key] = "" if value is None else str(value)
        return normalized_payload

    @staticmethod
    def _find_column_index(headers: List[str], header_name: str) -> Optional[int]:
        for index, header in enumerate(headers):
            if header == header_name:
                return index
        return None

    @staticmethod
    def _pad_row(row: List[str], size: int) -> List[str]:
        padded_row = list(row)
        if len(padded_row) < size:
            padded_row.extend([""] * (size - len(padded_row)))
        return padded_row

    @staticmethod
    def _column_letter(index: int) -> str:
        column_number = index + 1
        letters = []

        while column_number > 0:
            column_number, remainder = divmod(column_number - 1, 26)
            letters.append(chr(65 + remainder))

        return "".join(reversed(letters))

    @staticmethod
    def _get_existing_value(headers: List[str], row: List[str], header_name: str) -> str:
        header_index = GoogleSheetsManager._find_column_index(headers, header_name)
        if header_index is None:
            return ""
        padded_row = GoogleSheetsManager._pad_row(row, header_index + 1)
        return padded_row[header_index]

    @staticmethod
    def _format_audit_context(context_fields: Dict[str, object]) -> str:
        if not context_fields:
            return "context=none"

        parts = []
        for key in sorted(context_fields):
            value = context_fields[key]
            sanitized_value = str(value).replace(" ", "_")
            parts.append(f"{key}={sanitized_value}")
        return " ".join(parts)

    @classmethod
    def _is_member_active(cls, member: Dict[str, str]) -> bool:
        record_status = member.get("Record Status", "").strip().lower()
        in_group_now = member.get("In Group Now", "").strip().lower()
        return (
            record_status in cls.ACTIVE_RECORD_STATUSES
            and in_group_now in cls.ACTIVE_IN_GROUP_VALUES
        )

    @staticmethod
    def _serialize_audit_value(value) -> str:
        if value is None or value == "":
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _now_local_string() -> str:
        return datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _now_utc_string() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
