"""Unit tests for the vault-migration helper module.

Covers ``orchestrator.migrations.vault._vault_io``:

* ``read_person_frontmatter`` — parses well-formed frontmatter, returns
  ``(None, body)`` for files without frontmatter, raises on malformed YAML.
* ``is_note_type`` — canonical predicate consolidated in Week 6's
  holistic-review follow-up. The base operation other type-predicates
  delegate to.
* ``is_person_note`` / ``is_touch_note`` — thin wrappers over
  :func:`is_note_type` for the two common note types.
* ``add_frontmatter_field_text`` / ``remove_frontmatter_field_text`` —
  surgical insert / delete preserving every other line + comment.
* ``write_person_frontmatter_atomic`` — tmp-then-rename atomicity under
  simulated mid-rename crash; recovers cleanly on next write.
* ``iter_person_notes`` — walks recursively, skips hidden + conflict files.

No real ``apply`` / ``runner`` exercise here — those live in
``test_migrations_vault_0001.py`` and ``test_migrations_runner.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from orchestrator.migrations.vault._vault_io import (
    FrontmatterError,
    add_frontmatter_block_text,
    add_frontmatter_field_text,
    extend_frontmatter_nested_block_text,
    is_note_type,
    is_obsidian_conflict_file,
    is_person_note,
    is_touch_note,
    iter_person_notes,
    iter_touch_notes,
    read_person_frontmatter,
    remove_frontmatter_field_text,
    remove_frontmatter_nested_field_text,
    write_person_frontmatter_atomic,
)


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Isolated vault root per test, with `<vault>/10 People/` ready."""
    v = tmp_path / "vault"
    (v / "10 People").mkdir(parents=True)
    return v


def _write_person(
    vault_dir: Path, name: str, frontmatter: str, body: str = "body content\n",
) -> Path:
    """Write a synthetic Person note. ``frontmatter`` is the body of the
    YAML block (without the surrounding ``---`` delimiters)."""
    note = vault_dir / "10 People" / f"{name}.md"
    note.write_text(
        f"---\n{frontmatter}\n---\n{body}", encoding="utf-8",
    )
    return note


# ---------------------------------------------------------------------------
# read_person_frontmatter
# ---------------------------------------------------------------------------


class TestReadPersonFrontmatter:
    def test_parses_well_formed_frontmatter(self, vault_dir: Path):
        note = _write_person(
            vault_dir, "Foo", "name: Foo\ntype: person\nemail: foo@example.com",
        )
        fm, body = read_person_frontmatter(note)
        assert fm is not None
        assert fm["name"] == "Foo"
        assert fm["type"] == "person"
        assert fm["email"] == "foo@example.com"
        assert body == "body content\n"

    def test_no_frontmatter_returns_none(self, tmp_path: Path):
        note = tmp_path / "no_fm.md"
        note.write_text("just body content, no delimiters\n")
        fm, body = read_person_frontmatter(note)
        assert fm is None
        assert "just body content" in body

    def test_yaml_resolves_to_string_returns_none(self, vault_dir: Path):
        """An Obsidian sub-note may use `---` as a horizontal rule rather
        than a frontmatter delimiter. The 'frontmatter' parses as a
        string, not a dict; treat as not-a-Person-note + skip."""
        note = vault_dir / "10 People" / "subnote.md"
        note.write_text(
            "---\nsome notes about a person\n---\nmore notes\n",
            encoding="utf-8",
        )
        fm, body = read_person_frontmatter(note)
        assert fm is None  # parsed to a string, not a dict — skip

    def test_corrupt_yaml_raises(self, vault_dir: Path):
        """Frontmatter delimiters present but YAML is malformed."""
        note = vault_dir / "10 People" / "broken.md"
        note.write_text(
            "---\nname: Foo\n  unbalanced: [\n---\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(FrontmatterError, match="unparseable"):
            read_person_frontmatter(note)

    def test_missing_file_raises(self, vault_dir: Path):
        ghost = vault_dir / "10 People" / "does_not_exist.md"
        with pytest.raises(FrontmatterError, match="could not read"):
            read_person_frontmatter(ghost)

    def test_crlf_file_parses_as_person_note(self, vault_dir: Path):
        """Files written with Windows CRLF line endings should parse as
        Person notes after normalization. Without normalization, the
        regex (which uses literal `\\n`) would fail and the file would
        be silently treated as a non-Person file. The asymmetric-
        failure-cost calculus forbids silent skip on a file that IS a
        Person note."""
        note = vault_dir / "10 People" / "Windows.md"
        # Write with explicit CRLF.
        note.write_bytes(
            b"---\r\nname: Win\r\ntype: person\r\nemail: win@x.com\r\n"
            b"---\r\nbody content\r\n"
        )
        fm, body = read_person_frontmatter(note)
        assert fm is not None
        assert fm["type"] == "person"
        assert fm["name"] == "Win"
        assert fm["email"] == "win@x.com"


# ---------------------------------------------------------------------------
# is_person_note
# ---------------------------------------------------------------------------


class TestIsPersonNote:
    def test_true_for_type_person(self):
        assert is_person_note({"type": "person", "name": "Foo"})

    def test_false_for_other_types(self):
        assert not is_person_note({"type": "touch"})
        assert not is_person_note({"type": "company"})
        assert not is_person_note({"type": "lead-list"})

    def test_false_for_missing_type(self):
        assert not is_person_note({"name": "Foo"})

    def test_false_for_none(self):
        assert not is_person_note(None)

    def test_handles_whitespace_in_type(self):
        assert is_person_note({"type": " person "})

    def test_empty_string_type(self):
        assert not is_person_note({"type": ""})

    def test_false_for_integer_type(self):
        """A note with `type: 42` is not a Person note; the predicate
        must not crash on non-string values (a real risk if an operator
        hand-edited a YAML field to an unquoted number)."""
        assert not is_person_note({"type": 42})

    def test_false_for_boolean_type(self):
        """`type: true` (unquoted YAML boolean) is not a Person note."""
        assert not is_person_note({"type": True})

    def test_false_for_list_type(self):
        """`type: [a, b]` is not a Person note."""
        assert not is_person_note({"type": ["person", "manager"]})


# ---------------------------------------------------------------------------
# is_note_type — the consolidated shared predicate (Week 6 follow-up)
# ---------------------------------------------------------------------------


class TestIsNoteType:
    """Canonical predicate pinned at the helper level.

    Same contract as the wrapped :func:`is_person_note` /
    :func:`is_touch_note`, parameterized over the requested
    ``note_type``. Centralizes the test surface so future Pillar C / D /
    E migrations can use ``is_note_type(fm, "<new>")`` for new note
    types without re-asserting every edge case at each call site.

    Closes Pillar B holistic-review §P2-2: the consolidation pulled
    forward from the deferred Pillar I OSS sweep so Pillar C / D / E
    migrations import the canonical surface rather than re-implement
    the predicate (and risk re-introducing the Week 2 / Week 5
    non-string-`type:` crash).
    """

    def test_true_for_matching_type(self):
        assert is_note_type({"type": "company"}, "company")
        assert is_note_type({"type": "lead-list"}, "lead-list")

    def test_false_for_wrong_type(self):
        assert not is_note_type({"type": "touch"}, "person")
        assert not is_note_type({"type": "person"}, "touch")

    def test_false_for_missing_type(self):
        assert not is_note_type({"name": "Foo"}, "person")

    def test_false_for_none_fm(self):
        assert not is_note_type(None, "person")

    def test_false_for_empty_fm(self):
        assert not is_note_type({}, "person")

    def test_handles_whitespace_in_type(self):
        assert is_note_type({"type": " person "}, "person")
        assert is_note_type({"type": "\ttouch\n"}, "touch")

    def test_false_for_empty_string_type(self):
        assert not is_note_type({"type": ""}, "person")

    def test_false_for_non_string_types(self):
        """Robustness against ``type: 42`` / ``type: true`` /
        ``type: [a, b]`` — the entire reason this helper exists."""
        assert not is_note_type({"type": 42}, "person")
        assert not is_note_type({"type": True}, "person")
        assert not is_note_type({"type": None}, "person")
        assert not is_note_type({"type": ["person", "manager"]}, "person")
        assert not is_note_type({"type": {"nested": "dict"}}, "person")

    def test_is_person_note_delegates(self):
        """The legacy :func:`is_person_note` wrapper is a thin proxy
        over :func:`is_note_type` — verified by composition."""
        for fm in (
            {"type": "person"},
            {"type": " person "},
            {"type": "touch"},
            {"type": 42},
            None,
        ):
            assert is_person_note(fm) == is_note_type(fm, "person")


# ---------------------------------------------------------------------------
# is_touch_note — the sibling wrapper introduced alongside is_note_type
# ---------------------------------------------------------------------------


class TestIsTouchNote:
    """Mirrors :class:`TestIsPersonNote` for touch notes (used by
    ledger/0002's _walk_touch_records via the consolidated helper)."""

    def test_true_for_type_touch(self):
        assert is_touch_note({"type": "touch", "person": "Alice"})

    def test_false_for_person(self):
        assert not is_touch_note({"type": "person"})

    def test_false_for_missing_type(self):
        assert not is_touch_note({"date": "2026-04-10"})

    def test_false_for_non_string_type(self):
        assert not is_touch_note({"type": 42})
        assert not is_touch_note({"type": True})

    def test_false_for_none(self):
        assert not is_touch_note(None)

    def test_delegates_to_is_note_type(self):
        """Same composition pin as the is_person_note wrapper."""
        for fm in (
            {"type": "touch"},
            {"type": " touch "},
            {"type": "person"},
            {"type": 42},
            None,
        ):
            assert is_touch_note(fm) == is_note_type(fm, "touch")


# ---------------------------------------------------------------------------
# add_frontmatter_field_text
# ---------------------------------------------------------------------------


class TestAddFrontmatterFieldText:
    def test_appends_field_to_existing_frontmatter(self):
        text = "---\nname: Foo\ntype: person\n---\nbody\n"
        new = add_frontmatter_field_text(text, "schema_version", 1)
        assert new == "---\nname: Foo\ntype: person\nschema_version: 1\n---\nbody\n"

    def test_preserves_comments(self):
        text = "---\nname: Foo  # informal\nemail: foo@example.com  # guess\ntype: person\n---\nbody\n"
        new = add_frontmatter_field_text(text, "schema_version", 1)
        assert "name: Foo  # informal" in new
        assert "email: foo@example.com  # guess" in new
        assert "schema_version: 1" in new

    def test_preserves_field_order(self):
        text = "---\nz_last: 1\na_first: 2\nm_middle: 3\ntype: person\n---\nbody\n"
        new = add_frontmatter_field_text(text, "schema_version", 1)
        # Original order intact; new field appended at end.
        lines = new.split("\n")
        fm_lines = [ln for ln in lines if ":" in ln and not ln.startswith("---")]
        assert fm_lines[0].startswith("z_last:")
        assert fm_lines[1].startswith("a_first:")
        assert fm_lines[2].startswith("m_middle:")
        assert fm_lines[3].startswith("type:")
        assert fm_lines[4].startswith("schema_version:")

    def test_raises_when_field_already_present(self):
        text = "---\nname: Foo\nschema_version: 1\ntype: person\n---\nbody\n"
        with pytest.raises(FrontmatterError, match="already present"):
            add_frontmatter_field_text(text, "schema_version", 1)

    def test_raises_without_opening_delimiter(self):
        with pytest.raises(FrontmatterError, match="opening frontmatter"):
            add_frontmatter_field_text("just body\n", "k", 1)

    def test_raises_without_closing_delimiter(self):
        with pytest.raises(FrontmatterError, match="closing frontmatter"):
            add_frontmatter_field_text("---\nname: Foo\n", "k", 1)

    def test_eof_without_trailing_newline(self):
        """Some files end exactly with `\\n---` (no body, no newline)."""
        text = "---\nname: Foo\ntype: person\n---"
        new = add_frontmatter_field_text(text, "schema_version", 1)
        assert new == "---\nname: Foo\ntype: person\nschema_version: 1\n---"

    def test_string_value_with_yaml_special_chars_is_quoted(self):
        text = "---\nname: Foo\n---\nbody\n"
        new = add_frontmatter_field_text(
            text, "note", "has: colons, and, commas",
        )
        # Value should be single-quoted because it has YAML-significant chars.
        assert "note: 'has: colons, and, commas'" in new

    def test_boolean_value_unquoted(self):
        text = "---\nname: Foo\n---\nbody\n"
        new = add_frontmatter_field_text(text, "flag", True)
        assert "flag: true" in new


# ---------------------------------------------------------------------------
# remove_frontmatter_field_text
# ---------------------------------------------------------------------------


class TestRemoveFrontmatterFieldText:
    def test_removes_existing_field(self):
        text = "---\nname: Foo\nschema_version: 1\ntype: person\n---\nbody\n"
        new = remove_frontmatter_field_text(text, "schema_version")
        assert new == "---\nname: Foo\ntype: person\n---\nbody\n"

    def test_removes_field_at_end_of_frontmatter(self):
        text = "---\nname: Foo\ntype: person\nschema_version: 1\n---\nbody\n"
        new = remove_frontmatter_field_text(text, "schema_version")
        assert new == "---\nname: Foo\ntype: person\n---\nbody\n"

    def test_removes_field_at_start_of_frontmatter(self):
        text = "---\nschema_version: 1\nname: Foo\ntype: person\n---\nbody\n"
        new = remove_frontmatter_field_text(text, "schema_version")
        assert new == "---\nname: Foo\ntype: person\n---\nbody\n"

    def test_idempotent_when_field_absent(self):
        text = "---\nname: Foo\ntype: person\n---\nbody\n"
        new = remove_frontmatter_field_text(text, "schema_version")
        assert new == text

    def test_preserves_other_comments(self):
        text = (
            "---\nname: Foo  # informal\nschema_version: 1\n"
            "type: person  # buyer-shape\n---\nbody\n"
        )
        new = remove_frontmatter_field_text(text, "schema_version")
        assert "name: Foo  # informal" in new
        assert "type: person  # buyer-shape" in new
        assert "schema_version" not in new

    def test_raises_without_delimiters(self):
        with pytest.raises(FrontmatterError, match="opening"):
            remove_frontmatter_field_text("body only\n", "k")

    def test_eof_without_trailing_newline(self):
        text = "---\nname: Foo\nschema_version: 1\n---"
        new = remove_frontmatter_field_text(text, "schema_version")
        assert new == "---\nname: Foo\n---"


# ---------------------------------------------------------------------------
# Round-trip: add then remove returns original
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_add_then_remove_returns_original(self):
        original = "---\nname: Foo\ntype: person\n---\nbody\n"
        added = add_frontmatter_field_text(original, "schema_version", 1)
        removed = remove_frontmatter_field_text(added, "schema_version")
        assert removed == original

    def test_add_then_remove_preserves_comments(self):
        original = (
            "---\nname: Foo  # informal\nemail: foo@example.com  # guess\n"
            "type: person\n---\nbody with content\n"
        )
        added = add_frontmatter_field_text(original, "schema_version", 1)
        removed = remove_frontmatter_field_text(added, "schema_version")
        assert removed == original


# ---------------------------------------------------------------------------
# write_person_frontmatter_atomic
# ---------------------------------------------------------------------------


class TestWriteAtomic:
    def test_writes_content(self, vault_dir: Path):
        note = vault_dir / "10 People" / "Foo.md"
        write_person_frontmatter_atomic(note, "hello world\n")
        assert note.read_text(encoding="utf-8") == "hello world\n"

    def test_overwrites_existing_file(self, vault_dir: Path):
        note = _write_person(vault_dir, "Foo", "name: Foo\ntype: person")
        write_person_frontmatter_atomic(note, "new content\n")
        assert note.read_text(encoding="utf-8") == "new content\n"

    def test_creates_parent_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "path" / "Foo.md"
        write_person_frontmatter_atomic(nested, "content\n")
        assert nested.exists()

    def test_tmp_file_does_not_leak(self, vault_dir: Path):
        """After a successful write the `.tmp` file should not exist."""
        note = vault_dir / "10 People" / "Foo.md"
        write_person_frontmatter_atomic(note, "content\n")
        tmp = note.with_suffix(note.suffix + ".tmp")
        assert note.exists()
        assert not tmp.exists()

    def test_partial_write_does_not_overwrite_target(
        self, vault_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """If os.replace fails after writing the tmp file, the target
        must remain untouched. Same crash-safety as save_state_atomic."""
        note = _write_person(vault_dir, "Foo", "name: Foo\ntype: person")
        original = note.read_text(encoding="utf-8")

        def crashing_replace(src, dst):
            assert Path(src).exists()  # tmp must exist before replace
            raise OSError("simulated crash before rename")

        monkeypatch.setattr(os, "replace", crashing_replace)
        with pytest.raises(OSError, match="simulated crash"):
            write_person_frontmatter_atomic(note, "would clobber\n")

        # Target untouched.
        assert note.read_text(encoding="utf-8") == original

    def test_recovers_after_stale_tmp_leftover(self, vault_dir: Path):
        """A prior crash may have left `Foo.md.tmp`; the next successful
        write should overwrite it without confusion (O_TRUNC handles)."""
        note = vault_dir / "10 People" / "Foo.md"
        tmp = note.with_suffix(note.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("garbage from prior crash", encoding="utf-8")
        write_person_frontmatter_atomic(note, "clean content\n")
        assert note.read_text(encoding="utf-8") == "clean content\n"
        assert not tmp.exists()


# ---------------------------------------------------------------------------
# iter_person_notes
# ---------------------------------------------------------------------------


class TestIterPersonNotes:
    def test_yields_md_files_in_people_dir(self, vault_dir: Path):
        _write_person(vault_dir, "Foo", "name: Foo\ntype: person")
        _write_person(vault_dir, "Bar", "name: Bar\ntype: person")
        notes = list(iter_person_notes(vault_dir))
        names = sorted(n.name for n in notes)
        assert names == ["Bar.md", "Foo.md"]

    def test_recurses_into_subdirs(self, vault_dir: Path):
        (vault_dir / "10 People" / "active").mkdir()
        (vault_dir / "10 People" / "active" / "Foo.md").write_text(
            "---\nname: Foo\ntype: person\n---\nbody\n",
            encoding="utf-8",
        )
        notes = list(iter_person_notes(vault_dir))
        assert len(notes) == 1
        assert notes[0].name == "Foo.md"

    def test_skips_hidden_files(self, vault_dir: Path):
        _write_person(vault_dir, "Foo", "name: Foo\ntype: person")
        (vault_dir / "10 People" / ".hidden.md").write_text(
            "---\nname: Hidden\ntype: person\n---\nbody\n",
            encoding="utf-8",
        )
        notes = list(iter_person_notes(vault_dir))
        names = [n.name for n in notes]
        assert "Foo.md" in names
        assert ".hidden.md" not in names

    def test_skips_obsidian_sync_conflict_files(self, vault_dir: Path):
        _write_person(vault_dir, "Foo", "name: Foo\ntype: person")
        # Obsidian Sync produces these on merge conflict.
        (vault_dir / "10 People" / "Foo.conflicted.md").write_text(
            "---\nname: Foo conflicted\ntype: person\n---\nbody\n",
            encoding="utf-8",
        )
        (vault_dir / "10 People" / "Foo.conflict.md").write_text(
            "---\nname: Foo conflict\ntype: person\n---\nbody\n",
            encoding="utf-8",
        )
        notes = list(iter_person_notes(vault_dir))
        names = [n.name for n in notes]
        assert names == ["Foo.md"]

    def test_yields_nothing_when_people_dir_missing(self, tmp_path: Path):
        v = tmp_path / "vault_without_people"
        v.mkdir()
        notes = list(iter_person_notes(v))
        assert notes == []

    def test_respects_people_subdir_override(self, tmp_path: Path):
        v = tmp_path / "vault"
        (v / "Folks").mkdir(parents=True)
        (v / "Folks" / "Foo.md").write_text(
            "---\nname: Foo\ntype: person\n---\nbody\n",
            encoding="utf-8",
        )
        notes = list(iter_person_notes(v, people_subdir="Folks"))
        assert len(notes) == 1
        assert notes[0].name == "Foo.md"

    def test_skips_hidden_subdir(self, vault_dir: Path):
        (vault_dir / "10 People" / ".obsidian").mkdir()
        (vault_dir / "10 People" / ".obsidian" / "config.md").write_text(
            "---\nname: Conf\ntype: person\n---\nbody\n",
            encoding="utf-8",
        )
        _write_person(vault_dir, "Foo", "name: Foo\ntype: person")
        notes = list(iter_person_notes(vault_dir))
        names = [n.name for n in notes]
        assert "Foo.md" in names
        assert "config.md" not in names

    def test_results_are_sorted_for_deterministic_order(self, vault_dir: Path):
        for name in ("Charlie", "Alpha", "Bravo"):
            _write_person(vault_dir, name, "name: x\ntype: person")
        notes = list(iter_person_notes(vault_dir))
        names = [n.name for n in notes]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# is_obsidian_conflict_file — Pillar B Week 6 second follow-up
# (consolidates legacy + iCloud naming per
# .planning/REVIEW-pillar-b-boil-the-ocean.md §P2-1)
# ---------------------------------------------------------------------------


class TestIsObsidianConflictFile:
    """Canonical predicate for the Obsidian Sync conflict-file naming
    patterns. Both vault iteration (:func:`iter_person_notes` /
    :func:`iter_touch_notes`) and ledger migration walks delegate
    here so a future contributor adding a new sync-conflict-aware
    iterator inherits identical behavior + so the iCloud-backed
    naming gap (Week 6 boil-the-ocean P2-1) stays closed."""

    def test_legacy_desktop_dot_conflicted_dot_md(self):
        assert is_obsidian_conflict_file("Foo.conflicted.md")
        assert is_obsidian_conflict_file("Some Name.conflicted.md")

    def test_legacy_desktop_dot_conflict_dot_md(self):
        assert is_obsidian_conflict_file("Foo.conflict.md")

    def test_icloud_backed_parenthesized_conflicted_copy(self):
        """The pattern Obsidian Sync produces on iCloud-backed vaults
        (the gap the consolidation closed)."""
        assert is_obsidian_conflict_file(
            "Foo (conflicted copy 2026-05-21 from iPhone).md",
        )
        assert is_obsidian_conflict_file(
            "Alice Anderson (conflicted copy 2026-04-12 from MacBook).md",
        )

    def test_icloud_backed_apostrophe_s_variant(self):
        """The other iCloud-backed naming variant some Obsidian
        versions produce."""
        assert is_obsidian_conflict_file(
            "Foo (iPhone's conflicted copy 2026-05-21).md",
        )

    def test_regular_markdown_file_is_not_conflict(self):
        assert not is_obsidian_conflict_file("Foo.md")
        assert not is_obsidian_conflict_file("Alice Anderson.md")
        # Names that happen to contain "conflict" as a word are also
        # not Obsidian conflict files (this is intentional — the
        # iCloud pattern requires the parenthesized prefix).
        assert not is_obsidian_conflict_file("conflict-resolution-notes.md")

    def test_non_markdown_extension_with_conflict_pattern_still_matches(self):
        """The predicate matches on substring, not extension — a
        ``.txt`` file from Obsidian Sync also bears the pattern.
        Callers filter by extension separately via rglob('*.md')."""
        assert is_obsidian_conflict_file("Foo.conflicted.txt")


# ---------------------------------------------------------------------------
# iter_touch_notes — sibling iterator for 40 Conversations/
# (Pillar B Week 6 second follow-up addition per
# .planning/REVIEW-pillar-b-pillar-c-readiness.md §P3-3)
# ---------------------------------------------------------------------------


def _write_touch(
    vault_dir: Path, name: str, frontmatter: str, body: str = "body\n",
) -> Path:
    """Write a synthetic touch note under 40 Conversations/."""
    notes_dir = vault_dir / "40 Conversations"
    notes_dir.mkdir(parents=True, exist_ok=True)
    note = notes_dir / f"{name}.md"
    note.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return note


class TestIterTouchNotes:
    def test_yields_md_files_in_conversations_dir(self, tmp_path: Path):
        v = tmp_path / "vault"
        _write_touch(v, "2026-04-10 Alice initial", "type: touch")
        _write_touch(v, "2026-04-11 Bob initial", "type: touch")
        notes = list(iter_touch_notes(v))
        names = sorted(n.name for n in notes)
        assert names == [
            "2026-04-10 Alice initial.md",
            "2026-04-11 Bob initial.md",
        ]

    def test_skips_icloud_conflict_files(self, tmp_path: Path):
        """The iCloud-conflict-naming gap matters here too — Pillar
        C's touch-note migrations will walk this surface."""
        v = tmp_path / "vault"
        _write_touch(v, "2026-04-10 Alice initial", "type: touch")
        _write_touch(
            v,
            "2026-04-10 Alice initial (conflicted copy 2026-04-12 from iPhone)",
            "type: touch",
        )
        notes = list(iter_touch_notes(v))
        names = [n.name for n in notes]
        assert names == ["2026-04-10 Alice initial.md"], (
            f"iCloud conflict touch note was not filtered: {names}"
        )

    def test_yields_nothing_when_conversations_dir_missing(
        self, tmp_path: Path,
    ):
        v = tmp_path / "vault_without_conversations"
        v.mkdir()
        notes = list(iter_touch_notes(v))
        assert notes == []

    def test_respects_conversations_subdir_override(self, tmp_path: Path):
        v = tmp_path / "vault"
        (v / "Threads").mkdir(parents=True)
        (v / "Threads" / "msg.md").write_text(
            "---\ntype: touch\n---\nbody\n", encoding="utf-8",
        )
        notes = list(iter_touch_notes(v, conversations_subdir="Threads"))
        assert len(notes) == 1
        assert notes[0].name == "msg.md"


# ---------------------------------------------------------------------------
# add_frontmatter_block_text — nested-map insertion
# (Pillar B Week 6 second follow-up per
# .planning/REVIEW-pillar-b-pillar-c-readiness.md §P2-1)
# ---------------------------------------------------------------------------


class TestAddFrontmatterBlockText:
    """The sibling to :func:`add_frontmatter_field_text` for nested-
    map frontmatter values (e.g. ``identity_keys: {linkedin: ...,
    email: ...}``, ``discovery_lineage: {source_skill: ...}``, Pillar
    C's per-channel detail blocks). Pulled forward from Pillar I OSS
    sweep + ADR-0011 D8's "Pillar E author either extends or YAML-
    round-trips" alternative because Pillar C's first touch-note
    migration needs the primitive."""

    def test_inserts_block_at_end_of_frontmatter(self):
        text = "---\ntype: person\nname: Foo\n---\nbody"
        result = add_frontmatter_block_text(
            text, "identity_keys",
            {"linkedin": "in/foo", "email": "foo@bar.com"},
        )
        assert "type: person" in result
        assert "name: Foo" in result
        assert "identity_keys:\n  linkedin: in/foo\n  email: foo@bar.com" in result
        # Block appears before the closing delimiter.
        assert result.endswith("---\nbody")

    def test_preserves_existing_field_order_and_comments(self):
        text = (
            "---\n"
            "# Operator: do not delete this comment\n"
            "type: person\n"
            "name: Foo\n"
            "# another comment\n"
            "company: Acme\n"
            "---\n"
            "body"
        )
        result = add_frontmatter_block_text(
            text, "identity_keys",
            {"linkedin": "in/foo"},
        )
        assert "# Operator: do not delete this comment" in result
        assert "# another comment" in result
        assert result.index("type: person") < result.index("name: Foo")
        assert result.index("name: Foo") < result.index("company: Acme")
        assert result.index("company: Acme") < result.index("identity_keys:")

    def test_dict_iteration_order_preserved_in_output(self):
        """Python 3.7+ dicts preserve insertion order; the block
        output mirrors it. Callers needing deterministic field order
        pass an ordered dict."""
        text = "---\ntype: person\n---\nbody"
        result = add_frontmatter_block_text(
            text, "discovery_lineage",
            {"source_skill": "find-leads", "scraped_at": "2026-05-21"},
        )
        # source_skill comes before scraped_at in the rendered block.
        assert result.index("source_skill:") < result.index("scraped_at:")

    def test_scalar_value_types_render_correctly(self):
        """Booleans, ints, None, strings — all delegated to
        :func:`_format_yaml_value` so the same conventions as
        :func:`add_frontmatter_field_text` apply. None renders as
        empty-after-colon (YAML's other way to write null; matches
        the existing field-helper convention; both forms parse back
        as ``None`` via ``yaml.safe_load``)."""
        text = "---\ntype: person\n---\nbody"
        result = add_frontmatter_block_text(
            text, "details",
            {
                "active": True,
                "score": 42,
                "note": None,
                "tag": "premium",
            },
        )
        assert "  active: true" in result
        assert "  score: 42" in result
        # None renders as empty after colon — YAML accepts both `null`
        # and bare empty value; the field helper's convention is empty.
        assert "  note: \n" in result
        assert "  tag: premium" in result

    def test_refuses_when_block_key_already_present(self):
        text = (
            "---\n"
            "type: person\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "---\n"
            "body"
        )
        with pytest.raises(FrontmatterError, match="identity_keys.*already present"):
            add_frontmatter_block_text(
                text, "identity_keys", {"email": "foo@bar"},
            )

    def test_refuses_when_value_is_nested_dict(self):
        """One level of nesting only — a nested dict value (two
        levels of structure) is out of scope for this helper. Caller
        is told which key broke the contract."""
        text = "---\ntype: person\n---\nbody"
        with pytest.raises(FrontmatterError, match="channels.*dict"):
            add_frontmatter_block_text(
                text, "discovery_lineage",
                {"channels": {"linkedin": "x"}},
            )

    def test_refuses_when_value_is_list(self):
        """Lists similarly out of scope (would need YAML sequence
        rendering which differs from the scalar/block contract)."""
        text = "---\ntype: person\n---\nbody"
        with pytest.raises(FrontmatterError, match="tags.*list"):
            add_frontmatter_block_text(
                text, "details", {"tags": ["a", "b"]},
            )

    def test_refuses_when_block_dict_is_empty(self):
        text = "---\ntype: person\n---\nbody"
        with pytest.raises(FrontmatterError, match="empty"):
            add_frontmatter_block_text(text, "identity_keys", {})

    def test_refuses_when_text_has_no_frontmatter(self):
        text = "body only, no frontmatter\n"
        with pytest.raises(FrontmatterError, match="no opening frontmatter"):
            add_frontmatter_block_text(text, "identity_keys", {"x": "y"})

    def test_custom_indent_is_honored(self):
        """Caller-provided indent (default 2) controls block child
        indentation. Pillar C's coherence-test-fixture-builder might
        want 4-space to match a specific style — supported."""
        text = "---\ntype: person\n---\nbody"
        result = add_frontmatter_block_text(
            text, "details", {"key": "val"}, indent=4,
        )
        assert "    key: val" in result

    def test_block_text_round_trips_through_yaml_safe_load(self):
        """The output must parse back as YAML cleanly — this is the
        load-bearing invariant that future migrations + the engine
        depend on."""
        import yaml
        text = "---\ntype: person\nname: Foo\n---\nbody"
        result = add_frontmatter_block_text(
            text, "identity_keys",
            {"linkedin": "in/foo", "email": "foo@bar"},
        )
        # Extract frontmatter, parse, verify the block lands in the
        # right shape.
        fm_text = result.split("---\n", 2)[1]
        fm = yaml.safe_load(fm_text)
        assert fm["type"] == "person"
        assert fm["name"] == "Foo"
        assert fm["identity_keys"] == {
            "linkedin": "in/foo", "email": "foo@bar",
        }


# ---------------------------------------------------------------------------
# extend_frontmatter_nested_block_text — nested sub-block insertion
# (Pillar E Week 9-11 vault migration 0005 per ADR-0036 D168)
# ---------------------------------------------------------------------------


class TestExtendFrontmatterNestedBlockText:
    """Sibling to TestAddFrontmatterBlockText for the nested-sub-block
    insertion case. Pillar E Week 9-11 ships the discovery_lineage
    sub-block inside the existing identity_keys block."""

    def test_inserts_nested_block_under_existing_parent(self):
        text = (
            "---\n"
            "type: person\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "  emails:\n"
            "  - foo@bar.com\n"
            "identity_version: 1\n"
            "---\n"
            "body\n"
        )
        result = extend_frontmatter_nested_block_text(
            text, "identity_keys", "discovery_lineage",
            {
                "source_skill": "find-leads",
                "source_list": "[[test]]",
                "scraped_at": "2026-05-13T10:00:00Z",
                "raw_input_hash": "sha256:" + "a" * 64,
            },
        )
        assert "  discovery_lineage:" in result
        assert "    source_skill: find-leads" in result
        # The nested block is BEFORE identity_version: (the next top-level).
        assert (
            result.index("  discovery_lineage:")
            < result.index("identity_version: 1")
        )
        # identity_keys' existing children preserved.
        assert "  linkedin: in/foo" in result
        assert "  emails:" in result
        assert "  - foo@bar.com" in result

    def test_round_trip_through_yaml_safe_load(self):
        """The output must parse back as YAML cleanly."""
        import yaml
        text = (
            "---\n"
            "type: person\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "---\n"
            "body\n"
        )
        result = extend_frontmatter_nested_block_text(
            text, "identity_keys", "discovery_lineage",
            {"source_skill": "find-leads", "source_list": "[[t]]",
             "scraped_at": "2026-05-13T10:00:00Z",
             "raw_input_hash": "sha256:" + "0" * 64},
        )
        fm_text = result.split("---\n", 2)[1]
        fm = yaml.safe_load(fm_text)
        assert fm["type"] == "person"
        assert fm["identity_keys"]["linkedin"] == "in/foo"
        assert fm["identity_keys"]["discovery_lineage"] == {
            "source_skill": "find-leads",
            "source_list": "[[t]]",
            "scraped_at": "2026-05-13T10:00:00Z",
            "raw_input_hash": "sha256:" + "0" * 64,
        }

    def test_inserts_when_parent_is_last_top_level_field(self):
        """The parent_key is the final field — insert before the closing ---."""
        text = (
            "---\n"
            "type: person\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "---\n"
            "body\n"
        )
        result = extend_frontmatter_nested_block_text(
            text, "identity_keys", "discovery_lineage",
            {"source_skill": "manual", "source_list": "[[x]]",
             "scraped_at": "2026-05-13T10:00:00Z",
             "raw_input_hash": "sha256:" + "1" * 64},
        )
        # discovery_lineage lands inside identity_keys, before the closing ---.
        assert "  discovery_lineage:" in result
        assert "    source_skill: manual" in result
        assert result.endswith("---\nbody\n")

    def test_inserts_when_parent_has_one_child_only(self):
        text = (
            "---\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "---\n"
        )
        result = extend_frontmatter_nested_block_text(
            text, "identity_keys", "lineage",
            {"key": "val"},
        )
        assert "  linkedin: in/foo" in result
        assert "  lineage:" in result
        assert "    key: val" in result

    def test_refuses_when_parent_absent(self):
        text = "---\ntype: person\n---\nbody"
        with pytest.raises(FrontmatterError, match="parent_key.*not found"):
            extend_frontmatter_nested_block_text(
                text, "identity_keys", "discovery_lineage",
                {"k": "v"},
            )

    def test_refuses_when_child_already_present(self):
        text = (
            "---\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "  discovery_lineage:\n"
            "    source_skill: find-leads\n"
            "---\n"
        )
        with pytest.raises(FrontmatterError, match="already present"):
            extend_frontmatter_nested_block_text(
                text, "identity_keys", "discovery_lineage",
                {"source_skill": "manual"},
            )

    def test_refuses_when_child_block_empty(self):
        text = "---\nidentity_keys:\n  linkedin: in/foo\n---\n"
        with pytest.raises(FrontmatterError, match="empty"):
            extend_frontmatter_nested_block_text(
                text, "identity_keys", "discovery_lineage", {},
            )

    def test_refuses_when_child_value_is_dict(self):
        text = "---\nidentity_keys:\n  linkedin: in/foo\n---\n"
        with pytest.raises(FrontmatterError, match="dict"):
            extend_frontmatter_nested_block_text(
                text, "identity_keys", "discovery_lineage",
                {"nested": {"deeper": "value"}},
            )

    def test_refuses_when_child_value_is_list(self):
        text = "---\nidentity_keys:\n  linkedin: in/foo\n---\n"
        with pytest.raises(FrontmatterError, match="list"):
            extend_frontmatter_nested_block_text(
                text, "identity_keys", "discovery_lineage",
                {"items": ["a", "b"]},
            )

    def test_refuses_when_text_has_no_frontmatter(self):
        with pytest.raises(FrontmatterError, match="no opening frontmatter"):
            extend_frontmatter_nested_block_text(
                "body only\n", "identity_keys", "discovery_lineage",
                {"k": "v"},
            )

    def test_refuses_when_parent_has_inline_value_empty_dict(self):
        """Pillar E Week 9-11 review P2-A regression pin.

        Parent line `identity_keys: {}` is YAML-valid (empty inline
        mapping) but appending child lines after it produces malformed
        YAML. The helper must refuse-loud rather than corrupt the
        Person note on the atomic write.
        """
        text = "---\nidentity_keys: {}\n---\nbody\n"
        with pytest.raises(FrontmatterError, match="inline value"):
            extend_frontmatter_nested_block_text(
                text, "identity_keys", "discovery_lineage",
                {"source_skill": "manual"},
            )

    def test_refuses_when_parent_has_inline_scalar(self):
        """Variant of P2-A — parent line carries a scalar value."""
        text = "---\nidentity_keys: somescalar\n---\nbody\n"
        with pytest.raises(FrontmatterError, match="inline value"):
            extend_frontmatter_nested_block_text(
                text, "identity_keys", "discovery_lineage",
                {"source_skill": "manual"},
            )

    def test_allows_parent_with_trailing_whitespace_only(self):
        """Parent line `identity_keys: ` (colon + space + nothing) is
        block-mapping form — the helper must NOT refuse this case."""
        text = "---\nidentity_keys: \n  linkedin: in/x\n---\nbody\n"
        # Should not raise.
        result = extend_frontmatter_nested_block_text(
            text, "identity_keys", "discovery_lineage",
            {"source_skill": "manual"},
        )
        assert "  discovery_lineage:" in result

    def test_custom_indent_is_honored(self):
        """Caller-provided indent (default 2) controls the child indent."""
        text = "---\nidentity_keys:\n    linkedin: in/foo\n---\n"
        result = extend_frontmatter_nested_block_text(
            text, "identity_keys", "lineage",
            {"key": "val"}, indent=4,
        )
        assert "    lineage:" in result
        assert "        key: val" in result

    def test_preserves_other_top_level_fields(self):
        """Top-level fields after the parent stay in place."""
        text = (
            "---\n"
            "type: person\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "identity_version: 1\n"
            "pipeline_stage: queued\n"
            "tags:\n"
            "  - fresh\n"
            "  - high-fit\n"
            "---\n"
            "body\n"
        )
        result = extend_frontmatter_nested_block_text(
            text, "identity_keys", "discovery_lineage",
            {"source_skill": "manual", "source_list": "[[x]]",
             "scraped_at": "2026-05-13T10:00:00Z",
             "raw_input_hash": "sha256:" + "f" * 64},
        )
        # All original fields preserved.
        assert "type: person" in result
        assert "identity_version: 1" in result
        assert "pipeline_stage: queued" in result
        assert "tags:" in result
        assert "  - fresh" in result
        assert "  - high-fit" in result

    def test_value_with_yaml_significant_chars_gets_quoted(self):
        """Strings with YAML-significant chars (:, [, ]) get single-quoted."""
        text = "---\nidentity_keys:\n  linkedin: in/foo\n---\n"
        result = extend_frontmatter_nested_block_text(
            text, "identity_keys", "discovery_lineage",
            {"source_list": "[[2026-05-13-funded-founders]]",
             "source_skill": "manual",
             "scraped_at": "2026-05-13T10:00:00Z",
             "raw_input_hash": "sha256:" + "f" * 64},
        )
        # source_list and scraped_at contain colons / brackets — get quoted.
        assert "'[[2026-05-13-funded-founders]]'" in result
        assert "'2026-05-13T10:00:00Z'" in result


# ---------------------------------------------------------------------------
# remove_frontmatter_nested_field_text — inverse of the extend helper
# ---------------------------------------------------------------------------


class TestRemoveFrontmatterNestedFieldText:

    def test_removes_nested_block(self):
        text = (
            "---\n"
            "type: person\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "  discovery_lineage:\n"
            "    source_skill: find-leads\n"
            "    source_list: '[[t]]'\n"
            "identity_version: 1\n"
            "---\n"
            "body\n"
        )
        result = remove_frontmatter_nested_field_text(
            text, "identity_keys", "discovery_lineage",
        )
        assert "discovery_lineage:" not in result
        assert "source_skill:" not in result
        # Other content preserved.
        assert "type: person" in result
        assert "  linkedin: in/foo" in result
        assert "identity_version: 1" in result

    def test_round_trip_with_extend(self):
        """extend → remove returns the original text exactly."""
        text = (
            "---\n"
            "type: person\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "  emails:\n"
            "  - foo@bar.com\n"
            "identity_version: 1\n"
            "---\n"
            "body\n"
        )
        extended = extend_frontmatter_nested_block_text(
            text, "identity_keys", "discovery_lineage",
            {"source_skill": "find-leads", "source_list": "[[t]]",
             "scraped_at": "2026-05-13T10:00:00Z",
             "raw_input_hash": "sha256:" + "a" * 64},
        )
        removed = remove_frontmatter_nested_field_text(
            extended, "identity_keys", "discovery_lineage",
        )
        assert removed == text

    def test_idempotent_when_child_absent(self):
        """Removing a non-present child is a no-op."""
        text = (
            "---\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "---\n"
        )
        result = remove_frontmatter_nested_field_text(
            text, "identity_keys", "discovery_lineage",
        )
        assert result == text

    def test_idempotent_when_parent_absent(self):
        """Removing under a non-present parent is a no-op."""
        text = "---\ntype: person\n---\nbody"
        result = remove_frontmatter_nested_field_text(
            text, "identity_keys", "discovery_lineage",
        )
        assert result == text

    def test_removes_middle_child_preserves_siblings(self):
        text = (
            "---\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "  discovery_lineage:\n"
            "    source_skill: find-leads\n"
            "  emails:\n"
            "  - foo@bar.com\n"
            "---\n"
        )
        result = remove_frontmatter_nested_field_text(
            text, "identity_keys", "discovery_lineage",
        )
        assert "  linkedin: in/foo" in result
        assert "  emails:" in result
        assert "  - foo@bar.com" in result
        assert "discovery_lineage:" not in result

    def test_refuses_when_text_has_no_frontmatter(self):
        with pytest.raises(FrontmatterError, match="no opening frontmatter"):
            remove_frontmatter_nested_field_text(
                "body only\n", "identity_keys", "discovery_lineage",
            )

    def test_round_trip_through_yaml_safe_load(self):
        """The post-removal text parses back as YAML cleanly."""
        import yaml
        text = (
            "---\n"
            "type: person\n"
            "identity_keys:\n"
            "  linkedin: in/foo\n"
            "  discovery_lineage:\n"
            "    source_skill: find-leads\n"
            "    source_list: '[[t]]'\n"
            "    scraped_at: '2026-05-13T10:00:00Z'\n"
            "    raw_input_hash: 'sha256:abc'\n"
            "identity_version: 1\n"
            "---\n"
        )
        result = remove_frontmatter_nested_field_text(
            text, "identity_keys", "discovery_lineage",
        )
        fm_text = result.split("---\n", 2)[1]
        fm = yaml.safe_load(fm_text)
        assert fm["identity_keys"] == {"linkedin": "in/foo"}
        assert "discovery_lineage" not in fm["identity_keys"]
