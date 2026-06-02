#!/usr/bin/env python3
"""Augment your email voice corpus with sent cold-pitch Touch notes from the vault.

Walks `<conversations-dir>/**/*.md` in your Obsidian vault, filters for Touch
notes that were ACTUALLY SENT outbound cold-pitch emails, extracts the email
body from the first `## Email*` section's code block, and writes a combined
`curated_v2.jsonl` (existing curated + new cold-pitch records).

Why: a corpus built only from your inbox skews to warm-reply / follow-up, so
cold-pitch retrieval pulls register-mismatched exemplars. Folding in your sent
cold-touch notes raises the cold-pitch share of the corpus.

After running this, rebuild the index from curated_v2.jsonl:
    python3 build_index.py --in <corpus-dir>/curated_v2.jsonl

Usage:
    python3 augment_corpus_from_vault.py --vault-convos <path> [--corpus-dir <dir>] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Canonical corpus location (override via --corpus-dir / --vault-convos).
DEFAULT_CORPUS_DIR = Path("~/.outreach-factory/voice-corpus").expanduser()

URL_RE = re.compile(r"https?://\S+|www\.\S+")


def parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return None
    fm: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        if not line or line[0] in (" ", "-", "#"):
            continue
        m = re.match(r"^([a-z_][a-z_0-9]*):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm


def is_sent_outbound_email(fm: dict) -> bool:
    if fm.get("type") != "touch":
        return False
    if str(fm.get("sent", "false")).lower() not in ("true", "yes"):
        return False
    if fm.get("direction", "outbound") != "outbound":
        return False
    return "email" in fm.get("channel", "").lower()


def has_cold_pitch_tag(text: str) -> bool:
    if not text.startswith("---\n"):
        return False
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return False
    fm_block = text[4:end]
    return "cold-touch" in fm_block or "cold-pitch" in fm_block


def extract_email_body(text: str) -> tuple[str, str] | None:
    """Return (subject, body) from the first `## Email*` section, or None."""
    m = re.search(r"^##\s+Email[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return None
    section = m.group(1)

    subj_m = re.search(r"\*\*Subject:\*\*\s*`?([^`\n]+)`?", section)
    subject = subj_m.group(1).strip().strip("`") if subj_m else ""

    code_m = re.search(r"```(?:[a-zA-Z]*)?\n(.*?)```", section, re.DOTALL)
    if not code_m:
        return None
    body = code_m.group(1).strip()
    return subject, body


def strip_urls(text: str) -> str:
    return URL_RE.sub("", text)


def slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s[:maxlen]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Augment the curated corpus with sent cold-pitch touch notes from your vault.")
    p.add_argument("--vault-convos", required=True, type=Path,
                   help="Your vault's conversations dir (e.g. '<vault>/40 Conversations').")
    p.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR,
                   help=f"Corpus dir holding curated.jsonl (default: {DEFAULT_CORPUS_DIR}).")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    vault_convos = args.vault_convos.expanduser()
    corpus_dir = args.corpus_dir.expanduser()
    curated_in = corpus_dir / "curated.jsonl"
    curated_out = corpus_dir / "curated_v2.jsonl"

    if not curated_in.exists():
        print(f"ERROR: {curated_in} not found", file=sys.stderr)
        sys.exit(2)

    existing = [json.loads(line) for line in curated_in.open()]
    existing_ids = {r.get("message_id") for r in existing}
    print(f"loaded {len(existing)} existing curated records")

    added = 0
    skipped_no_fm = skipped_filter = skipped_no_body = skipped_dup = skipped_short = 0
    new_records: list[dict] = []

    for note in sorted(vault_convos.rglob("*.md")):
        text = note.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm:
            skipped_no_fm += 1
            continue
        if not is_sent_outbound_email(fm) or not has_cold_pitch_tag(text):
            skipped_filter += 1
            continue

        extracted = extract_email_body(text)
        if not extracted:
            skipped_no_body += 1
            continue
        subject, body = extracted
        if not body or len(body.split()) < 20:
            skipped_short += 1
            continue

        date_str = fm.get("sent_at") or fm.get("date") or "2026-01-01"
        year = int(date_str[:4]) if date_str[:4].isdigit() else 2026
        slug = slugify(note.stem)
        msg_id = f"touch-{slug}"

        if msg_id in existing_ids:
            skipped_dup += 1
            continue

        body_no_urls = strip_urls(body)
        rec = {
            "message_id": msg_id,
            "date": date_str + "T00:00:00-07:00",
            "year": year,
            "subject": subject or note.stem,
            "to": [],
            "cc": [],
            "word_count": len(body.split()),
            "body": body,
            "body_no_urls": body_no_urls,
            "clean_word_count": len(body_no_urls.split()),
            "ai_tell_score": 0.0,
            "source": "vault-touch-augment",
            "register": "cold-pitch",
        }
        new_records.append(rec)
        existing_ids.add(msg_id)
        added += 1

    print(
        f"added: {added} new | "
        f"skipped: {skipped_filter} (filter) + {skipped_no_body} (no email body) + "
        f"{skipped_short} (too short) + {skipped_dup} (dup) + {skipped_no_fm} (no fm)"
    )

    if args.dry_run:
        for r in new_records[:5]:
            print(f"  + {r['message_id']}: {r['subject'][:60]} ({r['clean_word_count']}w)")
        if len(new_records) > 5:
            print(f"  ... and {len(new_records) - 5} more")
        print("(dry-run; no file written)")
        return

    with curated_out.open("w") as f:
        for r in existing:
            f.write(json.dumps(r) + "\n")
        for r in new_records:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {curated_out} ({len(existing) + len(new_records)} total records)")


if __name__ == "__main__":
    main()
