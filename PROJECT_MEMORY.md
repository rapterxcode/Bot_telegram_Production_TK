# Project Memory: Bot_telegram_Production_TK

## Working Rules

- Read this file before starting work in this repository.
- Update this file whenever behavior, flow, config, dependency, deployment, or file structure changes.
- `app/...` is the source of truth for application logic.

## Project Overview

- This project is a Telegram bot for semi-automated group member management.
- Member data is stored in Google Sheets.
- The bot supports admin-driven member adds, invite links, join-request approval, and expired-member cleanup.
- Runtime state that must survive restarts is now persisted locally.

## Current Structure

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
    reconciliation.py
    telegram_bot.py
  core/
    config.py
  services/
    google_sheets.py
    state_store.py
    telethon_reconcile.py

data/
  bot_state.json          # created at runtime

tests/
  test_application.py
  test_callbacks.py
  test_config.py
  test_google_sheets.py
  test_reconciliation.py
  test_state_store.py

Dockerfile
docker-compose.yml
docker-run.sh
README.md
PROJECT_MEMORY.md
requirements.txt
```

## Important Files

- `app/main.py`: async entrypoint.
- `app/bot/telegram_bot.py`: orchestrator for lifecycle, shared runtime state, scheduler wiring, and common helpers.
- `app/bot/application.py`: handler registration and Telegram suggested commands.
- `app/bot/events.py`: chat member updates and join-request intake.
- `app/bot/callbacks.py`: approve/reject flows for pending members.
- `app/bot/member_commands.py`: admin commands for member management and scheduler interval changes.
- `app/bot/reconciliation.py`: group/sheet reconciliation helpers and `/syncmembers`.
- `app/bot/invites.py`: invite-link creation and cleanup.
- `app/bot/notifications.py`: admin notification helpers.
- `app/services/google_sheets.py`: Google Sheets reads, upserts by `User ID`, deletes, and field updates, including sync metadata columns.
- `app/services/state_store.py`: JSON persistence for runtime bot state.

## Runtime Flow

### Startup

- Run with `python -m app.main`.
- `app.main.main()` creates `TelegramMemberBot` and awaits `bot.run()`.
- `TelegramMemberBot.__init__()` loads persisted runtime state from `BOT_STATE_FILE` (default `data/bot_state.json`).
- `TelegramMemberBot.run()` builds the Telegram application, registers handlers, schedules the expired-member job, initializes the app, and starts polling.

### Polling

- Polling now explicitly requests these update types:
  - `message`
  - `callback_query`
  - `chat_member`
  - `chat_join_request`
  - `my_chat_member`

### Scheduler

- `_setup_job_queue()` is now wired during startup.
- The repeating job name is `check_expired_members`.
- `/setcheckinterval` reschedules the existing job instead of duplicating scheduling logic.

### Reconciliation

- `/syncmembers` verifies every `User ID` already known in Google Sheets against the current Telegram group.
- Bot API member lookups are now concurrency-limited instead of fully serial.
- During sync, rows missing from the Telegram group are removed from the sheet.
- Active rows are refreshed with extra metadata columns such as Telegram status, role, in-group flag, sync note, and last sync time.
- Google Sheets sync writes are now diffed in memory and written back with batched value updates and batched row deletes.
- When enabled, admins currently in Telegram but missing from the sheet are auto-added with a configurable backfill expiry value.
- `/status` now prefers the latest persisted sync snapshot for a faster response.
- `/statuslive` forces a fresh live lookup when an admin wants to bypass the cached snapshot.
- `/fullsyncmembers` uses an optional Telethon user session to enumerate the full group membership and reconcile the sheet exactly.
- Admins currently in Telegram but missing from the sheet are either auto-added or reported in sync/status output depending on config.
- The implementation uses Bot API methods such as member count, admin list, and per-user lookups.

### Join / Approval Flow

- `handle_chat_join_request()` reads invite-link metadata, calculates the member expiry, and stores a pending record.
- Pending join-request state now stores `chat_id` instead of a live `join_request` object so approval survives a restart.
- `handle_approval_callback()` approves or rejects both:
  - join requests
  - direct member additions that still need admin review
- Pending-list buttons now preserve whether a record is a join request or a member update.

### Direct Add Flow

- If an admin adds a member directly in Telegram, `handle_chat_member_update()` auto-adds that member to Google Sheets with the default expiry.
- If a non-admin-driven member update needs approval, it is stored in pending state and sent to the admin group.

## Runtime State

The following state is now persisted in `BOT_STATE_FILE`:

- `invite_link_expires`
- `active_invite_links`
- `pending_members`
- `sent_notifications`
- `last_sync_snapshot`

Notes:

- Expired invite-link metadata is cleaned during startup and during invite-link handling.
- `recent_join_type` is still in-memory only because it is only a short-lived fallback.

## Google Sheet Contract

Required headers used by the code:

- `Username`
- `User ID`
- `Expiredate`

Columns written by the bot:

- A = `Username`
- B = `User ID`
- C = `Expiredate`
- D = created timestamp
- E = `First Name`
- F = `Last Name`

Additional optional metadata columns may be created automatically:

- `Telegram Status`
- `Role`
- `In Group Now`
- `Sync Note`
- `Last Sync At`
- `Sync Source`

Current behavior:

- member writes are upserts keyed by `User ID`
- duplicate writes become no-ops when the row already matches
- sync writes batch row updates with `spreadsheets.values.batchUpdate(...)`
- sync deletes batch row removals with a single `spreadsheets().batchUpdate(...)` request chunk
- deletes now resolve the real worksheet `sheetId` from spreadsheet metadata instead of hardcoding `0`
- sync metadata headers are appended automatically when missing

## Environment Variables In Use

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USER_ID`
- `GROUP_CHAT_ID`
- `GROUP_CHAT_ID_FOR_ADMIN`
- `GOOGLE_SHEETS_ID`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `WORKSHEET_NAME`
- `TIMEZONE`
- `BOT_STATE_FILE`
- `CHECK_INTERVAL_VALUE`
- `CHECK_INTERVAL_UNIT`
- `DEFAULT_EXPIRE_DAYS`
- `INVITE_LINK_EXPIRE_MINUTES`
- `INVITE_LINK_1MONTH_DAYS`
- `INVITE_LINK_1YEAR_DAYS`
- `INVITE_LINK_NOEXPIRE`
- `GOOGLE_SHEETS_WRITE_RETRY_COUNT`
- `GOOGLE_SHEETS_WRITE_RETRY_DELAY_SECONDS`
- `GOOGLE_SHEETS_BATCH_CHUNK_SIZE`
- `STATUS_USE_CACHED_SNAPSHOT`
- `TELEGRAM_MEMBER_LOOKUP_CONCURRENCY`
- `SYNC_AUTO_ADD_MISSING_ADMINS_TO_SHEET`
- `SYNC_BACKFILL_EXPIREDATE`
- `TELETHON_API_ID`
- `TELETHON_API_HASH`
- `TELETHON_SESSION_NAME`
- `TELETHON_SESSION_STRING`

Notes:

- `ADMIN_USER_ID` supports multiple comma-separated IDs.
- `SYNC_BACKFILL_EXPIREDATE` also accepts the legacy env name `TELETHON_FULL_SYNC_BACKFILL_EXPIREDATE`.
- Telethon full sync remains optional and only activates when the Telethon env vars are configured.

## Logging

- Global logging is configured in `app/bot/logging_config.py`.
- The bot writes to console and to files in `logs/`.
- Google Sheets and state persistence now log through the application logger instead of `print(...)`.
- Google Sheets write attempts now also write audit entries to `logs/google_sheets_audit.log`.
- Verbose upstream HTTP request loggers are now reduced to warning level to keep secrets out of normal console output.

## Tests

Smoke tests now exist for:

- config helpers
- handler registration and polling update coverage
- callback helper parsing
- Google Sheets upsert/delete behavior
- reconciliation helpers
- runtime state persistence

Validation command:

```bash
python -m unittest discover -s tests
```

## Completed Cleanup / Improvements

- Scheduler startup is now wired automatically.
- Polling `allowed_updates` is explicit for the events the bot relies on.
- Runtime bot state survives restarts through local JSON persistence, and the path is now configurable.
- Join-request approvals can continue after restart because `chat_id` is persisted.
- Pending-list callback buttons now preserve join-request vs member-update flow.
- Google Sheets writes are now upserts by `User ID`.
- Google Sheets sync operations now batch row updates and row deletes.
- Google Sheets delete no longer hardcodes `sheetId = 0`.
- Added Bot API-based `/syncmembers` reconciliation for known sheet users.
- Added concurrency-limited Telegram member lookups during Bot API sync.
- Added retry and audit logging around Google Sheets writes.
- Added configurable admin auto-add during `/syncmembers`.
- Added optional Telethon-powered `/fullsyncmembers` for exact member backfill.
- `/status` now uses the latest persisted snapshot by default, and `/statuslive` keeps the live-lookup path available.
- Added smoke tests for core flows and helpers.

## Known Gaps

- The bot still cannot enumerate every Telegram group member directly with Bot API alone.
- `/syncmembers` can fully verify known sheet users and current admins, but it still cannot backfill unknown non-admin group members that the bot has never seen.
- `/fullsyncmembers` requires a separate authorized Telethon user session; it will not work with bot token credentials alone.
- Runtime state persistence is local-file based only; there is no external shared state store for multi-instance deployments.
- Command replies still primarily target `GROUP_CHAT_ID_FOR_ADMIN` instead of direct DM replies in all cases.
- Some existing Thai log/message strings may render incorrectly on consoles that are not UTF-8.
- `/setcheckinterval` still changes runtime config only until the bot restarts.

## Recommended Next Work

1. Add a one-time bootstrap or admin-only utility for creating/authorizing the Telethon session cleanly.
2. Consider moving runtime state from local JSON to a shared store if the bot will run on multiple instances.
3. Add higher-level approval-flow tests that exercise callback handling end to end.
4. Clean up the remaining legacy Thai message strings that were previously saved with broken encoding.
5. Consider adding a summarized sync history log or sheet tab for admin auditing over time.
