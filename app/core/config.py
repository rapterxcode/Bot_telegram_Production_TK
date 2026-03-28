"""Runtime configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def parse_bool_env(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized_value = raw_value.strip().lower()
    return normalized_value in {"1", "true", "yes", "on"}


def parse_optional_int(name: str):
    """Parse an optional integer environment variable."""
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return None
    return int(raw_value)


def parse_admin_ids():
    """Parse ADMIN_USER_ID into a list of integer user IDs."""
    admin_ids = []
    admin_env = os.getenv("ADMIN_USER_ID", "")

    if admin_env:
        for id_str in admin_env.split(","):
            try:
                admin_id = int(id_str.strip())
                if admin_id > 0:
                    admin_ids.append(admin_id)
            except ValueError:
                print(f"Warning: Invalid admin ID '{id_str.strip()}' in ADMIN_USER_ID")

    return admin_ids


ADMIN_USER_IDS = parse_admin_ids()

if ADMIN_USER_IDS:
    print(f"Loaded {len(ADMIN_USER_IDS)} admin(s): {ADMIN_USER_IDS}")
else:
    print("Warning: No admin users configured. Please set ADMIN_USER_ID in .env file")

GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", 0))
GROUP_CHAT_ID_FOR_ADMIN = int(os.getenv("GROUP_CHAT_ID_FOR_ADMIN", 0))

GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Members")
BOT_STATE_FILE = os.getenv("BOT_STATE_FILE", "data/bot_state.json")

SHEET_RANGE = f"{WORKSHEET_NAME}!A:F"

REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TIMEZONE = os.getenv("TIMEZONE", "Asia/Bangkok")
CHECK_INTERVAL_VALUE = int(os.getenv("CHECK_INTERVAL_VALUE", 1))
CHECK_INTERVAL_UNIT = os.getenv("CHECK_INTERVAL_UNIT", "hours")
DEFAULT_EXPIRE_DAYS = int(os.getenv("DEFAULT_EXPIRE_DAYS", 31))
INVITE_LINK_EXPIRE_MINUTES = int(os.getenv("INVITE_LINK_EXPIRE_MINUTES", 30))
INVITE_LINK_1MONTH_DAYS = int(os.getenv("INVITE_LINK_1MONTH_DAYS", 31))
INVITE_LINK_1YEAR_DAYS = int(os.getenv("INVITE_LINK_1YEAR_DAYS", 365))
INVITE_LINK_NOEXPIRE = os.getenv("INVITE_LINK_NOEXPIRE", "no_expire")
GOOGLE_SHEETS_WRITE_RETRY_COUNT = int(os.getenv("GOOGLE_SHEETS_WRITE_RETRY_COUNT", 3))
GOOGLE_SHEETS_WRITE_RETRY_DELAY_SECONDS = float(
    os.getenv("GOOGLE_SHEETS_WRITE_RETRY_DELAY_SECONDS", 1)
)
GOOGLE_SHEETS_BATCH_CHUNK_SIZE = int(os.getenv("GOOGLE_SHEETS_BATCH_CHUNK_SIZE", 200))
TELEGRAM_MEMBER_LOOKUP_CONCURRENCY = int(
    os.getenv("TELEGRAM_MEMBER_LOOKUP_CONCURRENCY", 10)
)
STATUS_USE_CACHED_SNAPSHOT = parse_bool_env("STATUS_USE_CACHED_SNAPSHOT", True)
SYNC_AUTO_ADD_MISSING_ADMINS_TO_SHEET = parse_bool_env(
    "SYNC_AUTO_ADD_MISSING_ADMINS_TO_SHEET",
    True,
)
TELETHON_API_ID = parse_optional_int("TELETHON_API_ID")
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "").strip()
TELETHON_SESSION_NAME = os.getenv("TELETHON_SESSION_NAME", "data/telethon_reconcile")
TELETHON_SESSION_STRING = os.getenv("TELETHON_SESSION_STRING", "").strip()
SYNC_BACKFILL_EXPIREDATE = os.getenv(
    "SYNC_BACKFILL_EXPIREDATE",
    os.getenv("TELETHON_FULL_SYNC_BACKFILL_EXPIREDATE", INVITE_LINK_NOEXPIRE),
)


def get_check_interval_seconds():
    """Convert the configured interval to seconds."""
    unit_multipliers = {
        "seconds": 1,
        "minutes": 60,
        "hours": 3600,
        "days": 86400,
    }

    if CHECK_INTERVAL_UNIT not in unit_multipliers:
        raise ValueError(
            f"Invalid interval unit: {CHECK_INTERVAL_UNIT}. "
            "Use: seconds, minutes, hours, days"
        )

    return CHECK_INTERVAL_VALUE * unit_multipliers[CHECK_INTERVAL_UNIT]


def is_admin(user_id):
    """Return True when the user ID is configured as an admin."""
    return int(user_id) in ADMIN_USER_IDS


def get_admin_list():
    """Return a copy of the configured admin user IDs."""
    return ADMIN_USER_IDS.copy()
