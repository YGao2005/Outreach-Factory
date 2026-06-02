"""Assemble a ScholarFeed cold-touch note from the fixed template, VERBATIM.

The operator's rule: only the first sentence varies per recipient; the body is
byte-for-byte identical on every email. An LLM "drafting" the body paraphrases
it (wording drift), so this assembler does a LITERAL substitution instead. It
reads the canonical template's fenced email block and swaps exactly three
placeholders:

    {{name}}            -> recipient first name (in the greeting)
    {{first_sentence}}  -> the per-recipient hook (the only prose that varies)
    {{api_key}}         -> the trial key minted for this recipient

Nothing else in the body is ever altered. The script refuses-loud if any
placeholder is left unfilled or if an em dash slips into the output (operator
ban). It writes a touch note in the ScholarFeed vault's conversations dir whose
``## Email`` section mirrors the format vault.py / send_queued.py expect, and
optionally creates a minimal Person note (so the gated send path has both the
``type: person`` record + the ``type: touch`` record it needs).

Usage:
    OUTREACH_FACTORY_CONFIG=~/.outreach-factory/config.scholarfeed.yml \\
      skills/send-outreach/.venv/bin/python \\
      skills/send-outreach/scripts/assemble_scholarfeed_touch.py \\
        --name "Dr. Jane Researcher" \\
        --first-sentence "saw your recent paper on self-evaluating agents, nice work." \\
        --key sf_xxxxxxxx \\
        --email jane@university.example \\
        [--arxiv-id 2501.00000] [--tier B] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

# This example tenant reuses the generic send-outreach config loader. Since this
# script lives under examples/ (not beside config.py), put the factory's
# send-outreach scripts dir on sys.path so `from config import ...` resolves.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "skills" / "send-outreach" / "scripts"),
)

from config import CONVERSATIONS_DIR, PEOPLE_DIR, VAULT_ROOT  # noqa: E402


DEFAULT_TEMPLATE = VAULT_ROOT / "90 Reference" / "ScholarFeed Cold-Pitch Template.md"
QUEUE_DIR = PEOPLE_DIR / "🟦 Queue"

# Anchor to line start so a `**Subject:**` mentioned inside the template's
# explanatory prose (backtick-quoted, mid-line) is NOT mistaken for the real
# subject line (which always begins at column 0). Without the anchor the regex
# greedily matched the prose mention and produced a garbage subject.
SUBJECT_RE = re.compile(r"^\*\*Subject:\*\*\s*`([^`]+)`", re.MULTILINE)
FENCE_RE = re.compile(r"^```(?:\w*\n)?(.*?)^```", re.MULTILINE | re.DOTALL)
PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}")
EM_DASH = "—"
EN_DASH = "–"


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "person"


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _email_collisions(exclude_name: str) -> dict[str, str]:
    """Map lowercased email -> Person-note path, across every Person note whose
    name differs from ``exclude_name``.

    The send-path ledger dedup (``last_send_for``) keys on the person-id slug, so
    it blocks re-queuing the SAME person but NOT the same email under a different
    name (a name typo, or two papers spelling the author differently). This guard
    closes that gap at assembly time: refuse to build a second cold touch to an
    address already in the CRM under a different identity. A re-assembly for the
    same person is allowed (their own note is excluded), since the ledger dedups
    the actual send.
    """
    out: dict[str, str] = {}
    if not PEOPLE_DIR.exists():
        return out
    for note in PEOPLE_DIR.rglob("*.md"):
        if note.stem == exclude_name:
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        for addr in _EMAIL_RE.findall(text):
            out.setdefault(addr.lower(), str(note))
    return out


def _extract_template(template_path: Path) -> tuple[str, str]:
    """Return (subject, fenced_body) from the template's ## Email section."""
    text = template_path.read_text(encoding="utf-8")
    sm = SUBJECT_RE.search(text)
    if not sm:
        raise SystemExit(f"Template {template_path} has no **Subject:** `...` line.")
    fm = FENCE_RE.search(text)
    if not fm:
        raise SystemExit(f"Template {template_path} has no fenced email body block.")
    return sm.group(1).strip(), fm.group(1).rstrip("\n")


def _fill(text: str, *, first_name: str, first_sentence: str, api_key: str) -> str:
    out = (
        text.replace("{{name}}", first_name)
        .replace("{{first_sentence}}", first_sentence)
        .replace("{{api_key}}", api_key)
    )
    leftover = PLACEHOLDER_RE.findall(out)
    if leftover:
        raise SystemExit(
            f"Unfilled placeholder(s) remain after substitution: {leftover}. "
            "The template has a placeholder this assembler does not know how to "
            "fill, refusing rather than send a broken body."
        )
    if EM_DASH in out or EN_DASH in out:
        raise SystemExit(
            "Assembled body contains an em/en dash (banned). Fix the template or "
            "the first sentence, refusing rather than ship a dash."
        )
    return out


def _touch_note(*, full_name: str, subject: str, body: str, today: str) -> str:
    return (
        "---\n"
        "type: touch\n"
        f"date: {today}\n"
        "channel: email\n"
        "direction: outbound\n"
        f'person: "[[{full_name}]]"\n'
        "substantive: false\n"
        "sent: false\n"
        "tags:\n"
        "  - cold-touch\n"
        "  - email-only\n"
        "  - scholarfeed\n"
        "---\n\n"
        f"# {today} {full_name} cold touch (Email)\n\n"
        "## Email\n\n"
        f"**Subject:** `{subject}`\n\n"
        "```\n"
        f"{body}\n"
        "```\n\n"
        "## Outcome\n\n"
        "- [ ] Email sent\n"
        "- [ ] Read receipt / opened\n"
        "- [ ] Replied\n"
        "- [ ] Substantive engagement\n"
        "- [ ] Advanced to call\n"
    )


def _person_note(*, full_name: str, email: str, tier: str, arxiv_id: str | None, today: str) -> str:
    pid = _slugify(full_name)
    lines = [
        "---",
        "type: person",
        f"id: {pid}",
        "identity_keys:",
        "  emails:",
        f"  - {email}",
        "  country: United States",
        f"name: {full_name}",
        f"email: {email}",
        "status: queued",
        "relationship: researcher",
        f"research_tier: {tier}",
        f"created: {today}",
    ]
    if arxiv_id:
        lines.append(f"arxiv_id: {arxiv_id}")
    lines += [
        "tags:",
        "  - scholarfeed",
        "  - arxiv-discovery",
        "---",
        "",
        f"# {full_name}",
        "",
        "## Why this person",
        "> Recently-published researcher; a paper-retrieval MCP + embeddings API fits their work.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble a ScholarFeed cold-touch note (verbatim body).")
    ap.add_argument("--name", required=True, help="Recipient full name (e.g. 'Dr. Jane Researcher').")
    ap.add_argument("--first-sentence", required=True, help="The per-recipient hook (one sentence).")
    ap.add_argument("--key", required=True, help="The trial API key (sf_...) minted for this recipient.")
    ap.add_argument("--email", help="Recipient email; if set and no Person note exists, one is created.")
    ap.add_argument("--arxiv-id", help="arXiv id of their paper (stamped on the Person note).")
    ap.add_argument("--tier", default="B", help="research_tier for the Person note (default B).")
    ap.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="Template path.")
    ap.add_argument("--dry-run", action="store_true", help="Print the assembled touch note, write nothing.")
    args = ap.parse_args()

    full_name = args.name.strip()
    first_name = full_name.split()[0] if full_name.split() else full_name
    today = date.today().isoformat()

    subject, body_template = _extract_template(args.template)
    body = _fill(
        body_template,
        first_name=first_name,
        first_sentence=args.first_sentence.strip(),
        api_key=args.key.strip(),
    )
    touch_md = _touch_note(full_name=full_name, subject=subject, body=body, today=today)

    if args.dry_run:
        print(touch_md)
        return 0

    # Person note (only if --email given and none exists; the gated send path
    # needs a type:person note with a non-temporary id).
    if args.email:
        email_lc = args.email.strip().lower()
        collisions = _email_collisions(exclude_name=full_name)
        if email_lc in collisions:
            raise SystemExit(
                f"EMAIL DUPE GUARD: {args.email} is already in the CRM under a "
                f"different person note ({collisions[email_lc]}). Refusing to "
                "assemble a second cold touch to the same address (the ledger "
                "send-dedup keys on person-id, not email, so this guard catches "
                "same-email / different-name duplicates). Nothing was written."
            )
        existing = list(PEOPLE_DIR.rglob(f"{full_name}.md"))
        if existing:
            print(f"Person note already exists: {existing[0]}")
        else:
            QUEUE_DIR.mkdir(parents=True, exist_ok=True)
            person_path = QUEUE_DIR / f"{full_name}.md"
            person_path.write_text(
                _person_note(
                    full_name=full_name, email=args.email.strip(),
                    tier=args.tier.strip(), arxiv_id=args.arxiv_id, today=today,
                ),
                encoding="utf-8",
            )
            print(f"Wrote Person note: {person_path}")

    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    touch_path = CONVERSATIONS_DIR / f"{today} {full_name} cold touch (Email).md"
    touch_path.write_text(touch_md, encoding="utf-8")
    print(f"Wrote touch note: {touch_path}")
    print("\nNext: review it, then send via")
    print('  OUTREACH_FACTORY_CONFIG=~/.outreach-factory/config.scholarfeed.yml \\')
    print("    skills/send-outreach/.venv/bin/python skills/send-outreach/scripts/send_queued.py \\")
    print(f'    --only "{full_name}" --dry-run')
    return 0


if __name__ == "__main__":
    sys.exit(main())
