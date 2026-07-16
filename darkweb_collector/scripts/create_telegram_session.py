from __future__ import annotations

import os
import sys

from telethon.sessions import StringSession
from telethon.sync import TelegramClient


def main() -> int:
    api_id = os.environ.get("SOCIAL_TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("SOCIAL_TELEGRAM_API_HASH", "").strip()
    if not api_id or not api_hash:
        print(
            "Set SOCIAL_TELEGRAM_API_ID and SOCIAL_TELEGRAM_API_HASH before running this helper.",
            file=sys.stderr,
        )
        return 2
    try:
        numeric_api_id = int(api_id)
    except ValueError:
        print("SOCIAL_TELEGRAM_API_ID must be an integer.", file=sys.stderr)
        return 2

    client = TelegramClient(StringSession(), numeric_api_id, api_hash)
    try:
        client.start()
        print("\nStore the following value as the SOCIAL_TELEGRAM_SESSION secret:")
        print(client.session.save())
        print("\nTreat this value like a password. Do not commit it or paste it into logs.")
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
