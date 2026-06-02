"""Pillar A Week 1 task #4 — policy engine types + ordered short-circuit evaluator.

These tests exercise the engine surface independently of any concrete rule
class. The rule registry + YAML loader behavior is tested here too so the
contract is locked before Pillar A Week 1 task #5 lands the first real
cooldown rule against it.

What's covered:
  - types: Allow / Block / RuleContext immutability + equality + defaults.
  - engine.evaluate: empty rules → Allow; first-block-wins; short-circuit;
    exception propagation (no silent swallow).
  - rule registry: register_rule_class normal + double-register raises.
  - load_rules_from_yaml: missing file → []; missing version → raises;
    wrong version → raises; unknown rule type → raises; rule order in YAML
    preserved in returned list.

What is intentionally NOT covered here (deferred to test_policy_cooldown.py
in task #5): any test that requires a concrete rule class. We use a tiny
fake rule (`_TestRule` below) registered only in this module's setup, so
the engine tests don't depend on cooldown/suppression/budget existing yet.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import pytest


# Bare-name import works because conftest.py inserts orchestrator/ on sys.path,
# and policy/__init__.py re-exports the public surface.
from orchestrator import policy as policy_pkg
from orchestrator.policy import types as policy_types
from orchestrator.policy import engine as policy_engine


# ---------------------------------------------------------------------------
# Fake rule + fake ledger (used across multiple test classes)
# ---------------------------------------------------------------------------


class _FakeLedger:
    """Minimal LedgerLike for engine tests.

    Engine tests don't actually consult the ledger (the fake rules below
    don't either) — this exists to satisfy RuleContext's type contract.
    """

    def query_by_person(self, person_id, since=None):
        return []

    def last_send_for(self, person_id, channel):
        return None

    def query_by_email(self, email):
        return set()

    def all_events(self):
        return []


def _make_ctx(**overrides):
    """Default RuleContext for tests. Overrides via kwargs."""
    defaults = dict(
        person_id="alice-li",
        channel="email",
        register="cold-pitch",
        email="alice@example.com",
        email_domain="example.com",
        now=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        timezone="America/Los_Angeles",
        ledger=_FakeLedger(),
    )
    defaults.update(overrides)
    return policy_types.RuleContext(**defaults)


class _AllowRule:
    """Always-Allow fake rule."""

    name = "always-allow"

    def evaluate(self, ctx):
        return policy_types.Allow()

    @classmethod
    def from_yaml(cls, spec):
        return cls()


class _BlockRule:
    """Always-Block fake rule with configurable identity."""

    def __init__(self, name="always-block", reason="blocked for test"):
        self.name = name
        self._reason = reason

    def evaluate(self, ctx):
        return policy_types.Block(
            rule=self.name,
            reason=self._reason,
            detail={"ctx_person_id": ctx.person_id},
        )

    @classmethod
    def from_yaml(cls, spec):
        return cls(name=spec.get("name", "always-block"),
                   reason=spec.get("reason", "blocked"))


class _RaiseRule:
    """A rule whose evaluate raises — used to verify no silent swallow."""

    name = "raise-rule"

    def evaluate(self, ctx):
        raise RuntimeError("policy outage")

    @classmethod
    def from_yaml(cls, spec):
        return cls()


# ---------------------------------------------------------------------------
# types — Allow / Block / RuleContext
# ---------------------------------------------------------------------------


class TestAllow:
    def test_allow_is_frozen(self):
        a = policy_types.Allow()
        with pytest.raises(dataclasses.FrozenInstanceError):
            a.foo = "bar"  # type: ignore[attr-defined]

    def test_two_allows_are_equal(self):
        # Markers — equality regardless of identity.
        assert policy_types.Allow() == policy_types.Allow()

    def test_allow_has_no_fields(self):
        assert dataclasses.fields(policy_types.Allow) == ()


class TestBlock:
    def test_block_requires_rule_and_reason(self):
        b = policy_types.Block(rule="r", reason="why")
        assert b.rule == "r"
        assert b.reason == "why"
        assert b.detail == {}  # default empty dict

    def test_block_detail_carries_evidence(self):
        b = policy_types.Block(rule="r", reason="why", detail={"k": 1})
        assert b.detail == {"k": 1}

    def test_block_is_frozen(self):
        b = policy_types.Block(rule="r", reason="why")
        with pytest.raises(dataclasses.FrozenInstanceError):
            b.rule = "other"  # type: ignore[misc]

    def test_block_equality(self):
        b1 = policy_types.Block(rule="r", reason="why", detail={"k": 1})
        b2 = policy_types.Block(rule="r", reason="why", detail={"k": 1})
        b3 = policy_types.Block(rule="r", reason="why", detail={"k": 2})
        assert b1 == b2
        assert b1 != b3

    def test_block_is_distinct_from_allow(self):
        assert policy_types.Block(rule="r", reason="why") != policy_types.Allow()


class TestRuleContext:
    def test_required_fields(self):
        ctx = _make_ctx()
        assert ctx.person_id == "alice-li"
        assert ctx.channel == "email"
        assert ctx.register == "cold-pitch"

    def test_is_frozen(self):
        ctx = _make_ctx()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.person_id = "other"  # type: ignore[misc]

    def test_now_is_timezone_aware(self):
        ctx = _make_ctx()
        assert ctx.now.tzinfo is not None

    def test_email_can_be_none(self):
        ctx = _make_ctx(email=None, email_domain=None)
        assert ctx.email is None
        assert ctx.email_domain is None


# ---------------------------------------------------------------------------
# engine.evaluate — ordered short-circuit
# ---------------------------------------------------------------------------


class TestEvaluate:
    def test_empty_rules_returns_allow(self):
        result = policy_engine.evaluate([], _make_ctx())
        assert isinstance(result, policy_types.Allow)

    def test_single_allow_rule_returns_allow(self):
        result = policy_engine.evaluate([_AllowRule()], _make_ctx())
        assert isinstance(result, policy_types.Allow)

    def test_single_block_rule_returns_that_block(self):
        rule = _BlockRule(name="my-rule", reason="my reason")
        result = policy_engine.evaluate([rule], _make_ctx())
        assert isinstance(result, policy_types.Block)
        assert result.rule == "my-rule"
        assert result.reason == "my reason"

    def test_block_detail_carries_context(self):
        result = policy_engine.evaluate(
            [_BlockRule()], _make_ctx(person_id="bob-li"),
        )
        assert isinstance(result, policy_types.Block)
        assert result.detail["ctx_person_id"] == "bob-li"

    def test_allow_then_block_returns_block(self):
        result = policy_engine.evaluate(
            [_AllowRule(), _BlockRule(name="second")], _make_ctx(),
        )
        assert isinstance(result, policy_types.Block)
        assert result.rule == "second"

    def test_first_block_wins_over_second_block(self):
        """First Block in list short-circuits — second is not consulted."""
        result = policy_engine.evaluate(
            [_BlockRule(name="first"), _BlockRule(name="second")],
            _make_ctx(),
        )
        assert isinstance(result, policy_types.Block)
        assert result.rule == "first"

    def test_short_circuit_does_not_call_later_rules(self):
        """A rule placed after a Block must not have its evaluate called.

        Proves the engine is short-circuit, not aggregate. Critical for
        ledger event emission: we want exactly one policy_blocked event
        per gate decision, not N.
        """
        call_log: list[str] = []

        class _LoggingAllow:
            name = "logging-allow"

            def evaluate(self, ctx):
                call_log.append(self.name)
                return policy_types.Allow()

            @classmethod
            def from_yaml(cls, spec):
                return cls()

        class _LoggingBlock:
            name = "logging-block"

            def evaluate(self, ctx):
                call_log.append(self.name)
                return policy_types.Block(rule=self.name, reason="r")

            @classmethod
            def from_yaml(cls, spec):
                return cls()

        rules = [_LoggingAllow(), _LoggingBlock(), _LoggingAllow()]
        policy_engine.evaluate(rules, _make_ctx())
        # The second LoggingAllow (index 2) must NOT have been called.
        assert call_log == ["logging-allow", "logging-block"]

    def test_rule_exception_propagates(self):
        """A bug in one rule must not be silently swallowed.

        Per ADR-0001: silent swallow would hide policy outages from the
        gate. The send-loop is expected to catch + log + halt the run,
        but the engine itself must not eat the exception.
        """
        with pytest.raises(RuntimeError, match="policy outage"):
            policy_engine.evaluate(
                [_AllowRule(), _RaiseRule()], _make_ctx(),
            )

    def test_evaluate_accepts_any_iterable(self):
        """Tuples, generators, lists all work — Iterable[Rule], not List[Rule]."""
        # Tuple.
        assert isinstance(
            policy_engine.evaluate((_AllowRule(),), _make_ctx()),
            policy_types.Allow,
        )

        # Generator.
        def gen():
            yield _AllowRule()
            yield _BlockRule(name="from-gen")

        result = policy_engine.evaluate(gen(), _make_ctx())
        assert isinstance(result, policy_types.Block)
        assert result.rule == "from-gen"


# ---------------------------------------------------------------------------
# Rule registry — register_rule_class
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_registry(monkeypatch):
    """Snapshot + restore RULE_REGISTRY around a test that mutates it.

    Several tests register fake rule classes; we don't want them leaking
    into other tests' namespaces, especially since cooldown.py (task #5)
    will register real classes that must not clash with test names.
    """
    snapshot = dict(policy_engine.RULE_REGISTRY)
    yield
    policy_engine.RULE_REGISTRY.clear()
    policy_engine.RULE_REGISTRY.update(snapshot)


class TestRuleRegistry:
    def test_register_then_lookup(self, clean_registry):
        policy_engine.register_rule_class("test.allow-rule", _AllowRule)
        assert policy_engine.RULE_REGISTRY["test.allow-rule"] is _AllowRule

    def test_double_registration_raises(self, clean_registry):
        policy_engine.register_rule_class("test.allow-rule", _AllowRule)
        # Double-register under the same key — silent shadow would be the
        # bug; explicit error is what we want.
        with pytest.raises(ValueError, match="already registered"):
            policy_engine.register_rule_class("test.allow-rule", _BlockRule)

    def test_distinct_keys_coexist(self, clean_registry):
        policy_engine.register_rule_class("test.allow", _AllowRule)
        policy_engine.register_rule_class("test.block", _BlockRule)
        assert policy_engine.RULE_REGISTRY["test.allow"] is _AllowRule
        assert policy_engine.RULE_REGISTRY["test.block"] is _BlockRule


# ---------------------------------------------------------------------------
# YAML loader — load_rules_from_yaml
# ---------------------------------------------------------------------------


class TestLoadRulesFromYaml:
    def test_missing_file_returns_empty_list(self, tmp_path):
        """Greenfield OSS install: no cooldowns.yml exists yet.

        Engine must not block sends in that state — doctor preflight is
        responsible for warning the user.
        """
        result = policy_engine.load_rules_from_yaml(tmp_path / "nope.yml")
        assert result == []

    def test_empty_file_returns_empty_list(self, tmp_path, clean_registry):
        """A file with only `version: 1` and no rules: returns []."""
        p = tmp_path / "rules.yml"
        p.write_text("version: 1\nrules: []\n", encoding="utf-8")
        result = policy_engine.load_rules_from_yaml(p)
        assert result == []

    def test_missing_version_raises(self, tmp_path):
        p = tmp_path / "rules.yml"
        p.write_text("rules: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="version"):
            policy_engine.load_rules_from_yaml(p)

    def test_wrong_version_raises(self, tmp_path):
        p = tmp_path / "rules.yml"
        p.write_text("version: 999\nrules: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="version"):
            policy_engine.load_rules_from_yaml(p)

    def test_single_quoted_version_loads_via_int_coercion(self, tmp_path):
        """`version: '1'` (single-quoted) parses as Python ``str`` via
        ``yaml.safe_load``. Pre-fix: ``'1' not in frozenset({1, 2})``
        → engine raises "unsupported version '1'". Post-fix (Pillar B
        Week 6 second follow-up per
        `.planning/REVIEW-pillar-a-b-coherence.md` §P1-1): engine
        coerces to ``int`` before the membership check, accepting the
        quoted form.

        This matters because
        ``orchestrator.migrations.policy._policy_io.bump_version_text``
        deliberately preserves quote style on rewrite; an operator
        whose factory YAML has a quoted version line would have their
        engine refuse to load post-migration without this fix."""
        p = tmp_path / "rules.yml"
        p.write_text("version: '1'\nrules: []\n", encoding="utf-8")
        # Must NOT raise — the int-coercion accepts the quoted form.
        result = policy_engine.load_rules_from_yaml(p)
        assert result == []

    def test_double_quoted_version_loads_via_int_coercion(self, tmp_path):
        """`version: "2"` (double-quoted) is the other quote-style
        variant. Same fix; same expectation."""
        p = tmp_path / "rules.yml"
        p.write_text('version: "2"\nrules: []\n', encoding="utf-8")
        result = policy_engine.load_rules_from_yaml(p)
        assert result == []

    def test_quoted_unsupported_version_still_refuses(self, tmp_path):
        """The int-coercion fix MUST NOT regress the wrong-version
        refusal: `version: '999'` still gets refused. Pinned so a
        future contributor doesn't think the fix means "accept
        anything"."""
        p = tmp_path / "rules.yml"
        p.write_text("version: '999'\nrules: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="999"):
            policy_engine.load_rules_from_yaml(p)

    def test_non_numeric_version_string_refuses(self, tmp_path):
        """`version: foo` (non-numeric string) cannot coerce to int.
        The fix's ``try/except (TypeError, ValueError)`` lets the
        original raw value through to the membership check, which
        refuses loud with the operator-readable "unsupported version"
        message."""
        p = tmp_path / "rules.yml"
        p.write_text("version: foo\nrules: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="foo"):
            policy_engine.load_rules_from_yaml(p)

    def test_unknown_rule_type_raises(self, tmp_path, clean_registry):
        p = tmp_path / "rules.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: x\n"
            "    type: never.registered\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="never.registered"):
            policy_engine.load_rules_from_yaml(p)

    def test_registered_rule_loads(self, tmp_path, clean_registry):
        policy_engine.register_rule_class("test.allow-rule", _AllowRule)
        p = tmp_path / "rules.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: my-allow\n"
            "    type: test.allow-rule\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 1
        # The fake's from_yaml ignores spec name, so just check class.
        assert isinstance(rules[0], _AllowRule)

    def test_rule_order_preserved(self, tmp_path, clean_registry):
        """YAML rule order = evaluation order (load-bearing per ADR-0001)."""
        policy_engine.register_rule_class("test.allow-rule", _AllowRule)
        policy_engine.register_rule_class("test.block-rule", _BlockRule)
        p = tmp_path / "rules.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: first-block\n"
            "    type: test.block-rule\n"
            "    reason: first one\n"
            "  - name: second-allow\n"
            "    type: test.allow-rule\n"
            "  - name: third-block\n"
            "    type: test.block-rule\n"
            "    reason: third one\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 3
        # _BlockRule reads name from spec; _AllowRule has fixed name.
        assert rules[0].name == "first-block"
        assert rules[1].name == "always-allow"
        assert rules[2].name == "third-block"

    def test_missing_rule_name_raises(self, tmp_path, clean_registry):
        policy_engine.register_rule_class("test.allow-rule", _AllowRule)
        p = tmp_path / "rules.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - type: test.allow-rule\n",  # missing name:
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="name"):
            policy_engine.load_rules_from_yaml(p)

    def test_missing_rule_type_raises(self, tmp_path, clean_registry):
        p = tmp_path / "rules.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: orphan\n",  # missing type:
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="type"):
            policy_engine.load_rules_from_yaml(p)


# ---------------------------------------------------------------------------
# engine.evaluate_all — non-short-circuit variant (ADR-0007 §Decision item
# "Simulation surface")
# ---------------------------------------------------------------------------


class TestEvaluateAll:
    """`evaluate_all` returns one verdict per rule, in iteration order.

    The contract divergence from ``evaluate``:
      - no short-circuit (every rule's evaluate is called)
      - return shape is ``list[RuleResult]`` not ``RuleResult``
      - exception propagation matches ``evaluate`` (ADR-0001 §Decision
        item 2 — engine doesn't swallow rule exceptions)
    """

    def test_empty_rules_returns_empty_list(self):
        """Empty input → empty list (not [Allow()] — zero verdicts is
        the truthful shape; ADR-0007 §Decision item "Simulation surface")."""
        result = policy_engine.evaluate_all([], _make_ctx())
        assert result == []

    def test_single_allow_returns_one_allow(self):
        results = policy_engine.evaluate_all([_AllowRule()], _make_ctx())
        assert len(results) == 1
        assert isinstance(results[0], policy_types.Allow)

    def test_single_block_returns_one_block(self):
        rule = _BlockRule(name="my-rule", reason="my reason")
        results = policy_engine.evaluate_all([rule], _make_ctx())
        assert len(results) == 1
        assert isinstance(results[0], policy_types.Block)
        assert results[0].rule == "my-rule"

    def test_verdicts_parallel_to_rules(self):
        rules = [
            _AllowRule(),
            _BlockRule(name="second"),
            _AllowRule(),
            _BlockRule(name="fourth"),
        ]
        results = policy_engine.evaluate_all(rules, _make_ctx())
        assert len(results) == 4
        assert isinstance(results[0], policy_types.Allow)
        assert isinstance(results[1], policy_types.Block)
        assert results[1].rule == "second"
        assert isinstance(results[2], policy_types.Allow)
        assert isinstance(results[3], policy_types.Block)
        assert results[3].rule == "fourth"

    def test_no_short_circuit_calls_every_rule(self):
        """Even after a Block, later rules still get evaluated."""
        call_log: list[str] = []

        class _LoggingAllow:
            name = "logging-allow"

            def evaluate(self, ctx):
                call_log.append(self.name)
                return policy_types.Allow()

            @classmethod
            def from_yaml(cls, spec):
                return cls()

        class _LoggingBlock:
            def __init__(self, suffix: str):
                self.name = f"logging-block-{suffix}"

            def evaluate(self, ctx):
                call_log.append(self.name)
                return policy_types.Block(rule=self.name, reason="r")

            @classmethod
            def from_yaml(cls, spec):
                return cls(spec.get("suffix", "x"))

        rules = [
            _LoggingAllow(),
            _LoggingBlock("first"),
            _LoggingAllow(),
            _LoggingBlock("second"),
        ]
        results = policy_engine.evaluate_all(rules, _make_ctx())
        # Every rule was called — short-circuit is OFF.
        assert call_log == [
            "logging-allow",
            "logging-block-first",
            "logging-allow",
            "logging-block-second",
        ]
        # And every verdict is in the result.
        assert len(results) == 4
        assert isinstance(results[1], policy_types.Block)
        assert isinstance(results[3], policy_types.Block)
        assert results[1].rule == "logging-block-first"
        assert results[3].rule == "logging-block-second"

    def test_short_circuit_vs_non_short_circuit_comparison(self):
        """`evaluate` returns the first Block; `evaluate_all` returns every
        verdict. The first Block in `evaluate_all`'s result MUST equal
        `evaluate`'s return."""
        rules = [
            _AllowRule(),
            _BlockRule(name="first-block", reason="r1"),
            _AllowRule(),
            _BlockRule(name="second-block", reason="r2"),
        ]
        ctx = _make_ctx()
        ev = policy_engine.evaluate(rules, ctx)
        all_results = policy_engine.evaluate_all(rules, ctx)

        # evaluate returns the first block (short-circuit).
        assert isinstance(ev, policy_types.Block)
        assert ev.rule == "first-block"

        # evaluate_all has every verdict, in order.
        assert len(all_results) == 4
        # The first Block in evaluate_all's result equals what evaluate
        # returned (well, equal by structure — Block has __eq__).
        first_block_in_all = next(
            r for r in all_results if isinstance(r, policy_types.Block)
        )
        assert first_block_in_all == ev

    def test_exception_propagates_uncaught(self):
        """Same contract as `evaluate` — engine does not swallow.

        A rule raising during simulation should bubble up; the CLI
        is responsible for the operator-friendly traceback. The engine
        itself must not eat the exception (ADR-0001 §Decision item 2).
        """
        with pytest.raises(RuntimeError, match="policy outage"):
            policy_engine.evaluate_all(
                [_AllowRule(), _RaiseRule()], _make_ctx(),
            )

    def test_exception_propagates_even_after_block(self):
        """Even when an earlier rule already produced a Block, a later
        rule's exception still bubbles up (no short-circuit means we
        do reach the raising rule)."""
        with pytest.raises(RuntimeError, match="policy outage"):
            policy_engine.evaluate_all(
                [_BlockRule(name="first"), _RaiseRule()], _make_ctx(),
            )

    def test_accepts_any_iterable(self):
        """Parallel with `evaluate`: tuples, generators, lists all work."""
        # Tuple.
        result = policy_engine.evaluate_all(
            (_AllowRule(), _BlockRule(name="x")), _make_ctx(),
        )
        assert len(result) == 2

        # Generator.
        def gen():
            yield _AllowRule()
            yield _BlockRule(name="from-gen")
        result = policy_engine.evaluate_all(gen(), _make_ctx())
        assert len(result) == 2
        assert result[1].rule == "from-gen"


# ---------------------------------------------------------------------------
# Public surface — __init__.py re-exports
# ---------------------------------------------------------------------------


class TestPublicSurface:
    """Lock the public API contract: callers import from `orchestrator.policy`."""

    def test_allow_exported(self):
        assert policy_pkg.Allow is policy_types.Allow

    def test_block_exported(self):
        assert policy_pkg.Block is policy_types.Block

    def test_rule_context_exported(self):
        assert policy_pkg.RuleContext is policy_types.RuleContext

    def test_evaluate_exported(self):
        assert policy_pkg.evaluate is policy_engine.evaluate

    def test_evaluate_all_exported(self):
        """ADR-0007 §Decision item "Simulation surface" — evaluate_all
        is part of the public API."""
        assert policy_pkg.evaluate_all is policy_engine.evaluate_all

    def test_load_rules_from_yaml_exported(self):
        assert policy_pkg.load_rules_from_yaml is \
            policy_engine.load_rules_from_yaml

    def test_register_rule_class_exported(self):
        assert policy_pkg.register_rule_class is \
            policy_engine.register_rule_class
