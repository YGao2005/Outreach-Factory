"""Content distribution reconcile + engagement ingest (ADR-0082 D415/D416).

The broadcast analog of the cold-side reconcile Pass A, plus the engagement
feedback loop. Both READ the channel via the Scrapling MCP, which is a
Claude-callable tool, NOT importable Python. So the actual scraping lives in the
skill (an agent opens a stealthy cookie session, fetches a post URL, extracts the
counts with a CSS selector); THIS module is the pure, testable correlation +
delta + ledger-write logic the skill calls with the scraped values.

Read-back recovery (the Pass A analog)
--------------------------------------
The auto-publish path writes ``distribution_intent`` then calls the posting
client; if the process dies before ``distribution_confirmed``, the intent is
orphaned. :func:`find_orphaned_distribution_intents` finds those (no outcome,
older than a grace window); the skill scrapes the author's recent posts to find
the one that landed; :func:`synthesize_confirmed_from_readback` writes the
recovered ``distribution_confirmed`` with a ``_recovered_by="reconcile"`` marker.
(The draft-and-manual path writes no intent until the operator confirms, so it
produces no orphans; this covers the auto path's crash window.)

Engagement ingest (the feedback loop)
-------------------------------------
For each confirmed post, the skill scrapes the CUMULATIVE counts; this module
turns them into a DELTA (ADR-0082 D416) and appends ``engagement_observed`` only
when the delta is non-empty. Best-effort + honest: a failed or empty scrape
produces no event, and the report says "no signal" rather than a fabricated
number.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import ledger as _ledger  # noqa: E402
import content as _content  # noqa: E402


def _coerce(ev: object) -> dict:
    return ev.to_dict() if hasattr(ev, "to_dict") else dict(ev)  # type: ignore[arg-type]


def _parse_iso(s: object) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Read-back recovery (the Pass A analog)
# ---------------------------------------------------------------------------


def find_orphaned_distribution_intents(
    events: Iterable[object],
    *,
    now: datetime,
    min_age: timedelta = timedelta(minutes=5),
) -> list[dict]:
    """Distribution intents with no outcome yet, older than ``min_age``.

    The input to the read-back recovery: a ``distribution_intent`` whose
    ``intent_id`` has no paired ``distribution_confirmed`` / ``distribution_failed``,
    and which is old enough that it is not just mid-flight. Read-only.
    """
    intents: dict[str, dict] = {}
    closed: set[str] = set()
    for raw in events:
        ev = _coerce(raw)
        iid = ev.get("intent_id")
        if not iid:
            continue
        t = ev.get("type")
        if t == "distribution_intent":
            intents[iid] = ev
        elif t in ("distribution_confirmed", "distribution_failed"):
            closed.add(iid)
    cutoff = now - min_age
    out: list[dict] = []
    for iid, ev in intents.items():
        if iid in closed:
            continue
        ts = _parse_iso(ev.get("ts"))
        if ts is not None and ts > cutoff:
            continue  # still inside the grace window
        out.append(ev)
    return out


def synthesize_confirmed_from_readback(
    led: _ledger.Ledger, *, intent_event: dict, post_id: str,
) -> dict:
    """Recover a ``distribution_confirmed`` from a scraped post id (Pass A analog).

    Given an orphaned intent and the ``post_id`` the skill found by scraping the
    author's recent posts, synthesize the confirmed outcome, stamped
    ``_recovered_by="reconcile"`` so it is auditable as recovered, not original.
    """
    payload = _content.build_distribution_confirmed_payload(
        content_id=intent_event.get("content_id") or "",
        channel=intent_event.get("channel") or "",
        intent_id=intent_event.get("intent_id") or "",
        post_id=post_id,
        body_hash=intent_event.get("body_hash") or "",
    )
    payload["_recovered_by"] = "reconcile"
    led.append({**payload, "type": "distribution_confirmed"})
    return payload


# ---------------------------------------------------------------------------
# Engagement ingest (the feedback loop)
# ---------------------------------------------------------------------------


def posts_to_poll(events: Iterable[object]) -> list[dict]:
    """The confirmed posts whose engagement the skill should scrape.

    One entry per (content_id, channel, post_id) that has a
    ``distribution_confirmed``. The skill scrapes each post's URL for its
    cumulative counts and calls :func:`ingest_engagement`.
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    for raw in events:
        ev = _coerce(raw)
        if ev.get("type") != "distribution_confirmed":
            continue
        cid, ch, pid = ev.get("content_id"), ev.get("channel"), ev.get("post_id")
        if not (cid and ch and pid):
            continue
        key = (cid, ch, pid)
        if key in seen:
            continue
        seen.add(key)
        out.append({"content_id": cid, "channel": ch, "post_id": pid})
    return out


def ingest_engagement(
    led: _ledger.Ledger,
    *,
    content_id: str,
    channel: str,
    scraped_metrics: dict,
    observed_at: str,
) -> dict | None:
    """Append an ``engagement_observed`` DELTA from a fresh cumulative scrape.

    ``scraped_metrics`` is the current cumulative count the skill scraped (e.g.
    ``{"likes": 50}``). Computes the delta vs prior observations
    (:func:`content.compute_engagement_delta`) and appends only when it is
    non-empty. Returns the emitted delta, or None when there is nothing new (a
    no-op poll, or an empty/failed scrape - the honest "no signal" path).
    """
    if not scraped_metrics:
        return None
    delta = _content.compute_engagement_delta(
        led.all_events(), content_id, channel, scraped_metrics)
    if not delta:
        return None
    led.append({**_content.build_engagement_observed_payload(
        content_id=content_id, channel=channel, metrics=delta,
        observed_at=observed_at), "type": "engagement_observed"})
    return delta


__all__ = [
    "find_orphaned_distribution_intents",
    "ingest_engagement",
    "posts_to_poll",
    "synthesize_confirmed_from_readback",
]
