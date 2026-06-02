"""Pillar A Week 5 — tier rule class + cross-cutting block_when filter.

Covers ADR-0007:
  - TierRequiresTierInRule (tier.requires-tier-in)
  - Cross-cutting block_when: {tier|tier_in} on the shared filter helper
  - Round-trip via from_yaml + engine integration

Tests are organized:
  TestTierRequiresTierInRule          — allow/block branches, None-tier,
                                         degenerate (empty allowed_tiers),
                                         case-sensitivity, block_when
                                         filters (register / channel).
  TestFromYaml                         — required-field validation,
                                         list-type enforcement, str-only
                                         entries, default reason, round-trip.
  TestEngineIntegration                — factory rule through engine.evaluate
                                         (short-circuit) and evaluate_all.
  TestBlockWhenTierFilter              — every existing rule class scoped
                                         by tier: / tier_in: (cooldown +
                                         budget + sending-window) — proves
                                         the cross-cutting filter works
                                         without per-class code.
  TestEmptyContextNoFalseBlocks        — invariant: ctx.tier=None does NOT
                                         block when no tier rule is configured.
  TestCooldownDSTPropertyStillHolds    — regression sentinel; ADR-0007
                                         did not break ADR-0002.
  TestSendingWindowTzDependenceStillHolds — regression sentinel for ADR-0005.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from orchestrator import policy as policy_pkg
from orchestrator.policy import budget as bd
from orchestrator.policy import cooldown as cd
from orchestrator.policy import engine as policy_engine
from orchestrator.policy import sending_window as sw
from orchestrator.policy import tier as ti
from orchestrator.policy import types as policy_types
from orchestrator.policy._helpers import _block_when_matches


# ---------------------------------------------------------------------------
# Fake ledger — minimal LedgerLike
# ---------------------------------------------------------------------------


class _Evt(dict):
    """Quack-like-Event dict (matches the budget test pattern)."""

    @property
    def type(self):
        return self["type"]

    @property
    def ts(self):
        return self.get("ts")


class _FakeLedger:
    """Minimal LedgerLike for tier tests.

    Most tier rule tests don't need any events at all (tier is pure
    context). A handful of TestBlockWhenTierFilter tests seed
    cost_incurred / send_confirmed events; this fake supports both via
    add_cost / add_send.
    """

    def __init__(self):
        self._events: list[_Evt] = []

    def add_cost(
        self,
        *,
        source: str,
        amount_usd: float = 0.0,
        units: int = 1,
        person_id: str | None = None,
        run_id: str | None = None,
        ts: datetime,
    ) -> None:
        t = ts.astimezone(timezone.utc)
        ts_iso = t.strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{t.microsecond // 1000:03d}Z"
        self._events.append(_Evt({
            "v": 1, "type": "cost_incurred", "ts": ts_iso,
            "source": source, "amount_usd": float(amount_usd),
            "units": int(units),
            "model_or_endpoint": "tier-test",
            "person_id": person_id, "run_id": run_id,
        }))

    def add_send(
        self,
        *,
        person_id: str,
        channel: str = "email",
        register: str = "cold-pitch",
        ts: datetime,
        email: str | None = None,
    ) -> str:
        intent_id = f"snd_test_{len(self._events):06d}"
        ts_iso = ts.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        self._events.append(_Evt({
            "v": 1, "type": "send_intent", "ts": ts_iso,
            "intent_id": intent_id, "person_id": person_id,
            "channel": channel, "register": register, "email": email,
        }))
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
        return set()

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
    tier="S",
    now=None,
    tz="America/Los_Angeles",
):
    return policy_types.RuleContext(
        person_id=person_id,
        channel=channel,
        register=register,
        email=email,
        email_domain=email.split("@", 1)[1] if email and "@" in email else None,
        now=now or datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc),
        timezone=tz,
        ledger=ledger or _FakeLedger(),
        person_status=person_status,
        run_id=run_id,
        tier=tier,
    )


# ---------------------------------------------------------------------------
# TierRequiresTierInRule — core behavior
# ---------------------------------------------------------------------------


class TestTierRequiresTierInRule:

    def test_allowed_tier_allows(self):
        rule = ti.TierRequiresTierInRule(
            name="cold-pitch-tier-gate",
            allowed_tiers=["S", "A"],
        )
        ctx = _make_ctx(tier="S")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_allowed_tier_A_also_allows(self):
        rule = ti.TierRequiresTierInRule(
            name="cold-pitch-tier-gate",
            allowed_tiers=["S", "A"],
        )
        ctx = _make_ctx(tier="A")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_disallowed_tier_blocks(self):
        rule = ti.TierRequiresTierInRule(
            name="cold-pitch-tier-gate",
            allowed_tiers=["S", "A"],
        )
        ctx = _make_ctx(tier="B")
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "cold-pitch-tier-gate"
        assert result.detail["tier_value"] == "B"
        assert result.detail["allowed_tiers"] == ["S", "A"]
        # The wrong-tier block does NOT set tier_unknown.
        assert "tier_unknown" not in result.detail

    def test_none_tier_blocks(self):
        """Restrictive interpretation — un-tiered prospect is refused."""
        rule = ti.TierRequiresTierInRule(
            name="cold-pitch-tier-gate",
            allowed_tiers=["S", "A"],
        )
        ctx = _make_ctx(tier=None)
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail["tier_unknown"] is True
        # The unknown-tier block does NOT set tier_value (no value to report).
        assert "tier_value" not in result.detail

    def test_empty_allowed_tiers_degenerate_blocks(self):
        """Empty allowed-set degenerate window — refuse rather than allow."""
        rule = ti.TierRequiresTierInRule(
            name="degenerate-tier-gate",
            allowed_tiers=[],
        )
        # Even a "good" tier blocks because the rule allows nothing.
        ctx = _make_ctx(tier="S")
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail["degenerate"] is True

    def test_empty_allowed_tiers_also_blocks_on_none(self):
        """Degenerate + None — the degenerate-Block takes precedence."""
        rule = ti.TierRequiresTierInRule(
            name="degenerate-tier-gate",
            allowed_tiers=[],
        )
        ctx = _make_ctx(tier=None)
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        # We don't strictly care whether degenerate OR tier_unknown is
        # set first — both are Block paths. The rule.py implementation
        # checks degenerate first because it's a higher-priority concern
        # (typo'd YAML > missing data).
        assert result.detail.get("degenerate") is True

    def test_case_sensitive_match(self):
        """ctx.tier='s' does NOT match allowed_tiers=['S']."""
        rule = ti.TierRequiresTierInRule(
            name="case-sensitive",
            allowed_tiers=["S", "A"],
        )
        ctx = _make_ctx(tier="s")
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail["tier_value"] == "s"

    def test_p1_p2_p3_scheme_works(self):
        """Rule is scheme-agnostic — works for P1/P2/P3 as well as S/A/B."""
        rule = ti.TierRequiresTierInRule(
            name="priority-gate",
            allowed_tiers=["P1", "P2"],
        )
        assert isinstance(
            rule.evaluate(_make_ctx(tier="P1")), policy_types.Allow,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(tier="P2")), policy_types.Allow,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(tier="P3")), policy_types.Block,
        )

    def test_block_when_register_filter_applies(self):
        """When register doesn't match block_when, rule is no-op (Allow)."""
        rule = ti.TierRequiresTierInRule(
            name="cold-pitch-only-tier-gate",
            allowed_tiers=["S", "A"],
            block_when={"register": "cold-pitch"},
        )
        # A tier-B follow-up doesn't trigger the rule.
        ctx = _make_ctx(tier="B", register="follow-up")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)
        # A tier-B cold-pitch still blocks.
        ctx = _make_ctx(tier="B", register="cold-pitch")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_block_when_channel_filter_applies(self):
        """When channel doesn't match block_when, rule is no-op (Allow)."""
        rule = ti.TierRequiresTierInRule(
            name="email-only-tier-gate",
            allowed_tiers=["S", "A"],
            block_when={"channel": "email"},
        )
        # A tier-B LinkedIn send doesn't trigger the rule.
        ctx = _make_ctx(tier="B", channel="linkedin", email=None)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)
        # A tier-B email still blocks.
        ctx = _make_ctx(tier="B", channel="email")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_block_when_both_register_and_channel(self):
        """Filters AND together (register AND channel must match)."""
        rule = ti.TierRequiresTierInRule(
            name="cold-email-tier-gate",
            allowed_tiers=["S", "A"],
            block_when={"register": "cold-pitch", "channel": "email"},
        )
        # Tier-B follow-up via email — register doesn't match → Allow.
        ctx = _make_ctx(tier="B", register="follow-up", channel="email")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)
        # Tier-B cold-pitch via LinkedIn — channel doesn't match → Allow.
        ctx = _make_ctx(tier="B", register="cold-pitch", channel="linkedin", email=None)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)
        # Tier-B cold-pitch via email — both match → Block.
        ctx = _make_ctx(tier="B", register="cold-pitch", channel="email")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_single_tier_allowed_list(self):
        """A list with one entry behaves like exact-match."""
        rule = ti.TierRequiresTierInRule(
            name="s-only",
            allowed_tiers=["S"],
        )
        assert isinstance(rule.evaluate(_make_ctx(tier="S")), policy_types.Allow)
        assert isinstance(rule.evaluate(_make_ctx(tier="A")), policy_types.Block)
        assert isinstance(rule.evaluate(_make_ctx(tier="B")), policy_types.Block)


# ---------------------------------------------------------------------------
# from_yaml
# ---------------------------------------------------------------------------


class TestFromYaml:

    def test_round_trip_minimal(self):
        rule = ti.TierRequiresTierInRule.from_yaml({
            "name": "tier-gate",
            "type": "tier.requires-tier-in",
            "allowed_tiers": ["S", "A"],
        })
        assert rule.name == "tier-gate"
        assert rule.allowed_tiers == ["S", "A"]
        assert rule.block_when == {}
        assert rule.reason == "Prospect tier not in the allowed set for this send"

    def test_round_trip_with_block_when_and_reason(self):
        rule = ti.TierRequiresTierInRule.from_yaml({
            "name": "cold-pitch-tier-gate",
            "type": "tier.requires-tier-in",
            "block_when": {"register": "cold-pitch"},
            "allowed_tiers": ["S", "A"],
            "reason": "Cold-pitch allowed for tier S/A only",
        })
        assert rule.block_when == {"register": "cold-pitch"}
        assert rule.reason == "Cold-pitch allowed for tier S/A only"

    def test_missing_allowed_tiers_raises(self):
        with pytest.raises(ValueError, match="allowed_tiers"):
            ti.TierRequiresTierInRule.from_yaml({
                "name": "bad",
                "type": "tier.requires-tier-in",
            })

    def test_non_list_allowed_tiers_raises(self):
        with pytest.raises(ValueError, match="must be a list"):
            ti.TierRequiresTierInRule.from_yaml({
                "name": "bad",
                "type": "tier.requires-tier-in",
                "allowed_tiers": "S",   # scalar, should be a list
            })

    def test_non_string_entries_raises(self):
        """Integer entries (P1/P2/P3 written without quotes in some YAML
        flavors) are coerced to int — the rule does str comparison, so
        an int entry would never match a string ctx.tier."""
        with pytest.raises(ValueError, match="not str"):
            ti.TierRequiresTierInRule.from_yaml({
                "name": "bad",
                "type": "tier.requires-tier-in",
                "allowed_tiers": [1, 2, 3],
            })

    def test_empty_list_is_accepted_at_construction(self):
        """An empty allowed_tiers list is valid YAML — the rule's
        degenerate path handles it at evaluation time. The from_yaml
        doesn't refuse because the operator MIGHT intend a degenerate
        rule (rare, but legitimate for "this rule is paused — block
        everything it would scope to until I re-tune")."""
        rule = ti.TierRequiresTierInRule.from_yaml({
            "name": "paused",
            "type": "tier.requires-tier-in",
            "allowed_tiers": [],
        })
        assert rule.allowed_tiers == []


# ---------------------------------------------------------------------------
# Engine integration — factory rule through evaluate + evaluate_all
# ---------------------------------------------------------------------------


class TestEngineIntegration:

    def test_factory_rule_blocks_tier_b_cold_pitch_via_evaluate(self):
        rule = ti.TierRequiresTierInRule(
            name="cold-pitch-tier-gate",
            allowed_tiers=["S", "A"],
            block_when={"register": "cold-pitch"},
        )
        ctx = _make_ctx(tier="B", register="cold-pitch")
        result = policy_engine.evaluate([rule], ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "cold-pitch-tier-gate"

    def test_factory_rule_allows_tier_s_cold_pitch_via_evaluate(self):
        rule = ti.TierRequiresTierInRule(
            name="cold-pitch-tier-gate",
            allowed_tiers=["S", "A"],
            block_when={"register": "cold-pitch"},
        )
        ctx = _make_ctx(tier="S", register="cold-pitch")
        assert isinstance(
            policy_engine.evaluate([rule], ctx), policy_types.Allow,
        )

    def test_registered_in_RULE_REGISTRY(self):
        assert "tier.requires-tier-in" in policy_engine.RULE_REGISTRY
        assert policy_engine.RULE_REGISTRY["tier.requires-tier-in"] is \
            ti.TierRequiresTierInRule

    def test_load_rules_from_yaml_constructs_tier_rule(self, tmp_path):
        p = tmp_path / "cooldowns.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
            "    allowed_tiers: [S, A]\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 1
        assert isinstance(rules[0], ti.TierRequiresTierInRule)
        assert rules[0].allowed_tiers == ["S", "A"]


# ---------------------------------------------------------------------------
# Cross-cutting block_when: {tier|tier_in} filter
# ---------------------------------------------------------------------------


class TestBlockWhenTierFilter:
    """Proves the shared filter helper scopes EVERY existing rule class
    by tier without per-class code changes.

    Each test picks a representative rule class (cooldown, budget,
    sending-window) and adds `tier:` or `tier_in:` to its block_when.
    """

    def test_block_when_tier_exact_match_on_cooldown_rule(self):
        """Cooldown rule scoped to tier=S only fires on tier-S sends."""
        rule = cd.NoDuplicateRegisterRule(
            name="no-dup-cold-pitch-tier-s",
            block_when={"register": "cold-pitch", "tier": "S"},
        )
        led = _FakeLedger()
        # Seed a prior send for the person.
        led.add_send(
            person_id="alice-li", channel="email",
            register="cold-pitch",
            ts=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
        )
        # Tier-S — rule fires, sees the prior send → Block.
        ctx = _make_ctx(ledger=led, tier="S")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)
        # Tier-A — rule does NOT fire (tier doesn't match block_when).
        ctx = _make_ctx(ledger=led, tier="A")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)
        # Tier=None — rule does NOT fire either (None ≠ "S").
        ctx = _make_ctx(ledger=led, tier=None)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_block_when_tier_in_set_match_on_budget_rule(self):
        """Budget rule scoped to tier_in=[S, A] caps only those tiers."""
        now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # $60 of Apollo spend in the last hour — would exceed a $50 cap.
        for _ in range(12):
            led.add_cost(
                source="apollo", amount_usd=5.0, units=1,
                ts=now - timedelta(minutes=10),
            )
        rule = bd.BudgetWindowCapRule(
            name="tier-sa-apollo-cap",
            block_when={"tier_in": ["S", "A"]},
            source="apollo", window_hours=24, max_usd=50.0,
        )
        # Tier-S — rule fires → Block.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now, tier="S")),
            policy_types.Block,
        )
        # Tier-A — rule fires → Block.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now, tier="A")),
            policy_types.Block,
        )
        # Tier-B — rule does NOT fire (B not in [S, A]).
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now, tier="B")),
            policy_types.Allow,
        )
        # Tier=None — rule does NOT fire (None not in [S, A]).
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now, tier=None)),
            policy_types.Allow,
        )

    def test_block_when_tier_on_sending_window_rule(self):
        """Sending-window rule scoped to tier=S only checks the window
        for tier-S recipients. Useful for "tier-S gets the strict
        business-hours window, others get the wider any-hour window."
        """
        rule = sw.LocalTimeOfDayRule(
            name="tier-s-business-hours",
            start_local="09:00",
            end_local="17:00",
            block_when={"tier": "S"},
        )
        # 03:00 LA — outside business hours.
        ctx_off = _make_ctx(
            tier="S",
            now=datetime(2026, 5, 19, 10, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        # 03:00 UTC == 20:00 LA the previous day (PDT during May). Both
        # are outside 09:00-17:00, but the rule fires only for tier S.
        assert isinstance(rule.evaluate(ctx_off), policy_types.Block)
        # Same time, tier-A — rule does NOT fire.
        ctx_a = _make_ctx(
            tier="A",
            now=datetime(2026, 5, 19, 10, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(rule.evaluate(ctx_a), policy_types.Allow)

    def test_tier_filter_combined_with_register_filter(self):
        """tier: + register: AND together — both must match."""
        rule = cd.NoDuplicateRegisterRule(
            name="cold-pitch-tier-s-only",
            block_when={"register": "cold-pitch", "tier": "S"},
        )
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
        )
        # Tier-S cold-pitch — both match → Block.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, tier="S", register="cold-pitch")),
            policy_types.Block,
        )
        # Tier-S follow-up — register doesn't match → Allow.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, tier="S", register="follow-up")),
            policy_types.Allow,
        )
        # Tier-A cold-pitch — tier doesn't match → Allow.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, tier="A", register="cold-pitch")),
            policy_types.Allow,
        )

    def test_empty_tier_in_list_does_not_match(self):
        """tier_in: [] is a degenerate filter — never matches any tier
        (the rule is effectively paused)."""
        rule = bd.BudgetWindowCapRule(
            name="paused-tier-cap",
            block_when={"tier_in": []},
            source="apollo", window_hours=24, max_usd=50.0,
        )
        now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for _ in range(12):
            led.add_cost(
                source="apollo", amount_usd=5.0, units=1,
                ts=now - timedelta(minutes=10),
            )
        # Even tier-S — would otherwise block — doesn't fire.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, now=now, tier="S")),
            policy_types.Allow,
        )

    def test_tier_in_scalar_raises_typeerror(self):
        """tier_in: "S" (scalar instead of list) raises TypeError. The
        operator-friendly error tells them to use [S] not S."""
        with pytest.raises(TypeError, match="must be a list"):
            _block_when_matches(
                {"tier_in": "S"}, _make_ctx(tier="S"),
            )

    def test_helper_directly_with_tier_none_and_filter_set(self):
        """Direct unit test of _block_when_matches: ctx.tier=None
        against block_when={'tier': 'S'} returns False (filter does
        not match → rule does not fire)."""
        assert _block_when_matches(
            {"tier": "S"}, _make_ctx(tier=None),
        ) is False

    def test_helper_directly_with_tier_none_and_tier_in_set(self):
        """ctx.tier=None against block_when={'tier_in': [S, A]} → False."""
        assert _block_when_matches(
            {"tier_in": ["S", "A"]}, _make_ctx(tier=None),
        ) is False

    def test_helper_with_no_tier_keys_ignores_ctx_tier(self):
        """A block_when: with no tier keys works for both tier and
        no-tier contexts (backward-compat with every existing rule)."""
        assert _block_when_matches(
            {"register": "cold-pitch"},
            _make_ctx(tier=None, register="cold-pitch"),
        ) is True
        assert _block_when_matches(
            {"register": "cold-pitch"},
            _make_ctx(tier="S", register="cold-pitch"),
        ) is True


# ---------------------------------------------------------------------------
# Empty-context invariant — None tier does not block anyone except the
# substantive tier rule, when configured
# ---------------------------------------------------------------------------


class TestEmptyContextNoFalseBlocks:
    """When NO tier rule is configured, ctx.tier=None must not cause
    any existing rule class to block. This is the backward-compat
    invariant for ADR-0007: every existing test in the suite was
    written with no tier field; the additive None default must
    preserve their verdicts.
    """

    def test_cooldown_with_none_tier_unchanged_verdict(self):
        rule = cd.NoDuplicateRegisterRule(
            name="no-dup-cold-pitch",
            block_when={"register": "cold-pitch"},
        )
        led = _FakeLedger()
        # No prior send → Allow regardless of tier.
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, tier=None)),
            policy_types.Allow,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, tier="S")),
            policy_types.Allow,
        )
        # Now seed a prior send — both tiers Block.
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, tier=None)),
            policy_types.Block,
        )
        assert isinstance(
            rule.evaluate(_make_ctx(ledger=led, tier="S")),
            policy_types.Block,
        )

    def test_budget_with_none_tier_unchanged_verdict(self):
        """Budget rule without tier scoping treats ctx.tier=None the
        same as ctx.tier='S' — the cap still fires."""
        now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for _ in range(12):
            led.add_cost(
                source="apollo", amount_usd=5.0, units=1,
                ts=now - timedelta(minutes=10),
            )
        rule = bd.BudgetWindowCapRule(
            name="daily-apollo-cap",
            source="apollo", window_hours=24, max_usd=50.0,
        )
        ctx_none = _make_ctx(ledger=led, now=now, tier=None)
        ctx_s = _make_ctx(ledger=led, now=now, tier="S")
        assert isinstance(rule.evaluate(ctx_none), policy_types.Block)
        assert isinstance(rule.evaluate(ctx_s), policy_types.Block)


# ---------------------------------------------------------------------------
# Regression sentinels — ADR-0002 + ADR-0005 contracts still hold
# ---------------------------------------------------------------------------


class TestCooldownDSTPropertyStillHolds:
    """Asserts ADR-0002's tz-invariance of cooldown rules survives
    the Week 5 changes (tier field + block_when filter extension)."""

    def test_no_duplicate_register_invariant_to_tz(self):
        led = _FakeLedger()
        seed_ts = datetime(2026, 3, 15, 18, 0, tzinfo=timezone.utc)
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=seed_ts,
        )
        rule = cd.NoDuplicateRegisterRule(
            name="no-dup", block_when={"register": "cold-pitch"},
        )
        now = datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc)
        # Same verdict across every tz — including DST-transition ones.
        for tz_name in (
            "America/Los_Angeles",
            "America/New_York",
            "Europe/London",
            "Asia/Tokyo",
            "UTC",
        ):
            ctx = _make_ctx(ledger=led, now=now, tz=tz_name)
            result = rule.evaluate(ctx)
            assert isinstance(result, policy_types.Block), (
                f"cooldown verdict drifted on tz={tz_name}"
            )


class TestSendingWindowTzDependenceStillHolds:
    """Asserts ADR-0005's tz-dependence of sending-window rules survives
    Week 5 changes."""

    def test_local_time_window_blocks_in_one_tz_allows_in_another(self):
        rule = sw.LocalTimeOfDayRule(
            name="business-hours",
            start_local="09:00",
            end_local="17:00",
            block_when={"channel": "email"},
        )
        # 17:00 UTC = 10:00 LA (PDT, May) → inside window → Allow.
        # 17:00 UTC = 02:00 Tokyo next day → outside window → Block.
        now = datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc)
        ctx_la = _make_ctx(now=now, tz="America/Los_Angeles")
        ctx_tokyo = _make_ctx(now=now, tz="Asia/Tokyo")
        assert isinstance(rule.evaluate(ctx_la), policy_types.Allow)
        assert isinstance(rule.evaluate(ctx_tokyo), policy_types.Block)
