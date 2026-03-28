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
        del spreadsheetId, range
        return FakeExecute(lambda: {"values": copy.deepcopy(self.service.values)})

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
                            "title": self.service.worksheet_name,
                            "sheetId": self.service.sheet_id,
                        }
                    }
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
            delete_range = request["deleteDimension"]["range"]
            start_index = delete_range["startIndex"]
            del self.values[start_index]
        return {}

    def apply_update(self, range_name, rows):
        _, coordinates = range_name.split("!", 1)
        if ":" in coordinates:
            start_cell, _ = coordinates.split(":", 1)
        else:
            start_cell = coordinates

        match = re.fullmatch(r"([A-Z]+)(\d+)", start_cell)
        column_index = self.column_to_index(match.group(1))
        row_index = int(match.group(2)) - 1

        while len(self.values) <= row_index:
            self.values.append([])

        row_values = self.values[row_index]
        target_values = rows[0]

        while len(row_values) < column_index:
            row_values.append("")

        for offset, value in enumerate(target_values):
            absolute_index = column_index + offset
            while len(row_values) <= absolute_index:
                row_values.append("")
            row_values[absolute_index] = value

    @staticmethod
    def column_to_index(column_letters):
        index = 0
        for letter in column_letters:
            index = (index * 26) + (ord(letter) - 64)
        return index - 1


class GoogleSheetsManagerTests(unittest.TestCase):
    """Verify sheet writes are clean and deterministic."""

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
        self.assertEqual(service.values[1][0], "@alice")
        self.assertEqual(service.values[1][1], "123")
        self.assertEqual(service.values[1][2], "2026-04-01 10:00:00")
        self.assertEqual(service.values[1][4], "Alice")
        self.assertEqual(service.values[1][5], "Example")

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
        self.assertEqual(service.values[1][0], "@new")
        self.assertEqual(service.values[1][2], "2026-04-01 10:00:00")
        self.assertEqual(service.values[1][3], "2024-01-01 00:00:00")
        self.assertEqual(service.values[1][4], "New")
        self.assertEqual(service.values[1][5], "Person")

    def test_remove_member_from_sheet_uses_runtime_sheet_id(self):
        service = FakeGoogleSheetsService(
            [
                ["Username", "User ID", "Expiredate", "Added At", "First Name", "Last Name"],
                ["@old", "123", "2025-01-01 00:00:00", "2024-01-01 00:00:00", "Old", "Name"],
            ],
            sheet_id=99,
        )
        manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

        success = manager.remove_member_from_sheet("123")

        self.assertTrue(success)
        self.assertEqual(
            service.last_batch_request["requests"][0]["deleteDimension"]["range"]["sheetId"],
            99,
        )
        self.assertEqual(len(service.values), 1)

    def test_ensure_headers_appends_sync_columns(self):
        service = FakeGoogleSheetsService(
            [["Username", "User ID", "Expiredate", "Added At", "First Name", "Last Name"]]
        )
        manager = GoogleSheetsManager(service=service, spreadsheet_id="sheet-1")

        headers = manager.ensure_headers(["Role", "Sync Note", "Sync Source"])

        self.assertIn("Role", headers)
        self.assertIn("Sync Note", headers)
        self.assertIn("Sync Source", headers)
        self.assertEqual(service.values[0][6], "Role")
        self.assertEqual(service.values[0][7], "Sync Note")
        self.assertEqual(service.values[0][8], "Sync Source")

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
        self.assertEqual(service.values[1][6], "admin")
        self.assertEqual(service.values[1][7], "Verified")
        self.assertEqual(service.values[1][8], "bot_api_sync")
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
        self.assertEqual(service.batch_attempts, 1)
        self.assertEqual(service.values[1][1], "111")
        self.assertEqual(service.values[1][6], "member")
        self.assertEqual(service.values[2][1], "333")
        self.assertEqual(service.values[2][8], "bot_api_admin_backfill")

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
