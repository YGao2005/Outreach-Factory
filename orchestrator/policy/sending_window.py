"""Pillar A — sending-window rule classes (recipient-local time).

Two concrete rule classes covering the sending-window failure modes:

* :class:`LocalTimeOfDayRule` (``sending-window.local-time-of-day``) —
  block when the recipient's local time-of-day is outside ``[start_local,
  end_local)``. Supports midnight-wrapping windows (``start > end``) for
  night-shift / off-hours patterns.
* :class:`DayOfWeekRule` (``sending-window.day-of-week``) — block when the
  recipient's local weekday is not in ``allowed_days``. Common pattern:
  ``[mon, tue, wed, thu, fri]`` for B2B outreach.

Both classes share the ``_local_now`` helper in ``_helpers.py`` to convert
``ctx.now`` (UTC, per ADR-0001 §Decision item 1) into the recipient's
local timezone. ``ctx.timezone`` is the recipient's IANA name, populated
by the send-gate caller via :mod:`orchestrator.policy.tz_inference` —
see ADR-0005 §Decision.

Cooldown vs sending-window: complementary contracts
---------------------------------------------------
The cooldown rule classes deliberately do NOT consult ``ctx.timezone``
(ADR-0002 §Decision). Cooldown math is UTC; "7 days" means 168 wall-clock
hours regardless of recipient timezone. The cooldown DST property test
(``tests/test_policy_cooldown.py::TestDSTSafetyProperty``) asserts this
tz-invariance.

Sending-window rules invert that contract: their verdict explicitly
depends on ``ctx.timezone``. The DST tz-dependence property test
(``tests/test_policy_sending_window.py::TestTimezoneDependence``) asserts
this. Together the two property tests fence in the contract — a refactor
that accidentally leaked tz into cooldown OR removed tz from
sending-window would fail one of them.

DST conventions (ADR-0005)
--------------------------
The rule reads the recipient's local time-of-day via
``ctx.now.astimezone(ZoneInfo(ctx.timezone)).time()``. ``zoneinfo``
handles both DST edge cases:

* **Non-existent local time (spring-forward):** A UTC instant that would
  have mapped to a skipped wall time (e.g. 02:30 PST on a spring-forward
  Sunday) instead maps to the post-jump local time (03:30 PDT). The rule
  sees a well-defined local time-of-day and produces a deterministic
  verdict. No special-casing.
* **Ambiguous local time (fall-back):** Two distinct UTC instants share
  the same local time-of-day (01:30 occurs twice on fall-back Sunday).
  The rule reads only local time-of-day, so both UTC instants produce
  identical verdicts naturally. No fold handling.

The asymmetric-failure-cost principle (PILLAR-PLAN §0) applies to two
edge inputs:

* **Unparseable ``ctx.timezone``** — block. The tz inference layer is
  supposed to normalize, but if a bug somewhere produces garbage, refuse
  the send rather than allow. ``UnparseableTimezoneError`` from
  ``_local_now`` is caught here and converted to a structured ``Block``.
* **Degenerate windows** (``start_local == end_local`` for LocalTimeOfDay;
  ``allowed_days == []`` for DayOfWeek) — block. A typo'd YAML producing
  an empty window should refuse, not silently allow every send.

Boundary semantics (ADR-0005 §Decision)
---------------------------------------
LocalTimeOfDayRule uses the half-open interval ``[start, end)``:
inclusive start, exclusive end. Matches the cooldown
``DomainThrottleRule`` and cross-channel ``CrossChannelTouchRule``
boundary convention (ADR-0003 CC-06). The boundary tests in
``tests/test_policy_sending_window.py`` pin this contract.

Risk this rule mitigates by design: R009 (off-hours / weekend sends
damage relationship + deliverability).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time
from typing import Any

from ._helpers import UnparseableTimezoneError, _block_when_matches, _local_now
from .engine import register_rule_class
from .types import Allow, Block, RuleContext, RuleResult


_TIME_HHMM_RE = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})$")

# Canonical weekday short names matching ``datetime.weekday()`` indexing
# (Monday = 0). The from_yaml path normalizes inputs to this set so the
# evaluate path can do a plain ``in`` check.
_WEEKDAY_NAMES: tuple[str, ...] = (
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
)
_WEEKDAY_INDEX: dict[str, int] = {n: i for i, n in enumerate(_WEEKDAY_NAMES)}

# Generous aliases for weekday inputs. The factory rule discriminator
# accepts any of these and normalizes — operators writing YAML shouldn't
# have to remember a single spelling.
_WEEKDAY_ALIASES: dict[str, str] = {
    "mon": "mon", "monday": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue",
    "wed": "wed", "weds": "wed", "wednesday": "wed",
    "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu",
    "fri": "fri", "friday": "fri",
    "sat": "sat", "saturday": "sat",
    "sun": "sun", "sunday": "sun",
}


# ---------------------------------------------------------------------------
# LocalTimeOfDayRule
# ---------------------------------------------------------------------------


def _parse_hhmm(value: str, *, field_name: str, rule_name: str) -> time:
    """Parse an ``HH:MM`` (24-hour) string into a :class:`datetime.time`.

    Raises ``ValueError`` (with a descriptive message including the
    rule's name + the field that failed) when the input doesn't match
    the strict ``HH:MM`` shape or names an out-of-range hour/minute.
    Strict parsing avoids the "9am" / "9:0" / "09:00:00" ambiguity that
    a permissive parser would silently swallow.
    """
    if not isinstance(value, str):
        raise ValueError(
            f"{type(value).__name__} for {rule_name!r} field {field_name!r}; "
            f"expected 'HH:MM' string, got {value!r}",
        )
    m = _TIME_HHMM_RE.match(value.strip())
    if not m:
        raise ValueError(
            f"{rule_name!r} field {field_name!r}={value!r} is not 'HH:MM' "
            f"(strict 24-hour format, e.g. '09:00' or '17:30')",
        )
    hour = int(m.group("h"))
    minute = int(m.group("m"))
    if hour > 23 or minute > 59:
        raise ValueError(
            f"{rule_name!r} field {field_name!r}={value!r} is out of range "
            f"(hour must be 0-23, minute 0-59)",
        )
    return time(hour=hour, minute=minute)


@dataclass
class LocalTimeOfDayRule:
    """Block when the recipient's local time-of-day is outside the window.

    Factory rule: ``business-hours-only`` (``start_local: 09:00,
    end_local: 17:00``). Equivalent variations (``no-late-evening``,
    ``no-pre-dawn``) are additional YAML entries — no new code required.

    Window semantics
    ----------------
    The window is the half-open interval ``[start_local, end_local)``:

    * ``now_local == start_local`` → in window → Allow.
    * ``now_local == end_local`` → outside window → Block.
    * For non-wrapping windows (``start < end``): in window iff
      ``start <= now < end``.
    * For wrapping windows (``start > end``, e.g. ``22:00 → 06:00``): in
      window iff ``now >= start OR now < end``.
    * Degenerate window (``start == end``) → always Block. See module
      docstring for rationale.

    The half-open convention matches :class:`DomainThrottleRule` and
    :class:`CrossChannelTouchRule` (ADR-0003 CC-06). The boundary tests
    in ``tests/test_policy_sending_window.py`` pin it.
    """

    name: str
    start_local: str
    end_local: str
    block_when: dict[str, Any] = field(default_factory=dict)
    reason: str = "Outside recipient's local sending window"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()

        start = _parse_hhmm(
            self.start_local, field_name="start_local", rule_name=self.name,
        )
        end = _parse_hhmm(
            self.end_local, field_name="end_local", rule_name=self.name,
        )

        if start == end:
            # Degenerate empty window — refuse rather than allow (a typo
            # producing equal start/end should not open the floodgates).
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "degenerate": True,
                    "start_local": self.start_local,
                    "end_local": self.end_local,
                    "timezone": ctx.timezone,
                },
            )

        try:
            local_now = _local_now(ctx)
        except UnparseableTimezoneError as exc:
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "invalid_timezone": True,
                    "timezone": ctx.timezone,
                    "error": str(exc),
                },
            )
        now_t = local_now.time()

        if start < end:
            in_window = start <= now_t < end
        else:
            # start > end → window wraps midnight.
            in_window = now_t >= start or now_t < end

        if in_window:
            return Allow()
        return Block(
            rule=self.name,
            reason=self.reason,
            detail={
                "local_time": now_t.strftime("%H:%M:%S"),
                "timezone": ctx.timezone,
                "start_local": self.start_local,
                "end_local": self.end_local,
                "wraps_midnight": start > end,
            },
        )

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "LocalTimeOfDayRule":
        name = spec.get("name")
        if "start_local" not in spec:
            raise ValueError(
                f"LocalTimeOfDayRule {name!r}: 'start_local' is required",
            )
        if "end_local" not in spec:
            raise ValueError(
                f"LocalTimeOfDayRule {name!r}: 'end_local' is required",
            )
        # Validate-at-load: bad HH:MM should raise here, not at first
        # evaluation under load.
        _parse_hhmm(spec["start_local"], field_name="start_local",
                    rule_name=str(name))
        _parse_hhmm(spec["end_local"], field_name="end_local",
                    rule_name=str(name))
        return cls(
            name=spec["name"],
            start_local=str(spec["start_local"]),
            end_local=str(spec["end_local"]),
            block_when=dict(spec.get("block_when", {})),
            reason=spec.get(
                "reason", "Outside recipient's local sending window",
            ),
        )


register_rule_class(
    "sending-window.local-time-of-day", LocalTimeOfDayRule,
)


# ---------------------------------------------------------------------------
# DayOfWeekRule
# ---------------------------------------------------------------------------


def _normalize_day(value: Any, *, rule_name: str) -> str:
    """Lowercase + alias-resolve a single day name to the canonical short form.

    Raises ``ValueError`` (with a descriptive message including the
    rule's name + the offending input) when the value isn't a recognized
    weekday name. Strict on unknowns — typo'd day names ("funday",
    "friady") would silently fail to ever match if we tolerated them.
    """
    if not isinstance(value, str):
        raise ValueError(
            f"DayOfWeekRule {rule_name!r}: allowed_days entry "
            f"{value!r} is not a string",
        )
    canonical = _WEEKDAY_ALIASES.get(value.strip().lower())
    if canonical is None:
        raise ValueError(
            f"DayOfWeekRule {rule_name!r}: allowed_days entry "
            f"{value!r} is not a recognized weekday name "
            f"(use mon/tue/wed/thu/fri/sat/sun or the long form)",
        )
    return canonical


@dataclass
class DayOfWeekRule:
    """Block when the recipient's local weekday is not in ``allowed_days``.

    Factory rule: ``weekdays-only`` (``allowed_days: [mon, tue, wed,
    thu, fri]``). Weekend-only variants flip the set.

    ``allowed_days`` is normalized to canonical lowercased short names
    (``mon``, ``tue``, ..., ``sun``) at construction time. Inputs may use
    long or short forms (``Monday`` / ``Mon`` / ``mon`` / ``MON``) and a
    set of common abbreviations (``tues``, ``thur``, ``thurs``, ``weds``).

    Empty ``allowed_days`` → degenerate, always-block (mirroring the
    LocalTimeOfDayRule degenerate case — a typo'd YAML producing an
    empty list should refuse, not open the floodgates).
    """

    name: str
    allowed_days: list[str]
    block_when: dict[str, Any] = field(default_factory=dict)
    reason: str = "Recipient's local weekday is not in the allowed set"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()

        # Normalize on the fly — the construction path normalizes too,
        # but a direct construct (test, future caller) may pass unnormalized.
        try:
            allowed = {
                _normalize_day(d, rule_name=self.name) for d in self.allowed_days
            }
        except ValueError:
            # Bad day name reaches here only via direct construct; raise
            # rather than swallow — same fail-loud principle as
            # cooldown's malformed-spec from_yaml validation.
            raise

        if not allowed:
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "degenerate": True,
                    "allowed_days": list(self.allowed_days),
                    "timezone": ctx.timezone,
                },
            )

        try:
            local_now = _local_now(ctx)
        except UnparseableTimezoneError as exc:
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "invalid_timezone": True,
                    "timezone": ctx.timezone,
                    "error": str(exc),
                },
            )

        weekday_idx = local_now.weekday()
        weekday_name = _WEEKDAY_NAMES[weekday_idx]
        if weekday_name in allowed:
            return Allow()

        return Block(
            rule=self.name,
            reason=self.reason,
            detail={
                "local_weekday": weekday_name,
                "local_date": local_now.date().isoformat(),
                "allowed_days": [
                    _normalize_day(d, rule_name=self.name)
                    for d in self.allowed_days
                ],
                "timezone": ctx.timezone,
            },
        )

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "DayOfWeekRule":
        name = spec.get("name")
        if "allowed_days" not in spec:
            raise ValueError(
                f"DayOfWeekRule {name!r}: 'allowed_days' is required",
            )
        raw = spec["allowed_days"]
        if not isinstance(raw, list):
            raise ValueError(
                f"DayOfWeekRule {name!r}: 'allowed_days' must be a list, "
                f"got {type(raw).__name__}",
            )
        # Validate at load — bad day names raise here, not at first
        # evaluation under load.
        normalized = [_normalize_day(d, rule_name=str(name)) for d in raw]
        return cls(
            name=spec["name"],
            allowed_days=normalized,
            block_when=dict(spec.get("block_when", {})),
            reason=spec.get(
                "reason",
                "Recipient's local weekday is not in the allowed set",
            ),
        )


register_rule_class("sending-window.day-of-week", DayOfWeekRule)
