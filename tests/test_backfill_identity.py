"""Tests for orchestrator/backfill_identity.py.

Covers:
  - parse_person_note: legacy field extraction, identity-keys round-trip,
    non-person notes are skipped
  - render_with_identity: surgical insert, idempotency, preserved quoting
  - detect_conflicts: pairwise + transitive (Union-Find) clusters
  - build_plan / apply_plan / validate_vault: end-to-end flows
  - --apply refusal when migration-conflicts.yml has unresolved entries
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator import backfill_identity as B
from orchestrator import identity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def people_dir(tmp_path: Path) -> Path:
    d = tmp_path / "10 People"
    (d / "🟦 Queue").mkdir(parents=True)
    (d / "🟧 Active").mkdir(parents=True)
    return d


def _write_note(people_dir: Path, subdir: str, name: str,
                fm_lines: list[str], body: str = "") -> Path:
    fm_block = "\n".join(fm_lines)
    body = body or f"# {name}\n"
    path = people_dir / subdir / f"{name}.md"
    path.write_text(f"---\n{fm_block}\n---\n\n{body}", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_person_note
# ---------------------------------------------------------------------------


class TestParse:
    def test_parses_legacy_frontmatter(self, people_dir):
        path = _write_note(people_dir, "🟦 Queue", "Alex Liu", [
            "type: person",
            "name: Alex Liu",
            'company: "[[Korso]]"',
            "linkedin: https://www.linkedin.com/in/alexdliu7/",
            "email: alex@korso.ai",
            "twitter:",
        ])
        parsed = B.parse_person_note(path)
        assert parsed is not None
        assert parsed.frontmatter["name"] == "Alex Liu"
        assert parsed.keys.linkedin == "in/alexdliu7"
        assert "alex@korso.ai" in parsed.keys.emails
        assert parsed.proposed_id == "alexdliu7-li"
        assert parsed.has_id is False
        assert parsed.has_identity_keys is False

    def test_skips_non_person_notes(self, people_dir):
        path = _write_note(people_dir, "🟦 Queue", "Some Doc", [
            "type: meeting", "name: A meeting",
        ])
        assert B.parse_person_note(path) is None

    def test_recognizes_existing_identity_block(self, people_dir):
        path = _write_note(people_dir, "🟧 Active", "Already Done", [
            "type: person",
            "name: Already Done",
            "id: done-li",
            "identity_keys:",
            "  linkedin: in/done",
            "identity_version: 1",
        ])
        parsed = B.parse_person_note(path)
        assert parsed.has_id is True
        assert parsed.has_identity_keys is True
        assert parsed.existing_id == "done-li"
        assert parsed.proposed_id == "done-li"   # honor existing

    def test_tmp_id_when_no_strong_keys(self, people_dir):
        path = _write_note(people_dir, "🟦 Queue", "Nobody", [
            "type: person", "name: Nobody",
            'company: "[[Ghost]]"',
        ])
        parsed = B.parse_person_note(path)
        assert parsed.proposed_id.endswith("-tmp")
        assert parsed.skip_reason == "no_identity_keys"

    def test_handles_unparseable_frontmatter(self, people_dir):
        bad = people_dir / "🟦 Queue" / "Bad.md"
        bad.write_text("---\nthis: is: not: yaml: ::\n---\n\nhi", encoding="utf-8")
        assert B.parse_person_note(bad) is None

    def test_handles_emails_list(self, people_dir):
        path = _write_note(people_dir, "🟧 Active", "Multi Email", [
            "type: person", "name: Multi Email",
            "emails:",
            "  - one@example.com",
            "  - two@example.com",
        ])
        parsed = B.parse_person_note(path)
        assert {"one@example.com", "two@example.com"} <= parsed.keys.emails


# ---------------------------------------------------------------------------
# render_with_identity
# ---------------------------------------------------------------------------


class TestRender:
    def test_inserts_after_type_line(self, people_dir):
        path = _write_note(people_dir, "🟦 Queue", "Dylan", [
            "type: person",
            "name: Dylan Teixeira",
            'company: "[[Gojiberry AI]]"',
            "linkedin: https://linkedin.com/in/dylan-txa",
        ])
        parsed = B.parse_person_note(path)
        out = B.render_with_identity(parsed)
        # Re-parse to verify structure
        new = B.parse_person_note(_write_text(path, out))
        assert new.has_id is True
        assert new.has_identity_keys is True
        assert new.existing_id == "dylan-txa-li"
        # Original company quoting style preserved
        assert 'company: "[[Gojiberry AI]]"' in out

    def test_idempotent_double_render(self, people_dir):
        path = _write_note(people_dir, "🟦 Queue", "Idem", [
            "type: person", "name: Idem",
            "linkedin: https://linkedin.com/in/idem-slug",
        ])
        parsed = B.parse_person_note(path)
        once = B.render_with_identity(parsed)
        _write_text(path, once)
        parsed2 = B.parse_person_note(path)
        twice = B.render_with_identity(parsed2)
        assert once == twice
        # And only one id line
        assert twice.count("\nid: ") == 1
        assert twice.count("\nidentity_keys:") == 1

    def test_inserts_at_top_when_no_type_line(self, people_dir):
        # Synthetic edge case: notes without `type:` shouldn't happen post-parse,
        # but the rendering helper should still produce valid YAML.
        path = _write_note(people_dir, "🟦 Queue", "Type Stripped", [
            "type: person",   # required to parse
            "name: Type Stripped",
            "linkedin: https://linkedin.com/in/strip",
        ])
        parsed = B.parse_person_note(path)
        # Manually strip the type line to exercise the fallback path.
        parsed.fm_text_lines = [
            ln for ln in parsed.fm_text_lines
            if not ln.startswith("type:")
        ]
        out = B.render_with_identity(parsed)
        # id should sit at or near top (after name:, which we kept)
        fm = out.split("---")[1]
        assert "id: strip-li" in fm

    def test_preserves_pipeline_stage_and_extras(self, people_dir):
        path = _write_note(people_dir, "🟧 Active", "Preserve", [
            "type: person",
            "name: Preserve Test",
            'company: "[[Foo]]"',
            "linkedin: https://linkedin.com/in/preserve",
            "pipeline_stage: drafted",
            "pipeline_enrolled_at: 2026-05-10T00:00:00Z",
            "status: queued",
            "tags:",
            "  - tag-one",
            "  - tag-two",
        ])
        parsed = B.parse_person_note(path)
        out = B.render_with_identity(parsed)
        assert "pipeline_stage: drafted" in out
        assert "pipeline_enrolled_at: 2026-05-10T00:00:00Z" in out
        assert "tag-one" in out and "tag-two" in out

    def test_converges_from_partial_state(self, people_dir):
        """If a previous run wrote `id:` but not `identity_keys:` (or vice
        versa), the next run should strip the stale half and emit a
        complete block — strip + reinsert."""
        path = _write_note(people_dir, "🟦 Queue", "Partial", [
            "type: person",
            "name: Partial",
            "id: stale-li",         # left over from a half-finished run
            "linkedin: https://linkedin.com/in/partial",
        ])
        parsed = B.parse_person_note(path)
        out = B.render_with_identity(parsed)
        # id was preserved (existing_id wins) but identity_keys is now present
        assert out.count("\nid: ") == 1
        assert "id: stale-li" in out
        assert "identity_keys:" in out
        assert "linkedin: in/partial" in out

    def test_double_apply_is_idempotent(self, people_dir):
        """After a clean apply, re-running render on the re-parsed note
        produces no change."""
        path = _write_note(people_dir, "🟦 Queue", "Clean", [
            "type: person", "name: Clean",
            "linkedin: https://linkedin.com/in/clean",
        ])
        first = B.render_with_identity(B.parse_person_note(path))
        _write_text(path, first)
        second = B.render_with_identity(B.parse_person_note(path))
        assert second == first


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# detect_conflicts
# ---------------------------------------------------------------------------


class TestDetectConflicts:
    def test_two_records_share_linkedin(self, people_dir):
        _write_note(people_dir, "🟧 Active", "A1", [
            "type: person", "name: A1",
            "linkedin: https://linkedin.com/in/shared-slug",
        ])
        _write_note(people_dir, "🟧 Active", "A2", [
            "type: person", "name: A2",
            "linkedin: https://linkedin.com/in/shared-slug",
        ])
        plan = B.build_plan(people_dir)
        assert len(plan.conflicts) == 1
        cluster = plan.conflicts[0]
        assert len(cluster.note_paths) == 2
        assert "linkedin" in cluster.shared_keys

    def test_transitive_cluster_three_notes(self, people_dir):
        """A↔B via email, B↔C via linkedin -> {A, B, C} all in one cluster."""
        _write_note(people_dir, "🟧 Active", "A", [
            "type: person", "name: A",
            "email: shared@x.com",
        ])
        _write_note(people_dir, "🟧 Active", "B", [
            "type: person", "name: B",
            "email: shared@x.com",
            "linkedin: https://linkedin.com/in/connector",
        ])
        _write_note(people_dir, "🟧 Active", "C", [
            "type: person", "name: C",
            "linkedin: https://linkedin.com/in/connector",
        ])
        plan = B.build_plan(people_dir)
        assert len(plan.conflicts) == 1
        assert len(plan.conflicts[0].note_paths) == 3

    def test_no_false_positive_on_name_collision(self, people_dir):
        """Two distinct Alex Lius with different LinkedIns -> NOT a conflict.
        This is the failure mode the identity layer exists to fix."""
        _write_note(people_dir, "🟧 Active", "Alex Liu A", [
            "type: person", "name: Alex Liu",
            "linkedin: https://linkedin.com/in/alex-a",
        ])
        _write_note(people_dir, "🟧 Active", "Alex Liu B", [
            "type: person", "name: Alex Liu",
            "linkedin: https://linkedin.com/in/alex-b",
        ])
        plan = B.build_plan(people_dir)
        assert plan.conflicts == []

    def test_empty_keys_dont_intersect(self, people_dir):
        """Two notes with no identity keys do NOT collide on alt_names.
        alt_names is diagnostic-only, not a match class."""
        _write_note(people_dir, "🟦 Queue", "Unknown One", [
            "type: person", "name: Unknown One",
        ])
        _write_note(people_dir, "🟦 Queue", "Unknown Two", [
            "type: person", "name: Unknown Two",
        ])
        plan = B.build_plan(people_dir)
        assert plan.conflicts == []


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApply:
    def test_apply_writes_id_and_keys(self, people_dir):
        path = _write_note(people_dir, "🟦 Queue", "Apply Me", [
            "type: person", "name: Apply Me",
            "linkedin: https://linkedin.com/in/apply-me",
        ])
        plan = B.build_plan(people_dir)
        result = B.apply_plan(plan)
        assert result["ok"] is True
        assert result["applied"] == 1
        text = path.read_text(encoding="utf-8")
        assert "id: apply-me-li" in text
        assert "identity_keys:" in text
        assert "identity_version: 1" in text

    def test_apply_refuses_on_conflicts(self, people_dir):
        _write_note(people_dir, "🟧 Active", "C1", [
            "type: person", "name: C1",
            "linkedin: https://linkedin.com/in/dup",
        ])
        _write_note(people_dir, "🟧 Active", "C2", [
            "type: person", "name: C2",
            "linkedin: https://linkedin.com/in/dup",
        ])
        plan = B.build_plan(people_dir)
        result = B.apply_plan(plan)
        assert result["ok"] is False
        assert "conflict" in result["reason"]
        assert result["applied"] == 0

    def test_apply_force_bypasses_conflict_block(self, people_dir):
        _write_note(people_dir, "🟧 Active", "F1", [
            "type: person", "name: F1",
            "linkedin: https://linkedin.com/in/force-dup",
        ])
        _write_note(people_dir, "🟧 Active", "F2", [
            "type: person", "name: F2",
            "linkedin: https://linkedin.com/in/force-dup",
        ])
        plan = B.build_plan(people_dir)
        result = B.apply_plan(plan, force=True)
        assert result["ok"] is True
        assert result["applied"] == 2

    def test_apply_idempotent_skip_already_complete(self, people_dir):
        path = _write_note(people_dir, "🟦 Queue", "Done", [
            "type: person", "name: Done",
            "id: done-li",
            "identity_keys:",
            "  linkedin: in/done",
            "identity_version: 1",
        ])
        plan = B.build_plan(people_dir)
        result = B.apply_plan(plan)
        assert result["ok"] is True
        assert result["applied"] == 0
        assert result["skipped"] == 1

    def test_apply_then_validate_passes(self, people_dir):
        _write_note(people_dir, "🟦 Queue", "V1", [
            "type: person", "name: V1",
            "linkedin: https://linkedin.com/in/v1",
        ])
        _write_note(people_dir, "🟧 Active", "V2", [
            "type: person", "name: V2",
            "email: v2@example.com",
        ])
        plan = B.build_plan(people_dir)
        B.apply_plan(plan)
        result = B.validate_vault(people_dir)
        assert result["ok"] is True
        assert result["missing_id"] == []
        assert result["missing_identity_keys"] == []


# ---------------------------------------------------------------------------
# Conflict file workflow
# ---------------------------------------------------------------------------


class TestConflictFile:
    def test_write_conflicts_file(self, people_dir, tmp_path):
        _write_note(people_dir, "🟧 Active", "X", [
            "type: person", "name: X", "linkedin: https://linkedin.com/in/x",
        ])
        _write_note(people_dir, "🟧 Active", "X2", [
            "type: person", "name: X2", "linkedin: https://linkedin.com/in/x",
        ])
        plan = B.build_plan(people_dir)
        target = tmp_path / "conflicts.yml"
        B.write_conflicts_file(plan, target)
        assert target.exists()
        body = yaml.safe_load(target.read_text())
        assert body["version"] == 1
        assert len(body["conflicts"]) == 1
        assert body["conflicts"][0]["resolved"] is False

    def test_read_unresolved_skips_resolved(self, tmp_path):
        path = tmp_path / "conflicts.yml"
        path.write_text(yaml.safe_dump({
            "version": 1,
            "conflicts": [
                {"note_paths": ["a"], "resolved": False},
                {"note_paths": ["b"], "resolved": True},
            ],
        }))
        unresolved = B.read_unresolved_conflicts(path)
        assert len(unresolved) == 1
        assert unresolved[0]["note_paths"] == ["a"]

    def test_read_unresolved_handles_missing_file(self, tmp_path):
        assert B.read_unresolved_conflicts(tmp_path / "missing.yml") == []


# ---------------------------------------------------------------------------
# Round-trip with identity.read_person_keys (cross-module integration)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_backfilled_note_is_readable_by_identity(self, people_dir):
        path = _write_note(people_dir, "🟦 Queue", "Round Trip", [
            "type: person", "name: Round Trip",
            "linkedin: https://linkedin.com/in/round-trip",
            "email: round@trip.com",
        ])
        plan = B.build_plan(people_dir)
        B.apply_plan(plan)
        parsed = identity.read_person_keys(path)
        assert parsed is not None
        person_id, keys = parsed
        assert person_id == "round-trip-li"
        assert keys.linkedin == "in/round-trip"
        assert "round@trip.com" in keys.emails

    def test_backfilled_note_matches_via_identity_layer(self, people_dir):
        """The whole point: post-backfill, identity.find_matches sees the
        records and matches by identity_keys block (not legacy fields)."""
        path = _write_note(people_dir, "🟦 Queue", "Match Me", [
            "type: person", "name: Match Me",
            "linkedin: https://linkedin.com/in/match-me",
        ])
        plan = B.build_plan(people_dir)
        B.apply_plan(plan)
        # Re-read raw text; legacy `linkedin:` line is still there too, but
        # the identity_keys block is the load-bearing one.
        keys = identity.compute_keys(
            linkedin_url="https://linkedin.com/in/match-me",
        )
        matches = identity.find_matches(keys, people_dir)
        assert len(matches) == 1
        assert matches[0].note_path == path
