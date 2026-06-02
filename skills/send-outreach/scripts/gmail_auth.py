"""One-time Gmail OAuth bootstrap. Triggers browser consent, stores refresh token."""

import sys

from gmail_client import GmailClient
from config import GMAIL_TOKEN


def main() -> int:
    client = GmailClient.authenticate()
    print(f"Authenticated as: {client.sender_email}")
    print(f"Token stored at: {GMAIL_TOKEN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
