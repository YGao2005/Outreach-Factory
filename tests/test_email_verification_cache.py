"""Tests for orchestrator/email_verification_cache.py — Pillar E Week 4-5.

Covers the email-verification cache primitive per ADR-0034 D154-D159:
:class:`EmailVerificationCacheResult` dataclass invariants,
:func:`lookup_cache` happy paths + TTL boundaries + ledger-error
fallback, event-payload factory contract, the integration shape with
:func:`enrich_emails.verify_with_reoon` (cache-hit / cache-miss
dispatch via the wrap), the deterministic-clock pin via the ``now``
parameter (per ADR-0031 D140 precedent), and the module-level
constants the cross-pillar audit pins (per D157 + D146 channel-on-
every-event invariant).

Run:
    cd /Users/yang/code/outreach-factory && pytest tests/test_email_verification_cache.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator import email_verification_cache, enrich_emails
from orchestrator import ledger as _ledger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def led(tmp_path: Path) -> _ledger.Ledger:
    """Per-test isolated ledger directory.

    Mirrors :file:`tests/test_enrichment_costs.py`'s fixture so the
    cache primitive's tests + the cost-emission tests use compatible
    setups (the cache primitive's substrate IS the cost-incurred
    event stream per ADR-0034 D156).
    """
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    return _ledger.Ledger(ledger_dir)


def _append_reoon_cost(
    led: _ledger.Ledger,
    *,
    email: str,
    response: dict,
    ts: str,
    person_id: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Append a Reoon cost_incurred event with the Pillar-E-Week-4-5
    extended shape (carries ``email`` + ``verification_response`` per
    ADR-0034 D156 — the cache substrate)."""
    return led.append({
        "type": "cost_incurred",
        "source": "reoon",
        "amount_usd": 0.005,
        "units": 1,
        "model_or_endpoint": "verifier/power",
        "person_id": person_id,
        "run_id": run_id,
        "email": email,
        "verification_response": response,
        "ts": ts,
    })


def _iso(dt: datetime) -> str:
    """Format datetime as the ledger-canonical ISO string (Z-suffixed UTC)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------------------------------------------------------------------------
# EmailVerificationCacheResult invariants — ADR-0034 D155
# ---------------------------------------------------------------------------


class TestEmailVerificationCacheResultInvariants:
    """ADR-0034 D155 — the dataclass's status + helper-property contract."""

    def test_miss_carries_no_cached_data(self):
        result = email_verification_cache.EmailVerificationCacheResult(
            is_cache_hit=False, email="dylan@example.com",
        )
        assert result.is_cache_hit is False
        assert result.cached_response is None
        assert result.cached_at is None
        assert result.cache_age_days is None
        assert result.cached_outcome is None

    def test_hit_requires_cached_response(self):
        with pytest.raises(ValueError, match="requires cached_response"):
            email_verification_cache.EmailVerificationCacheResult(
                is_cache_hit=True,
                email="dylan@example.com",
                cached_at="2026-05-01T10:00:00.000Z",
                # missing cached_response
            )

    def test_hit_requires_cached_at(self):
        with pytest.raises(ValueError, match="requires cached_at"):
            email_verification_cache.EmailVerificationCacheResult(
                is_cache_hit=True,
                email="dylan@example.com",
                cached_response={"status": "safe"},
                # missing cached_at
            )

    def test_miss_must_not_carry_cached_response(self):
        with pytest.raises(ValueError, match="must NOT carry cached_response"):
            email_verification_cache.EmailVerificationCacheResult(
                is_cache_hit=False,
                email="dylan@example.com",
                cached_response={"status": "safe"},
            )

    def test_hit_full_invariants(self):
        result = email_verification_cache.EmailVerificationCacheResult(
            is_cache_hit=True,
            email="dylan@example.com",
            cached_response={"status": "safe", "overall_score": 95},
            cached_at="2026-05-01T10:00:00.000Z",
            cache_age_days=23,
            cached_person_id="dylan-txa",
        )
        assert result.is_cache_hit is True
        assert result.cached_outcome == "safe"
        assert result.cached_response == {"status": "safe", "overall_score": 95}
        assert result.cache_age_days == 23
        assert result.cached_person_id == "dylan-txa"

    def test_cached_outcome_derives_from_cached_response_status(self):
        result = email_verification_cache.EmailVerificationCacheResult(
            is_cache_hit=True,
            email="dylan@example.com",
            cached_response={"status": "catch_all", "overall_score": 60},
            cached_at="2026-05-01T10:00:00.000Z",
            cache_age_days=5,
        )
        assert result.cached_outcome == "catch_all"

    def test_cached_outcome_handles_missing_status_field(self):
        """A malformed cached_response (no status key) yields None."""
        result = email_verification_cache.EmailVerificationCacheResult(
            is_cache_hit=True,
            email="dylan@example.com",
            cached_response={"overall_score": 95},  # no status key
            cached_at="2026-05-01T10:00:00.000Z",
            cache_age_days=5,
        )
        assert result.cached_outcome is None


# ---------------------------------------------------------------------------
# lookup_cache happy paths — ADR-0034 D156
# ---------------------------------------------------------------------------


class TestLookupCacheHappyPaths:
    """ADR-0034 D156 — the cache substrate is the ledger event stream."""

    def test_no_ledger_returns_miss(self):
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=None,
        )
        assert result.is_cache_hit is False
        assert result.email == "dylan@example.com"

    def test_empty_ledger_returns_miss(self, led):
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led,
        )
        assert result.is_cache_hit is False
        assert result.cached_response is None

    def test_one_matching_event_within_ttl_returns_hit(self, led):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe", "overall_score": 95},
            ts=ts,
            person_id="dylan-txa",
        )
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is True
        assert result.cached_response == {"status": "safe", "overall_score": 95}
        assert result.cached_outcome == "safe"
        assert result.cached_at == ts
        assert result.cache_age_days == 5
        assert result.cached_person_id == "dylan-txa"

    def test_one_matching_event_outside_ttl_returns_miss(self, led):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=31))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe", "overall_score": 95},
            ts=ts,
        )
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is False

    def test_two_matching_events_returns_most_recent(self, led):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        old_ts = _iso(now - timedelta(days=20))
        new_ts = _iso(now - timedelta(days=3))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "catch_all", "overall_score": 60},
            ts=old_ts,
        )
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe", "overall_score": 95},
            ts=new_ts,
        )
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is True
        assert result.cached_outcome == "safe"  # most-recent wins
        assert result.cached_at == new_ts
        assert result.cache_age_days == 3

    def test_lookup_is_case_insensitive_on_email(self, led):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        _append_reoon_cost(
            led,
            email="Dylan@Example.com",
            response={"status": "safe"},
            ts=ts,
        )
        # Lookup with lower-cased email finds the upper-cased event.
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is True

    def test_lookup_filters_by_email_not_other_emails(self, led):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        _append_reoon_cost(
            led,
            email="other@example.com",
            response={"status": "safe"},
            ts=ts,
        )
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is False

    def test_lookup_filters_by_source_reoon_only(self, led):
        """A cost_incurred event from a non-Reoon source for the same
        email does NOT count as a cache hit (the cache is Reoon-
        specific per ADR-0034 D156)."""
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        led.append({
            "type": "cost_incurred",
            "source": "apollo",  # NOT reoon
            "amount_usd": 0.10,
            "units": 1,
            "model_or_endpoint": "people_enrich",
            "person_id": "dylan-txa",
            "email": "dylan@example.com",
            "verification_response": {"status": "safe"},
            "ts": ts,
        })
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is False

    def test_lookup_filters_by_type_cost_incurred_only(self, led):
        """A non-cost_incurred event with email + verification_response
        does NOT count (the cache filters by type per ADR-0034 D156)."""
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        led.append({
            "type": "discovery_dedup_hit",  # NOT cost_incurred
            "person_id": "dylan-txa",
            "email": "dylan@example.com",
            "verification_response": {"status": "safe"},
            "ts": ts,
            "channel": "none",
            "_emitted_by": "discovery_dedup",
        })
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is False

    def test_pre_pillar_e_week_4_cost_event_without_email_is_treated_as_miss(
        self, led,
    ):
        """A pre-Week-4-5 cost_incurred event (no email field) is
        invisible to the cache. Existing operators see no historical
        cache; the cache populates from the next Reoon call forward
        per ADR-0034 §Existing-operator seed."""
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        led.append({
            "type": "cost_incurred",
            "source": "reoon",
            "amount_usd": 0.005,
            "units": 1,
            "model_or_endpoint": "verifier/power",
            "person_id": "dylan-txa",
            # NO email; NO verification_response (pre-Week-4-5 shape)
            "ts": ts,
        })
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is False

    def test_cost_event_with_email_but_no_response_is_treated_as_miss(
        self, led,
    ):
        """A malformed cost event (email present but verification_response
        missing) yields a cache miss — the caller falls through to
        Reoon. The malformed shape would otherwise leave the cache
        with no payload to return."""
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        led.append({
            "type": "cost_incurred",
            "source": "reoon",
            "amount_usd": 0.005,
            "units": 1,
            "person_id": "dylan-txa",
            "email": "dylan@example.com",
            # NO verification_response field
            "ts": ts,
        })
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is False

    def test_empty_email_returns_miss(self, led):
        result = email_verification_cache.lookup_cache(
            "", ledger=led,
        )
        assert result.is_cache_hit is False


# ---------------------------------------------------------------------------
# TTL boundary — ADR-0034 D157
# ---------------------------------------------------------------------------


class TestTTLBoundary:
    """ADR-0034 D157 — the 30-day TTL is the operator-pinned default."""

    def test_default_ttl_is_30_days(self):
        assert email_verification_cache.DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS == 30

    def test_event_at_exactly_ttl_boundary_is_hit(self, led):
        """An event at exactly `now - TTL_DAYS` is a HIT (inclusive
        lower bound — matches the cooldown / budget rule convention
        per ADR-0002 + ADR-0006)."""
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        boundary_ts = _iso(now - timedelta(days=30))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe"},
            ts=boundary_ts,
        )
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is True

    def test_event_one_second_inside_ttl_is_hit(self, led):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        inside_ts = _iso(now - timedelta(days=30) + timedelta(seconds=1))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe"},
            ts=inside_ts,
        )
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is True

    def test_event_one_second_outside_ttl_is_miss(self, led):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        outside_ts = _iso(now - timedelta(days=30) - timedelta(seconds=1))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe"},
            ts=outside_ts,
        )
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now,
        )
        assert result.is_cache_hit is False

    def test_custom_ttl_overrides_default(self, led):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=14))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe"},
            ts=ts,
        )
        # 7-day TTL — the 14-day-old event is outside.
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now, ttl_days=7,
        )
        assert result.is_cache_hit is False
        # 30-day TTL — the same event is inside.
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=now, ttl_days=30,
        )
        assert result.is_cache_hit is True


# ---------------------------------------------------------------------------
# Deterministic clock — ADR-0031 D140 precedent
# ---------------------------------------------------------------------------


class TestDeterministicClock:
    """The `now` parameter pins the clock for test reproducibility.

    Per ADR-0031 D140 (Pillar D Week 12's funnel CLI `--since`
    deterministic-clock pattern). The cache primitive is the SECOND
    consumer of the pattern after the funnel CLI; ADR-0034 may
    extract a shared helper or defer per RETRO-pillar-d.md item-8.
    """

    def test_now_parameter_pins_lookup_clock(self, led):
        # Append an event with a specific timestamp.
        anchor = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(anchor - timedelta(days=10))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe"},
            ts=ts,
        )
        # First call with `now=anchor` — event is 10 days old → HIT.
        r1 = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=anchor,
        )
        assert r1.is_cache_hit is True
        assert r1.cache_age_days == 10
        # Second call with `now=anchor + 25 days` — event is 35 days
        # old → MISS (outside default TTL).
        r2 = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led, now=anchor + timedelta(days=25),
        )
        assert r2.is_cache_hit is False

    def test_default_now_uses_wall_clock(self, led):
        """When `now` is not provided, the lookup uses
        ``datetime.now(timezone.utc)`` — verified by stamping an event
        in the present-time window and confirming hit."""
        now = datetime.now(timezone.utc)
        ts = _iso(now - timedelta(days=2))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe"},
            ts=ts,
        )
        # No `now` kwarg — relies on wall clock.
        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=led,
        )
        assert result.is_cache_hit is True


# ---------------------------------------------------------------------------
# build_email_verification_cache_hit_payload — ADR-0034 D155
# ---------------------------------------------------------------------------


class TestBuildEmailVerificationCacheHitPayload:
    """ADR-0034 D155 — the event-payload factory shape contract."""

    def _hit_result(self) -> email_verification_cache.EmailVerificationCacheResult:
        return email_verification_cache.EmailVerificationCacheResult(
            is_cache_hit=True,
            email="dylan@example.com",
            cached_response={"status": "safe", "overall_score": 95},
            cached_at="2026-05-01T10:00:00.000Z",
            cache_age_days=23,
            cached_person_id="dylan-txa",
        )

    def test_payload_type_is_email_verification_cache_hit(self):
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert payload["type"] == "email_verification_cache_hit"

    def test_payload_carries_email(self):
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert payload["email"] == "dylan@example.com"

    def test_payload_carries_cached_result_status_string(self):
        """Per D155 the event's `cached_result` field is the STATUS
        STRING (not the full response dict — the dict is preserved on
        the originating cost_incurred event's `verification_response`)."""
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert payload["cached_result"] == "safe"

    def test_payload_carries_cached_at_iso_timestamp(self):
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert payload["cached_at"] == "2026-05-01T10:00:00.000Z"

    def test_payload_carries_cache_age_days(self):
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert payload["cache_age_days"] == 23

    def test_payload_carries_channel_email_per_d146(self):
        """Per ADR-0032 D146's channel-on-every-event invariant +
        the design recommendation in HANDOFF-pillar-e-week-4.md
        (cache event is email-specific; mirrors Pillar D Week 1's
        Pass B `channel: email` stamp)."""
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert payload["channel"] == "email"

    def test_payload_carries_emitted_by_marker(self):
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert payload["_emitted_by"] == "email_verification_cache"

    def test_payload_defaults_person_id_from_cached_person_id(self):
        """When the caller does not pass `person_id`, the payload
        carries the cached event's person_id (the original
        verification's person_id is the natural attribution)."""
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert payload["person_id"] == "dylan-txa"

    def test_payload_caller_can_override_person_id(self):
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com", person_id="different-pid",
        )
        assert payload["person_id"] == "different-pid"

    def test_payload_person_id_none_when_no_cached_or_caller_value(self):
        """When the cached event has no person_id AND the caller does
        not override, the payload carries `person_id: None` (the
        explicit None makes the absence operator-visible per the
        Pillar A I5 convention)."""
        result = email_verification_cache.EmailVerificationCacheResult(
            is_cache_hit=True,
            email="dylan@example.com",
            cached_response={"status": "safe"},
            cached_at="2026-05-01T10:00:00.000Z",
            cache_age_days=5,
            # cached_person_id defaults to None
        )
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            result, "dylan@example.com",
        )
        assert payload["person_id"] is None

    def test_payload_rejects_cache_miss_result(self):
        miss = email_verification_cache.EmailVerificationCacheResult(
            is_cache_hit=False, email="dylan@example.com",
        )
        with pytest.raises(ValueError, match="requires is_cache_hit=True"):
            email_verification_cache.build_email_verification_cache_hit_payload(
                miss, "dylan@example.com",
            )

    def test_payload_field_set_is_exactly_pinned(self):
        """Strict shape contract — Pillar G dashboards consume these
        events; an unexpected extra field would surface as an unknown
        column. The set of keys is closed."""
        payload = email_verification_cache.build_email_verification_cache_hit_payload(
            self._hit_result(), "dylan@example.com",
        )
        assert set(payload.keys()) == {
            "type",
            "person_id",
            "email",
            "cached_result",
            "cached_at",
            "cache_age_days",
            "channel",
            "_emitted_by",
        }


# ---------------------------------------------------------------------------
# Module constants — ADR-0034 D155 + D157
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """ADR-0034 D155 + D157 — module-level reservations the cross-pillar
    audit pins as single source of truth for downstream consumers."""

    def test_ttl_days_constant_is_thirty(self):
        assert email_verification_cache.DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS == 30

    def test_emitted_by_marker_reserved(self):
        assert email_verification_cache.EMITTED_BY == "email_verification_cache"

    def test_channel_value_is_email_per_d146(self):
        """The cache event carries `channel: "email"` — the cache hit
        IS email-channel-specific (the lookup key is an email; the
        cached outcome is Reoon's email-verification verdict).
        Mirrors Pillar D Week 1's `reply_received` events stamping
        `channel: email` even though Pass B's emit context is
        unambiguously email — the explicit stamp makes the absence
        operator-visible to Pillar G dashboards filtered by channel."""
        assert email_verification_cache.CHANNEL_VALUE == "email"


# ---------------------------------------------------------------------------
# Ledger-error fallback
# ---------------------------------------------------------------------------


class TestLedgerErrorFallback:
    """The cache primitive is FAST-PATH; an unreadable ledger MUST NOT
    block the caller's Reoon call. Returns miss + writes a warning."""

    def test_broken_ledger_returns_miss(self, capsys):
        class _BrokenLedger:
            def all_events(self):
                raise OSError("disk full")

        result = email_verification_cache.lookup_cache(
            "dylan@example.com", ledger=_BrokenLedger(),
        )
        assert result.is_cache_hit is False
        captured = capsys.readouterr()
        assert "lookup_cache" in captured.err or "ledger walk" in captured.err


# ---------------------------------------------------------------------------
# Integration smoke — verify_with_reoon dispatches on cache hit vs miss
# ---------------------------------------------------------------------------


class TestVerifyWithReoonCacheIntegration:
    """ADR-0034 D158 — the per-call-site integration in
    ``orchestrator/enrich_emails.py``. Verifies that the wrap inside
    `verify_with_reoon` correctly dispatches on cache hit vs miss:
    cache hit short-circuits the Reoon API call + emits the cache_hit
    event + returns the cached response; cache miss falls through to
    the existing Reoon HTTP path + emits cost_incurred unchanged."""

    def test_cache_hit_short_circuits_reoon_api_call(self, led, monkeypatch):
        # Seed the ledger with a recent Reoon cost event.
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe", "overall_score": 95},
            ts=ts,
            person_id="dylan-txa",
        )

        # Mock the HTTP urlopen to detect any unexpected Reoon call.
        called = {"count": 0}
        def _no_http(*args, **kwargs):
            called["count"] += 1
            raise AssertionError("Cache hit should short-circuit HTTP call")
        monkeypatch.setattr(
            "urllib.request.urlopen", _no_http,
        )

        # Use the deterministic-clock pin via the patch.
        with patch.object(
            email_verification_cache, "datetime",
            wraps=email_verification_cache.datetime,
        ) as mock_dt:
            mock_dt.now.return_value = now
            result = enrich_emails.verify_with_reoon(
                "dylan@example.com", "fake-api-key",
                led=led, person_id="dylan-txa",
            )

        assert called["count"] == 0  # No HTTP call.
        assert result == {"status": "safe", "overall_score": 95}

    def test_cache_hit_emits_cache_hit_event_not_cost_incurred(
        self, led, monkeypatch,
    ):
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        ts = _iso(now - timedelta(days=5))
        _append_reoon_cost(
            led,
            email="dylan@example.com",
            response={"status": "safe", "overall_score": 95},
            ts=ts,
            person_id="dylan-txa",
        )

        # Stub urlopen so the test won't ever hit real network.
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(
                AssertionError("Cache hit should short-circuit HTTP"),
            ),
        )

        with patch.object(
            email_verification_cache, "datetime",
            wraps=email_verification_cache.datetime,
        ) as mock_dt:
            mock_dt.now.return_value = now
            enrich_emails.verify_with_reoon(
                "dylan@example.com", "fake-api-key",
                led=led, person_id="dylan-txa",
            )

        events = [e for e in led.all_events()]
        cache_hits = [e for e in events
                      if e.get("type") == "email_verification_cache_hit"]
        new_cost_incurred = [
            e for e in events
            if e.get("type") == "cost_incurred"
            and e.get("ts") != ts  # exclude the seed event
        ]
        assert len(cache_hits) == 1, (
            f"Expected exactly ONE email_verification_cache_hit; "
            f"got {len(cache_hits)}"
        )
        assert len(new_cost_incurred) == 0, (
            "Cache hit MUST NOT emit a new cost_incurred event; "
            f"got {len(new_cost_incurred)} new cost events"
        )
        evt = cache_hits[0]
        assert evt["email"] == "dylan@example.com"
        assert evt["cached_result"] == "safe"
        assert evt["channel"] == "email"
        assert evt["_emitted_by"] == "email_verification_cache"
        assert evt["person_id"] == "dylan-txa"

    def test_cache_miss_falls_through_to_reoon_http(self, led, monkeypatch):
        # Empty ledger — no cached entry.
        # Mock urlopen to return a synthetic Reoon-shaped response.
        class _MockResp:
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *args):
                return False
            def read(self_inner):
                import json as _json
                return _json.dumps(
                    {"status": "safe", "overall_score": 88},
                ).encode("utf-8")

        called = {"count": 0}
        def _mock_open(*args, **kwargs):
            called["count"] += 1
            return _MockResp()
        monkeypatch.setattr("urllib.request.urlopen", _mock_open)

        result = enrich_emails.verify_with_reoon(
            "dylan@example.com", "fake-api-key",
            led=led, person_id="dylan-txa", run_id="enrich-test",
        )

        assert called["count"] == 1  # HTTP call DID happen.
        assert result == {"status": "safe", "overall_score": 88}

        events = [e for e in led.all_events()]
        cache_hits = [e for e in events
                      if e.get("type") == "email_verification_cache_hit"]
        cost_events = [e for e in events
                       if e.get("type") == "cost_incurred"
                       and e.get("source") == "reoon"]
        assert len(cache_hits) == 0  # No cache hit emit on miss.
        assert len(cost_events) == 1, (
            "Cache miss MUST emit a cost_incurred event per ADR-0006 "
            "(unchanged from pre-Week-4-5 behavior)"
        )
        ev = cost_events[0]
        assert ev["email"] == "dylan@example.com"
        assert ev["verification_response"] == {
            "status": "safe", "overall_score": 88,
        }

    def test_no_led_arg_preserves_legacy_behavior(self, monkeypatch):
        """The existing call-site `verify_with_reoon(email, api_key)`
        without the new kwargs preserves pre-Week-4-5 behavior — no
        cache lookup; no cost emit (the legacy caller emits cost
        separately via emit_reoon_cost_event). Backwards compatible."""
        class _MockResp:
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *args):
                return False
            def read(self_inner):
                import json as _json
                return _json.dumps({"status": "safe"}).encode("utf-8")
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda *a, **kw: _MockResp(),
        )

        # No led / person_id / run_id kwargs — legacy two-arg signature.
        result = enrich_emails.verify_with_reoon(
            "dylan@example.com", "fake-api-key",
        )
        assert result == {"status": "safe"}

    def test_round_trip_second_call_hits_cache(self, led, monkeypatch):
        """End-to-end: first call misses cache → calls Reoon → emits
        cost_incurred. Second call within TTL hits cache → emits
        cache_hit + skips Reoon. The full cache cycle is exercised."""
        class _MockResp:
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *args):
                return False
            def read(self_inner):
                import json as _json
                return _json.dumps(
                    {"status": "safe", "overall_score": 95},
                ).encode("utf-8")

        http_count = {"n": 0}
        def _mock_open(*args, **kwargs):
            http_count["n"] += 1
            return _MockResp()
        monkeypatch.setattr("urllib.request.urlopen", _mock_open)

        # First call — cache miss → HTTP call.
        r1 = enrich_emails.verify_with_reoon(
            "dylan@example.com", "fake-api-key",
            led=led, person_id="dylan-txa", run_id="r1",
        )
        assert http_count["n"] == 1

        # Second call — cache hit → no HTTP call.
        r2 = enrich_emails.verify_with_reoon(
            "dylan@example.com", "fake-api-key",
            led=led, person_id="dylan-txa", run_id="r2",
        )
        assert http_count["n"] == 1  # unchanged
        assert r1 == r2

        events = [e for e in led.all_events()]
        cache_hits = [e for e in events
                      if e.get("type") == "email_verification_cache_hit"]
        cost_events = [e for e in events
                       if e.get("type") == "cost_incurred"
                       and e.get("source") == "reoon"]
        assert len(cost_events) == 1  # One Reoon credit consumed.
        assert len(cache_hits) == 1   # One cache hit emitted.

    def test_cache_lookup_failure_does_not_block_reoon_call(
        self, led, monkeypatch, capsys,
    ):
        """If the cache lookup raises (corrupted ledger; index error),
        the wrapper MUST fall through to the Reoon call — the cache
        is FAST-PATH; a broken cache must not block the verification."""
        class _MockResp:
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *args):
                return False
            def read(self_inner):
                import json as _json
                return _json.dumps({"status": "safe"}).encode("utf-8")
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda *a, **kw: _MockResp(),
        )

        # Patch lookup_cache to raise.
        monkeypatch.setattr(
            email_verification_cache, "lookup_cache",
            lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("cache index corrupted"),
            ),
        )

        # Should NOT raise — should fall through to Reoon call.
        result = enrich_emails.verify_with_reoon(
            "dylan@example.com", "fake-api-key",
            led=led, person_id="dylan-txa",
        )
        assert result == {"status": "safe"}
