"""Pillar A — shared helpers used by multiple rule modules.

Helpers shipped here because they are needed by more than one rule module
(or anticipated to be soon), and pulling them up avoids inter-module
imports between peers (e.g. ``cross_channel`` importing from ``cooldown``).

* ``_block_when_matches`` — shared ``block_when:`` filter semantics
  (used by cooldown + cross_channel + sending_window).
* ``_parse_iso_utc`` — tolerant ISO-8601 → UTC ``datetime`` parser
  (used by cooldown + cross_channel).
* ``_local_now`` — convert ``ctx.now`` (UTC) to the recipient's local
  timezone via ``zoneinfo`` (used by sending_window — ADR-0005).
* ``UnparseableTimezoneError`` — documented error type raised by
  ``_local_now`` when ``ctx.timezone`` is not a valid IANA name.
  Sending-window rules catch this and return ``Block`` per the
  asymmetric-failure-cost principle (ADR-0005 §Decision).

Underscore-prefixed because these are package-internal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .types import RuleContext


class UnparseableTimezoneError(ValueError):
    """Raised by :func:`_local_now` when ``ctx.timezone`` is not a valid
    IANA timezone name.

    Sending-window rules (ADR-0005) catch this and return a restrictive
    ``Block`` — refusing the send is the safer side of the asymmetric
    failure cost (PILLAR-PLAN §0). The tz inference layer
    (:mod:`orchestrator.policy.tz_inference`) is supposed to ensure
    every ``RuleContext`` gets constructed with a valid IANA name; this
    error class exists for defense-in-depth in case a caller bypassed
    the inference layer.
    """


def _block_when_matches(block_when: dict[str, Any], ctx: RuleContext) -> bool:
    """Whether ``block_when:`` filter matches the context.

    Supported keys (others are ignored — see "Unknown-key tolerance"
    below for the typo-defense gap and the deferral pointer):

    * ``register`` — equality on ``ctx.register``.
    * ``channel`` — equality on ``ctx.channel``.
    * ``tier`` — equality on ``ctx.tier``. A ``None`` ``ctx.tier`` does
      NOT match a non-None filter value (rule does not apply); the
      filter never fires the rule on a Person note that lacks a tier.
      Tier ordering is NOT supported (set-membership only — see
      ``tier_in:``); ADR-0007 §Decision rejects min-tier semantics
      because the cost of getting ordering wrong is asymmetric (false-
      Allow on a low-tier prospect is the failure mode tier rules
      exist to prevent).
    * ``tier_in`` — set-membership on ``ctx.tier``. Accepts a list
      (canonical YAML form). Empty list does NOT match anything
      (filter never fires the rule); a non-list raises ``TypeError``
      at evaluation time. ``None`` ``ctx.tier`` does NOT match a
      non-empty ``tier_in`` (same rationale as ``tier:`` above).
      Operators write the set explicitly — case-sensitive, exact-match,
      no aliasing. Mixing ``tier:`` and ``tier_in:`` on the same rule
      is supported (both must match; the natural ``AND`` semantics
      that ``register:`` + ``channel:`` already use).

    A missing or empty ``block_when`` means "applies to every send."

    Behavioral contract: ``_block_when_matches`` returning ``False``
    means the rule's other logic short-circuits to ``Allow`` for that
    evaluation. Adding a new filter key here lets every existing rule
    class scope by the new dimension WITHOUT per-class code changes —
    this is the load-bearing pattern ADR-0007 §Cross-cutting
    ``block_when:`` extension calls out.

    Unknown-key tolerance (defer / strict-mode TODO)
    ------------------------------------------------
    Unknown keys in ``block_when:`` are silently ignored today. A typo
    like ``{teir: S}`` produces a rule that silently never matches the
    intended tier filter — the rule's substantive logic still runs,
    just without the operator's intended tier scope. ADR-0007
    §Alternative 9 considered switching to strict mode (raise on
    unknown keys) and deferred: the cost is a breaking change to every
    existing operator's YAML; the value is catching a single class of
    typo. A future ADR can flip this when the operator base is larger
    and the migration cost is worth paying. Until then, operator-side
    discipline (review YAML diffs; let `python -m orchestrator.policy
    simulate` surface unexpected rule scope) is the safety surface.
    """
    if not block_when:
        return True
    reg = block_when.get("register")
    if reg is not None and reg != ctx.register:
        return False
    ch = block_when.get("channel")
    if ch is not None and ch != ctx.channel:
        return False
    tier = block_when.get("tier")
    if tier is not None and tier != ctx.tier:
        return False
    tier_in = block_when.get("tier_in")
    if tier_in is not None:
        # Strict typing: a scalar where a list is expected is a YAML
        # error (would silently never match if we accepted ``"S"`` and
        # checked membership: ``ctx.tier in "S"`` happens to pass for
        # "S" but fails for "A"). Raise so the operator notices.
        if not isinstance(tier_in, (list, tuple, set)):
            raise TypeError(
                f"block_when.tier_in must be a list, got "
                f"{type(tier_in).__name__}; write `tier_in: [S, A]` "
                f"not `tier_in: S`",
            )
        if ctx.tier is None or ctx.tier not in tier_in:
            return False
    return True


def _parse_iso_utc(ts: str | None) -> datetime | None:
    """ISO-8601 → timezone-aware UTC datetime, tolerantly.

    Returns ``None`` if ``ts`` is None / unparseable. Ledger writes are
    always well-formed, but reading tolerantly costs nothing and protects
    against synthetic events (e.g. backfill, future schema variants).
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local_now(ctx: RuleContext) -> datetime:
    """Convert ``ctx.now`` (UTC) to the recipient's local timezone.

    Returns a timezone-aware ``datetime`` in ``ctx.timezone``. The returned
    instant represents the same UTC moment — only the wall-clock
    representation differs. Used by sending-window rules to read the
    recipient's local time-of-day and weekday.

    The cooldown rule classes deliberately do NOT call this helper —
    cooldown math is UTC-only (ADR-0002 §Decision). If a future cooldown
    rule starts consulting recipient-local time, ADR-0002 must be
    amended; the cooldown DST property test in
    ``tests/test_policy_cooldown.py::TestDSTSafetyProperty`` is the
    canary.

    DST semantics
    -------------
    * **Spring-forward (non-existent local time):** ``zoneinfo``'s default
      ``fold=0`` resolution applies; the rule sees a well-defined local
      time-of-day on the post-jump side. The rule does not special-case
      this — the UTC instant simply cannot map to the skipped wall time.
      (See ADR-0005 §Decision "DST conventions".)
    * **Fall-back (ambiguous local time):** the same wall time recurs;
      both UTC instants on either side of the fold yield the same local
      time-of-day, so the verdict is naturally consistent. No fold
      handling needed.

    Raises
    ------
    UnparseableTimezoneError:
        ``ctx.timezone`` is empty, None, or not a valid IANA name. The
        caller is responsible for translating this into a restrictive
        ``Block`` — the helper does NOT itself return a verdict (keeping
        the verdict-vs-error split clean: the helper does timezone
        conversion, the rule does policy interpretation).
    """
    tz_name = ctx.timezone
    if not tz_name or not isinstance(tz_name, str):
        raise UnparseableTimezoneError(
            f"RuleContext.timezone is empty or not a string: {tz_name!r}",
        )
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise UnparseableTimezoneError(
            f"RuleContext.timezone {tz_name!r} is not a valid IANA name",
        ) from exc
    # ctx.now is contractually timezone-aware UTC (ADR-0001 §Decision
    # item 1, ADR-0002 §Decision). astimezone preserves the underlying
    # instant; only the wall-clock representation changes.
    return ctx.now.astimezone(zone)
