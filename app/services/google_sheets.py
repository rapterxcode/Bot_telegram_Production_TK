"""Google Sheets access helpers for member data."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
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

    headers: List[str]
    rows: List[List[str]]
    member_locations: Dict[str, MemberRowLocation]


class GoogleSheetsManager:
    """Read and write member data in a single worksheet."""

    BASE_MEMBER_HEADERS = [
        "Username",
        "User ID",
        "Expiredate",
        "Added At",
        "First Name",
        "Last Name",
    ]
    MEMBER_COLUMNS = 6

    def __init__(self, service=None, spreadsheet_id: Optional[str] = None):
        self.credentials = None
        self.service = service
        self.spreadsheet_id = spreadsheet_id or config.GOOGLE_SHEETS_ID
        self.worksheet_name = config.WORKSHEET_NAME
        self._sheet_id_cache = None

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

    def get_all_members(self) -> List[Dict]:
        """Return all member rows that have both username and user ID."""
        try:
            values = self._get_sheet_values()
            if not values:
                return []

            headers = values[0]
            members = []
            for row in values[1:]:
                padded_row = self._pad_row(row, len(headers))
                member = {
                    header: padded_row[index]
                    for index, header in enumerate(headers)
                }
                if member.get("User ID") and member.get("Username"):
                    members.append(member)

            return members
        except HttpError:
            logger.exception("Failed to read members from Google Sheets")
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
    ) -> bool:
        """Insert a new member or update the existing row matched by User ID."""
        try:
            snapshot = self.load_sheet_snapshot()
            location = snapshot.member_locations.get(str(user_id))

            if location:
                return self._update_existing_member(
                    location=location,
                    username=username,
                    user_id=user_id,
                    expire_date=expire_date,
                    first_name=first_name,
                    last_name=last_name,
                )

            return self._insert_member(
                next_row=len(snapshot.rows) + 1,
                username=username,
                user_id=user_id,
                expire_date=expire_date,
                first_name=first_name,
                last_name=last_name,
            )
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

    def remove_member_from_sheet(self, user_id: str) -> bool:
        """Delete a member row using the configured worksheet name."""
        try:
            snapshot = self.load_sheet_snapshot()
            location = snapshot.member_locations.get(str(user_id))
            if not location:
                logger.info(
                    "User ID %s was not found in worksheet %s",
                    user_id,
                    self.worksheet_name,
                )
                return False

            self._delete_rows_by_numbers(
                [location.row_number],
                action_name="delete_member_row",
            )
            logger.info("Deleted member row for user ID %s", user_id)
            return True
        except HttpError:
            logger.exception("Failed to delete member %s from worksheet", user_id)
            return False
        except Exception:
            logger.exception("Unexpected failure deleting member %s", user_id)
            return False

    def ensure_headers(self, required_headers: List[str]) -> List[str]:
        """Ensure the worksheet header row contains the given headers."""
        snapshot = self.load_sheet_snapshot()
        snapshot = self.ensure_headers_in_snapshot(snapshot, required_headers)
        return snapshot.headers

    def update_member_fields(self, user_id: str, field_values: Dict[str, str]) -> bool:
        """Update one or more fields for an existing member row."""
        if not field_values:
            return True

        try:
            snapshot = self.load_sheet_snapshot()
            snapshot = self.ensure_headers_in_snapshot(snapshot, list(field_values.keys()))

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
                [
                    {
                        "range": self._build_row_range(
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
        member_payloads: List[Dict[str, str]],
        *,
        remove_user_ids: Optional[List[str]] = None,
        required_headers: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """Apply a sync diff using batched value updates and row deletes."""
        snapshot = self.load_sheet_snapshot()

        inferred_headers = list(required_headers or [])
        for payload in member_payloads:
            for header_name in payload:
                if header_name not in self.BASE_MEMBER_HEADERS and header_name not in inferred_headers:
                    inferred_headers.append(header_name)

        snapshot = self.ensure_headers_in_snapshot(snapshot, inferred_headers)

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
                next_row_number += 1

        self._execute_value_batch_updates(
            value_updates,
            action_name="bulk_sync_member_rows",
            added_count=len(added_user_ids),
            updated_count=len(updated_user_ids),
        )

        removed_user_ids = self._delete_rows_by_user_ids(
            snapshot,
            remove_user_ids or [],
            action_name="bulk_sync_delete_rows",
        )

        return {
            "added_user_ids": added_user_ids,
            "updated_user_ids": updated_user_ids,
            "unchanged_user_ids": unchanged_user_ids,
            "removed_user_ids": removed_user_ids,
        }

    def load_sheet_snapshot(self) -> SheetSnapshot:
        """Load the worksheet once and index rows by user ID."""
        values = self._get_sheet_values()
        if not values:
            raise ValueError(
                f"Worksheet '{self.worksheet_name}' is empty and has no header row"
            )

        headers = list(values[0])
        rows = [list(row) for row in values]
        member_locations = self._build_member_locations(headers, rows)
        return SheetSnapshot(headers=headers, rows=rows, member_locations=member_locations)

    def ensure_headers_in_snapshot(
        self,
        snapshot: SheetSnapshot,
        required_headers: List[str],
    ) -> SheetSnapshot:
        """Ensure headers exist and keep the in-memory snapshot aligned."""
        missing_headers = [
            header_name
            for header_name in required_headers
            if header_name and header_name not in snapshot.headers
        ]
        if not missing_headers:
            return snapshot

        updated_headers = list(snapshot.headers) + missing_headers
        header_range = (
            f"{self.worksheet_name}!A1:{self._column_letter(len(updated_headers) - 1)}1"
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
            added_headers=",".join(missing_headers),
        )

        logger.info("Added worksheet headers: %s", ", ".join(missing_headers))
        snapshot.headers = updated_headers
        snapshot.rows[0] = updated_headers
        return snapshot

    def _get_sheet_values(self) -> List[List[str]]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.worksheet_name}!A:Z",
            )
            .execute()
        )
        return result.get("values", [])

    def _insert_member(
        self,
        next_row: int,
        username: str,
        user_id: str,
        expire_date: str,
        first_name: str,
        last_name: str,
    ) -> bool:
        row_values = self._build_member_row(
            username=username,
            user_id=user_id,
            expire_date=expire_date,
            first_name=first_name,
            last_name=last_name,
        )
        range_name = f"{self.worksheet_name}!A{next_row}:F{next_row}"

        self._execute_write_request(
            action_name="insert_member",
            execute_callable=lambda: self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [row_values]},
            )
            .execute(),
            user_id=user_id,
            username=username,
            row_number=next_row,
        )

        logger.info("Inserted member %s (user ID %s)", username, user_id)
        return True

    def _update_existing_member(
        self,
        location: MemberRowLocation,
        username: str,
        user_id: str,
        expire_date: str,
        first_name: str,
        last_name: str,
    ) -> bool:
        updated_row = self._build_member_row(
            username=username,
            user_id=user_id,
            expire_date=expire_date,
            first_name=first_name,
            last_name=last_name,
            existing_row=location.row_values,
        )
        existing_row = self._pad_row(location.row_values, self.MEMBER_COLUMNS)[: self.MEMBER_COLUMNS]

        if updated_row == existing_row:
            logger.info(
                "Member %s already matches worksheet data; skipping update",
                user_id,
            )
            return True

        range_name = f"{self.worksheet_name}!A{location.row_number}:F{location.row_number}"
        self._execute_write_request(
            action_name="update_member_row",
            execute_callable=lambda: self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [updated_row]},
            )
            .execute(),
            user_id=user_id,
            username=username,
            row_number=location.row_number,
        )

        logger.info("Updated member %s in worksheet row %s", user_id, location.row_number)
        return True

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

    def _build_member_row(
        self,
        username: str,
        user_id: str,
        expire_date: str,
        first_name: str = "",
        last_name: str = "",
        existing_row: Optional[List[str]] = None,
    ) -> List[str]:
        current_time = datetime.now(pytz.timezone(config.TIMEZONE)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        padded_existing_row = self._pad_row(existing_row or [], self.MEMBER_COLUMNS)

        created_at = padded_existing_row[3] or current_time
        stored_first_name = padded_existing_row[4]
        stored_last_name = padded_existing_row[5]

        return [
            username,
            str(user_id),
            expire_date,
            created_at,
            first_name or stored_first_name,
            last_name or stored_last_name,
        ]

    def _build_row_from_payload(
        self,
        *,
        headers: List[str],
        payload: Dict[str, str],
        existing_row: List[str],
    ) -> List[str]:
        normalized_payload = self._normalize_member_payload(payload)
        row = self._pad_row(existing_row, len(headers))

        current_time = datetime.now(pytz.timezone(config.TIMEZONE)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        added_at_value = normalized_payload.get("Added At") or self._get_existing_value(
            headers,
            row,
            "Added At",
        ) or current_time
        first_name_value = normalized_payload.get("First Name") or self._get_existing_value(
            headers,
            row,
            "First Name",
        )
        last_name_value = normalized_payload.get("Last Name") or self._get_existing_value(
            headers,
            row,
            "Last Name",
        )

        base_values = {
            "Username": normalized_payload.get("Username", self._get_existing_value(headers, row, "Username")),
            "User ID": normalized_payload.get("User ID", self._get_existing_value(headers, row, "User ID")),
            "Expiredate": normalized_payload.get(
                "Expiredate",
                self._get_existing_value(headers, row, "Expiredate"),
            ),
            "Added At": added_at_value,
            "First Name": first_name_value,
            "Last Name": last_name_value,
        }

        for header_name, header_value in base_values.items():
            header_index = self._find_column_index(headers, header_name)
            if header_index is not None:
                row[header_index] = header_value

        for header_name, header_value in normalized_payload.items():
            header_index = self._find_column_index(headers, header_name)
            if header_index is None:
                continue
            row[header_index] = header_value

        return row

    def _delete_rows_by_user_ids(
        self,
        snapshot: SheetSnapshot,
        user_ids: List[str],
        *,
        action_name: str,
    ) -> List[str]:
        row_numbers = []
        removed_user_ids = []

        for user_id in user_ids:
            location = snapshot.member_locations.get(str(user_id))
            if not location:
                continue
            row_numbers.append(location.row_number)
            removed_user_ids.append(str(user_id))

        self._delete_rows_by_numbers(row_numbers, action_name=action_name)
        return removed_user_ids

    def _delete_rows_by_numbers(self, row_numbers: List[int], *, action_name: str):
        if not row_numbers:
            return

        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": self._get_sheet_id(),
                        "dimension": "ROWS",
                        "startIndex": row_number - 1,
                        "endIndex": row_number,
                    }
                }
            }
            for row_number in sorted(set(row_numbers), reverse=True)
        ]

        chunk_size = max(1, int(config.GOOGLE_SHEETS_BATCH_CHUNK_SIZE))
        for chunk_start in range(0, len(requests), chunk_size):
            chunk = requests[chunk_start : chunk_start + chunk_size]
            self._execute_write_request(
                action_name=action_name,
                execute_callable=lambda chunk=chunk: self.service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": chunk},
                )
                .execute(),
                chunk_index=(chunk_start // chunk_size) + 1,
                request_count=len(chunk),
            )

    def _execute_value_batch_updates(
        self,
        value_updates: List[Dict[str, object]],
        *,
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
            logger.error("Header 'User ID' not found in worksheet %s", self.worksheet_name)
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

    def _get_sheet_id(self) -> int:
        if self._sheet_id_cache is not None:
            return self._sheet_id_cache

        spreadsheet = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
        ).execute()
        for sheet in spreadsheet.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == self.worksheet_name:
                self._sheet_id_cache = properties["sheetId"]
                return self._sheet_id_cache

        raise ValueError(f"Worksheet '{self.worksheet_name}' not found")

    def _build_row_range(self, row_number: int, last_column_index: int) -> str:
        return (
            f"{self.worksheet_name}!A{row_number}:"
            f"{self._column_letter(last_column_index)}{row_number}"
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
