"""Vault migration 0002 — backfill id + identity_keys lineage onto Person notes.

Pillar B Week 5: wraps the Phase 5.5 Week 1b backfill (``backfill_identity.py``)
as a ``Migration`` so the same logic that ran historically against
operator vaults can be replayed against synthetic fixtures via the
migration framework. The wrapper is the integration vehicle that the
Pillar B exit criterion (PILLAR-PLAN §2) names: *"the Phase 5.5
backfills replayed cleanly through the migration runner against a
fresh synthetic vault."*

What it does
------------

For every Person note under ``<ctx.vault_dir>/10 People/``:

1. Parse the note's frontmatter via
   :func:`._vault_io.read_person_frontmatter`.
2. Compute ``IdentityKeys`` from existing legacy fields (``linkedin:``,
   ``email:`` / ``emails:``, ``github:``, ``twitter:``, ``name:``) via
   :func:`orchestrator.identity.compute_keys`.
3. Mint a stable ``id:`` via :func:`orchestrator.identity.mint_id` with
   the canonical provenance-suffix convention (``-li`` / ``-em`` /
   ``-gh`` / ``-tw`` / ``-tmp``).
4. Surgically insert ``id:``, ``identity_keys:`` block, and
   ``identity_version: 1`` immediately after the existing ``type:``
   line — preserving every other line + comment + quote-style byte
   identical.
5. Atomically rewrite the note via
   :func:`._vault_io.write_person_frontmatter_atomic` (tmp-then-rename
   with ``fsync``).

Conflicts: refuse loud
----------------------

When two or more Person notes share an ``IdentityKeys`` strong-key
class (``linkedin`` / ``emails`` / ``github`` / ``twitter`` — but not
``alt_names``), the migration raises
:class:`IdentityBackfillConflictError`. The error message lists every
conflict cluster's file paths + the shared key values so the operator
can resolve in-place (merge the records or remove the shared key from
one).

Per the asymmetric-failure-cost principle (PILLAR-PLAN §0): a
silent auto-merge could route a future send to the wrong human. Loud
refusal + operator inspection is the only safe shape. The framework's
atomicity contract (ADR-0009 D4) means a raised ``upgrade`` does NOT
mark the migration applied — the operator fixes the conflict and
re-runs ``apply`` to resume idempotently.

Why ``is_reversible=False``
---------------------------

Mint order is path-dependent: the ``provenance suffix`` on the minted
``id:`` is chosen from the strong-key inventory at mint time. If a
downgrade removed the field and a future operator re-ran the migration
after adding/removing strong keys (operator-edited frontmatter between
the two runs), the new ``id:`` could differ from the original. The
ledger then references a stable id that the vault no longer mints
the same way — a denormalized-view drift the framework's
asymmetric-failure-cost calculus says we should avoid by structurally
forbidding downgrade.

Operators recovering from a bad apply restore the vault directory from
backup + manually mark the migration as un-applied via the state-file
primitive (``mark_unapplied``); ``MigrationRunner.rollback`` refuses
with ``MigrationNotReversibleError``.

Per-file atomicity
------------------

Each note's rewrite goes through
:func:`._vault_io.write_person_frontmatter_atomic` — the same
tmp-then-rename-with-``fsync`` primitive
``vault/0001_add_schema_version_to_person_notes`` uses. A crash mid-
batch leaves every file in either the pre- or post-migration shape,
never half-written. The runner's state-file lock + ADR-0009 D4
atomicity contract layer batch-level atomicity on top of per-file
atomicity.

Idempotence
-----------

Notes already declaring BOTH ``id:`` and ``identity_keys:`` (in any
non-empty form) are silently skipped — the migration's contract is "go
from no-identity-block to v1." If a previous partial apply wrote
``id:`` but not ``identity_keys:`` (or vice versa) the re-render
function strips both and rewrites cleanly, so partial-failure resume
is safe.

See ADR-0013 for the synthetic-replay vehicle design (D23 wrapped
backfill IDs; D24 synthetic fixture shape; D26 doctor refuse-on-pending
posture; D27 default-apply-order reorder VAULT → LEDGER → POLICY).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from orchestrator.identity import (
    IdentityKeys,
    compute_keys,
    keys_intersect,
    keys_intersect_detail,
    mint_id,
)

from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._vault_io import (
    FrontmatterError,
    is_person_note,
    iter_person_notes,
    read_person_frontmatter,
    write_person_frontmatter_atomic,
)


# Migration id — exported so tests + downstream consumers refer to it
# symbolically without re-typing the string.
MIGRATION_ID = "0002_backfill_identity_lineage"

# Default people-subdir. Matches `_vault_io.iter_person_notes`'s default
# AND the `vault.people_dir` config field's factory default. Operators
# with renamed subdirs configure via `vault.people_dir` in
# `~/.outreach-factory/config.yml` — the runner reads config + passes
# the resolved path as `ctx.vault_dir`, and the migration walks
# `<vault_dir>/<PEOPLE_SUBDIR>/` for Person notes.
PEOPLE_SUBDIR = "10 People"

# The identity_version this migration stamps. Future migrations that
# evolve the identity_keys block shape bump this value + ship coordinated
# engine updates that accept both versions during the transition window.
IDENTITY_VERSION_VALUE = 1


class IdentityBackfillConflictError(FrontmatterError):
    """Two or more Person notes share an identity-key strong class.

    Raised by :meth:`BackfillIdentityLineage.upgrade` when pairwise
    ``IdentityKeys`` intersection (transitive closure) surfaces a
    cluster of 2+ Person notes that share at least one strong key
    (``linkedin`` / ``emails`` / ``github`` / ``twitter``). The
    migration cannot auto-resolve: it doesn't know whether the shared
    key means "same person" (merge candidates) or "two people with
    overlapping touchpoints" (different humans who happen to share
    ownership of, say, a company twitter handle).

    Per ADR-0013 D23 the migration refuses + names the conflict
    cluster(s) in the exception's message. Operators resolve in
    vault (merge or split Person notes) and re-run apply. The
    framework's atomicity contract (ADR-0009 D4) guarantees the
    re-run picks up cleanly — the migration was not marked applied.
    """


@dataclass
class _ParsedNote:
    """Internal: one Person note's parsed state + proposed identity."""

    path: Path
    raw_text: str
    fm: dict
    has_id: bool
    has_identity_keys: bool
    has_identity_version: bool
    keys: IdentityKeys
    proposed_id: str
    proposed_keys_block: dict


def _coerce_email_list(value: Any) -> list[str]:
    """Accept None / str / list and produce a list of email strings.

    Mirrors backfill_identity._coerce_email_list. The frontmatter may
    declare ``emails:`` as a single string (a manual operator edit) or
    a YAML list; either shape produces the same downstream
    IdentityKeys.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return []


def _coerce_company_slug(value: Any) -> str | None:
    """Extract the bare slug from an Obsidian wikilink ``[[Company]]``.

    Mirrors backfill_identity._coerce_company_slug. Used when the
    minted id needs a ``-tmp`` fallback with the operator's company
    string for human readability.
    """
    if not value:
        return None
    if isinstance(value, str):
        m = re.match(r"\[\[([^\]]+)\]\]", value.strip())
        return (m.group(1) if m else value).strip() or None
    return None


def _proposed_keys_block(keys: IdentityKeys) -> dict:
    """Stable shape for the ``identity_keys:`` block.

    Mirrors backfill_identity._proposed_keys_block. Sorted lists for
    determinism — re-running the migration on an unchanged note
    produces byte-identical output.
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


def _parse_one(path: Path) -> _ParsedNote | None:
    """Parse a Person note's frontmatter + compute proposed identity.

    Returns ``None`` for files that aren't Person notes (no parseable
    frontmatter; ``type != "person"``). Raises
    :class:`FrontmatterError` from :func:`read_person_frontmatter` on
    corrupt YAML — propagated so the runner's atomicity contract
    catches it (state pointer doesn't advance; operator inspects).
    """
    fm, _body = read_person_frontmatter(path)
    if not is_person_note(fm):
        return None
    assert fm is not None
    # Re-read the raw text after CRLF normalization so the surgical
    # render operates on LF-only content (read_person_frontmatter
    # normalizes internally but doesn't return the normalized text).
    raw_text = path.read_text(encoding="utf-8")
    if "\r\n" in raw_text:
        raw_text = raw_text.replace("\r\n", "\n")
    name = str(fm.get("name") or path.stem or "").strip()
    keys = compute_keys(
        name=name,
        email=fm.get("email"),
        emails=_coerce_email_list(fm.get("emails")),
        linkedin_url=fm.get("linkedin"),
        github=fm.get("github"),
        twitter=fm.get("twitter"),
    )
    existing_id = str(fm["id"]).strip() if fm.get("id") else None
    proposed_id = existing_id or mint_id(
        keys,
        name_fallback=name,
        company_slug=_coerce_company_slug(fm.get("company")),
    )
    return _ParsedNote(
        path=path,
        raw_text=raw_text,
        fm=fm,
        has_id=bool(existing_id),
        has_identity_keys=bool(fm.get("identity_keys")),
        has_identity_version="identity_version" in fm,
        keys=keys,
        proposed_id=proposed_id,
        proposed_keys_block=_proposed_keys_block(keys),
    )


def _yaml_block_lines(block: dict, indent: int = 2) -> list[str]:
    """Serialize a single mapping as indented YAML lines, no doc fences.

    Mirrors backfill_identity._yaml_block_lines. Sorted keys are
    preserved from the input dict (Python dict ordering); the input
    dict is constructed deterministically by :func:`_proposed_keys_block`.
    """
    dumped = yaml.safe_dump(
        block,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return [" " * indent + line for line in dumped.rstrip().split("\n")]


def _find_insertion_point(lines: list[str]) -> int:
    """Index in ``lines`` AFTER the ``type:`` line, or ``name:``, or 0.

    Mirrors backfill_identity._find_insertion_point. Identity block
    sits at the top of frontmatter where a human reader expects it —
    immediately under the type / name banner.
    """
    for i, ln in enumerate(lines):
        if re.match(r"^type\s*:", ln):
            return i + 1
    for i, ln in enumerate(lines):
        if re.match(r"^name\s*:", ln):
            return i + 1
    return 0


def _strip_existing_identity_lines(lines: list[str]) -> list[str]:
    """Drop any partial id / identity_keys / identity_version lines.

    Called before re-inserting so the migration converges on re-runs
    after a partial-failure (some notes were rewritten; some weren't;
    re-running apply walks the partially-rewritten + un-rewritten set
    uniformly).

    Mirrors backfill_identity._strip_existing_identity_lines.
    """
    out: list[str] = []
    skipping_block = False
    for ln in lines:
        if skipping_block:
            if ln.startswith(" ") or ln.startswith("\t"):
                continue
            skipping_block = False
        if re.match(r"^id\s*:", ln):
            continue
        if re.match(r"^identity_version\s*:", ln):
            continue
        if re.match(r"^identity_keys\s*:", ln):
            skipping_block = True
            continue
        out.append(ln)
    return out


def _render(parsed: _ParsedNote) -> str:
    """Re-render a Person note with id + identity_keys block inserted.

    Returns the input text unchanged when both fields are already
    present (idempotent). Otherwise:

    1. Strip any partial existing identity lines.
    2. Insert id + identity_keys block + identity_version after the
       type: / name: banner.
    3. Re-serialize as ``---\\n<fm>\\n---\\n<body>``.

    The body is preserved byte-for-byte (no markdown content is
    rewritten). Inline frontmatter comments are preserved on lines that
    are not stripped.

    Raises
    ------
    FrontmatterError:
        When ``parsed.raw_text`` has no closing frontmatter delimiter.
        Should be unreachable in practice — :func:`_parse_one` already
        consulted :func:`read_person_frontmatter` which would have
        raised on this shape.
    """
    # All three fields (``id``, ``identity_keys``, ``identity_version``)
    # must be present for the short-circuit. A Person note where an
    # operator hand-stamped two of the three but not the third should
    # be rewritten so the v1 marker (``identity_version: 1``) is
    # stamped — otherwise a future Pillar D / E / F migration that
    # gates on ``identity_version`` would find counterexamples.
    if (parsed.has_id
            and parsed.has_identity_keys
            and parsed.has_identity_version):
        return parsed.raw_text
    if not parsed.raw_text.startswith("---\n"):
        raise FrontmatterError(
            f"{parsed.path}: cannot insert identity block — no opening "
            f"frontmatter delimiter",
        )
    # Locate the closing delimiter. Accept both styles:
    # * ``\n---\n``  (typical — body follows on the next line)
    # * ``\n---`` at EOF  (no body)
    m = re.search(r"\n---[ \t]*(?:\n|$)", parsed.raw_text[4:])
    if m is None:
        raise FrontmatterError(
            f"{parsed.path}: cannot insert identity block — no closing "
            f"frontmatter delimiter (expected `\\n---\\n` or `\\n---` "
            f"at EOF)",
        )
    close_rel_start = m.start()  # index of "\n" in the match, relative to text[4:]
    close_rel_end = m.end()
    fm_text = parsed.raw_text[4 : 4 + close_rel_start]
    body = parsed.raw_text[4 + close_rel_end :]
    lines = fm_text.split("\n")
    lines = _strip_existing_identity_lines(lines)
    insert_idx = _find_insertion_point(lines)
    new_lines = [f"id: {parsed.proposed_id}"]
    block_lines = _yaml_block_lines(parsed.proposed_keys_block, indent=2)
    if block_lines:
        new_lines.append("identity_keys:")
        new_lines.extend(block_lines)
        new_lines.append(f"identity_version: {IDENTITY_VERSION_VALUE}")
    # If the keys block is empty (no strong identity present), still
    # write id (so the note has a stable handle) but skip the empty
    # mapping — emitting ``identity_keys: {}`` would look strange in
    # the vault and confuse downstream readers.
    lines[insert_idx:insert_idx] = new_lines
    new_fm = "\n".join(lines).rstrip() + "\n"
    return f"---\n{new_fm}---\n{body}"


def _detect_conflicts(
    notes: list[_ParsedNote],
) -> list[tuple[list[Path], dict[str, list[str]]]]:
    """Pairwise key-class intersection; transitive closure via union-find.

    Returns a list of (note_paths, shared_keys) tuples — one per
    cluster of 2+ notes whose IdentityKeys intersect on at least one
    strong key class. ``alt_names`` is NOT a match class (matches
    backfill_identity.detect_conflicts).
    """
    n = len(notes)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pair_detail: dict[tuple[int, int], dict[str, list[str]]] = {}
    for i in range(n):
        for j in range(i + 1, n):
            classes = keys_intersect(notes[i].keys, notes[j].keys)
            if classes:
                union(i, j)
                pair_detail[(i, j)] = keys_intersect_detail(
                    notes[i].keys, notes[j].keys,
                )
    by_root: dict[int, list[int]] = {}
    for i in range(n):
        by_root.setdefault(find(i), []).append(i)
    out: list[tuple[list[Path], dict[str, list[str]]]] = []
    for members in by_root.values():
        if len(members) < 2:
            continue
        merged: dict[str, set[str]] = {}
        for a_idx in range(len(members)):
            for b_idx in range(a_idx + 1, len(members)):
                a, b = sorted((members[a_idx], members[b_idx]))
                detail = pair_detail.get((a, b)) or {}
                for cls, vals in detail.items():
                    merged.setdefault(cls, set()).update(vals)
        out.append((
            sorted(notes[m].path for m in members),
            {k: sorted(v) for k, v in merged.items()},
        ))
    return out


def _format_conflicts_message(
    conflicts: list[tuple[list[Path], dict[str, list[str]]]],
) -> str:
    """Render conflicts as a multi-line operator-readable message."""
    parts = [
        f"{len(conflicts)} identity-graph conflict cluster(s) detected. "
        f"The migration refuses to proceed; manually resolve in vault "
        f"(merge or split) and re-run apply.",
    ]
    for i, (paths, shared) in enumerate(conflicts, 1):
        classes = ",".join(sorted(shared.keys()))
        parts.append(f"")
        parts.append(f"Cluster {i} — shared via [{classes}]:")
        for cls, vals in shared.items():
            for v in vals:
                parts.append(f"  {cls:10s} = {v}")
        for p in paths:
            parts.append(f"  -> {p}")
    return "\n".join(parts)


@dataclass
class BackfillIdentityLineage:
    """Backfill ``id`` + ``identity_keys`` + ``identity_version`` per note.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work lives in
    :meth:`upgrade`. :meth:`downgrade` raises ``NotImplementedError``
    per the irreversibility rationale documented at the module level.

    Module-level singleton ``MIGRATION`` is registered in
    ``vault/__init__.py::MIGRATIONS`` so the runner discovers it.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.VAULT
    description: str = (
        "Backfill id + identity_keys + identity_version onto every "
        "Person note (Phase 5.5 Week 1b backfill replay)"
    )
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Stamp id + identity_keys + identity_version on every Person note.

        Iterates every ``*.md`` under ``<vault_dir>/10 People/``,
        reads each note's frontmatter, computes proposed identity,
        detects conflicts (refuse-loud), then atomically rewrites
        each note via tmp-then-rename.

        Side effects on a successful apply:

        * N Person notes rewritten (where N = ``affected_count``).
        * Zero ledger writes (this is a vault migration; ledger
          migrations live in ``orchestrator/migrations/ledger/``).
        * Zero policy writes.

        On dry-run (``ctx.dry_run=True``): no on-disk mutation. The
        ``MigrationResult`` carries the same counts as a real apply
        would produce.

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None`` (operator hasn't set
            ``vault.path`` in config).
        IdentityBackfillConflictError:
            When the identity-graph has 2+ Person notes sharing a
            strong key class. Subclass of ``FrontmatterError``.
        FrontmatterError:
            On any Person note with corrupt YAML frontmatter (propa-
            gated from :func:`read_person_frontmatter`).
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} requires ctx.vault_dir; "
                f"set vault.path in ~/.outreach-factory/config.yml or "
                f"pass --vault-path equivalent to the runner.",
            )
        people_dir = ctx.vault_dir / PEOPLE_SUBDIR
        if not people_dir.exists():
            # A vault that hasn't created the People dir yet is a
            # legitimate fresh-install state — no Person notes to
            # backfill. Same posture as `iter_person_notes` (yields
            # nothing). Mark applied with zero affected.
            ctx.logger.info(
                "%s: people dir %s does not exist; nothing to backfill",
                self.id, people_dir,
            )
            return MigrationResult(
                migration_id=self.id,
                category=self.category,
                applied=True,
                dry_run=ctx.dry_run,
                affected_count=0,
                notes=(
                    f"people dir {people_dir} does not exist; nothing "
                    f"to backfill (legitimate fresh-install state)"
                ),
            )

        parsed: list[_ParsedNote] = []
        for note in iter_person_notes(ctx.vault_dir, people_subdir=PEOPLE_SUBDIR):
            p = _parse_one(note)
            if p is None:
                continue
            parsed.append(p)

        conflicts = _detect_conflicts(parsed)
        if conflicts:
            raise IdentityBackfillConflictError(
                _format_conflicts_message(conflicts),
            )

        affected = 0
        already_complete = 0
        tmp_id_count = 0
        for p in parsed:
            # All three fields must be present to count as complete —
            # mirrors the _render short-circuit. A partial state where
            # id + identity_keys are present but identity_version is
            # missing still gets rewritten so the v1 marker is stamped.
            if (p.has_id
                    and p.has_identity_keys
                    and p.has_identity_version):
                already_complete += 1
                continue
            new_text = _render(p)
            if new_text == p.raw_text:
                # Render produced byte-identical output (idempotent
                # short-circuit when only one of has_id / has_identity_keys
                # was set and the strip + re-insert happened to converge).
                already_complete += 1
                continue
            if not ctx.dry_run:
                write_person_frontmatter_atomic(p.path, new_text)
            if p.proposed_id.endswith("-tmp"):
                tmp_id_count += 1
            affected += 1

        verb = "would backfill" if ctx.dry_run else "backfilled"
        ctx.logger.info(
            "%s id+identity_keys onto %d Person note(s) "
            "(%d already complete, %d minted -tmp ids)",
            verb, affected, already_complete, tmp_id_count,
        )

        notes_msg = (
            f"{verb} id+identity_keys onto {affected} Person note(s) "
            f"({already_complete} already complete"
            + (f"; {tmp_id_count} minted -tmp ids — send-gate will "
               f"block until upgraded" if tmp_id_count else "")
            + ")"
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=notes_msg,
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Refuse — vault identity backfill is structurally irreversible.

        Raises ``NotImplementedError``; the runner translates this
        into ``MigrationNotReversibleError`` for the operator-facing
        refusal. See the module docstring for the rationale (mint
        order is path-dependent — removing the field and re-running
        could produce different ids).
        """
        raise NotImplementedError(
            f"vault migration {self.id!r} is structurally irreversible. "
            f"id mint is path-dependent (provenance suffix chosen from "
            f"the strong-key inventory at mint time); rolling back + "
            f"re-applying after operator vault edits could produce a "
            f"different id and break ledger references. Restore the "
            f"vault directory from backup if you need the prior state."
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: BackfillIdentityLineage = BackfillIdentityLineage()


# Re-export for tests that need the bare-name conflict marker.
__all__ = [
    "BackfillIdentityLineage",
    "IdentityBackfillConflictError",
    "MIGRATION",
    "MIGRATION_ID",
    "IDENTITY_VERSION_VALUE",
    "PEOPLE_SUBDIR",
]
