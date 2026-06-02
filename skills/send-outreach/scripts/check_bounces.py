"""Bounce check: scan Gmail inbox for mailer-daemon DSN messages, match failed recipients
against sent cold-touch notes, annotate person + touch notes."""

from __future__ import annotations

import argparse
import base64
import re
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterator, Optional

from config import CONVERSATIONS_DIR, PEOPLE_DIR, TOUCH_NOTE_GLOB
from gmail_client import GmailClient
from vault import (
    _read_raw_frontmatter_value,
    split_frontmatter,
    update_frontmatter,
)


FAILED_TO_RE = re.compile(r"(?:wasn't delivered to|delivery to the following recipient failed permanently)\s*[:\s]*([\w.+-]+@[\w.-]+\.\w+)", re.IGNORECASE)
FINAL_RECIPIENT_RE = re.compile(r"Final-Recipient:\s*rfc822;\s*([\w.+-]+@[\w.-]+\.\w+)", re.IGNORECASE)
GENERIC_EMAIL_RE = re.compile(r"\b([\w.+-]+@[\w.-]+\.\w+)\b")


def _decode_part(part: dict) -> Optional[str]:
    if part.get("mimeType") == "text/plain":
        data = part.get("body", {}).get("data")
        if data:
            try:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            except Exception:
                return None
    for sub in part.get("parts") or []:
        r = _decode_part(sub)
        if r:
            return r
    return None


def _extract_failed_recipient(body: str) -> Optional[str]:
    """Try multiple patterns to find the failed recipient address in a bounce body."""
    m = FAILED_TO_RE.search(body)
    if m:
        return m.group(1).lower()
    m = FINAL_RECIPIENT_RE.search(body)
    if m:
        return m.group(1).lower()
    # Fallback: take the first email-shaped string that isn't mailer-daemon
    for m in GENERIC_EMAIL_RE.finditer(body):
        addr = m.group(1).lower()
        if "mailer-daemon" not in addr and "noreply" not in addr:
            return addr
    return None


def iter_bounces(client: GmailClient, days: int = 30) -> Iterator[tuple[str, datetime]]:
    """Yield (failed_recipient, bounce_date) for each mailer-daemon DSN in the last N days."""
    after = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"from:mailer-daemon after:{after}"
    page_token = None
    while True:
        resp = client.service.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token
        ).execute()
        for ref in resp.get("messages", []):
            msg = client.service.users().messages().get(
                userId="me", id=ref["id"], format="full"
            ).execute()
            body = _decode_part(msg.get("payload", {})) or ""
            failed = _extract_failed_recipient(body)
            if not failed:
                continue
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            try:
                bounce_dt = parsedate_to_datetime(headers.get("date", ""))
            except Exception:
                bounce_dt = datetime.now()
            yield failed, bounce_dt
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def _find_person_by_email(target: str) -> Optional[Path]:
    """Search all person notes for one whose `email:` frontmatter (primary or alt) matches target."""
    target = target.lower()
    for note in PEOPLE_DIR.rglob("*.md"):
        raw = _read_raw_frontmatter_value(note, "email")
        if not raw:
            continue
        for m in GENERIC_EMAIL_RE.finditer(raw):
            if m.group(1).lower() == target:
                return note
    return None


def _find_touch_for_recipient(target: str) -> Optional[Path]:
    """Find the most-recent sent cold-touch note whose person's primary email matches target."""
    target = target.lower()
    candidates = []
    for note in CONVERSATIONS_DIR.glob(TOUCH_NOTE_GLOB):
        text = note.read_text()
        fm, body = split_frontmatter(text)
        if fm.get("type") != "touch" or fm.get("sent") is not True:
            continue
        # Walk to person; check their email
        person_field = fm.get("person") or ""
        m = re.search(r"\[\[([^\]]+)\]\]", str(person_field))
        if not m:
            continue
        name = m.group(1)
        person_path = next(PEOPLE_DIR.rglob(f"{name}.md"), None)
        if not person_path:
            continue
        raw = _read_raw_frontmatter_value(person_path, "email")
        if raw and target in raw.lower():
            sent_at = fm.get("sent_at") or fm.get("date") or ""
            candidates.append((str(sent_at), note))
    if not candidates:
        return None
    # Pick the most recent
    candidates.sort(reverse=True)
    return candidates[0][1]


def _annotate_bounce(person_path: Path, touch_path: Optional[Path], failed_addr: str, bounce_dt: datetime) -> bool:
    """Idempotent: returns True if any writeback actually happened."""
    bounce_date = bounce_dt.date().isoformat()
    changed = False

    # Person note: only update if email_status not already a bounce for this addr
    person_text = person_path.read_text()
    person_fm, _ = split_frontmatter(person_text)
    current_status = str(person_fm.get("email_status") or "")
    if failed_addr not in current_status or "bounced" not in current_status.lower():
        update_frontmatter(person_path, {"email_status": f"bounced {bounce_date} ({failed_addr})"})
        changed = True

    # Touch note: only insert reflection if not already mentioned
    if touch_path:
        text = touch_path.read_text()
        if failed_addr in text and "bounced" in text.lower():
            # Already annotated (auto or manual). Skip.
            pass
        else:
            reflection_line = f"- **{bounce_date}:** Email to `{failed_addr}` bounced (auto-detected via Gmail DSN). Consider LinkedIn channel or alt email patterns."
            m = re.search(r"^(##\s+Reflections[^\n]*\n\n)", text, re.MULTILINE)
            if m:
                insertion = m.group(1) + reflection_line + "\n"
                text = text[:m.start()] + insertion + text[m.end():]
                touch_path.write_text(text)
                changed = True
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect bounced cold-touch emails via Gmail DSN scan")
    ap.add_argument("--days", type=int, default=30, help="How far back to scan inbox (default 30)")
    ap.add_argument("--dry-run", action="store_true", help="Show bounces without writeback")
    args = ap.parse_args()

    client = GmailClient.authenticate()
    print(f"Authenticated as: {client.sender_email}")
    print(f"Scanning Gmail inbox for bounces in last {args.days} days...\n")

    bounces = list(iter_bounces(client, days=args.days))
    if not bounces:
        print("No bounces detected.")
        return 0

    print(f"Found {len(bounces)} bounce(s):\n")
    for failed, dt in bounces:
        person = _find_person_by_email(failed)
        touch = _find_touch_for_recipient(failed)
        person_label = person.stem if person else "no match"
        touch_label = touch.name if touch else "no touch"
        print(f"  {dt.date()}  {failed:<35}  person: {person_label}   touch: {touch_label}")

    if args.dry_run:
        print("\n(dry-run) — not writing back")
        return 0

    annotated = 0
    already = 0
    for failed, dt in bounces:
        person = _find_person_by_email(failed)
        touch = _find_touch_for_recipient(failed)
        if not person:
            continue
        if _annotate_bounce(person, touch, failed, dt):
            annotated += 1
            print(f"  ✓ annotated {person.stem}  ({failed})")
        else:
            already += 1
            print(f"  · already annotated {person.stem}  ({failed})")

    print(f"\n{annotated} newly annotated, {already} already on file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
