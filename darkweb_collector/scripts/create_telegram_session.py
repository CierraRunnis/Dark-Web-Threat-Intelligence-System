from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from telethon.sessions import StringSession
from telethon.sync import TelegramClient

from darkweb_collector.social_secrets import get_social_secret


def main() -> int:
    api_id = get_social_secret("SOCIAL_TELEGRAM_API_ID")
    api_hash = get_social_secret("SOCIAL_TELEGRAM_API_HASH")
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
