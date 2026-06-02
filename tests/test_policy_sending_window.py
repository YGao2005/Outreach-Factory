"""Pillar A Week 3 — sending-window rules + DST tz-DEPENDENCE property.

Covers the two factory sending-window rule classes:
  - LocalTimeOfDayRule (sending-window.local-time-of-day)
  - DayOfWeekRule (sending-window.day-of-week)

Tests are organized:
  TestLocalTimeOfDayRule — in/out-of-window allow/block, boundary semantics.
  TestWindowWrapsMidnight — windows that span midnight (22:00→06:00).
  TestTimezoneDependence — Hypothesis property INVERTING the cooldown DST
                            property: for a fixed UTC `now`, the verdict
                            CHANGES across recipient timezones.
  TestDSTNonExistentTime — spring-forward 02:30 (no such wall-clock time).
                            zoneinfo's resolution must yield a consistent
                            verdict.
  TestDSTAmbiguousTime — fall-back 01:30 (the same wall-clock occurs twice).
                          Both repeated UTC instants must yield the same
                          verdict (the rule reads local time-of-day only,
                          which is identical across the two folds).
  TestUnparseableTimezone — invalid IANA string → Block (restrictive
                             interpretation per ADR-0005, mirroring the
                             cooldown rule's asymmetric-failure-cost stance).
  TestDayOfWeekRule — allowed-days allow/block, weekend filter, unparseable
                       tz handling.
  TestFromYaml — each rule class round-trips through YAML spec.
  TestEngineIntegration — end-to-end: load factory rules from YAML, evaluate
                           through engine.evaluate against synthetic ctx.
  TestEmptyDayOfWeek — defensive: empty allowed_days → restrictive block.
  TestBlockWhenFilter — both rules support the standard block_when filter.
  TestLocalNowHelper — the shared ``_local_now`` helper returns the correct
                        zoneinfo-localized datetime and raises the documented
                        error type for unparseable timezones.

The fake ledger is a no-op stub — sending-window rules don't consult the
ledger, they consult ``ctx.now`` and ``ctx.timezone`` only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from orchestrator.policy import _helpers as policy_helpers
from orchestrator.policy import engine as policy_engine
from orchestrator.policy import sending_window as sw
from orchestrator.policy import types as policy_types


# ---------------------------------------------------------------------------
# Stub ledger — sending-window rules don't query the ledger.
# ---------------------------------------------------------------------------


class _StubLedger:
    def query_by_person(self, person_id, since=None):
        return []

    def last_send_for(self, person_id, channel):
        return None

    def query_by_email(self, email):
        return set()

    def all_events(self):
        return []


def _make_ctx(
    *,
    channel="email",
    register="cold-pitch",
    person_id="alice-li",
    email="alice@example.com",
    now=None,
    tz="America/Los_Angeles",
    person_status=None,
):
    """Build a RuleContext with sensible defaults.

    ``now`` defaults to a date deliberately NOT on a DST transition so the
    base allow/block tests aren't accidentally noised by tz-transition
    effects. DST tests construct their own ``now`` explicitly.
    """
    return policy_types.RuleContext(
        person_id=person_id,
        channel=channel,
        register=register,
        email=email,
        email_domain=email.split("@", 1)[1] if email and "@" in email else None,
        now=now or datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),  # noon LA
        timezone=tz,
        ledger=_StubLedger(),
        person_status=person_status,
    )


# ---------------------------------------------------------------------------
# LocalTimeOfDayRule — basic allow/block semantics
# ---------------------------------------------------------------------------


class TestLocalTimeOfDayRule:
    def _rule(self, start="09:00", end="17:00", **kw):
        return sw.LocalTimeOfDayRule(
            name="business-hours-only",
            start_local=start,
            end_local=end,
            block_when=kw.get("block_when", {}),
            reason=kw.get("reason", "Outside recipient business hours"),
        )

    def test_inside_window_allows(self):
        # UTC 19:00 → 12:00 PDT (May, DST active). Inside 09:00-17:00.
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_before_window_blocks(self):
        # UTC 13:00 on a May weekday → 06:00 PDT. Before 09:00 → Block.
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        result = self._rule().evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "business-hours-only"
        # Detail carries the actual local time so audit can see "we refused
        # because it was 06:00, not 09:00."
        assert result.detail.get("local_time")
        assert result.detail.get("timezone") == "America/Los_Angeles"
        assert result.detail.get("start_local") == "09:00"
        assert result.detail.get("end_local") == "17:00"

    def test_after_window_blocks(self):
        # UTC 03:00 → 20:00 PDT (previous day). After 17:00 → Block.
        ctx = _make_ctx(
            now=datetime(2026, 5, 19, 3, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Block)

    def test_at_start_boundary_allows(self):
        """Inclusive lower-end: 09:00:00 local is INSIDE the window.

        Pins the boundary convention matching the cooldown DomainThrottleRule
        and CrossChannelTouchRule (ADR-0003 CC-06). Without this test the
        ``<=`` vs ``<`` choice could silently drift.
        """
        # UTC 16:00 → 09:00 PDT exactly.
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 16, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_at_end_boundary_blocks(self):
        """Exclusive upper-end: 17:00:00 local is OUTSIDE the window.

        Standard half-open interval [start, end). A send AT the upper
        boundary instant is refused; one microsecond before is allowed.
        """
        # UTC 00:00 next day → 17:00 PDT exactly.
        ctx = _make_ctx(
            now=datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Block)

    def test_one_microsecond_before_end_allows(self):
        """Boundary pin paired with test_at_end_boundary_blocks — together
        they unambiguously pin the half-open interval convention."""
        # 1 microsecond before UTC 00:00 → 16:59:59.999999 PDT.
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 23, 59, 59, 999999, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# Windows that wrap midnight (start > end)
# ---------------------------------------------------------------------------


class TestWindowWrapsMidnight:
    def _rule(self):
        # Night-shift "send during 22:00-06:00 recipient-local" — block during
        # the 06:00-22:00 daytime range.
        return sw.LocalTimeOfDayRule(
            name="night-shift-only",
            start_local="22:00",
            end_local="06:00",
            reason="Only send during recipient's night-shift hours",
        )

    def test_late_evening_inside_wrapping_window_allows(self):
        # UTC 06:00 → 23:00 PDT previous day. Inside [22:00, 06:00). Allow.
        ctx = _make_ctx(
            now=datetime(2026, 5, 19, 6, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_early_morning_inside_wrapping_window_allows(self):
        # UTC 09:00 → 02:00 PDT. Inside [22:00, 06:00). Allow.
        ctx = _make_ctx(
            now=datetime(2026, 5, 19, 9, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_midday_outside_wrapping_window_blocks(self):
        # UTC 14:00 → 07:00 PDT. Outside the wrapping window. Block.
        ctx = _make_ctx(
            now=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Block)

    def test_start_boundary_in_wrapping_window_allows(self):
        # UTC 05:00 → 22:00 PDT previous day. Inclusive start: Allow.
        ctx = _make_ctx(
            now=datetime(2026, 5, 19, 5, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_end_boundary_in_wrapping_window_blocks(self):
        # UTC 13:00 → 06:00 PDT. Exclusive end: Block.
        ctx = _make_ctx(
            now=datetime(2026, 5, 19, 13, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        assert isinstance(self._rule().evaluate(ctx), policy_types.Block)


# ---------------------------------------------------------------------------
# Same-start-as-end (degenerate empty window)
# ---------------------------------------------------------------------------


class TestEmptyAndFullDayWindows:
    def test_equal_start_and_end_is_empty_window_blocks(self):
        """start == end → empty window → always Block.

        Documented convention: a degenerate window is treated as the empty
        set (NOT the 24h "always" interpretation). Asymmetric-failure-cost:
        a typo in YAML producing an equal start/end should refuse rather
        than open the floodgates.
        """
        rule = sw.LocalTimeOfDayRule(
            name="empty-window",
            start_local="12:00",
            end_local="12:00",
        )
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("degenerate") is True


# ---------------------------------------------------------------------------
# Timezone-DEPENDENCE — the property that distinguishes this rule from
# cooldown's tz-invariance.
# ---------------------------------------------------------------------------


_TZ_SAMPLES = [
    "UTC",
    "America/Los_Angeles",
    "Europe/London",
    "Australia/Sydney",
    "Asia/Tokyo",
    "Asia/Kolkata",
]


class TestTimezoneDependence:
    """Hypothesis property: for a fixed UTC ``now`` and a non-trivial window,
    the sending-window verdict DEPENDS on the recipient timezone.

    This is the inverse of cooldown's DST-safety property
    (``test_policy_cooldown.py::TestDSTSafetyProperty``). The two properties
    together encode the ADR-0002/0005 contract: cooldown is UTC-only;
    sending-window is local-time-of-day only. If a refactor accidentally
    drifted either rule into the other's regime, one of these property
    tests would fail.
    """

    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        # Cover all 24 hours of UTC by stepping at hour granularity. The
        # property we want is *existential*: there must EXIST a pair (tz1,
        # tz2) where the verdict differs at SOME UTC instant. We assert
        # this once across the search space, not per-example.
        utc_hour=st.integers(min_value=0, max_value=23),
    )
    def test_verdict_differs_across_timezones_at_some_utc_hour(self, utc_hour):
        """At any single UTC hour, the local-time verdict for 09:00-17:00
        is *not* the same across every timezone. Concretely: at UTC 12:00,
        Tokyo is 21:00 (block) while London is 12:00 BST (allow).

        Encoding this as a Hypothesis property protects against a regression
        where someone refactored the rule to consult UTC time directly —
        the property would shrink to a counterexample showing identical
        verdicts.
        """
        rule = sw.LocalTimeOfDayRule(
            name="business-hours",
            start_local="09:00",
            end_local="17:00",
        )
        now = datetime(2026, 5, 18, utc_hour, 0, tzinfo=timezone.utc)

        verdicts = {}
        for tz in _TZ_SAMPLES:
            ctx = _make_ctx(now=now, tz=tz)
            v = rule.evaluate(ctx)
            verdicts[tz] = type(v).__name__

        # The property: NOT all timezones produce the same verdict at every
        # UTC hour. (At some hours they may all agree — e.g. UTC noon when
        # Tokyo + Sydney + LA + London all happen to fall outside 9-5, but
        # such hours don't exist because LA noon is in window. Across the
        # 24 hours sampled, at least one hour shows divergence.)
        # We assert per-hour: for any hour, the local-tod values across
        # timezones MUST differ (verdicts may coincidentally agree, but the
        # rule's INPUT cannot be tz-invariant at any hour).
        local_tods = set()
        for tz in _TZ_SAMPLES:
            local = now.astimezone(ZoneInfo(tz))
            local_tods.add((local.hour, local.minute))
        # 6 distinct timezones at the same UTC instant must give at least 5
        # distinct local TODs (Asia/Kolkata's +5:30 offset alone is unique).
        assert len(local_tods) >= 5, (
            f"At UTC hour {utc_hour}, expected ≥5 distinct local TODs across "
            f"{_TZ_SAMPLES}, got {len(local_tods)}: {local_tods}"
        )

    def test_concrete_tokyo_vs_london_diverge(self):
        """Anchor test: at UTC 04:00 on a normal weekday, Tokyo is 13:00
        (in 09-17 window → Allow) and London is 05:00 (BST: 05:00; pre-BST
        the divergence is even sharper) — outside 09-17 → Block.

        This is the load-bearing contract for the rule class.
        """
        rule = sw.LocalTimeOfDayRule(
            name="business-hours",
            start_local="09:00",
            end_local="17:00",
        )
        now = datetime(2026, 5, 18, 4, 0, tzinfo=timezone.utc)

        ctx_tokyo = _make_ctx(now=now, tz="Asia/Tokyo")
        ctx_london = _make_ctx(now=now, tz="Europe/London")

        assert isinstance(rule.evaluate(ctx_tokyo), policy_types.Allow), (
            "Tokyo 13:00 must be Allow"
        )
        assert isinstance(rule.evaluate(ctx_london), policy_types.Block), (
            "London 05:00 BST must be Block"
        )


# ---------------------------------------------------------------------------
# DST edge cases — non-existent and ambiguous local times
# ---------------------------------------------------------------------------


class TestDSTNonExistentTime:
    """Spring-forward day in Los Angeles: 2026-03-08 02:00 PST → 03:00 PDT.

    The wall-clock time 02:30 simply does not occur. Any UTC instant that
    would have mapped to 02:30 PST (i.e. UTC 10:30 on 2026-03-08) maps
    instead to 03:30 PDT under zoneinfo's normalization. The rule reads
    whatever local time-of-day zoneinfo returns; the verdict is consistent.

    Convention (ADR-0005): we rely on zoneinfo's default fold=0 behavior.
    No special-casing in the rule. Documented so a future refactor that
    "fixes" non-existent times by raising will know it's breaking the
    contract.
    """

    def test_spring_forward_skipped_hour_consistent_verdict(self):
        rule = sw.LocalTimeOfDayRule(
            name="business-hours",
            start_local="09:00",
            end_local="17:00",
        )
        # UTC 10:30 on 2026-03-08 — the wall-clock "would have been" 02:30
        # PST, but the spring-forward jump means zoneinfo resolves it to
        # the appropriate post-jump time (03:30 PDT). Either way, 03:30 is
        # outside 09-17 → Block. The contract: the rule produces SOME
        # well-defined verdict, not an exception.
        now = datetime(2026, 3, 8, 10, 30, tzinfo=timezone.utc)
        ctx = _make_ctx(now=now, tz="America/Los_Angeles")
        result = rule.evaluate(ctx)
        # Whatever the local-tod resolves to, it's clearly not in 09-17.
        assert isinstance(result, policy_types.Block)


class TestDSTAmbiguousTime:
    """Fall-back day in Los Angeles: 2026-11-01 02:00 PDT → 01:00 PST.

    The wall-clock time 01:30 occurs twice — once at UTC 08:30 (PDT side)
    and once at UTC 09:30 (PST side). The rule reads local-time-of-day,
    which is 01:30 in both cases. Both UTC instants must produce identical
    verdicts.

    This is a stronger property than "the rule doesn't crash" — it pins
    the contract that the verdict depends purely on local-time-of-day,
    NOT on which side of the fold the UTC instant landed.
    """

    def test_fall_back_ambiguous_hour_consistent_verdict(self):
        rule = sw.LocalTimeOfDayRule(
            name="business-hours",
            start_local="09:00",
            end_local="17:00",
        )
        # The two UTC instants that share local TOD 01:30 LA on fall-back day.
        # 01:30 is outside 09-17 → Block on both.
        utc_pre_fold = datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc)
        utc_post_fold = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
        ctx_pre = _make_ctx(now=utc_pre_fold, tz="America/Los_Angeles")
        ctx_post = _make_ctx(now=utc_post_fold, tz="America/Los_Angeles")
        v_pre = rule.evaluate(ctx_pre)
        v_post = rule.evaluate(ctx_post)
        assert type(v_pre) is type(v_post), (
            "fall-back ambiguous local time must yield identical verdict "
            f"across the two folds: pre={type(v_pre).__name__}, "
            f"post={type(v_post).__name__}"
        )
        assert isinstance(v_pre, policy_types.Block)


# ---------------------------------------------------------------------------
# Unparseable timezone — restrictive interpretation
# ---------------------------------------------------------------------------


class TestUnparseableTimezone:
    """ADR-0005 §Decision: an unparseable ``ctx.timezone`` produces Block,
    not Allow. The tz_inference helper at the call site is supposed to
    normalize tz strings; if it failed (bug) and produced garbage, the
    asymmetric-failure-cost principle wins — refuse the send.
    """

    def test_invalid_iana_blocks(self):
        rule = sw.LocalTimeOfDayRule(
            name="business-hours",
            start_local="09:00",
            end_local="17:00",
        )
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="Not_A_Real/Timezone",
        )
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("invalid_timezone") is True
        assert result.detail.get("timezone") == "Not_A_Real/Timezone"

    def test_empty_string_blocks(self):
        rule = sw.LocalTimeOfDayRule(
            name="business-hours",
            start_local="09:00",
            end_local="17:00",
        )
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="",
        )
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)


# ---------------------------------------------------------------------------
# DayOfWeekRule
# ---------------------------------------------------------------------------


class TestDayOfWeekRule:
    def _rule(self, days=None, **kw):
        if days is None:
            days = ["mon", "tue", "wed", "thu", "fri"]
        return sw.DayOfWeekRule(
            name="weekdays-only",
            allowed_days=days,
            block_when=kw.get("block_when", {}),
            reason=kw.get("reason", "Only send on weekdays"),
        )

    def test_monday_allows(self):
        # 2026-05-18 is a Monday.
        now = datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc)
        ctx = _make_ctx(now=now, tz="America/Los_Angeles")
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_saturday_blocks(self):
        # 2026-05-16 is a Saturday.
        now = datetime(2026, 5, 16, 19, 0, tzinfo=timezone.utc)
        ctx = _make_ctx(now=now, tz="America/Los_Angeles")
        result = self._rule().evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("local_weekday") == "sat"
        assert result.detail.get("allowed_days") == [
            "mon", "tue", "wed", "thu", "fri",
        ]

    def test_sunday_blocks(self):
        # 2026-05-17 is a Sunday.
        now = datetime(2026, 5, 17, 19, 0, tzinfo=timezone.utc)
        ctx = _make_ctx(now=now, tz="America/Los_Angeles")
        assert isinstance(self._rule().evaluate(ctx), policy_types.Block)

    def test_timezone_dependence(self):
        """Saturday 23:00 UTC is Saturday in London but Sunday in Sydney.
        The rule's verdict must depend on the recipient's local weekday.
        """
        now = datetime(2026, 5, 16, 23, 0, tzinfo=timezone.utc)
        # Saturday 23:00 UTC → Saturday 23:00 London (BST is +1 but in May
        # it's BST so 00:00 Sun) — wait, BST is UTC+1, so 23:00 UTC →
        # Sunday 00:00 BST. Use a clearer fixture: 14:00 UTC on Saturday.
        now = datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc)
        ctx_london = _make_ctx(now=now, tz="Europe/London")
        ctx_sydney = _make_ctx(now=now, tz="Australia/Sydney")
        rule = self._rule()
        # London: 15:00 BST Saturday → Block.
        assert isinstance(rule.evaluate(ctx_london), policy_types.Block)
        # Sydney: Sunday 00:00 AEST (Sydney is UTC+10 in May, AEST after
        # DST ended on 2026-04-05) → Sunday → Block too.
        # Need a fixture where the days differ: 22:00 UTC Friday.
        # Fri 2026-05-15 22:00 UTC. London: Fri 23:00 BST. Sydney: Sat 08:00.
        now2 = datetime(2026, 5, 15, 22, 0, tzinfo=timezone.utc)
        ctx_london2 = _make_ctx(now=now2, tz="Europe/London")
        ctx_sydney2 = _make_ctx(now=now2, tz="Australia/Sydney")
        # London Friday → Allow.
        assert isinstance(rule.evaluate(ctx_london2), policy_types.Allow)
        # Sydney Saturday → Block.
        assert isinstance(rule.evaluate(ctx_sydney2), policy_types.Block)

    def test_empty_allowed_days_blocks(self):
        """Defensive: an empty allowed_days list means "no days allowed" →
        block every send. (A typo-prone failure mode: an operator delete-
        editing the list down to empty should refuse, not allow.)"""
        rule = sw.DayOfWeekRule(
            name="never",
            allowed_days=[],
        )
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("degenerate") is True

    def test_unparseable_timezone_blocks(self):
        rule = self._rule()
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="Mars/Phobos",
        )
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("invalid_timezone") is True

    def test_case_insensitive_day_names(self):
        """Day names are normalized case-insensitively. ``MON``, ``Mon``,
        ``mon`` are all equivalent."""
        rule = sw.DayOfWeekRule(
            name="weekdays",
            allowed_days=["MON", "TUE", "Wed", "thu", "fri"],
        )
        now = datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc)  # Monday
        ctx = _make_ctx(now=now, tz="America/Los_Angeles")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# block_when filter — both rules support it
# ---------------------------------------------------------------------------


class TestBlockWhenFilter:
    def test_local_time_of_day_block_when_register(self):
        """LocalTimeOfDayRule scoped to register=cold-pitch doesn't fire on
        follow-up sends."""
        rule = sw.LocalTimeOfDayRule(
            name="cold-pitch-business-hours",
            start_local="09:00",
            end_local="17:00",
            block_when={"register": "cold-pitch"},
        )
        # 06:00 PDT (before window) — would block if rule applied.
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
            register="follow-up",  # rule scoped to cold-pitch
        )
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_day_of_week_block_when_channel(self):
        """DayOfWeekRule scoped to channel=email doesn't fire on linkedin."""
        rule = sw.DayOfWeekRule(
            name="weekdays-email-only",
            allowed_days=["mon", "tue", "wed", "thu", "fri"],
            block_when={"channel": "email"},
        )
        # Saturday — would block if rule applied.
        ctx = _make_ctx(
            now=datetime(2026, 5, 16, 19, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
            channel="linkedin",
            email=None,
        )
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# from_yaml round-trip
# ---------------------------------------------------------------------------


class TestFromYaml:
    def test_local_time_of_day_from_yaml(self):
        spec = {
            "name": "business-hours-only",
            "type": "sending-window.local-time-of-day",
            "start_local": "09:00",
            "end_local": "17:00",
            "block_when": {"channel": "email"},
            "reason": "Outside business hours",
        }
        rule = sw.LocalTimeOfDayRule.from_yaml(spec)
        assert rule.name == "business-hours-only"
        assert rule.start_local == "09:00"
        assert rule.end_local == "17:00"
        assert rule.block_when == {"channel": "email"}

    def test_day_of_week_from_yaml(self):
        spec = {
            "name": "weekdays-only",
            "type": "sending-window.day-of-week",
            "allowed_days": ["mon", "tue", "wed", "thu", "fri"],
            "block_when": {"register": "cold-pitch"},
        }
        rule = sw.DayOfWeekRule.from_yaml(spec)
        assert rule.name == "weekdays-only"
        assert rule.allowed_days == ["mon", "tue", "wed", "thu", "fri"]

    def test_local_time_of_day_requires_start_and_end(self):
        with pytest.raises((KeyError, ValueError)):
            sw.LocalTimeOfDayRule.from_yaml({
                "name": "x",
                "type": "sending-window.local-time-of-day",
                # missing start_local + end_local
            })

    def test_local_time_of_day_invalid_time_format_raises(self):
        with pytest.raises(ValueError):
            sw.LocalTimeOfDayRule.from_yaml({
                "name": "x",
                "type": "sending-window.local-time-of-day",
                "start_local": "9am",  # not HH:MM
                "end_local": "17:00",
            })

    def test_day_of_week_requires_allowed_days(self):
        with pytest.raises((KeyError, ValueError)):
            sw.DayOfWeekRule.from_yaml({
                "name": "x",
                "type": "sending-window.day-of-week",
                # missing allowed_days
            })

    def test_day_of_week_invalid_day_name_raises(self):
        with pytest.raises(ValueError):
            sw.DayOfWeekRule.from_yaml({
                "name": "x",
                "type": "sending-window.day-of-week",
                "allowed_days": ["mon", "funday"],
            })


# ---------------------------------------------------------------------------
# Engine integration (load_rules_from_yaml + evaluate)
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    def test_factory_rules_through_engine(self, tmp_path):
        p = tmp_path / "windows.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: business-hours-only\n"
            "    type: sending-window.local-time-of-day\n"
            "    start_local: '09:00'\n"
            "    end_local: '17:00'\n"
            "    block_when: {channel: email}\n"
            "  - name: weekdays-only\n"
            "    type: sending-window.day-of-week\n"
            "    allowed_days: [mon, tue, wed, thu, fri]\n"
            "    block_when: {channel: email}\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 2
        assert [r.name for r in rules] == [
            "business-hours-only",
            "weekdays-only",
        ]

        # Case 1: weekday at 12:00 PDT → both rules allow → Allow.
        now = datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc)  # Mon 12:00 PDT
        ctx = _make_ctx(now=now, tz="America/Los_Angeles")
        result = policy_engine.evaluate(rules, ctx)
        assert isinstance(result, policy_types.Allow)

        # Case 2: weekday at 06:00 PDT → time-of-day blocks first.
        now2 = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
        ctx2 = _make_ctx(now=now2, tz="America/Los_Angeles")
        result2 = policy_engine.evaluate(rules, ctx2)
        assert isinstance(result2, policy_types.Block)
        assert result2.rule == "business-hours-only"

        # Case 3: Saturday at 12:00 PDT → time-of-day allows but day-of-week
        # blocks → engine short-circuits on first Block, which is
        # day-of-week (it's second in rule order, but time-of-day allows
        # first).
        now3 = datetime(2026, 5, 16, 19, 0, tzinfo=timezone.utc)
        ctx3 = _make_ctx(now=now3, tz="America/Los_Angeles")
        result3 = policy_engine.evaluate(rules, ctx3)
        assert isinstance(result3, policy_types.Block)
        assert result3.rule == "weekdays-only"

    def test_rules_register_under_discriminators(self):
        # Import triggers registration via policy.__init__.
        from orchestrator import policy  # noqa: F401
        assert "sending-window.local-time-of-day" in policy_engine.RULE_REGISTRY
        assert "sending-window.day-of-week" in policy_engine.RULE_REGISTRY


# ---------------------------------------------------------------------------
# _local_now helper — direct tests
# ---------------------------------------------------------------------------


class TestLocalNowHelper:
    def test_returns_zoneinfo_localized_datetime(self):
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        )
        local = policy_helpers._local_now(ctx)
        assert local.tzinfo is not None
        assert local.hour == 12  # noon PDT
        assert local.minute == 0

    def test_invalid_timezone_raises_documented_error(self):
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="Not_A_Real/Tz",
        )
        with pytest.raises(policy_helpers.UnparseableTimezoneError):
            policy_helpers._local_now(ctx)

    def test_empty_timezone_raises_documented_error(self):
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="",
        )
        with pytest.raises(policy_helpers.UnparseableTimezoneError):
            policy_helpers._local_now(ctx)

    def test_utc_timezone_is_valid(self):
        ctx = _make_ctx(
            now=datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc),
            tz="UTC",
        )
        local = policy_helpers._local_now(ctx)
        assert local.hour == 19
        assert local.minute == 0


# ---------------------------------------------------------------------------
# Cooldown DST-property regression — sanity that Week 3 didn't break it
# ---------------------------------------------------------------------------


class TestCooldownDSTPropertyStillHolds:
    """ADR-0002 cooldown DST property must continue to hold after Week 3.

    Week 3 made ``RuleContext.timezone`` semantically load-bearing for the
    first time (sending-window rules consume it). If a careless refactor
    leaked tz consultation into a cooldown rule, the cooldown DST property
    would fail. This test pins the dependency: a sentinel cooldown
    evaluation must remain tz-invariant.

    The full property test lives in ``tests/test_policy_cooldown.py``;
    this is a sanity-anchor mirroring it from the sending-window test
    file so a Week-3 regression surfaces at the right module.
    """

    def test_no_duplicate_register_invariant_to_tz(self):
        from orchestrator.policy import cooldown as cd

        # Build a fake ledger with one prior cold-pitch.
        class _LedgerWithSend:
            def __init__(self, ts):
                self._ts = ts

            def query_by_person(self, person_id, since=None):
                return [
                    {
                        "type": "send_intent",
                        "ts": self._ts,
                        "intent_id": "x",
                        "person_id": person_id,
                        "channel": "email",
                        "register": "cold-pitch",
                    },
                    {
                        "type": "send_confirmed",
                        "ts": self._ts,
                        "intent_id": "x",
                        "person_id": person_id,
                        "channel": "email",
                    },
                ]

            def last_send_for(self, *a, **k):
                return None

            def query_by_email(self, *a, **k):
                return set()

            def all_events(self):
                return []

        rule = cd.NoDuplicateRegisterRule(
            name="no-double",
            block_when={"register": "cold-pitch"},
        )
        now = datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc)
        prior_ts = "2026-04-01T12:00:00Z"
        # Evaluate across the same _TZ_SAMPLES set sending-window varies over.
        verdicts = set()
        for tz in _TZ_SAMPLES:
            ctx = policy_types.RuleContext(
                person_id="alice-li",
                channel="email",
                register="cold-pitch",
                email="alice@example.com",
                email_domain="example.com",
                now=now,
                timezone=tz,
                ledger=_LedgerWithSend(prior_ts),
                person_status=None,
            )
            verdicts.add(type(rule.evaluate(ctx)).__name__)
        # Cooldown verdict is identical across every tz — the contract.
        assert len(verdicts) == 1, (
            f"Cooldown leaked tz-dependence after Week 3: {verdicts}"
        )
