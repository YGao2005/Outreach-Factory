"""Refine filtered.jsonl → cleaned.jsonl with stricter quality rules.

Drops: forwards, near-empty meeting-link emails, transactional auto-content,
emails dominated by URLs/quoted blocks, and noise-only sends.

Goal: a clean count of emails that actually contain the operator's prose.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

# Canonical corpus location (override in/out/summary via flags).
DEFAULT_CORPUS_DIR = Path("~/.outreach-factory/voice-corpus").expanduser()

URL_RE = re.compile(r"https?://\S+")
FORWARD_RE = re.compile(r"-{5,}\s*Forwarded message", re.IGNORECASE)
ZOOM_RE = re.compile(r"\b(zoom\.us|meet\.google\.com|teams\.microsoft\.com)\b", re.IGNORECASE)


def alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = sum(1 for c in text if c.isalpha())
    return alpha / len(text)


def url_density(text: str) -> float:
    if not text:
        return 0.0
    urls = URL_RE.findall(text)
    url_chars = sum(len(u) for u in urls)
    return url_chars / max(1, len(text))


def strip_urls(text: str) -> str:
    return URL_RE.sub("", text)


def is_forward(rec: dict) -> bool:
    subj = rec.get("subject", "").lower()
    if subj.startswith(("fwd:", "fw:")):
        return True
    if FORWARD_RE.search(rec.get("body", "")):
        return True
    return False


def is_meeting_link_only(rec: dict) -> bool:
    body = rec.get("body", "")
    if not ZOOM_RE.search(body):
        return False
    stripped = strip_urls(body)
    return len(stripped.split()) < 25


def is_low_signal(rec: dict) -> bool:
    body = rec.get("body", "")
    if alpha_ratio(body) < 0.5:
        return True
    if url_density(body) > 0.35:
        return True
    stripped = strip_urls(body)
    return len(stripped.split()) < 25


def decode_subject(s: str) -> str:
    if not s.startswith("=?"):
        return s
    try:
        from email.header import decode_header

        parts = decode_header(s)
        return "".join(
            p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
            for p, enc in parts
        )
    except Exception:  # noqa: BLE001
        return s


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Refine filtered.jsonl into cleaned.jsonl with stricter quality rules.")
    ap.add_argument("--in", dest="in_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "filtered.jsonl",
                    help="Input filtered.jsonl (from parse_mbox.py).")
    ap.add_argument("--out", dest="out_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "cleaned.jsonl", help="Output cleaned.jsonl.")
    ap.add_argument("--summary", dest="summary_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "cleaned_summary.json", help="Output summary json.")
    args = ap.parse_args()
    in_path = args.in_path.expanduser()
    out_path = args.out_path.expanduser()
    summary_path = args.summary_path.expanduser()

    kept = []
    drop_forward = drop_meeting = drop_lowsig = 0

    for line in in_path.open():
        rec = json.loads(line)
        rec["subject"] = decode_subject(rec.get("subject", ""))

        if is_forward(rec):
            drop_forward += 1
            continue
        if is_meeting_link_only(rec):
            drop_meeting += 1
            continue
        if is_low_signal(rec):
            drop_lowsig += 1
            continue

        rec["body_no_urls"] = strip_urls(rec["body"]).strip()
        rec["clean_word_count"] = len(rec["body_no_urls"].split())
        kept.append(rec)

    with out_path.open("w") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_year = Counter(r["year"] for r in kept)
    word_buckets = Counter()
    for r in kept:
        wc = r["clean_word_count"]
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
        "input_count": sum(1 for _ in in_path.open()),
        "kept": len(kept),
        "dropped": {
            "forward": drop_forward,
            "meeting_link_only": drop_meeting,
            "low_signal_urls_or_nonalpha": drop_lowsig,
        },
        "by_year": dict(sorted(by_year.items())),
        "clean_word_count_buckets": dict(word_buckets),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
