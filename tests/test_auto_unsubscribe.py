"""Pillar D Week 4-5 — auto-unsubscribe handler unit tests.

Per ADR-0028 D115-D117. Covers:

* The (dimension, value) resolution per channel.
* The YAML-first + ledger-second write order (apply path).
* The dedup-by-(reply_message_id, channel) requirement
  (LOAD-BEARING per ADR-0028 D117 — the Week 2 P2-B carry-forward).
* The legal-liability guard (only ``category=unsubscribe`` events
  drive writes; long-tail categories never trigger).
* The dry-run path.
* The since-window filter.
* The YAML idempotence (forget_append is set-based; duplicate writes
  produce the same on-disk state).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import auto_unsubscribe as au
import ledger as _ledger


def _ledger_with(events, ledger_dir):
    led = _ledger.Ledger(ledger_dir)
    for e in events:
        led.append(e)
    return led


def _reply_received_email(*, person_id, mid, from_addr, ts):
    return {
        "type": "reply_received",
        "person_id": person_id,
        "channel": "email",
        "gmail_message_id": mid,
        "gmail_thread_id": f"thr_{mid}",
        "from": from_addr,
        "subject": "Re: outreach",
        "body": "please unsubscribe me",
        "ts": ts,
    }


def _reply_classified_unsubscribe(*, person_id, channel, reply_mid, ts):
    return {
        "type": "reply_classified",
        "person_id": person_id,
        "channel": channel,
        "reply_message_id": reply_mid,
        "reply_to_intent_id": None,
        "category": "unsubscribe",
        "classification_method": "rule",
        "confidence": 1.0,
        "matched_pattern": r"\bunsubscribe\b",
        "_emitted_by": "reply_classifier",
        "ts": ts,
    }


class TestResolveSuppressionTarget:
    """Per ADR-0028 D115 — the per-channel resolution contract."""

    def test_email_channel_with_from_header_resolves_to_email_dimension(
        self, tmp_path,
    ):
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_1", mid="gid_001",
                    from_addr="Bob Smith <bob@example.test>",
                    ts="2026-05-22T12:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        classified = _reply_classified_unsubscribe(
            person_id="p_1", channel="email",
            reply_mid="gid_001", ts="2026-05-22T12:00:01.000Z",
        )
        target = au.resolve_suppression_target(classified, led)
        assert target.dimension == "email"
        assert target.value == "bob@example.test"

    def test_email_channel_bare_address_resolves(self, tmp_path):
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_2", mid="gid_002",
                    from_addr="alice@bar.test",
                    ts="2026-05-22T12:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        classified = _reply_classified_unsubscribe(
            person_id="p_2", channel="email",
            reply_mid="gid_002", ts="2026-05-22T12:00:01.000Z",
        )
        target = au.resolve_suppression_target(classified, led)
        assert target.dimension == "email"
        assert target.value == "alice@bar.test"

    def test_email_channel_missing_from_header_falls_back_to_identity_key(
        self, tmp_path,
    ):
        # Reply without ``from`` header — legacy / malformed shape.
        # Handler falls back to identity_key per ADR-0028 D115.
        led = _ledger_with(
            [
                {
                    "type": "reply_received",
                    "person_id": "p_3",
                    "channel": "email",
                    "gmail_message_id": "gid_003",
                    "gmail_thread_id": "thr_003",
                    "subject": "Re: outreach",
                    "ts": "2026-05-22T12:00:00.000Z",
                },
            ],
            tmp_path / "ledger",
        )
        classified = _reply_classified_unsubscribe(
            person_id="p_3", channel="email",
            reply_mid="gid_003", ts="2026-05-22T12:00:01.000Z",
        )
        target = au.resolve_suppression_target(classified, led)
        assert target.dimension == "identity_key"
        assert target.value == "p_3"

    def test_linkedin_channel_resolves_to_identity_key(self, tmp_path):
        led = _ledger_with([], tmp_path / "ledger")
        classified = _reply_classified_unsubscribe(
            person_id="in/jane-doe", channel="linkedin",
            reply_mid="li_msg_001", ts="2026-05-22T12:00:00.000Z",
        )
        target = au.resolve_suppression_target(classified, led)
        assert target.dimension == "identity_key"
        assert target.value == "in/jane-doe"

    def test_twitter_channel_resolves_to_identity_key(self, tmp_path):
        led = _ledger_with([], tmp_path / "ledger")
        classified = _reply_classified_unsubscribe(
            person_id="p_5", channel="twitter",
            reply_mid="tw_001", ts="2026-05-22T12:00:00.000Z",
        )
        target = au.resolve_suppression_target(classified, led)
        assert target.dimension == "identity_key"
        assert target.value == "p_5"

    def test_no_email_no_person_id_refuses_loud(self, tmp_path):
        led = _ledger_with([], tmp_path / "ledger")
        classified = {
            "type": "reply_classified",
            "channel": "linkedin",
            "reply_message_id": "li_msg_x",
            "category": "unsubscribe",
            "classification_method": "rule",
            "confidence": 1.0,
            # Missing person_id.
        }
        with pytest.raises(ValueError, match="neither a resolvable email"):
            au.resolve_suppression_target(classified, led)


class TestRunAutoUnsubscribeApplyPath:
    """Per ADR-0028 D115-D117 — apply-path behaviors."""

    def _seed(self, tmp_path):
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_a", mid="gid_a",
                    from_addr="alice@x.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _reply_classified_unsubscribe(
                    person_id="p_a", channel="email", reply_mid="gid_a",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()
        return led, sup_dir

    def test_apply_writes_yaml_first_then_ledger(self, tmp_path):
        led, sup_dir = self._seed(tmp_path)
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir, since=since, apply=True,
        )

        # Assert YAML write happened.
        yaml_path = sup_dir / au.AUTO_UNSUBSCRIBE_FILENAME
        assert yaml_path.exists(), (
            f"YAML must be written; missing at {yaml_path}"
        )
        on_disk = yaml.safe_load(yaml_path.read_text())
        assert on_disk["version"] == 1
        assert "alice@x.test" in on_disk["emails"]

        # Assert ledger event was appended.
        assert result.examined == 1
        assert len(result.synthesized) == 1
        added = result.synthesized[0]
        assert added["type"] == "suppression_added"
        assert added["person_id"] == "p_a"
        assert added["channel"] == "email"
        assert added["suppressed_dimension"] == "email"
        assert added["suppressed_value"] == "alice@x.test"
        assert added["source_reply_classified_event"]["reply_message_id"] == "gid_a"
        assert added["source_reply_classified_event"]["channel"] == "email"
        assert added["_emitted_by"] == "auto_unsubscribe_handler"

        # Ledger walk reflects the new event.
        ledger_events = [
            e for e in led.all_events()
            if e.get("type") == "suppression_added"
        ]
        assert len(ledger_events) == 1

    def test_yaml_write_failure_propagates_no_ledger_emission(
        self, tmp_path, monkeypatch,
    ):
        """Per ADR-0025 D100's failure-mode matrix: when ``forget_append``
        raises (disk full, permission, etc.), the handler:

        * Records the error in ``result.errors``.
        * Does NOT emit a ``suppression_added`` ledger event for the
          failing classified event (no orphan audit-trail entry).
        * Continues to subsequent classified events (one failure
          doesn't abort the whole pass).

        Per the per-week reviewer's P2-B finding — this surface was
        not directly tested; the crash-injection test only covered
        the ledger-append-failure leg. Both failure modes need
        coverage.
        """
        led, sup_dir = self._seed(tmp_path)
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)

        # Patch ``forget_append`` to raise OSError. We patch via the
        # module the handler imports from — the handler does
        # ``from policy.suppression import forget_append`` at module
        # load time, so we patch the symbol in the handler's namespace.
        from datetime import datetime as _dt, timezone as _tz
        import auto_unsubscribe as _au_mod
        real_fa = _au_mod.forget_append
        def failing_forget_append(*args, **kwargs):
            raise OSError("simulated disk full")
        monkeypatch.setattr(_au_mod, "forget_append", failing_forget_append)

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir, since=since, apply=True,
        )

        # Error captured.
        assert len(result.errors) == 1
        assert "forget_append failed" in result.errors[0]
        assert "simulated disk full" in result.errors[0]

        # No suppression_added emitted (no orphan audit trail per
        # ADR-0025 D100 — the YAML write must succeed BEFORE the
        # ledger emits anything).
        assert not [
            e for e in result.synthesized
            if e.get("type") == "suppression_added"
        ]

        # YAML NOT written (we faked the write).
        assert not (sup_dir / au.AUTO_UNSUBSCRIBE_FILENAME).exists()

        # The ledger likewise has no suppression_added events.
        assert not [
            e for e in led.all_events()
            if e.get("type") == "suppression_added"
        ]

    def test_yaml_write_first_invariant_under_ledger_append_failure(
        self, tmp_path, monkeypatch,
    ):
        """ADR-0025 D100 — if ledger append fails AFTER YAML write,
        suppression is LIVE despite incomplete audit trail."""
        led, sup_dir = self._seed(tmp_path)
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)

        # Force ledger append to fail on the suppression_added event.
        # The YAML write should have already happened; the handler
        # captures the error + continues.
        real_append = led.append
        def failing_append(event):
            if event.get("type") == "suppression_added":
                raise OSError("disk full")
            return real_append(event)
        monkeypatch.setattr(led, "append", failing_append)

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir, since=since, apply=True,
        )

        # YAML is LIVE per ADR-0025 D100's invariant.
        yaml_path = sup_dir / au.AUTO_UNSUBSCRIBE_FILENAME
        assert yaml_path.exists()
        on_disk = yaml.safe_load(yaml_path.read_text())
        assert "alice@x.test" in on_disk["emails"]

        # Error captured + no suppression_added in result.synthesized.
        assert len(result.errors) == 1
        assert "ledger append failed" in result.errors[0]
        assert not [
            e for e in result.synthesized
            if e.get("type") == "suppression_added"
        ]

    def test_only_unsubscribe_category_triggers_writes(self, tmp_path):
        """ADR-0025 D97 invariant — long-tail categories DON'T trigger
        auto-suppression. Only ``category=unsubscribe`` does."""
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_x", mid="gid_x",
                    from_addr="x@x.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                # Classified as INTEREST, not unsubscribe.
                {
                    "type": "reply_classified",
                    "person_id": "p_x", "channel": "email",
                    "reply_message_id": "gid_x",
                    "category": "interest",
                    "classification_method": "rule",
                    "confidence": 1.0,
                    "matched_pattern": r"\binterested\b",
                    "ts": "2026-05-22T10:00:01.000Z",
                },
                # Classified as REJECTION.
                _reply_received_email(
                    person_id="p_y", mid="gid_y",
                    from_addr="y@y.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                {
                    "type": "reply_classified",
                    "person_id": "p_y", "channel": "email",
                    "reply_message_id": "gid_y",
                    "category": "rejection",
                    "classification_method": "rule",
                    "confidence": 1.0,
                    "matched_pattern": r"\bnot now\b",
                    "ts": "2026-05-22T10:00:01.000Z",
                },
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir, since=since, apply=True,
        )

        # No writes — long-tail categories don't trigger.
        assert result.examined == 0
        assert result.synthesized == []
        assert not (sup_dir / au.AUTO_UNSUBSCRIBE_FILENAME).exists()


class TestDedupRequirement:
    """ADR-0028 D117 — LOAD-BEARING dedup-by-(reply_message_id, channel)
    requirement carried forward from Week 2's P2-B finding."""

    def test_handler_deduplicates_by_reply_message_id_and_channel_within_batch(
        self, tmp_path,
    ):
        """Concurrent Pass G runs CAN produce duplicate classified
        events for the same (reply_message_id, channel) pair per
        ADR-0026 §Negative consequences. The handler MUST dedup
        WITHIN one batch run."""
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_dup", mid="gid_dup",
                    from_addr="dup@x.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                # Duplicate classified events — same (mid, channel).
                _reply_classified_unsubscribe(
                    person_id="p_dup", channel="email",
                    reply_mid="gid_dup",
                    ts="2026-05-22T10:00:01.000Z",
                ),
                _reply_classified_unsubscribe(
                    person_id="p_dup", channel="email",
                    reply_mid="gid_dup",
                    ts="2026-05-22T10:00:02.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir,
            since=datetime(2026, 5, 1, tzinfo=timezone.utc), apply=True,
        )

        # The handler examined 2 (one per duplicate) but synthesized
        # only ONE suppression_added — dedup-by-pair within batch.
        assert result.examined == 2
        assert result.deduped == 1
        suppression_addeds = [
            e for e in result.synthesized
            if e.get("type") == "suppression_added"
        ]
        assert len(suppression_addeds) == 1, (
            "LOAD-BEARING dedup requirement violated — a second classified "
            "event with the same (reply_message_id, channel) should not "
            "produce a second suppression_added event. Per ADR-0028 D117."
        )

    def test_handler_deduplicates_across_runs(self, tmp_path):
        """Re-running the handler against an already-handled
        classification produces NO new write. Cross-run idempotence
        per ADR-0028 D117."""
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_run", mid="gid_run",
                    from_addr="run@x.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _reply_classified_unsubscribe(
                    person_id="p_run", channel="email",
                    reply_mid="gid_run",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)

        first = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir, since=since, apply=True,
        )
        assert len(first.synthesized) == 1

        second = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir, since=since, apply=True,
        )
        # Already-suppressed pair → second run dedups + emits nothing.
        assert second.examined == 1
        assert second.deduped == 1
        assert second.synthesized == []


class TestDryRun:

    def test_dry_run_does_not_write_yaml_or_ledger(self, tmp_path):
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_dry", mid="gid_dry",
                    from_addr="dry@x.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _reply_classified_unsubscribe(
                    person_id="p_dry", channel="email",
                    reply_mid="gid_dry",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir,
            since=datetime(2026, 5, 1, tzinfo=timezone.utc), apply=False,
        )

        # YAML NOT written.
        assert not (sup_dir / au.AUTO_UNSUBSCRIBE_FILENAME).exists()
        # Ledger has NO suppression_added.
        assert not [
            e for e in led.all_events()
            if e.get("type") == "suppression_added"
        ]
        # Dry-run payload synthesized + marked.
        assert len(result.synthesized) == 1
        assert result.synthesized[0].get("_dry_run") is True


class TestSinceWindow:

    def test_pre_window_classified_events_skipped(self, tmp_path):
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_old", mid="gid_old",
                    from_addr="old@x.test",
                    ts="2026-04-01T10:00:00.000Z",
                ),
                _reply_classified_unsubscribe(
                    person_id="p_old", channel="email",
                    reply_mid="gid_old",
                    ts="2026-04-01T10:00:01.000Z",
                ),
                _reply_received_email(
                    person_id="p_new", mid="gid_new",
                    from_addr="new@x.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _reply_classified_unsubscribe(
                    person_id="p_new", channel="email",
                    reply_mid="gid_new",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()
        # Since 7 days ago — pre-window p_old's classification is older.
        since = datetime(2026, 5, 15, tzinfo=timezone.utc)

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir, since=since, apply=True,
        )

        # Only the in-window classification triggers a write.
        assert result.examined == 1
        sups = [
            e for e in result.synthesized
            if e.get("type") == "suppression_added"
        ]
        assert len(sups) == 1
        assert sups[0]["person_id"] == "p_new"


class TestPerChannelTargetResolution:

    def test_linkedin_dm_unsubscribe_writes_identity_key(self, tmp_path):
        led = _ledger_with(
            [
                {
                    "type": "li_dm_reply_received",
                    "person_id": "in/jane-doe",
                    "channel": "linkedin",
                    "reply_message_id": "li_dm_msg_1",
                    "reply_to_intent_id": "li_intent_1",
                    "linkedin_thread_id": "li_thr_1",
                    "snippet": "please remove me",
                    "ts": "2026-05-22T10:00:00.000Z",
                },
                _reply_classified_unsubscribe(
                    person_id="in/jane-doe", channel="linkedin",
                    reply_mid="li_dm_msg_1",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir,
            since=datetime(2026, 5, 1, tzinfo=timezone.utc), apply=True,
        )

        assert len(result.synthesized) == 1
        added = result.synthesized[0]
        assert added["suppressed_dimension"] == "identity_key"
        assert added["suppressed_value"] == "in/jane-doe"

        on_disk = yaml.safe_load(
            (sup_dir / au.AUTO_UNSUBSCRIBE_FILENAME).read_text()
        )
        assert "in/jane-doe" in on_disk["identity_keys"]


class TestSuppressionRuleIntegration:
    """Per ADR-0025 D100's load-bearing integration — the existing
    Pillar A SuppressEmailRule blocks the next send after the
    handler writes."""

    def test_post_handler_suppress_email_rule_blocks_next_send(self, tmp_path):
        # Seed: an unsubscribe reply + classification.
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_b", mid="gid_b",
                    from_addr="bob@example.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _reply_classified_unsubscribe(
                    person_id="p_b", channel="email",
                    reply_mid="gid_b",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()

        # Pre-handler — suppression list is empty; the rule allows.
        from policy.suppression import (
            SuppressEmailRule, load_suppression_dir,
        )
        from policy.types import RuleContext, Block

        class _StubLedger:
            def query_by_person(self, person_id, since=None):
                return []
            def last_send_for(self, person_id, channel):
                return None
            def query_by_email(self, email):
                return set()
            def all_events(self):
                return []

        def _ctx():
            return RuleContext(
                person_id="p_b", channel="email", register="cold-pitch",
                email="bob@example.test", email_domain="example.test",
                now=datetime(2026, 5, 22, tzinfo=timezone.utc),
                timezone="UTC", ledger=_StubLedger(),
            )

        sups_before = load_suppression_dir(sup_dir)
        rule = SuppressEmailRule(name="auto", suppressions=sups_before)
        assert not isinstance(rule.evaluate(_ctx()), Block)

        # Apply handler.
        au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir,
            since=datetime(2026, 5, 1, tzinfo=timezone.utc), apply=True,
        )

        # Post-handler — load the updated list; the rule MUST refuse.
        sups_after = load_suppression_dir(sup_dir)
        rule_after = SuppressEmailRule(
            name="auto", suppressions=sups_after,
        )
        result = rule_after.evaluate(_ctx())
        assert isinstance(result, Block), (
            "ADR-0025 D100 integration broken: the auto-unsubscribe "
            "YAML write does NOT make the existing SuppressEmailRule "
            "refuse on the next gate. The directory-merge contract "
            "from ADR-0004 should pick up the new YAML file."
        )


class TestEventShape:

    def test_suppression_added_event_carries_full_correlation(self, tmp_path):
        led = _ledger_with(
            [
                _reply_received_email(
                    person_id="p_corr", mid="gid_corr",
                    from_addr="corr@x.test",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _reply_classified_unsubscribe(
                    person_id="p_corr", channel="email",
                    reply_mid="gid_corr",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        sup_dir = tmp_path / "suppressions"
        sup_dir.mkdir()

        result = au.run_auto_unsubscribe(
            led=led, suppressions_dir=sup_dir,
            since=datetime(2026, 5, 1, tzinfo=timezone.utc), apply=True,
        )

        added = result.synthesized[0]
        # ADR-0025 D100 event shape — every field present.
        assert added["type"] == "suppression_added"
        assert added["person_id"] == "p_corr"
        assert added["channel"] == "email"
        assert added["suppressed_dimension"] == "email"
        assert added["suppressed_value"] == "corr@x.test"
        src = added["source_reply_classified_event"]
        assert src["reply_message_id"] == "gid_corr"
        assert src["channel"] == "email"
        assert src["ts"] == "2026-05-22T10:00:01.000Z"
        assert "auto-unsubscribe.yml" in added["yaml_file"]
        assert added["_emitted_by"] == "auto_unsubscribe_handler"
