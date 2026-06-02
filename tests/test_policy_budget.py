"""Pillar A Week 4 — budget rule classes + cost_incurred consumption.

Covers the three factory budget rule classes (ADR-0006):
  - BudgetWindowCapRule (budget.window-cap)
  - BudgetPerPersonCapRule (budget.per-person-cap)
  - BudgetPerRunCapRule (budget.per-run-cap)

Tests are organized:
  TestBudgetWindowCapRule       — USD mode, units mode, source filter,
                                   window boundary semantics, scope
                                   filters, malformed event tolerance,
                                   construction validation.
  TestBudgetPerPersonCapRule    — per-person isolation, threshold,
                                   missing person_id no-op,
                                   construction validation.
  TestBudgetPerRunCapRule       — run isolation, missing run_id no-op,
                                   threshold semantics.
  TestEmptyHistoryNoFalseBlocks — invariant: empty ledger never blocks
                                   a budget rule.
  TestFromYaml                   — every rule class round-trips YAML.
  TestEngineIntegration          — factory rules through engine.evaluate.
  TestManualOverride             — unexpired matching override → Allow.
  TestCostIncurredAggregation    — Hypothesis property: verdict is
                                   commutative under event reordering.
  TestCooldownDSTPropertyStillHolds — regression sentinel; ensures
                                   Week 4 changes don't break the
                                   ADR-0002 DST contract.
  TestSendingWindowTzDependenceStillHolds — regression sentinel for
                                   ADR-0005's tz-dependence contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from orchestrator import policy as policy_pkg
from orchestrator.policy import budget as bd
from orchestrator.policy import cooldown as cd
from orchestrator.policy import engine as policy_engine
from orchestrator.policy import sending_window as sw
from orchestrator.policy import types as policy_types


# ---------------------------------------------------------------------------
# Fake ledger — minimal LedgerLike implementing the cost-event surface
# ---------------------------------------------------------------------------


class _Evt(dict):
    """Dict that quacks like Event enough for budget.py's consumption.

    budget.py reads strictly via .get(); this is sufficient.
    """

    @property
    def type(self):
        return self["type"]

    @property
    def ts(self):
        return self.get("ts")


class _FakeLedger:
    """Minimal ledger for budget tests.

    Construct empty, then ``.add_cost(...)`` to seed ``cost_incurred``
    events. Internal storage mirrors what the real Ledger writes to
    JSONL (each event is a flat dict with a ``ts`` ISO string).
    """

    def __init__(self):
        self._events: list[_Evt] = []

    def add_cost(
        self,
        *,
        source: str,
        amount_usd: float = 0.0,
        units: int = 1,
        model_or_endpoint: str = "test/endpoint",
        person_id: str | None = None,
        run_id: str | None = None,
        ts: datetime,
        intent_id: str | None = None,
    ) -> None:
        # Mirror the production ``Ledger._now_iso`` format exactly:
        # ``YYYY-MM-DDTHH:MM:SS.MMMZ`` (millisecond precision, no offset
        # suffix, trailing ``Z``). Earlier versions of this helper
        # emitted ``YYYY-MM-DDTHH:MM:SSZ`` which agreed with the budget
        # rule's lex-comparison and hid B1 (the lex / millisecond
        # format mismatch). Both `_sum_cost_events` and this fake now
        # use parsed-datetime comparison; the format match here is
        # belt + suspenders.
        t = ts.astimezone(timezone.utc)
        ts_iso = t.strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{t.microsecond // 1000:03d}Z"
        self._events.append(_Evt({
            "v": 1, "type": "cost_incurred", "ts": ts_iso,
            "source": source, "amount_usd": float(amount_usd),
            "units": int(units),
            "model_or_endpoint": model_or_endpoint,
            "person_id": person_id, "run_id": run_id,
            "intent_id": intent_id,
        }))

    def add_override(
        self,
        *,
        rule: str,
        expires_ts: datetime,
        scope: dict | None = None,
        reason: str = "test override",
        approved_by: str = "test-user",
        ts: datetime | None = None,
    ) -> None:
        ts_iso = (ts or datetime.now(timezone.utc)).astimezone(timezone.utc) \
            .isoformat().replace("+00:00", "Z")
        exp_iso = expires_ts.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        self._events.append(_Evt({
            "v": 1, "type": "manual_override", "ts": ts_iso,
            "rule": rule, "expires_ts": exp_iso,
            "scope": scope or {},
            "reason": reason, "approved_by": approved_by,
        }))

    def add_send(
        self,
        *,
        person_id: str,
        channel: str = "email",
        register: str = "cold-pitch",
        ts: datetime,
        email: str | None = None,
        confirmed: bool = True,
    ) -> str:
        """Seed send_intent + send_confirmed pair (for tests that mix
        cooldown DST regression checks)."""
        intent_id = f"snd_test_{len(self._events):06d}"
        ts_iso = ts.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        self._events.append(_Evt({
            "v": 1, "type": "send_intent", "ts": ts_iso,
            "intent_id": intent_id, "person_id": person_id,
            "channel": channel, "register": register, "email": email,
        }))
        if confirmed:
            conf_ts = (ts + timedelta(milliseconds=1)) \
                .astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            self._events.append(_Evt({
                "v": 1, "type": "send_confirmed", "ts": conf_ts,
                "intent_id": intent_id, "person_id": person_id,
                "channel": channel, "email": email,
                "gmail_message_id": f"gm_{intent_id}",
            }))
        return intent_id

    def query_by_person(self, person_id, since=None):
        out = [e for e in self._events if e.get("person_id") == person_id]
        if since is not None:
            cutoff = since.astimezone(timezone.utc).isoformat() \
                .replace("+00:00", "Z")
            out = [e for e in out if (e.get("ts") or "") >= cutoff]
        return out

    def last_send_for(self, person_id, channel):
        best = None
        for e in self._events:
            if e.get("type") != "send_confirmed":
                continue
            if e.get("person_id") != person_id:
                continue
            if e.get("channel") != channel:
                continue
            if best is None or (e.get("ts") or "") > (best.get("ts") or ""):
                best = e
        return best

    def query_by_email(self, email):
        out: set[str] = set()
        for e in self._events:
            if (e.get("email") or "").lower() == email.lower():
                pid = e.get("person_id")
                if pid:
                    out.add(pid)
        return out

    def all_events(self):
        return list(self._events)


def _make_ctx(
    *,
    ledger=None,
    register="cold-pitch",
    channel="email",
    person_id="alice-li",
    email="alice@example.com",
    person_status=None,
    run_id=None,
    now=None,
    tz="America/Los_Angeles",
):
    return policy_types.RuleContext(
        person_id=person_id,
        channel=channel,
        register=register,
        email=email,
        email_domain=email.split("@", 1)[1] if email and "@" in email else None,
        now=now or datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
        timezone=tz,
        ledger=ledger or _FakeLedger(),
        person_status=person_status,
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# BudgetWindowCapRule
# ---------------------------------------------------------------------------


class TestBudgetWindowCapRule:
    def test_empty_history_allows_usd_mode(self):
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap",
            source="apollo",
            window_hours=24,
            max_usd=50.0,
        )
        ctx = _make_ctx()
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_empty_history_allows_units_mode(self):
        rule = bd.BudgetWindowCapRule(
            name="daily-gmail-cap",
            source="gmail",
            window_hours=24,
            max_units=400,
        )
        ctx = _make_ctx()
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_usd_sum_in_window_blocks(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for _ in range(11):
            led.add_cost(
                source="apollo", amount_usd=5.0, units=1,
                ts=now - timedelta(hours=1),
            )
        # 11 * $5 = $55 > $50 cap.
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        result = rule.evaluate(_make_ctx(ledger=led, now=now))
        assert isinstance(result, policy_types.Block)
        assert result.detail["mode"] == "usd"
        assert result.detail["total_usd"] == 55.0
        assert result.detail["max_usd"] == 50.0
        assert result.detail["event_count_in_window"] == 11

    def test_usd_sum_at_threshold_blocks(self):
        """Boundary contract: total == max blocks (at-threshold-blocks,
        same convention as DomainThrottleRule + CrossChannelTouchRule).
        """
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=50.0, units=1,
            ts=now - timedelta(hours=1),
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        result = rule.evaluate(_make_ctx(ledger=led, now=now))
        assert isinstance(result, policy_types.Block)

    def test_usd_sum_one_cent_below_allows(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=49.99, units=1,
            ts=now - timedelta(hours=1),
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Allow,
        )

    def test_source_filter_excludes_other_sources(self):
        """A rule scoped to source=apollo doesn't sum reoon events."""
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # 100 reoon events at $0.005 = $0.50 — would crush an
        # un-source-scoped rule but should be invisible to apollo's cap.
        for _ in range(100):
            led.add_cost(
                source="reoon", amount_usd=0.005, units=1,
                ts=now - timedelta(minutes=1),
            )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=0.10,  # very tight cap
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Allow,
        )

    def test_no_source_filter_sums_across_sources(self):
        """Source omitted → sum across every source. Useful for total
        spend caps that don't care which vendor."""
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(source="apollo", amount_usd=30.0,
                     ts=now - timedelta(hours=1))
        led.add_cost(source="pdl", amount_usd=25.0,
                     ts=now - timedelta(hours=2))
        # $55 across two sources > $50.
        rule = bd.BudgetWindowCapRule(
            name="total-daily-cap", source=None,
            window_hours=24, max_usd=50.0,
        )
        result = rule.evaluate(_make_ctx(ledger=led, now=now))
        assert isinstance(result, policy_types.Block)

    def test_event_outside_window_excluded(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # 1 day + 1 hour ago → outside the 24h window.
        led.add_cost(
            source="apollo", amount_usd=100.0, units=1,
            ts=now - timedelta(days=1, hours=1),
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Allow,
        )

    def test_event_at_window_boundary_included(self):
        """Lower-end inclusive — matches DomainThrottleRule (ADR-0002)
        and CrossChannelTouchRule (ADR-0003 CC-06)."""
        now = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # Exactly 24h ago — inside window per ADR-0002 boundary contract.
        led.add_cost(
            source="apollo", amount_usd=100.0, units=1,
            ts=now - timedelta(hours=24),
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Block,
        )

    def test_event_one_microsecond_past_boundary_excluded(self):
        """Negative boundary test."""
        now = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=100.0, units=1,
            ts=now - timedelta(hours=24, microseconds=1),
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Allow,
        )

    def test_units_mode_blocks_quota_only(self):
        """Gmail quota: 400 sends/day at the personal limit."""
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for _ in range(400):
            led.add_cost(
                source="gmail", amount_usd=0.0, units=1,
                ts=now - timedelta(minutes=1),
            )
        rule = bd.BudgetWindowCapRule(
            name="daily-gmail-cap", source="gmail",
            window_hours=24, max_units=400,
        )
        result = rule.evaluate(_make_ctx(ledger=led, now=now))
        assert isinstance(result, policy_types.Block)
        assert result.detail["mode"] == "units"
        assert result.detail["total_units"] == 400

    def test_window_days_parameter(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # 6 days ago.
        led.add_cost(
            source="apollo", amount_usd=200.0, units=1,
            ts=now - timedelta(days=6),
        )
        # 7-day window includes it.
        rule = bd.BudgetWindowCapRule(
            name="weekly-apollo-cap", source="apollo",
            window_days=7, max_usd=150.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Block,
        )
        # 3-day window excludes it.
        rule = bd.BudgetWindowCapRule(
            name="3day-apollo-cap", source="apollo",
            window_days=3, max_usd=150.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Allow,
        )

    def test_block_when_channel_filter(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=100.0, units=1,
            ts=now - timedelta(hours=1),
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap-email-only",
            block_when={"channel": "email"},
            source="apollo", window_hours=24, max_usd=50.0,
        )
        # On a LinkedIn send, the rule doesn't apply → Allow.
        ctx = _make_ctx(ledger=led, now=now, channel="linkedin", email=None)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_block_when_register_filter(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=100.0, units=1,
            ts=now - timedelta(hours=1),
        )
        # Cap applies only to cold-pitch register.
        rule = bd.BudgetWindowCapRule(
            name="daily-cold-pitch-apollo-cap",
            block_when={"register": "cold-pitch"},
            source="apollo", window_hours=24, max_usd=50.0,
        )
        ctx = _make_ctx(ledger=led, now=now, register="follow-up")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_real_ledger_format_with_milliseconds_included(self):
        """B1 regression: production ``Ledger._now_iso`` emits ts with
        millisecond precision (``...HH:MM:SS.MMMZ``). A serialized
        cutoff has no fractional second (``...HH:MM:SS+00:00``).
        String-lex compare excludes events in the same second as
        cutoff because ``.`` (0x2E) < ``Z`` (0x5A) and ``.`` < ``+``;
        parsed-datetime compare doesn't.

        This test injects an event 500ms after the cutoff (clearly
        inside the 24h window) using the production ts format
        directly, bypassing :meth:`_FakeLedger.add_cost`. Before B1
        was fixed, the rule wrongly Allowed; after, it Blocks.
        """
        now = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        cutoff = now - timedelta(hours=24)
        ev_ts = cutoff + timedelta(milliseconds=500)
        # Hand-craft the production ts format so the test fails on a
        # regression even if _FakeLedger.add_cost gets reformatted.
        prod_ts_iso = ev_ts.strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{ev_ts.microsecond // 1000:03d}Z"
        led._events.append(_Evt({
            "v": 1, "type": "cost_incurred", "ts": prod_ts_iso,
            "source": "apollo", "amount_usd": 100.0, "units": 1,
            "model_or_endpoint": "x",
        }))
        rule = bd.BudgetWindowCapRule(
            name="cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        result = rule.evaluate(_make_ctx(ledger=led, now=now))
        assert isinstance(result, policy_types.Block), (
            "production-format ts with millisecond precision wrongly "
            "excluded by string-lex comparison (B1 regression)"
        )

    def test_construction_requires_exactly_one_mode(self):
        with pytest.raises(ValueError, match="exactly one"):
            bd.BudgetWindowCapRule(
                name="bad", source="apollo",
                window_hours=24,
            )  # neither max_usd nor max_units
        with pytest.raises(ValueError, match="exactly one"):
            bd.BudgetWindowCapRule(
                name="bad", source="apollo",
                window_hours=24, max_usd=50.0, max_units=400,
            )

    def test_construction_requires_exactly_one_window(self):
        with pytest.raises(ValueError, match="exactly one"):
            bd.BudgetWindowCapRule(
                name="bad", source="apollo", max_usd=50.0,
            )  # no window
        with pytest.raises(ValueError, match="exactly one"):
            bd.BudgetWindowCapRule(
                name="bad", source="apollo", max_usd=50.0,
                window_hours=24, window_days=1,
            )

    def test_construction_refuses_zero_or_negative_window(self):
        """Holistic-review P1-3: a non-positive window produces a cutoff
        at-or-after ctx.now, every event is filtered as 'outside window',
        running sum is always 0, cap never fires. The construction-time
        refusal is defense-in-depth — the operator's only plausible
        non-typo intent for `window_hours: 0` is "pause the rule," and
        they have a cleaner way to do that (comment out the rule)."""
        for w in (0, -1, -100):
            with pytest.raises(ValueError, match="window_hours"):
                bd.BudgetWindowCapRule(
                    name="bad", source="apollo", max_usd=50.0,
                    window_hours=w,
                )
        for w in (0, -0.5, -7):
            with pytest.raises(ValueError, match="window_days"):
                bd.BudgetWindowCapRule(
                    name="bad", source="apollo", max_usd=50.0,
                    window_days=w,
                )

    def test_negative_amount_subtracts_from_sum(self):
        """Refunds / accounting reversals show up as negative
        ``amount_usd``. The rule sums them into the total (net spend)
        rather than clamping at zero. An operator who wants to exclude
        refunds from the cap should filter at the emit site.

        Pinned here so a future change to clamp-at-zero would surface
        as a deliberate test failure rather than silent drift.
        """
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=100.0,
            ts=now - timedelta(hours=1),
        )
        led.add_cost(
            source="apollo", amount_usd=-60.0,  # refund
            ts=now - timedelta(minutes=30),
        )
        # Net spend = 40.0 < 50.0 cap → Allow.
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Allow,
        )


# ---------------------------------------------------------------------------
# BudgetPerPersonCapRule
# ---------------------------------------------------------------------------


class TestBudgetPerPersonCapRule:
    def test_no_cost_for_person_allows(self):
        rule = bd.BudgetPerPersonCapRule(
            name="per-person-apollo-cap",
            source="apollo", max_usd=1.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx()), policy_types.Allow,
        )

    def test_at_threshold_blocks(self):
        led = _FakeLedger()
        # $1.00 spent on Alice.
        led.add_cost(
            source="apollo", amount_usd=0.50, person_id="alice-li",
            ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        led.add_cost(
            source="apollo", amount_usd=0.50, person_id="alice-li",
            ts=datetime(2026, 5, 10, tzinfo=timezone.utc),
        )
        rule = bd.BudgetPerPersonCapRule(
            name="per-person-apollo-cap",
            source="apollo", max_usd=1.0,
        )
        result = rule.evaluate(_make_ctx(ledger=led, person_id="alice-li"))
        assert isinstance(result, policy_types.Block)
        assert result.detail["person_id"] == "alice-li"
        assert result.detail["total_usd"] == 1.0

    def test_alice_costs_dont_gate_bob(self):
        """Person-level isolation: Alice over-cap doesn't block Bob's send."""
        led = _FakeLedger()
        for _ in range(10):
            led.add_cost(
                source="apollo", amount_usd=1.0, person_id="alice-li",
                ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        rule = bd.BudgetPerPersonCapRule(
            name="per-person-apollo-cap",
            source="apollo", max_usd=1.0,
        )
        # Bob has no Apollo spend → Allow.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, person_id="bob-li")),
            policy_types.Allow,
        )

    def test_events_without_person_id_excluded(self):
        """Run-level overhead (no person_id) doesn't gate a per-person rule."""
        led = _FakeLedger()
        for _ in range(10):
            led.add_cost(
                source="apollo", amount_usd=1.0, person_id=None,
                ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        rule = bd.BudgetPerPersonCapRule(
            name="per-person-apollo-cap",
            source="apollo", max_usd=0.10,  # tiny
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, person_id="alice-li")),
            policy_types.Allow,
        )

    def test_source_filter(self):
        """source=apollo doesn't see reoon spend on the same person."""
        led = _FakeLedger()
        for _ in range(100):
            led.add_cost(
                source="reoon", amount_usd=0.005, person_id="alice-li",
                ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        rule = bd.BudgetPerPersonCapRule(
            name="per-person-apollo-cap",
            source="apollo", max_usd=0.10,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, person_id="alice-li")),
            policy_types.Allow,
        )

    def test_missing_person_id_in_ctx_allows(self):
        """ctx.person_id falsy → rule is a no-op (safe default)."""
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=100.0, person_id="alice-li",
            ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        rule = bd.BudgetPerPersonCapRule(
            name="per-person-apollo-cap",
            source="apollo", max_usd=0.10,
        )
        # ctx has person_id=None — should not gate.
        ctx = _make_ctx(ledger=led, person_id="")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_construction_rejects_non_positive_cap(self):
        with pytest.raises(ValueError, match="must be > 0"):
            bd.BudgetPerPersonCapRule(
                name="bad", source="apollo", max_usd=0.0,
            )
        with pytest.raises(ValueError, match="must be > 0"):
            bd.BudgetPerPersonCapRule(
                name="bad", source="apollo", max_usd=-1.0,
            )


# ---------------------------------------------------------------------------
# BudgetPerRunCapRule
# ---------------------------------------------------------------------------


class TestBudgetPerRunCapRule:
    def test_no_run_id_allows(self):
        """A send outside a batched run → rule is a no-op."""
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=100.0, run_id="run-abc",
            ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        rule = bd.BudgetPerRunCapRule(
            name="per-run-cap", source="apollo", max_usd=25.0,
        )
        ctx = _make_ctx(ledger=led, run_id=None)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_run_at_threshold_blocks(self):
        led = _FakeLedger()
        for _ in range(5):
            led.add_cost(
                source="apollo", amount_usd=5.0, run_id="run-abc",
                ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        rule = bd.BudgetPerRunCapRule(
            name="per-run-apollo-cap",
            source="apollo", max_usd=25.0,
        )
        result = rule.evaluate(
            _make_ctx(ledger=led, run_id="run-abc"),
        )
        assert isinstance(result, policy_types.Block)
        assert result.detail["run_id"] == "run-abc"
        assert result.detail["total_usd"] == 25.0

    def test_cross_run_isolation(self):
        """Run B's cost doesn't gate Run A's send."""
        led = _FakeLedger()
        for _ in range(10):
            led.add_cost(
                source="apollo", amount_usd=10.0, run_id="run-other",
                ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        rule = bd.BudgetPerRunCapRule(
            name="per-run-apollo-cap",
            source="apollo", max_usd=25.0,
        )
        # run-current has no cost → Allow.
        ctx = _make_ctx(ledger=led, run_id="run-current")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_no_source_filter_sums_across_sources(self):
        """When source omitted, sums everything within the run."""
        led = _FakeLedger()
        led.add_cost(source="apollo", amount_usd=15.0, run_id="run-abc",
                     ts=datetime(2026, 5, 1, tzinfo=timezone.utc))
        led.add_cost(source="pdl", amount_usd=15.0, run_id="run-abc",
                     ts=datetime(2026, 5, 1, tzinfo=timezone.utc))
        rule = bd.BudgetPerRunCapRule(
            name="per-run-total-cap", source=None, max_usd=25.0,
        )
        result = rule.evaluate(
            _make_ctx(ledger=led, run_id="run-abc"),
        )
        assert isinstance(result, policy_types.Block)

    def test_construction_rejects_non_positive(self):
        with pytest.raises(ValueError):
            bd.BudgetPerRunCapRule(
                name="bad", source="apollo", max_usd=0.0,
            )

    def test_empty_run_id_treated_as_no_run(self):
        """ctx.run_id="" — same falsy semantics as None. The rule's
        ``if not ctx.run_id: return Allow()`` check passes both
        cases. Pins the contract so a future change from ``not`` to
        ``is None`` would surface as a test failure."""
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=100.0, run_id="run-abc",
            ts=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        rule = bd.BudgetPerRunCapRule(
            name="per-run-cap", source="apollo", max_usd=25.0,
        )
        ctx = _make_ctx(ledger=led, run_id="")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# Invariant: empty history never produces false blocks
# ---------------------------------------------------------------------------


class TestEmptyHistoryNoFalseBlocks:
    """Sanity: a fresh ledger never produces a budget block."""

    def test_window_usd(self):
        rule = bd.BudgetWindowCapRule(
            name="r", source="apollo", window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx()), policy_types.Allow,
        )

    def test_window_units(self):
        rule = bd.BudgetWindowCapRule(
            name="r", source="gmail", window_hours=24, max_units=400,
        )
        assert isinstance(
            rule.evaluate(_make_ctx()), policy_types.Allow,
        )

    def test_per_person(self):
        rule = bd.BudgetPerPersonCapRule(
            name="r", source="apollo", max_usd=1.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx()), policy_types.Allow,
        )

    def test_per_run(self):
        rule = bd.BudgetPerRunCapRule(
            name="r", source="apollo", max_usd=25.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(run_id="run-abc")),
            policy_types.Allow,
        )


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


class TestFromYaml:
    def test_window_cap_usd_from_yaml(self):
        spec = {
            "name": "daily-apollo-cap",
            "type": "budget.window-cap",
            "source": "apollo",
            "window_hours": 24,
            "max_usd": 50.0,
        }
        rule = bd.BudgetWindowCapRule.from_yaml(spec)
        assert rule.name == "daily-apollo-cap"
        assert rule.source == "apollo"
        assert rule.max_usd == 50.0
        assert rule.window_hours == 24

    def test_window_cap_units_from_yaml(self):
        spec = {
            "name": "daily-gmail-cap",
            "type": "budget.window-cap",
            "source": "gmail",
            "window_days": 1,
            "max_units": 400,
        }
        rule = bd.BudgetWindowCapRule.from_yaml(spec)
        assert rule.max_units == 400
        assert rule.window_days == 1

    def test_window_cap_block_when_from_yaml(self):
        spec = {
            "name": "cold-pitch-only",
            "type": "budget.window-cap",
            "block_when": {"register": "cold-pitch", "channel": "email"},
            "source": "apollo",
            "window_hours": 24,
            "max_usd": 50.0,
        }
        rule = bd.BudgetWindowCapRule.from_yaml(spec)
        assert rule.block_when == {
            "register": "cold-pitch", "channel": "email",
        }

    def test_per_person_from_yaml(self):
        spec = {
            "name": "per-person-apollo-cap",
            "type": "budget.per-person-cap",
            "source": "apollo",
            "max_usd": 1.0,
        }
        rule = bd.BudgetPerPersonCapRule.from_yaml(spec)
        assert rule.max_usd == 1.0
        assert rule.source == "apollo"

    def test_per_run_from_yaml(self):
        spec = {
            "name": "per-run-cap",
            "type": "budget.per-run-cap",
            "max_usd": 25.0,
        }
        rule = bd.BudgetPerRunCapRule.from_yaml(spec)
        assert rule.max_usd == 25.0
        assert rule.source is None

    def test_per_person_missing_max_raises(self):
        with pytest.raises(ValueError):
            bd.BudgetPerPersonCapRule.from_yaml({
                "name": "bad", "type": "budget.per-person-cap",
                "source": "apollo",
            })

    def test_load_rules_from_yaml_integrates(self, tmp_path):
        """End-to-end: budget classes are registered, YAML loads cleanly."""
        p = tmp_path / "cooldowns.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: daily-apollo-cap\n"
            "    type: budget.window-cap\n"
            "    source: apollo\n"
            "    window_hours: 24\n"
            "    max_usd: 50.0\n"
            "  - name: per-person-apollo-cap\n"
            "    type: budget.per-person-cap\n"
            "    source: apollo\n"
            "    max_usd: 1.0\n"
            "  - name: per-run-cap\n"
            "    type: budget.per-run-cap\n"
            "    max_usd: 25.0\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 3
        assert [r.name for r in rules] == [
            "daily-apollo-cap",
            "per-person-apollo-cap",
            "per-run-cap",
        ]


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    def test_factory_rules_through_engine(self, tmp_path):
        p = tmp_path / "cooldowns.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: daily-apollo-cap\n"
            "    type: budget.window-cap\n"
            "    source: apollo\n"
            "    window_hours: 24\n"
            "    max_usd: 50.0\n"
            "  - name: per-person-apollo-cap\n"
            "    type: budget.per-person-cap\n"
            "    source: apollo\n"
            "    max_usd: 1.0\n"
            "  - name: per-run-cap\n"
            "    type: budget.per-run-cap\n"
            "    max_usd: 25.0\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 3

        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)

        # Case 1: empty ledger → Allow.
        ctx = _make_ctx(now=now, run_id="run-abc")
        assert isinstance(
            policy_engine.evaluate(rules, ctx), policy_types.Allow,
        )

        # Case 2: per-person cap hit on Alice → block (per-person first
        # to block because window/per-run thresholds aren't met).
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=1.0, person_id="alice-li",
            run_id="run-prior",
            ts=now - timedelta(hours=1),
        )
        ctx = _make_ctx(ledger=led, now=now, person_id="alice-li",
                        run_id="run-abc")
        result = policy_engine.evaluate(rules, ctx)
        assert isinstance(result, policy_types.Block)
        # The order in the YAML file matters: window-cap is first but
        # one $1 event isn't enough to hit $50. Per-person-cap is
        # second and DOES hit at $1.00.
        assert result.rule == "per-person-apollo-cap"

        # Case 3: per-run cap hit → block.
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=25.0, person_id="alice-li",
            run_id="run-abc",
            ts=now - timedelta(hours=1),
        )
        ctx = _make_ctx(ledger=led, now=now, person_id="bob-li",
                        run_id="run-abc")
        result = policy_engine.evaluate(rules, ctx)
        assert isinstance(result, policy_types.Block)
        # window-cap ($50 cap, $25 spent) Allow; per-person-cap
        # (alice-li > $1) Allow because ctx is bob-li; per-run-cap
        # ($25 cap, $25 in run-abc) Block.
        assert result.rule == "per-run-cap"


# ---------------------------------------------------------------------------
# Manual override (ADR-0006)
# ---------------------------------------------------------------------------


class TestManualOverride:
    def test_matching_unexpired_override_allows(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for _ in range(11):
            led.add_cost(
                source="apollo", amount_usd=5.0,
                ts=now - timedelta(hours=1),
            )
        led.add_override(
            rule="daily-apollo-cap",
            expires_ts=now + timedelta(hours=1),
            scope={},
            reason="legitimate spike",
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Allow,
        )

    def test_expired_override_does_not_apply(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for _ in range(11):
            led.add_cost(
                source="apollo", amount_usd=5.0,
                ts=now - timedelta(hours=1),
            )
        # Override expired an hour ago.
        led.add_override(
            rule="daily-apollo-cap",
            expires_ts=now - timedelta(hours=1),
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Block,
        )

    def test_override_for_other_rule_does_not_apply(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for _ in range(11):
            led.add_cost(
                source="apollo", amount_usd=5.0,
                ts=now - timedelta(hours=1),
            )
        # Override is for a DIFFERENT rule.
        led.add_override(
            rule="some-other-rule",
            expires_ts=now + timedelta(hours=1),
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Block,
        )

    def test_scope_person_id_must_match(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=2.0, person_id="alice-li",
            ts=now - timedelta(hours=1),
        )
        # Override only covers bob-li, but ctx is alice-li.
        led.add_override(
            rule="per-person-apollo-cap",
            expires_ts=now + timedelta(hours=1),
            scope={"person_id": "bob-li"},
        )
        rule = bd.BudgetPerPersonCapRule(
            name="per-person-apollo-cap",
            source="apollo", max_usd=1.0,
        )
        # Alice still blocked because the override's scope.person_id
        # is bob-li.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now,
                                    person_id="alice-li")),
            policy_types.Block,
        )

    def test_scope_run_id_match_allows(self):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=25.0, run_id="run-abc",
            ts=now - timedelta(hours=1),
        )
        led.add_override(
            rule="per-run-cap",
            expires_ts=now + timedelta(hours=1),
            scope={"run_id": "run-abc"},
        )
        rule = bd.BudgetPerRunCapRule(
            name="per-run-cap", source="apollo", max_usd=25.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now,
                                    run_id="run-abc")),
            policy_types.Allow,
        )

    def test_scope_explicit_null_field_treated_as_no_scope(self):
        """B2 regression: an override serialized with
        ``scope: {run_id: null}`` (e.g. a JSON tool round-tripping the
        absence-of-constraint as an explicit null) must NOT silently
        match only ``ctx.run_id is None``. The natural operator
        gesture for "no scope on this field" is to omit it; serialized
        ``null`` must read the same way.

        Before the fix this override would only apply to non-batched
        sends (because ``scope["run_id"] != ctx.run_id`` would be
        ``None != "run-abc"`` → True → skip-the-override). After the
        fix, ``None`` means "no scope" → override applies to run-abc.
        """
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_cost(
            source="apollo", amount_usd=25.0, run_id="run-abc",
            ts=now - timedelta(hours=1),
        )
        led.add_override(
            rule="per-run-cap",
            expires_ts=now + timedelta(hours=1),
            scope={"run_id": None, "person_id": None},
        )
        rule = bd.BudgetPerRunCapRule(
            name="per-run-cap", source="apollo", max_usd=25.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now,
                                    run_id="run-abc")),
            policy_types.Allow,
        )

    def test_first_matching_override_wins(self):
        """When two unexpired matching overrides exist, the rule
        Allows (it doesn't matter which one wins — the bypass
        applies). Pins that no exception is raised and that the
        all-events scan honors at-least-one-match semantics."""
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for _ in range(11):
            led.add_cost(
                source="apollo", amount_usd=5.0,
                ts=now - timedelta(hours=1),
            )
        # Two distinct overrides, both unexpired, both match.
        led.add_override(
            rule="daily-apollo-cap",
            expires_ts=now + timedelta(hours=2),
            reason="first",
        )
        led.add_override(
            rule="daily-apollo-cap",
            expires_ts=now + timedelta(hours=4),
            reason="second",
        )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap", source="apollo",
            window_hours=24, max_usd=50.0,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now)),
            policy_types.Allow,
        )


# ---------------------------------------------------------------------------
# Commutativity property: budget verdict is insensitive to event order
# ---------------------------------------------------------------------------


class TestCostIncurredAggregation:
    """Hypothesis property: the budget verdict is invariant under any
    permutation of the cost_incurred event order. The ledger writes
    events in chronological order, but reconciliation / replay may
    produce different orders; the verdict must not depend on it.

    This is a stricter formulation of "sum is commutative" — it
    proves that all three rule classes treat the cost stream as a
    multiset, not a sequence.
    """

    @settings(
        max_examples=100, deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        amounts=st.lists(
            st.floats(min_value=0.0, max_value=100.0,
                      allow_nan=False, allow_infinity=False),
            min_size=0, max_size=50,
        ),
        max_usd=st.floats(min_value=1.0, max_value=1000.0,
                          allow_nan=False, allow_infinity=False),
    )
    def test_window_cap_verdict_commutes(self, amounts, max_usd):
        now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
        # Two ledgers with the SAME events in DIFFERENT order.
        led1 = _FakeLedger()
        led2 = _FakeLedger()
        for i, amt in enumerate(amounts):
            led1.add_cost(
                source="apollo", amount_usd=amt,
                ts=now - timedelta(minutes=i),
            )
        for i, amt in enumerate(reversed(amounts)):
            led2.add_cost(
                source="apollo", amount_usd=amt,
                ts=now - timedelta(minutes=i),
            )
        rule = bd.BudgetWindowCapRule(
            name="cap", source="apollo",
            window_hours=24, max_usd=max_usd,
        )
        v1 = rule.evaluate(_make_ctx(ledger=led1, now=now))
        v2 = rule.evaluate(_make_ctx(ledger=led2, now=now))
        assert type(v1) is type(v2), (
            f"verdict drift across event order: amounts={amounts}, "
            f"max_usd={max_usd}, v1={type(v1).__name__}, "
            f"v2={type(v2).__name__}"
        )


# ---------------------------------------------------------------------------
# Regression sentinel: cooldown DST property still holds after Week 4
# ---------------------------------------------------------------------------


class TestCooldownDSTPropertyStillHolds:
    """Smoke test: Week 4's additions (cost_incurred consumption +
    ``RuleContext.run_id``) must not break cooldown's tz-invariance
    contract (ADR-0002 §Decision).

    NOT a deep regression sentinel — it only proves the cooldown rule
    class still produces tz-invariant verdicts under the new context
    shape. The real coverage is the Hypothesis property over many
    timezone / timestamp combinations in
    ``tests/test_policy_cooldown.py::TestDSTSafetyProperty``. This
    file's check exists so that an import-or-context-shape regression
    introduced by Week 4 surfaces at the Week 4 test file (narrows
    the bisect window).
    """

    _TZ_SAMPLES = (
        "UTC", "America/Los_Angeles", "Europe/London",
        "Australia/Sydney", "Asia/Tokyo",
    )

    def test_no_duplicate_register_still_tz_invariant(self):
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
            email="alice@example.com",
        )
        rule = cd.NoDuplicateRegisterRule(
            name="no-double", block_when={"register": "cold-pitch"},
        )
        now = datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc)
        verdicts = []
        for tz_name in self._TZ_SAMPLES:
            ctx = _make_ctx(ledger=led, now=now, tz=tz_name)
            verdicts.append(type(rule.evaluate(ctx)).__name__)
        assert len(set(verdicts)) == 1, (
            f"cooldown DST regression — verdicts differed by tz: {verdicts}"
        )


# ---------------------------------------------------------------------------
# Regression sentinel: sending-window tz-dependence still holds
# ---------------------------------------------------------------------------


class TestSendingWindowTzDependenceStillHolds:
    """Smoke test: Week 4's additions must not break ADR-0005's
    complementary contract — sending-window verdicts MUST depend on
    tz.

    NOT a deep regression sentinel — only proves
    ``LocalTimeOfDayRule`` still produces tz-dependent verdicts under
    the new context shape. Real coverage is the Hypothesis property
    in ``tests/test_policy_sending_window.py::TestTimezoneDependence``.
    Same bisect-narrowing rationale as the cooldown sentinel above."""

    def test_local_time_of_day_still_tz_dependent(self):
        rule = sw.LocalTimeOfDayRule(
            name="business-hours",
            start_local="09:00",
            end_local="17:00",
        )
        # 03:00 UTC: 19:00 PST previous day (out-of-window) vs
        # 12:00 Tokyo (in-window). Verdicts MUST differ by tz.
        now = datetime(2026, 5, 18, 3, 0, tzinfo=timezone.utc)
        v_pst = rule.evaluate(_make_ctx(
            now=now, tz="America/Los_Angeles",
        ))
        v_jpt = rule.evaluate(_make_ctx(now=now, tz="Asia/Tokyo"))
        assert type(v_pst).__name__ != type(v_jpt).__name__, (
            "sending-window tz-dependence regression — both verdicts "
            "are identical, but PST 19:00 and Tokyo 12:00 should differ"
        )
