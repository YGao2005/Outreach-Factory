"""Discovery-lineage primitive — per ADR-0032 D142 + ADR-0036.

The discovery-lineage primitive owns the canonical schema for tracking
WHICH discovery skill surfaced a prospect, WHICH operator-supplied list
the surface came from, WHEN the scrape landed, and WHAT the canonical
raw-input hash was (for dedup-of-scrapes + provenance audit).

Module surface
--------------

* :data:`SOURCE_SKILLS` — the closed-enum of discovery skill names. The
  canonical home (moved from ``discovery_dedup.py:96`` per ADR-0036 D167).
  Extending the enum requires a coordinated ADR amendment.

* :class:`DiscoveryLineage` — the frozen-dataclass shape per D142. Four
  required fields + construction-time validation via ``__post_init__``.

* :func:`build_discovery_lineage_dict` — render a
  :class:`DiscoveryLineage` as the canonical YAML-ready dict for
  Person frontmatter's ``identity_keys.discovery_lineage:`` sub-block
  + the ``enrolled`` event's denormalized payload.

* :func:`parse_discovery_lineage_dict` — inverse of
  :func:`build_discovery_lineage_dict`; round-trips through the
  validation surface.

* :data:`LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL` — the legacy ``source_channel``
  value → canonical ``source_skill`` mapping. The vault migration's
  backfill, the ledger migration's backfill, the tier primitive's
  legacy fallback, and any future consumer all share one source of
  truth for the mapping.

* :func:`normalize_legacy_source_to_skill` — map a legacy value via
  :data:`LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL`; unknown values + ``None``
  map to ``"manual"`` (the §Existing-operator seed floor).

* :func:`compute_canonical_raw_input_hash` — deterministic SHA256-prefixed
  hex of a canonical input. Used by discovery skills at stamping time +
  by the vault migration's backfill cascade.

* :func:`build_enrolled_source_skill_backfill_payload` — factory for the
  ledger migration's new event class (per D170 + ADR-0010 D14 append-only
  ledger discipline).

* :data:`EMITTED_BY` — operator-readable ``_emitted_by`` marker for any
  event the lineage primitive emits.

* :data:`CHANNEL_VALUE` — the channel-agnostic stamp value (``"none"``)
  per ADR-0014 D33 channel-on-every-event invariant.

CLI surface
-----------

::

    python -m orchestrator.discovery_lineage validate --source-skill <skill> \
        --source-list <list> --scraped-at <iso> --raw-input-hash <sha256:hex>

    python -m orchestrator.discovery_lineage backfill --person <id> \
        --source-skill <skill> [--source-list <list>]

The ``validate`` subcommand exercises the construction-time invariants
operator-readably. The ``backfill`` subcommand allows operators to
correct any per-Person mis-attribution surfaced by the vault migration's
fall-back-to-manual stderr summary.

See ADR-0036 for the design rationale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Per ADR-0032 D142 + ADR-0036 D167 — the canonical closed-set enum of
# discovery skills. Moved from ``discovery_dedup.py:96`` (Week 2's
# temporary reservation per ADR-0033's authoring note) to this module
# (the canonical owner of the lineage primitive). ``discovery_dedup.py``
# imports the name from here for back-compat with any consumer that
# references the dedup module's local re-export.
SOURCE_SKILLS: frozenset[str] = frozenset({
    "find-leads",
    "find-funded-founders",
    "competitor-customers",
    "research-prospect",
    "manual",
})


# Per ADR-0010 D17 — every Pillar E event carries an ``_emitted_by``
# marker for operator-facing filterability. The lineage primitive's
# marker is reserved for the ledger migration's new event class +
# any future event the primitive emits directly.
EMITTED_BY: str = "discovery_lineage"


# Per ADR-0036 D170 + ADR-0014 D33 — the lineage primitive's events
# carry ``channel: "none"`` because the lineage is channel-agnostic
# (mirrors the dedup primitive's stamp per ADR-0033 + the tier
# primitive's stamp per ADR-0035; contrasts with the cache primitive's
# ``channel: "email"`` per ADR-0034). A future Pillar G dashboard
# filtering by channel would silently exclude lineage events if the
# field were absent; the explicit ``"none"`` value makes the absence
# operator-visible.
CHANNEL_VALUE: str = "none"


# The legacy ``source_channel`` value → canonical ``source_skill``
# mapping per ADR-0036 D167. The mapping is the rename trajectory:
# pre-Pillar-E-Week-9-11 Person notes carry ``source_channel: <legacy>``;
# the normalization makes them readable as canonical ``source_skill``
# without rewriting the legacy field.
#
# Unknown values + ``None`` map to ``"manual"`` (the §Existing-operator
# seed floor) per :func:`normalize_legacy_source_to_skill`.
LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL: dict[str, str] = {
    # Canonical mappings — the legacy field's shortened naming.
    "find-leads": "find-leads",
    "funded-founders": "find-funded-founders",
    "competitor-customers": "competitor-customers",
    "research-prospect": "research-prospect",
    # Permissive — operator-typed variants (the legacy ``source_channel:``
    # field is operator-supplied; some operators have written the canonical
    # form already).
    "find-funded-founders": "find-funded-founders",
    "manual": "manual",
}


# The ledger migration's new event class type name (per ADR-0036 D170).
# Carries the renamed ``source_skill`` field paired with the original
# ``enrolled`` event's ``ts`` via ``_backfill_of_ts``.
BACKFILL_EVENT_TYPE: str = "enrolled_source_skill_backfill"


# SHA256 hex length — used by :func:`_is_sha256_prefixed` for validation.
_SHA256_HEX_LEN: int = 64


# Per ADR-0032 D142 — ISO 8601 UTC timestamp shape. Accepted:
#   * ``YYYY-MM-DDTHH:MM:SSZ`` (the canonical form discovery skills emit)
#   * ``YYYY-MM-DDTHH:MM:SS.fffZ`` (fractional seconds)
#   * ``YYYY-MM-DDTHH:MM:SS+00:00`` (explicit UTC offset)
# Rejected:
#   * Naive timestamps (no Z or offset)
#   * Non-UTC offsets (the canonical form is UTC; mixed-timezone
#     persisted timestamps create downstream confusion)
_ISO_8601_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$",
)


# ---------------------------------------------------------------------------
# Private validators
# ---------------------------------------------------------------------------


def _is_iso8601_utc(value: object) -> bool:
    """True if ``value`` is a non-empty string matching ISO 8601 UTC shape.

    See :data:`_ISO_8601_UTC_RE` for the accepted forms.
    """
    return isinstance(value, str) and bool(_ISO_8601_UTC_RE.match(value))


def _is_sha256_prefixed(value: object) -> bool:
    """True if ``value`` is ``"sha256:<64-hex>"`` per ADR-0032 D142.

    The 64-hex-char tail is the canonical SHA256 hex digest. Both
    upper-case + lower-case hex are accepted (the canonical form is
    lower-case; the validator is tolerant).
    """
    if not isinstance(value, str):
        return False
    if not value.startswith("sha256:"):
        return False
    tail = value[len("sha256:"):]
    if len(tail) != _SHA256_HEX_LEN:
        return False
    try:
        int(tail, 16)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# DiscoveryLineage dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryLineage:
    """The provenance of a Person enrollment per ADR-0032 D142.

    Frozen + construction-time-validated. The four required fields
    capture WHICH discovery skill surfaced the prospect, WHICH
    operator-supplied list the surface came from, WHEN the scrape
    landed, and WHAT the canonical raw-input hash was (for
    dedup-of-scrapes + provenance audit).

    Constructed at the discovery skill's enrollment site; serialized
    via :func:`build_discovery_lineage_dict` into the Person
    frontmatter's ``identity_keys.discovery_lineage:`` sub-block +
    denormalized into the emitted ``enrolled`` event's
    ``source_skill`` / ``source_list`` / ``scraped_at`` /
    ``raw_input_hash`` fields per ADR-0036 D170.

    Construction-time invariants:

    * :attr:`source_skill` MUST be one of :data:`SOURCE_SKILLS` —
      ``ValueError`` on unknown values (refuse-loud per D167).
    * :attr:`source_list` MUST be a non-empty string —
      ``ValueError`` on empty / whitespace-only values.
    * :attr:`scraped_at` MUST be an ISO 8601 UTC timestamp matching
      ``YYYY-MM-DDTHH:MM:SSZ`` (or fractional seconds, or ``+00:00``
      offset) — ``ValueError`` on shape violations. Naive timestamps
      are rejected.
    * :attr:`raw_input_hash` MUST be ``"sha256:<64-hex>"`` —
      ``ValueError`` on prefix mismatch or wrong-length hex.

    Operator-private posture for :attr:`source_list` per ADR-0032
    D148 — the framework treats the field as an opaque string +
    Pillar G dashboards filter on :attr:`source_skill` but NEVER
    on :attr:`source_list`.

    The dataclass is frozen + hashable so a single instance can be
    passed across the discovery-skill + enrollment + event-payload-
    factory boundary without copying.
    """

    source_skill: str
    source_list: str
    scraped_at: str
    raw_input_hash: str

    def __post_init__(self) -> None:
        if self.source_skill not in SOURCE_SKILLS:
            raise ValueError(
                f"source_skill {self.source_skill!r} not in "
                f"SOURCE_SKILLS {sorted(SOURCE_SKILLS)!r}; per "
                f"ADR-0032 D142 the enum is closed-set + "
                f"construction-time-validated. To add a new skill, "
                f"amend SOURCE_SKILLS in orchestrator/discovery_lineage.py "
                f"+ coordinate an ADR amendment (per ADR-0036 D167)."
            )
        if not (
            isinstance(self.source_list, str)
            and self.source_list.strip()
        ):
            raise ValueError(
                f"source_list must be a non-empty string per "
                f"ADR-0032 D142; got {self.source_list!r}"
            )
        if not _is_iso8601_utc(self.scraped_at):
            raise ValueError(
                f"scraped_at must be ISO 8601 UTC "
                f"(YYYY-MM-DDTHH:MM:SSZ or fractional / +00:00) per "
                f"ADR-0032 D142; got {self.scraped_at!r}"
            )
        if not _is_sha256_prefixed(self.raw_input_hash):
            raise ValueError(
                f"raw_input_hash must be 'sha256:<64-hex>' per "
                f"ADR-0032 D142; got {self.raw_input_hash!r}"
            )


# ---------------------------------------------------------------------------
# Frontmatter serialization factories
# ---------------------------------------------------------------------------


def build_discovery_lineage_dict(lineage: DiscoveryLineage) -> dict:
    """Render a :class:`DiscoveryLineage` as the canonical YAML-ready dict.

    The output is the exact shape that goes into the Person
    frontmatter's ``identity_keys.discovery_lineage:`` sub-block +
    the ``enrolled`` event's denormalized ``discovery_lineage:``
    field. Key order matches the D142 schema (source_skill +
    source_list + scraped_at + raw_input_hash) for operator-readable
    YAML ordering.

    Raises
    ------
    TypeError:
        If ``lineage`` is not a :class:`DiscoveryLineage` instance —
        the caller is expected to pass a validated dataclass instance,
        not an unvalidated dict.
    """
    if not isinstance(lineage, DiscoveryLineage):
        raise TypeError(
            f"build_discovery_lineage_dict expects a DiscoveryLineage; "
            f"got {type(lineage).__name__}. Construct one via "
            f"DiscoveryLineage(source_skill=, source_list=, scraped_at=, "
            f"raw_input_hash=) — the construction-time validation is "
            f"load-bearing per ADR-0036 D167."
        )
    return {
        "source_skill": lineage.source_skill,
        "source_list": lineage.source_list,
        "scraped_at": lineage.scraped_at,
        "raw_input_hash": lineage.raw_input_hash,
    }


def parse_discovery_lineage_dict(
    block: dict | None,
) -> DiscoveryLineage | None:
    """Parse a frontmatter sub-block (or `enrolled` event payload)
    back into a :class:`DiscoveryLineage` instance.

    Returns ``None`` when ``block`` is ``None`` (the lineage is
    absent on legacy Person notes; the caller decides how to handle).
    Raises ``ValueError`` via the dataclass's ``__post_init__`` if
    any field violates D142's invariants.

    Tolerant of:

    * Missing optional fields → ``ValueError`` (every field is
      required per D142).
    * Extra fields → silently ignored (future Pillar E weeks MAY
      extend the schema; the parser is forward-compatible).

    Raises
    ------
    ValueError:
        Propagated from :meth:`DiscoveryLineage.__post_init__` if
        any field is invalid; raised directly if ``block`` is not
        a dict.
    """
    if block is None:
        return None
    if not isinstance(block, dict):
        raise ValueError(
            f"discovery_lineage block must be a dict; got "
            f"{type(block).__name__}"
        )
    return DiscoveryLineage(
        source_skill=block.get("source_skill"),
        source_list=block.get("source_list"),
        scraped_at=block.get("scraped_at"),
        raw_input_hash=block.get("raw_input_hash"),
    )


# ---------------------------------------------------------------------------
# Legacy normalization
# ---------------------------------------------------------------------------


def normalize_legacy_source_to_skill(value: str | None) -> str:
    """Map a legacy ``source_channel`` value to a canonical
    ``source_skill`` enum value.

    Unknown values + ``None`` + empty strings map to ``"manual"`` —
    the §Existing-operator seed floor. The mapping IS the rename
    trajectory per ADR-0036 D167 — pre-Pillar-E-Week-9-11 Person
    notes carry ``source_channel: <legacy>``; the normalization
    makes them readable as canonical ``source_skill`` without
    rewriting the legacy field.

    Centralizes the legacy-value drift so the vault migration's
    backfill (vault/0005), the ledger migration's backfill
    (ledger/0007), the tier primitive's legacy fallback path
    (per ADR-0035 D162), and any future consumer all share one
    source of truth.
    """
    if not value:
        return "manual"
    return LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL.get(value, "manual")


# ---------------------------------------------------------------------------
# Canonical raw-input hash
# ---------------------------------------------------------------------------


def compute_canonical_raw_input_hash(canonical_input: str | bytes) -> str:
    """Compute the SHA256-prefixed hex of a canonical raw input.

    Discovery skills compute the hash at stamping time from their
    own canonical-input shape (e.g., the candidate's name + linkedin
    URL + the scrape source URL — per-skill canonicalization). The
    helper centralizes the prefix convention so every emitted
    ``raw_input_hash`` matches the D142 shape exactly.

    Used by:

    * Discovery skills at stamping time (NEW enrollments).
    * The vault migration's backfill cascade (per ADR-0036 D168).
    * The ledger migration's backfill emission (per ADR-0036 D170).

    The canonical-input shape MUST be deterministic per the skill —
    e.g., if the same candidate is re-scraped twice, the canonical
    input MUST produce the same hash. Per-skill canonicalization is
    a Pillar I doctrine (each skill's CLI documents its
    canonicalization).

    Parameters
    ----------
    canonical_input:
        The canonical raw input as either a str (UTF-8-encoded
        before hashing) or bytes (hashed directly).

    Returns
    -------
    str:
        ``"sha256:<64-lower-hex>"`` matching D142's shape exactly.
    """
    if isinstance(canonical_input, str):
        canonical_input = canonical_input.encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical_input).hexdigest()


# ---------------------------------------------------------------------------
# Ledger migration backfill event factory
# ---------------------------------------------------------------------------


def build_enrolled_source_skill_backfill_payload(
    *,
    person_id: str,
    source_skill: str,
    backfill_of_ts: str,
    migration_id: str,
) -> dict:
    """Build the ``enrolled_source_skill_backfill`` event payload per
    ADR-0036 D170.

    The ledger migration `ledger/0007` walks every historical
    `enrolled` event lacking `source_skill`, normalizes the legacy
    `enrolled.source` value via :func:`normalize_legacy_source_to_skill`,
    appends a backfill event carrying the normalized value paired
    with the original event's `ts`.

    Consumers reading `source_skill` for a Person walk the ledger:

    1. Find the latest `enrolled` event for ``person_id``.
    2. If ``event["source_skill"]`` is present (post-Week-9-11), use it.
    3. Else look for an ``enrolled_source_skill_backfill`` event with
       ``_backfill_of_ts == event["ts"]`` (the migration's backfill).
    4. Else inline-normalize ``event["source"]`` via
       :func:`normalize_legacy_source_to_skill`.

    The new event class carries ``channel: "none"`` per the
    channel-on-every-event invariant + ``_emitted_by:
    "discovery_lineage"`` per the operator-readable marker convention.

    Parameters
    ----------
    person_id:
        The Person whose backfill event this is — matches the
        original ``enrolled.person_id``.
    source_skill:
        The canonical enum value — MUST be one of :data:`SOURCE_SKILLS`.
        Construction-time validated.
    backfill_of_ts:
        The original ``enrolled`` event's ``ts`` — the pairing key
        that lets consumers join the backfill back to the source.
    migration_id:
        The ledger migration's ``id`` — typically
        ``"0007_backfill_enrolled_source_skill"``. Stamped on the
        ``_recovered_by`` field so operators can grep for the
        migration's effects.

    Returns
    -------
    dict:
        Event payload ready to append to the ledger.

    Raises
    ------
    ValueError:
        If ``source_skill`` is not in :data:`SOURCE_SKILLS`; if
        ``person_id`` is empty; if ``backfill_of_ts`` is not ISO
        8601 UTC.
    """
    if source_skill not in SOURCE_SKILLS:
        raise ValueError(
            f"source_skill {source_skill!r} not in SOURCE_SKILLS "
            f"{sorted(SOURCE_SKILLS)!r} per ADR-0032 D142"
        )
    if not (isinstance(person_id, str) and person_id.strip()):
        raise ValueError(
            f"person_id must be a non-empty string; got {person_id!r}"
        )
    if not _is_iso8601_utc(backfill_of_ts):
        raise ValueError(
            f"backfill_of_ts must be ISO 8601 UTC; got "
            f"{backfill_of_ts!r}"
        )
    if not (isinstance(migration_id, str) and migration_id.strip()):
        raise ValueError(
            f"migration_id must be a non-empty string; got "
            f"{migration_id!r}"
        )
    return {
        "type": BACKFILL_EVENT_TYPE,
        "person_id": person_id,
        "source_skill": source_skill,
        "_backfill_of_ts": backfill_of_ts,
        "_recovered_by": f"migration_{migration_id}",
        "channel": CHANNEL_VALUE,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# Per-Person backfill helper (operator surface)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC now as ``YYYY-MM-DDTHH:MM:SSZ``. Centralized for testability."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_person_note(
    person_id: str,
    people_dir: Path,
) -> Path | None:
    """Locate a Person note in ``people_dir`` by ``id:`` frontmatter field.

    Walks every ``*.md`` file recursively + parses the frontmatter
    via ``yaml.safe_load``. Returns the first match (canonically
    there should be exactly one — the operator's vault is single-
    source-of-truth per I3). Returns ``None`` if no match found.

    Used by the ``backfill`` CLI subcommand to stamp the lineage
    block on a per-Person override.
    """
    import yaml

    for note in sorted(people_dir.rglob("*.md")):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end == -1:
            continue
        try:
            fm = yaml.safe_load(text[4:end])
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        if fm.get("id") == person_id:
            return note
    return None


def _load_config() -> dict:
    """Load the operator's ``~/.outreach-factory/config.yml`` for the CLI."""
    import yaml

    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _people_dir_from_cfg(cfg: dict) -> Path | None:
    """Resolve the vault's People dir per the operator's config."""
    import os

    v = cfg.get("vault") or {}
    vault_path = Path(os.path.expanduser(v.get("path") or ""))
    if not vault_path.exists():
        return None
    people_dir = vault_path / (v.get("people_dir") or "10 People")
    return people_dir if people_dir.exists() else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_validate(args: argparse.Namespace) -> int:
    """``validate`` subcommand — exercise the construction-time invariants."""
    try:
        lineage = DiscoveryLineage(
            source_skill=args.source_skill,
            source_list=args.source_list,
            scraped_at=args.scraped_at,
            raw_input_hash=args.raw_input_hash,
        )
    except ValueError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "lineage": build_discovery_lineage_dict(lineage)}))
    else:
        print(f"VALID: {build_discovery_lineage_dict(lineage)}")
    return 0


def _cli_backfill(args: argparse.Namespace) -> int:
    """``backfill`` subcommand — per-Person operator override of source_skill.

    Stamps the ``identity_keys.discovery_lineage:`` sub-block on the
    named Person note using the operator-supplied ``--source-skill``.
    The ``--source-list`` defaults to ``[[legacy-{source_skill}]]``
    (the conventional manual-attribution tag); the ``--scraped-at``
    defaults to now-UTC; the ``--raw-input-hash`` defaults to
    ``sha256(manual:<person_id>)`` (deterministic per-Person
    fingerprint).

    Operator workflow per ADR-0036 §Existing-operator seed:

    1. Run ``python -m orchestrator.migrations doctor apply`` —
       apply vault/0005 (the bulk backfill).
    2. Review the migration's stderr summary — note the count of
       fall-back-to-manual Persons.
    3. For each Person whose ``source_skill`` should be a non-manual
       value, run this backfill subcommand.
    """
    # Import lazily so the CLI doesn't pull in the _vault_io substrate
    # unless backfill is actually invoked.
    from orchestrator.migrations.vault._vault_io import (  # noqa: E402
        extend_frontmatter_nested_block_text,
        read_person_frontmatter,
        write_person_frontmatter_atomic,
    )

    cfg = _load_config()
    people_dir = _people_dir_from_cfg(cfg)
    if people_dir is None:
        print("ERROR: vault.people_dir does not exist or is unreadable",
              file=sys.stderr)
        return 2

    note_path = _find_person_note(args.person, people_dir)
    if note_path is None:
        print(f"ERROR: no Person note found with id={args.person!r} under "
              f"{people_dir}", file=sys.stderr)
        return 1

    source_list = args.source_list or f"[[legacy-{args.source_skill}]]"
    scraped_at = args.scraped_at or _now_iso()
    raw_input_hash = args.raw_input_hash or compute_canonical_raw_input_hash(
        f"manual:{args.person}",
    )

    try:
        lineage = DiscoveryLineage(
            source_skill=args.source_skill,
            source_list=source_list,
            scraped_at=scraped_at,
            raw_input_hash=raw_input_hash,
        )
    except ValueError as exc:
        print(f"ERROR: invalid lineage: {exc}", file=sys.stderr)
        return 1

    fm, _body = read_person_frontmatter(note_path)
    if not isinstance(fm, dict) or "identity_keys" not in fm:
        print(f"ERROR: {note_path} has no identity_keys block; cannot "
              f"stamp the discovery_lineage sub-block. Run the standard "
              f"enrollment path first.", file=sys.stderr)
        return 1

    existing_keys = fm.get("identity_keys")
    if isinstance(existing_keys, dict) and "discovery_lineage" in existing_keys:
        print(f"NOTE: {note_path} already carries discovery_lineage; the "
              f"backfill CLI does not overwrite. Edit the Person note "
              f"directly to update.", file=sys.stderr)
        return 1

    text = note_path.read_text(encoding="utf-8")
    new_text = extend_frontmatter_nested_block_text(
        text,
        parent_key="identity_keys",
        child_key="discovery_lineage",
        child_block=build_discovery_lineage_dict(lineage),
    )
    write_person_frontmatter_atomic(note_path, new_text)
    print(f"OK: stamped discovery_lineage on {note_path}: "
          f"{build_discovery_lineage_dict(lineage)}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m orchestrator.discovery_lineage",
        description=(
            "Discovery-lineage primitive operator surface per ADR-0036. "
            "Validate a lineage payload or backfill a per-Person override."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    val = sub.add_parser(
        "validate",
        help="Exercise the construction-time invariants on a lineage payload.",
    )
    val.add_argument("--source-skill", required=True,
                     help=f"One of {sorted(SOURCE_SKILLS)}")
    val.add_argument("--source-list", required=True,
                     help="The operator-supplied list tag (operator-private per D148)")
    val.add_argument("--scraped-at", required=True,
                     help="ISO 8601 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)")
    val.add_argument("--raw-input-hash", required=True,
                     help="sha256:<64-hex> per D142")
    val.add_argument("--json", action="store_true")

    bf = sub.add_parser(
        "backfill",
        help=(
            "Stamp identity_keys.discovery_lineage on a Person note "
            "(operator override of the vault migration's fall-back-to-manual)."
        ),
    )
    bf.add_argument("--person", required=True,
                    help="Person id (matches frontmatter id: field)")
    bf.add_argument("--source-skill", required=True,
                    help=f"One of {sorted(SOURCE_SKILLS)}")
    bf.add_argument("--source-list", default=None,
                    help=("Operator-supplied list tag. Defaults to "
                          "[[legacy-{source_skill}]]."))
    bf.add_argument("--scraped-at", default=None,
                    help="ISO 8601 UTC timestamp. Defaults to now-UTC.")
    bf.add_argument("--raw-input-hash", default=None,
                    help=("sha256:<64-hex>. Defaults to "
                          "sha256(manual:<person_id>)."))

    args = p.parse_args(list(argv) if argv is not None else None)
    if args.cmd == "validate":
        return _cli_validate(args)
    elif args.cmd == "backfill":
        return _cli_backfill(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "BACKFILL_EVENT_TYPE",
    "CHANNEL_VALUE",
    "DiscoveryLineage",
    "EMITTED_BY",
    "LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL",
    "SOURCE_SKILLS",
    "build_discovery_lineage_dict",
    "build_enrolled_source_skill_backfill_payload",
    "compute_canonical_raw_input_hash",
    "normalize_legacy_source_to_skill",
    "parse_discovery_lineage_dict",
]
