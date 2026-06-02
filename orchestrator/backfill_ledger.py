"""One-time migration: emit retroactive ledger events for existing state.

Phase 5.5 Week 2. Once the ledger primitive is live, the send-gate
consults it on every send. New events accumulate forward, but the
ledger needs to know about prior enrollments + sends or the funnel
diagnostic shows zero history. This script reconstructs the ledger
from the vault's current state — Person notes + touch notes — and
emits retroactive events.

Emitted events:

  enrolled (retroactive)
    One per Person note. ts = `created:` frontmatter date if present
    (rendered as `<date>T00:00:00.000Z`); falls back to the file's
    mtime if `created:` is missing.

  send_intent + send_confirmed (retroactive, paired)
    One pair per touch note with `sent: true`. ts = `sent_at:` or
    `date:` frontmatter (in that priority). intent_id is synthetic
    and deterministic: `bf_<sha256(person_id|date|channel)[:16]>` so
    rerunning the script is idempotent.

  send_confirmed_orphan
    One per Person note that has a `last_touch:` date but no matching
    touch note in the conversations dir. Surfaces for manual review;
    the operator can hand-write a touch stub or accept the loose
    history.

Idempotency:
  Every emission checks the ledger first. enrolled events are
  deduped by (person_id, type=enrolled); send events by intent_id.
  Safe to re-run after partial completion.

CLI:

    python backfill_ledger.py --dry-run [--vault-path <p>]
    python backfill_ledger.py --apply   [--vault-path <p>]
    python backfill_ledger.py --validate [--vault-path <p>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

import identity
import ledger as _ledger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _vault_dirs(cfg: dict, vault_override: str | None) -> tuple[Path, Path] | None:
    """Return (people_dir, conversations_dir) or None if unresolvable."""
    if vault_override:
        vault_path = Path(os.path.expanduser(vault_override)).resolve()
    else:
        v = cfg.get("vault") or {}
        vault_path = Path(os.path.expanduser(v.get("path") or "")).resolve()
    if not vault_path.exists():
        return None
    v = cfg.get("vault") or {}
    people_dir = vault_path / (v.get("people_dir") or "10 People")
    conv_dir = vault_path / (v.get("conversations_dir") or "40 Conversations")
    if not people_dir.exists():
        return None
    # conversations_dir may legitimately not exist on a brand-new vault.
    return people_dir, conv_dir


def _ledger_dir() -> Path:
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return _ledger.DEFAULT_LEDGER_DIR


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:end].lstrip("\n"))
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _date_to_iso(value, *, fallback_mtime: float | None = None) -> str:
    """Coerce a frontmatter date value to an ISO 8601 UTC string.

    Accepts:
      - datetime.date / datetime.datetime
      - 'YYYY-MM-DD' string
      - falls through to fallback_mtime (file mtime), or 'now' if missing.

    The fallback is silent — we don't want to refuse to retroactively
    enroll a Person just because their `created:` field was edited away.
    """
    if value is not None:
        if hasattr(value, "isoformat"):
            try:
                if isinstance(value, datetime):
                    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                else:
                    dt = datetime(value.year, value.month, value.day,
                                  tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            except (TypeError, ValueError):
                pass
        if isinstance(value, str):
            s = value.strip()
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            except ValueError:
                # Bare date strings sometimes appear with trailing chars.
                m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
                if m:
                    return f"{m.group(1)}T00:00:00.000Z"
    if fallback_mtime is not None:
        dt = datetime.fromtimestamp(fallback_mtime, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _person_link_to_name(value) -> str | None:
    """Parse `[[Display Name]]` wikilink into the bare display name."""
    if not value:
        return None
    if isinstance(value, str):
        m = re.match(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", value.strip())
        return (m.group(1).strip() if m else value.strip()) or None
    return None


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class PersonRecord:
    path: Path
    name: str
    person_id: str | None
    created_ts: str
    status: str | None
    last_touch: str | None
    has_identity_keys: bool


@dataclass
class TouchRecord:
    path: Path
    person_link_name: str | None
    channel: str
    date_ts: str
    sent_at_ts: str | None
    linkedin_state: str | None
    raw_fm: dict


@dataclass
class BackfillResult:
    enrolled_emitted: list[str] = field(default_factory=list)
    enrolled_skipped: list[str] = field(default_factory=list)
    sends_emitted: list[str] = field(default_factory=list)
    sends_skipped: list[str] = field(default_factory=list)
    orphans_emitted: list[str] = field(default_factory=list)
    persons_without_id: list[str] = field(default_factory=list)
    touches_without_person_match: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Walkers
# ---------------------------------------------------------------------------


def _walk_person_records(people_dir: Path) -> list[PersonRecord]:
    out: list[PersonRecord] = []
    for note in sorted(people_dir.rglob("*.md")):
        rel = note.relative_to(people_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if ".conflicted" in note.name or note.name.endswith(".conflict.md"):
            continue
        fm = _parse_frontmatter(note)
        if not fm or (fm.get("type") or "").strip() != "person":
            continue
        try:
            mtime = note.stat().st_mtime
        except OSError:
            mtime = None
        created_ts = _date_to_iso(fm.get("created"), fallback_mtime=mtime)
        out.append(PersonRecord(
            path=note.resolve(),
            name=str(fm.get("name") or note.stem).strip(),
            person_id=(str(fm["id"]).strip() if fm.get("id") else None),
            created_ts=created_ts,
            status=(str(fm.get("status")).strip() if fm.get("status") else None),
            last_touch=(str(fm.get("last_touch")).strip()
                        if fm.get("last_touch") else None),
            has_identity_keys=bool(fm.get("identity_keys")),
        ))
    return out


def _walk_touch_records(conv_dir: Path) -> list[TouchRecord]:
    if not conv_dir.exists():
        return []
    out: list[TouchRecord] = []
    for note in sorted(conv_dir.rglob("*.md")):
        rel = note.relative_to(conv_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if ".conflicted" in note.name or note.name.endswith(".conflict.md"):
            continue
        fm = _parse_frontmatter(note)
        if not fm or (fm.get("type") or "").strip() != "touch":
            continue
        if not bool(fm.get("sent")):
            continue
        try:
            mtime = note.stat().st_mtime
        except OSError:
            mtime = None
        date_ts = _date_to_iso(fm.get("date"), fallback_mtime=mtime)
        sent_at_ts = None
        if fm.get("sent_at"):
            sent_at_ts = _date_to_iso(fm.get("sent_at"), fallback_mtime=mtime)
        channel = str(fm.get("channel") or "email").strip().lower() or "email"
        ls = fm.get("linkedin_state")
        out.append(TouchRecord(
            path=note.resolve(),
            person_link_name=_person_link_to_name(fm.get("person")),
            channel=channel,
            date_ts=date_ts,
            sent_at_ts=sent_at_ts,
            linkedin_state=(str(ls).strip() if ls else None),
            raw_fm=fm,
        ))
    return out


# ---------------------------------------------------------------------------
# Synthetic intent_id
# ---------------------------------------------------------------------------


def synth_intent_id(
    person_id: str, date_iso: str, channel: str,
    touch_stem: str | None = None,
) -> str:
    """Deterministic synthetic intent id for backfill.

    `bf_` prefix distinguishes from live `snd_` ULIDs so a reader can
    instantly tell which sends came from retroactive reconstruction.

    The touch_stem discriminator is load-bearing: two real touches to
    the same person on the same day via the same channel (initial + retry,
    or reply-thread fragments) are distinct sends, not one. Without the
    stem they'd hash-collide and a follow-up send would be silently lost
    from the funnel. Hash inputs stay stable across runs → idempotent.
    """
    parts = [person_id, date_iso[:10], channel]
    if touch_stem:
        parts.append(touch_stem)
    payload = "|".join(parts).encode("utf-8")
    h = hashlib.sha256(payload).hexdigest()[:16]
    return f"bf_{h}"


# ---------------------------------------------------------------------------
# Person → id resolution
# ---------------------------------------------------------------------------


def _build_name_to_id(persons: list[PersonRecord]) -> dict[str, str]:
    """Map display-name → person_id, normalized case-insensitive.

    Indexes BOTH the frontmatter `name:` AND the filename stem because
    Obsidian wikilinks (`[[Francis Nickels]]`) target the filename, which
    is often a shortened/casual form of the formal name in frontmatter
    (`name: Francis J. Nickels III`). Without the filename fallback,
    every formally-named record would orphan its touches.

    On name collisions we keep the first; `backfill_identity` should
    already have surfaced any same-name dups as a conflict.
    """
    out: dict[str, str] = {}
    for p in persons:
        if not p.person_id:
            continue
        out.setdefault(p.name.strip().lower(), p.person_id)
        out.setdefault(p.path.stem.strip().lower(), p.person_id)
    return out


# ---------------------------------------------------------------------------
# Planning + apply
# ---------------------------------------------------------------------------


def _enrolled_event_for(p: PersonRecord) -> dict:
    return {
        "type": "enrolled",
        "person_id": p.person_id,
        "note_path": str(p.path),
        "candidate_name": p.name,
        "ts": p.created_ts,
        "_recovered_by": "backfill",
    }


def _send_pair_for(
    t: TouchRecord,
    person_id: str,
    intent_id: str,
) -> tuple[dict, dict]:
    send_ts = t.sent_at_ts or t.date_ts
    intent = {
        "type": "send_intent",
        "person_id": person_id,
        "intent_id": intent_id,
        "channel": t.channel,
        "touch_note": str(t.path),
        "ts": send_ts,
        "_recovered_by": "backfill",
    }
    confirmed = {
        "type": "send_confirmed",
        "person_id": person_id,    # denormalized for query speed in backfill
        "intent_id": intent_id,
        "ts": send_ts,
        "_recovered_by": "backfill",
    }
    return intent, confirmed


def plan_and_apply(
    people_dir: Path,
    conv_dir: Path,
    *,
    dry_run: bool,
    ledger_dir: Path | None = None,
) -> BackfillResult:
    led = _ledger.Ledger(ledger_dir or _ledger_dir())
    led._build_indexes(force=True)

    persons = _walk_person_records(people_dir)
    touches = _walk_touch_records(conv_dir)
    name_to_id = _build_name_to_id(persons)

    result = BackfillResult()

    # 1. Enrolled events — one per Person note.
    existing_enrolled: set[str] = set()
    for pid, events in led._idx_person.items():
        if any(e.get("type") == "enrolled" for e in events):
            existing_enrolled.add(pid)

    for p in persons:
        if not p.person_id:
            result.persons_without_id.append(str(p.path))
            continue
        if p.person_id in existing_enrolled:
            result.enrolled_skipped.append(p.person_id)
            continue
        evt = _enrolled_event_for(p)
        if not dry_run:
            led.append(evt)
        result.enrolled_emitted.append(p.person_id)

    # 2. Send events — one pair per touch with sent:true.
    # Rebuild after any appends so existing-intent check is current.
    if not dry_run and result.enrolled_emitted:
        led._build_indexes(force=True)

    matched_touch_persons: set[str] = set()
    # In-run dedup: the on-disk index isn't re-read between appends, so two
    # touches that hash to the same synthetic intent_id (same person, same
    # date, same channel — common when a 2-channel touch lists email + a
    # later LinkedIn invite on the same day under the same record) would
    # both get appended. Track ids emitted in this run so they collapse.
    emitted_this_run: set[str] = set()
    for t in touches:
        if not t.person_link_name:
            result.touches_without_person_match.append(str(t.path))
            continue
        pid = name_to_id.get(t.person_link_name.strip().lower())
        if not pid:
            result.touches_without_person_match.append(str(t.path))
            continue
        matched_touch_persons.add(pid)
        send_ts = t.sent_at_ts or t.date_ts
        intent_id = synth_intent_id(pid, send_ts, t.channel,
                                    touch_stem=t.path.stem)
        if intent_id in led._idx_intent_origin \
                or intent_id in emitted_this_run:
            result.sends_skipped.append(intent_id)
            continue
        intent_evt, confirm_evt = _send_pair_for(t, pid, intent_id)
        if not dry_run:
            led.append(intent_evt)
            led.append(confirm_evt)
        emitted_this_run.add(intent_id)
        result.sends_emitted.append(intent_id)

    # 3. Orphans — Person notes with last_touch but no matching touch event.
    if not dry_run and result.sends_emitted:
        led._build_indexes(force=True)

    for p in persons:
        if not p.person_id or not p.last_touch:
            continue
        # Did any of the touches we just processed map to this person?
        if p.person_id in matched_touch_persons:
            continue
        # Already an orphan event for this person?
        existing_for_person = led._idx_person.get(p.person_id, [])
        if any(e.get("type") == "send_confirmed_orphan"
               for e in existing_for_person):
            continue
        orphan_ts = _date_to_iso(p.last_touch)
        evt = {
            "type": "send_confirmed_orphan",
            "person_id": p.person_id,
            "note_path": str(p.path),
            "ts": orphan_ts,
            "reason": ("Person.last_touch set but no matching touch note in "
                       "conversations dir — manual review recommended"),
            "_recovered_by": "backfill",
        }
        if not dry_run:
            led.append(evt)
        result.orphans_emitted.append(p.person_id)

    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_ledger(
    people_dir: Path,
    conv_dir: Path,
    *,
    ledger_dir: Path | None = None,
) -> dict:
    led = _ledger.Ledger(ledger_dir or _ledger_dir())
    led._build_indexes(force=True)

    persons = _walk_person_records(people_dir)
    touches = _walk_touch_records(conv_dir)
    name_to_id = _build_name_to_id(persons)

    person_ids_with_id = {p.person_id for p in persons if p.person_id}
    enrolled_pids = {pid for pid, events in led._idx_person.items()
                     if any(e.get("type") == "enrolled" for e in events)}
    missing_enrolled = sorted(person_ids_with_id - enrolled_pids)

    expected_intent_ids: set[str] = set()
    for t in touches:
        if not t.person_link_name:
            continue
        pid = name_to_id.get(t.person_link_name.strip().lower())
        if not pid:
            continue
        send_ts = t.sent_at_ts or t.date_ts
        expected_intent_ids.add(synth_intent_id(
            pid, send_ts, t.channel, touch_stem=t.path.stem,
        ))
    missing_intents = sorted(expected_intent_ids - led._idx_intent_origin.keys())

    return {
        "ok": (not missing_enrolled and not missing_intents),
        "person_count": len(persons),
        "touch_count": len(touches),
        "enrolled_events": len(enrolled_pids),
        "missing_enrolled": missing_enrolled,
        "expected_intents": len(expected_intent_ids),
        "missing_intents": missing_intents,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_result(result: BackfillResult, *, dry_run: bool) -> None:
    tag = "[dry-run]" if dry_run else "[applied]"
    print(f"{tag} backfill_ledger:")
    print(f"  enrolled emitted: {len(result.enrolled_emitted)}")
    print(f"  enrolled skipped (already present): {len(result.enrolled_skipped)}")
    print(f"  sends emitted (intent+confirmed pairs): {len(result.sends_emitted)}")
    print(f"  sends skipped (already present): {len(result.sends_skipped)}")
    print(f"  orphans emitted: {len(result.orphans_emitted)}")
    if result.persons_without_id:
        print(f"  ⚠ persons without id (run backfill_identity --apply first): "
              f"{len(result.persons_without_id)}")
        for path in result.persons_without_id[:5]:
            print(f"      {path}")
        if len(result.persons_without_id) > 5:
            print(f"      ... and {len(result.persons_without_id) - 5} more")
    if result.touches_without_person_match:
        print(f"  ⚠ touches without person match: "
              f"{len(result.touches_without_person_match)}")
        for path in result.touches_without_person_match[:5]:
            print(f"      {path}")
        if len(result.touches_without_person_match) > 5:
            print(f"      ... and {len(result.touches_without_person_match) - 5} more")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--validate", action="store_true")
    p.add_argument("--vault-path", default=None,
                   help="Override config.yml (testing).")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    cfg = {} if args.vault_path else _load_config()
    dirs = _vault_dirs(cfg, args.vault_path)
    if dirs is None:
        msg = "vault path not resolvable"
        print(json.dumps({"ok": False, "reason": msg}) if args.json
              else f"ERROR: {msg}", file=sys.stderr)
        sys.exit(2)
    people_dir, conv_dir = dirs

    if args.validate:
        result = validate_ledger(people_dir, conv_dir)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            tag = "✅" if result["ok"] else "❌"
            print(f"{tag} ledger backfill validation")
            print(f"   persons:           {result['person_count']}")
            print(f"   touches (sent):    {result['touch_count']}")
            print(f"   enrolled events:   {result['enrolled_events']}")
            print(f"   expected intents:  {result['expected_intents']}")
            if result["missing_enrolled"]:
                print(f"   missing enrolled:  {len(result['missing_enrolled'])}")
            if result["missing_intents"]:
                print(f"   missing intents:   {len(result['missing_intents'])}")
        sys.exit(0 if result["ok"] else 1)

    result = plan_and_apply(people_dir, conv_dir, dry_run=args.dry_run)
    if args.json:
        print(json.dumps({
            "ok": True,
            "dry_run": args.dry_run,
            "enrolled_emitted": result.enrolled_emitted,
            "enrolled_skipped": result.enrolled_skipped,
            "sends_emitted": result.sends_emitted,
            "sends_skipped": result.sends_skipped,
            "orphans_emitted": result.orphans_emitted,
            "persons_without_id": result.persons_without_id,
            "touches_without_person_match": result.touches_without_person_match,
        }, indent=2))
    else:
        _print_result(result, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
