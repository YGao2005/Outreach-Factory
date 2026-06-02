"""Pillar E Week 4-5 — email-verification cache primitive.

Per ADR-0032 D144 (Pillar E foundation) + ADR-0034 D154-D159 (Pillar E
Week 4-5). The cache primitive wraps the existing
:func:`enrich_emails.verify_with_reoon` call site with a per-email
TTL-based lookup against the ledger's ``cost_incurred.source=reoon``
event stream. On a cache hit (a recent Reoon verification result for
the same email exists within the 30-day TTL), the wrapper short-
circuits the Reoon API call, emits a ``email_verification_cache_hit``
event (NEW per ADR-0032 D146) INSTEAD of ``cost_incurred``, and
returns the cached Reoon response verbatim. On a cache miss, the
wrapper falls through to the existing Reoon HTTP path + the existing
``cost_incurred`` emit per ADR-0006 — unchanged. The cost-avoidance
IS the binding exit-criterion behavior per PILLAR-PLAN §2 Pillar E:
*"discovering the same person via three skills in one day consumes
one Apollo credit, one Reoon credit, zero duplicate enrollments."*

Module shape (ADR-0034 D154 — sibling-of-enrich_emails.py + sibling-
of-discovery_dedup.py placement):
  * :class:`EmailVerificationCacheResult` — frozen dataclass; the
    outcome of a per-email lookup. Two states: ``is_cache_hit=True``
    (the caller short-circuits the Reoon call + emits the cache_hit
    event) and ``is_cache_hit=False`` (the caller proceeds with the
    existing Reoon HTTP path).
  * :func:`lookup_cache` — the per-call entry point. Walks the
    ledger's ``all_events()`` filtering on
    ``type == "cost_incurred"`` + ``source == "reoon"`` +
    ``email == <target>`` + ``ts >= now - ttl_days``. Returns the
    most-recent matching row's ``verification_response`` on hit.
  * :func:`build_email_verification_cache_hit_payload` — emit-shape
    factory for ``email_verification_cache_hit`` events per ADR-0034
    D155 + ADR-0032 D146's channel-on-every-event invariant extension
    (``channel: "email"`` since the cache is email-channel-specific).
  * :data:`DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS` — the 30-day
    TTL constant per ADR-0034 D157. Reoon's official accuracy
    guarantee is ~30 days; beyond that, the operator's risk
    tolerance accepts re-verification.

Per-call integration (ADR-0034 D158):
  :func:`enrich_emails.verify_with_reoon` wraps with the cache
  primitive. The integration is INSIDE ``verify_with_reoon`` (single
  call site) — structurally simpler than the dedup primitive's per-
  skill integration (four discovery skills); the cache wrap is
  content-additive (the existing call signature is preserved via
  optional kwargs with ``None`` defaults).

CLI (mirrors :mod:`discovery_dedup`):

    python email_verification_cache.py lookup --email <addr> \\
                                              [--ttl-days N] \\
                                              [--apply] [--json]

The ``--apply`` flag controls whether the
``email_verification_cache_hit`` event is appended to the ledger
(live mode) or just reported (dry-run mode — the default). The
dry-run default mirrors :mod:`policy`'s ``simulate`` posture: read-
only by default; explicit opt-in for state-mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import ledger as _ledger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Per ADR-0034 D157 — the operator-pinned cache TTL.
#
# Reoon's official accuracy guarantee is ~30 days (per Reoon's
# documentation on disposable-mailbox lifecycle + catch-all
# configuration drift). Beyond 30 days the cached result may
# misrepresent the email's current deliverability — the operator's
# risk tolerance accepts re-verification at that point.
#
# Operators can override the TTL per-call via the :func:`lookup_cache`
# ``ttl_days`` kwarg. The framework-level constant is the default;
# operator override via Pillar I CLI is the future extension surface.
DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS: int = 30


# Per ADR-0010 D17 — every Pillar E event carries an ``_emitted_by``
# marker for operator-facing filterability. The cache primitive's
# marker is reserved here as the single source of truth (consumed by
# :func:`build_email_verification_cache_hit_payload` + the cross-
# pillar surface audit's literal-string predicate).
EMITTED_BY: str = "email_verification_cache"


# Per ADR-0032 D146 + ADR-0014 D33 — the cache primitive's event
# carries ``channel: "email"`` because the cache is email-channel-
# specific (the lookup key is an email; the cached outcome is Reoon's
# email-verification verdict).
#
# Mirrors Pillar D Week 1's ``reply_received`` events stamping
# ``channel: "email"`` even though Pass B's emit context is
# unambiguously email — the explicit stamp makes the absence
# operator-visible to Pillar G dashboards filtered by channel.
#
# Contrast with the dedup primitive (:mod:`discovery_dedup`) which
# stamps ``channel: "none"`` (dedup is channel-agnostic). The cache
# primitive's email-specific stamp is operator-deliberate per the
# HANDOFF-pillar-e-week-4.md §Design-decisions recommendation.
CHANNEL_VALUE: str = "email"


# Internal — the ledger-walk filter constants. Pinned here so the
# cross-pillar audit + the test corpus reference a single source of
# truth (per the ADR-0033 EMITTED_BY pattern).
COST_INCURRED_TYPE: str = "cost_incurred"
REOON_SOURCE: str = "reoon"


# ---------------------------------------------------------------------------
# EmailVerificationCacheResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailVerificationCacheResult:
    """Outcome of an email-verification cache lookup per ADR-0034 D155.

    Two states + the data each carries:

    * ``is_cache_hit=True`` — the lookup found a ``cost_incurred.
      source=reoon`` event for the email within the TTL window.
      :attr:`cached_response` carries the full Reoon response dict
      verbatim from the originating event (the caller returns this
      to its own caller in place of a fresh Reoon HTTP call);
      :attr:`cached_at` carries the ISO timestamp of the originating
      event; :attr:`cache_age_days` carries the integer age at
      lookup time (computed against the ``now`` clock);
      :attr:`cached_person_id` carries the originating event's
      ``person_id`` (if any) for caller-default attribution on the
      emitted cache_hit event.

    * ``is_cache_hit=False`` — no matching event within TTL.
      :attr:`cached_response` / :attr:`cached_at` /
      :attr:`cache_age_days` / :attr:`cached_person_id` are all
      ``None``. The caller proceeds to call Reoon as today + emits
      ``cost_incurred`` per ADR-0006 unchanged.

    The dataclass is frozen + has no internal mutability so a single
    :class:`EmailVerificationCacheResult` can be passed across the
    cache-lookup + event-payload-factory boundary without copying.

    The :attr:`cached_outcome` property derives the Reoon status
    string (``"safe"`` / ``"catch_all"`` / ``"invalid"`` / etc.)
    from :attr:`cached_response` — the operator-visible outcome
    label that the emitted ``email_verification_cache_hit`` event
    carries (per D155's ``cached_result`` field).
    """

    is_cache_hit: bool
    email: str
    cached_response: dict | None = None
    cached_at: str | None = None
    cache_age_days: int | None = None
    cached_person_id: str | None = None

    def __post_init__(self) -> None:
        if self.is_cache_hit:
            if self.cached_response is None:
                raise ValueError(
                    "EmailVerificationCacheResult(is_cache_hit=True) "
                    "requires cached_response (the Reoon response dict "
                    "from the prior cost_incurred event)"
                )
            if self.cached_at is None:
                raise ValueError(
                    "EmailVerificationCacheResult(is_cache_hit=True) "
                    "requires cached_at (the ISO timestamp of the prior "
                    "cost_incurred event)"
                )
        else:
            if self.cached_response is not None:
                raise ValueError(
                    "EmailVerificationCacheResult(is_cache_hit=False) "
                    "must NOT carry cached_response; got "
                    f"{type(self.cached_response).__name__}"
                )
            if self.cached_at is not None:
                raise ValueError(
                    "EmailVerificationCacheResult(is_cache_hit=False) "
                    "must NOT carry cached_at"
                )
            if self.cache_age_days is not None:
                raise ValueError(
                    "EmailVerificationCacheResult(is_cache_hit=False) "
                    "must NOT carry cache_age_days"
                )

    @property
    def cached_outcome(self) -> str | None:
        """The Reoon status string derived from :attr:`cached_response`.

        Returns one of ``"safe"`` / ``"catch_all"`` / ``"invalid"`` /
        ``"disposable"`` / ``"spamtrap"`` / etc. (per Reoon's status
        enum) or ``None`` on cache miss OR on a malformed cached
        response that lacks the ``status`` key. The status is the
        operator-visible outcome label; the full response is
        preserved for the caller's downstream consumption via
        :attr:`cached_response`.

        Per ADR-0034 D155 — the emitted ``email_verification_cache_hit``
        event's ``cached_result`` field carries this string (not the
        full dict — the dict is preserved on the originating
        ``cost_incurred`` event's ``verification_response`` field).
        """
        if self.cached_response is None:
            return None
        return self.cached_response.get("status")


# ---------------------------------------------------------------------------
# Internal — timestamp parsing
# ---------------------------------------------------------------------------


def _parse_iso_ts(ts: str | None) -> datetime | None:
    """Parse a ledger ``ts`` ISO string to a UTC datetime, tolerantly.

    The ledger's :func:`ledger._now_iso` writes ``...Z``-suffixed UTC
    timestamps. Some pre-existing or test-supplied events may carry
    ``+00:00`` offset form. Both are accepted; malformed strings
    return ``None`` (treated as miss by the lookup).
    """
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts[:-1]).replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Cache lookup primitive
# ---------------------------------------------------------------------------


def lookup_cache(
    email: str,
    *,
    ledger: "_ledger.Ledger | None" = None,
    now: datetime | None = None,
    ttl_days: int = DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS,
) -> EmailVerificationCacheResult:
    """Consult the ledger event stream for a recent Reoon verification.

    Per ADR-0034 D156. The cache substrate IS the ledger's
    ``cost_incurred.source=reoon`` event stream — no separate cache
    file; the lookup is a derived view per ADR-0032 D144's "ledger-
    as-cache-substrate" choice (preserves I1 single source of truth).

    The lookup walks :meth:`Ledger.all_events`, filtering by
    ``type == "cost_incurred"`` + ``source == "reoon"`` +
    ``email == <target>`` (case-insensitive) +
    ``ts >= now - ttl_days``. Returns the most-recent matching
    event's ``verification_response`` as the cached payload.

    The TTL boundary is INCLUSIVE on the lower bound (an event at
    exactly ``now - ttl_days`` IS a hit) — matches the cooldown
    rule + budget rule convention per ADR-0002 + ADR-0006.

    Args:
        email: The email address to look up. Lower-cased for
            comparison.
        ledger: The :class:`Ledger` instance. ``None`` returns miss
            (best-effort — the cache primitive is the FAST-PATH;
            an absent ledger falls through to the Reoon HTTP call).
        now: The clock pinning for test reproducibility (per
            ADR-0031 D140 deterministic-clock precedent). Defaults
            to ``datetime.now(timezone.utc)``.
        ttl_days: The cache TTL in days. Defaults to
            :data:`DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS` (30).

    Returns:
        :class:`EmailVerificationCacheResult` carrying the hit/miss
        status + diagnostic context. The caller inspects
        ``result.is_cache_hit`` and dispatches on hit (call
        :func:`build_email_verification_cache_hit_payload` + emit
        the event + return ``result.cached_response``) or miss
        (proceed with the Reoon HTTP call as today + emit
        ``cost_incurred`` per ADR-0006 unchanged).

    Behavior:
        * Empty email OR ``ledger is None`` → miss (the caller falls
          through to the Reoon call; the cache simply provides no
          benefit for this lookup).
        * Ledger walk failure (OSError / unparseable events) → miss
          + stderr warning (best-effort observability; the
          verification proceeds).
        * Zero matching events → miss.
        * 1+ matching events within TTL → hit on the most-recent
          (highest ``ts``).
        * Pre-Pillar-E-Week-4 cost events lacking the ``email`` +
          ``verification_response`` fields → invisible (treated as
          miss); existing operators populate the cache going forward
          from the next Reoon call onward (per ADR-0034 §Existing-
          operator seed).

    Side effects: NONE. The lookup is read-only; the caller appends
    the cache_hit event via :func:`build_email_verification_cache_hit_payload`
    + the caller's own ledger handle.
    """
    if ledger is None or not email:
        return EmailVerificationCacheResult(
            is_cache_hit=False, email=email or "",
        )

    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ttl_days)
    target_email = email.lower()

    try:
        all_events = ledger.all_events()
    except (OSError, ValueError) as exc:
        sys.stderr.write(
            f"WARNING: email_verification_cache.lookup_cache ledger walk "
            f"failed for {email!r}: {exc}; treating as cache miss.\n"
        )
        return EmailVerificationCacheResult(
            is_cache_hit=False, email=email,
        )

    best: object | None = None
    best_ts: datetime | None = None
    for event in all_events:
        # ``event`` may be an :class:`Event` (post-:meth:`from_dict`)
        # or a plain dict (legacy path); both expose ``.get`` per the
        # Event class's dict-like surface.
        if event.get("type") != COST_INCURRED_TYPE:
            continue
        if event.get("source") != REOON_SOURCE:
            continue
        evt_email = event.get("email")
        if not evt_email or evt_email.lower() != target_email:
            continue
        ts_str = event.get("ts") or ""
        ts = _parse_iso_ts(ts_str)
        if ts is None or ts < cutoff:
            continue
        if best_ts is None or ts > best_ts:
            best = event
            best_ts = ts

    if best is None or best_ts is None:
        return EmailVerificationCacheResult(
            is_cache_hit=False, email=email,
        )

    response = best.get("verification_response")
    if not isinstance(response, dict):
        # Malformed cost event (email present but verification_response
        # missing or non-dict). Treat as miss — no payload to return;
        # caller falls through to Reoon. Operator-visible via the
        # absence of cache_hit events for this email.
        return EmailVerificationCacheResult(
            is_cache_hit=False, email=email,
        )

    age_days = int((now - best_ts).total_seconds() // 86400)
    return EmailVerificationCacheResult(
        is_cache_hit=True,
        email=email,
        cached_response=response,
        cached_at=best.get("ts"),
        cache_age_days=age_days,
        cached_person_id=best.get("person_id"),
    )


# ---------------------------------------------------------------------------
# Event payload factory
# ---------------------------------------------------------------------------


def build_email_verification_cache_hit_payload(
    result: EmailVerificationCacheResult,
    email: str,
    *,
    person_id: str | None = None,
) -> dict:
    """Construct the ``email_verification_cache_hit`` event payload (no append).

    Per ADR-0034 D155 + ADR-0032 D146. Single source of truth for the
    event shape — both the live-emit path (caller appends to ledger)
    and the dry-run / CLI path call this helper to avoid drift.
    Mirrors :func:`discovery_dedup.build_discovery_dedup_hit_payload`'s
    build-then-append separation (the Pillar E sibling primitive).

    Caller-consistency note: ``person_id`` defaults to the cached
    event's ``person_id`` (``result.cached_person_id``). The cache
    hit's natural attribution IS the original verification's
    attribution — the same Person whose email was first verified is
    typically the one being re-verified now. A caller in a different
    per-Person context (e.g., a manual operator-initiated lookup
    where the original cached event has no ``person_id``, or a
    cross-Person email lookup) MAY override via the ``person_id``
    kwarg.

    Event shape (per ADR-0034 D155):

    .. code-block:: text

        type: email_verification_cache_hit
        person_id              (the Person whose email was verified —
                                defaults to the cached event's person_id)
        email                  (the email looked up)
        cached_result          (the Reoon status string — "safe", "catch_all",
                                "invalid", "disposable", etc.; derived from
                                the cached response's status field)
        cached_at              (ISO 8601 of the originating cost_incurred event)
        cache_age_days         (computed at lookup time for operator audit)
        channel                ("email" per D146 channel-on-every-event invariant +
                                the cache primitive's email-channel-specific scope)
        _emitted_by            ("email_verification_cache" per ADR-0010 D17 convention)

    The event REPLACES (does not co-emit with) the ``cost_incurred``
    event per ADR-0032 D144 — the cache hit IS the cost-avoidance
    signal; co-emission would double-count in Pillar G's per-source
    cost dashboards.

    Raises:
        ValueError: if ``result.is_cache_hit`` is False — the
            cache_hit shape only applies to actual cache hits. The
            caller is expected to dispatch on ``result.is_cache_hit``
            before calling this factory (cache miss → proceed with
            Reoon HTTP call + existing ``cost_incurred`` emit; cache
            hit → call this factory + append the returned payload).
            Mirrors :func:`discovery_dedup.build_discovery_dedup_hit_payload`'s
            misdispatch-fails-loud convention.
    """
    if not result.is_cache_hit:
        raise ValueError(
            "build_email_verification_cache_hit_payload requires "
            f"is_cache_hit=True; got is_cache_hit={result.is_cache_hit!r}. "
            "The caller is expected to dispatch on result.is_cache_hit "
            "before calling this factory (cache miss → proceed with Reoon "
            "API call + existing cost_incurred emit; cache hit → call this "
            "factory + append the returned payload)."
        )
    resolved_person_id = (
        person_id if person_id is not None else result.cached_person_id
    )
    return {
        "type": "email_verification_cache_hit",
        "person_id": resolved_person_id,
        "email": email,
        "cached_result": result.cached_outcome,
        "cached_at": result.cached_at,
        "cache_age_days": result.cache_age_days,
        "channel": CHANNEL_VALUE,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# Internal — safe-append helper (mirrors discovery_dedup._safe_append)
# ---------------------------------------------------------------------------


def _safe_append(led: "_ledger.Ledger", event: dict) -> None:
    """Best-effort ledger append — mirrors :func:`discovery_dedup._safe_append`.

    A ledger I/O failure must not block the verification (the cache_hit
    event is the cost-attribution signal; losing it loses one row of
    Pillar G observability, not the cache behavior itself). Print
    stderr warning + continue.

    Per HANDOFF-pillar-e-week-4.md §Design-decisions: each Pillar
    primitive owns its own emit error handling per ADR-0033 D149's
    pillar-primitive-as-sibling shape (don't cross-import).
    """
    try:
        led.append(event)
    except (OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write(
            f"WARNING: ledger append failed for "
            f"{event.get('type')}: {exc}\n"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _ledger_dir() -> Path:
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return _ledger.DEFAULT_LEDGER_DIR


def main() -> None:
    p = argparse.ArgumentParser(
        description="Pillar E email-verification cache primitive (ADR-0034)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    lk = sub.add_parser(
        "lookup", help="Look up an email in the cache; report hit/miss + "
                       "optionally emit the cache_hit event.",
    )
    lk.add_argument("--email", required=True, help="Email address to look up")
    lk.add_argument(
        "--ttl-days", type=int,
        default=DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS,
        help=(f"Cache TTL in days "
              f"(default: {DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS} "
              "per ADR-0034 D157)"),
    )
    lk.add_argument(
        "--person-id", default=None,
        help="Override the person_id on the emitted event (defaults "
             "to the cached event's person_id)",
    )
    lk.add_argument(
        "--apply", action="store_true",
        help="Append the email_verification_cache_hit event to the "
             "ledger. Default is dry-run (report only).",
    )
    lk.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "lookup":
        led = _ledger.Ledger(_ledger_dir())
        result = lookup_cache(args.email, ledger=led, ttl_days=args.ttl_days)

        report: dict = {
            "ok": True,
            "is_cache_hit": result.is_cache_hit,
            "email": result.email,
            "ttl_days": args.ttl_days,
        }
        if result.is_cache_hit:
            payload = build_email_verification_cache_hit_payload(
                result, args.email, person_id=args.person_id,
            )
            report["cached_outcome"] = result.cached_outcome
            report["cached_at"] = result.cached_at
            report["cache_age_days"] = result.cache_age_days
            report["cached_person_id"] = result.cached_person_id
            report["payload"] = payload
            if args.apply:
                _safe_append(led, payload)
                report["applied"] = True

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"is_cache_hit: {report['is_cache_hit']}")
            if result.is_cache_hit:
                print(f"  cached_outcome:    {report['cached_outcome']}")
                print(f"  cached_at:         {report['cached_at']}")
                print(f"  cache_age_days:    {report['cache_age_days']}")
                print(f"  cached_person_id:  {report['cached_person_id']}")
                if report.get("applied"):
                    print("  ledger event appended.")
                else:
                    print("  (dry-run; pass --apply to emit the event "
                          "to the ledger.)")
            else:
                print(
                    f"  (no recent Reoon verification within "
                    f"{args.ttl_days} days; caller falls through to "
                    f"Reoon call.)"
                )
        sys.exit(0)


if __name__ == "__main__":
    main()
