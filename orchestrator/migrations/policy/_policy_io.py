"""Per-file IO surface for policy migrations.

Policy migrations rewrite ``~/.outreach-factory/policies/*.yml`` files —
the SoT for "what rules are active." Each policy file declares
``version:`` at the top; the engine's
:mod:`orchestrator.policy.engine.load_rules_from_yaml` consumes the
file's version to gate "this build knows how to read this file."

This module exposes:

* :func:`iter_policy_files` — walks ``<policy_dir>/*.yml`` (non-recursive),
  yielding every candidate policy file in sorted order. Skips hidden
  files + Obsidian Sync conflict files (same convention as vault).
* :func:`read_policy_file` — parse a policy YAML file. Returns
  ``(parsed_dict, raw_text)`` so the migration has the structured
  shape for version / shape validation AND the raw text for surgical
  edits that preserve comments + field ordering.
* :func:`write_policy_file_atomic` — tmp-then-rename atomic write.
  Mirrors the durability bar set by
  :func:`orchestrator.migrations.vault._vault_io.write_person_frontmatter_atomic`
  and :func:`orchestrator.migrations.state.save_state_atomic`.
* :func:`add_top_level_field_text` — surgical insert of a scalar
  top-level field. Inserted immediately after the ``version:`` line so
  the insertion point is deterministic + predictable across files.
  Refuses if the field is already present (the caller is responsible
  for the idempotence check).
* :func:`add_top_level_block_text` — surgical insert of a multi-line
  block (top-level key whose value is a single-level map of scalars).
  Same insertion semantics as :func:`add_top_level_field_text`.
* :func:`remove_top_level_field_text` /
  :func:`remove_top_level_block_text` — surgical delete inverses.
  Both are idempotent — removing an absent field is a no-op so
  downgrade re-runs are safe.
* :func:`bump_version_text` — rewrite the ``version:`` line from one
  value to another. Refuses if the current value isn't ``from_version``
  — same defense-in-depth posture as the vault migration's
  ``existing == SCHEMA_VERSION_VALUE`` check.

The atomicity model is per-file: each policy migration rewrites every
``.yml`` file in the policy dir one at a time, each via tmp-then-rename.
A crash during the batch leaves every file in either the pre-migration
shape or the post-migration shape, never half-written. The runner's
state file tracks batch-level atomicity (the migration is marked
applied iff every file was successfully rewritten).

Why surgical edits (not ``yaml.safe_dump`` round-trip)
-------------------------------------------------------

The factory-shipped ``config-template/cooldowns.example.yml`` is 275
lines, most of which are commented-out rule templates (Rules 7–13 are
commented templates the operator can uncomment + tune). A YAML
round-trip via ``yaml.safe_dump`` would:

* Drop every comment (the round-trip parses the YAML to a dict, then
  re-serializes; comments live in the original text but not the parse
  tree).
* Normalize quote styles (operator's hand-quoted strings become
  unquoted; unquoted strings get re-quoted).
* Reorder fields (insertion order vs alphabetical depends on Python
  version).

For a 275-line file where ~80% is operator-meaningful comments, a
round-trip destroys most of the file's value. The surgical-edit pattern
matches what ADR-0011 D10 specifies for vault migrations + what
:func:`orchestrator.reconcile._write_pipeline_stage` uses for the only
other in-place YAML mutation in the orchestrator.

Insertion point convention
--------------------------

Every helper that inserts new top-level content places it immediately
after the ``version:`` line — NOT at the end of the file. The rationale:

* ``rules:`` is a top-level block-map that spans most of the file body.
  Appending after ``rules:`` would put the new field inside the block,
  changing its meaning.
* Appending BEFORE ``rules:`` is the right placement, and immediately
  after ``version:`` is the deterministic "before rules" point.
* The operator-facing diff is minimal: one block-of-lines inserted in
  a predictable location; every other line byte-identical.

See ADR-0012 for the policy-migration-specific design.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator

import yaml


# Regex matching a top-level ``version:`` line. The value can be an
# unquoted integer (``version: 1``), a single-quoted string
# (``version: '1'``), or a double-quoted string (``version: "1"``). The
# engine's ``load_rules_from_yaml`` accepts all three via ``yaml.safe_load``;
# the migration must handle the same forms when surgically rewriting.
#
# Anchored to start-of-line + re.MULTILINE so it matches only top-level
# occurrences, not nested ``version:`` fields inside a rule entry (rule
# fields are always indented by at least 4 spaces under ``rules:``).
#
# Critical: the prefix uses ``[ \t]*`` (NOT ``\s*``) and the suffix
# uses ``[ \t]*`` so the regex consumes ONLY inline whitespace + a
# trailing comment. Using ``\s*`` would let the regex greedily consume
# trailing newlines (and any blank lines that follow), shifting the
# insertion point past content that should stay where it is.
_VERSION_LINE_RE = re.compile(
    r"^(version:[ \t]*)(['\"]?)(\d+)(['\"]?)([ \t]*(?:#.*)?)$",
    re.MULTILINE,
)


class PolicyFileError(ValueError):
    """Raised on shape violations a policy migration cannot recover from.

    Distinct from "this file looks fine but doesn't match the migration's
    preconditions" — the migration handles its own preconditions (e.g.
    refusing on a wrong version value). ``PolicyFileError`` is reserved
    for IO-level failures the helpers detect:

    * Unparseable YAML (the file's syntax is broken).
    * Missing ``version:`` line where the migration expects one.
    * :func:`add_top_level_field_text` / :func:`add_top_level_block_text`
      invoked with a key that's already present in the file — the caller
      is responsible for the idempotence check + must skip BEFORE
      calling the insert helper. The helper refuses to silently clobber.
    * :func:`bump_version_text` invoked with a ``from_version`` that
      doesn't match the file's current version.

    Migrations propagate this error so the runner refuses to mark the
    migration applied (the state-file pointer doesn't move) and the
    operator can fix the offending file before re-running ``apply``.
    """


def iter_policy_files(policy_dir: Path) -> Iterator[Path]:
    """Yield every ``*.yml`` policy file under ``policy_dir`` (sorted).

    Non-recursive — policy files live directly under
    ``~/.outreach-factory/policies/``, NOT in subdirectories (unlike
    the vault's nested ``10 People/active/`` layout). Yields files in
    name-sorted order so test fixtures get deterministic iteration.

    Skips:

    * Hidden files (``.foo.yml``, ``.DS_Store``, etc.). The Obsidian
      vault analog (``_vault_io.iter_person_notes``) skips hidden
      directories too; policy dir is flat so only file-level skip
      matters.
    * Obsidian Sync conflict files (``*.conflicted.yml``,
      ``*.conflict.yml``). Operators who keep their policy dir under
      Obsidian Sync occasionally see these; rewriting them would
      compound the conflict.

    Does NOT filter by content — the iterator yields every ``.yml`` file
    regardless of shape. Migrations call :func:`read_policy_file` per
    yield and decide whether to act based on the parsed dict.

    Yields nothing when ``policy_dir`` does not exist (a fresh state
    directory with no policy files is a legitimate zero-file state).

    The handler does NOT walk ``~/.outreach-factory/suppressions/`` —
    suppression YAML files are a separate SoT (per ``SOURCES-OF-TRUTH.md``
    row "Suppression list") with their own
    ``SUPPORTED_SUPPRESSION_SCHEMA_VERSION``. A future migration that
    targets suppressions would walk a different directory + use this
    helper module's primitives the same way the policy-dir walk does.

    Parameters
    ----------
    policy_dir:
        Path to a directory containing ``*.yml`` policy files. May not
        exist yet (yields nothing).

    Yields
    ------
    Path:
        Sorted candidate policy file paths.
    """
    policy_dir = Path(policy_dir)
    if not policy_dir.exists():
        return
    for f in sorted(policy_dir.glob("*.yml")):
        if f.name.startswith("."):
            continue
        if ".conflicted." in f.name or f.name.endswith(".conflict.yml"):
            continue
        yield f


def read_policy_file(path: Path) -> tuple[dict, str]:
    """Parse a policy YAML file. Returns ``(parsed_dict, raw_text)``.

    The raw text is what surgical-edit helpers operate on (to preserve
    comments + field ordering); the parsed dict is for the migration's
    shape validation (version check, idempotence check, etc.).

    Both forms are returned so the migration body doesn't have to read
    the file twice or duplicate the parse.

    CRLF handling: matches the vault helper's posture — normalize CRLF
    to LF on read; write side always writes LF. A policy file edited on
    Windows or by a cross-platform sync tool becomes LF after the
    migration. macOS-native operators (the primary platform) see no
    change.

    Raises
    ------
    PolicyFileError:
        * The file is unreadable (OS error).
        * The file's YAML is unparseable.
        * The file's top-level YAML resolves to something other than a
          mapping (e.g. a bare list, a scalar). Policy files MUST be
          maps at the top level — the engine's
          :func:`load_rules_from_yaml` enforces the same.
        * The file is empty or contains only ``---`` / whitespace.
          A blank policy file is a contributor mistake the migration
          framework should not paper over — the engine returns ``[]``
          from such a file (which gracefully degrades to "no rules"
          per ADR-0001), but a migration that tries to bump the version
          of an empty file has nothing meaningful to do.

    Parameters
    ----------
    path:
        Path to a ``.yml`` policy file.

    Returns
    -------
    tuple[dict, str]:
        ``(parsed_dict, raw_text)`` — both views of the same file. The
        raw text is CRLF-normalized.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyFileError(f"could not read {path}: {exc}") from exc

    if "\r\n" in text:
        text = text.replace("\r\n", "\n")

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PolicyFileError(
            f"unparseable YAML in policy file {path}: {exc}",
        ) from exc

    if data is None:
        raise PolicyFileError(
            f"policy file {path} is empty or contains only delimiters; "
            f"a migration cannot meaningfully operate on a blank file. "
            f"Either delete the file or add a `version:` declaration.",
        )

    if not isinstance(data, dict):
        raise PolicyFileError(
            f"policy file {path}: top-level must be a mapping, got "
            f"{type(data).__name__}. Migrations cannot operate on a "
            f"non-mapping policy file.",
        )

    return data, text


def write_policy_file_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via tmp-then-rename.

    Same atomicity contract as
    :func:`orchestrator.migrations.vault._vault_io.write_person_frontmatter_atomic`
    and :func:`orchestrator.migrations.state.save_state_atomic`:

    * Write the entire payload to ``<path>.tmp`` and ``fsync`` before
      ``os.replace``.
    * ``os.replace`` is atomic on POSIX when source + target are on the
      same filesystem (they are — we write the tmp file beside the
      target).
    * A crash between open and rename leaves ``path`` untouched. A
      crash between fsync and rename leaves a recoverable tmp file
      that the next write will overwrite via ``O_TRUNC``.

    No per-file lock — the migration's contract is single-writer. If
    two ``apply`` calls race against the same policy file, the
    framework's state-file lock serializes them at the migration level,
    not the per-file level. (Operators are expected to quiesce the
    dispatcher before running policy migrations; ADR-0012 D-quiescence
    documents the rationale.)

    Parameters
    ----------
    path:
        Where to write.
    text:
        Full file contents. Written as UTF-8 LF.
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


def _find_version_line_end(text: str) -> int:
    """Return the offset just AFTER the ``version:`` line's newline.

    The version line is the deterministic insertion point for new
    top-level fields + blocks. Subsequent inserts go immediately after
    this offset.

    Raises
    ------
    PolicyFileError:
        If no top-level ``version:`` line is present. Every policy file
        the engine accepts declares ``version:``; a file without it is
        either pre-versioning shape (which the engine refuses to load
        with a different error) or operator-corrupted.
    """
    m = _VERSION_LINE_RE.search(text)
    if m is None:
        raise PolicyFileError(
            "no top-level `version:` line found; the helper cannot "
            "determine the insertion point. Every policy file must "
            "declare `version:` at the top level — see "
            "`config-template/cooldowns.example.yml` for the canonical "
            "shape.",
        )
    # m.end() points at the end of the matched content (excluding the
    # trailing newline because $ in MULTILINE matches BEFORE \n). The
    # newline character is at m.end(); we want to insert AFTER it.
    end = m.end()
    if end < len(text) and text[end] == "\n":
        return end + 1
    return end


def _top_level_key_present(text: str, key: str) -> bool:
    """True if ``key`` appears as a top-level YAML field.

    Top-level means: at column 0, followed by ``:``. Nested keys (under
    ``rules:`` etc., indented by 2+ spaces) are NOT matched. Comment
    lines that mention the key are also not matched (the regex anchors
    the key at start-of-line).
    """
    pattern = re.compile(rf"^{re.escape(key)}:", re.MULTILINE)
    return pattern.search(text) is not None


def _format_yaml_scalar(value: object) -> str:
    """Render a Python value as a YAML scalar suitable for inline use.

    Booleans / None / ints / dates render unquoted. Strings containing
    YAML-significant characters get single-quoted. Other types pass
    through ``str()``. Mirrors
    :func:`orchestrator.migrations.vault._vault_io._format_yaml_value`.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return ""
    s = str(value)
    # Strings always get single-quoted to be safe — version strings
    # like "0.1.0" need quoting (the dot doesn't force it but YAML
    # would parse ``0.1.0`` as the float 0.1 followed by `.0` which is
    # nonsense, and ``0.1`` alone would parse as 0.1). The defensive
    # quoting matches the cooldowns.example.yml convention where every
    # string value is quoted (``reason: "Already cold-pitched ..."``).
    if any(c in s for c in [":", "#", "[", "]", "{", "}", ",", " ", "."]):
        return "'" + s.replace("'", "''") + "'"
    return s


def add_top_level_field_text(text: str, key: str, value: object) -> str:
    """Insert ``<key>: <value>`` as a new top-level scalar line.

    Inserts immediately after the ``version:`` line (per the
    insertion-point convention documented at the module level).
    Preserves every other line + comment in the file.

    Strict insert — refuses to update an existing field. The caller is
    responsible for skipping files where ``key`` is already present
    (idempotence) and for choosing the value-mismatch policy (refuse
    loud is the default).

    Parameters
    ----------
    text:
        The file's current contents.
    key:
        Top-level YAML key to insert.
    value:
        Scalar value (rendered via :func:`_format_yaml_scalar`).

    Returns
    -------
    str:
        The updated text.

    Raises
    ------
    PolicyFileError:
        * No ``version:`` line found (no deterministic insertion
          point).
        * ``key`` already exists as a top-level field — the caller
          should have detected idempotence before calling.
    """
    if _top_level_key_present(text, key):
        raise PolicyFileError(
            f"cannot insert top-level field {key!r}: already present. "
            f"The caller should detect idempotence + skip BEFORE "
            f"calling add_top_level_field_text.",
        )
    insert_at = _find_version_line_end(text)
    formatted = _format_yaml_scalar(value)
    new_line = f"{key}: {formatted}\n"
    return text[:insert_at] + new_line + text[insert_at:]


def add_top_level_block_text(text: str, key: str, block: dict) -> str:
    """Insert a multi-line top-level block: ``<key>:`` + indented children.

    Inserts immediately after the ``version:`` line, like
    :func:`add_top_level_field_text`. The block renders as:

    .. code-block:: yaml

        <key>:
          <child_1>: <value_1>
          <child_2>: <value_2>

    Two-space indentation matches the YAML style used in the factory
    ``config-template/cooldowns.example.yml`` (rule entries are
    two-space indented under ``rules:``).

    The ``block`` dict's keys are inserted in dict-iteration order
    (Python 3.7+ preserves insertion order in dicts). Migrations that
    need a specific child ordering construct the dict accordingly.

    Strict insert — refuses to update an existing top-level field. The
    caller is responsible for the idempotence check.

    Single-level map only — values must be scalars (no nested dicts /
    lists). A future migration needing deeper structure either adds a
    dedicated helper or accepts a string-rendered YAML fragment.

    Parameters
    ----------
    text:
        The file's current contents.
    key:
        Top-level YAML key to insert.
    block:
        Mapping of child-name → scalar-value.

    Returns
    -------
    str:
        The updated text.

    Raises
    ------
    PolicyFileError:
        * No ``version:`` line found.
        * ``key`` already exists as a top-level field.
        * Any value in ``block`` is itself a mapping or list (the
          single-level-map contract; nested shapes need a more capable
          helper).
    """
    if _top_level_key_present(text, key):
        raise PolicyFileError(
            f"cannot insert top-level block {key!r}: already present. "
            f"The caller should detect idempotence + skip BEFORE "
            f"calling add_top_level_block_text.",
        )
    for child_key, child_val in block.items():
        if isinstance(child_val, (dict, list)):
            raise PolicyFileError(
                f"add_top_level_block_text accepts single-level maps "
                f"only; got nested {type(child_val).__name__} for "
                f"child key {child_key!r}. Use a different helper for "
                f"deeper structure.",
            )
    insert_at = _find_version_line_end(text)
    lines = [f"{key}:"]
    for child_key, child_val in block.items():
        formatted = _format_yaml_scalar(child_val)
        lines.append(f"  {child_key}: {formatted}")
    new_block = "\n".join(lines) + "\n"
    return text[:insert_at] + new_block + text[insert_at:]


def remove_top_level_field_text(text: str, key: str) -> str:
    """Delete a top-level scalar field. Inverse of
    :func:`add_top_level_field_text`.

    Removes the line matching ``^<key>: ...$``. Idempotent — absence of
    the field returns ``text`` unchanged (downgrade re-run is safe).

    Removes ONLY single-line top-level fields. Multi-line blocks need
    :func:`remove_top_level_block_text`.

    Parameters
    ----------
    text:
        The file's current contents.
    key:
        Top-level YAML key to remove.

    Returns
    -------
    str:
        The updated text (or ``text`` unchanged if the key was absent).
    """
    # Match the exact line `<key>: ...` (including any trailing comment),
    # consuming the newline after the line.
    line_re = re.compile(rf"^{re.escape(key)}:[^\n]*\n", re.MULTILINE)
    return line_re.sub("", text, count=1)


def remove_top_level_block_text(text: str, key: str) -> str:
    """Delete a top-level multi-line block. Inverse of
    :func:`add_top_level_block_text`.

    Removes the ``<key>:`` line + every subsequent indented continuation
    line (lines starting with one or more spaces / tabs). Stops at the
    first non-indented line — top-level field, blank line, or comment
    at column 0. Idempotent — absence of the block returns ``text``
    unchanged.

    Why stop at blank lines (not consume them)
    ------------------------------------------

    A blank line after a block is operator-meaningful spacing — they
    likely placed it as a visual separator between the block and the
    next top-level construct. Consuming it would silently delete
    operator formatting that wasn't part of the block. Per the
    surgical-edit principle (ADR-0011 D10, ADR-0012 D-surgical-edit):
    inverse operations should restore the file to the byte-identical
    pre-insert shape.

    A consequence: if the block ITSELF contains a blank line between
    its children (rare but possible), this remove function stops at the
    blank line and leaves orphan children behind. The caller's
    contract: this helper only round-trips blocks shaped like those
    :func:`add_top_level_block_text` produces (no internal blank lines).
    Operators who hand-edit a block with blank-line spacing in the
    middle need a more sophisticated helper.

    Parameters
    ----------
    text:
        The file's current contents.
    key:
        Top-level YAML block-key to remove.

    Returns
    -------
    str:
        The updated text (or ``text`` unchanged if the block was absent).
    """
    # Match: ``^<key>:.*\n`` followed by any number of indented
    # continuation lines (lines starting with at least one space / tab).
    # Stops at the first non-indented line (including blank lines, top-
    # level fields, and comments).
    pattern = re.compile(
        rf"^{re.escape(key)}:[^\n]*\n(?:[ \t]+[^\n]*\n)*",
        re.MULTILINE,
    )
    return pattern.sub("", text, count=1)


# Matches the top-level ``rules:`` header line. Captures the inline
# value (e.g. ``[]`` for the empty-list shape) so callers can detect
# the empty form + convert to multi-line.
_RULES_HEADER_RE = re.compile(
    r"^rules:[ \t]*(.*?)[ \t]*$",
    re.MULTILINE,
)

# Matches a rule-entry head line: ``  - name:`` at the canonical
# 2-space indent under ``rules:``. Anchored at column 0 + 2 spaces so
# nested keys named ``name`` (which appear under ``block_when:`` or
# elsewhere at deeper indents) are not matched.
_RULE_ENTRY_HEAD_RE = re.compile(
    r"^  - name:[ \t]+",
    re.MULTILINE,
)


def _is_rule_continuation_line(line: str) -> bool:
    """Whether ``line`` belongs to an in-progress rule entry's body.

    A rule entry's body lines are indented past the ``- `` of the entry
    head (the convention: ``  - name: ...`` is at 2 spaces; subsequent
    fields are at 4 spaces; nested maps go to 6+). A line is a
    continuation if:

    * It starts with whitespace deeper than the entry head's column
      (either ``    `` 4-space indent OR a leading tab — see
      "Tab-indent acceptance" below), AND
    * It is not blank (after lstrip).

    A blank line, or a column-0 / column-2 line, is NOT a continuation
    — it ends the rule entry.

    Inline comment acceptance
    -------------------------

    A comment line at column ≥4 IS a continuation. Operators who
    annotate fields inside a rule body (e.g. ``    # tuned down``
    between ``    type:`` and ``    max_units:``) need the comment
    line treated as inside the entry; otherwise the scanner truncates
    the entry at the comment and the migration inserts the new rule
    mid-body, corrupting the file. The earlier convention of "reject
    comment-only continuation" was a Week-7 bug caught in the per-
    week independent code review + fixed in the per-week-review
    follow-up commit; the regression sentinel lives at
    ``tests/test_migrations_policy_io.py::TestAddRuleBlockText::
    test_inline_comment_inside_rule_body_does_not_truncate``.

    Tab-indent acceptance
    ---------------------

    Tab-indented continuation lines (``\\treason: ...``) are accepted.
    Operators whose editors auto-converted spaces to tabs in one field
    would otherwise see the scanner truncate the entry at the tab line
    and the migration corrupt the file. YAML treats tabs as
    significant whitespace + most linters reject mixed indent, but the
    helper's job is to find structural boundaries in operator-edited
    YAML — not to enforce YAML style.

    A line indented by fewer than 4 spaces (and no tab) — e.g. 3
    spaces — is NOT a continuation. That's structurally a "wrong
    indent" line; refusing-to-scan stops the helper from silently
    consuming a column-2 line (which would belong to the parent list,
    not the rule entry).
    """
    has_block_indent = line.startswith("    ")
    has_tab_indent = line.startswith("\t")
    if not (has_block_indent or has_tab_indent):
        return False
    stripped = line.lstrip()
    if not stripped:
        return False
    return True


def add_rule_block_text(text: str, rule_block: str) -> str:
    """Append a rule entry to the top-level ``rules:`` list.

    Used by per-channel policy migrations (ADR-0020) to add a new
    rule entry to operator-installed ``cooldowns.yml`` files. The
    primitive that ADR-0012 D20 deferred — landed in Pillar C Week 7.

    The inserted ``rule_block`` is multi-line YAML for ONE rule entry,
    with leading 2-space indent (placing the rule under the ``rules:``
    list). Example:

    .. code-block:: python

        rule_block = (
            "  - name: linkedin-weekly-invite-cap\\n"
            "    type: budget.window-cap\\n"
            "    block_when:\\n"
            "      channel: linkedin\\n"
            "    source: linkedin_invite\\n"
            "    window_days: 7\\n"
            "    max_units: 100\\n"
            "    reason: \\"LinkedIn weekly invite cap\\"\\n"
        )

    Behavior
    --------

    * **Inline empty form** (``rules: []`` or ``rules:`` with no body):
      the ``rules:`` line is rewritten to multi-line form
      (``rules:\\n<rule_block>``).
    * **Multi-line form with entries**: ``rule_block`` is inserted
      AFTER the LAST active rule entry's last continuation line
      (the canonical APPEND semantics per ADR-0020 D73 —
      operator-installed-first ordering preserved).
    * **Multi-line form with no entries** (``rules:`` followed only
      by comments / blank lines): ``rule_block`` is inserted
      immediately after the ``rules:`` line.

    Round-trip
    ----------

    Paired with :func:`remove_rule_block_text`. The two are inverses;
    insert + remove returns byte-identical content. Verified by the
    factory-template round-trip test in
    ``tests/test_migrations_policy_0002.py::TestRealFactoryTemplateRoundTrip``.

    Parameters
    ----------
    text:
        The policy file's current contents.
    rule_block:
        Multi-line YAML for one rule entry, with 2-space leading indent
        on the ``- name:`` line. The block SHOULD end with a newline;
        if it doesn't, the helper adds one (defense-in-depth).

    Returns
    -------
    str:
        The updated text with the rule entry appended.

    Raises
    ------
    PolicyFileError:
        No top-level ``rules:`` line found — the file is not a
        recognizable policy file shape.
    """
    rules_match = _RULES_HEADER_RE.search(text)
    if rules_match is None:
        raise PolicyFileError(
            "no top-level `rules:` line found; cannot append a rule "
            "entry. Every policy file must declare `rules:` at the top "
            "level — see `config-template/cooldowns.example.yml` for "
            "the canonical shape.",
        )

    # Normalize the block — trim any trailing whitespace + ensure a
    # single trailing newline so the inserted region is well-formed
    # (no missing terminator; no stacked blank lines from a careless
    # caller string).
    block = rule_block.rstrip("\n") + "\n"

    # Inline empty form: ``rules: []`` ONLY. A bare ``rules:`` (with no
    # inline value) is the multi-line form's HEADER — entries may
    # follow on subsequent lines. Distinguishing the two:
    #
    # * ``rules: []`` — inline empty list. Group(1) captures ``[]``.
    #   The list IS empty + has no continuation. Convert to multi-line.
    # * ``rules:`` (no value) — multi-line list header. Group(1) is
    #   empty. Entries follow as ``  - name: ...`` on subsequent lines
    #   (or the list is empty because of subsequent comments/blanks
    #   only — the no-entries case handled below).
    #
    # Treating bare ``rules:`` as "inline empty" would replace the
    # header line with ``rules:\\n<rule_block>`` — duplicating ``rules:``
    # against any following content and producing an unparseable file.
    rules_value = rules_match.group(1).strip()
    if rules_value == "[]":
        # Replace the inline empty form with the multi-line shape.
        line_start = rules_match.start()
        line_end = rules_match.end()
        if line_end < len(text) and text[line_end] == "\n":
            line_end += 1
        return text[:line_start] + "rules:\n" + block + text[line_end:]

    # Multi-line form. Find the LAST `  - name:` entry under rules:.
    last_entry_head = None
    for m in _RULE_ENTRY_HEAD_RE.finditer(text, pos=rules_match.end()):
        last_entry_head = m

    if last_entry_head is None:
        # ``rules:`` is declared with neither inline value nor entries
        # (only comments + blank lines underneath). Insert right after
        # the ``rules:`` line's newline so the new entry becomes the
        # first.
        insert_at = rules_match.end()
        if insert_at < len(text) and text[insert_at] == "\n":
            insert_at += 1
        return text[:insert_at] + block + text[insert_at:]

    # Find the end of the last rule entry by scanning forward through
    # continuation lines. The entry ends at the first non-continuation
    # line (blank, comment, or de-indent).
    head_line_end = text.find("\n", last_entry_head.start())
    if head_line_end == -1:
        # Entry head at EOF with no terminating newline. Add a newline
        # + the block; the caller's text lacked a terminator.
        return text + "\n" + block
    pos = head_line_end + 1

    while pos < len(text):
        next_nl = text.find("\n", pos)
        if next_nl == -1:
            line = text[pos:]
            line_end = len(text)
        else:
            line = text[pos:next_nl]
            line_end = next_nl + 1
        if _is_rule_continuation_line(line):
            pos = line_end
            continue
        break

    insert_at = pos
    return text[:insert_at] + block + text[insert_at:]


def remove_rule_block_text(text: str, rule_name: str) -> str:
    """Delete a rule entry by canonical ``name`` from the ``rules:`` list.

    Inverse of :func:`add_rule_block_text`. Locates the rule entry whose
    ``- name: <rule_name>`` line matches (quote-tolerant: unquoted,
    single-quoted, or double-quoted form all match) and removes the
    entry's head line + every subsequent continuation line.

    Idempotent — if no rule with that name is present, returns ``text``
    unchanged. The downgrade path uses this property so re-running
    rollback after success is a no-op.

    Quote tolerance
    ---------------

    ``- name: foo``, ``- name: 'foo'``, and ``- name: "foo"`` all match.
    Operators who hand-wrote a quoted name (the factory template's
    convention for strings with spaces or special chars) are still
    detected. The quote-pair must be balanced (both single OR both
    double); mismatched quotes are an operator-corrupted state the
    helper does NOT silently fix.

    Round-trip
    ----------

    Paired with :func:`add_rule_block_text`. Insert + remove returns
    byte-identical content. See its docstring for the round-trip
    contract.

    Parameters
    ----------
    text:
        The policy file's current contents.
    rule_name:
        The canonical ``name`` value of the rule to remove. Must match
        exactly (case-sensitive). Comparison uses ``re.escape`` so
        names containing regex metachars (rare but possible) work too.

    Returns
    -------
    str:
        The updated text (or ``text`` unchanged if the name was absent).
    """
    # Quote-tolerant: optional matching open + close quote. Using a
    # named group ``q`` with backreference ``(?P=q)`` enforces balanced
    # quotes (both single OR both double, or none — not mismatched).
    pattern = re.compile(
        rf"^  - name:[ \t]+(?P<q>['\"]?){re.escape(rule_name)}"
        rf"(?P=q)[ \t]*(?:#.*)?$",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if m is None:
        return text

    entry_start = m.start()
    head_line_end = text.find("\n", m.start())
    if head_line_end == -1:
        # Entry head at EOF with no newline.
        return text[:entry_start]
    pos = head_line_end + 1

    while pos < len(text):
        next_nl = text.find("\n", pos)
        if next_nl == -1:
            line = text[pos:]
            line_end = len(text)
        else:
            line = text[pos:next_nl]
            line_end = next_nl + 1
        if _is_rule_continuation_line(line):
            pos = line_end
            continue
        break

    entry_end = pos
    return text[:entry_start] + text[entry_end:]


def bump_version_text(text: str, from_version: int, to_version: int) -> str:
    """Rewrite the top-level ``version:`` line.

    Finds the ``version:`` line + replaces its numeric value, preserving
    any surrounding whitespace, quote style, and trailing comment. The
    rest of the file is byte-identical.

    Refuses if the current version isn't ``from_version`` — defense in
    depth against accidentally bumping a file whose version has drifted
    from what the migration expects. Same posture as the vault
    migration's ``existing == SCHEMA_VERSION_VALUE`` idempotence check.

    Parameters
    ----------
    text:
        The file's current contents.
    from_version:
        The integer version the file is expected to declare.
    to_version:
        The integer version to write in its place.

    Returns
    -------
    str:
        The updated text with the version line rewritten.

    Raises
    ------
    PolicyFileError:
        * No top-level ``version:`` line found.
        * The current version doesn't match ``from_version``.
    """
    m = _VERSION_LINE_RE.search(text)
    if m is None:
        raise PolicyFileError(
            "no top-level `version:` line found; cannot bump.",
        )
    current = int(m.group(3))
    if current != from_version:
        raise PolicyFileError(
            f"bump_version_text expected current version "
            f"{from_version!r} but found {current!r}. The caller "
            f"should detect this mismatch + decide whether to skip "
            f"(idempotence) or refuse (corrupt state).",
        )
    # Reconstruct the line preserving prefix + quotes + suffix.
    prefix, open_q, _old_value, close_q, suffix = m.groups()
    new_line = f"{prefix}{open_q}{to_version}{close_q}{suffix}"
    return text[: m.start()] + new_line + text[m.end():]
