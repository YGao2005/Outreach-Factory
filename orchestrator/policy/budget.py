"""Pillar A — budget rule classes (I7 cost-cap enforcement).

Three concrete rule classes covering the budget failure modes named in
``docs/PILLAR-PLAN.md`` §1 I7 ("a runaway dispatcher cannot spend $500
of Apollo credits without an explicit override + audit trail"):

* :class:`BudgetWindowCapRule` (``budget.window-cap``) — block when the
  sum of ``cost_incurred`` events in the configured window exceeds
  ``max_usd`` (or ``max_units`` for quota-only sources). The "daily
  Apollo $50 cap" factory pattern.
* :class:`BudgetPerPersonCapRule` (``budget.per-person-cap``) — block
  when the sum of ``cost_incurred`` events attributed to
  ``ctx.person_id`` exceeds ``max_usd``. The "$1.00 per-prospect Apollo
  cap" factory pattern — prevents runaway enrichment loops on one
  person.
* :class:`BudgetPerRunCapRule` (``budget.per-run-cap``) — block when
  the sum of ``cost_incurred`` events with the in-flight ``ctx.run_id``
  exceeds ``max_usd``. Guards the "dispatcher in a bad loop" failure
  mode I7 calls out: a misbehaving send-batch cannot transitively burn
  the daily budget.

Each class:

* Implements the ``Rule`` Protocol from :mod:`orchestrator.policy.types`.
* Registers itself into ``RULE_REGISTRY`` at import time.
* Reads its YAML spec via ``from_yaml`` classmethod.
* Accepts a ``block_when:`` filter for per-register / per-channel
  scoping. Budget is tunable policy (caps may legitimately differ
  between cold-pitch sends and follow-up sends), so the cooldown-style
  ``block_when:`` opt-in applies — unlike suppression (ADR-0004
  §Alternative 8), which is a kill switch and refuses scoping. See
  ADR-0006 §Alternative 4 for the full rationale.

Cost ledger contract (ADR-0006)
-------------------------------
The rules consume ``cost_incurred`` events from the ledger. The event
schema is:

    {
      "v": 1, "ts": "<ISO 8601 UTC>", "type": "cost_incurred",
      "source": "<vendor name>",          # anthropic / apollo / pdl / reoon / gmail / linkedin
      "amount_usd": <float>,               # 0.0 for quota-only sources
      "units": <int>,                      # per-source natural unit
      "model_or_endpoint": "<diagnostic>", # e.g. "claude-opus-4-7"
      "person_id": "<id>",                 # optional; attributable cost
      "run_id": "<run-…>",                 # optional; run-level attribution
    }

Failed API calls do NOT emit cost events. The "we don't pay for
failures" assumption is per-vendor and documented in
``COST_RATES_USD``; if a vendor charges for failures (Anthropic does
not; Apollo does not for HTTP errors; verify per-vendor on add), the
emit-site convention changes and ADR-0006 must be amended.

Pricing table contract
----------------------
``COST_RATES_USD`` is the source of truth for per-source pricing. It
is hardcoded into source code (not loaded from a data file) so that
budget evaluation never crashes on missing data — the rule path is
deterministic. Price changes follow the discipline named in ADR-0006
§Decision: a price update is a code change accompanied by an
amendment to the ADR's pricing-table-as-of-date row. Operators with
custom pricing should fork the table or open an issue.

Emit sites (per ADR-0006 §Migration / rollout)
----------------------------------------------
The Python-side emit sites for ``cost_incurred`` events are:

* ``skills/send-outreach/scripts/send_queued.py:gated_send_one`` —
  Gmail send success path. Emits ``source="gmail"``, ``units=1``,
  ``amount_usd=0.0`` (quota-only).
* ``orchestrator/enrich_emails.py:verify_with_reoon`` (Pillar E
  Week 4-5+) — emits ``cost_incurred`` on the cache-miss HTTP-success
  path when ``led`` is provided (per ADR-0034 D158). On cache hit,
  emits ``email_verification_cache_hit`` INSTEAD per ADR-0034 D155
  (the cache hit IS the cost-avoidance signal; co-emission would
  double-count). The event carries ``source="reoon"``, ``units=1``,
  ``amount_usd=COST_RATES_USD["reoon"]["verify"]`` + the cache
  substrate fields ``email`` + ``verification_response`` (per
  ADR-0034 D156). Legacy two-arg ``verify_with_reoon(email, api_key)``
  callers (without ``led``) still rely on the caller-side
  :func:`emit_reoon_cost_event` invocation; the primary call site
  :func:`process_one` was refactored at Week 4-5 to pass ``led``.

Other costs (Anthropic / Apollo / PDL / LinkedIn) are accrued via
Claude Code skill orchestration that runs outside this Python codebase
(MCP-mediated). Their emit sites are out of scope for Pillar A Week 4;
Pillar G (observability) will revisit cross-process cost capture.

Override (per ADR-0006)
-----------------------
A legitimate "spend over the cap" decision is encoded as a
``manual_override`` ledger event PRIOR to the gate evaluation. The
override event names the rule + scope + expiry; the budget rules
honor unexpired overrides by returning ``Allow`` instead of ``Block``.
See ADR-0006 §Override contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ._helpers import _block_when_matches, _parse_iso_utc
from .engine import register_rule_class
from .types import Allow, Block, RuleContext, RuleResult


# ---------------------------------------------------------------------------
# Pricing table — SoT for per-source USD/unit conversion
# ---------------------------------------------------------------------------


# Per-source pricing as USD per natural unit. Hardcoded into source
# code (not loaded from a data file) so the budget rule's evaluate
# path is deterministic and cannot crash on missing data — the
# asymmetric-failure-cost principle compels this (silently allowing
# every send because the pricing table failed to load would be the
# exact false-positive class budget rules exist to block).
#
# Updates to this table are versioned via ADR-0006 amendments;
# operators with custom pricing should fork the constant.
#
# Last reviewed: 2026-05-18 (ADR-0006 §Migration / rollout).
#
# Quota-only sources (Gmail, LinkedIn) have ``amount_usd: 0.0`` per
# emit event; the budget rules count ``units`` for those (e.g. invites
# per week against the LinkedIn 100/week cap). The dict carries them
# only for diagnostic completeness — the per-unit rate is 0.0 by
# definition.
COST_RATES_USD: dict[str, dict[str, float]] = {
    "anthropic": {
        # Per 1M tokens. Multiply by tokens/1_000_000 at emit site.
        # Claude Opus 4.7 input/output rates as of 2026-05-18 docs.
        "claude-opus-4-7:input_per_mtok": 15.0,
        "claude-opus-4-7:output_per_mtok": 75.0,
        "claude-sonnet-4-6:input_per_mtok": 3.0,
        "claude-sonnet-4-6:output_per_mtok": 15.0,
        "claude-haiku-4-5:input_per_mtok": 0.80,
        "claude-haiku-4-5:output_per_mtok": 4.0,
    },
    "apollo": {
        # Per credit. Apollo's people search + enrich each cost
        # one credit at the Basic tier; pricing reviewed against
        # apollo.io/pricing as of 2026-05-18.
        "credit": 0.05,
    },
    "pdl": {
        # Per credit. PeopleDataLabs person-enrich credit rate at
        # pay-as-you-go tier as of 2026-05-18.
        "credit": 0.10,
    },
    "reoon": {
        # Per email-verify check. Power-mode pricing as of 2026-05-18.
        "verify": 0.005,
    },
    "gmail": {
        # Quota-only — Google's API limit is the binding constraint.
        # Units are sends per day (1 per send); USD is 0.0.
        "send": 0.0,
    },
    "linkedin": {
        # Quota-only — LinkedIn enforces an invite-per-week soft cap
        # (~100/week for personal accounts). Units are invites; USD
        # is 0.0.
        "invite": 0.0,
        "dm": 0.0,
    },
}


# ---------------------------------------------------------------------------
# Override consultation
# ---------------------------------------------------------------------------


def _is_overridden(rule_name: str, ctx: RuleContext) -> bool:
    """Whether an unexpired ``manual_override`` event covers this rule.

    The override contract (ADR-0006 §Override contract) is:

        {
          "type": "manual_override",
          "rule": "<rule name to override>",        # required, exact match
          "expires_ts": "<ISO 8601 UTC>",            # required; at-expiry
                                                     # treated as expired
                                                     # (safer side)
          "scope": {                                  # optional
            "person_id": "<id>",                     # match ctx.person_id
            "run_id": "<run-…>",                     # match ctx.run_id
          },
          "reason": "<human-readable justification>",  # required by convention,
                                                       # not validated here
          "approved_by": "<user identifier>",         # audit trail
        }

    A matching override is one whose ``rule`` equals ``rule_name`` AND
    whose ``expires_ts`` is strictly in the future (``ctx.now <
    expires_ts``) AND whose ``scope`` constraints (if any) match
    ``ctx``.

    A scope field set to ``None`` (or absent) is treated as "no scope
    constraint on this field" — the natural operator gesture for an
    override that applies regardless of run / person identity. The
    alternative reading (``scope.run_id: null`` matches only
    ``ctx.run_id is None``) would let a serialized-with-null override
    silently apply only to non-batched sends, which is the opposite
    of what an operator typing it expects.

    Defense-in-depth: the override consultation runs INSIDE the rule's
    evaluate, not at the engine layer. This guarantees that any rule
    forgetting to call ``_is_overridden`` continues to enforce — the
    override is an opt-in by the rule class, not a default the engine
    swallows.
    """
    now = ctx.now.astimezone(timezone.utc)
    for ev in ctx.ledger.all_events():
        if ev.get("type") != "manual_override":
            continue
        if ev.get("rule") != rule_name:
            continue
        expires = _parse_iso_utc(ev.get("expires_ts"))
        # ``<=`` is the safer-side choice: at the expiry instant, the
        # override has expired and the cap is back in force.
        if expires is None or expires <= now:
            continue
        scope = ev.get("scope") or {}
        if isinstance(scope, dict):
            scope_pid = scope.get("person_id")
            if scope_pid is not None and scope_pid != ctx.person_id:
                continue
            scope_run = scope.get("run_id")
            if scope_run is not None and scope_run != ctx.run_id:
                continue
        return True
    return False


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _sum_cost_events(
    ctx: RuleContext,
    *,
    source: str | None = None,
    since: "datetime | None" = None,
    person_id: str | None = None,
    run_id: str | None = None,
) -> tuple[float, int, int]:
    """Sum ``cost_incurred`` events on the ledger, optionally filtered.

    Returns ``(total_usd, total_units, event_count)``.

    Filtering semantics:

    * ``source``: exact match on ``ev["source"]`` (case-sensitive). ``None``
      sums across every source.
    * ``since``: include only events whose ``ts`` is ``>= since``. The
      lower bound is inclusive — the same convention the cooldown
      ``DomainThrottleRule`` uses (ADR-0002 + the boundary tests).
      ``None`` means "no lower bound."
    * ``person_id`` / ``run_id``: when not ``None``, the event must
      carry the same value. Events whose attribution field is absent
      are excluded (they are run-level overhead, not attributable).

    Walks ``ctx.ledger.all_events()`` — same pattern as
    :class:`DomainThrottleRule`. The per-event-type indexing
    optimization is deliberately deferred (see ADR-0006 §LedgerLike
    Protocol shape).

    Timestamp comparison parses each event's ``ts`` to a UTC
    ``datetime`` rather than lex-comparing strings. ``Ledger._now_iso``
    formats with millisecond precision (``...:HH:MM:SS.MMMZ``) while
    a serialized cutoff datetime has none (``...:HH:MM:SS+00:00``);
    string-lex would silently exclude events in the same second as
    the cutoff because ``.`` < ``Z`` and ``.`` < ``+``. Parsed-datetime
    compare is what :class:`DomainThrottleRule` already does.
    """
    total_usd = 0.0
    total_units = 0
    n = 0
    cutoff: "datetime | None" = None
    if since is not None:
        cutoff = since.astimezone(timezone.utc)
    for ev in ctx.ledger.all_events():
        if ev.get("type") != "cost_incurred":
            continue
        if source is not None and ev.get("source") != source:
            continue
        if person_id is not None and ev.get("person_id") != person_id:
            continue
        if run_id is not None and ev.get("run_id") != run_id:
            continue
        if cutoff is not None:
            ev_ts = _parse_iso_utc(ev.get("ts"))
            if ev_ts is None or ev_ts < cutoff:
                continue
        total_usd += float(ev.get("amount_usd") or 0.0)
        total_units += int(ev.get("units") or 0)
        n += 1
    return total_usd, total_units, n


# ---------------------------------------------------------------------------
# BudgetWindowCapRule
# ---------------------------------------------------------------------------


@dataclass
class BudgetWindowCapRule:
    """Block when the sum of ``cost_incurred`` events in the window exceeds
    the configured threshold.

    Factory rule: ``daily-apollo-cap-50usd`` (``source: apollo,
    window_hours: 24, max_usd: 50.0``). Equivalent rules for other
    sources / time-windows are additional YAML entries — no new code.

    Threshold semantics
    -------------------
    The rule blocks when the running sum is **≥** the configured
    threshold — at-threshold blocks. Matches the cooldown
    ``DomainThrottleRule`` convention (ADR-0002), where ``count >=
    max_count`` blocks. The asymmetric-failure-cost principle
    (PILLAR-PLAN §0) compels the at-threshold-blocks choice: an
    off-by-one that lets one extra dollar through is cheaper than
    an off-by-one that lets every send through.

    Mode selection
    --------------
    Exactly one of ``max_usd`` or ``max_units`` must be set:

    * ``max_usd: <float>`` — the rule sums ``amount_usd`` from
      matching events. The natural mode for USD-priced sources
      (Anthropic / Apollo / PDL / Reoon).
    * ``max_units: <int>`` — the rule sums ``units`` from matching
      events. The natural mode for quota-only sources (Gmail /
      LinkedIn) where the binding constraint is a count, not a cost.

    Setting both raises at construction time; setting neither also
    raises. The two-modes-one-class shape mirrors the cooldown
    ``DomainThrottleRule``'s ``max_count`` (units only) — budget needs
    the USD mode because most external APIs charge by token / credit
    and the per-unit cost varies.

    Window
    ------
    Specify exactly one of ``window_days`` or ``window_hours``. Days
    are converted to hours internally; both end up as a ``timedelta``.
    The lower-end is inclusive (events whose ``ts`` equals the cutoff
    are counted), matching the cooldown boundary convention.

    Empty history
    -------------
    A ledger with zero matching events returns sums of 0, which is
    below any non-degenerate threshold — Allow. The empty-history
    invariant (TestEmptyHistoryNoFalseBlocks in
    ``test_policy_budget.py``) pins this.
    """

    name: str
    block_when: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    window_days: float | None = None
    window_hours: float | None = None
    max_usd: float | None = None
    max_units: int | None = None
    reason: str = "Budget window cap exceeded"

    def __post_init__(self) -> None:
        # Exactly-one-mode validation. Catches misconfiguration at
        # construction time, before any send is attempted.
        if (self.max_usd is None) == (self.max_units is None):
            raise ValueError(
                f"BudgetWindowCapRule {self.name!r}: exactly one of "
                f"'max_usd' or 'max_units' must be set (got "
                f"max_usd={self.max_usd!r}, max_units={self.max_units!r})",
            )
        if (self.window_days is None) == (self.window_hours is None):
            raise ValueError(
                f"BudgetWindowCapRule {self.name!r}: exactly one of "
                f"'window_days' or 'window_hours' must be set (got "
                f"window_days={self.window_days!r}, "
                f"window_hours={self.window_hours!r})",
            )
        # Positive-window validation. A zero-or-negative window produces
        # `cutoff == ctx.now` (or `cutoff > ctx.now` for negatives) → every
        # event is "strictly older than cutoff" → counted as outside the
        # window → running sum is always 0 → cap never fires → silently
        # allows every send. Same asymmetric-failure-cost class the
        # sibling rules (TierRequiresTierInRule, DayOfWeekRule,
        # LocalTimeOfDayRule) defend against with degenerate-Block
        # semantics; budget defends here at construction because a
        # zero/negative window has no plausible "rule paused" reading
        # (an operator who wants the cap paused comments out the rule).
        if self.window_days is not None and self.window_days <= 0:
            raise ValueError(
                f"BudgetWindowCapRule {self.name!r}: 'window_days' must "
                f"be > 0 (got {self.window_days!r}); a non-positive "
                f"window produces a cutoff at-or-after ctx.now and the "
                f"running sum is always 0, so the cap never fires and "
                f"every send is silently allowed — the exact failure "
                f"mode the cap exists to prevent.",
            )
        if self.window_hours is not None and self.window_hours <= 0:
            raise ValueError(
                f"BudgetWindowCapRule {self.name!r}: 'window_hours' "
                f"must be > 0 (got {self.window_hours!r}); a non-"
                f"positive window produces a cutoff at-or-after "
                f"ctx.now and the running sum is always 0, so the cap "
                f"never fires and every send is silently allowed — "
                f"the exact failure mode the cap exists to prevent.",
            )

    def _window(self) -> timedelta:
        # __post_init__ guarantees exactly one of window_days /
        # window_hours is non-None.
        if self.window_days is not None:
            return timedelta(days=float(self.window_days))
        return timedelta(hours=float(self.window_hours or 0))

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()

        cutoff = ctx.now.astimezone(timezone.utc) - self._window()
        total_usd, total_units, n = _sum_cost_events(
            ctx, source=self.source, since=cutoff,
        )

        if self.max_usd is not None:
            if total_usd >= self.max_usd:
                # Override check is gated on a Block — no need to
                # pay the ledger walk twice for the Allow path.
                if _is_overridden(self.name, ctx):
                    return Allow()
                return Block(
                    rule=self.name,
                    reason=self.reason,
                    detail={
                        "mode": "usd",
                        "source": self.source,
                        "total_usd": total_usd,
                        "max_usd": self.max_usd,
                        "window_seconds": int(self._window().total_seconds()),
                        "event_count_in_window": n,
                    },
                )
            return Allow()

        # max_units mode. __post_init__ guarantees it's non-None when
        # max_usd is None.
        if total_units >= (self.max_units or 0):
            if _is_overridden(self.name, ctx):
                return Allow()
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "mode": "units",
                    "source": self.source,
                    "total_units": total_units,
                    "max_units": self.max_units,
                    "window_seconds": int(self._window().total_seconds()),
                    "event_count_in_window": n,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "BudgetWindowCapRule":
        return cls(
            name=spec["name"],
            block_when=dict(spec.get("block_when", {})),
            source=spec.get("source"),
            window_days=spec.get("window_days"),
            window_hours=spec.get("window_hours"),
            max_usd=spec.get("max_usd"),
            max_units=spec.get("max_units"),
            reason=spec.get("reason", "Budget window cap exceeded"),
        )


register_rule_class("budget.window-cap", BudgetWindowCapRule)


# ---------------------------------------------------------------------------
# BudgetPerPersonCapRule
# ---------------------------------------------------------------------------


@dataclass
class BudgetPerPersonCapRule:
    """Block when the sum of ``cost_incurred`` events attributed to
    ``ctx.person_id`` exceeds ``max_usd``.

    Factory rule: ``per-person-apollo-cap-1usd`` (``source: apollo,
    max_usd: 1.00``) — prevents runaway enrichment loops on a single
    prospect. A misconfigured rediscovery loop that re-enriches Alice
    every minute will hit this cap before it burns the daily window cap.

    Person-level isolation
    ----------------------
    The rule sums only events whose ``person_id`` matches
    ``ctx.person_id``. Events with no ``person_id`` (run-level
    overhead like authentication checks) are excluded — they are not
    per-person attributable and would muddy the cap. A consequence:
    operators must ensure their cost emit sites carry ``person_id``
    when the cost IS attributable. The Gmail send emit site already
    does this (the send is per-prospect); the Apollo / PDL enrichers
    must too. See ADR-0006 §Per-emit-site attribution contract.

    Threshold semantics
    -------------------
    Same at-threshold-blocks convention as ``BudgetWindowCapRule`` —
    when the running sum is ``>= max_usd``, Block. Mirrors the
    cooldown / cross-channel boundary contract.

    No window
    ---------
    Per-person cap is lifetime-cumulative by design — once we've spent
    $1 enriching Alice, we don't enrich her further regardless of how
    long it's been. If an operator wants the rule to "reset" (e.g.
    after a quarter), they should write a separate
    ``BudgetWindowCapRule`` with the same ``max_usd`` and a long
    window, or rely on the operator's own pruning of old cost events.
    """

    name: str
    block_when: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    max_usd: float = 0.0
    reason: str = "Per-person budget cap exceeded"

    def __post_init__(self) -> None:
        if self.max_usd <= 0:
            raise ValueError(
                f"BudgetPerPersonCapRule {self.name!r}: 'max_usd' must be > 0 "
                f"(got {self.max_usd!r}); a non-positive cap would block "
                f"every send the rule scopes to, which is almost certainly "
                f"unintended.",
            )

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()
        if not ctx.person_id:
            # No person to attribute against — rule is a no-op.
            # The send-gate always carries person_id, but a future
            # caller path may not; safe-default to Allow.
            return Allow()

        total_usd, _total_units, n = _sum_cost_events(
            ctx, source=self.source, person_id=ctx.person_id,
        )
        if total_usd >= self.max_usd:
            if _is_overridden(self.name, ctx):
                return Allow()
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "person_id": ctx.person_id,
                    "source": self.source,
                    "total_usd": total_usd,
                    "max_usd": self.max_usd,
                    "event_count": n,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "BudgetPerPersonCapRule":
        if "max_usd" not in spec:
            raise ValueError(
                f"BudgetPerPersonCapRule {spec.get('name')!r}: "
                "'max_usd' is required",
            )
        return cls(
            name=spec["name"],
            block_when=dict(spec.get("block_when", {})),
            source=spec.get("source"),
            max_usd=float(spec["max_usd"]),
            reason=spec.get("reason", "Per-person budget cap exceeded"),
        )


register_rule_class("budget.per-person-cap", BudgetPerPersonCapRule)


# ---------------------------------------------------------------------------
# BudgetPerRunCapRule
# ---------------------------------------------------------------------------


@dataclass
class BudgetPerRunCapRule:
    """Block when the sum of ``cost_incurred`` events with the
    in-flight ``ctx.run_id`` exceeds ``max_usd``.

    Factory rule: ``per-run-cap-25usd`` (``source: null, max_usd: 25.0``)
    — guards the "dispatcher in a bad loop" failure mode named in
    I7. A misbehaving send-batch that's transitively burning Apollo
    credits cannot exhaust the daily budget; the per-run rule fires
    first.

    Run-level isolation
    -------------------
    The rule sums only events whose ``run_id`` matches ``ctx.run_id``.
    Events from other runs (including past runs of the same script)
    are excluded — the cap is about THIS run's spend, not the
    operator's cumulative spend.

    Missing ``ctx.run_id``
    ----------------------
    When ``ctx.run_id is None``, the rule returns Allow. This is the
    expected state for non-batched callers (e.g. a manual one-off
    send invoked outside the dispatcher). Operators who want a hard
    cap on every send-path regardless of run identity should use
    ``BudgetWindowCapRule`` with a short window instead. The decision
    is documented in ADR-0006 §Alternative 6.

    Threshold semantics
    -------------------
    Same at-threshold-blocks convention as the sibling budget rules.
    """

    name: str
    block_when: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    max_usd: float = 0.0
    reason: str = "Per-run budget cap exceeded"

    def __post_init__(self) -> None:
        if self.max_usd <= 0:
            raise ValueError(
                f"BudgetPerRunCapRule {self.name!r}: 'max_usd' must be > 0 "
                f"(got {self.max_usd!r}); a non-positive cap would block "
                f"every send the rule scopes to.",
            )

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()
        if not ctx.run_id:
            # Non-batched send — rule is a no-op. See class docstring.
            return Allow()

        total_usd, _total_units, n = _sum_cost_events(
            ctx, source=self.source, run_id=ctx.run_id,
        )
        if total_usd >= self.max_usd:
            if _is_overridden(self.name, ctx):
                return Allow()
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "run_id": ctx.run_id,
                    "source": self.source,
                    "total_usd": total_usd,
                    "max_usd": self.max_usd,
                    "event_count": n,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "BudgetPerRunCapRule":
        if "max_usd" not in spec:
            raise ValueError(
                f"BudgetPerRunCapRule {spec.get('name')!r}: "
                "'max_usd' is required",
            )
        return cls(
            name=spec["name"],
            block_when=dict(spec.get("block_when", {})),
            source=spec.get("source"),
            max_usd=float(spec["max_usd"]),
            reason=spec.get("reason", "Per-run budget cap exceeded"),
        )


register_rule_class("budget.per-run-cap", BudgetPerRunCapRule)
