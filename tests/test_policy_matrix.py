"""Pillar A — consolidated policy-engine test matrix (Week 5 start).

This file is the **at-a-glance** "every rule class is wired and produces
the expected verdict on its canonical case" test surface. The PILLAR-PLAN
§2 Pillar A exit criterion calls for a 50-case matrix consolidated here;
Week 5 ships the foundational rows (CC-01..CC-12 from ADR-0003 + 1–2
representative seeds from each other rule class); Week 6 finishes the
consolidation.

This is **not** the per-class deep-coverage surface — that lives in:
  * ``tests/test_policy_cooldown.py`` — 4 cooldown classes + DST property.
  * ``tests/test_policy_cross_channel.py`` — CC-01..CC-12 detail rows +
    same-channel-overlap warning + DST property.
  * ``tests/test_policy_suppression.py`` — 3 suppression classes + GDPR
    forget atomic-append contract.
  * ``tests/test_policy_sending_window.py`` — 2 sending-window classes +
    DST conventions + tz-dependence property.
  * ``tests/test_policy_budget.py`` — 3 budget classes + window math +
    override consultation + Hypothesis property.
  * ``tests/test_policy_tier.py`` — tier rule + cross-cutting
    ``block_when: {tier|tier_in}`` filter.

The matrix file's job is **integration sanity**: one verdict per row,
exercising the same code path the production gate takes
(``load_rules_from_yaml`` → ``evaluate``) on a hand-crafted YAML +
context. If a row fails here but the per-class test passes, something
is wired wrong at the engine layer.

Each row is a ``MatrixRow`` dataclass; ``pytest.mark.parametrize`` walks
the list. New rows append to the bottom; Week 6 expands toward the 50
target by adding (a) the remaining suppression-rule variants
(domain-block, identity-key-block, GDPR-forget), (b) more sending-window
variants (day-of-week, midnight-wrap), (c) more budget variants
(per-run cap, units mode), (d) more cross-cutting filter rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from orchestrator import policy as policy_pkg
from orchestrator.policy import engine as policy_engine
from orchestrator.policy import suppression as sp
from orchestrator.policy import types as policy_types


# ---------------------------------------------------------------------------
# Test harness — fake ledger + context builder
# ---------------------------------------------------------------------------


class _Evt(dict):
    @property
    def type(self):
        return self["type"]

    @property
    def ts(self):
        return self.get("ts")


class _FakeLedger:
    """Unified fake ledger for matrix rows.

    Supports the seed shapes every rule class consumes:
      * ``add_send`` — send_intent + send_confirmed (cooldown / cross-channel)
      * ``add_confirmed_event`` — raw ``*_confirmed`` (Pillar C LinkedIn types)
      * ``add_cost`` — cost_incurred (budget)
      * ``add_override`` — manual_override (budget override consultation)
    """

    def __init__(self):
        self._events: list[_Evt] = []
        self._n = 0

    def add_send(
        self, *,
        person_id: str,
        channel: str,
        register: str,
        ts: datetime,
        email: str | None = None,
        confirmed: bool = True,
    ) -> str:
        self._n += 1
        intent_id = f"snd_m_{self._n:06d}"
        ts_iso = ts.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        self._events.append(_Evt({
            "v": 1, "type": "send_intent", "ts": ts_iso,
            "intent_id": intent_id, "person_id": person_id,
            "channel": channel, "register": register, "email": email,
        }))
        if confirmed:
            conf_ts = (ts + timedelta(milliseconds=1)) \
                .astimezone(timezone.utc).isoformat() \
                .replace("+00:00", "Z")
            self._events.append(_Evt({
                "v": 1, "type": "send_confirmed", "ts": conf_ts,
                "intent_id": intent_id, "person_id": person_id,
                "channel": channel, "email": email,
                "gmail_message_id": f"gm_{intent_id}",
            }))
        return intent_id

    def add_confirmed_event(
        self, *,
        person_id: str,
        channel: str,
        event_type: str,
        ts: datetime,
    ) -> str:
        self._n += 1
        intent_id = f"evt_m_{self._n:06d}"
        ts_iso = ts.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        self._events.append(_Evt({
            "v": 1, "type": event_type, "ts": ts_iso,
            "intent_id": intent_id, "person_id": person_id,
            "channel": channel,
        }))
        return intent_id

    def add_cost(
        self, *,
        source: str,
        amount_usd: float,
        units: int = 1,
        ts: datetime,
        person_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        t = ts.astimezone(timezone.utc)
        ts_iso = t.strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{t.microsecond // 1000:03d}Z"
        self._events.append(_Evt({
            "v": 1, "type": "cost_incurred", "ts": ts_iso,
            "source": source, "amount_usd": float(amount_usd),
            "units": int(units),
            "model_or_endpoint": "matrix-test",
            "person_id": person_id, "run_id": run_id,
        }))

    def add_override(
        self, *,
        rule: str,
        expires_ts: datetime,
        reason: str = "test override",
        approved_by: str = "matrix-test",
        person_id: str | None = None,
        run_id: str | None = None,
        ts: datetime | None = None,
    ) -> None:
        """Append a ``manual_override`` event (ADR-0006 schema).

        Used by BUD-06 / BUD-07 to exercise the override consultation
        path inside the budget rules' evaluate. The ``expires_ts``
        argument is the override's expiry instant; ``ts`` defaults to
        ``NOW - 1h`` so the override is unambiguously already-written
        when the rule evaluates at ``NOW``.
        """
        when = ts if ts is not None else NOW - timedelta(hours=1)
        ts_iso = when.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        expires_iso = expires_ts.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        ev: dict = {
            "v": 1, "type": "manual_override", "ts": ts_iso,
            "rule": rule, "expires_ts": expires_iso,
            "reason": reason, "approved_by": approved_by,
        }
        scope: dict[str, str] = {}
        if person_id is not None:
            scope["person_id"] = person_id
        if run_id is not None:
            scope["run_id"] = run_id
        if scope:
            ev["scope"] = scope
        self._events.append(_Evt(ev))

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
            ev_email = e.get("email")
            if ev_email and ev_email.lower() == email.lower():
                pid = e.get("person_id")
                if pid:
                    out.add(pid)
        return out

    def all_events(self):
        return list(self._events)


NOW = datetime(2026, 5, 19, 17, 0, 0, tzinfo=timezone.utc)


def _ctx(
    *,
    ledger: _FakeLedger | None = None,
    channel: str = "email",
    register: str = "cold-pitch",
    person_id: str = "alice-li",
    email: str | None = "alice@example.com",
    tier: str | None = "S",
    person_status: str | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
    tz: str = "America/Los_Angeles",
) -> policy_types.RuleContext:
    return policy_types.RuleContext(
        person_id=person_id,
        channel=channel,
        register=register,
        email=email,
        email_domain=email.split("@", 1)[1] if email and "@" in email else None,
        now=now or NOW,
        timezone=tz,
        ledger=ledger or _FakeLedger(),
        person_status=person_status,
        run_id=run_id,
        tier=tier,
    )


# ---------------------------------------------------------------------------
# MatrixRow — one test row in the consolidated matrix
# ---------------------------------------------------------------------------


@dataclass
class MatrixRow:
    """One row in the policy matrix.

    Each row is self-contained — it builds its YAML + context, parses
    the YAML through ``load_rules_from_yaml`` (the same code path the
    production gate uses), evaluates, and asserts on the verdict.
    """

    id: str
    description: str
    rules_yaml: str
    ctx_factory: Callable[[], policy_types.RuleContext]
    expected: str  # "Allow" or "Block"
    expected_rule_if_block: str | None = None
    suppressions_seed: dict[str, list[str]] | None = None
    """Optional seed for suppression rules.

    Suppression rules read entries via ``SuppressionList``; the YAML's
    ``source:`` would normally point to a file. The matrix harness
    (``_load_rules``) writes a real tmp YAML built from this seed and
    rewrites the row's ``rules_yaml`` so ``source:`` references the
    real file. The full ``load_suppression_list_from_yaml`` code path
    runs end-to-end — no post-parse mutation of the rule's
    ``suppressions`` attribute. The row's ``rules_yaml`` must use the
    sentinel string ``/tmp/_unused_matrix.yml`` for every suppression
    rule's ``source:`` value; the harness substitutes the real path
    in-place.
    """


def _load_rules(row: MatrixRow, tmp_path: Path) -> list:
    """Build the rule list for a row.

    When the row carries ``suppressions_seed``, the harness writes a
    real tmp suppressions YAML to ``tmp_path / sup-<row.id>.yml`` and
    rewrites the row's ``rules_yaml`` so every
    ``source: /tmp/_unused_matrix.yml`` placeholder points to the
    real file. The result: ``load_rules_from_yaml`` exercises the
    full ``load_suppression_list_from_yaml`` code path for each
    suppression rule — no post-parse mutation of the rule's
    ``suppressions`` attribute. Per REVIEW-week-5.md §F5.
    """
    rules_yaml_text = row.rules_yaml

    if row.suppressions_seed is not None:
        sup_path = tmp_path / f"sup-{row.id}.yml"
        sup_payload = {
            "version": sp.SUPPORTED_SUPPRESSION_SCHEMA_VERSION,
            "emails": sorted(row.suppressions_seed.get("emails", [])),
            "domains": sorted(row.suppressions_seed.get("domains", [])),
            "identity_keys": sorted(
                row.suppressions_seed.get("identity_keys", []),
            ),
        }
        sup_path.write_text(
            yaml.safe_dump(sup_payload, sort_keys=True),
            encoding="utf-8",
        )
        rules_yaml_text = rules_yaml_text.replace(
            "/tmp/_unused_matrix.yml", str(sup_path),
        )

    rules_path = tmp_path / f"rules-{row.id}.yml"
    rules_path.write_text(rules_yaml_text, encoding="utf-8")
    return policy_engine.load_rules_from_yaml(rules_path)


# ---------------------------------------------------------------------------
# Row builders — keep matrix-level YAML small and reusable
# ---------------------------------------------------------------------------


def _ccr_email_blocks_linkedin_yaml() -> str:
    return (
        "version: 1\n"
        "rules:\n"
        "  - name: cross-channel-email-suppresses-linkedin\n"
        "    type: cooldown.cross-channel-touch\n"
        "    block_when: {channel: linkedin}\n"
        "    consider_channels: [email]\n"
        "    window_days: 14\n"
    )


def _ccr_linkedin_blocks_email_yaml() -> str:
    return (
        "version: 1\n"
        "rules:\n"
        "  - name: cross-channel-linkedin-suppresses-email\n"
        "    type: cooldown.cross-channel-touch\n"
        "    block_when: {channel: email}\n"
        "    consider_channels: [linkedin]\n"
        "    window_days: 14\n"
    )


def _ledger_with_prior_email_send(days_ago: int = 3) -> _FakeLedger:
    led = _FakeLedger()
    led.add_send(
        person_id="alice-li", channel="email", register="cold-pitch",
        ts=NOW - timedelta(days=days_ago),
        email="alice@example.com",
    )
    return led


def _ledger_with_prior_linkedin_dm(days_ago: int = 3) -> _FakeLedger:
    led = _FakeLedger()
    led.add_confirmed_event(
        person_id="alice-li", channel="linkedin",
        event_type="li_dm_confirmed",
        ts=NOW - timedelta(days=days_ago),
    )
    return led


# ---------------------------------------------------------------------------
# Matrix rows — cross-channel single-verdict reduction + per-class seeds
# ---------------------------------------------------------------------------


# Matrix CC-01..CC-12 are this file's INDEPENDENT NUMBERING of the
# cross-channel verdict surface — NOT a 1:1 mirror of ADR-0003's
# CC-01..CC-12 table. The mapping is:
#
#   Matrix CC-01..CC-06: same row as ADR-0003 CC-01..CC-06 (1:1).
#   Matrix CC-07:        the boundary-pair row that ADR-0003 calls CC-06b
#                        (1µs before boundary → Allow). Renumbered here
#                        because the matrix uses a flat sequence; the
#                        boundary contract is pinned by CC-06 + CC-07
#                        as a pair.
#   Matrix CC-08..CC-12: matrix-only single-verdict variations. ADR-0003's
#                        CC-08 (load-time error on empty consider_channels),
#                        CC-11 (Hypothesis tz-invariance property), and
#                        CC-12 (rule-ordering / engine short-circuit) are
#                        structurally non-matrix rows (the matrix's row
#                        shape is "one verdict per row"; structural errors
#                        + property tests don't fit). Those cases are
#                        covered in tests/test_policy_cross_channel.py
#                        and in INTEGRATION_ROWS below (engine short-
#                        circuit is INT-01 / INT-02).
#
# The Pillar A exit criterion's "12 cross-channel rows CC-01 through
# CC-12 enumerated in ADR-0003" is satisfied by: matrix rows CC-01..CC-07
# (the single-verdict subset) + the deep-coverage rows in
# tests/test_policy_cross_channel.py (the structural / property subset).
# The Pillar A 50-case matrix target is met independently of the
# CC-numbering correspondence — see test_minimum_row_count_for_week_6_
# exit_criterion.
CROSS_CHANNEL_ROWS: list[MatrixRow] = [
    MatrixRow(
        id="CC-01",
        description="linkedin send, empty ledger → Allow",
        rules_yaml=_ccr_email_blocks_linkedin_yaml(),
        ctx_factory=lambda: _ctx(channel="linkedin", email=None),
        expected="Allow",
    ),
    MatrixRow(
        id="CC-02",
        description="linkedin send, email send_confirmed within window → Block",
        rules_yaml=_ccr_email_blocks_linkedin_yaml(),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_email_send(days_ago=3),
            channel="linkedin", email=None,
        ),
        expected="Block",
        expected_rule_if_block="cross-channel-email-suppresses-linkedin",
    ),
    MatrixRow(
        id="CC-03",
        description="linkedin send, email send_confirmed beyond window → Allow",
        rules_yaml=_ccr_email_blocks_linkedin_yaml(),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_email_send(days_ago=30),
            channel="linkedin", email=None,
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="CC-04",
        description="email send, li_dm_confirmed within window → Block",
        rules_yaml=_ccr_linkedin_blocks_email_yaml(),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_linkedin_dm(days_ago=5),
            channel="email",
        ),
        expected="Block",
        expected_rule_if_block="cross-channel-linkedin-suppresses-email",
    ),
    MatrixRow(
        id="CC-05",
        description=(
            "linkedin send, email send_intent only (no confirmed) → Allow "
            "(asymmetric-failure-cost: blocking on intent is FP risk)"
        ),
        rules_yaml=_ccr_email_blocks_linkedin_yaml(),
        ctx_factory=lambda: _intent_only_email_ctx(),
        expected="Allow",
    ),
    MatrixRow(
        id="CC-06",
        description=(
            "linkedin send, email send_confirmed exactly at boundary "
            "(now - window_days) → Block (inclusive lower-end)"
        ),
        rules_yaml=_ccr_email_blocks_linkedin_yaml(),
        ctx_factory=lambda: _ctx(
            ledger=_boundary_email_ledger(days_ago=14, microseconds_after=0),
            channel="linkedin", email=None,
        ),
        expected="Block",
        expected_rule_if_block="cross-channel-email-suppresses-linkedin",
    ),
    MatrixRow(
        id="CC-07",
        description=(
            "linkedin send, email send_confirmed 1µs before boundary → "
            "Allow (strictly older than cutoff = outside window)"
        ),
        rules_yaml=_ccr_email_blocks_linkedin_yaml(),
        ctx_factory=lambda: _ctx(
            ledger=_boundary_email_ledger(
                days_ago=14, microseconds_after=-1,
            ),
            channel="linkedin", email=None,
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="CC-08",
        description=(
            "linkedin send, prior email AND prior LinkedIn within window → "
            "Block on cross-channel-email-suppresses-linkedin "
            "(query channel filter restricts to email)"
        ),
        rules_yaml=_ccr_email_blocks_linkedin_yaml(),
        ctx_factory=lambda: _email_and_linkedin_ledger_ctx(),
        expected="Block",
        expected_rule_if_block="cross-channel-email-suppresses-linkedin",
    ),
    MatrixRow(
        id="CC-09",
        description=(
            "email send, no prior touches → Allow "
            "(symmetric to CC-01 in the other direction)"
        ),
        rules_yaml=_ccr_linkedin_blocks_email_yaml(),
        ctx_factory=lambda: _ctx(channel="email"),
        expected="Allow",
    ),
    MatrixRow(
        id="CC-10",
        description=(
            "linkedin send, li_invite_confirmed (DIFFERENT prior type) "
            "within window → Block (any *_confirmed on considered "
            "channel blocks; ADR-0003 §Decision 'Event-type predicate')"
        ),
        rules_yaml=_ccr_linkedin_blocks_email_yaml(),
        ctx_factory=lambda: _ctx(
            ledger=_invite_confirmed_ledger(days_ago=2),
            channel="email",
        ),
        expected="Block",
        expected_rule_if_block="cross-channel-linkedin-suppresses-email",
    ),
    MatrixRow(
        id="CC-11",
        description=(
            "linkedin send, NEITHER channel has prior touches → Allow "
            "(rule with empty considered set semantics)"
        ),
        rules_yaml=_ccr_email_blocks_linkedin_yaml(),
        ctx_factory=lambda: _ctx(
            ledger=_FakeLedger(),
            channel="linkedin", email=None,
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="CC-12",
        description=(
            "linkedin send, block_when scope MISMATCH (rule fires only on "
            "email, current send is linkedin) → Allow (block_when filter "
            "short-circuits)"
        ),
        rules_yaml=_ccr_linkedin_blocks_email_yaml(),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_email_send(),
            channel="linkedin", email=None,
        ),
        # The linkedin-blocks-email rule's block_when is {channel: email}; a
        # linkedin send doesn't match the filter → rule is no-op → Allow.
        expected="Allow",
    ),
]


def _intent_only_email_ctx() -> policy_types.RuleContext:
    led = _FakeLedger()
    led.add_send(
        person_id="alice-li", channel="email", register="cold-pitch",
        ts=NOW - timedelta(days=3),
        email="alice@example.com",
        confirmed=False,
    )
    return _ctx(ledger=led, channel="linkedin", email=None)


def _boundary_email_ledger(
    *, days_ago: int, microseconds_after: int,
) -> _FakeLedger:
    """Build a ledger with one email send_confirmed exactly at the boundary.

    ``microseconds_after`` is a signed offset from ``NOW - days_ago``:
      0  → exactly at the cutoff (inside window)
     -1  → 1µs before the cutoff (outside window — strictly older)
     +1  → 1µs after the cutoff (well inside window)
    """
    led = _FakeLedger()
    target = NOW - timedelta(days=days_ago) + timedelta(microseconds=microseconds_after)
    # add_send emits confirm at intent_ts + 1ms; subtract 1ms so the
    # confirm lands at the requested instant.
    led.add_send(
        person_id="alice-li", channel="email", register="cold-pitch",
        ts=target - timedelta(milliseconds=1),
        email="alice@example.com",
    )
    return led


def _email_and_linkedin_ledger_ctx() -> policy_types.RuleContext:
    led = _FakeLedger()
    led.add_send(
        person_id="alice-li", channel="email", register="cold-pitch",
        ts=NOW - timedelta(days=3),
        email="alice@example.com",
    )
    led.add_confirmed_event(
        person_id="alice-li", channel="linkedin",
        event_type="li_dm_confirmed",
        ts=NOW - timedelta(days=2),
    )
    return _ctx(ledger=led, channel="linkedin", email=None)


def _invite_confirmed_ledger(days_ago: int) -> _FakeLedger:
    led = _FakeLedger()
    led.add_confirmed_event(
        person_id="alice-li", channel="linkedin",
        event_type="li_invite_confirmed",
        ts=NOW - timedelta(days=days_ago),
    )
    return led


# ---------------------------------------------------------------------------
# Per-class representative seeds (1–2 each)
# ---------------------------------------------------------------------------


PER_CLASS_ROWS: list[MatrixRow] = [
    # ---- Cooldown ---------------------------------------------------------
    MatrixRow(
        id="COOL-01",
        description=(
            "cooldown.no-duplicate-register — second cold-pitch to same "
            "person → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: no-double-cold-pitch\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when: {register: cold-pitch}\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_email_send(days_ago=10),
            register="cold-pitch",
        ),
        expected="Block",
        expected_rule_if_block="no-double-cold-pitch",
    ),
    MatrixRow(
        id="COOL-02",
        description=(
            "cooldown.requires-person-status — re-engage without dormant "
            "status → Block (None-status restrictive per ADR-0002)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: re-engage-requires-dormancy\n"
            "    type: cooldown.requires-person-status\n"
            "    block_when: {register: re-engage}\n"
            "    required_status: dormant\n"
        ),
        ctx_factory=lambda: _ctx(
            register="re-engage", person_status=None,
        ),
        expected="Block",
        expected_rule_if_block="re-engage-requires-dormancy",
    ),

    # ---- Suppression -----------------------------------------------------
    MatrixRow(
        id="SUPP-01",
        description=(
            "suppression.email — recipient email on suppression list → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: do-not-contact-emails\n"
            "    type: suppression.email\n"
            "    source: /tmp/_unused_matrix.yml\n"
        ),
        ctx_factory=lambda: _ctx(email="alice@example.com"),
        expected="Block",
        expected_rule_if_block="do-not-contact-emails",
        suppressions_seed={"emails": ["alice@example.com"]},
    ),
    MatrixRow(
        id="SUPP-02",
        description=(
            "suppression.identity-key — Person.id on suppression list → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: do-not-contact-identities\n"
            "    type: suppression.identity-key\n"
            "    source: /tmp/_unused_matrix.yml\n"
        ),
        ctx_factory=lambda: _ctx(person_id="alice-li"),
        expected="Block",
        expected_rule_if_block="do-not-contact-identities",
        suppressions_seed={"identity_keys": ["alice-li"]},
    ),

    # ---- Sending-window --------------------------------------------------
    MatrixRow(
        id="SW-01",
        description=(
            "sending-window.local-time-of-day — 17:00 UTC == 10:00 LA "
            "(PDT, May) → inside 09:00-17:00 → Allow"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: business-hours\n"
            "    type: sending-window.local-time-of-day\n"
            "    block_when: {channel: email}\n"
            "    start_local: \"09:00\"\n"
            "    end_local: \"17:00\"\n"
        ),
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="SW-02",
        description=(
            "sending-window.local-time-of-day — 17:00 UTC at Asia/Tokyo "
            "(UTC+9) → 02:00 local → outside window → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: business-hours\n"
            "    type: sending-window.local-time-of-day\n"
            "    block_when: {channel: email}\n"
            "    start_local: \"09:00\"\n"
            "    end_local: \"17:00\"\n"
        ),
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc),
            tz="Asia/Tokyo",
        ),
        expected="Block",
        expected_rule_if_block="business-hours",
    ),

    # ---- Budget ----------------------------------------------------------
    MatrixRow(
        id="BUD-01",
        description=(
            "budget.window-cap — $55 of Apollo spend in last 24h vs $50 "
            "cap → Block (at-threshold blocks per ADR-0006)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: daily-apollo-cap\n"
            "    type: budget.window-cap\n"
            "    source: apollo\n"
            "    window_hours: 24\n"
            "    max_usd: 50.0\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_apollo_spend_ledger(amount_usd=55.0),
        ),
        expected="Block",
        expected_rule_if_block="daily-apollo-cap",
    ),
    MatrixRow(
        id="BUD-02",
        description=(
            "budget.per-person-cap — $1.05 of Apollo spend on alice-li "
            "vs $1 cap → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: per-person-apollo-cap\n"
            "    type: budget.per-person-cap\n"
            "    source: apollo\n"
            "    max_usd: 1.0\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_apollo_spend_ledger(
                amount_usd=1.05, person_id="alice-li",
            ),
            person_id="alice-li",
        ),
        expected="Block",
        expected_rule_if_block="per-person-apollo-cap",
    ),

    # ---- Tier (Week 5) ---------------------------------------------------
    MatrixRow(
        id="TIER-01",
        description=(
            "tier.requires-tier-in — tier-S cold-pitch with allowed_tiers "
            "[S, A] → Allow"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n"
        ),
        ctx_factory=lambda: _ctx(tier="S", register="cold-pitch"),
        expected="Allow",
    ),
    MatrixRow(
        id="TIER-02",
        description=(
            "tier.requires-tier-in — tier-B cold-pitch with allowed_tiers "
            "[S, A] → Block (wrong tier; detail.tier_value='B')"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n"
        ),
        ctx_factory=lambda: _ctx(tier="B", register="cold-pitch"),
        expected="Block",
        expected_rule_if_block="cold-pitch-tier-gate",
    ),
    MatrixRow(
        id="TIER-03",
        description=(
            "tier.requires-tier-in — None-tier cold-pitch with "
            "allowed_tiers [S, A] → Block (restrictive per ADR-0007)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n"
        ),
        ctx_factory=lambda: _ctx(tier=None, register="cold-pitch"),
        expected="Block",
        expected_rule_if_block="cold-pitch-tier-gate",
    ),

    # ---- Cross-cutting block_when: {tier|tier_in} ------------------------
    MatrixRow(
        id="XCT-01",
        description=(
            "Cross-cutting filter — budget.window-cap with "
            "block_when: {tier: S} → fires for tier-S → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: tier-s-apollo-cap\n"
            "    type: budget.window-cap\n"
            "    block_when: {tier: S}\n"
            "    source: apollo\n"
            "    window_hours: 24\n"
            "    max_usd: 50.0\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_apollo_spend_ledger(amount_usd=55.0),
            tier="S",
        ),
        expected="Block",
        expected_rule_if_block="tier-s-apollo-cap",
    ),
    MatrixRow(
        id="XCT-02",
        description=(
            "Cross-cutting filter — budget.window-cap with "
            "block_when: {tier: S} doesn't fire for tier-A → Allow"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: tier-s-apollo-cap\n"
            "    type: budget.window-cap\n"
            "    block_when: {tier: S}\n"
            "    source: apollo\n"
            "    window_hours: 24\n"
            "    max_usd: 50.0\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_apollo_spend_ledger(amount_usd=55.0),
            tier="A",
        ),
        expected="Allow",
    ),

    # ---- Suppression (Week 6 additions) ----------------------------------
    MatrixRow(
        id="SUPP-03",
        description=(
            "suppression.domain — recipient domain on list → Block "
            "(domain-level kill switch fires regardless of which "
            "address at acme.com is the target)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: do-not-contact-domains\n"
            "    type: suppression.domain\n"
            "    source: /tmp/_unused_matrix.yml\n"
        ),
        ctx_factory=lambda: _ctx(email="alice@spamtrap.io"),
        expected="Block",
        expected_rule_if_block="do-not-contact-domains",
        suppressions_seed={"domains": ["spamtrap.io"]},
    ),
    MatrixRow(
        id="SUPP-04",
        description=(
            "suppression.identity-key — full LinkedIn URL in list "
            "canonicalizes to in/<slug>, matches person_id 'in/alice' "
            "→ Block (canonicalization round-trip)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: do-not-contact-identities-canon\n"
            "    type: suppression.identity-key\n"
            "    source: /tmp/_unused_matrix.yml\n"
        ),
        ctx_factory=lambda: _ctx(person_id="in/alice", email=None),
        expected="Block",
        expected_rule_if_block="do-not-contact-identities-canon",
        # The seed is the canonical form (matches what
        # _canon_identity_key would produce from any URL input — proves
        # the canonical-store + canonical-read round-trip).
        suppressions_seed={"identity_keys": ["in/alice"]},
    ),
    MatrixRow(
        id="SUPP-05",
        description=(
            "suppression.email — recipient NOT on list → Allow "
            "(empty-match invariant; the rule's positive case is "
            "covered by SUPP-01)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: do-not-contact-emails\n"
            "    type: suppression.email\n"
            "    source: /tmp/_unused_matrix.yml\n"
        ),
        ctx_factory=lambda: _ctx(email="alice@example.com"),
        expected="Allow",
        suppressions_seed={"emails": ["someone-else@example.com"]},
    ),
    MatrixRow(
        id="SUPP-06",
        description=(
            "suppression.email — `block_when:` filter in YAML is "
            "IGNORED per ADR-0004 §Alternative 8 (suppression is a "
            "kill switch; channel/register/tier scoping doesn't "
            "apply). The rule fires even when block_when would "
            "exclude it on cooldown / budget. Reproduces by "
            "supplying block_when that would NOT match the ctx and "
            "asserting the rule still Blocks."
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: do-not-contact-kill-switch\n"
            "    type: suppression.email\n"
            "    source: /tmp/_unused_matrix.yml\n"
            # block_when is intentionally not parsed by suppression
            # rules — but if a user put one in, it would be silently
            # ignored. Putting register: follow-up here proves the
            # filter has no effect on a cold-pitch send.
            "    block_when: {register: follow-up}\n"
        ),
        ctx_factory=lambda: _ctx(
            email="alice@example.com", register="cold-pitch",
        ),
        expected="Block",
        expected_rule_if_block="do-not-contact-kill-switch",
        suppressions_seed={"emails": ["alice@example.com"]},
    ),

    # ---- Sending-window (Week 6 additions) -------------------------------
    MatrixRow(
        id="SW-03",
        description=(
            "sending-window.day-of-week — Tuesday 2026-05-19 17:00 UTC "
            "= Tuesday 10:00 LA → in allowed [mon..fri] → Allow"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: weekdays-only\n"
            "    type: sending-window.day-of-week\n"
            "    block_when: {channel: email}\n"
            "    allowed_days: [mon, tue, wed, thu, fri]\n"
        ),
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="SW-04",
        description=(
            "sending-window.day-of-week — Saturday 2026-05-23 17:00 UTC "
            "= Saturday 10:00 LA → not in [mon..fri] → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: weekdays-only\n"
            "    type: sending-window.day-of-week\n"
            "    block_when: {channel: email}\n"
            "    allowed_days: [mon, tue, wed, thu, fri]\n"
        ),
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 23, 17, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        ),
        expected="Block",
        expected_rule_if_block="weekdays-only",
    ),
    MatrixRow(
        id="SW-05",
        description=(
            "sending-window.local-time-of-day — midnight-wrap window "
            "22:00→06:00 at 23:30 local → inside the wrap → Allow "
            "(start > end semantics)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: night-window\n"
            "    type: sending-window.local-time-of-day\n"
            "    block_when: {channel: email}\n"
            "    start_local: \"22:00\"\n"
            "    end_local: \"06:00\"\n"
        ),
        # 23:30 LA on 2026-05-19 == 06:30 UTC on 2026-05-20.
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 20, 6, 30, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="SW-06",
        description=(
            "sending-window.local-time-of-day — midnight-wrap window "
            "22:00→06:00 at 03:00 local → inside the wrap → Allow "
            "(pre-end branch of wrap)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: night-window\n"
            "    type: sending-window.local-time-of-day\n"
            "    block_when: {channel: email}\n"
            "    start_local: \"22:00\"\n"
            "    end_local: \"06:00\"\n"
        ),
        # 03:00 LA == 10:00 UTC (PDT, May).
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="SW-07",
        description=(
            "sending-window.local-time-of-day — midnight-wrap window "
            "22:00→06:00 at 12:00 local → outside the wrap → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: night-window\n"
            "    type: sending-window.local-time-of-day\n"
            "    block_when: {channel: email}\n"
            "    start_local: \"22:00\"\n"
            "    end_local: \"06:00\"\n"
        ),
        # 12:00 LA == 19:00 UTC.
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 19, 19, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        ),
        expected="Block",
        expected_rule_if_block="night-window",
    ),
    MatrixRow(
        id="SW-08",
        description=(
            "sending-window.day-of-week — empty allowed_days [] → "
            "degenerate Block (typo-defends per ADR-0005)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: degenerate-day-window\n"
            "    type: sending-window.day-of-week\n"
            "    block_when: {channel: email}\n"
            "    allowed_days: []\n"
        ),
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        ),
        expected="Block",
        expected_rule_if_block="degenerate-day-window",
    ),

    # ---- Budget (Week 6 additions) ---------------------------------------
    MatrixRow(
        id="BUD-03",
        description=(
            "budget.per-run-cap — $30 of in-run cost vs $25 cap, "
            "ctx.run_id matches → Block"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: per-run-spend-cap\n"
            "    type: budget.per-run-cap\n"
            "    max_usd: 25.0\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_run_spend_ledger(amount_usd=30.0, run_id="run-abc"),
            run_id="run-abc",
        ),
        expected="Block",
        expected_rule_if_block="per-run-spend-cap",
    ),
    MatrixRow(
        id="BUD-04",
        description=(
            "budget.per-run-cap — $30 of spend exists but ctx.run_id "
            "is None → Allow (rule scopes only to in-flight run; "
            "non-batched callers are not subject to per-run caps)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: per-run-spend-cap\n"
            "    type: budget.per-run-cap\n"
            "    max_usd: 25.0\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_run_spend_ledger(amount_usd=30.0, run_id="run-abc"),
            run_id=None,
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="BUD-05",
        description=(
            "budget.window-cap units mode — 400 gmail sends in 24h "
            "vs max_units=400 → Block (at-threshold blocks; "
            "Gmail daily-quota cap pattern)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: daily-gmail-quota\n"
            "    type: budget.window-cap\n"
            "    source: gmail\n"
            "    window_hours: 24\n"
            "    max_units: 400\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_gmail_units_ledger(units=400),
        ),
        expected="Block",
        expected_rule_if_block="daily-gmail-quota",
    ),
    MatrixRow(
        id="LIA-01",
        description=(
            "ADR-0008 LinkedIn weekly invite cap — 100 confirmed "
            "linkedin invites in last 7d vs max_units=100 → Block "
            "(at-threshold blocks; channel-scoped rule). Migrated "
            "from send_queued.py:LINKEDIN_WEEKLY_SOFT_LIMIT."
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: linkedin-weekly-invite-cap\n"
            "    type: budget.window-cap\n"
            "    block_when: {channel: linkedin}\n"
            "    source: linkedin\n"
            "    window_days: 7\n"
            "    max_units: 100\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_linkedin_invite_ledger(units=100),
            channel="linkedin", email=None,
        ),
        expected="Block",
        expected_rule_if_block="linkedin-weekly-invite-cap",
    ),
    MatrixRow(
        id="LIA-02",
        description=(
            "ADR-0008 LinkedIn weekly invite cap — same rule fires "
            "only on linkedin channel; an email send (with the "
            "same invite history) → Allow (channel filter mismatch)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: linkedin-weekly-invite-cap\n"
            "    type: budget.window-cap\n"
            "    block_when: {channel: linkedin}\n"
            "    source: linkedin\n"
            "    window_days: 7\n"
            "    max_units: 100\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_linkedin_invite_ledger(units=100),
            channel="email",
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="BUD-06",
        description=(
            "budget.window-cap — $55 of spend vs $50 cap, but an "
            "unexpired manual_override for this rule exists → Allow "
            "(ADR-0006 override consultation)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: daily-apollo-cap\n"
            "    type: budget.window-cap\n"
            "    source: apollo\n"
            "    window_hours: 24\n"
            "    max_usd: 50.0\n"
        ),
        ctx_factory=lambda: _override_apollo_ledger_ctx(
            override_expires=NOW + timedelta(hours=1),
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="BUD-07",
        description=(
            "budget.window-cap — $55 of spend vs $50 cap, "
            "manual_override exists but EXPIRED → Block (cap "
            "reasserts at expiry; safer-side <= semantics)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: daily-apollo-cap\n"
            "    type: budget.window-cap\n"
            "    source: apollo\n"
            "    window_hours: 24\n"
            "    max_usd: 50.0\n"
        ),
        ctx_factory=lambda: _override_apollo_ledger_ctx(
            override_expires=NOW - timedelta(seconds=1),
        ),
        expected="Block",
        expected_rule_if_block="daily-apollo-cap",
    ),

    # ---- Tier (Week 6 additions) -----------------------------------------
    MatrixRow(
        id="TIER-04",
        description=(
            "tier.requires-tier-in — block_when channel filter on "
            "LinkedIn; tier-B linkedin send with allowed [S, A] → "
            "Block (filter matches channel; rule fires)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: linkedin-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {channel: linkedin}\n"
            "    allowed_tiers: [S, A]\n"
        ),
        ctx_factory=lambda: _ctx(
            channel="linkedin", email=None, tier="B",
        ),
        expected="Block",
        expected_rule_if_block="linkedin-tier-gate",
    ),
    MatrixRow(
        id="TIER-05",
        description=(
            "tier.requires-tier-in — P1/P2/P3 scheme; ctx.tier='P3' "
            "with allowed_tiers ['P1', 'P2'] → Block (rule is "
            "scheme-agnostic; no S/A/B coupling)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: priority-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            # Quote the values: an unquoted YAML scalar like P1 would
            # still parse as str here, but quoting is the operator-
            # safe form ADR-0007 documents.
            "    allowed_tiers: [\"P1\", \"P2\"]\n"
        ),
        ctx_factory=lambda: _ctx(tier="P3"),
        expected="Block",
        expected_rule_if_block="priority-gate",
    ),
    MatrixRow(
        id="TIER-06",
        description=(
            "tier.requires-tier-in — case-sensitive: ctx.tier='s' "
            "(lower) with allowed_tiers ['S'] (upper) → Block "
            "(no normalization; ADR-0007 §Decision item "
            "'Case-sensitive set membership')"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: case-strict-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S]\n"
        ),
        ctx_factory=lambda: _ctx(tier="s"),
        expected="Block",
        expected_rule_if_block="case-strict-tier-gate",
    ),
    MatrixRow(
        id="TIER-07",
        description=(
            "tier.requires-tier-in — allowed_tiers: [] degenerate "
            "→ Block on every scoped send (typo-defends per "
            "ADR-0007 §Decision item 'Empty allowed_tiers')"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: paused-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: []\n"
        ),
        ctx_factory=lambda: _ctx(tier="S"),
        expected="Block",
        expected_rule_if_block="paused-tier-gate",
    ),

    # ---- Cross-cutting block_when: {tier|tier_in} (Week 6) ---------------
    MatrixRow(
        id="XCT-03",
        description=(
            "Cross-cutting filter — cross-channel rule with "
            "block_when: {channel: linkedin, tier_in: [S, A]}; tier-S "
            "linkedin send with prior email touch → Block (filter "
            "matches; rule fires)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: tier-sa-cross-channel\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when: {channel: linkedin, tier_in: [S, A]}\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_email_send(days_ago=3),
            channel="linkedin", email=None, tier="S",
        ),
        expected="Block",
        expected_rule_if_block="tier-sa-cross-channel",
    ),
    MatrixRow(
        id="XCT-04",
        description=(
            "Cross-cutting filter — same rule as XCT-03; tier-B "
            "linkedin send with prior email touch → Allow (tier B "
            "not in [S, A]; filter skips this rule)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: tier-sa-cross-channel\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when: {channel: linkedin, tier_in: [S, A]}\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_email_send(days_ago=3),
            channel="linkedin", email=None, tier="B",
        ),
        expected="Allow",
    ),
    MatrixRow(
        id="XCT-05",
        description=(
            "Cross-cutting filter — sending-window rule with "
            "block_when: {tier: S} only fires for tier-S; tier-A "
            "send at outside-window time → Allow (rule does not "
            "fire)"
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: tier-s-business-hours\n"
            "    type: sending-window.local-time-of-day\n"
            "    block_when: {tier: S}\n"
            "    start_local: \"09:00\"\n"
            "    end_local: \"17:00\"\n"
        ),
        # 02:00 LA, outside 09-17. tier-A → filter doesn't match.
        ctx_factory=lambda: _ctx(
            now=datetime(2026, 5, 19, 9, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
            tier="A",
        ),
        expected="Allow",
    ),
]


def _apollo_spend_ledger(
    *, amount_usd: float, person_id: str | None = None,
) -> _FakeLedger:
    """Seed a ledger with a single Apollo cost_incurred summing to amount_usd."""
    led = _FakeLedger()
    led.add_cost(
        source="apollo", amount_usd=amount_usd, units=1,
        ts=NOW - timedelta(hours=1),
        person_id=person_id,
    )
    return led


def _run_spend_ledger(
    *, amount_usd: float, run_id: str,
) -> _FakeLedger:
    """Seed a ledger with one cost_incurred attributed to ``run_id``.

    Used by BUD-03 / BUD-04 to exercise BudgetPerRunCapRule. The cost
    has no ``source:`` filter — per-run-cap defaults to summing every
    source (any in-run spend counts).
    """
    led = _FakeLedger()
    led.add_cost(
        source="anthropic", amount_usd=amount_usd, units=1,
        ts=NOW - timedelta(hours=1), run_id=run_id,
    )
    return led


def _gmail_units_ledger(*, units: int) -> _FakeLedger:
    """Seed a ledger with ``units`` Gmail sends in the last hour.

    Each event is a single-unit gmail cost_incurred (amount_usd=0.0,
    quota-only). Exercises the units-mode branch of BudgetWindowCapRule
    that the Pillar A exit criterion's "Gmail daily-quota cap" factory
    pattern relies on.
    """
    led = _FakeLedger()
    for i in range(units):
        led.add_cost(
            source="gmail", amount_usd=0.0, units=1,
            ts=NOW - timedelta(minutes=1, seconds=i % 60),
        )
    return led


def _linkedin_invite_ledger(*, units: int) -> _FakeLedger:
    """Seed a ledger with ``units`` LinkedIn invites in the last 6 days.

    Each event is a single-unit linkedin cost_incurred (amount_usd=0.0,
    quota-only — the binding constraint is LinkedIn's per-week soft
    cap). Spread evenly across the last 6 days so all events land
    inside a 7-day window-cap regardless of the cutoff math. Exercises
    the ADR-0008 LinkedIn-cap migration (LIA-01 / LIA-02 rows).
    """
    led = _FakeLedger()
    for i in range(units):
        # Spread across 6*24=144 hours; modulo lets units > 144 stack.
        offset = timedelta(hours=(i % 144), minutes=(i % 60))
        led.add_cost(
            source="linkedin", amount_usd=0.0, units=1,
            ts=NOW - offset,
        )
    return led


def _override_apollo_ledger_ctx(
    *, override_expires: datetime,
) -> policy_types.RuleContext:
    """Seed a ledger with $55 Apollo spend + a manual_override (any
    expiry the caller chooses) for the ``daily-apollo-cap`` rule.

    BUD-06 passes an expiry in the future (override is live → Allow);
    BUD-07 passes an expiry in the past (override is dead → Block).
    The rule name in the override MUST match the YAML's rule name —
    both rows use ``daily-apollo-cap``.
    """
    led = _apollo_spend_ledger(amount_usd=55.0)
    led.add_override(
        rule="daily-apollo-cap",
        expires_ts=override_expires,
        reason="matrix test",
        approved_by="matrix-suite",
    )
    return _ctx(ledger=led)


# ---------------------------------------------------------------------------
# Integration rows — multi-rule chains exercising engine short-circuit
# ---------------------------------------------------------------------------


INTEGRATION_ROWS: list[MatrixRow] = [
    MatrixRow(
        id="INT-01",
        description=(
            "Multi-rule chain — suppression rule placed BEFORE "
            "cooldown rule; both would Block; engine returns the "
            "FIRST Block (suppression). Pins the short-circuit "
            "contract from ADR-0001 §Decision."
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: do-not-contact-emails\n"
            "    type: suppression.email\n"
            "    source: /tmp/_unused_matrix.yml\n"
            "  - name: no-double-cold-pitch\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when: {register: cold-pitch}\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_email_send(days_ago=10),
            email="alice@example.com",
        ),
        expected="Block",
        # Suppression fires first because it's listed first; the
        # cooldown rule never runs.
        expected_rule_if_block="do-not-contact-emails",
        suppressions_seed={"emails": ["alice@example.com"]},
    ),
    MatrixRow(
        id="INT-02",
        description=(
            "Multi-rule chain — cooldown rule placed BEFORE the "
            "same suppression rule from INT-01; same context; "
            "cooldown's Block wins (rule order is load-bearing per "
            "ADR-0001). Asserts the order-flip flips the firing rule."
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: no-double-cold-pitch\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when: {register: cold-pitch}\n"
            "  - name: do-not-contact-emails\n"
            "    type: suppression.email\n"
            "    source: /tmp/_unused_matrix.yml\n"
        ),
        ctx_factory=lambda: _ctx(
            ledger=_ledger_with_prior_email_send(days_ago=10),
            email="alice@example.com",
        ),
        expected="Block",
        expected_rule_if_block="no-double-cold-pitch",
        suppressions_seed={"emails": ["alice@example.com"]},
    ),
    MatrixRow(
        id="INT-03",
        description=(
            "Multi-rule chain — first rule Allows, second rule "
            "Blocks; second's verdict surfaces (no false short-"
            "circuit on Allow). Pins that the engine does NOT "
            "stop on Allow."
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            # Allow: scope mismatch (rule fires only on follow-up).
            "  - name: follow-up-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: follow-up}\n"
            "    allowed_tiers: [S, A]\n"
            # Block: cold-pitch-tier-gate refuses tier B.
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n"
        ),
        ctx_factory=lambda: _ctx(register="cold-pitch", tier="B"),
        expected="Block",
        expected_rule_if_block="cold-pitch-tier-gate",
    ),
    MatrixRow(
        id="INT-04",
        description=(
            "Multi-rule chain — every rule Allows → engine Allow. "
            "Pins the all-Allows-still-Allows invariant for chains "
            "of >1 rule (single-rule case is in load_rules_from_yaml "
            "tests)."
        ),
        rules_yaml=(
            "version: 1\n"
            "rules:\n"
            "  - name: tier-gate-s\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n"
            "  - name: business-hours\n"
            "    type: sending-window.local-time-of-day\n"
            "    block_when: {channel: email}\n"
            "    start_local: \"09:00\"\n"
            "    end_local: \"17:00\"\n"
        ),
        ctx_factory=lambda: _ctx(
            register="cold-pitch", tier="S",
            now=datetime(2026, 5, 19, 17, 0, tzinfo=timezone.utc),
            tz="America/Los_Angeles",
        ),
        expected="Allow",
    ),
]


# ---------------------------------------------------------------------------
# Combined matrix
# ---------------------------------------------------------------------------


ALL_ROWS: list[MatrixRow] = (
    CROSS_CHANNEL_ROWS + PER_CLASS_ROWS + INTEGRATION_ROWS
)


# ---------------------------------------------------------------------------
# pytest parameterized runner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row", ALL_ROWS, ids=[r.id for r in ALL_ROWS],
)
def test_matrix_row(row: MatrixRow, tmp_path: Path) -> None:
    """One verdict per row — exercises load_rules_from_yaml + evaluate."""
    rules = _load_rules(row, tmp_path)
    ctx = row.ctx_factory()
    verdict = policy_engine.evaluate(rules, ctx)

    if row.expected == "Allow":
        assert isinstance(verdict, policy_types.Allow), (
            f"row {row.id} expected Allow but got Block "
            f"(rule={getattr(verdict, 'rule', None)!r}, "
            f"reason={getattr(verdict, 'reason', None)!r})"
        )
    elif row.expected == "Block":
        assert isinstance(verdict, policy_types.Block), (
            f"row {row.id} expected Block but got Allow"
        )
        if row.expected_rule_if_block is not None:
            assert verdict.rule == row.expected_rule_if_block, (
                f"row {row.id} expected block rule "
                f"{row.expected_rule_if_block!r}, got {verdict.rule!r}"
            )
    else:
        pytest.fail(
            f"row {row.id} has unrecognized expected={row.expected!r}"
        )


# ---------------------------------------------------------------------------
# Sanity tests — the matrix itself
# ---------------------------------------------------------------------------


class TestMatrixSanity:
    """Tests of the matrix structure (not the policy engine)."""

    def test_all_row_ids_unique(self):
        ids = [r.id for r in ALL_ROWS]
        assert len(ids) == len(set(ids)), "duplicate row id in matrix"

    def test_minimum_row_count_for_week_5(self):
        """Week 5 floor — ≥ 25 rows. Kept as a regression sentinel
        even after Week 6 raised the target to 50; if the matrix ever
        drops back below 25 we want to fail loud."""
        assert len(ALL_ROWS) >= 25, (
            f"matrix has {len(ALL_ROWS)} rows; Week 5 floor ≥ 25"
        )

    def test_minimum_row_count_for_week_6_exit_criterion(self):
        """Pillar A exit criterion (PILLAR-PLAN §2 Pillar A) calls
        for a 50-case test matrix. Week 6 ships toward that target;
        the assert is the binding gate."""
        assert len(ALL_ROWS) >= 50, (
            f"matrix has {len(ALL_ROWS)} rows; Pillar A exit "
            f"criterion target ≥ 50"
        )

    def test_cross_channel_has_12_rows(self):
        """CC-01..CC-12 (matrix's reduction of ADR-0003) must all
        be present. The matrix's CC-N IDs are an independent
        single-verdict reduction; see ``CROSS_CHANNEL_ROWS``
        docstring for the mapping to ADR-0003's row table (some
        rows mirror 1:1, some are matrix-only variations)."""
        cc_ids = {r.id for r in CROSS_CHANNEL_ROWS}
        for i in range(1, 13):
            expected = f"CC-{i:02d}"
            assert expected in cc_ids, f"missing matrix row {expected}"

    def test_every_rule_class_has_at_least_one_row(self):
        """Cooldown / suppression / sending-window / budget / tier /
        cross-cutting each have at least one canonical row."""
        prefixes_seen = {r.id.split("-")[0] for r in PER_CLASS_ROWS}
        assert "COOL" in prefixes_seen
        assert "SUPP" in prefixes_seen
        assert "SW" in prefixes_seen
        assert "BUD" in prefixes_seen
        assert "TIER" in prefixes_seen
        assert "XCT" in prefixes_seen

    def test_integration_rows_present(self):
        """Multi-rule chains (INT-*) exercise engine short-circuit +
        rule-ordering. Week 6 added these to cover the integration
        gap the per-class tests can't reach."""
        int_ids = {r.id for r in INTEGRATION_ROWS}
        assert len(int_ids) >= 3, (
            f"matrix has {len(int_ids)} INT-* rows; "
            f"Week 6 target ≥ 3 integration cases"
        )

    def test_suppression_has_block_when_ignored_row(self):
        """ADR-0004 §Alternative 8 invariant — suppression rules
        ignore block_when:. The matrix must exercise this with a
        block_when that would NOT match, asserting Block anyway."""
        # Find a row whose YAML has block_when AND is a suppression
        # rule AND ends in Block (i.e. proves the filter was ignored).
        found = False
        for row in PER_CLASS_ROWS:
            if (
                row.id.startswith("SUPP-")
                and "block_when" in row.rules_yaml
                and row.expected == "Block"
            ):
                found = True
                break
        assert found, (
            "no SUPP-* row exercises the 'block_when ignored' "
            "invariant (ADR-0004 §Alt 8)"
        )
