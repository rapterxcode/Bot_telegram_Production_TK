#!/usr/bin/env python3
"""Application entrypoint for the Telegram member management bot."""

import asyncio
import sys

from app.bot.telegram_bot import TelegramMemberBot


async def main():
    """Start the bot and keep the process alive until shutdown."""
    print("Starting Telegram Member Management Bot")
    print("Loading configuration...")

    bot = TelegramMemberBot()

    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as exc:
        print(f"Startup failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
