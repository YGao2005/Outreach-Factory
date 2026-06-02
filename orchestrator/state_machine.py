"""State machine for the outreach-factory pipeline.

Stages (frontmatter field `pipeline_stage` on Person notes):

    queued → researched → drafted → ready → sent

Transitions:

    queued     → researched   via /research-prospect   (automated)
    researched → drafted      via /draft-outreach      (automated)
    drafted    → ready        manual review gate       (user flips)
    ready      → sent         via /send-outreach       (automated)
    sent       → (terminal)

`pipeline_stage` is the orchestrator's state-machine field. It is distinct from
the existing CRM `status:` field (queued / contacted / replied / ...). The two
do not conflict — `/send-outreach` flips `status:`; the dispatcher flips
`pipeline_stage:`.

Person-note lookup (Phase 5.5 Week 1b):

  - `find_person_note(name)` is the legacy name-only path; retained for
    back-compat with callers that have only a display name. Two distinct
    people with the same name will collide here — prefer the identity-aware
    variants below whenever the caller has any stable identifier.
  - `find_person_note_by_keys(keys)` performs identity-graph lookup using
    the `identity` module. Returns a single Path on a confident match,
    None on no match, or a Conflict object if 2+ records match.
  - `find_person_note_identity(name, keys)` is the integrated entry point:
    identity-first when keys are non-empty, name fallback otherwise.

CLI:

    python state_machine.py list-eligible [--json] [--automated-only]
    python state_machine.py status [--json]
    python state_machine.py find-person-note --name <n> \
        [--linkedin <url>] [--email <addr>] [--github <h>] [--twitter <h>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

import identity
import ledger as _ledger


STAGES = ("queued", "researched", "drafted", "ready", "sent")
TERMINAL = "sent"

# from_stage -> (to_stage, skill_to_invoke, is_automated)
TRANSITIONS: dict[str, tuple[str, str | None, bool]] = {
    "queued":     ("researched", "research-prospect", True),
    "researched": ("drafted",    "draft-outreach",    True),
    "drafted":    ("ready",      None,                False),  # manual review gate
    "ready":      ("sent",       "send-outreach",     True),
}


def next_stage(current: str) -> str | None:
    t = TRANSITIONS.get(current)
    return t[0] if t else None


def skill_for_transition(current: str) -> str | None:
    t = TRANSITIONS.get(current)
    return t[1] if t else None


def is_automated(current: str) -> bool:
    t = TRANSITIONS.get(current)
    return bool(t and t[2])


def is_terminal(stage: str) -> bool:
    return stage == TERMINAL or stage not in STAGES


@dataclass
class Prospect:
    note_path: str
    name: str
    current_stage: str
    target_stage: str | None
    skill: str | None
    automated: bool
    pipeline_error: str | None = None


def _load_config() -> dict:
    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _vault_people_dir(cfg: dict) -> Path | None:
    v = cfg.get("vault") or {}
    vault_path = Path(os.path.expanduser(v.get("path") or ""))
    people_dir = vault_path / (v.get("people_dir") or "10 People")
    return people_dir if people_dir.exists() else None


def _parse_frontmatter(p: Path) -> dict | None:
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        return yaml.safe_load(text[3:end].lstrip("\n")) or {}
    except yaml.YAMLError:
        return None


def _walk_person_notes(people_dir: Path):
    """Yield (path, frontmatter) for every person note in the people dir tree."""
    for note in sorted(people_dir.rglob("*.md")):
        # Skip locks dir, hidden dirs, etc.
        if any(part.startswith(".") for part in note.relative_to(people_dir).parts):
            continue
        fm = _parse_frontmatter(note)
        if not fm:
            continue
        if (fm.get("type") or "").strip() != "person":
            continue
        yield note, fm


def list_eligible(cfg: dict | None = None) -> list[Prospect]:
    cfg = cfg or _load_config()
    people_dir = _vault_people_dir(cfg)
    if people_dir is None:
        return []
    out: list[Prospect] = []
    for note, fm in _walk_person_notes(people_dir):
        stage = (fm.get("pipeline_stage") or "").strip()
        if stage not in STAGES:
            continue
        if stage == TERMINAL:
            continue
        target = next_stage(stage)
        skill = skill_for_transition(stage)
        out.append(Prospect(
            note_path=str(note.resolve()),
            name=str(fm.get("name") or note.stem).strip(),
            current_stage=stage,
            target_stage=target,
            skill=skill,
            automated=is_automated(stage),
            pipeline_error=(fm.get("pipeline_error") or None),
        ))
    return out


def find_person_note(name: str, cfg: dict | None = None,
                     _emit_warning: bool = True) -> Path | None:
    """Locate a Person note by display name across every subdir of {vault.people_dir}.

    LEGACY name-only lookup. Two distinct people who share a display name
    will collide here — prefer `find_person_note_by_keys` or
    `find_person_note_identity` for any caller that has a stable identifier.

    Match priority:
      1. Frontmatter `name:` field equals the requested name (robust to file renames)
      2. Filename (without `.md`) equals the requested name (fallback for legacy notes)

    Both comparisons are case-insensitive and strip surrounding whitespace.

    Returns the absolute Path on success, or None if no match.
    """
    if _emit_warning:
        # Soft deprecation: stderr-only, single line, not a Python warning so
        # batch CLI output stays readable. Callers that explicitly opt out
        # (the integrated find_person_note_identity helper) suppress this.
        print(
            "state_machine.find_person_note: name-only lookup is legacy — "
            "prefer find_person_note_by_keys when an identifier is available",
            file=sys.stderr,
        )
    cfg = cfg or _load_config()
    people_dir = _vault_people_dir(cfg)
    if people_dir is None:
        return None
    target = (name or "").strip().lower()
    if not target:
        return None
    filename_match: Path | None = None
    for note, fm in _walk_person_notes(people_dir):
        fm_name = str(fm.get("name") or "").strip().lower()
        if fm_name and fm_name == target:
            return note.resolve()
        if filename_match is None and note.stem.strip().lower() == target:
            filename_match = note.resolve()
    return filename_match


def find_person_note_by_keys(
    keys: "identity.IdentityKeys",
    cfg: dict | None = None,
) -> Path | "identity.Conflict" | None:
    """Identity-graph lookup by stable identifiers.

    Returns:
        Path           -> exactly one Person note matches the keys
        Conflict       -> 2+ records match (or single-class email + distinct
                          LinkedIn ambiguity); a conflict report is written
                          under ~/.outreach-factory/conflicts/
        None           -> no match (keys are empty or no record intersects)

    The lookup uses identity.resolve_strict so behavior is identical to
    enrollment: strict policy, never auto-merge. Callers that want the raw
    match list (to handle the multi-match case themselves) should use
    identity.find_matches directly.
    """
    if keys.is_empty():
        return None
    cfg = cfg or _load_config()
    people_dir = _vault_people_dir(cfg)
    if people_dir is None:
        return None
    matches = identity.find_matches(keys, people_dir)
    conflicts_dir = Path.home() / ".outreach-factory" / "conflicts"
    resolution = identity.resolve_strict(keys, matches, conflicts_dir)
    if resolution is None:
        return None
    if isinstance(resolution, identity.Match):
        return resolution.note_path
    return resolution    # Conflict


def find_person_note_identity(
    name: str | None = None,
    keys: "identity.IdentityKeys | None" = None,
    cfg: dict | None = None,
) -> Path | "identity.Conflict" | None:
    """Integrated lookup: identity-first, name fallback.

    - If `keys` is provided and non-empty, performs identity-graph lookup.
      Returns Conflict on ambiguous match — caller MUST handle.
    - If `keys` is empty / not provided, falls back to legacy name lookup
      (silently — no deprecation warning, since the caller explicitly
      chose the integrated entry point that knows when keys are absent).

    This is the recommended entry point for dispatcher-style code that
    re-locates a note across a stage transition.
    """
    if keys is not None and not keys.is_empty():
        result = find_person_note_by_keys(keys, cfg=cfg)
        if result is not None:
            return result
        # Fall through to name lookup ONLY if no identity match — useful
        # during the backfill window when some notes have identity_keys and
        # others don't.
    if name:
        return find_person_note(name, cfg=cfg, _emit_warning=False)
    return None


def _ledger_dir() -> Path:
    """Resolve the ledger dir for transition records.

    Mirrors enrollment._ledger_dir: env var wins so test harnesses can
    sandbox writes; default is ~/.outreach-factory/ledger/.
    """
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return _ledger.DEFAULT_LEDGER_DIR


def record_transition(
    person_id: str,
    from_stage: str | None,
    to_stage: str,
    *,
    skill: str | None = None,
    note_path: str | None = None,
    reason: str | None = None,
    extra: dict | None = None,
) -> dict | None:
    """Append a `state_transition` event for this pipeline move.

    Callers (the dispatcher and any skill that flips pipeline_stage)
    should invoke this immediately after the vault frontmatter write so
    the ledger is the trusted record even if the vault later drifts.

    Returns the appended event dict, or None if the append failed (a
    stderr warning is printed; transitions never raise — the orchestrator
    must keep moving even with a degraded ledger).
    """
    payload: dict = {
        "type": "state_transition",
        "person_id": person_id,
        "from": from_stage,
        "to": to_stage,
    }
    if skill:
        payload["skill"] = skill
    if note_path:
        payload["note_path"] = note_path
    if reason:
        payload["reason"] = reason
    if extra:
        for k, v in extra.items():
            payload.setdefault(k, v)
    try:
        led = _ledger.Ledger(_ledger_dir())
        return led.append(payload)
    except (OSError, ValueError) as exc:
        print(f"WARNING: state_machine.record_transition: ledger append "
              f"failed for {person_id} {from_stage}->{to_stage}: {exc}",
              file=sys.stderr)
        return None


def pipeline_status(cfg: dict | None = None) -> dict:
    """Return a count-per-stage summary for the whole vault."""
    cfg = cfg or _load_config()
    people_dir = _vault_people_dir(cfg)
    if people_dir is None:
        return {"counts": {}, "total": 0}
    counts: Counter[str] = Counter()
    for _note, fm in _walk_person_notes(people_dir):
        stage = (fm.get("pipeline_stage") or "").strip()
        if stage:
            counts[stage] += 1
    return {
        "counts": {s: counts.get(s, 0) for s in STAGES},
        "total": sum(counts.values()),
    }


def _print_eligible(items: list[Prospect]) -> None:
    if not items:
        print("(no prospects with pipeline_stage set, or all are terminal)")
        return
    width = max(len(it.name) for it in items)
    for it in items:
        arrow = "→" if it.automated else "⏸"
        err = f"  ⚠ {it.pipeline_error}" if it.pipeline_error else ""
        print(f"  {it.name:<{width}}  {it.current_stage:>11s} {arrow} {it.target_stage or '(terminal)':<11s}  ({it.skill or '—'}){err}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    le = sub.add_parser("list-eligible")
    le.add_argument("--json", action="store_true")
    le.add_argument("--automated-only", action="store_true")

    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")

    fp = sub.add_parser("find-person-note")
    fp.add_argument("--name", default=None,
                    help="Display-name fallback if no identity keys match")
    fp.add_argument("--linkedin", default=None)
    fp.add_argument("--email", action="append", default=None,
                    help="Email (repeatable)")
    fp.add_argument("--github", default=None)
    fp.add_argument("--twitter", default=None)
    fp.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "list-eligible":
        items = list_eligible()
        if args.automated_only:
            items = [it for it in items if it.automated]
        if args.json:
            print(json.dumps([asdict(it) for it in items], indent=2))
        else:
            _print_eligible(items)

    elif args.cmd == "status":
        s = pipeline_status()
        if args.json:
            print(json.dumps(s, indent=2))
        else:
            print(f"Pipeline status ({s['total']} prospects with pipeline_stage set):")
            for stage in STAGES:
                n = s["counts"].get(stage, 0)
                gate = " ⏸ (manual review gate)" if stage == "drafted" else ""
                term = " (terminal)" if stage == "sent" else ""
                print(f"  {stage:<11s}  {n:>3d}{gate}{term}")

    elif args.cmd == "find-person-note":
        keys = identity.compute_keys(
            name=args.name, emails=args.email,
            linkedin_url=args.linkedin, github=args.github, twitter=args.twitter,
        )
        result = find_person_note_identity(name=args.name, keys=keys)
        if isinstance(result, identity.Conflict):
            out = {
                "ok": False, "resolution": "conflict", "name": args.name,
                "path": None, "report_path": str(result.report_path),
                "match_count": len(result.matches),
                "matches": [{"path": str(m.note_path),
                             "person_id": m.person_id,
                             "matched_classes": sorted(m.matched_classes)}
                            for m in result.matches],
            }
            if args.json:
                print(json.dumps(out))
            else:
                print(f"CONFLICT: {out['match_count']} matches — see {out['report_path']}")
            sys.exit(2)
        ok = result is not None
        if args.json:
            print(json.dumps({"ok": ok, "name": args.name,
                              "path": str(result) if result else None}))
        else:
            print(str(result) if result else "(not found)")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
