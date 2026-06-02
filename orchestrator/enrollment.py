"""Shared stub-writer for the outreach-factory discovery skills.

`/find-leads`, `/find-funded-founders`, and `/competitor-customers` all
discover prospects but historically only saved a Lead List (markdown
table). To get those prospects into the orchestrator pipeline a Person
note has to exist with `pipeline_stage: queued` set in its frontmatter.

This helper centralizes that stub-write so all three discovery skills
can shell out to it without duplicating dedup / path / frontmatter
logic.

Pipeline contract:
- Stub goes into `{vault.path}/{vault.people_dir}/{vault.queue_subdir}/`
- Frontmatter always includes `pipeline_stage: queued` and `type: person`
  (the dispatcher's vault scan filters on `type: person`)
- Dedup: **identity-graph** matching (Phase 5.5 Week 1b). The candidate's
  identifying keys (LinkedIn slug, email, GitHub, Twitter) are intersected
  against every existing Person note's `identity_keys`. Strict policy:
    0 matches  -> mint new ID, create stub
    1 match    -> return existing (skip)
    2+ matches -> Conflict, refuse to enroll, write report under
                  ~/.outreach-factory/conflicts/, return error
  Name-only collisions are no longer treated as matches at all — two
  distinct people can share a display name and identity is the gate.

CLI:

    python enrollment.py enroll --name <name> \\
                                [--linkedin <url>] [--email <addr> ...] \\
                                [--github <h>] [--twitter <h>] \\
                                [--alt-name <name> ...] \\
                                [--frontmatter @file.yml | "<yaml>"] \\
                                [--body @file.md | "<text>"] [--json]
    python enrollment.py check  --name <name> \\
                                [--linkedin <url>] [--email <addr> ...] \\
                                [--github <h>] [--twitter <h>] [--json]

The identity flags are first-class; if they're omitted, the helper will
also pull `linkedin`/`email`/`github`/`twitter` out of the
`--frontmatter` YAML payload as a back-compat fallback so existing
discovery-skill call sites keep working without a flag rename.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

import discovery_lineage as _dl
import identity
import ledger as _ledger
import state_machine
from discovery_lineage import DiscoveryLineage


# macOS APFS allows 255 bytes per path component; some Obsidian sync targets are
# stricter. Cap defensively — real founder names rarely exceed 60 chars; we
# leave headroom for `.md` and unicode multi-byte expansion.
MAX_FILENAME_BYTES = 200


def _load_config() -> dict:
    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _vault_paths(cfg: dict) -> tuple[Path | None, Path | None]:
    """Return (people_dir, queue_dir) — either may be None if unconfigured/missing."""
    v = cfg.get("vault") or {}
    vault_path = Path(os.path.expanduser(v.get("path") or ""))
    if not vault_path.exists():
        return None, None
    people_dir = vault_path / (v.get("people_dir") or "10 People")
    queue_dir = people_dir / (v.get("queue_subdir") or "🟦 Queue")
    return (people_dir if people_dir.exists() else None), queue_dir


def _conflicts_dir(cfg: dict) -> Path:
    """Resolve ~/.outreach-factory/conflicts/ — never inside the vault.

    Kept out of the Obsidian-synced tree so report files don't cause
    Obsidian Sync conflict-suffix duplication.
    """
    return Path.home() / ".outreach-factory" / "conflicts"


def _ledger_dir(cfg: dict) -> Path:
    """Resolve the ledger directory.

    Order: explicit env var > config-driven override > the global default.
    The env var is the test-harness escape hatch (set per-test to a
    tmp_path so a vault-creation test never pollutes the user's real
    ledger).
    """
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return _ledger.DEFAULT_LEDGER_DIR


def _open_ledger(cfg: dict) -> "_ledger.Ledger":
    """Best-effort ledger handle.

    Returns a Ledger pointing at the resolved directory. If the directory
    can't be created (rare; only on a read-only home), the caller is
    expected to handle the OSError on first append — we don't pre-validate
    here because enrollment shouldn't refuse to mint a stub just because
    the ledger storage is temporarily unhappy.
    """
    return _ledger.Ledger(_ledger_dir(cfg))


def _normalize_name(name: str) -> str:
    """Strip control chars + collapse whitespace. The canonical name written
    to frontmatter `name:` AND used as the basis for the filename. Run once
    at the top of `enroll_person` so both representations stay in sync."""
    s = re.sub(r"[\x00-\x1f]+", " ", name or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _safe_filename(name: str) -> str:
    """Vault-safe filename derived from an already-normalized name. Strips
    path separators + reserved chars, then caps at MAX_FILENAME_BYTES so we
    don't trigger an OSError on pathological LinkedIn display names."""
    s = re.sub(r"[\\/:\*\?\"<>\|]+", " ", name)
    s = re.sub(r"\s+", " ", s).strip() or "unnamed"
    encoded = s.encode("utf-8")
    if len(encoded) <= MAX_FILENAME_BYTES:
        return s
    truncated = encoded[:MAX_FILENAME_BYTES].decode("utf-8", errors="ignore").rstrip()
    return truncated or "unnamed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_company_slug(value) -> str | None:
    """Pull a slug out of a `company:` field that may be a wikilink or string."""
    if not value:
        return None
    if isinstance(value, str):
        m = re.match(r"\[\[([^\]]+)\]\]", value.strip())
        return (m.group(1) if m else value).strip() or None
    return None


def _identity_keys_from_inputs(
    name: str,
    linkedin: str | None,
    emails: list[str] | None,
    github: str | None,
    twitter: str | None,
    alt_names: list[str] | None,
    frontmatter: dict | None,
) -> identity.IdentityKeys:
    """Build IdentityKeys from explicit args, falling back to frontmatter fields.

    Explicit identity flags WIN over frontmatter values when both are
    provided — the caller's intent (the discovery skill knows what it
    scraped) is more trustworthy than YAML that may have been hand-edited.
    """
    fm = frontmatter or {}
    linkedin_in = linkedin or fm.get("linkedin")
    email_in: list[str] = []
    if emails:
        email_in.extend(emails)
    fm_email = fm.get("email")
    if isinstance(fm_email, str) and fm_email.strip():
        email_in.append(fm_email)
    elif isinstance(fm_email, list):
        email_in.extend(str(e) for e in fm_email if e)
    github_in = github or fm.get("github")
    twitter_in = twitter or fm.get("twitter")
    alt_in: list[str] = list(alt_names or [])
    return identity.compute_keys(
        name=name,
        emails=email_in or None,
        linkedin_url=linkedin_in,
        github=github_in,
        twitter=twitter_in,
        alt_names=alt_in or None,
    )


def _serialize_keys_block(keys: identity.IdentityKeys) -> dict:
    """Persist shape for the `identity_keys:` frontmatter block.

    Mirrors `IdentityKeys.to_serializable` but with stable key order and
    drops empty lists / None for tidier YAML.
    """
    block: dict = {}
    if keys.linkedin:
        block["linkedin"] = keys.linkedin
    if keys.emails:
        block["emails"] = sorted(keys.emails)
    if keys.github:
        block["github"] = keys.github
    if keys.twitter:
        block["twitter"] = keys.twitter
    if keys.alt_names:
        block["alt_names"] = sorted(keys.alt_names)
    return block


def enroll_person(
    name: str,
    frontmatter: dict | None = None,
    body: str = "",
    cfg: dict | None = None,
    *,
    linkedin: str | None = None,
    emails: list[str] | None = None,
    github: str | None = None,
    twitter: str | None = None,
    alt_names: list[str] | None = None,
    lineage: DiscoveryLineage | None = None,
) -> dict:
    """Create a `pipeline_stage: queued` Person note stub for `name`.

    Identity-aware dedup (Phase 5.5):
      - Computes IdentityKeys from explicit args + frontmatter fields.
      - Calls identity.find_matches against the vault.
      - resolve_strict applies the strict 0/1/2+ policy.

    Returns:
        {
            "ok": bool,
            "status": "created" | "exists" | "conflict" | "error",
            "path": str | None,
            "person_id": str | None,
            "report_path": str | None,   # only on status="conflict"
            "matched_classes": list[str] | None,  # only on status="exists"
            "reason": str,
        }

    "exists" is NOT an error — the discovery skill should treat it as a
    no-op. "conflict" means 2+ existing records match and manual
    resolution is required (or single-class-email match with distinct
    LinkedIn); discovery skills should aggregate the count and continue
    enrolling other prospects. "error" means the enrollment couldn't
    proceed (no vault, name empty, file collision).
    """
    name = _normalize_name(name)
    if not name:
        return {"ok": False, "status": "error", "path": None, "person_id": None,
                "report_path": None, "matched_classes": None,
                "reason": "name is empty"}

    cfg = cfg or _load_config()
    people_dir, queue_dir = _vault_paths(cfg)
    if people_dir is None:
        return {"ok": False, "status": "error", "path": None, "person_id": None,
                "report_path": None, "matched_classes": None,
                "reason": "vault.people_dir does not exist or is unreadable"}

    keys = _identity_keys_from_inputs(
        name=name, linkedin=linkedin, emails=emails, github=github,
        twitter=twitter, alt_names=alt_names, frontmatter=frontmatter,
    )

    matches = identity.find_matches(keys, people_dir)
    resolution = identity.resolve_strict(keys, matches, _conflicts_dir(cfg))

    # Source attribution for the ledger. Two paths:
    #
    # 1. Post-Pillar-E-Week-9-11 callers pass an explicit ``lineage``
    #    DiscoveryLineage instance. The four canonical fields stamp on
    #    every enrollment event (`source_skill` + `source_list` +
    #    `scraped_at` + `raw_input_hash`); the legacy ``source`` field
    #    also stamps (back-compat for existing consumers / tests).
    # 2. Pre-Pillar-E-Week-9-11 callers (no ``lineage`` kwarg) fall
    #    back to the legacy ``source_channel`` / ``source_list`` keys
    #    in the frontmatter payload. The ``source_skill`` field is
    #    derived via :func:`discovery_lineage.normalize_legacy_source_to_skill`
    #    so post-Week-9-11 consumers reading the field on these events
    #    get the canonical enum value without an inline-normalization
    #    burden.
    #
    # Per ADR-0036 D170 — the rename `enrolled.source` → `enrolled.source_skill`
    # is symmetric across all four enrollment-adjacent event classes
    # (`enrolled` + `enrollment_skipped_exists` + `enrollment_conflict`
    # + `needs_identity_upgrade`); the Week 1 P2-A pattern is extended.
    fm_in = frontmatter or {}
    if lineage is not None:
        source = lineage.source_skill
        source_skill = lineage.source_skill
        source_list = lineage.source_list
        lineage_scraped_at = lineage.scraped_at
        lineage_raw_input_hash = lineage.raw_input_hash
    else:
        legacy_source = fm_in.get("source_channel") or fm_in.get("source") or None
        source = legacy_source
        source_skill = _dl.normalize_legacy_source_to_skill(legacy_source) if legacy_source else None
        source_list = fm_in.get("source_list") or None
        lineage_scraped_at = None
        lineage_raw_input_hash = None
    led = _open_ledger(cfg)

    if isinstance(resolution, identity.Match):
        # Existing person; surface the match path + which key classes matched
        # so callers can log diagnostic info ("matched by LinkedIn" vs "by
        # email"). person_id may be empty for legacy pre-backfill notes; that
        # is fine — the caller still treats this as "exists".
        _safe_append(led, {
            "type": "enrollment_skipped_exists",
            "person_id": resolution.person_id or None,
            "note_path": str(resolution.note_path),
            "matched_classes": sorted(resolution.matched_classes),
            "candidate_name": name,
            "source": source,
            "source_skill": source_skill,
            "source_list": source_list,
        })
        return {
            "ok": True, "status": "exists",
            "path": str(resolution.note_path),
            "person_id": resolution.person_id or None,
            "report_path": None,
            "matched_classes": sorted(resolution.matched_classes),
            "reason": f"matched existing Person note via {','.join(sorted(resolution.matched_classes))}",
        }

    if isinstance(resolution, identity.Conflict):
        # 2+ matches OR ambiguous single-class email; refuse to enroll.
        _safe_append(led, {
            "type": "enrollment_conflict",
            "report_path": str(resolution.report_path),
            "match_count": len(resolution.matches),
            "matched_note_paths": [str(m.note_path) for m in resolution.matches],
            "candidate_name": name,
            "candidate_keys": keys.to_serializable(),
            "source": source,
            "source_skill": source_skill,
            "source_list": source_list,
        })
        return {
            "ok": False, "status": "conflict",
            "path": None, "person_id": None,
            "report_path": str(resolution.report_path),
            "matched_classes": None,
            "reason": (
                f"identity-graph conflict: {len(resolution.matches)} existing "
                f"record(s) match; manual resolution required"
            ),
        }

    # resolution is None -> mint ID and create the stub.
    if not queue_dir.exists():
        try:
            queue_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return {"ok": False, "status": "error", "path": None, "person_id": None,
                    "report_path": None, "matched_classes": None,
                    "reason": f"could not create queue dir {queue_dir}: {e}"}

    extras = dict(frontmatter or {})
    extras.pop("name", None)
    extras.pop("type", None)
    extras.pop("pipeline_stage", None)
    extras.pop("id", None)               # never accept caller-supplied id
    extras.pop("identity_keys", None)    # we own this block
    enrolled_at = extras.pop("pipeline_enrolled_at", _now_iso())

    company_slug = _coerce_company_slug(extras.get("company"))
    person_id = identity.mint_id(
        keys, name_fallback=name, company_slug=company_slug,
    )

    fm: dict = {"name": name, "type": "person", "id": person_id}
    identity_keys_block = _serialize_keys_block(keys)
    if identity_keys_block:
        # Per ADR-0036 D167 — the discovery_lineage sub-block lives
        # INSIDE identity_keys when the caller provides a validated
        # DiscoveryLineage. The four canonical fields stamp at
        # enrollment time per D169's "every NEW Person enrollment
        # carries the canonical block" invariant.
        if lineage is not None:
            identity_keys_block["discovery_lineage"] = (
                _dl.build_discovery_lineage_dict(lineage)
            )
        fm["identity_keys"] = identity_keys_block
        fm["identity_version"] = 1
    fm.update(extras)
    fm["pipeline_stage"] = "queued"
    fm["pipeline_enrolled_at"] = enrolled_at

    target = queue_dir / f"{_safe_filename(name)}.md"
    if target.exists():
        # Filename collision but identity-graph match said "no existing record" —
        # likely a different person sharing a sanitized name, or a stale stub
        # without parseable frontmatter. Don't overwrite blindly; pick a
        # disambiguated path. Suffix with the person_id short form to keep
        # collisions deterministic across re-runs.
        suffix_id = person_id.rsplit("-", 1)[0]   # strip the -li/-em/-tmp tag
        alt_name = f"{name} ({suffix_id})"
        target = queue_dir / f"{_safe_filename(alt_name)}.md"
        if target.exists():
            return {"ok": False, "status": "error", "path": str(target),
                    "person_id": person_id, "report_path": None,
                    "matched_classes": None,
                    "reason": f"file collision even after id-suffix at {target}"}

    fm_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    body_text = (body or f"# {name}\n").rstrip() + "\n"
    target.write_text(f"---\n{fm_yaml}\n---\n\n{body_text}", encoding="utf-8")
    # Ledger event: enrolled. Includes provenance (source/list) and a
    # needs_identity_upgrade flag for -tmp ids so the send-gate's reason
    # for blocking is recoverable from the funnel.
    #
    # Per ADR-0036 D170 — the rename `enrolled.source` → `enrolled.source_skill`
    # is implemented additively: both fields stamp on every new event
    # (back-compat for pre-Week-9-11 consumers reading `source`;
    # canonical for post-Week-9-11 consumers reading `source_skill`).
    # The full lineage sub-block (`scraped_at` + `raw_input_hash`)
    # stamps too when the caller provided a DiscoveryLineage.
    event_payload = {
        "type": "enrolled",
        "person_id": person_id,
        "note_path": str(target),
        "candidate_name": name,
        "identity_keys": keys.to_serializable(),
        "source": source,
        "source_skill": source_skill,
        "source_list": source_list,
    }
    if lineage_scraped_at is not None:
        event_payload["scraped_at"] = lineage_scraped_at
    if lineage_raw_input_hash is not None:
        event_payload["raw_input_hash"] = lineage_raw_input_hash
    _safe_append(led, event_payload)
    if identity.id_is_temporary(person_id):
        # Source attribution carried alongside the other enrollment-adjacent
        # events (enrolled / enrollment_skipped_exists / enrollment_conflict)
        # per the Pillar E Week 1 surface audit P2-A fix
        # (.planning/REVIEW-pillar-e-surface-audit.md §3). Pillar E Week 9-11
        # extends the symmetry with `source_skill` per ADR-0036 D170.
        _safe_append(led, {
            "type": "needs_identity_upgrade",
            "person_id": person_id,
            "note_path": str(target),
            "reason": "tmp_id_no_strong_key",
            "source": source,
            "source_skill": source_skill,
            "source_list": source_list,
        })
    return {"ok": True, "status": "created", "path": str(target),
            "person_id": person_id, "report_path": None,
            "matched_classes": None,
            "reason": f"enrolled at pipeline_stage: queued (id={person_id})"}


def _safe_append(led: "_ledger.Ledger", event: dict) -> None:
    """Best-effort ledger append.

    A ledger I/O failure must not block enrollment — the Person note has
    already been written to the vault by this point, and dropping the
    write would leave the system inconsistent in a worse way (vault says
    "exists", ledger says "never enrolled"). On failure we print a
    stderr warning so reconcile can later patch the gap from the vault
    snapshot, but we don't raise.
    """
    try:
        led.append(event)
    except (OSError, ValueError) as exc:
        print(f"WARNING: ledger append failed for {event.get('type')}: {exc}",
              file=sys.stderr)


def _read_arg(value: str | None) -> str | None:
    """Resolve `@path` to file contents; otherwise return value verbatim."""
    if value is None:
        return None
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def _add_identity_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--linkedin", default=None,
                   help="LinkedIn URL or slug; identity match key")
    p.add_argument("--email", action="append", default=None,
                   help="Email address; identity match key (repeatable)")
    p.add_argument("--github", default=None,
                   help="GitHub handle or URL; identity match key")
    p.add_argument("--twitter", default=None,
                   help="Twitter/X handle or URL; identity match key")
    p.add_argument("--alt-name", action="append", default=None,
                   dest="alt_names",
                   help="Additional display-name variants for conflict reports (repeatable)")


def _add_lineage_args(p: argparse.ArgumentParser) -> None:
    """Per ADR-0036 D169 — the four discovery-lineage flags.

    When all four are present (or auto-defaulted), the CLI constructs a
    :class:`DiscoveryLineage` instance + passes it as ``lineage`` to
    :func:`enroll_person`. When any flag is absent without an
    auto-default, the CLI falls back to the legacy frontmatter-driven
    path (back-compat for operators not yet updated to the lineage
    flags).
    """
    # Per Week 9-11 review P3-B — do NOT add `None` to choices list.
    # `default=None` covers the omitted-flag case; including None in
    # choices renders as `{find-leads,...,None}` in --help and error
    # messages, which is operator-confusing (operators may attempt
    # `--source-skill None` literal string, which argparse rejects).
    p.add_argument(
        "--source-skill", default=None,
        choices=sorted(_dl.SOURCE_SKILLS),
        help=("Discovery skill that surfaced the prospect. One of "
              f"{sorted(_dl.SOURCE_SKILLS)}. Required for the canonical "
              "discovery_lineage stamping per ADR-0036 D169."),
    )
    p.add_argument(
        "--source-list", default=None,
        help=("Operator-supplied list filename / tag (e.g., "
              "'[[2026-05-13-funded-founders]]'). Operator-private per "
              "ADR-0032 D148."),
    )
    p.add_argument(
        "--scraped-at", default=None,
        help=("ISO 8601 UTC timestamp at scraping time. Defaults to "
              "now-UTC if --source-skill is set."),
    )
    p.add_argument(
        "--raw-input-hash", default=None,
        help=("sha256:<64-hex> of the canonical raw input. Defaults to "
              "sha256(canonical-identity-keys) if --source-skill is set."),
    )


def _build_lineage_from_args(
    args: argparse.Namespace,
    keys: identity.IdentityKeys | None = None,
) -> DiscoveryLineage | None:
    """Construct a :class:`DiscoveryLineage` from CLI flags, or ``None``.

    Returns ``None`` when ``--source-skill`` is absent (back-compat
    legacy path). Auto-defaults the optional fields per D169:

    * ``--scraped-at`` defaults to now-UTC.
    * ``--raw-input-hash`` defaults to ``sha256(canonical-identity-keys)``
      derived from the candidate's identity_keys; falls back to
      ``sha256("manual:<name>")`` if no keys available.

    Raises ``ValueError`` via the dataclass constructor if any field
    violates D142's invariants.
    """
    if not args.source_skill:
        return None
    scraped_at = args.scraped_at or _now_iso()
    raw_input_hash = args.raw_input_hash
    if raw_input_hash is None:
        if keys is not None and not keys.is_empty():
            raw_input_hash = _dl.compute_canonical_raw_input_hash(
                json.dumps(keys.to_serializable(), sort_keys=True),
            )
        else:
            raw_input_hash = _dl.compute_canonical_raw_input_hash(
                f"manual:{args.name}",
            )
    source_list = args.source_list
    if not source_list:
        source_list = f"[[manual-{args.source_skill}]]"
    return DiscoveryLineage(
        source_skill=args.source_skill,
        source_list=source_list,
        scraped_at=scraped_at,
        raw_input_hash=raw_input_hash,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    en = sub.add_parser("enroll", help="Create a pipeline_stage: queued stub for one prospect")
    en.add_argument("--name", required=True)
    _add_identity_args(en)
    _add_lineage_args(en)
    en.add_argument("--frontmatter", default=None,
                    help='YAML string, or "@/path/to/frontmatter.yml"')
    en.add_argument("--body", default=None,
                    help='Markdown body, or "@/path/to/body.md"')
    en.add_argument("--json", action="store_true")

    ck = sub.add_parser("check", help="Report whether a Person note for this name/identity already exists")
    ck.add_argument("--name", required=True)
    _add_identity_args(ck)
    ck.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "enroll":
        fm_text = _read_arg(args.frontmatter)
        try:
            fm = yaml.safe_load(fm_text) if fm_text else None
        except yaml.YAMLError as e:
            print(json.dumps({"ok": False, "status": "error", "path": None,
                              "person_id": None, "report_path": None,
                              "matched_classes": None,
                              "reason": f"invalid YAML in --frontmatter: {e}"}))
            sys.exit(2)
        if fm is not None and not isinstance(fm, dict):
            print(json.dumps({"ok": False, "status": "error", "path": None,
                              "person_id": None, "report_path": None,
                              "matched_classes": None,
                              "reason": "--frontmatter must parse as a YAML mapping"}))
            sys.exit(2)
        body = _read_arg(args.body) or ""
        # Per ADR-0036 D169 — construct the DiscoveryLineage when
        # --source-skill is provided. We pre-compute the identity keys
        # here (mirroring the call site inside enroll_person) so the
        # auto-defaulted raw_input_hash is derived from the same shape.
        precomputed_keys = _identity_keys_from_inputs(
            name=args.name, linkedin=args.linkedin, emails=args.email,
            github=args.github, twitter=args.twitter,
            alt_names=args.alt_names, frontmatter=fm,
        )
        try:
            lineage = _build_lineage_from_args(args, keys=precomputed_keys)
        except ValueError as exc:
            print(json.dumps({"ok": False, "status": "error", "path": None,
                              "person_id": None, "report_path": None,
                              "matched_classes": None,
                              "reason": f"invalid lineage flags: {exc}"}))
            sys.exit(2)
        result = enroll_person(
            args.name, frontmatter=fm, body=body,
            linkedin=args.linkedin, emails=args.email,
            github=args.github, twitter=args.twitter,
            alt_names=args.alt_names,
            lineage=lineage,
        )
        if args.json:
            print(json.dumps(result))
        else:
            tag = {"created": "✅", "exists": "⏭ ",
                   "conflict": "⚠️ ", "error": "❌"}.get(result["status"], "?")
            print(f"{tag} {args.name}: {result['status']} — {result['reason']}")
            if result.get("path"):
                print(f"    {result['path']}")
            if result.get("report_path"):
                print(f"    conflict report: {result['report_path']}")
        sys.exit(0 if result["ok"] else 1)

    elif args.cmd == "check":
        cfg = _load_config()
        people_dir, _ = _vault_paths(cfg)
        if people_dir is None:
            result = {"ok": False, "exists": False, "path": None,
                      "person_id": None, "matched_classes": None,
                      "reason": "vault.people_dir does not exist or is unreadable"}
        else:
            keys = _identity_keys_from_inputs(
                name=args.name, linkedin=args.linkedin, emails=args.email,
                github=args.github, twitter=args.twitter, alt_names=args.alt_names,
                frontmatter=None,
            )
            matches = identity.find_matches(keys, people_dir) if not keys.is_empty() else []
            # Fall back to name-only lookup if no identity keys provided.
            if not matches and keys.is_empty():
                legacy = state_machine.find_person_note(args.name, cfg=cfg)
                if legacy:
                    result = {"ok": True, "exists": True,
                              "path": str(legacy), "person_id": None,
                              "matched_classes": [],
                              "reason": "name match (legacy fallback; no identity keys provided)"}
                else:
                    result = {"ok": True, "exists": False,
                              "path": None, "person_id": None,
                              "matched_classes": None, "reason": "not found"}
            elif not matches:
                result = {"ok": True, "exists": False,
                          "path": None, "person_id": None,
                          "matched_classes": None, "reason": "not found"}
            elif len(matches) == 1:
                m = matches[0]
                result = {"ok": True, "exists": True,
                          "path": str(m.note_path),
                          "person_id": m.person_id or None,
                          "matched_classes": sorted(m.matched_classes),
                          "reason": f"matched via {','.join(sorted(m.matched_classes))}"}
            else:
                result = {"ok": True, "exists": True, "conflict": True,
                          "path": None, "person_id": None,
                          "matched_classes": None,
                          "match_count": len(matches),
                          "reason": f"identity-graph conflict: {len(matches)} candidate matches"}
        if args.json:
            print(json.dumps(result))
        else:
            if result.get("conflict"):
                print(f"CONFLICT: {result['match_count']} matches — {result['reason']}")
            elif result["exists"]:
                print(f"exists: {result['path']}")
            else:
                print("(not found)")
        # Exit 0 = check ran successfully (regardless of found/not-found).
        # The `exists` field carries the boolean answer in JSON output. This
        # matches conventional CLI semantics so a Bash `if check...; then`
        # guard reflects whether the check itself worked, not the answer.
        sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
