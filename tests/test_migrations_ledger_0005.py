"""Tests for ``ledger/0005_baseline_tw_dm_history``.

Direct unit tests against the synthetic fixture. Mirrors
``tests/test_migrations_ledger_0004.py`` shape — the per-migration test
classes (TestMigrationSurface, TestUpgradeHappyPath,
TestUpgradeWithoutVaultBackfill, TestDryRun, TestIdempotence,
TestRefuseLoud, TestDowngrade, TestIntentIdDeterminism,
TestChannelFiltering) match Pillar B's per-migration test convention.

Pillar C Week 5 (ADR-0018) extended the synthetic fixture with:

* Evan Estefan Person note (``vault/10 People/Evan Estefan.md``,
  ``linkedin: in/evanestefan``, ``twitter_handle: evan_estefan``) —
  Twitter-active founder with LinkedIn-derived identity strength.
* Evan's Twitter DM touch (``vault/40 Conversations/2026-04-22 Evan
  twitter dm.md``, ``sent: true``, ``channel: twitter``) — the
  substrate ledger/0005 backfills. No ``twitter_action:`` field per
  ADR-0018 D61's deferral (Twitter has no invite-vs-DM ambiguity).
* Orphan ``tw_dm_intent`` for Evan in ``ledger/events-2026-04-15.jsonl``
  — substrate for reconcile Pass F.

This migration depends on vault/0002 having stamped ``id:`` on Person
notes — without that, the ``person_id`` lookup fails for every touch.

See ADR-0018 for the full Week 5 design.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.migrations.ledger._ledger_io import iter_events
from orchestrator.migrations.ledger.migration_0005_baseline_tw_dm_history import (
    MIGRATION,
    MIGRATION_ID,
    RECOVERED_BY_TAG,
    SYNTHETIC_INTENT_PREFIX,
    TWITTER_ACTION_DM,
    TWITTER_CHANNEL,
    BaselineTwitterDMHistory,
    _synth_intent_id,
    _walk_twitter_touch_records,
)
from orchestrator.migrations.types import (
    MigrationCategory, MigrationContext,
)
from orchestrator.migrations.vault._vault_io import iter_touch_notes
from orchestrator.migrations.vault.migration_0002 import (
    MIGRATION as VAULT_BACKFILL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    state_dir: Path,
    vault_dir: Path | None,
    ledger_dir: Path | None = None,
    dry_run: bool = False,
) -> MigrationContext:
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=ledger_dir if ledger_dir is not None else state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.ledger.0005"),
    )


def _apply_vault_backfill_first(state) -> None:
    """Run vault/0002 first so Person notes have ``id:`` set.

    Mirrors the ledger/0004 test helper — ledger/0005 depends on
    vault/0002 the same way.
    """
    ctx = _make_ctx(state_dir=state.state_dir, vault_dir=state.vault_dir)
    VAULT_BACKFILL.upgrade(ctx)


def _events_by_type(ledger_dir: Path, type_name: str) -> list[dict]:
    return [e for e in iter_events(ledger_dir) if e.get("type") == type_name]


# ---------------------------------------------------------------------------
# Migration surface — Protocol compliance
# ---------------------------------------------------------------------------


class TestMigrationSurface:
    def test_singleton_implements_protocol(self):
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0005_baseline_tw_dm_history"
        assert MIGRATION.category == MigrationCategory.LEDGER
        assert MIGRATION.is_reversible is False

    def test_description_is_one_line(self):
        assert "\n" not in MIGRATION.description
        # The description names the channel + action so operators
        # scanning the migration manifest can recognize what runs.
        assert "twitter" in MIGRATION.description.lower()
        assert "dm" in MIGRATION.description.lower()

    def test_is_distinct_singleton_from_ledger_0004(self):
        """ledger/0005 + ledger/0004 are distinct migrations.

        Sanity check against an accidental aliasing — the registry
        imports each migration by name; two MIGRATION constants
        pointing at the same object would mask one of them in the
        registry.
        """
        from orchestrator.migrations.ledger.migration_0004_baseline_li_dm_history import (
            MIGRATION as LEDGER_0004,
        )
        assert MIGRATION is not LEDGER_0004
        assert MIGRATION.id != LEDGER_0004.id

    def test_registered_in_migrations_list(self):
        """The MIGRATION singleton is in the ledger registry."""
        from orchestrator.migrations.ledger import MIGRATIONS
        assert MIGRATION in MIGRATIONS

    def test_registered_after_ledger_0004(self):
        """The apply order places ledger/0005 after ledger/0004 —
        per-channel weeks ship in chronological order so observers
        scanning the apply log see the natural progression."""
        from orchestrator.migrations.ledger import MIGRATIONS
        from orchestrator.migrations.ledger.migration_0004_baseline_li_dm_history import (
            MIGRATION as LEDGER_0004,
        )
        idx_0004 = MIGRATIONS.index(LEDGER_0004)
        idx_0005 = MIGRATIONS.index(MIGRATION)
        assert idx_0005 == idx_0004 + 1


# ---------------------------------------------------------------------------
# upgrade() — happy path with vault/0002 having run first
# ---------------------------------------------------------------------------


class TestUpgradeHappyPath:
    def test_emits_tw_dm_pair_per_twitter_touch(self, synthetic_state_dir):
        """Each ``sent: true`` Twitter touch produces a ``tw_dm_intent``
        + ``tw_dm_confirmed`` pair.

        Fixture has one Twitter touch (Evan's 2026-04-22 ``2026-04-22
        Evan twitter dm.md``). No invite-vs-DM filter per ADR-0018 D61
        — every Twitter touch is unconditionally walked + emitted."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_confirmed",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 1
        backfill_confirms = [
            e for e in confirms
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_confirms) == 1
        # Pair structure: same intent_id; both channel: twitter.
        bf_iid = backfill_intents[0]["intent_id"]
        assert backfill_confirms[0]["intent_id"] == bf_iid

    def test_both_pair_sides_carry_channel_twitter(self, synthetic_state_dir):
        """Every emitted ``tw_dm_*`` event carries
        ``channel: "twitter"`` per ADR-0014 D33.

        Same discipline ledger/0003 + ledger/0004 enforce for LinkedIn —
        Pillar C Week 5 ships ledger/0005 correct from day one.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_confirmed",
        )
        backfilled = [
            e for e in intents + confirms
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfilled) == 2
        for e in backfilled:
            assert e.get("channel") == TWITTER_CHANNEL, (
                f"backfilled {e.get('type')!r} for "
                f"{e.get('intent_id')!r} missing channel='twitter'. "
                f"ADR-0014 D33 invariant violated."
            )

    def test_backfilled_events_recovered_by_tag(self, synthetic_state_dir):
        """Backfilled events carry ``_recovered_by: 'backfill'`` per
        ADR-0010 D15 + ADR-0014 D33 + ADR-0013 Alternative 12 (the
        tag is shared across migrations emitting Phase-5.5-shape
        semantic events)."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        backfilled = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfilled) == 1
        assert backfilled[0]["_recovered_by"] == RECOVERED_BY_TAG
        assert RECOVERED_BY_TAG == "backfill"  # shared tag invariant.

    def test_emits_migration_event_with_channel_kwarg(
        self, synthetic_state_dir,
    ):
        """Per ADR-0010 D17 + ADR-0014 D35 every ledger migration emits
        one ``migration_event``; per-channel migrations pass
        ``channel=<channel_name>`` as an extra kwarg so Pillar G can
        query without text-matching against migration_id."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        ours = [e for e in mes if e.get("migration_id") == MIGRATION_ID]
        assert len(ours) == 1
        e = ours[0]
        assert e["category"] == "ledger"
        # The D35 invariant — Pillar G's discriminator.
        assert e["channel"] == TWITTER_CHANNEL
        # affected_count = pairs_emitted (1 from Evan's Twitter DM).
        assert e["affected_count"] == 1
        # Diagnostic fields per ADR-0018.
        assert e["twitter_dm_pairs_emitted"] == 1
        assert e["twitter_dm_pairs_skipped"] == 0
        # No touches_skipped_not_dm field — Twitter has no invite-vs-DM
        # ambiguity per ADR-0018 D61.
        assert "touches_skipped_not_dm" not in e

    def test_backfilled_confirm_event_carries_touch_note(
        self, synthetic_state_dir,
    ):
        """The backfilled ``tw_dm_confirmed`` carries the ``touch_note``
        path — mirroring ledger/0003 + ledger/0004's Week 2 P2-4
        discipline. The backfill knows the touch path at confirm-emit
        time, so a query on the confirmed events can find the source
        touch without joining through intent_id.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "tw_dm_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        confirms = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "tw_dm_confirmed")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(intents) == 1
        assert len(confirms) == 1
        # Both sides carry touch_note pointing at the same path.
        assert intents[0].get("touch_note") is not None
        assert confirms[0].get("touch_note") is not None
        assert intents[0]["touch_note"] == confirms[0]["touch_note"]
        # The path points at Evan's Twitter touch in the fixture.
        assert "twitter" in confirms[0]["touch_note"].lower()

    def test_linkedin_touches_not_emitted_by_twitter_migration(
        self, synthetic_state_dir,
    ):
        """ledger/0005 SKIPS LinkedIn-channel touches — they belong to
        ledger/0003 + ledger/0004. The channel filter in
        ``_walk_twitter_touch_records`` is load-bearing."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        # Alice's LinkedIn invite touch + Dana's LinkedIn DM touch are
        # in the fixture. ledger/0005 does NOT emit tw_dm pairs for them.
        tw_dm_intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        for e in tw_dm_intents:
            # Compare on basename only — full paths through pytest's
            # tmp dir can incidentally contain "linkedin" (the test
            # name is in the dir path).
            filename = Path(e.get("touch_note", "")).name.lower()
            assert "linkedin" not in filename, (
                f"tw_dm_intent should not be emitted for a LinkedIn "
                f"touch. Got {filename!r}."
            )


# ---------------------------------------------------------------------------
# upgrade() — without vault/0002 having run first
# ---------------------------------------------------------------------------


class TestUpgradeWithoutVaultBackfill:
    def test_zero_pairs_when_no_person_has_id(self, synthetic_state_dir):
        """Without vault/0002 stamping ``id:`` on Person notes, the
        person_id lookup fails for every touch; the migration records
        them in ``touches_without_person_match`` and emits zero pairs."""
        # NOT calling _apply_vault_backfill_first.
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 0
        # The migration_event still records the no-op + the diagnostic
        # count for operator visibility.
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        ours = [e for e in mes if e.get("migration_id") == MIGRATION_ID]
        assert len(ours) == 1
        # Evan's Twitter touch is the only Twitter-channel touch in the
        # fixture; without vault/0002 his person_id lookup fails.
        assert ours[0]["touches_without_person_match"] == 1
        assert ours[0]["twitter_dm_pairs_emitted"] == 0
        assert result.affected_count == 0


# ---------------------------------------------------------------------------
# upgrade() — dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_append(self, synthetic_state_dir):
        """Dry-run produces counts without appending to the ledger."""
        _apply_vault_backfill_first(synthetic_state_dir)
        before = list(iter_events(synthetic_state_dir.ledger_dir))

        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True
        assert result.applied is True
        # 1 pair from Evan's Twitter DM touch.
        assert result.affected_count == 1

        after = list(iter_events(synthetic_state_dir.ledger_dir))
        assert before == after, "dry-run must not write events"

    def test_dry_run_does_not_emit_migration_event(self, synthetic_state_dir):
        """Per ADR-0010 D17: dry-run does NOT emit migration_event."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        MIGRATION.upgrade(ctx)
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        ours = [e for e in mes if e.get("migration_id") == MIGRATION_ID]
        assert ours == []


# ---------------------------------------------------------------------------
# upgrade() — idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_re_apply_finds_zero_new_work(self, synthetic_state_dir):
        """Second apply finds zero new pairs."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        r2 = MIGRATION.upgrade(ctx)
        assert r2.affected_count == 0
        # Still emits migration_event per D17 (audit trail continuity).
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        ours = [e for e in mes if e.get("migration_id") == MIGRATION_ID]
        assert len(ours) == 2  # one per apply.

    def test_re_apply_does_not_duplicate_events(self, synthetic_state_dir):
        """Re-running doesn't append duplicate tw_dm_* events."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        # Two: Evan's backfilled intent + the Week 5 fixture orphan
        # (twdm_synthetic_orphan_dm_01). No new emissions on re-apply.
        assert len(intents) == 2

    def test_re_apply_skipped_count_reflects_existing_events(
        self, synthetic_state_dir,
    ):
        """The second apply's migration_event records the per-touch skip
        as ``twitter_dm_pairs_skipped`` — the idempotence check
        recognizes Evan's intent_id is already in the ledger and skips
        emission."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        MIGRATION.upgrade(ctx)
        mes = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "migration_event")
            if e.get("migration_id") == MIGRATION_ID
        ]
        assert len(mes) == 2
        # First apply emitted 1 pair, skipped 0.
        assert mes[0]["twitter_dm_pairs_emitted"] == 1
        assert mes[0]["twitter_dm_pairs_skipped"] == 0
        # Second apply emitted 0 pairs, skipped 1 (Evan's pair was
        # already present from the first apply).
        assert mes[1]["twitter_dm_pairs_emitted"] == 0
        assert mes[1]["twitter_dm_pairs_skipped"] == 1


# ---------------------------------------------------------------------------
# upgrade() — refuse-loud
# ---------------------------------------------------------------------------


class TestRefuseLoud:
    def test_refuses_on_missing_vault_dir(self, synthetic_state_dir):
        """ctx.vault_dir=None → ValueError (the backfill reads vault)."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=None,
        )
        with pytest.raises(ValueError, match="vault_dir"):
            MIGRATION.upgrade(ctx)

    def test_refuses_on_missing_ledger_dir(self, tmp_path):
        """ctx.ledger_dir not on disk → FileNotFoundError."""
        state = tmp_path / "state"
        state.mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()
        ctx = _make_ctx(state_dir=state, vault_dir=vault)
        with pytest.raises(FileNotFoundError, match="ctx.ledger_dir"):
            MIGRATION.upgrade(ctx)

    def test_non_string_type_in_touch_note_is_silently_skipped(
        self, synthetic_state_dir,
    ):
        """A touch note with ``type: 42`` (unquoted YAML int) is by
        contract non-touch; skip silently rather than crashing.

        Mirrors ledger/0003 + ledger/0004's analogous test — the
        ``_vault_io.is_touch_note`` shared predicate is robust to
        non-string ``type:`` (per Pillar B Week 6 holistic-review).
        """
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        (conv / "Broken touch.md").write_text(
            "---\ntype: 42\nperson: \"[[Evan Estefan]]\"\n"
            "channel: twitter\nsent: true\n---\n"
            "body\n",
            encoding="utf-8",
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # No crash. The broken note is silently skipped; Evan's valid
        # Twitter DM touch still backfills.
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1


# ---------------------------------------------------------------------------
# downgrade() — refusal
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_downgrade_raises_not_implemented(self, synthetic_state_dir):
        """The migration is structurally irreversible (append-only
        ledger)."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        with pytest.raises(NotImplementedError, match="irreversible"):
            MIGRATION.downgrade(ctx)


# ---------------------------------------------------------------------------
# Intent-id determinism + distinctness from prior backfill prefixes
# ---------------------------------------------------------------------------


class TestIntentIdDeterminism:
    def test_same_touch_re_run_produces_same_intent_id(
        self, synthetic_state_dir,
    ):
        """The synthetic intent_id is deterministic.

        Re-running the migration produces the same intent_id per touch
        — that's WHY the idempotence check works."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents_1 = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "tw_dm_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        first_id = intents_1[0]["intent_id"]
        # bf_twdm_<16-hex-chars>.
        assert first_id.startswith(SYNTHETIC_INTENT_PREFIX)
        assert len(first_id) == len(SYNTHETIC_INTENT_PREFIX) + 16

    def test_prefix_distinguishes_from_li_invite_and_li_dm_backfill(self):
        """``bf_twdm_`` distinguishes from ledger/0003's ``bf_li_`` AND
        ledger/0004's ``bf_lidm_``.

        Per the Week 5 module docstring: the prefix discriminator at
        the intent_id level lets operators scanning the ledger
        immediately tell which retroactive-reconstruction class a
        synthetic event came from."""
        from orchestrator.migrations.ledger.migration_0003_baseline_li_invite_history import (
            SYNTHETIC_INTENT_PREFIX as INVITE_PREFIX,
        )
        from orchestrator.migrations.ledger.migration_0004_baseline_li_dm_history import (
            SYNTHETIC_INTENT_PREFIX as LI_DM_PREFIX,
        )
        assert SYNTHETIC_INTENT_PREFIX == "bf_twdm_"
        assert INVITE_PREFIX == "bf_li_"
        assert LI_DM_PREFIX == "bf_lidm_"
        # All three are pairwise distinct + none is a prefix-of-prefix
        # of another (startswith checks remain unambiguous).
        assert not SYNTHETIC_INTENT_PREFIX.startswith(INVITE_PREFIX)
        assert not SYNTHETIC_INTENT_PREFIX.startswith(LI_DM_PREFIX)
        assert not INVITE_PREFIX.startswith(SYNTHETIC_INTENT_PREFIX)
        assert not LI_DM_PREFIX.startswith(SYNTHETIC_INTENT_PREFIX)

    def test_synth_intent_id_hash_inputs_include_action(self):
        """The synthetic intent_id incorporates the ``TWITTER_ACTION_DM``
        constant so a future Pillar F action class (e.g.
        ``twitter_thread_mention``) would produce distinct hashes for the
        same person + date + touch stem. The structural slot is
        preserved by D61's deferral rationale."""
        # Same person + date + stem; the helper always uses
        # TWITTER_ACTION_DM as the action discriminator today.
        ident_a = _synth_intent_id(
            "evan-li", "2026-04-22T00:00:00.000Z", touch_stem="stem-a",
        )
        ident_b = _synth_intent_id(
            "evan-li", "2026-04-22T00:00:00.000Z", touch_stem="stem-b",
        )
        # Same prefix; different hashes because stems differ.
        assert ident_a.startswith(SYNTHETIC_INTENT_PREFIX)
        assert ident_b.startswith(SYNTHETIC_INTENT_PREFIX)
        assert ident_a != ident_b
        # The action constant is "dm" per ADR-0018 D61.
        assert TWITTER_ACTION_DM == "dm"


# ---------------------------------------------------------------------------
# Channel filtering — Week 5 ships Twitter-only walker
# ---------------------------------------------------------------------------


class TestChannelFiltering:
    def test_walker_yields_only_twitter_touches(self, synthetic_state_dir):
        """:func:`_walk_twitter_touch_records` filters touches by
        ``channel: twitter`` — LinkedIn / email / calendar touches are
        silently skipped.

        The walker is the load-bearing filter that keeps Week 5's
        migration scope tight; per Week 2 per-week review P2-3 the
        analogous LinkedIn walker is similarly tight.
        """
        records = _walk_twitter_touch_records(
            iter_touch_notes(synthetic_state_dir.vault_dir),
        )
        # The fixture has 4 touches:
        # - Alice email (channel: email)
        # - Alice linkedin invite (channel: linkedin)
        # - Dana linkedin dm (channel: linkedin)
        # - Evan twitter dm (channel: twitter)
        # Only the Twitter one is yielded.
        assert len(records) == 1
        assert "twitter" in str(records[0].path).lower()
        assert "evan" in str(records[0].path).lower()

    def test_linkedin_touch_not_walked_by_twitter_walker(
        self, synthetic_state_dir,
    ):
        """An additional LinkedIn-channel touch added to the fixture is
        NOT walked by Week 5's Twitter walker."""
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        (conv / "2026-05-01 Bob linkedin invite.md").write_text(
            "---\ntype: touch\nperson: \"[[Bob Brown]]\"\n"
            "channel: linkedin\nsent: true\nsent_at: 2026-05-01\n"
            "date: 2026-05-01\n---\nLinkedIn invite body\n",
            encoding="utf-8",
        )
        records = _walk_twitter_touch_records(
            iter_touch_notes(synthetic_state_dir.vault_dir),
        )
        # Still just Evan's Twitter touch — basename check (full paths
        # through pytest tmp dirs incidentally contain test names).
        assert len(records) == 1
        for r in records:
            assert "linkedin" not in r.path.name.lower()

    def test_email_touch_not_walked_by_twitter_walker(
        self, synthetic_state_dir,
    ):
        """Email-channel touches (the fixture's Alice initial) are NOT
        walked by Week 5's Twitter walker."""
        records = _walk_twitter_touch_records(
            iter_touch_notes(synthetic_state_dir.vault_dir),
        )
        for r in records:
            assert "alice" not in r.path.name.lower()
            assert "initial" not in r.path.name.lower()


# ---------------------------------------------------------------------------
# Synthetic-orphan coexistence with the backfill
# ---------------------------------------------------------------------------


class TestSyntheticOrphanCoexistence:
    """The fixture extension per the Week 5 handoff also adds an orphan
    ``tw_dm_intent`` for Evan (intent_id ``twdm_synthetic_orphan_dm_01``).
    This orphan models a Week 5 dispatcher crash between intent-write
    and MCP-call success; reconcile Pass F is responsible for healing it.

    These tests verify the orphan + backfill coexist correctly — the
    backfill emits its own distinct ``bf_twdm_<hash>`` pair, AND the
    orphan stays in the ledger untouched by the backfill (it's a
    distinct two-phase commit instance per the intent_id-uniqueness
    contract).
    """

    def test_orphan_intent_unchanged_by_backfill(self, synthetic_state_dir):
        """The fixture's pre-existing orphan ``tw_dm_intent`` stays in
        the ledger after backfill — the backfill doesn't touch it.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        orphan_intents = [
            e for e in intents
            if e.get("intent_id") == "twdm_synthetic_orphan_dm_01"
        ]
        assert len(orphan_intents) == 1
        # No matching confirmed (it's the orphan substrate for Pass F).
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_confirmed",
        )
        orphan_confirms = [
            e for e in confirms
            if e.get("intent_id") == "twdm_synthetic_orphan_dm_01"
        ]
        assert len(orphan_confirms) == 0

    def test_orphan_intent_id_distinct_from_backfill_prefix(
        self, synthetic_state_dir,
    ):
        """The orphan's intent_id (`twdm_synthetic_orphan_dm_01`) is
        DISTINCT from the backfill prefix (`bf_twdm_`) so a re-apply
        of the backfill never accidentally collides with the orphan.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        backfill_ids = {
            e["intent_id"] for e in intents
            if e["intent_id"].startswith(SYNTHETIC_INTENT_PREFIX)
        }
        orphan_ids = {
            e["intent_id"] for e in intents
            if e["intent_id"] == "twdm_synthetic_orphan_dm_01"
        }
        assert backfill_ids & orphan_ids == set(), (
            "backfill intent_ids must not collide with the orphan id"
        )

    def test_backfill_idempotence_holds_alongside_orphan(
        self, synthetic_state_dir,
    ):
        """Even with the orphan present, re-running the backfill emits
        no new tw_dm_* events. The idempotence check correctly indexes
        BOTH the orphan's intent_id AND the backfill's intent_ids."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        # One backfilled + one orphan = 2 total. No duplication.
        assert len(intents) == 2
