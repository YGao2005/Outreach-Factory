"""Vault migration 0005 — add ``identity_keys.discovery_lineage:`` sub-block to Person notes.

Pillar E Week 9-11 vault migration. Per ADR-0036 D168, the migration
stamps the canonical four-field ``discovery_lineage:`` sub-block on
every pre-Week-9-11 Person note with an existing ``identity_keys:``
block. The sub-block carries the per-prospect provenance:

* ``source_skill``  — which discovery skill surfaced the prospect
  (closed-enum per ADR-0032 D142)
* ``source_list``   — the operator-supplied list filename / tag
  (operator-private per ADR-0032 D148)
* ``scraped_at``    — ISO 8601 UTC scrape timestamp
* ``raw_input_hash`` — SHA256-prefixed hex of the canonical raw input

Backfill cascade (per ADR-0036 D168)
------------------------------------

The migration's backfill strategy walks the Person note + its sibling
files + the ledger to derive each lineage field. The cascade order
prefers richer provenance:

1. **``_source.md`` sibling file** (if present + parseable). The
   operator's curated lead-list metadata; carries the original scrape
   URL + the canonical timestamp + the list filename.
2. **``source_channel:`` Person frontmatter field**. The discovery
   skills' legacy field — present on most post-Phase-5.5 enrollments.
   Normalized via :func:`orchestrator.discovery_lineage.normalize_legacy_source_to_skill`.
3. **Ledger ``enrolled.source`` field**. The denormalized provenance —
   present on every Person enrolled since Phase 5.5 Week 2 (when the
   ``source`` field was added to the ``enrolled`` event). Resilient to
   operator hand-edits of the Person frontmatter.
4. **``source_skill: manual`` floor**. The §Existing-operator seed
   floor — every pre-Week-9-11 Person without parseable provenance
   gets the manual default.

Per-field cascade rules
-----------------------

| Source | source_skill | source_list | scraped_at | raw_input_hash |
|---|---|---|---|---|
| _source.md | parsed | parsed | parsed or mtime | parsed or sha256(text) |
| source_channel: | normalized | fm.source_list or [[legacy-{skill}]] | fm.created or mtime | sha256(canonical fm) |
| ledger enrolled.source | normalized | event.source_list or [[legacy-{skill}]] | event.ts | sha256(canonical event) |
| manual floor | "manual" | [[legacy-manual]] | apply-time UTC | sha256(manual:{person_id}) |

Operator-visible stderr summary
-------------------------------

At apply time the migration logs the per-source backfill count + the
count that fell to manual:

::

    INFO 0005_add_discovery_lineage_to_identity_keys: stamping discovery_lineage
    INFO   from _source.md (high-confidence): 12 Persons
    INFO   from source_channel: (medium-confidence): 287 Persons
    INFO   from ledger enrolled.source (medium-confidence): 31 Persons
    INFO   fallback to source_skill: manual (low-confidence): 18 Persons
    INFO total: 348 Persons stamped; 0 skipped (no identity_keys block); 0 errored
    WARNING 18 Persons fell to source_skill: manual. Review with:
    WARNING   python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>
    WARNING for any Person whose source_skill should be a non-manual value.

The fall-back-to-manual surface is the R022 mitigation per ADR-0036
§Risks; operators correct any per-Person mis-attribution via the
:mod:`orchestrator.discovery_lineage` CLI.

Contract
--------

* **Idempotent.** Person notes already carrying
  ``identity_keys.discovery_lineage`` are silently skipped (the
  helper's ``FrontmatterError`` on duplicate-child is caught + logged
  as no-op).

* **Reversible.** :meth:`downgrade` removes the sub-block via
  :func:`._vault_io.remove_frontmatter_nested_field_text`.

* **Per-file atomic.** Each note's rewrite goes through
  :func:`._vault_io.write_person_frontmatter_atomic` — tmp-then-rename
  with ``fsync``.

* **Refuses on missing vault.** ``ctx.vault_dir is None`` raises
  ``ValueError`` before any file is touched.

* **Tolerates missing ledger.** ``ctx.ledger_dir is None`` is OK — the
  cascade skips step 3 (ledger fallback) and proceeds to manual.

* **Refuses-loud on the construction-time invariants.** If a derived
  lineage value violates :class:`DiscoveryLineage`'s contract (e.g., a
  legacy ``source_channel`` that normalizes to an unknown skill), the
  migration logs the Person's path + raises — the runner does NOT mark
  the migration applied (per ADR-0009 D4 atomicity contract).

Non-Person files (sub-notes, drafts) are silently skipped via
``is_person_note``. People notes with no ``identity_keys:`` block are
silently skipped (the migration can't insert a nested sub-block under
an absent parent; pre-Phase-5.5 notes without ``identity_keys`` need
the operator's hand-stamping first).

See ADR-0036 D168 for the design rationale + the per-source cascade +
the operator-correctable surface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._vault_io import (
    FrontmatterError,
    extend_frontmatter_nested_block_text,
    is_person_note,
    iter_person_notes,
    read_person_frontmatter,
    remove_frontmatter_nested_field_text,
    write_person_frontmatter_atomic,
)


MIGRATION_ID = "0005_add_discovery_lineage_to_identity_keys"


# Obsidian Sync concurrency warning — printed at upgrade/downgrade
# start regardless of dry_run, so operators see it BEFORE deciding
# to apply. Mirrors vault/0001-0004's convention.
_OBSIDIAN_SYNC_WARNING = (
    "WARNING: vault migration about to rewrite Person notes "
    "(identity_keys.discovery_lineage). If Obsidian Sync is uploading "
    "concurrent edits, merge conflicts may appear as .conflicted.md "
    "files in your vault. Quit Obsidian before running apply, or "
    "accept the rare conflict-recovery cost."
)


def _import_runtime_helpers():
    """Lazy-load orchestrator.discovery_lineage + orchestrator.ledger.

    The runtime modules live at the orchestrator/ top-level. Migrations
    are inside a subpackage so we go through the package import path
    to keep test isolation clean.
    """
    from orchestrator import discovery_lineage as _dl
    from orchestrator import ledger as _led
    return _dl, _led


def _canonical_yaml_bytes(value: Any) -> bytes:
    """Deterministic YAML serialization for fingerprinting.

    ``sort_keys=True`` so insertion-order variation doesn't change the
    fingerprint; ``default_flow_style=False`` for block-style YAML.
    """
    return yaml.safe_dump(
        value,
        sort_keys=True,
        default_flow_style=False,
    ).encode("utf-8")


def _file_mtime_iso(path: Path) -> str:
    """Return the file's mtime as ISO 8601 UTC."""
    from datetime import datetime, timezone
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )


def _now_iso() -> str:
    """UTC now as ``YYYY-MM-DDTHH:MM:SSZ``."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _BackfillResult:
    """One Person note's backfill outcome — what source was used + values."""
    person_id: str
    note_path: Path
    source: str  # one of "_source.md", "source_channel", "ledger", "manual"
    lineage_dict: dict


def _try_source_md_file(note: Path, people_dir: Path | None = None) -> dict | None:
    """Look for a sibling ``_source.md`` file + parse its frontmatter.

    Returns a dict of ``{source_skill, source_list, scraped_at,
    raw_input_hash}`` if parseable + all four fields present; ``None``
    otherwise.

    The ``_source.md`` convention is operator-curated lead-list
    metadata — operators MAY maintain a per-list file describing the
    scrape provenance. The file lives alongside the Person note (same
    parent dir or one of its ancestors up to the People dir).

    Per Week 9-11 review P3-A — the traversal STOPS at ``people_dir``
    (when provided) so a `_source.md` at the vault root cannot pollute
    every Person note's attribution via the cascade's silent ancestor
    walk. When ``people_dir`` is None (legacy callers; defensive
    fallback), the traversal walks up to 3 levels capped at the
    filesystem root.
    """
    import re

    candidates: list[Path] = []
    # Look in note's parent + ancestors up to People dir (per P3-A).
    parent = note.parent
    for _ in range(3):
        candidates.append(parent / "_source.md")
        # P3-A bound: stop at the People dir; do NOT walk above it
        # (a vault-root `_source.md` would pollute every Person note).
        if people_dir is not None and parent == people_dir:
            break
        if parent.parent == parent:  # filesystem root
            break
        parent = parent.parent

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
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
        skill = fm.get("source_skill")
        sl = fm.get("source_list")
        if not (skill and sl):
            continue
        # If the _source.md has scraped_at + raw_input_hash, use them;
        # else derive defensible defaults.
        scraped_at = fm.get("scraped_at") or _file_mtime_iso(candidate)
        raw_hash = fm.get("raw_input_hash")
        if not raw_hash:
            # Hash the _source.md body for a deterministic fingerprint.
            raw_hash = "sha256:" + hashlib.sha256(
                text.encode("utf-8"),
            ).hexdigest()
        return {
            "source_skill": skill,
            "source_list": sl,
            "scraped_at": scraped_at,
            "raw_input_hash": raw_hash,
        }
    return None


def _try_source_channel(
    fm: dict, note: Path, normalize_fn,
) -> dict | None:
    """Backfill from the Person frontmatter's legacy ``source_channel:`` field.

    Returns the canonical lineage dict if the field is present; else
    ``None``.
    """
    legacy = fm.get("source_channel")
    if not legacy:
        return None
    canonical_skill = normalize_fn(legacy)
    source_list = fm.get("source_list") or f"[[legacy-{canonical_skill}]]"
    if not isinstance(source_list, str):
        source_list = str(source_list)
    scraped_at = fm.get("created") or _file_mtime_iso(note)
    # If `created` is just a date (YYYY-MM-DD), promote to ISO UTC.
    if isinstance(scraped_at, str) and len(scraped_at) == 10:
        scraped_at = f"{scraped_at}T00:00:00Z"
    elif not isinstance(scraped_at, str):
        scraped_at = _file_mtime_iso(note)
    # Compute a deterministic hash from the canonical frontmatter shape.
    fm_for_hash = {
        "name": fm.get("name"),
        "id": fm.get("id"),
        "source_channel": legacy,
        "source_list": fm.get("source_list"),
    }
    raw_hash = "sha256:" + hashlib.sha256(
        _canonical_yaml_bytes(fm_for_hash),
    ).hexdigest()
    return {
        "source_skill": canonical_skill,
        "source_list": source_list,
        "scraped_at": scraped_at,
        "raw_input_hash": raw_hash,
    }


def _try_ledger_enrolled(
    person_id: str, ledger_dir: Path | None, normalize_fn,
) -> dict | None:
    """Backfill from the ledger's ``enrolled`` event for this person_id.

    Returns the canonical lineage dict if an ``enrolled`` event exists
    + carries a non-empty ``source`` field; else ``None``.
    """
    if ledger_dir is None or not ledger_dir.exists():
        return None
    # Lazy import — the ledger iter lives in the ledger subpackage, not
    # the vault subpackage. Defer to keep import-time clean.
    from orchestrator.migrations.ledger._ledger_io import iter_events as iter_led
    best_event: dict | None = None
    for ev in iter_led(ledger_dir):
        if ev.get("type") != "enrolled":
            continue
        if ev.get("person_id") != person_id:
            continue
        if not ev.get("source"):
            continue
        # Chronologically last wins (multiple `enrolled` events for a
        # single Person is rare but possible per backfill_ledger).
        if best_event is None or (ev.get("ts") or "") > (best_event.get("ts") or ""):
            best_event = ev
    if best_event is None:
        return None
    canonical_skill = normalize_fn(best_event.get("source"))
    source_list = (
        best_event.get("source_list")
        or f"[[legacy-{canonical_skill}]]"
    )
    if not isinstance(source_list, str):
        source_list = str(source_list)
    scraped_at = best_event.get("ts") or _now_iso()
    raw_hash = "sha256:" + hashlib.sha256(
        json.dumps(best_event, sort_keys=True).encode("utf-8"),
    ).hexdigest()
    return {
        "source_skill": canonical_skill,
        "source_list": source_list,
        "scraped_at": scraped_at,
        "raw_input_hash": raw_hash,
    }


def _manual_floor(person_id: str) -> dict:
    """The §Existing-operator seed floor — manual default."""
    raw_hash = "sha256:" + hashlib.sha256(
        f"manual:{person_id}".encode("utf-8"),
    ).hexdigest()
    return {
        "source_skill": "manual",
        "source_list": "[[legacy-manual]]",
        "scraped_at": _now_iso(),
        "raw_input_hash": raw_hash,
    }


@dataclass
class AddDiscoveryLineageToIdentityKeys:
    """Stamp ``identity_keys.discovery_lineage:`` on every Person note.

    Per ADR-0036 D168. Backfill cascade per the module docstring.
    Reversible: :meth:`downgrade` removes the sub-block.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.VAULT
    description: str = (
        "Add identity_keys.discovery_lineage: sub-block to every "
        "Person note with an existing identity_keys: block. "
        "Backfill cascade: _source.md if parseable → source_channel: "
        "frontmatter field → ledger enrolled.source → manual floor. "
        "Pillar E Week 9-11 — per ADR-0036 D168."
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Stamp ``discovery_lineage`` on every eligible Person note.

        See module docstring for the backfill cascade + per-source
        rules. Logs per-source counts + the fall-back-to-manual
        surface at INFO/WARNING level.

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None``. ``ctx.ledger_dir`` may
            be ``None`` (the cascade skips the ledger step).
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} requires ctx.vault_dir; "
                f"set vault.path in ~/.outreach-factory/config.yml or "
                f"pass --vault-path."
            )
        ctx.logger.warning(_OBSIDIAN_SYNC_WARNING)

        _dl, _ = _import_runtime_helpers()
        normalize_fn = _dl.normalize_legacy_source_to_skill

        per_source_count = {
            "_source.md": 0,
            "source_channel": 0,
            "ledger": 0,
            "manual": 0,
        }
        affected = 0
        already_at_target = 0
        skipped_no_identity_keys = 0
        skipped_non_person = 0
        skipped_no_person_id = 0

        manual_persons: list[str] = []  # for the operator-visible summary

        # Resolve the People dir once so _try_source_md_file's bounded
        # traversal stops at the right place (per Week 9-11 review P3-A).
        people_subdir_path = ctx.vault_dir / "10 People"

        for note in iter_person_notes(ctx.vault_dir):
            fm, _body = read_person_frontmatter(note)
            if not is_person_note(fm):
                skipped_non_person += 1
                continue
            assert fm is not None
            person_id = fm.get("id")
            if not (person_id and isinstance(person_id, str)):
                skipped_no_person_id += 1
                continue

            # Require an existing identity_keys block (parent for the
            # nested sub-block). Persons without identity_keys are
            # pre-Phase-5.5 stubs; they need the operator's hand-
            # stamping via the standard enrollment path first.
            existing_keys = fm.get("identity_keys")
            if not isinstance(existing_keys, dict):
                skipped_no_identity_keys += 1
                continue

            # Idempotent skip — already has discovery_lineage.
            if "discovery_lineage" in existing_keys:
                already_at_target += 1
                continue

            # Cascade per D168. P3-A: pass people_dir so the
            # _source.md traversal stops at the People dir bound.
            chosen_source = "manual"
            lineage_dict = _try_source_md_file(note, people_dir=people_subdir_path)
            if lineage_dict is not None:
                chosen_source = "_source.md"
            else:
                lineage_dict = _try_source_channel(fm, note, normalize_fn)
                if lineage_dict is not None:
                    chosen_source = "source_channel"
                else:
                    lineage_dict = _try_ledger_enrolled(
                        person_id, ctx.ledger_dir, normalize_fn,
                    )
                    if lineage_dict is not None:
                        chosen_source = "ledger"
                    else:
                        lineage_dict = _manual_floor(person_id)
                        chosen_source = "manual"
                        manual_persons.append(person_id)

            # Validate via the DiscoveryLineage dataclass.
            try:
                lineage = _dl.DiscoveryLineage(**lineage_dict)
            except ValueError as exc:
                ctx.logger.error(
                    "%s: refusing to stamp %s — derived lineage "
                    "violates construction-time invariant: %s",
                    self.id, note, exc,
                )
                raise

            canonical_dict = _dl.build_discovery_lineage_dict(lineage)

            text = note.read_text(encoding="utf-8")
            try:
                new_text = extend_frontmatter_nested_block_text(
                    text,
                    parent_key="identity_keys",
                    child_key="discovery_lineage",
                    child_block=canonical_dict,
                )
            except FrontmatterError as exc:
                # The helper's strict-insert refuses when child is
                # already present — race with a concurrent writer or
                # operator who hand-edited between our read + the
                # write. Treat as idempotent-skip + log.
                ctx.logger.info(
                    "%s: skipping %s — extend helper refused: %s",
                    self.id, note, exc,
                )
                already_at_target += 1
                continue

            ctx.logger.info(
                "%s: stamping discovery_lineage on %s "
                "(source=%s, source_skill=%s, source_list=%s)",
                self.id, note.name, chosen_source,
                lineage.source_skill, lineage.source_list,
            )
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1
            per_source_count[chosen_source] += 1

        # Operator-visible per-source summary.
        verb = "would stamp" if ctx.dry_run else "stamped"
        ctx.logger.info(
            "%s discovery_lineage on %d Person notes:",
            verb, affected,
        )
        ctx.logger.info(
            "  from _source.md (high-confidence): %d Persons",
            per_source_count["_source.md"],
        )
        ctx.logger.info(
            "  from source_channel: (medium-confidence): %d Persons",
            per_source_count["source_channel"],
        )
        ctx.logger.info(
            "  from ledger enrolled.source (medium-confidence): %d Persons",
            per_source_count["ledger"],
        )
        ctx.logger.info(
            "  fallback to source_skill: manual (low-confidence): %d Persons",
            per_source_count["manual"],
        )
        ctx.logger.info(
            "total: %d Persons %s; %d already at target; "
            "%d skipped (no identity_keys block); "
            "%d skipped (no person_id); "
            "%d skipped (non-Person)",
            affected, verb, already_at_target,
            skipped_no_identity_keys, skipped_no_person_id,
            skipped_non_person,
        )
        if per_source_count["manual"] > 0:
            ctx.logger.warning(
                "%d Persons fell to source_skill: manual. "
                "Review with: python -m orchestrator.discovery_lineage "
                "backfill --person <id> --source-skill <skill> "
                "for any Person whose source_skill should be a "
                "non-manual value. Per ADR-0036 D168 + R022 mitigation.",
                per_source_count["manual"],
            )
            # Log up to first 10 manual person_ids for operator triage.
            for pid in manual_persons[:10]:
                ctx.logger.warning("  manual-floor person_id: %s", pid)
            if len(manual_persons) > 10:
                ctx.logger.warning(
                    "  ... and %d more (see DEBUG log for full list)",
                    len(manual_persons) - 10,
                )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} discovery_lineage on {affected} Person notes "
                f"(per_source={per_source_count}; "
                f"already_at_target={already_at_target}; "
                f"skipped_no_identity_keys={skipped_no_identity_keys}; "
                f"skipped_no_person_id={skipped_no_person_id}; "
                f"skipped_non_person={skipped_non_person})"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Remove ``identity_keys.discovery_lineage:`` from every Person note.

        Inverse of :meth:`upgrade`. Operators rarely invoke; the
        framework requires ``allow_rollback=True`` explicitly.

        Iterates every Person note and removes the
        ``discovery_lineage:`` sub-block via surgical edit (preserves
        all other identity_keys children + every other top-level
        frontmatter field). Per-file atomic via tmp-then-rename.

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None``.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} downgrade requires "
                f"ctx.vault_dir."
            )
        ctx.logger.warning(_OBSIDIAN_SYNC_WARNING)

        affected = 0
        already_absent = 0
        skipped_non_person = 0
        skipped_no_identity_keys = 0

        for note in iter_person_notes(ctx.vault_dir):
            fm, _body = read_person_frontmatter(note)
            if not is_person_note(fm):
                skipped_non_person += 1
                continue
            assert fm is not None
            existing_keys = fm.get("identity_keys")
            if not isinstance(existing_keys, dict):
                skipped_no_identity_keys += 1
                continue
            if "discovery_lineage" not in existing_keys:
                already_absent += 1
                continue

            text = note.read_text(encoding="utf-8")
            new_text = remove_frontmatter_nested_field_text(
                text, "identity_keys", "discovery_lineage",
            )
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1

        verb = "would remove" if ctx.dry_run else "removed"
        ctx.logger.info(
            "%s discovery_lineage from %d Person notes "
            "(%d already absent, %d no identity_keys, "
            "%d non-Person skipped)",
            verb, affected, already_absent,
            skipped_no_identity_keys, skipped_non_person,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} discovery_lineage from {affected} Person "
                f"notes ({already_absent} already absent, "
                f"{skipped_no_identity_keys} no identity_keys, "
                f"{skipped_non_person} non-Person skipped)"
            ),
        )


MIGRATION: AddDiscoveryLineageToIdentityKeys = (
    AddDiscoveryLineageToIdentityKeys()
)


__all__ = [
    "AddDiscoveryLineageToIdentityKeys",
    "MIGRATION",
    "MIGRATION_ID",
]
