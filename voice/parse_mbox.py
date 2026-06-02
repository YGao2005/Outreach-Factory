"""Parse Gmail Takeout mbox → filtered JSONL of outbound substantive emails.

Streams the 2.3GB mbox without loading it all into memory. Filters to:
  - X-Gmail-Labels contains "Sent" (outbound)
  - Not in Spam/Trash/Chats
  - Date >= 2022-01-01
  - Body word count after cleanup >= 30
  - Strips quoted reply text and common signatures

Outputs:
  filtered.jsonl   — one email per line
  summary.json     — corpus stats (date dist, word-count dist, top recipients)
"""
from __future__ import annotations

import argparse
import json
import mailbox
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

# Canonical corpus location (override with --out-dir). The Gmail Takeout .mbox
# and your own sender address(es) are supplied on the command line so nothing
# here is hardcoded to one operator.
DEFAULT_CORPUS_DIR = Path("~/.outreach-factory/voice-corpus").expanduser()
DEFAULT_MIN_YEAR = 2022
DEFAULT_MIN_WORDS = 30


QUOTED_REPLY_RE = re.compile(
    r"^(On .{1,200}wrote:|From:.{1,500}Sent:|-+\s*Original Message\s*-+|_{5,}|Begin forwarded message:)",
    re.MULTILINE | re.IGNORECASE,
)
SIG_RE = re.compile(r"^(--\s*$|Sent from my (i[Pp]hone|iPad|Android)|Cheers,|Best,|Thanks,|Regards,|Best regards,|Sincerely,)", re.MULTILINE)


def get_body(msg: Message) -> str:
    """Extract plain-text body. Prefer text/plain over text/html."""
    if msg.is_multipart():
        text_part = None
        html_part = None
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and text_part is None:
                text_part = part
            elif ctype == "text/html" and html_part is None:
                html_part = part
        target = text_part or html_part
        if target is None:
            return ""
        payload = target.get_payload(decode=True) or b""
        try:
            text = payload.decode(target.get_content_charset() or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = payload.decode("utf-8", errors="replace")
        if target.get_content_type() == "text/html":
            text = strip_html(text)
        return text
    payload = msg.get_payload(decode=True) or b""
    try:
        text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = payload.decode("utf-8", errors="replace")
    if msg.get_content_type() == "text/html":
        text = strip_html(text)
    return text


def strip_html(html: str) -> str:
    """Crude HTML → text. Good enough for email bodies."""
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p>", "\n\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"&lt;", "<", html)
    html = re.sub(r"&gt;", ">", html)
    html = re.sub(r"&quot;", '"', html)
    html = re.sub(r"&#39;", "'", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def clean_body(text: str) -> str:
    """Strip quoted-reply text, signatures, excessive whitespace."""
    if not text:
        return ""
    m = QUOTED_REPLY_RE.search(text)
    if m:
        text = text[: m.start()]
    text = re.sub(r"^>.*$", "", text, flags=re.MULTILINE)
    m = SIG_RE.search(text)
    if m:
        text = text[: m.start()]
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def word_count(s: str) -> int:
    return len(s.split())


def parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def extract_addresses(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [addr.lower() for _, addr in getaddresses([raw]) if addr]


def is_sent(labels: str) -> bool:
    L = labels.lower()
    if "spam" in L or "trash" in L or "chats" in L or "draft" in L:
        return False
    return "sent" in L


def is_user_sender(msg: Message, addresses: set[str]) -> bool:
    senders = extract_addresses(msg.get("From"))
    return any(s in addresses for s in senders)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Parse a Gmail Takeout .mbox into filtered.jsonl of YOUR "
                    "outbound substantive emails.")
    ap.add_argument("--mbox", required=True, type=Path,
                    help="Path to your Gmail Takeout .mbox export.")
    ap.add_argument("--sender", action="append", default=[], metavar="EMAIL",
                    help="Your own sender address (repeatable). Only mail FROM "
                         "these addresses is kept.")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_CORPUS_DIR,
                    help=f"Output dir for filtered.jsonl + summary.json "
                         f"(default: {DEFAULT_CORPUS_DIR}).")
    ap.add_argument("--min-year", type=int, default=DEFAULT_MIN_YEAR,
                    help=f"Drop mail sent before Jan 1 of this year "
                         f"(default: {DEFAULT_MIN_YEAR}).")
    ap.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS,
                    help=f"Drop bodies shorter than this after cleanup "
                         f"(default: {DEFAULT_MIN_WORDS}).")
    args = ap.parse_args()

    mbox_path = args.mbox.expanduser()
    addresses = {a.strip().lower() for a in args.sender if a.strip()}
    if not addresses:
        print("ERROR: pass at least one --sender <your-email> so only YOUR "
              "outbound mail is kept.", file=sys.stderr)
        return 2
    if not mbox_path.exists():
        print(f"missing: {mbox_path}", file=sys.stderr)
        return 1

    out_dir = args.out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = out_dir / "filtered.jsonl"
    summary_json = out_dir / "summary.json"
    min_date = datetime(args.min_year, 1, 1, tzinfo=timezone.utc)
    min_words = args.min_words

    print(f"reading {mbox_path} ({mbox_path.stat().st_size / 1e9:.1f} GB)")
    mbox = mailbox.mbox(str(mbox_path))

    total = 0
    kept = 0
    drop_label = drop_sender = drop_date = drop_words = drop_no_body = 0
    by_year: Counter[int] = Counter()
    recipients: Counter[str] = Counter()
    word_buckets: Counter[str] = Counter()

    with out_jsonl.open("w") as out_f:
        for msg in mbox:
            total += 1
            if total % 5000 == 0:
                print(f"  ... {total} scanned, {kept} kept")

            labels = msg.get("X-Gmail-Labels", "") or ""
            if not is_sent(labels):
                drop_label += 1
                continue

            if not is_user_sender(msg, addresses):
                drop_sender += 1
                continue

            dt = parse_date(msg.get("Date"))
            if dt is None or dt < min_date:
                drop_date += 1
                continue

            raw_body = get_body(msg)
            body = clean_body(raw_body)
            if not body:
                drop_no_body += 1
                continue

            wc = word_count(body)
            if wc < min_words:
                drop_words += 1
                continue

            to_addrs = extract_addresses(msg.get("To"))
            cc_addrs = extract_addresses(msg.get("Cc"))
            for addr in to_addrs + cc_addrs:
                recipients[addr] += 1

            rec = {
                "message_id": msg.get("Message-ID", "").strip("<>"),
                "date": dt.isoformat(),
                "year": dt.year,
                "subject": (msg.get("Subject") or "").strip(),
                "to": to_addrs,
                "cc": cc_addrs,
                "word_count": wc,
                "body": body,
            }
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            kept += 1
            by_year[dt.year] += 1
            if wc < 50:
                word_buckets["30-49"] += 1
            elif wc < 100:
                word_buckets["50-99"] += 1
            elif wc < 200:
                word_buckets["100-199"] += 1
            elif wc < 400:
                word_buckets["200-399"] += 1
            else:
                word_buckets["400+"] += 1

    summary = {
        "total_scanned": total,
        "kept": kept,
        "dropped": {
            "wrong_label_or_spam_trash": drop_label,
            "not_user_sender": drop_sender,
            "before_2022_or_no_date": drop_date,
            "too_short": drop_words,
            "no_body": drop_no_body,
        },
        "by_year": dict(sorted(by_year.items())),
        "word_count_buckets": dict(word_buckets),
        "top_recipients": recipients.most_common(30),
    }
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print("\n=== summary ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
