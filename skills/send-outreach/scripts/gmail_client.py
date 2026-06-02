"""Gmail API client — OAuth bootstrap, send, Sent-folder scan."""

from __future__ import annotations

import base64
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Iterator, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import CREDENTIALS_DIR, GMAIL_CREDENTIALS, GMAIL_SCOPES, GMAIL_TOKEN


def _load_or_refresh_creds() -> Credentials:
    if not GMAIL_CREDENTIALS.exists():
        print(
            f"Missing OAuth credentials at {GMAIL_CREDENTIALS}\n\n"
            "One-time setup:\n"
            "  1. Go to https://console.cloud.google.com/apis/credentials\n"
            "  2. Create a project (e.g., 'outreach-factory')\n"
            "  3. Enable Gmail API: APIs & Services > Enable APIs > search 'Gmail API' > Enable\n"
            "  4. Configure OAuth consent screen (External, your email as test user)\n"
            "  5. Create Credentials > OAuth client ID > Desktop app\n"
            "  6. Download JSON, save as:\n"
            f"     {GMAIL_CREDENTIALS}\n"
            "  7. Re-run this command",
            file=sys.stderr,
        )
        sys.exit(2)

    creds: Optional[Credentials] = None
    if GMAIL_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN), GMAIL_SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        GMAIL_TOKEN.write_text(creds.to_json())
        return creds

    # No valid creds — run installed-app flow
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(GMAIL_CREDENTIALS), GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)
    GMAIL_TOKEN.write_text(creds.to_json())
    return creds


@dataclass
class GmailClient:
    service: object  # googleapiclient.discovery.Resource
    sender_email: str

    @classmethod
    def authenticate(cls) -> "GmailClient":
        creds = _load_or_refresh_creds()
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        return cls(service=service, sender_email=profile["emailAddress"])

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        from_name: Optional[str] = None,
        extra_headers: Optional[dict] = None,
        body_footer: Optional[str] = None,
    ) -> tuple[str, str]:
        """Send plain-text email. Returns (message_id, thread_id).

        extra_headers (e.g. X-Outreach-Intent-Id) is stamped onto the
        message so reconcile Pass A can recover from a mid-send crash by
        searching Gmail for the intent.

        body_footer is appended to the body verbatim. The two-phase send
        path stamps a zero-width-spaced sentinel like
        '\\u200boutreach-intent:snd_XXX\\u200b' there so Gmail's body-text
        search returns hits even when custom-header search misbehaves.
        """
        full_body = body if not body_footer else f"{body}{body_footer}"
        msg = EmailMessage()
        msg.set_content(full_body)
        msg["To"] = to
        msg["From"] = f"{from_name} <{self.sender_email}>" if from_name else self.sender_email
        msg["Subject"] = subject
        if extra_headers:
            for hname, hval in extra_headers.items():
                # email.message replaces values when the header already exists;
                # add via setitem semantics (allows multi-value via add_header,
                # but a single value is the common case here).
                msg[hname] = hval

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        try:
            result = self.service.users().messages().send(userId="me", body={"raw": raw}).execute()
        except HttpError as e:
            raise RuntimeError(f"Gmail API send failed: {e}") from e
        return result["id"], result.get("threadId", "")

    def search_messages(self, query: str, max_results: int = 100) -> list[dict]:
        """List messages matching a Gmail search query. Returns [{id, threadId}]."""
        resp = (
            self.service.users().messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return resp.get("messages", []) or []

    def get_message(self, msg_id: str) -> Optional[dict]:
        """Full message dict (metadata format). Returns None on lookup failure."""
        try:
            return (
                self.service.users().messages()
                .get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date",
                                     "X-Outreach-Intent-Id", "Message-Id",
                                     "In-Reply-To"],
                )
                .execute()
            )
        except HttpError:
            return None

    def get_thread(self, thread_id: str) -> Optional[dict]:
        """Full thread dict including its messages list. None on failure."""
        try:
            return (
                self.service.users().threads()
                .get(
                    userId="me", id=thread_id, format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date",
                                     "X-Outreach-Intent-Id", "Message-Id",
                                     "In-Reply-To"],
                )
                .execute()
            )
        except HttpError:
            return None

    def iter_sent_messages(self, after_date: Optional[datetime] = None) -> Iterator[dict]:
        """Yield Sent messages with headers (Subject, To, Date) populated. Newest first."""
        query = "in:sent"
        if after_date:
            # Gmail q syntax: after:YYYY/MM/DD (date-only, no tz)
            query += f" after:{after_date.strftime('%Y/%m/%d')}"

        page_token = None
        while True:
            resp = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=100, pageToken=page_token)
                .execute()
            )
            ids = resp.get("messages", [])
            for msg_ref in ids:
                msg = (
                    self.service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_ref["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "To", "Date"],
                    )
                    .execute()
                )
                yield msg
            page_token = resp.get("nextPageToken")
            if not page_token:
                break


def _bootstrap_cli() -> int:
    """Direct invocation: trigger OAuth flow + print authenticated email."""
    client = GmailClient.authenticate()
    print(f"Authenticated as: {client.sender_email}")
    print(f"Token stored at: {GMAIL_TOKEN}")
    return 0


if __name__ == "__main__":
    sys.exit(_bootstrap_cli())
