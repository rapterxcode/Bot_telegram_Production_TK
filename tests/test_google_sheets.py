"""Tests for Google Sheets upsert, bulk sync, delete, and retry helpers."""

import copy
import re
import unittest

from app.core import config
from app.services.google_sheets import GoogleSheetsManager


class FakeExecute:
    """Wrap a callable in a google-api-like execute interface."""

    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class FakeValuesResource:
    """Implement the values() subset used by the service."""

    def __init__(self, service):
        self.service = service

    def get(self, spreadsheetId, range):
        del spreadsheetId
        worksheet_name = range.split("!", 1)[0]
        return FakeExecute(
            lambda: {
                "values": copy.deepcopy(
                    self.service.sheet_values.get(worksheet_name, [])
                )
            }
        )

    def update(self, spreadsheetId, range, valueInputOption, body):
        del spreadsheetId, valueInputOption
        return FakeExecute(lambda: self.service.execute_update(range, body["values"]))

    def batchUpdate(self, spreadsheetId, body):
        del spreadsheetId
        return FakeExecute(lambda: self.service.execute_values_batch_update(body))


class FakeSpreadsheetsResource:
    """Implement the spreadsheets() subset used by the service."""

    def __init__(self, service):
        self.service = service

    def values(self):
        return FakeValuesResource(self.service)

    def batchUpdate(self, spreadsheetId, body):
        del spreadsheetId
        return FakeExecute(lambda: self.service.execute_batch_update(body))

    def get(self, spreadsheetId):
        del spreadsheetId
        return FakeExecute(
            lambda: {
                "sheets": [
                    {
                        "properties": {
                            "title": worksheet_name,
                            "sheetId": sheet_id,
                        }
                    }
                    for worksheet_name, sheet_id in self.service.sheet_ids.items()
                ]
            }
        )


class FakeGoogleSheetsService:
    """In-memory sheet representation used by tests."""

    def __init__(
        self,
        values,
        worksheet_name="Members",
        sheet_id=42,
        update_failures_remaining=0,
        batch_failures_remaining=0,
        values_batch_failures_remaining=0,
    ):
        self.values = copy.deepcopy(values)
        self.worksheet_name = worksheet_name
        self.sheet_id = sheet_id
        self.updated_ranges = []
        self.batch_value_ranges = []
        self.last_batch_request = None
        self.update_failures_remaining = update_failures_remaining
        self.batch_failures_remaining = batch_failures_remaining
        self.values_batch_failures_remaining = values_batch_failures_remaining
        self.update_attempts = 0
        self.batch_attempts = 0
        self.values_batch_attempts = 0
        self.primary_worksheet_name = worksheet_name
        self.values = copy.deepcopy(values)
        self.sheet_values = {worksheet_name: self.values}
        self.sheet_ids = {worksheet_name: sheet_id}

    def spreadsheets(self):
        return FakeSpreadsheetsResource(self)

    def execute_update(self, range_name, rows):
        self.update_attempts += 1
        if self.update_failures_remaining > 0:
            self.update_failures_remaining -= 1
            raise RuntimeError("temporary update failure")

        self.updated_ranges.append((range_name, copy.deepcopy(rows)))
        self.apply_update(range_name, rows)
        return {}

    def execute_values_batch_update(self, body):
        self.values_batch_attempts += 1
        if self.values_batch_failures_remaining > 0:
            self.values_batch_failures_remaining -= 1
            raise RuntimeError("temporary values batch failure")

        self.batch_value_ranges.append(copy.deepcopy(body["data"]))
        for value_range in body["data"]:
            self.apply_update(value_range["range"], value_range["values"])
        return {}

    def execute_batch_update(self, body):
        self.batch_attempts += 1
        if self.batch_failures_remaining > 0:
            self.batch_failures_remaining -= 1
            raise RuntimeError("temporary batch failure")

        self.last_batch_request = copy.deepcopy(body)
        for request in body["requests"]:
            if "deleteDimension" in request:
                delete_range = request["deleteDimension"]["range"]
                start_index = delete_range["startIndex"]
                target_sheet_id = delete_range["sheetId"]
                worksheet_name = self.sheet_name_from_id(target_sheet_id)
                del self.sheet_values[worksheet_name][start_index]
                continue

            if "addSheet" in request:
                title = request["addSheet"]["properties"]["title"]
                if title not in self.sheet_values:
                    next_sheet_id = max(self.sheet_ids.values(), default=0) + 1
                    self.sheet_values[title] = []
                    self.sheet_ids[title] = next_sheet_id
        return {}

    def apply_update(self, range_name, rows):
        worksheet_name, coordinates = range_name.split("!", 1)
        if ":" in coordinates:
            start_cell, _ = coordinates.split(":", 1)
        else:
            start_cell = coordinates

        match = re.fullmatch(r"([A-Z]+)(\d+)", start_cell)
        column_index = self.column_to_index(match.group(1))
        row_index = int(match.group(2)) - 1

        target_values = self.sheet_values.setdefault(worksheet_name, [])

        while len(target_values) <= row_index:
            target_values.append([])

        row_values = target_values[row_index]
        new_values = rows[0]

        while len(row_values) < column_index:
            row_values.append("")

        for offset, value in enumerate(new_values):
            absolute_index = column_index + offset
            while len(row_values) <= absolute_index:
                row_values.append("")
            row_values[absolute_index] = value

    def sheet_name_from_id(self, target_sheet_id):
        for worksheet_name, sheet_id in self.sheet_ids.items():
            if sheet_id == target_sheet_id:
                return worksheet_name
        raise KeyError(target_sheet_id)

    @staticmethod
    def column_to_index(column_letters):
        index = 0
        for letter in column_letters:
            index = (index * 26) + (ord(letter) - 64)
        return index - 1


class GoogleSheetsManagerTests(unittest.TestCase):
    """Verify sheet writes are clean and deterministic."""

    @staticmethod
    def row_to_dict(headers, row):
        padded_row = list(row)
        if len(padded_row) < len(headers):
            padded_row.extend([""] * (len(headers) - len(padded_row)))
        return {
            header: padded_row[index]
            for index, header in enumerate(headers)
        }

    def test_add_member_with_details_inserts_new_row(self):
        service = FakeGoogleSheetsService(
            [["Username", "User ID", "Expiredate", "Added At", "First Name", "Last Name"]]
        )
        manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

        success = manager.add_member_with_details(
            "@alice",
            "123",
            "2026-04-01 10:00:00",
            "Alice",
            "Example",
        )

        self.assertTrue(success)
        row = self.row_to_dict(service.values[0], service.values[1])
        self.assertEqual(row["Username"], "@alice")
        self.assertEqual(row["User ID"], "123")
        self.assertEqual(row["Expiredate"], "2026-04-01 10:00:00")
        self.assertEqual(row["First Name"], "Alice")
        self.assertEqual(row["Last Name"], "Example")
        self.assertEqual(row["Record Status"], "active")
        self.assertEqual(row["In Group Now"], "Yes")

    def test_add_member_with_details_updates_existing_user_id(self):
        service = FakeGoogleSheetsService(
            [
                ["Username", "User ID", "Expiredate", "Added At", "First Name", "Last Name"],
                ["@old", "123", "2025-01-01 00:00:00", "2024-01-01 00:00:00", "Old", "Name"],
            ]
        )
        manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

        success = manager.add_member_with_details(
            "@new",
            "123",
            "2026-04-01 10:00:00",
            "New",
            "Person",
        )

        self.assertTrue(success)
        self.assertEqual(len(service.values), 2)
        row = self.row_to_dict(service.values[0], service.values[1])
        self.assertEqual(row["Username"], "@new")
        self.assertEqual(row["Expiredate"], "2026-04-01 10:00:00")
        self.assertEqual(row["Added At"], "2024-01-01 00:00:00")
        self.assertEqual(row["First Name"], "New")
        self.assertEqual(row["Last Name"], "Person")
        self.assertNotEqual(row["Datetime (UTC)"], "")

    def test_remove_member_from_sheet_uses_runtime_sheet_id(self):
        service = FakeGoogleSheetsService(
            [
                ["Username", "User ID", "Expiredate", "Added At", "First Name", "Last Name"],
                ["@old", "123", "2025-01-01 00:00:00", "2024-01-01 00:00:00", "Old", "Name"],
            ],
            sheet_id=99,
        )
        manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

        success = manager.remove_member_from_sheet(
            "123",
            remove_reason="Left Telegram group",
            actor="@system",
            source="chat_member_update",
            note="Telegram reported that the member left the group",
        )

        self.assertTrue(success)
        member_row = self.row_to_dict(service.values[0], service.values[1])
        self.assertEqual(member_row["Record Status"], "removed")
        self.assertEqual(member_row["In Group Now"], "No")
        self.assertEqual(member_row["Remove Reason"], "Left Telegram group")
        self.assertEqual(member_row["Sync Source"], "chat_member_update")
        self.assertNotEqual(member_row["Removed At"], "")

        audit_headers = service.sheet_values["audit_logs"][0]
        audit_row = self.row_to_dict(
            audit_headers,
            service.sheet_values["audit_logs"][1],
        )
        self.assertEqual(audit_row["User ID"], "123")
        self.assertEqual(audit_row["Action"], "member_removed")
        self.assertEqual(audit_row["Actor"], "@system")
        self.assertEqual(audit_row["Source"], "chat_member_update")
        self.assertIn("Left Telegram group", audit_row["New Value"])

    def test_ensure_headers_appends_sync_columns(self):
        service = FakeGoogleSheetsService(
            [["Username", "User ID", "Expiredate", "Added At", "First Name", "Last Name"]]
        )
        manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

        headers = manager.ensure_headers(["Role", "Sync Note", "Sync Source"])

        self.assertIn("Role", headers)
        self.assertIn("Sync Note", headers)
        self.assertIn("Sync Source", headers)
        self.assertEqual(service.values[0], headers)
        self.assertTrue(set(manager.MEMBER_HEADERS).issubset(set(headers)))

    def test_update_member_fields_updates_row_once(self):
        service = FakeGoogleSheetsService(
            [
                [
                    "Username",
                    "User ID",
                    "Expiredate",
                    "Added At",
                    "First Name",
                    "Last Name",
                    "Role",
                ],
                ["@old", "123", "2025-01-01 00:00:00", "2024-01-01 00:00:00", "Old", "Name", ""],
            ]
        )
        manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

        success = manager.update_member_fields(
            "123",
            {
                "Role": "admin",
                "Sync Note": "Verified",
                "Sync Source": "bot_api_sync",
            },
        )

        self.assertTrue(success)
        row = self.row_to_dict(service.values[0], service.values[1])
        self.assertEqual(row["Role"], "admin")
        self.assertEqual(row["Sync Note"], "Verified")
        self.assertEqual(row["Sync Source"], "bot_api_sync")
        self.assertEqual(service.values_batch_attempts, 1)

    def test_bulk_sync_members_batches_updates_and_deletes(self):
        service = FakeGoogleSheetsService(
            [
                [
                    "Username",
                    "User ID",
                    "Expiredate",
                    "Added At",
                    "First Name",
                    "Last Name",
                    "Telegram Status",
                    "Role",
                ],
                ["@old1", "111", "2025-01-01 00:00:00", "2024-01-01 00:00:00", "Old", "One", "", ""],
                ["@old2", "222", "2025-01-01 00:00:00", "2024-01-01 00:00:00", "Old", "Two", "", ""],
            ]
        )
        manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

        result = manager.bulk_sync_members(
            [
                {
                    "Username": "@old1",
                    "User ID": "111",
                    "Expiredate": "2025-01-01 00:00:00",
                    "First Name": "Old",
                    "Last Name": "One",
                    "Telegram Status": "member",
                    "Role": "member",
                    "Sync Source": "bot_api_sync",
                },
                {
                    "Username": "@new3",
                    "User ID": "333",
                    "Expiredate": "no_expire",
                    "First Name": "New",
                    "Last Name": "Three",
                    "Telegram Status": "administrator",
                    "Role": "admin",
                    "Sync Source": "bot_api_admin_backfill",
                },
            ],
            remove_user_ids=["222"],
            required_headers=["Sync Source"],
        )

        self.assertEqual(result["added_user_ids"], ["333"])
        self.assertEqual(result["updated_user_ids"], ["111"])
        self.assertEqual(result["removed_user_ids"], ["222"])
        self.assertEqual(service.values_batch_attempts, 1)
        self.assertEqual(service.batch_attempts, 0)

        member_rows = {
            row_dict["User ID"]: row_dict
            for row_dict in (
                self.row_to_dict(service.values[0], row)
                for row in service.values[1:]
            )
        }
        self.assertEqual(member_rows["111"]["Telegram Status"], "member")
        self.assertEqual(member_rows["111"]["Role"], "member")
        self.assertEqual(member_rows["111"]["Sync Source"], "bot_api_sync")
        self.assertEqual(member_rows["222"]["Record Status"], "removed")
        self.assertEqual(member_rows["222"]["In Group Now"], "No")
        self.assertEqual(member_rows["333"]["Role"], "admin")
        self.assertEqual(member_rows["333"]["Sync Source"], "bot_api_admin_backfill")

    def test_write_operations_retry_after_transient_failure(self):
        original_retry_count = config.GOOGLE_SHEETS_WRITE_RETRY_COUNT
        original_retry_delay = config.GOOGLE_SHEETS_WRITE_RETRY_DELAY_SECONDS
        config.GOOGLE_SHEETS_WRITE_RETRY_COUNT = 2
        config.GOOGLE_SHEETS_WRITE_RETRY_DELAY_SECONDS = 0

        try:
            service = FakeGoogleSheetsService(
                [["Username", "User ID", "Expiredate", "Added At", "First Name", "Last Name"]],
                update_failures_remaining=1,
            )
            manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

            headers = manager.ensure_headers(["Role"])

            self.assertEqual(service.update_attempts, 2)
            self.assertIn("Role", headers)
            self.assertEqual(service.values[0][6], "Role")
        finally:
            config.GOOGLE_SHEETS_WRITE_RETRY_COUNT = original_retry_count
            config.GOOGLE_SHEETS_WRITE_RETRY_DELAY_SECONDS = original_retry_delay


if __name__ == "__main__":
    unittest.main()
