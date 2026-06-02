"""Unit tests for the policy-migration helper module.

Covers ``orchestrator.migrations.policy._policy_io``:

* ``iter_policy_files`` — walks ``*.yml`` non-recursively, skips hidden +
  conflict files, sorted, returns nothing when policy dir missing.
* ``read_policy_file`` — parses well-formed YAML + returns
  ``(dict, text)``, raises on unparseable / non-mapping / empty / OS
  error.
* ``write_policy_file_atomic`` — tmp-then-rename atomicity under
  simulated mid-rename crash; recovers cleanly on next write.
* ``add_top_level_field_text`` / ``add_top_level_block_text`` —
  surgical insert preserving every other line + comment + the
  ``rules:`` block. Refuses on already-present key.
* ``remove_top_level_field_text`` / ``remove_top_level_block_text`` —
  surgical delete preserving other content; idempotent on absent key;
  round-trip with add returns original.
* ``bump_version_text`` — finds + rewrites the ``version:`` line,
  preserves trailing comment + quote style, refuses on mismatched
  current value, raises on missing version line.

No real ``apply`` / ``runner`` exercise here — those live in
``test_migrations_policy_0001.py`` and ``test_migrations_runner.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from orchestrator.migrations.policy._policy_io import (
    PolicyFileError,
    add_rule_block_text,
    add_top_level_block_text,
    add_top_level_field_text,
    bump_version_text,
    iter_policy_files,
    read_policy_file,
    remove_rule_block_text,
    remove_top_level_block_text,
    remove_top_level_field_text,
    write_policy_file_atomic,
)


@pytest.fixture
def policy_dir(tmp_path: Path) -> Path:
    """Isolated policy dir per test."""
    p = tmp_path / "policies"
    p.mkdir()
    return p


def _write_policy(policy_dir: Path, name: str, content: str) -> Path:
    """Write a synthetic policy YAML file."""
    f = policy_dir / name
    f.write_text(content, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# iter_policy_files
# ---------------------------------------------------------------------------


class TestIterPolicyFiles:
    def test_yields_yml_files_sorted(self, policy_dir: Path):
        _write_policy(policy_dir, "charlie.yml", "version: 1\n")
        _write_policy(policy_dir, "alpha.yml", "version: 1\n")
        _write_policy(policy_dir, "bravo.yml", "version: 1\n")
        names = [p.name for p in iter_policy_files(policy_dir)]
        assert names == ["alpha.yml", "bravo.yml", "charlie.yml"]

    def test_does_not_recurse(self, policy_dir: Path):
        """Policy files live directly under policy_dir — subdirs are
        not policy locations and should not be walked."""
        sub = policy_dir / "subdir"
        sub.mkdir()
        (sub / "nested.yml").write_text("version: 1\n", encoding="utf-8")
        _write_policy(policy_dir, "top.yml", "version: 1\n")
        names = [p.name for p in iter_policy_files(policy_dir)]
        assert names == ["top.yml"]

    def test_skips_hidden_files(self, policy_dir: Path):
        _write_policy(policy_dir, "cooldowns.yml", "version: 1\n")
        _write_policy(policy_dir, ".hidden.yml", "version: 1\n")
        names = [p.name for p in iter_policy_files(policy_dir)]
        assert ".hidden.yml" not in names
        assert "cooldowns.yml" in names

    def test_skips_obsidian_conflict_files(self, policy_dir: Path):
        _write_policy(policy_dir, "cooldowns.yml", "version: 1\n")
        _write_policy(
            policy_dir, "cooldowns.conflicted.yml", "version: 1\n",
        )
        _write_policy(
            policy_dir, "cooldowns.conflict.yml", "version: 1\n",
        )
        names = [p.name for p in iter_policy_files(policy_dir)]
        assert names == ["cooldowns.yml"]

    def test_skips_non_yml_extensions(self, policy_dir: Path):
        _write_policy(policy_dir, "cooldowns.yml", "version: 1\n")
        _write_policy(policy_dir, "README.md", "# notes\n")
        _write_policy(policy_dir, "cooldowns.yaml", "version: 1\n")
        names = [p.name for p in iter_policy_files(policy_dir)]
        # ``.yaml`` extension is NOT walked — strict ``.yml`` per the
        # cooldowns.example.yml convention. Operators with ``.yaml``
        # files would not be migrated; that's a separate decision.
        assert names == ["cooldowns.yml"]

    def test_yields_nothing_when_policy_dir_missing(self, tmp_path: Path):
        ghost = tmp_path / "nonexistent_policy_dir"
        assert list(iter_policy_files(ghost)) == []

    def test_yields_nothing_when_policy_dir_empty(self, policy_dir: Path):
        assert list(iter_policy_files(policy_dir)) == []


# ---------------------------------------------------------------------------
# read_policy_file
# ---------------------------------------------------------------------------


class TestReadPolicyFile:
    def test_parses_well_formed_yaml(self, policy_dir: Path):
        f = _write_policy(
            policy_dir, "cooldowns.yml",
            "version: 1\nrules:\n  - name: foo\n    type: bar\n",
        )
        data, text = read_policy_file(f)
        assert data["version"] == 1
        assert data["rules"][0]["name"] == "foo"
        assert text.startswith("version: 1\n")

    def test_returns_raw_text_for_surgical_edits(self, policy_dir: Path):
        """The raw text must round-trip exactly so surgical edits can
        rewrite specific lines without re-serializing the whole file."""
        content = "# leading comment\nversion: 1\n\nrules:\n  - x: 1\n"
        f = _write_policy(policy_dir, "cooldowns.yml", content)
        _data, text = read_policy_file(f)
        assert text == content

    def test_normalizes_crlf_to_lf(self, policy_dir: Path):
        """CRLF files (Windows / cross-platform sync) parse fine; the
        returned text is LF-normalized so surgical edits operate on a
        single line-ending shape. Mirrors the vault helper's behavior."""
        f = policy_dir / "cooldowns.yml"
        f.write_bytes(b"version: 1\r\nrules:\r\n  - x: 1\r\n")
        data, text = read_policy_file(f)
        assert data["version"] == 1
        assert "\r\n" not in text
        assert text == "version: 1\nrules:\n  - x: 1\n"

    def test_raises_on_unparseable_yaml(self, policy_dir: Path):
        f = _write_policy(
            policy_dir, "broken.yml",
            "version: 1\nrules:\n  - bad: [unbalanced\n",
        )
        with pytest.raises(PolicyFileError, match="unparseable YAML"):
            read_policy_file(f)

    def test_raises_on_non_mapping_top_level(self, policy_dir: Path):
        """A policy file MUST have a mapping at the top level. A bare
        list / scalar / null is a contributor mistake."""
        f = _write_policy(policy_dir, "weird.yml", "- just\n- a list\n")
        with pytest.raises(PolicyFileError, match="top-level must be a mapping"):
            read_policy_file(f)

    def test_raises_on_empty_file(self, policy_dir: Path):
        f = _write_policy(policy_dir, "empty.yml", "")
        with pytest.raises(PolicyFileError, match="empty"):
            read_policy_file(f)

    def test_raises_on_only_delimiter(self, policy_dir: Path):
        f = _write_policy(policy_dir, "delim.yml", "---\n")
        with pytest.raises(PolicyFileError, match="empty"):
            read_policy_file(f)

    def test_raises_on_unreadable_file(self, policy_dir: Path):
        ghost = policy_dir / "ghost.yml"
        with pytest.raises(PolicyFileError, match="could not read"):
            read_policy_file(ghost)


# ---------------------------------------------------------------------------
# write_policy_file_atomic
# ---------------------------------------------------------------------------


class TestWriteAtomic:
    def test_writes_content(self, policy_dir: Path):
        f = policy_dir / "out.yml"
        write_policy_file_atomic(f, "version: 1\n")
        assert f.read_text(encoding="utf-8") == "version: 1\n"

    def test_overwrites_existing_file(self, policy_dir: Path):
        f = _write_policy(policy_dir, "cd.yml", "old content\n")
        write_policy_file_atomic(f, "new content\n")
        assert f.read_text(encoding="utf-8") == "new content\n"

    def test_creates_parent_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "cd.yml"
        write_policy_file_atomic(nested, "content\n")
        assert nested.exists()

    def test_tmp_file_does_not_leak(self, policy_dir: Path):
        f = policy_dir / "cd.yml"
        write_policy_file_atomic(f, "content\n")
        tmp = f.with_suffix(f.suffix + ".tmp")
        assert f.exists()
        assert not tmp.exists()

    def test_partial_write_does_not_overwrite_target(
        self, policy_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """If os.replace fails after writing the tmp file, the target
        must remain untouched. Same crash-safety as the vault helper +
        save_state_atomic."""
        f = _write_policy(policy_dir, "cd.yml", "original\n")
        original = f.read_text(encoding="utf-8")

        def crashing_replace(src, dst):
            assert Path(src).exists()
            raise OSError("simulated crash before rename")

        monkeypatch.setattr(os, "replace", crashing_replace)
        with pytest.raises(OSError, match="simulated crash"):
            write_policy_file_atomic(f, "would clobber\n")

        assert f.read_text(encoding="utf-8") == original

    def test_recovers_after_stale_tmp_leftover(self, policy_dir: Path):
        """A prior crash may have left ``cd.yml.tmp``; the next
        successful write overwrites it cleanly via O_TRUNC."""
        f = policy_dir / "cd.yml"
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text("garbage from prior crash", encoding="utf-8")
        write_policy_file_atomic(f, "clean content\n")
        assert f.read_text(encoding="utf-8") == "clean content\n"
        assert not tmp.exists()


# ---------------------------------------------------------------------------
# add_top_level_field_text
# ---------------------------------------------------------------------------


class TestAddTopLevelFieldText:
    def test_inserts_after_version_line(self):
        text = "version: 1\nrules: []\n"
        out = add_top_level_field_text(text, "extra", 42)
        assert out == "version: 1\nextra: 42\nrules: []\n"

    def test_preserves_comments_before_version(self):
        text = (
            "# Long header comment.\n"
            "# Second line of header.\n"
            "version: 1\n"
            "rules: []\n"
        )
        out = add_top_level_field_text(text, "extra", 42)
        assert out.startswith("# Long header comment.\n# Second line")
        assert "extra: 42" in out

    def test_preserves_rules_block(self):
        text = (
            "version: 1\n"
            "rules:\n"
            "  - name: foo\n"
            "    type: bar\n"
            "    reason: 'because'  # comment\n"
        )
        out = add_top_level_field_text(text, "extra", 42)
        assert "  - name: foo\n" in out
        assert "  reason: 'because'  # comment" in out

    def test_preserves_blank_line_after_version(self):
        """A blank line between version and rules must survive the
        insert."""
        text = "version: 1\n\nrules: []\n"
        out = add_top_level_field_text(text, "extra", 42)
        # Insert immediately after version; blank line survives.
        assert out == "version: 1\nextra: 42\n\nrules: []\n"

    def test_raises_when_field_already_present(self):
        text = "version: 1\nextra: 7\nrules: []\n"
        with pytest.raises(PolicyFileError, match="already present"):
            add_top_level_field_text(text, "extra", 42)

    def test_raises_without_version_line(self):
        text = "rules: []\n"
        with pytest.raises(PolicyFileError, match="version"):
            add_top_level_field_text(text, "extra", 42)

    def test_handles_quoted_version_value(self):
        """The version line can have a quoted value
        (``version: '1'``); inserts still work."""
        text = "version: '1'\nrules: []\n"
        out = add_top_level_field_text(text, "extra", 42)
        assert "version: '1'\nextra: 42\nrules:" in out

    def test_handles_trailing_comment_on_version_line(self):
        """The version line can have a trailing comment."""
        text = "version: 1  # required\nrules: []\n"
        out = add_top_level_field_text(text, "extra", 42)
        # The insert goes after the version line's newline; the
        # comment + version stay byte-identical.
        assert "version: 1  # required\n" in out
        assert out.index("extra: 42") > out.index("version: 1  # required")

    def test_quotes_string_with_yaml_specials(self):
        text = "version: 1\nrules: []\n"
        out = add_top_level_field_text(text, "note", "has: colons")
        assert "note: 'has: colons'" in out

    def test_renders_boolean_unquoted(self):
        text = "version: 1\nrules: []\n"
        out = add_top_level_field_text(text, "flag", True)
        assert "flag: true" in out

    def test_renders_integer_unquoted(self):
        text = "version: 1\nrules: []\n"
        out = add_top_level_field_text(text, "count", 5)
        assert "count: 5" in out

    def test_does_not_match_nested_version(self):
        """A rule's nested ``version:`` field (column ≥4) must NOT be
        matched as the insertion-point anchor. Idempotence-checking
        helpers should likewise only match top-level keys."""
        text = (
            "version: 1\n"
            "rules:\n"
            "  - name: foo\n"
            "    version: 99\n"  # rule's own version field; irrelevant
        )
        out = add_top_level_field_text(text, "extra", 42)
        # The new field appears between line 1 and line 2 — i.e.
        # immediately after the TOP-LEVEL version line.
        lines = out.split("\n")
        assert lines[0] == "version: 1"
        assert lines[1] == "extra: 42"
        assert lines[2] == "rules:"


# ---------------------------------------------------------------------------
# add_top_level_block_text
# ---------------------------------------------------------------------------


class TestAddTopLevelBlockText:
    def test_inserts_block_after_version(self):
        text = "version: 1\nrules: []\n"
        out = add_top_level_block_text(
            text, "engine_compat", {"min_engine_version": "0.1.0"},
        )
        assert "version: 1\nengine_compat:\n  min_engine_version: '0.1.0'\nrules:" in out

    def test_preserves_blank_line_after_version(self):
        text = "version: 1\n\nrules: []\n"
        out = add_top_level_block_text(
            text, "engine_compat", {"min_engine_version": "0.1.0"},
        )
        # Block inserted immediately after version line; blank line
        # survives + separates the block from rules.
        assert "version: 1\nengine_compat:\n  min_engine_version: '0.1.0'\n\nrules:" in out

    def test_preserves_comments_and_rules(self):
        text = (
            "# header comment\n"
            "version: 1\n"
            "rules:\n"
            "  - name: foo  # informal\n"
        )
        out = add_top_level_block_text(
            text, "engine_compat", {"min_engine_version": "0.1.0"},
        )
        assert "# header comment" in out
        assert "  - name: foo  # informal" in out

    def test_multiple_children_in_dict_order(self):
        text = "version: 1\nrules: []\n"
        out = add_top_level_block_text(
            text, "compat",
            {"min": "0.1.0", "max": "1.0.0"},
        )
        # Python 3.7+ preserves dict insertion order. Children appear
        # in the order they were passed.
        block_idx = out.index("compat:\n")
        min_idx = out.index("min:", block_idx)
        max_idx = out.index("max:", block_idx)
        assert min_idx < max_idx

    def test_raises_when_block_already_present(self):
        text = (
            "version: 1\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "rules: []\n"
        )
        with pytest.raises(PolicyFileError, match="already present"):
            add_top_level_block_text(
                text, "engine_compat",
                {"min_engine_version": "0.1.0"},
            )

    def test_raises_on_nested_dict_value(self):
        text = "version: 1\nrules: []\n"
        with pytest.raises(PolicyFileError, match="single-level"):
            add_top_level_block_text(
                text, "compat", {"nested": {"deep": "value"}},
            )

    def test_raises_on_list_value(self):
        text = "version: 1\nrules: []\n"
        with pytest.raises(PolicyFileError, match="single-level"):
            add_top_level_block_text(
                text, "compat", {"items": [1, 2, 3]},
            )

    def test_raises_without_version_line(self):
        text = "rules: []\n"
        with pytest.raises(PolicyFileError, match="version"):
            add_top_level_block_text(
                text, "compat", {"k": "v"},
            )


# ---------------------------------------------------------------------------
# remove_top_level_field_text
# ---------------------------------------------------------------------------


class TestRemoveTopLevelFieldText:
    def test_removes_existing_field(self):
        text = "version: 1\nextra: 42\nrules: []\n"
        out = remove_top_level_field_text(text, "extra")
        assert out == "version: 1\nrules: []\n"

    def test_idempotent_when_absent(self):
        text = "version: 1\nrules: []\n"
        out = remove_top_level_field_text(text, "absent")
        assert out == text

    def test_preserves_comments(self):
        text = (
            "# header\n"
            "version: 1\n"
            "extra: 42\n"
            "rules:\n"
            "  - name: foo\n"
        )
        out = remove_top_level_field_text(text, "extra")
        assert "# header" in out
        assert "  - name: foo" in out
        assert "extra:" not in out

    def test_removes_field_with_trailing_comment(self):
        text = "version: 1\nextra: 42  # remove me\nrules: []\n"
        out = remove_top_level_field_text(text, "extra")
        assert "extra:" not in out
        assert "remove me" not in out


# ---------------------------------------------------------------------------
# remove_top_level_block_text
# ---------------------------------------------------------------------------


class TestRemoveTopLevelBlockText:
    def test_removes_existing_block(self):
        text = (
            "version: 1\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "rules: []\n"
        )
        out = remove_top_level_block_text(text, "engine_compat")
        assert "engine_compat" not in out
        assert "min_engine_version" not in out
        assert "version: 1" in out
        assert "rules: []" in out

    def test_idempotent_when_absent(self):
        text = "version: 1\nrules: []\n"
        out = remove_top_level_block_text(text, "engine_compat")
        assert out == text

    def test_preserves_blank_line_after_block(self):
        """A blank line after the block is operator-meaningful spacing
        — must NOT be consumed by the remove regex."""
        text = (
            "version: 1\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "\n"
            "rules: []\n"
        )
        out = remove_top_level_block_text(text, "engine_compat")
        assert out == "version: 1\n\nrules: []\n"

    def test_stops_at_next_top_level_field(self):
        text = (
            "version: 1\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "extra: 99\n"
        )
        out = remove_top_level_block_text(text, "engine_compat")
        assert out == "version: 1\nextra: 99\n"

    def test_stops_at_next_top_level_comment(self):
        text = (
            "version: 1\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "# trailing top-level comment\n"
            "rules: []\n"
        )
        out = remove_top_level_block_text(text, "engine_compat")
        assert "engine_compat" not in out
        assert "# trailing top-level comment" in out
        assert "rules: []" in out

    def test_handles_block_at_end_of_file(self):
        text = (
            "version: 1\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
        )
        out = remove_top_level_block_text(text, "engine_compat")
        assert out == "version: 1\n"

    def test_multiple_indented_children(self):
        text = (
            "version: 1\n"
            "compat:\n"
            "  min: '0.1.0'\n"
            "  max: '1.0.0'\n"
            "  middle: '0.5.0'\n"
            "rules: []\n"
        )
        out = remove_top_level_block_text(text, "compat")
        assert out == "version: 1\nrules: []\n"


# ---------------------------------------------------------------------------
# Round-trip: add then remove returns original
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_scalar_round_trip(self):
        original = "version: 1\nrules: []\n"
        added = add_top_level_field_text(original, "extra", 42)
        removed = remove_top_level_field_text(added, "extra")
        assert removed == original

    def test_block_round_trip_with_blank_line(self):
        """The factory shape: header comment, version, blank, rules.
        Block round-trip must return byte-identical text."""
        original = (
            "# header comment.\n"
            "version: 1\n"
            "\n"
            "rules:\n"
            "  - name: foo\n"
        )
        added = add_top_level_block_text(
            original, "engine_compat",
            {"min_engine_version": "0.1.0"},
        )
        removed = remove_top_level_block_text(added, "engine_compat")
        assert removed == original

    def test_block_round_trip_with_version_bump(self):
        """The migration's actual round-trip shape: insert block + bump
        version, then revert version + remove block."""
        original = "version: 1\n\nrules: []\n"
        # Upgrade direction
        out = add_top_level_block_text(
            original, "engine_compat", {"min_engine_version": "0.1.0"},
        )
        out = bump_version_text(out, 1, 2)
        # Downgrade direction
        out = bump_version_text(out, 2, 1)
        out = remove_top_level_block_text(out, "engine_compat")
        assert out == original

    def test_block_round_trip_on_real_factory_template(self):
        """Round-trip against the actual 275-line cooldowns.example.yml
        — the most realistic operator-shaped file we have."""
        template = (
            Path(__file__).resolve().parent.parent
            / "config-template"
            / "cooldowns.example.yml"
        )
        original = template.read_text(encoding="utf-8")
        out = add_top_level_block_text(
            original, "engine_compat", {"min_engine_version": "0.1.0"},
        )
        out = bump_version_text(out, 1, 2)
        out = bump_version_text(out, 2, 1)
        out = remove_top_level_block_text(out, "engine_compat")
        assert out == original


# ---------------------------------------------------------------------------
# bump_version_text
# ---------------------------------------------------------------------------


class TestBumpVersionText:
    def test_bumps_unquoted_integer(self):
        text = "version: 1\nrules: []\n"
        out = bump_version_text(text, 1, 2)
        assert out == "version: 2\nrules: []\n"

    def test_bumps_single_quoted_value(self):
        text = "version: '1'\nrules: []\n"
        out = bump_version_text(text, 1, 2)
        assert out == "version: '2'\nrules: []\n"

    def test_bumps_double_quoted_value(self):
        text = 'version: "1"\nrules: []\n'
        out = bump_version_text(text, 1, 2)
        assert out == 'version: "2"\nrules: []\n'

    def test_preserves_trailing_comment(self):
        text = "version: 1  # current schema\nrules: []\n"
        out = bump_version_text(text, 1, 2)
        assert out == "version: 2  # current schema\nrules: []\n"

    def test_preserves_surrounding_lines(self):
        text = (
            "# header comment\n"
            "version: 1\n"
            "\n"
            "rules:\n"
            "  - name: foo\n"
        )
        out = bump_version_text(text, 1, 2)
        assert out == (
            "# header comment\n"
            "version: 2\n"
            "\n"
            "rules:\n"
            "  - name: foo\n"
        )

    def test_refuses_mismatched_current_version(self):
        text = "version: 5\nrules: []\n"
        with pytest.raises(PolicyFileError, match="expected current version 1"):
            bump_version_text(text, 1, 2)

    def test_raises_without_version_line(self):
        text = "rules: []\n"
        with pytest.raises(PolicyFileError, match="no top-level"):
            bump_version_text(text, 1, 2)

    def test_does_not_bump_nested_version_field(self):
        """A rule's nested ``version:`` (indented) must NOT match —
        only the top-level version is rewritten."""
        text = (
            "version: 1\n"
            "rules:\n"
            "  - name: foo\n"
            "    version: 99\n"
        )
        out = bump_version_text(text, 1, 2)
        assert "version: 2\n" in out
        assert "    version: 99\n" in out

    def test_round_trip_bump_and_back(self):
        text = "version: 1\nrules: []\n"
        out = bump_version_text(text, 1, 2)
        back = bump_version_text(out, 2, 1)
        assert back == text


# ---------------------------------------------------------------------------
# add_rule_block_text / remove_rule_block_text — Pillar C Week 7 surface
# (deferred from ADR-0012 D20; landed in ADR-0020)
# ---------------------------------------------------------------------------


_SAMPLE_RULE_BLOCK = (
    "  - name: linkedin-weekly-invite-cap\n"
    "    type: budget.window-cap\n"
    "    block_when:\n"
    "      channel: linkedin\n"
    "    source: linkedin_invite\n"
    "    window_days: 7\n"
    "    max_units: 100\n"
    "    reason: \"LinkedIn weekly invite cap\"\n"
)


class TestAddRuleBlockText:
    def test_appends_after_last_rule(self):
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: rule1\n"
            "    type: cooldown.foo\n"
            "    reason: 'first'\n"
        )
        out = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        assert "  - name: rule1\n" in out
        assert _SAMPLE_RULE_BLOCK.rstrip("\n") in out
        # The new rule comes AFTER rule1.
        rule1_pos = out.index("  - name: rule1")
        new_rule_pos = out.index("  - name: linkedin-weekly-invite-cap")
        assert new_rule_pos > rule1_pos

    def test_appends_after_multiple_rules(self):
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: r1\n"
            "    type: foo\n"
            "  - name: r2\n"
            "    type: bar\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
            "  - name: r3\n"
            "    type: baz\n"
        )
        out = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        # Order: r1, r2, r3, new.
        r1 = out.index("  - name: r1")
        r2 = out.index("  - name: r2")
        r3 = out.index("  - name: r3")
        new = out.index("  - name: linkedin-weekly-invite-cap")
        assert r1 < r2 < r3 < new

    def test_inline_empty_rules_converted_to_multiline(self):
        """`rules: []` (inline empty) is rewritten to multi-line form
        with the new rule as the first entry."""
        text = "version: 2\nrules: []\n"
        out = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        assert "rules: []" not in out
        assert "rules:\n" in out
        assert "  - name: linkedin-weekly-invite-cap" in out
        # Still parses as valid YAML.
        import yaml
        data = yaml.safe_load(out)
        assert data["rules"][0]["name"] == "linkedin-weekly-invite-cap"

    def test_bare_rules_no_entries_inserts_after_header(self):
        """`rules:` followed only by comments / blanks (no entries) —
        the new rule becomes the first entry."""
        text = (
            "version: 2\n"
            "rules:\n"
            "  # commented-out template:\n"
            "  # - name: future-rule\n"
        )
        out = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        # Parses cleanly with the new rule.
        import yaml
        data = yaml.safe_load(out)
        assert data["rules"][0]["name"] == "linkedin-weekly-invite-cap"

    def test_preserves_comments_outside_insertion_zone(self):
        text = (
            "# Header comment.\n"
            "version: 2\n"
            "\n"
            "rules:\n"
            "  # Rule 1: ...\n"
            "  - name: rule1\n"
            "    type: foo\n"
            "\n"
            "  # ---- Future templates (commented):\n"
            "  # - name: future-rule\n"
        )
        out = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        # Every original comment line preserved.
        for line in text.split("\n"):
            if line.lstrip().startswith("#"):
                assert line in out

    def test_preserves_existing_rule_content_byte_identical(self):
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: rule1\n"
            "    type: cooldown.foo\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
            "    reason: 'first reason'\n"
        )
        out = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        # rule1's full block stays in the output.
        assert (
            "  - name: rule1\n"
            "    type: cooldown.foo\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
            "    reason: 'first reason'\n"
        ) in out

    def test_refuses_without_rules_key(self):
        text = "version: 2\nengine_compat:\n  min_engine_version: '0.1.0'\n"
        with pytest.raises(PolicyFileError, match="rules"):
            add_rule_block_text(text, _SAMPLE_RULE_BLOCK)

    def test_block_normalized_to_single_trailing_newline(self):
        """Caller may pass a block with no trailing newline OR multiple;
        the helper writes exactly one."""
        no_trailing = _SAMPLE_RULE_BLOCK.rstrip("\n")
        multi_trailing = _SAMPLE_RULE_BLOCK + "\n\n\n"
        text = "version: 2\nrules:\n  - name: r1\n    type: foo\n"
        out1 = add_rule_block_text(text, no_trailing)
        out2 = add_rule_block_text(text, multi_trailing)
        assert out1 == out2

    def test_works_on_factory_template(self):
        """The 275-line factory cooldowns.example.yml must accept the
        append cleanly + remain parseable as YAML."""
        import yaml
        template = (
            Path(__file__).resolve().parent.parent
            / "config-template" / "cooldowns.example.yml"
        ).read_text(encoding="utf-8")
        out = add_rule_block_text(template, _SAMPLE_RULE_BLOCK)
        data = yaml.safe_load(out)
        rule_names = [r["name"] for r in data["rules"]]
        assert "linkedin-weekly-invite-cap" in rule_names
        # The factory's 6 active rules are still present.
        for original_name in (
            "no-double-cold-pitch",
            "follow-up-requires-prior-cold-pitch",
            "re-engage-requires-dormancy",
            "domain-cooldown",
            "cross-channel-email-suppresses-linkedin",
            "cross-channel-linkedin-suppresses-email",
        ):
            assert original_name in rule_names

    # P1-A regression: inline comment inside a rule's body must not
    # truncate the scanner.
    def test_inline_comment_inside_rule_body_does_not_truncate(self):
        """An operator who annotated a rule field with an inline comment
        (e.g. `# tuned down`) must not have their rule split when the
        migration appends a new rule. The scanner consumes the comment
        line as part of the entry body. Per-week-review P1-A regression
        sentinel."""
        import yaml
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: rule1\n"
            "    type: foo\n"
            "    # operator note: tuned down\n"
            "    reason: 'first reason'\n"
        )
        out = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        # The new rule comes AFTER rule1's full body (including the
        # inline comment + reason).
        data = yaml.safe_load(out)
        rule_names = [r["name"] for r in data["rules"]]
        assert rule_names == ["rule1", "linkedin-weekly-invite-cap"]
        # rule1's reason field preserved.
        rule1 = data["rules"][0]
        assert rule1["reason"] == "first reason"
        # Inline comment preserved in the text.
        assert "    # operator note: tuned down\n" in out
        # The comment is BEFORE rule1's reason, not stranded between rules.
        comment_pos = out.index("# operator note: tuned down")
        reason_pos = out.index("'first reason'")
        new_rule_pos = out.index("- name: linkedin-weekly-invite-cap")
        assert comment_pos < reason_pos < new_rule_pos

    # P1-B regression: tab-indented field must not terminate the scan.
    def test_tab_indented_continuation_does_not_truncate(self):
        """A rule body field indented with a leading tab (operator
        editor auto-converted spaces to tabs) must not be misread as
        an entry boundary. The scanner accepts both 4-space and tab
        indents. Per-week-review P1-B regression sentinel."""
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: rule1\n"
            "    type: foo\n"
            "\treason: 'tab indented'\n"
        )
        out = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        # The new rule comes after rule1's full body (including the
        # tab-indented reason).
        # We can't yaml.safe_load (mixed tabs/spaces is invalid YAML)
        # but we can check the structural position.
        tab_field_pos = out.index("\treason: 'tab indented'")
        new_rule_pos = out.index("- name: linkedin-weekly-invite-cap")
        assert tab_field_pos < new_rule_pos


class TestRemoveRuleBlockTextWithEdgeCases:
    """P1-A regression: inline comment + tab indent during downgrade."""

    def test_inline_comment_inside_rule_body_round_trip(self):
        """A rule with an inline comment in its body round-trips
        through add + remove without dropping the comment."""
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: rule1\n"
            "    type: foo\n"
            "    # inline note\n"
            "    reason: 'preserved'\n"
        )
        added = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        removed = remove_rule_block_text(added, "linkedin-weekly-invite-cap")
        assert removed == text

    def test_remove_canonical_rule_with_inline_comment_in_its_body(self):
        """If the migration's canonical rule itself has an operator-
        added inline comment (between the migration apply + downgrade),
        downgrade still removes the full entry including the comment.
        The scanner consumes the operator's annotation as part of the
        entry."""
        # Construct a state where the canonical rule has an extra
        # inline comment that an operator added post-migration.
        modified_block = (
            "  - name: linkedin-weekly-invite-cap\n"
            "    type: budget.window-cap\n"
            "    # operator tuned this down\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    source: linkedin_invite\n"
            "    window_days: 7\n"
            "    max_units: 80\n"  # tuned
            "    reason: \"tuned\"\n"
        )
        text = "version: 2\nrules:\n  - name: rule1\n    type: foo\n"
        with_canonical = text + modified_block
        out = remove_rule_block_text(with_canonical, "linkedin-weekly-invite-cap")
        # rule1 stays; canonical + its operator-added comment are gone.
        assert "  - name: rule1\n" in out
        assert "linkedin-weekly-invite-cap" not in out
        assert "operator tuned this down" not in out


class TestRemoveRuleBlockText:
    def test_removes_appended_rule(self):
        text = "version: 2\nrules:\n  - name: rule1\n    type: foo\n"
        added = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        removed = remove_rule_block_text(added, "linkedin-weekly-invite-cap")
        assert removed == text

    def test_round_trip_byte_identical(self):
        """Add then remove == byte-identical original. The load-bearing
        contract for the migration's downgrade path."""
        text = (
            "# Header.\n"
            "version: 2\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "\n"
            "rules:\n"
            "  - name: rule1\n"
            "    type: cooldown.foo\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
            "    reason: 'first'\n"
        )
        added = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        removed = remove_rule_block_text(added, "linkedin-weekly-invite-cap")
        assert removed == text

    def test_factory_template_round_trip_byte_identical(self):
        """The 275-line factory cooldowns.example.yml round-trips
        byte-identical — the load-bearing test for the surgical-edit
        promise on operator-installed substrate."""
        template = (
            Path(__file__).resolve().parent.parent
            / "config-template" / "cooldowns.example.yml"
        ).read_text(encoding="utf-8")
        added = add_rule_block_text(template, _SAMPLE_RULE_BLOCK)
        removed = remove_rule_block_text(added, "linkedin-weekly-invite-cap")
        assert removed == template

    def test_idempotent_on_absent_name(self):
        """Removing a rule that's not present returns text unchanged.
        The downgrade re-run safety property."""
        text = "version: 2\nrules:\n  - name: other\n    type: foo\n"
        out = remove_rule_block_text(text, "linkedin-weekly-invite-cap")
        assert out == text

    def test_removes_only_matched_name_not_substring(self):
        """`- name: linkedin-cap` should NOT be matched when removing
        `linkedin-weekly-invite-cap` (substring would be incorrect)."""
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: linkedin-cap\n"
            "    type: foo\n"
            "    reason: 'short name; should NOT be removed'\n"
        )
        out = remove_rule_block_text(text, "linkedin-weekly-invite-cap")
        assert out == text  # unchanged — name doesn't match exactly

    def test_quote_tolerant_single_quoted(self):
        """`- name: 'foo'` matches removal target `foo`."""
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: 'linkedin-weekly-invite-cap'\n"
            "    type: foo\n"
            "    reason: 'q'\n"
        )
        out = remove_rule_block_text(text, "linkedin-weekly-invite-cap")
        assert "linkedin-weekly-invite-cap" not in out

    def test_quote_tolerant_double_quoted(self):
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: \"linkedin-weekly-invite-cap\"\n"
            "    type: foo\n"
            "    reason: 'q'\n"
        )
        out = remove_rule_block_text(text, "linkedin-weekly-invite-cap")
        assert "linkedin-weekly-invite-cap" not in out

    def test_preserves_subsequent_rules(self):
        """Removing a middle rule preserves rules before AND after."""
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: rule-before\n"
            "    type: foo\n"
        )
        added = add_rule_block_text(text, _SAMPLE_RULE_BLOCK)
        # Append a rule AFTER the new rule.
        with_after = added + "  - name: rule-after\n    type: bar\n"
        removed = remove_rule_block_text(with_after, "linkedin-weekly-invite-cap")
        assert "  - name: rule-before\n" in removed
        assert "  - name: rule-after\n" in removed
        assert "linkedin-weekly-invite-cap" not in removed

    def test_handles_nested_field_named_name(self):
        """A nested `name:` field (e.g. inside a rule's `block_when:`
        sub-map) at deeper indent must NOT be matched — only the rule's
        own `- name:` at column-2 indent."""
        text = (
            "version: 2\n"
            "rules:\n"
            "  - name: outer-rule\n"
            "    type: foo\n"
            "    block_when:\n"
            "      name: linkedin-weekly-invite-cap\n"  # NOT a rule name
            "    reason: 'has a nested name field'\n"
        )
        out = remove_rule_block_text(text, "linkedin-weekly-invite-cap")
        # outer-rule still present.
        assert "  - name: outer-rule\n" in out
        # The nested `name:` field stays.
        assert "      name: linkedin-weekly-invite-cap\n" in out
