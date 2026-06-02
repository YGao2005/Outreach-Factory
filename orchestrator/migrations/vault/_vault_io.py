"""Per-file IO surface for vault migrations.

Vault migrations rewrite YAML frontmatter inside individual Person notes.
This module exposes:

* ``read_person_frontmatter(path)`` — parse ``(frontmatter_dict, body)`` from
  a markdown file. Returns ``(None, body)`` when the file has no
  parseable frontmatter (Obsidian sub-notes, drafts) so the migration
  can skip them silently. Raises :class:`FrontmatterError` when the
  delimiters are present but the YAML is malformed — that's a corrupt
  Person note + per the asymmetric-failure-cost principle the migration
  must refuse loud rather than silently skip.
* ``is_note_type(fm, note_type)`` — canonical predicate "is this note
  declared as ``type: <note_type>``?" Robust to non-string ``type:``
  values (Week 2 P2-1 + Week 5 P2-2 fix). The shared predicate other
  modules import — see Pillar B holistic-review §P2-2 for the
  consolidation rationale.
* ``is_person_note(fm)`` / ``is_touch_note(fm)`` — thin wrappers over
  :func:`is_note_type` for the two common note types. The iterator
  yields every ``*.md`` file under the relevant dir; the migration
  filters with these predicates after reading frontmatter.
* ``add_frontmatter_field_text(text, key, value)`` /
  ``remove_frontmatter_field_text(text, key)`` — surgical insert /
  delete preserving every other line + comment. Same convention
  ``orchestrator.reconcile._write_pipeline_stage`` uses for surgical
  frontmatter edits, generalized.
* ``write_person_frontmatter_atomic(path, text)`` — tmp-then-rename
  atomic write. Matches the durability bar set by
  ``orchestrator.migrations.state.save_state_atomic`` and
  ``orchestrator.policy.suppression.forget_append`` (ADR-0004).
* ``iter_person_notes(vault_dir, people_subdir="10 People")`` — walks
  ``<vault_dir>/<people_subdir>/`` and yields every ``*.md`` file,
  skipping hidden files + Obsidian Sync conflict files. Same walk
  convention ``orchestrator.identity.build_index`` +
  ``orchestrator.reconcile._walk_people_dir`` use.

The atomicity model is per-file: each vault migration rewrites every
Person note one at a time, each via tmp-then-rename. A crash during the
batch leaves every file in either the pre-migration shape or the
post-migration shape, never half-written. The runner's state file
tracks batch-level atomicity (the migration is marked applied iff
every file was successfully rewritten).

See ADR-0011 for the vault-migration-specific design.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator

import yaml


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


class FrontmatterError(ValueError):
    """Raised when a Person note's frontmatter is corrupt or shape-wrong.

    Distinct from "this file is not a Person note" — for the latter the
    parser returns ``(None, body)`` and the migration silently skips.
    ``FrontmatterError`` is reserved for cases where the file LOOKS like
    a Person note (has ``---`` delimiters) but cannot be parsed safely:

    * Frontmatter delimiters present but the YAML between them is
      malformed (unbalanced braces, bad indentation, etc.).
    * ``add_frontmatter_field_text`` invoked on text that has no
      frontmatter delimiters — the caller's contract violation.
    * ``add_frontmatter_field_text`` invoked with a key that already
      exists — guards against silently clobbering operator edits.

    Migrations propagate this error so the runner refuses to mark the
    migration applied (the state-file pointer doesn't move) and the
    operator can fix the offending file before re-running ``apply``.
    """


def read_person_frontmatter(path: Path) -> tuple[dict | None, str]:
    """Parse a Person note's frontmatter + body.

    Returns ``(fm, body)`` where ``fm`` is the parsed frontmatter dict
    (or ``None`` when the file has no parseable frontmatter) and
    ``body`` is the remainder of the file. The caller filters via
    :func:`is_person_note` to decide whether to act.

    Three terminal shapes:

    * **No frontmatter delimiters.** The file doesn't start with
      ``---\\n``. Returns ``(None, full_text)``. Migration skips.
    * **Frontmatter parses to non-dict.** The file starts with ``---``
      but the YAML inside resolves to e.g. a string (the file uses
      ``---`` as a horizontal rule, not a frontmatter delimiter).
      Returns ``(None, body)``. Migration skips.
    * **Frontmatter delimiters present but YAML is corrupt.** Raises
      :class:`FrontmatterError` with the file path so the operator can
      fix the file and re-run apply.

    Raises
    ------
    FrontmatterError:
        When the YAML between the ``---`` delimiters fails to parse.
        Or when the file is unreadable.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FrontmatterError(f"could not read {path}: {exc}") from exc

    # Normalize CRLF → LF so the regex (which uses literal \n) matches
    # files edited on Windows or by tools that wrote CRLF endings. The
    # write side (`write_person_frontmatter_atomic`) always writes LF;
    # CRLF files get normalized on the round-trip. Acceptable trade-off
    # for the asymmetric-failure-cost calculus: the alternative is
    # silently treating CRLF Person notes as non-Person files, which
    # would skip them entirely. macOS Obsidian uses LF natively;
    # this only matters for vaults that have been touched by Windows
    # editors or cross-platform sync tools.
    if "\r\n" in text:
        text = text.replace("\r\n", "\n")

    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text

    raw_fm = m.group(1)
    body = m.group(2)
    try:
        fm = yaml.safe_load(raw_fm)
    except yaml.YAMLError as exc:
        raise FrontmatterError(
            f"unparseable YAML frontmatter in {path}: {exc}",
        ) from exc

    if not isinstance(fm, dict):
        return None, text

    return fm, body


def is_note_type(fm: dict | None, note_type: str) -> bool:
    """True if the parsed frontmatter declares ``type: <note_type>``.

    Canonical predicate for "is this markdown note of the expected
    type?" — used by vault migrations to filter Person notes, by
    ledger migrations to filter Person + touch notes, and by future
    Pillar C / D / E migrations to filter whatever new note types
    they introduce.

    Contract
    --------
    * ``fm is None`` or ``fm`` is empty → False (no parseable
      frontmatter; the file is not a typed note).
    * ``fm["type"]`` missing → False (a frontmatter dict without
      ``type:`` is not a typed note).
    * ``fm["type"]`` is a string that strips-equal to ``note_type`` →
      True. Leading / trailing whitespace in the YAML value is
      forgiven (Obsidian's frontmatter editor sometimes appends).
    * ``fm["type"]`` is a non-string (``int`` from ``type: 42``,
      ``bool`` from ``type: true``, ``None`` from ``type:`` with no
      value) → False. The contract is "silently skip files that are
      not the requested type"; a file with a non-string ``type``
      cannot be the requested type by definition. Without this guard
      the bare ``str.strip()`` call would crash with
      ``AttributeError``.

    History
    -------
    Consolidated in Pillar B Week 6's holistic-review follow-up. The
    same predicate previously existed in three near-identical inline
    forms across ``_vault_io.is_person_note``,
    ``ledger.migration_0002._walk_person_records``, and
    ``ledger.migration_0002._walk_touch_records``. Two of those three
    forms had to be independently fixed (Week 2 P2-1 + Week 5 P2-2)
    after each crashed on non-string ``type:`` values. Centralizing
    here means the next migration that needs the predicate imports
    rather than re-implements — see the holistic review at
    ``.planning/REVIEW-pillar-b-holistic.md`` §P2-2 for the rationale.
    """
    if not fm:
        return False
    t = fm.get("type")
    return isinstance(t, str) and t.strip() == note_type


def is_person_note(fm: dict | None) -> bool:
    """True if the parsed frontmatter declares ``type: person``.

    Thin wrapper over :func:`is_note_type` for the most-common case
    (Person notes are the dominant vault-migration target). New code
    that needs another note type should call :func:`is_note_type`
    directly rather than adding a sibling wrapper per type.
    """
    return is_note_type(fm, "person")


def is_touch_note(fm: dict | None) -> bool:
    """True if the parsed frontmatter declares ``type: touch``.

    Touch notes live in ``vault/40 Conversations/``; ledger
    migrations walk them to retroactively emit ``send_intent`` /
    ``send_confirmed`` pairs (e.g. ledger/0002). Provided here for
    symmetry with :func:`is_person_note`.
    """
    return is_note_type(fm, "touch")


# Known Obsidian Sync conflict-file naming conventions.
# Filters in :func:`is_obsidian_conflict_file` use ``in`` substring
# matching for the parenthesized patterns (which can appear at any
# position depending on the Obsidian version) and an endswith / in
# combination for the legacy patterns.
#
# History (Pillar B Week 6 second follow-up consolidation per
# `.planning/REVIEW-pillar-b-boil-the-ocean.md` §P2-1):
#
# The pre-consolidation filter handled only the legacy desktop naming
# (``.conflicted.md`` / ``.conflict.md``) and missed the iCloud-backed
# variant (``"<base> (conflicted copy YYYY-MM-DD from iPhone).md"``),
# silently passing iCloud Sync conflict files through to be rewritten
# by vault migrations — exactly what the filter exists to prevent.
# Both vault iteration (:func:`iter_person_notes`) and ledger walks
# (``ledger/migration_0002._walk_person_records`` /
# ``_walk_touch_records``) now delegate to this consolidated helper.
_OBSIDIAN_CONFLICT_PATTERNS = (
    ".conflicted",          # legacy desktop: <base>.conflicted.md
    ".conflict.md",         # legacy desktop variant: <base>.conflict.md
    "(conflicted copy",     # iCloud: "<base> (conflicted copy YYYY-MM-DD from <device>).md"
    "'s conflicted copy",   # iCloud variant: "<base> (<device>'s conflicted copy YYYY-MM-DD).md"
)


def is_obsidian_conflict_file(name: str) -> bool:
    """True if ``name`` looks like an Obsidian Sync conflict artifact.

    Conflict files are sync-engine artifacts produced when two devices
    edit the same note while offline. Rewriting them via a vault
    migration would compound the conflict (the conflict file ends up
    stamped with new frontmatter that the upstream's canonical
    version doesn't have, and Obsidian Sync then has two stamped
    versions to merge).

    Covers all known naming conventions across Obsidian Sync versions:

    * Legacy desktop: ``<base>.conflicted.md``
    * Legacy desktop variant: ``<base>.conflict.md``
    * iCloud-backed: ``<base> (conflicted copy YYYY-MM-DD from <device>).md``
    * iCloud-backed variant: ``<base> (<device>'s conflicted copy YYYY-MM-DD).md``

    Use this everywhere a migration walks vault markdown — vault
    dispatcher's :func:`iter_person_notes` + ledger migration walks
    of People + Conversations dirs both delegate here.
    """
    return any(pat in name for pat in _OBSIDIAN_CONFLICT_PATTERNS)


def _frontmatter_split(text: str) -> int:
    """Return position of the ``\\n`` immediately before the closing ``---``.

    The frontmatter content lives at ``text[4:split+1]`` (with the trailing
    newline). The closing delimiter + body live at ``text[split+1:]``.

    Tolerates both styles of file ending:

    * ``\\n---\\n`` followed by body
    * ``\\n---`` at EOF (no trailing newline after the closing delimiter)

    Raises :class:`FrontmatterError` when neither ending is present.
    """
    end = text.find("\n---\n", 4)
    if end != -1:
        return end
    end = text.find("\n---", 4)
    if end == -1 or end + 4 != len(text):
        raise FrontmatterError(
            "no closing frontmatter delimiter (expected `\\n---\\n` or "
            "`\\n---` at EOF)",
        )
    return end


def add_frontmatter_field_text(text: str, key: str, value: object) -> str:
    """Insert ``<key>: <value>`` as a new line at the end of the frontmatter.

    Strict insert — refuses to update an existing field. The caller is
    responsible for skipping notes where ``key`` already has the desired
    value (idempotence check) and raising if it has a different value
    (no silent clobber).

    Preserves every other line + every comment in the frontmatter block.
    The new field appears as the last frontmatter line (before the
    closing ``---``), with the same indentation as a top-level field.

    Raises
    ------
    FrontmatterError:
        When ``text`` has no frontmatter delimiters (no opening
        ``---\\n`` or no closing ``\\n---``); or when ``key`` already
        exists in the frontmatter.
    """
    if not text.startswith("---\n"):
        raise FrontmatterError(
            "cannot insert field: text has no opening frontmatter delimiter",
        )
    end = _frontmatter_split(text)
    fm_with_nl = text[4 : end + 1]
    line_re = re.compile(rf"^{re.escape(key)}:", re.MULTILINE)
    if line_re.search(fm_with_nl):
        raise FrontmatterError(
            f"cannot insert field {key!r}: already present in frontmatter. "
            f"The caller should have detected idempotence or value-mismatch "
            f"before calling add_frontmatter_field_text.",
        )
    formatted = _format_yaml_value(value)
    new_fm = fm_with_nl + f"{key}: {formatted}\n"
    return text[:4] + new_fm + text[end + 1 :]


def remove_frontmatter_field_text(text: str, key: str) -> str:
    """Delete a frontmatter field. Inverse of ``add_frontmatter_field_text``.

    Preserves every other line + comment. If the key is absent, returns
    ``text`` unchanged (idempotent — downgrade re-run is safe).

    Removes ONLY top-level frontmatter fields. A nested key like
    ``identity_keys.discovery_lineage`` cannot be removed by this
    function — that's a deeper transformation requiring a YAML round-trip.

    Raises
    ------
    FrontmatterError:
        When ``text`` has no frontmatter delimiters. Absence of the key
        is NOT an error (idempotent removal).
    """
    if not text.startswith("---\n"):
        raise FrontmatterError(
            "cannot remove field: text has no opening frontmatter delimiter",
        )
    end = _frontmatter_split(text)
    fm_with_nl = text[4 : end + 1]
    # Match the exact line `<key>: ...` (including any trailing comment),
    # consuming the newline after the line.
    line_re = re.compile(rf"^{re.escape(key)}:[^\n]*\n", re.MULTILINE)
    new_fm = line_re.sub("", fm_with_nl)
    return text[:4] + new_fm + text[end + 1 :]


def add_frontmatter_block_text(
    text: str, key: str, block: dict, indent: int = 2,
) -> str:
    """Insert ``<key>:`` followed by a nested mapping block at the end
    of the frontmatter. The nested mapping is rendered as YAML using
    the same scalar conventions as :func:`add_frontmatter_field_text`
    (booleans / None / numbers unquoted; strings with YAML-significant
    chars single-quoted).

    Sibling to :func:`add_frontmatter_field_text` for nested-map
    frontmatter fields. Vault migrations that need to stamp a single
    scalar (``schema_version: 1``, ``id: alice-li``) use the field
    helper; migrations that need to stamp a nested map
    (``identity_keys: {linkedin: ..., email: ...}``,
    ``discovery_lineage: {source_skill: ..., scraped_at: ...}``) use
    this helper.

    Pillar B Week 6 second follow-up addition per
    `.planning/REVIEW-pillar-b-pillar-c-readiness.md` §P2-1 — pulled
    forward from Pillar I OSS sweep + ADR-0011 D8's "Pillar E author
    either extends or YAML-round-trips" alternative. Pillar C's
    LinkedIn touch-note migrations will need nested-map insertion
    (channel detail, invite intent details); shipping the primitive
    pre-Pillar-C avoids each future migration re-implementing it or
    falling back to the comment-destroying YAML round-trip.

    Strict insert — refuses to update an existing ``key``. Caller
    handles idempotence (skip if the key is already present with the
    desired shape) before calling.

    Output shape: a key line + one indented line per dict entry. Two-
    space indentation by default (matches Obsidian frontmatter
    convention + the policy module's ``add_top_level_block_text``).

    Example:

    >>> text = "---\\ntype: person\\n---\\nbody"
    >>> add_frontmatter_block_text(
    ...     text, "identity_keys",
    ...     {"linkedin": "in/foo", "email": "foo@bar"},
    ... )
    '---\\ntype: person\\nidentity_keys:\\n  linkedin: in/foo\\n  email: foo@bar\\n---\\nbody'

    The block's child order matches the dict's iteration order
    (insertion order in Python 3.7+); callers needing deterministic
    field ordering should pass an ordered dict.

    Limitations:

    * One level of nesting only. Two-level maps (e.g.
      ``discovery_lineage: {channels: {linkedin: ..., email: ...}}``)
      need an extension this helper does NOT provide; that's a
      Pillar E or later concern.
    * The block values must be scalars (str / int / float / bool /
      None). A nested list or dict value raises ``FrontmatterError``
      with a message naming the offending key.

    Raises
    ------
    FrontmatterError:
        When ``text`` has no frontmatter delimiters; when ``key``
        already exists in the frontmatter (strict-insert); when any
        value in ``block`` is itself a list or dict (single-level
        nesting only); when ``block`` is empty (an empty block would
        produce ambiguous YAML — caller should not call with empty).
    """
    if not text.startswith("---\n"):
        raise FrontmatterError(
            "cannot insert block: text has no opening frontmatter delimiter",
        )
    if not block:
        raise FrontmatterError(
            f"cannot insert block {key!r}: block dict is empty. An empty "
            f"block would render as `{key}: {{}}` which is ambiguous; if "
            f"the caller actually wants `{key}: {{}}` they should call "
            f"add_frontmatter_field_text(text, {key!r}, {{}}) directly.",
        )
    for sub_key, sub_val in block.items():
        if isinstance(sub_val, (dict, list)):
            raise FrontmatterError(
                f"cannot insert block {key!r}: nested key "
                f"{sub_key!r} has type {type(sub_val).__name__}; "
                f"this helper supports one level of nesting only "
                f"(scalar values under the top-level block key).",
            )
    end = _frontmatter_split(text)
    fm_with_nl = text[4 : end + 1]
    line_re = re.compile(rf"^{re.escape(key)}:", re.MULTILINE)
    if line_re.search(fm_with_nl):
        raise FrontmatterError(
            f"cannot insert block {key!r}: already present in frontmatter. "
            f"The caller should have detected idempotence or value-mismatch "
            f"before calling add_frontmatter_block_text.",
        )
    indent_str = " " * indent
    lines = [f"{key}:"]
    for sub_key, sub_val in block.items():
        formatted = _format_yaml_value(sub_val)
        lines.append(f"{indent_str}{sub_key}: {formatted}")
    new_fm = fm_with_nl + "\n".join(lines) + "\n"
    return text[:4] + new_fm + text[end + 1 :]


def extend_frontmatter_nested_block_text(
    text: str,
    parent_key: str,
    child_key: str,
    child_block: dict,
    indent: int = 2,
) -> str:
    """Insert ``<child_key>:`` followed by a nested mapping block as the
    last child of an existing top-level ``<parent_key>:`` block.

    Sibling to :func:`add_frontmatter_block_text` for nested-map
    extension. Pillar E Week 9-11 vault migration 0005 (per ADR-0036
    D168) ships the ``discovery_lineage:`` sub-block inside the
    existing ``identity_keys:`` block; future Pillar E (or Pillar I)
    migrations needing similar nested-block insertion import this
    helper.

    Preserves every other line + comment in the frontmatter block.
    The new sub-block appears as the last child of ``parent_key``,
    BEFORE the next top-level field (or end of frontmatter).

    Strict insert — refuses to update an existing ``<child_key>``;
    refuses if ``<parent_key>`` is not present at the top level;
    refuses if any value in ``child_block`` is itself a list or
    dict (single-level nesting only). The caller handles idempotence
    (skip if the child is already present with the desired shape)
    before calling.

    Output shape — for ``parent_key="identity_keys"``,
    ``child_key="discovery_lineage"``, ``indent=2``:

    >>> text = "---\\ntype: person\\nidentity_keys:\\n  linkedin: in/foo\\n---\\n"
    >>> extend_frontmatter_nested_block_text(
    ...     text, "identity_keys", "discovery_lineage",
    ...     {"source_skill": "find-leads"},
    ... )
    '---\\ntype: person\\nidentity_keys:\\n  linkedin: in/foo\\n  discovery_lineage:\\n    source_skill: find-leads\\n---\\n'

    The new child's children are double-indented (``2 * indent``)
    matching YAML nested-map convention.

    Raises
    ------
    FrontmatterError:
        When ``text`` has no frontmatter delimiters; when
        ``<parent_key>:`` is not present at the top level; when
        ``<child_key>`` is already present as a direct child of
        ``<parent_key>``; when ``child_block`` is empty; when any
        value in ``child_block`` is itself a list or dict.
    """
    if not text.startswith("---\n"):
        raise FrontmatterError(
            "cannot insert nested block: text has no opening frontmatter delimiter",
        )
    if not child_block:
        raise FrontmatterError(
            f"cannot insert nested block {parent_key!r}.{child_key!r}: "
            f"child_block is empty",
        )
    for sub_key, sub_val in child_block.items():
        if isinstance(sub_val, (dict, list)):
            raise FrontmatterError(
                f"cannot insert nested block {parent_key!r}.{child_key!r}: "
                f"nested key {sub_key!r} has type {type(sub_val).__name__}; "
                f"this helper supports one level of nesting only "
                f"(scalar values under the child_key)."
            )

    end = _frontmatter_split(text)
    fm_with_nl = text[4 : end + 1]
    fm_lines = fm_with_nl.split("\n")

    # Find the parent_key line at top level (indent=0, no leading whitespace).
    parent_re = re.compile(rf"^{re.escape(parent_key)}:")
    parent_idx = -1
    for i, line in enumerate(fm_lines):
        if parent_re.match(line):
            parent_idx = i
            break
    if parent_idx == -1:
        raise FrontmatterError(
            f"cannot insert nested block: parent_key {parent_key!r} "
            f"not found at top level of frontmatter",
        )

    # Per Week 9-11 review P2-A — refuse-loud on inline-value parents
    # (e.g., `identity_keys: {}` or `identity_keys: scalar`). The helper
    # supports only block-mapping parents — appending child lines after
    # an inline parent line produces malformed YAML that `safe_load`
    # rejects, silently corrupting the Person note on the atomic write.
    # The asymmetric-failure-cost calculus per PILLAR-PLAN §0 says
    # refuse-loud is correct (false-positive refuse is recoverable;
    # false-negative silent corruption requires per-file repair).
    parent_inline_re = re.compile(
        rf"^{re.escape(parent_key)}:\s*\S",
    )
    if parent_inline_re.match(fm_lines[parent_idx]):
        raise FrontmatterError(
            f"cannot insert nested block under {parent_key!r}: parent "
            f"key has an inline value ({fm_lines[parent_idx]!r}); "
            f"this helper supports only block-mapping parents. The "
            f"caller should rewrite the parent to block-mapping form "
            f"first (e.g., remove `: {{}}` and let children imply the "
            f"mapping)."
        )

    indent_str = " " * indent

    # Walk lines after parent — any line at indent >= `indent` chars is
    # part of parent's subtree (including deeper-nested grandchildren
    # like YAML list items). Stop at first line that isn't.
    insert_idx = parent_idx + 1
    while insert_idx < len(fm_lines):
        line = fm_lines[insert_idx]
        if line == "":
            # Empty line ends the parent's subtree (or end of frontmatter).
            break
        if not line.startswith(indent_str):
            break
        insert_idx += 1

    # Check if child_key already exists as a direct child of parent_key.
    direct_child_re = re.compile(rf"^{indent_str}{re.escape(child_key)}:")
    for i in range(parent_idx + 1, insert_idx):
        if direct_child_re.match(fm_lines[i]):
            raise FrontmatterError(
                f"cannot insert nested block {parent_key!r}.{child_key!r}: "
                f"child already present in frontmatter. The caller should "
                f"have detected idempotence or value-mismatch before calling.",
            )

    # Build the new sub-block lines.
    sub_indent_str = " " * (2 * indent)
    new_lines = [f"{indent_str}{child_key}:"]
    for sub_key, sub_val in child_block.items():
        formatted = _format_yaml_value(sub_val)
        new_lines.append(f"{sub_indent_str}{sub_key}: {formatted}")

    # Splice into the frontmatter.
    fm_lines = fm_lines[:insert_idx] + new_lines + fm_lines[insert_idx:]
    new_fm = "\n".join(fm_lines)
    return text[:4] + new_fm + text[end + 1 :]


def remove_frontmatter_nested_field_text(
    text: str,
    parent_key: str,
    child_key: str,
    indent: int = 2,
) -> str:
    """Remove a nested sub-block from inside an existing top-level block.

    Inverse of :func:`extend_frontmatter_nested_block_text`. Preserves
    the rest of the parent block + every other line + comment. If the
    child is absent OR the parent is absent, returns ``text`` unchanged
    (idempotent — vault migration downgrade re-run is safe).

    Removes ONLY immediate children of the named parent. A deeper-
    nested key cannot be removed; that's a yet-deeper transformation
    requiring a YAML round-trip.

    Raises
    ------
    FrontmatterError:
        When ``text`` has no frontmatter delimiters. Absence of the
        parent OR the child is NOT an error (idempotent removal).
    """
    if not text.startswith("---\n"):
        raise FrontmatterError(
            "cannot remove nested field: text has no opening frontmatter delimiter",
        )
    end = _frontmatter_split(text)
    fm_with_nl = text[4 : end + 1]
    fm_lines = fm_with_nl.split("\n")

    indent_str = " " * indent
    child_prefix = f"{indent_str}{child_key}:"
    sub_indent_str = " " * (2 * indent)

    parent_re = re.compile(rf"^{re.escape(parent_key)}:")
    parent_idx = -1
    for i, line in enumerate(fm_lines):
        if parent_re.match(line):
            parent_idx = i
            break
    if parent_idx == -1:
        return text  # idempotent: parent absent

    # Find the child line at the child indent.
    child_start_idx = -1
    for i in range(parent_idx + 1, len(fm_lines)):
        line = fm_lines[i]
        if line == "" or not line.startswith(indent_str):
            break  # end of parent's children — child not present
        if line.startswith(child_prefix) and (
            len(line) == len(child_prefix) or line[len(child_prefix)] in " \t"
        ):
            child_start_idx = i
            break
    if child_start_idx == -1:
        return text  # idempotent: child absent under parent

    # Find end of child block: first line at indent < sub_indent (i.e.,
    # not a grandchild). That line is the next sibling-of-child OR the
    # next top-level field OR end of parent's subtree.
    child_end_idx = child_start_idx + 1
    while child_end_idx < len(fm_lines):
        line = fm_lines[child_end_idx]
        if line == "":
            break
        if not line.startswith(sub_indent_str):
            break
        child_end_idx += 1

    fm_lines = fm_lines[:child_start_idx] + fm_lines[child_end_idx:]
    new_fm = "\n".join(fm_lines)
    return text[:4] + new_fm + text[end + 1 :]


def _format_yaml_value(value: object) -> str:
    """Render a Python value as a YAML scalar suitable for inline use.

    Booleans / None / ints / dates render unquoted. Strings containing
    YAML-significant characters get single-quoted. Other types pass
    through ``str()``.

    This is deliberately narrow — vault migrations stamp simple scalars
    (int versions, ISO dates, str slugs). Complex nested values are not
    supported via this helper; a migration that needs to write a nested
    map / list should round-trip through ``yaml.safe_dump`` instead.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return ""
    s = str(value)
    if any(c in s for c in [":", "#", "[", "]", "{", "}", ","]):
        return "'" + s.replace("'", "''") + "'"
    return s


def write_person_frontmatter_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via tmp-then-rename.

    Same atomicity contract as
    :func:`orchestrator.migrations.state.save_state_atomic`:

    * Write the entire payload to ``<path>.tmp`` and ``fsync`` before
      ``os.replace``.
    * ``os.replace`` is atomic on POSIX when source + target are on the
      same filesystem (they are — we write the tmp file beside the
      target).
    * A crash between open and rename leaves ``path`` untouched. A
      crash between fsync and rename leaves a recoverable tmp file
      that the next write will overwrite via ``O_TRUNC``.

    No per-file lock — the migration's contract is single-writer. If
    two ``apply`` calls race against the same Person note, the
    framework's state-file lock serializes them at the migration level,
    not the per-file level. (Operators are expected to quit Obsidian
    Sync before running vault migrations; ADR-0011 D9 documents the
    risk + warning surface.)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def iter_person_notes(
    vault_dir: Path,
    people_subdir: str = "10 People",
) -> Iterator[Path]:
    """Yield every ``*.md`` candidate under ``<vault_dir>/<people_subdir>/``.

    Walks recursively (Obsidian-Sync layouts nest by status, e.g.
    ``10 People/active/Foo.md``, ``10 People/contacted/Bar.md``). Skips:

    * Hidden files / directories (path components starting with ``.``).
    * Obsidian Sync conflict files — every variant the sync engine
      produces (legacy desktop + iCloud-backed) via
      :func:`is_obsidian_conflict_file`. These are sync-engine
      artifacts, not Person notes; rewriting them would compound the
      conflict.

    Does NOT filter by ``type: person`` — that's the caller's job after
    reading frontmatter (the iterator can't know without re-reading).
    The migration calls :func:`read_person_frontmatter` +
    :func:`is_person_note` per yield.

    Yields nothing when ``<vault_dir>/<people_subdir>/`` does not exist
    (the migration logs zero affected_count and the runner marks
    applied — a vault with no Person notes is a legitimate edge case,
    not a failure).

    The ``people_subdir`` default ``"10 People"`` matches the convention
    from :func:`orchestrator.identity._vault_people_dir` and the
    ``vault.people_dir`` operator config field's default. Migrations
    that need to honor an operator-configured override read the config
    themselves and pass it explicitly — adding a config-loading
    side-effect inside this helper would couple the iterator to
    operator-config shape.
    """
    yield from _iter_notes(vault_dir / people_subdir)


def iter_touch_notes(
    vault_dir: Path,
    conversations_subdir: str = "40 Conversations",
) -> Iterator[Path]:
    """Yield every ``*.md`` candidate under
    ``<vault_dir>/<conversations_subdir>/``.

    Sibling to :func:`iter_person_notes` for touch notes (one note
    per cold-touch send; live in ``40 Conversations/`` by convention).
    Same skip rules: hidden files + Obsidian Sync conflict files.

    Pillar B Week 6 second follow-up addition per
    `.planning/REVIEW-pillar-b-pillar-c-readiness.md` §P3-3 — Pillar
    C vault migrations will need to walk touch notes to stamp
    LinkedIn-specific fields (e.g. ``li_invite_intent_id:``,
    ``li_invite_confirmed_at:``). Pre-this-helper, ledger/0002
    inlined its own walk; Pillar C author had no convenience wrapper
    and risked inlining a third copy. The wrapper centralizes the
    pattern so future migrations import rather than re-implement.

    Does NOT filter by ``type: touch`` — caller filters via
    :func:`is_touch_note` after reading frontmatter (same shape as
    :func:`iter_person_notes`).
    """
    yield from _iter_notes(vault_dir / conversations_subdir)


def _iter_notes(notes_dir: Path) -> Iterator[Path]:
    """Shared walk used by :func:`iter_person_notes` +
    :func:`iter_touch_notes`. Centralizes the skip rules + the
    sorted-rglob recursion so a future contributor adding a third
    typed-note iterator inherits identical behavior."""
    if not notes_dir.exists():
        return
    for note in sorted(notes_dir.rglob("*.md")):
        rel = note.relative_to(notes_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if is_obsidian_conflict_file(note.name):
            continue
        yield note
