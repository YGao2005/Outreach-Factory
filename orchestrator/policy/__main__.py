"""Policy CLI — `python -m orchestrator.policy <subcommand>`.

Two subcommands ship in Week 5 (ADR-0007 §Decision item "Simulation
surface" + §Operator tooling):

* ``simulate`` — load the YAML rule list, build a ``RuleContext`` from
  a named Person note (+ register / channel / optional `--at`
  time-travel), call :func:`engine.evaluate_all`, and print every
  rule's verdict. Used for "would my YAML refuse this send right now,
  and which rule fires first?" investigations.
* ``override`` — write a validated ``manual_override`` ledger event.
  ADR-0006 locked the event schema; before this CLI, the only way to
  add an override was hand-crafting JSON and piping it through
  ``orchestrator/ledger.py append @event.json``. This subcommand
  reduces the "incident at 2am, operator writes malformed JSON"
  failure mode that the Week 4 review surfaced as W1.

Why a separate ``__main__`` instead of extending ``engine.py``: the
CLI is operational tooling, not engine internals. Keeping it in a
dedicated module means a future ``simulation.py`` (Week 6 — alternate
rule-set what-if, batch what-if) can land alongside without churning
the engine surface. The handoff doc names ``simulation.py`` as the
PILLAR-PLAN target; Week 5 ships ``evaluate_all`` + this CLI;
``simulation.py`` lands when there's a real reason for a third module.

Config discovery (matches the rest of the orchestrator)
-------------------------------------------------------
* Policy YAML directory: ``OUTREACH_FACTORY_POLICIES_DIR`` env, then
  ``~/.outreach-factory/policies/`` (the same lookup
  :func:`send_queued._policies_dir` does).
* Ledger directory: ``OUTREACH_FACTORY_LEDGER_DIR`` env, then
  ``~/.outreach-factory/ledger/`` (same as
  :func:`send_queued._ledger_handle`).
* People-directory for `--person <id>` resolution:
  ``OUTREACH_FACTORY_PEOPLE_DIR`` env, then derived from
  ``~/.outreach-factory/config.yml`` ``vault.path`` (same lookup
  :func:`identity._vault_people_dir` does). The CLI also accepts
  ``--person-note <path>`` to bypass the directory walk — useful in
  tests + ad-hoc one-off investigations.

Exit codes:
    0  success
    2  argument or input error (bad YAML, missing person note, etc.)
    3  policy engine raised during simulation (operator-actionable
       — same shape as ADR-0001 §Decision item 2 "exceptions propagate")
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from orchestrator import ledger as _ledger
from . import tz_inference
from .engine import evaluate_all, load_rules_from_yaml
from .types import Allow, Block, RuleContext, RuleResult


# Far-time-travel sanity threshold for `simulate --at`. An operator who
# meant 2026 and typo'd 2206 produces a 180-years-future simulation
# whose only symptom is "why doesn't my cooldown fire?" The threshold
# warns (doesn't refuse — forensic time-travel is legitimate); the
# 365-day window is chosen so that any normal "what would tomorrow's
# verdict be?" gesture stays silent while a century-typo loudly stands
# out. See REVIEW-week-5.md §F4 for the original finding.
_AT_TIMETRAVEL_SANITY_DAYS = 365


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------


def _policies_dir(override: str | None = None) -> Path:
    """Resolve where the policy YAMLs live.

    Precedence: ``--policies-dir`` arg → ``OUTREACH_FACTORY_POLICIES_DIR``
    env → ``~/.outreach-factory/policies/``. Mirrors
    :func:`send_queued._policies_dir` so tests + production agree.
    """
    if override:
        return Path(os.path.expanduser(override)).resolve()
    env = os.environ.get("OUTREACH_FACTORY_POLICIES_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return Path.home() / ".outreach-factory" / "policies"


def _ledger_dir(override: str | None = None) -> Path:
    """Resolve where the ledger directory lives.

    Precedence matches :func:`send_queued._ledger_handle`.
    """
    if override:
        return Path(os.path.expanduser(override)).resolve()
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return Path.home() / ".outreach-factory" / "ledger"


def _people_dir(override: str | None = None) -> Path | None:
    """Resolve where Person notes live.

    Precedence: ``--people-dir`` arg → ``OUTREACH_FACTORY_PEOPLE_DIR``
    env → ``~/.outreach-factory/config.yml`` `vault.path` /
    `vault.people_dir`. Returns ``None`` if none of these resolve to
    an existing directory — the caller decides whether that's an error
    (it is for `simulate --person <id>`, isn't for `--person-note`).
    """
    if override:
        p = Path(os.path.expanduser(override)).resolve()
        return p if p.exists() else None
    env = os.environ.get("OUTREACH_FACTORY_PEOPLE_DIR")
    if env:
        p = Path(os.path.expanduser(env)).resolve()
        return p if p.exists() else None
    cfg_path = Path.home() / ".outreach-factory" / "config.yml"
    if not cfg_path.exists():
        return None
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    v = cfg.get("vault") or {}
    vault_path = Path(os.path.expanduser(str(v.get("path") or ""))).resolve()
    if not vault_path.exists():
        return None
    p = vault_path / (v.get("people_dir") or "10 People")
    return p if p.exists() else None


# ---------------------------------------------------------------------------
# Person-note parsing (light; doesn't import identity.py to keep the CLI
# independent of the orchestrator/* package's full surface — only YAML
# frontmatter and a handful of fields are needed for simulate)
# ---------------------------------------------------------------------------


def _parse_person_note(note_path: Path) -> dict[str, Any]:
    """Extract the fields ``simulate`` needs from a Person note.

    Returns a dict with the keys:
      * ``person_id`` (str | None)
      * ``country`` (str | None) — precedence matches
        :func:`identity.read_person_keys` (``identity_keys.country`` ⟶
        top-level ``location:``)
      * ``research_tier`` (str | None) — for ``ctx.tier``
      * ``status`` (str | None) — for ``ctx.person_status``
      * ``email`` (str | None) — for ``ctx.email``

    Raises ``ValueError`` on a file that doesn't have a YAML
    frontmatter block or whose ``type:`` isn't ``person``.
    """
    text = note_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(
            f"{note_path}: file does not start with YAML frontmatter "
            f"(`---` line)",
        )
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(
            f"{note_path}: YAML frontmatter is not terminated by "
            f"`---` on its own line",
        )
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{note_path}: YAML parse error: {exc}") from exc
    if not isinstance(fm, dict):
        raise ValueError(
            f"{note_path}: YAML frontmatter is not a mapping (got "
            f"{type(fm).__name__})",
        )
    if (fm.get("type") or "").strip() != "person":
        raise ValueError(
            f"{note_path}: not a Person note (type={fm.get('type')!r})",
        )

    person_id = fm.get("id") or None

    # Country precedence — identical to identity.read_person_keys (ADR-0005)
    country: str | None = None
    ik = fm.get("identity_keys") or {}
    if isinstance(ik, dict) and ik.get("country"):
        country = str(ik["country"]).strip() or None
    if country is None:
        loc = fm.get("location")
        if isinstance(loc, str):
            country = loc.strip() or None
        elif isinstance(loc, dict):
            c = loc.get("country")
            if c:
                country = str(c).strip() or None

    research_tier = fm.get("research_tier") or None
    if isinstance(research_tier, str):
        research_tier = research_tier.strip() or None

    return {
        "person_id": person_id,
        "country": country,
        "research_tier": research_tier,
        "status": fm.get("status") or None,
        "email": fm.get("email") or None,
    }


def _find_person_note_by_id(people_dir: Path, person_id: str) -> Path | None:
    """Walk ``people_dir`` and return the first .md file whose frontmatter
    ``id:`` equals ``person_id``. ``None`` if not found.

    Skips hidden / .conflicted files for parity with
    :func:`identity.build_index`. This is the read-only equivalent of
    that function tailored to "look up one id" — cheaper than building
    the full IndexEntry list for a CLI's one-off use.
    """
    for note in sorted(people_dir.rglob("*.md")):
        rel = note.relative_to(people_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if ".conflicted" in note.name:
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end < 0:
            continue
        try:
            fm = yaml.safe_load(text[4:end]) or {}
        except yaml.YAMLError:
            continue
        if isinstance(fm, dict) and (fm.get("id") or "").strip() == person_id:
            return note
    return None


# ---------------------------------------------------------------------------
# Verdict pretty-printer
# ---------------------------------------------------------------------------


def _format_verdict(rule_name: str, result: RuleResult) -> str:
    """Single-line rendering of one rule's verdict for the simulate output.

    Allow lines stay compact ("ALLOW  rule-name"); Block lines surface
    the reason + detail keys so the operator sees the firing-reason at
    a glance.
    """
    if isinstance(result, Allow):
        return f"ALLOW  {rule_name}"
    if isinstance(result, Block):
        detail_keys = ", ".join(sorted(result.detail.keys())) if result.detail else ""
        if detail_keys:
            return (
                f"BLOCK  {rule_name}  — {result.reason}  "
                f"[detail: {detail_keys}]"
            )
        return f"BLOCK  {rule_name}  — {result.reason}"
    return f"???    {rule_name}  ({type(result).__name__})"


def _verdict_to_dict(rule_name: str, result: RuleResult) -> dict[str, Any]:
    if isinstance(result, Allow):
        return {"rule": rule_name, "verdict": "Allow"}
    if isinstance(result, Block):
        return {
            "rule": rule_name,
            "verdict": "Block",
            "reason": result.reason,
            "detail": dict(result.detail),
        }
    return {"rule": rule_name, "verdict": type(result).__name__}


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------


def _cmd_simulate(args: argparse.Namespace) -> int:
    # Resolve the Person note.
    if args.person_note:
        note_path = Path(os.path.expanduser(args.person_note)).resolve()
        if not note_path.exists():
            print(
                f"ERROR: --person-note path does not exist: {note_path}",
                file=sys.stderr,
            )
            return 2
    else:
        if not args.person:
            print(
                "ERROR: either --person <id> or --person-note <path> is "
                "required for `simulate`",
                file=sys.stderr,
            )
            return 2
        pd = _people_dir(args.people_dir)
        if pd is None:
            print(
                "ERROR: people_dir not resolvable. Set "
                "OUTREACH_FACTORY_PEOPLE_DIR, pass --people-dir, or "
                "configure vault.path + vault.people_dir in "
                "~/.outreach-factory/config.yml. Alternatively pass "
                "--person-note <path> directly.",
                file=sys.stderr,
            )
            return 2
        found = _find_person_note_by_id(pd, args.person)
        if found is None:
            print(
                f"ERROR: no Person note with id={args.person!r} found "
                f"under {pd}",
                file=sys.stderr,
            )
            return 2
        note_path = found

    try:
        person = _parse_person_note(note_path)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    person_id = person["person_id"]
    if not person_id:
        print(
            f"ERROR: Person note {note_path} has no `id:` frontmatter; "
            f"cannot build a RuleContext without one.",
            file=sys.stderr,
        )
        return 2

    # Resolve `--at` (time-travel) — default is "now (UTC)".
    if args.at:
        try:
            now = datetime.fromisoformat(args.at.replace("Z", "+00:00"))
        except ValueError as exc:
            print(
                f"ERROR: --at value {args.at!r} is not ISO-8601: {exc}",
                file=sys.stderr,
            )
            return 2
        if now.tzinfo is None:
            # Naive datetime → assume UTC (consistent with how the
            # ledger reads naive timestamps; ADR-0001 §Decision item 1
            # specifies UTC-aware context, so we normalize here).
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        # F4 sanity warning: a typo'd century ("2206" for "2026") would
        # silently produce a far-future simulation. Warn but don't
        # refuse — forensic far-time simulation is legitimate.
        real_now = datetime.now(timezone.utc)
        if abs(now - real_now) > timedelta(days=_AT_TIMETRAVEL_SANITY_DAYS):
            print(
                f"WARNING: --at {args.at} is more than "
                f"{_AT_TIMETRAVEL_SANITY_DAYS} days from real-now "
                f"({real_now.isoformat()}). Common typo class: "
                f"transposed century ('2206' vs '2026') or wrong "
                f"decade. Proceeding with simulation as written.",
                file=sys.stderr,
            )
    else:
        now = datetime.now(timezone.utc)

    # Tz inference (ADR-0005 contract).
    timezone_name = tz_inference.infer_timezone(person["country"])

    # Build a minimal LedgerLike. The orchestrator.ledger.Ledger reader
    # is the production shape; we use it so the rules walking
    # `all_events()` see the same on-disk events the production gate
    # would see.
    ledger = _ledger.Ledger(_ledger_dir(args.ledger_dir))

    email = person["email"]
    email_domain: str | None = None
    if email and "@" in email:
        email_domain = email.split("@", 1)[1].lower()

    ctx = RuleContext(
        person_id=person_id,
        channel=args.channel,
        register=args.register,
        email=email,
        email_domain=email_domain,
        now=now,
        timezone=timezone_name,
        ledger=ledger,
        person_status=person["status"],
        run_id=args.run_id,
        tier=person["research_tier"],
    )

    # Load the YAML rules. Missing file → empty list → "ALLOW (no
    # rules configured)" output (mirrors the greenfield contract from
    # ADR-0001).
    policies_dir = _policies_dir(args.policies_dir)
    rules_path = policies_dir / args.rules_file
    rules = load_rules_from_yaml(rules_path)

    # Parallel pull of names — load_rules_from_yaml returns the
    # constructed instances; their `.name` attribute is what
    # `evaluate_all` doesn't carry. We pair them here.
    rule_names = [getattr(r, "name", "<anonymous>") for r in rules]

    try:
        results = evaluate_all(rules, ctx)
    except Exception as exc:
        # ADR-0001 §Decision item 2: engine doesn't swallow. The CLI
        # surface, however, prints + returns a structured error code —
        # an operator running simulate at 2am during an incident
        # wants to see which rule blew up, not just a stack trace.
        # We still emit the traceback to stderr for the engineer.
        import traceback
        print(f"ERROR: policy engine raised: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 3

    # Output.
    out_lines: list[str] = []
    summary = {
        "person_id": person_id,
        "channel": args.channel,
        "register": args.register,
        "at_utc": now.isoformat().replace("+00:00", "Z"),
        "tier": person["research_tier"],
        "person_status": person["status"],
        "recipient_timezone": timezone_name,
        "rules_file": str(rules_path),
        "rule_count": len(rules),
    }

    if args.json:
        out = {
            "context": summary,
            "verdicts": [
                _verdict_to_dict(name, result)
                for name, result in zip(rule_names, results)
            ],
            "would_block": any(isinstance(r, Block) for r in results),
            "first_block": next(
                (
                    name
                    for name, r in zip(rule_names, results)
                    if isinstance(r, Block)
                ),
                None,
            ),
        }
        print(json.dumps(out, indent=2, default=str))
        return 0

    out_lines.append(f"# simulate")
    out_lines.append(f"person_id          : {person_id}")
    out_lines.append(f"channel            : {args.channel}")
    out_lines.append(f"register           : {args.register}")
    out_lines.append(f"at (UTC)           : {summary['at_utc']}")
    out_lines.append(f"tier               : {summary['tier']!r}")
    out_lines.append(f"person_status      : {summary['person_status']!r}")
    out_lines.append(f"recipient_timezone : {timezone_name}")
    out_lines.append(f"rules_file         : {rules_path}")
    out_lines.append(f"rule_count         : {len(rules)}")
    out_lines.append("")
    if not rules:
        out_lines.append(
            "(no rules configured — greenfield Allow per ADR-0001)"
        )
    else:
        for name, result in zip(rule_names, results):
            out_lines.append(_format_verdict(name, result))
        first_block = next(
            (name for name, r in zip(rule_names, results) if isinstance(r, Block)),
            None,
        )
        out_lines.append("")
        if first_block:
            out_lines.append(
                f"production verdict (evaluate, short-circuit) : "
                f"BLOCK by {first_block}"
            )
        else:
            out_lines.append(
                "production verdict (evaluate, short-circuit) : ALLOW"
            )
    print("\n".join(out_lines))
    return 0


# ---------------------------------------------------------------------------
# override
# ---------------------------------------------------------------------------


def _collect_known_rule_names(args: argparse.Namespace) -> set[str] | None:
    """Walk the policies directory and return the set of every rule name.

    Used by ``_cmd_override`` to warn when ``--rule`` is a typo. Returns
    ``None`` if the policies directory doesn't exist or isn't readable —
    the caller treats that as "can't validate, no warning." Per-file
    parse errors are tolerated (skipped + counted in stderr); the goal
    is best-effort enumeration, not strict validation.

    Walks every ``*.yml`` in the policies dir (matching how the gate
    boot path loads + merges suppression lists). Each file's rule
    names are union'd into the returned set.
    """
    pdir = _policies_dir(getattr(args, "policies_dir", None))
    if not pdir.exists() or not pdir.is_dir():
        return None
    names: set[str] = set()
    parse_errors: list[str] = []
    for f in sorted(pdir.glob("*.yml")):
        try:
            for rule in load_rules_from_yaml(f):
                rname = getattr(rule, "name", None)
                if isinstance(rname, str) and rname:
                    names.add(rname)
        except Exception as exc:
            parse_errors.append(f"{f.name}: {exc}")
    if parse_errors:
        print(
            f"WARNING: --rule validation walked {len(parse_errors)} "
            f"file(s) with parse errors; some rule names may be "
            f"missing from the known-set. Errors: {parse_errors[:3]}"
            f"{'...' if len(parse_errors) > 3 else ''}",
            file=sys.stderr,
        )
    return names


def _cmd_override(args: argparse.Namespace) -> int:
    """Write a validated ``manual_override`` event to the ledger.

    Carries out W1 from the Week 4 review: until now the only way to
    produce one of these was hand-crafted JSON via ``ledger.py append``,
    which the operator might typo at 2am during an incident. This
    surface validates the args + builds the JSON correctly.

    Schema lock is ADR-0006 §`manual_override` event schema + consumption
    contract. Decisions encoded here:

    * ``--until`` is required and parsed to ISO 8601 UTC. A naive
      datetime is interpreted as UTC (consistent with the ledger
      reader's tolerance). An invalid timestamp fails with exit-2 BEFORE
      any ledger write.
    * ``--rule`` is required and is the exact name of the policy rule
      to override. No wildcards (ADR-0006 §Alternative 7 explicitly
      rejected wildcards — see the override of every cap with one
      typo failure mode).
    * ``--reason`` is required. Audit-trail data; CLI refuses to write
      an override without one because Pillar J's CI gate will demand
      it later anyway.
    * ``--approved-by`` is required. Same audit-trail rationale.
    * ``--person`` / ``--run`` populate ``scope.person_id`` /
      ``scope.run_id`` if given. Absent fields are omitted from the
      event (ADR-0006 §`manual_override` "scope absent = no scope
      constraint on this field").
    """
    # Required-field validation (argparse already catches missing args;
    # this is the parse-validation pass for the ones that have format
    # rules).
    try:
        expires = datetime.fromisoformat(args.until.replace("Z", "+00:00"))
    except ValueError as exc:
        print(
            f"ERROR: --until value {args.until!r} is not ISO-8601: {exc}",
            file=sys.stderr,
        )
        return 2
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    expires = expires.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)
    if expires <= now:
        # Allowing an override that's already expired is operationally
        # nonsensical — the budget rule's `_is_overridden` would
        # immediately ignore it. Block the write rather than silently
        # accept a no-op.
        print(
            f"ERROR: --until {expires.isoformat()} is not in the "
            f"future (now={now.isoformat()}). Override would be a "
            f"no-op; refusing to write.",
            file=sys.stderr,
        )
        return 2

    # Holistic-review P1-4: far-future --until sanity warning. Mirrors
    # the simulate --at warning shape (F4). An operator typing
    # `--until 2299-12-31` writes a quasi-permanent override; if that's
    # genuinely the intent, the warning is informational and the write
    # proceeds. If it's a typo, the warning catches it at 2am.
    if expires - now > timedelta(days=_AT_TIMETRAVEL_SANITY_DAYS):
        print(
            f"WARNING: --until {expires.isoformat()} is more than "
            f"{_AT_TIMETRAVEL_SANITY_DAYS} days in the future. "
            f"Common typo class: transposed century ('2299' vs "
            f"'2029') or extra digit. Proceeding with override as "
            f"written.",
            file=sys.stderr,
        )

    # Holistic-review P1-4: warn when --rule names a rule that isn't
    # in any loaded policy YAML. The override is still written (the
    # rule may not be deployed yet, or the operator may be staging an
    # override ahead of a rule that lands tomorrow), but the warning
    # catches the common typo class (`daily_apollo_cap` vs
    # `daily-apollo-cap`) before 2am audit confusion.
    known_rule_names = _collect_known_rule_names(args)
    if known_rule_names is not None and args.rule not in known_rule_names:
        print(
            f"WARNING: --rule {args.rule!r} does not match any rule "
            f"name in the loaded policy YAMLs. Known rules: "
            f"{sorted(known_rule_names)!r}. The override will still "
            f"be written (the rule may not be deployed yet), but if "
            f"this is a typo (common: dashes vs underscores) the "
            f"override will be a silent no-op.",
            file=sys.stderr,
        )

    # Build the event. Field order mirrors the ADR-0006 schema; we
    # also include `v: 1` explicitly so a future schema bump doesn't
    # rely on the Event dataclass's default.
    event: dict[str, Any] = {
        "v": 1,
        "type": "manual_override",
        "rule": args.rule,
        "expires_ts": expires.isoformat().replace("+00:00", "Z"),
        "reason": args.reason,
        "approved_by": args.approved_by,
    }
    scope: dict[str, str] = {}
    if args.person:
        scope["person_id"] = args.person
    if args.run:
        scope["run_id"] = args.run
    if scope:
        event["scope"] = scope

    # Append.
    ledger = _ledger.Ledger(_ledger_dir(args.ledger_dir))
    written = ledger.append(event)

    if args.json:
        print(json.dumps(written, indent=2))
    else:
        print(
            f"manual_override written:\n"
            f"  rule         : {written['rule']}\n"
            f"  expires_ts   : {written['expires_ts']}\n"
            f"  scope        : {written.get('scope') or '(unscoped)'}\n"
            f"  reason       : {written['reason']}\n"
            f"  approved_by  : {written['approved_by']}\n"
            f"  ts           : {written.get('ts')}"
        )
    return 0


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m orchestrator.policy",
        description=(
            "Policy engine CLI — simulate gate verdicts + write "
            "manual_override events. See docs/adr/0007-tier-rules-"
            "and-block-when-tier.md §Operator tooling."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # simulate
    sim = sub.add_parser(
        "simulate",
        help=(
            "Print every rule's verdict for a hypothetical send to a "
            "Person, optionally at a different UTC instant."
        ),
    )
    sim.add_argument(
        "--person", default=None,
        help=(
            "Person.id to simulate against. Requires --people-dir, "
            "OUTREACH_FACTORY_PEOPLE_DIR, or ~/.outreach-factory/"
            "config.yml vault.path. Use --person-note instead to "
            "bypass directory walking."
        ),
    )
    sim.add_argument(
        "--person-note", default=None,
        help="Path to a Person .md note (bypasses --person id lookup).",
    )
    sim.add_argument(
        "--people-dir", default=None,
        help="Override the directory walked for --person id lookup.",
    )
    sim.add_argument(
        "--register", required=True,
        help=(
            "Register to simulate (cold-pitch / follow-up / re-engage / "
            "reply / public-comment)."
        ),
    )
    sim.add_argument(
        "--channel", default="email",
        choices=["email", "linkedin", "twitter"],
        help="Channel to simulate. Defaults to email.",
    )
    sim.add_argument(
        "--at", default=None,
        help=(
            "ISO-8601 datetime to time-travel to. Naive = UTC. "
            "Defaults to now."
        ),
    )
    sim.add_argument(
        "--run-id", default=None,
        help=(
            "Run-id to populate on ctx.run_id. Required to exercise "
            "BudgetPerRunCapRule in simulation."
        ),
    )
    sim.add_argument(
        "--policies-dir", default=None,
        help=(
            "Override OUTREACH_FACTORY_POLICIES_DIR / "
            "~/.outreach-factory/policies/."
        ),
    )
    sim.add_argument(
        "--rules-file", default="cooldowns.yml",
        help=(
            "Filename within the policies directory to load. Defaults "
            "to cooldowns.yml (matches the production gate)."
        ),
    )
    sim.add_argument(
        "--ledger-dir", default=None,
        help=(
            "Override OUTREACH_FACTORY_LEDGER_DIR / "
            "~/.outreach-factory/ledger/."
        ),
    )
    sim.add_argument(
        "--json", action="store_true",
        help="Emit machine-parseable JSON instead of human-readable text.",
    )

    # override
    ov = sub.add_parser(
        "override",
        help=(
            "Write a validated manual_override event to the ledger. "
            "ADR-0006 schema."
        ),
    )
    ov.add_argument(
        "--rule", required=True,
        help="Exact name of the rule to override (no wildcards).",
    )
    ov.add_argument(
        "--until", required=True,
        help=(
            "ISO-8601 expiry datetime (naive = UTC). Override fires "
            "until this instant; at-expiry the cap is back in force."
        ),
    )
    ov.add_argument(
        "--reason", required=True,
        help="Human-readable justification for the audit trail.",
    )
    ov.add_argument(
        "--approved-by", required=True,
        help="User identifier of the approver (audit trail).",
    )
    ov.add_argument(
        "--person", default=None,
        help="Scope to a single person_id (optional).",
    )
    ov.add_argument(
        "--run", default=None,
        help="Scope to a single run_id (optional).",
    )
    ov.add_argument(
        "--ledger-dir", default=None,
        help=(
            "Override OUTREACH_FACTORY_LEDGER_DIR / "
            "~/.outreach-factory/ledger/."
        ),
    )
    ov.add_argument(
        "--policies-dir", default=None,
        help=(
            "Override OUTREACH_FACTORY_POLICIES_DIR / "
            "~/.outreach-factory/policies/. Used to warn when --rule "
            "names a rule that isn't in any loaded YAML (typo defense)."
        ),
    )
    ov.add_argument(
        "--json", action="store_true",
        help="Emit the written event as JSON to stdout.",
    )

    args = p.parse_args(argv)
    if args.cmd == "simulate":
        return _cmd_simulate(args)
    if args.cmd == "override":
        return _cmd_override(args)
    # argparse `required=True` on the subparsers already prevents this,
    # but mypy doesn't know that.
    print(f"ERROR: unknown subcommand {args.cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
