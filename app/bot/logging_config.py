"""Logging helpers for the bot package."""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_global_logging(logger_name: str) -> logging.Logger:
    """Configure console and file logging for the bot."""
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if root_logger.handlers:
        root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(
        os.path.join(log_dir, "application.log"),
        mode="a",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    rotating_handler = RotatingFileHandler(
        os.path.join(log_dir, "application_rotating.log"),
        maxBytes=100 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    rotating_handler.setLevel(logging.INFO)
    rotating_handler.setFormatter(formatter)
    root_logger.addHandler(rotating_handler)

    bot_handler = logging.FileHandler(
        os.path.join(log_dir, "telegram_bot.log"),
        mode="a",
        encoding="utf-8",
    )
    bot_handler.setLevel(logging.INFO)
    bot_handler.setFormatter(formatter)
    bot_handler.addFilter(
        lambda record: record.name.startswith("app.bot") or record.name == "__main__"
    )
    root_logger.addHandler(bot_handler)

    google_sheets_audit_handler = RotatingFileHandler(
        os.path.join(log_dir, "google_sheets_audit.log"),
        maxBytes=20 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    google_sheets_audit_handler.setLevel(logging.INFO)
    google_sheets_audit_handler.setFormatter(formatter)
    google_sheets_audit_handler.addFilter(
        lambda record: record.name == "app.audit.google_sheets"
    )
    root_logger.addHandler(google_sheets_audit_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)

    return logging.getLogger(logger_name)
