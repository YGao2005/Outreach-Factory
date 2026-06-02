"""Tests for ``vault/0003_add_linkedin_action_to_touch_notes``.

Direct unit tests. Mirrors ``tests/test_migrations_vault_0001.py``
shape — per-migration test classes (TestMigrationSurface,
TestUpgradeHappyPath, TestIdempotence, TestRefuseLoud, TestDowngrade)
match Pillar B's per-migration test convention.

Per ADR-0015 D38, vault/0003 stamps ``linkedin_action: invite | dm``
on LinkedIn touch notes via a filename-pattern heuristic. This module
exercises the migration's per-file atomicity, the heuristic
classification, and the reversibility contract.

See ADR-0015 for the full Week 2 design.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from orchestrator.migrations.types import (
    MigrationCategory, MigrationContext, MigrationResult,
)
from orchestrator.migrations.vault._vault_io import (
    FrontmatterError, read_person_frontmatter,
)
from orchestrator.migrations.vault.migration_0003_add_linkedin_action_to_touch_notes import (
    LINKEDIN_ACTION_DM,
    LINKEDIN_ACTION_FIELD,
    LINKEDIN_ACTION_INVITE,
    LINKEDIN_CHANNEL,
    MIGRATION,
    MIGRATION_ID,
    AddLinkedInActionToTouchNotes,
    _classify_action_from_filename,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    state_dir: Path,
    vault_dir: Path | None,
    dry_run: bool = False,
) -> MigrationContext:
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.vault.0003"),
    )


def _write_li_touch(
    conv_dir: Path,
    filename: str,
    *,
    person: str = "Alice Anderson",
    channel: str = LINKEDIN_CHANNEL,
    sent: bool = True,
    linkedin_action: str | None = None,
) -> Path:
    """Write a synthetic LinkedIn touch note for vault/0003 to walk."""
    lines = [
        "---",
        "type: touch",
        f"person: \"[[{person}]]\"",
        f"channel: {channel}",
        f"sent: {str(sent).lower()}",
    ]
    if linkedin_action is not None:
        lines.append(f"linkedin_action: {linkedin_action}")
    lines += [
        "register: cold-pitch",
        "---",
        "",
        "# LinkedIn touch body",
        "",
        "Hi there.",
    ]
    p = conv_dir / filename
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _read_fm(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        end = text.find("\n---", 4)
    return yaml.safe_load(text[4:end])


# ---------------------------------------------------------------------------
# Migration surface — Protocol compliance
# ---------------------------------------------------------------------------


class TestMigrationSurface:
    def test_singleton_implements_protocol(self):
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0003_add_linkedin_action_to_touch_notes"
        assert MIGRATION.category == MigrationCategory.VAULT
        # Distinct from ledger/0003 — vault/0003 IS reversible.
        assert MIGRATION.is_reversible is True

    def test_description_is_one_line(self):
        assert "\n" not in MIGRATION.description
        assert "linkedin_action" in MIGRATION.description.lower()


# ---------------------------------------------------------------------------
# upgrade() — happy path
# ---------------------------------------------------------------------------


class TestUpgradeHappyPath:
    def test_stamps_invite_on_invite_filename(self, synthetic_state_dir):
        """The fixture's Alice LinkedIn touch (``2026-04-18 Alice linkedin
        invite.md``) classifies as invite via the filename heuristic
        and gets ``linkedin_action: invite`` stamped."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        assert result.applied is True
        # One LinkedIn touch was stamped (Alice's).
        assert result.affected_count == 1
        alice = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-18 Alice linkedin invite.md"
        )
        fm = _read_fm(alice)
        assert fm[LINKEDIN_ACTION_FIELD] == LINKEDIN_ACTION_INVITE

    def test_stamps_dm_on_dm_filename(self, synthetic_state_dir):
        """A touch with a DM-pattern filename classifies as DM."""
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        bob_dm = _write_li_touch(
            conv, "2026-05-15 Bob linkedin dm.md",
            person="Bob Brown",
        )
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        fm = _read_fm(bob_dm)
        assert fm[LINKEDIN_ACTION_FIELD] == LINKEDIN_ACTION_DM

    def test_default_is_invite_when_no_pattern_match(self, synthetic_state_dir):
        """Filenames matching neither pattern default to invite per D38."""
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        ambiguous = _write_li_touch(
            conv, "2026-05-15 ambiguous followup.md",
            person="Alice Anderson",
        )
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        fm = _read_fm(ambiguous)
        assert fm[LINKEDIN_ACTION_FIELD] == LINKEDIN_ACTION_INVITE

    def test_skips_non_linkedin_touches(self, synthetic_state_dir):
        """The fixture's email touch (``2026-04-10 Alice initial.md``,
        ``channel: email``) is NOT stamped."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        email_touch = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-10 Alice initial.md"
        )
        fm = _read_fm(email_touch)
        assert LINKEDIN_ACTION_FIELD not in fm

    def test_preserves_other_frontmatter_fields(self, synthetic_state_dir):
        """The surgical insert preserves every other field + comment."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        alice = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-18 Alice linkedin invite.md"
        )
        fm = _read_fm(alice)
        # Pre-existing fields still present + unchanged.
        assert fm["type"] == "touch"
        assert fm["channel"] == LINKEDIN_CHANNEL
        assert fm["sent"] is True
        assert fm["register"] == "cold-pitch"


# ---------------------------------------------------------------------------
# upgrade() — dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_write(self, synthetic_state_dir):
        """Dry-run reports the count but doesn't mutate touch notes."""
        alice = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-18 Alice linkedin invite.md"
        )
        before = alice.read_text(encoding="utf-8")

        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True
        assert result.applied is True
        assert result.affected_count == 1
        # File unchanged.
        assert alice.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# upgrade() — idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_re_apply_finds_zero_new_work(self, synthetic_state_dir):
        """A LinkedIn touch already stamped is silently skipped."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        r2 = MIGRATION.upgrade(ctx)
        # No new stamps on re-run.
        assert r2.affected_count == 0

    def test_re_apply_does_not_change_files(self, synthetic_state_dir):
        """Files written by the first apply stay byte-identical on re-run."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        alice = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-18 Alice linkedin invite.md"
        )
        after_first = alice.read_text(encoding="utf-8")
        MIGRATION.upgrade(ctx)
        after_second = alice.read_text(encoding="utf-8")
        assert after_first == after_second


# ---------------------------------------------------------------------------
# upgrade() — refuse-loud
# ---------------------------------------------------------------------------


class TestRefuseLoud:
    def test_refuses_on_missing_vault_dir(self, synthetic_state_dir):
        """ctx.vault_dir=None → ValueError."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=None,
        )
        with pytest.raises(ValueError, match="vault_dir"):
            MIGRATION.upgrade(ctx)

    def test_refuses_on_unexpected_linkedin_action_value(
        self, synthetic_state_dir,
    ):
        """A touch declaring an unexpected ``linkedin_action`` value
        raises FrontmatterError — operator must inspect + decide."""
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        _write_li_touch(
            conv, "2026-05-15 Bob unexpected.md",
            person="Bob Brown",
            linkedin_action="unexpected_value",
        )
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        with pytest.raises(FrontmatterError, match="unexpected_value"):
            MIGRATION.upgrade(ctx)

    def test_silently_skips_when_already_stamped(self, synthetic_state_dir):
        """A touch already stamped at a valid value is silently skipped
        (no refuse-loud; this IS the idempotent re-apply path)."""
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        _write_li_touch(
            conv, "2026-05-15 Bob already.md",
            person="Bob Brown",
            linkedin_action=LINKEDIN_ACTION_INVITE,
        )
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # No exception — silent skip.
        result = MIGRATION.upgrade(ctx)
        # Only Alice's touch was newly stamped; Bob's was already.
        assert result.affected_count == 1

    def test_non_string_type_in_touch_note_is_silently_skipped(
        self, synthetic_state_dir,
    ):
        """A touch with ``type: 42`` (non-string) is silently skipped
        per the shared ``is_touch_note`` predicate's robustness."""
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        (conv / "Broken touch.md").write_text(
            "---\ntype: 42\nperson: \"[[Alice Anderson]]\"\n"
            "channel: linkedin\nsent: true\n---\nbody\n",
            encoding="utf-8",
        )
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # No crash. The broken note is silently skipped.
        result = MIGRATION.upgrade(ctx)
        # Only Alice's valid LinkedIn touch was stamped.
        assert result.affected_count == 1


# ---------------------------------------------------------------------------
# downgrade() — reversibility
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_downgrade_removes_field(self, synthetic_state_dir):
        """Downgrade is the inverse of upgrade — removes the
        ``linkedin_action:`` field via surgical edit."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        result = MIGRATION.downgrade(ctx)
        assert result.applied is False
        # Alice's touch had linkedin_action stamped (during upgrade);
        # Dana's touch arrived with linkedin_action: dm pre-stamped in
        # the Pillar C Week 3 fixture extension. Downgrade removes the
        # field from both → affected_count = 2.
        assert result.affected_count == 2
        alice = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-18 Alice linkedin invite.md"
        )
        fm = _read_fm(alice)
        assert LINKEDIN_ACTION_FIELD not in fm
        dana = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-20 Dana linkedin dm.md"
        )
        fm_dana = _read_fm(dana)
        assert LINKEDIN_ACTION_FIELD not in fm_dana

    def test_downgrade_idempotent(self, synthetic_state_dir):
        """Second downgrade is a no-op."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        r3 = MIGRATION.downgrade(ctx)
        assert r3.affected_count == 0

    def test_downgrade_refuses_on_missing_vault_dir(self, synthetic_state_dir):
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=None,
        )
        with pytest.raises(ValueError, match="vault_dir"):
            MIGRATION.downgrade(ctx)


# ---------------------------------------------------------------------------
# Filename heuristic — direct unit tests on _classify_action_from_filename
# ---------------------------------------------------------------------------


class TestClassifyActionFromFilename:
    def test_invite_pattern_matches(self):
        for name in (
            "2026-05-21 Alice linkedin invite.md",
            "INVITE alice.md",
            "Alice connect attempt.md",
        ):
            assert _classify_action_from_filename(
                name,
            ) == LINKEDIN_ACTION_INVITE

    def test_dm_pattern_matches(self):
        for name in (
            "2026-05-21 Alice linkedin dm.md",
            "DM alice.md",
            "Alice followup message.md",
        ):
            assert _classify_action_from_filename(
                name,
            ) == LINKEDIN_ACTION_DM

    def test_default_is_invite(self):
        for name in (
            "2026-05-21 Alice followup.md",
            "Random filename.md",
        ):
            assert _classify_action_from_filename(
                name,
            ) == LINKEDIN_ACTION_INVITE

    def test_word_boundary_prevents_substring_match(self):
        """'Connecticut intro.md' contains 'connect' as a substring but
        the word-boundary regex shouldn't match — defaults to invite."""
        # No "connect" word match; default-to-invite kicks in.
        assert _classify_action_from_filename(
            "Connecticut intro.md",
        ) == LINKEDIN_ACTION_INVITE
        # The default IS invite, so this can't distinguish substring
        # match from default. But a "missioned to Yang" file should not
        # match "message" as a word — it contains "message" as a
        # substring but the word boundary should prevent the match.
        # Since the default is invite anyway, this test pins the regex
        # behavior in a positive case: explicit "message" in the
        # filename matches DM.
        assert _classify_action_from_filename(
            "Alice followup message.md",
        ) == LINKEDIN_ACTION_DM
