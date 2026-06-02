"""Cal.com webhook handler — calendar booking confirmed-event emission.

Pillar C Week 6 (ADR-0019). The asymmetric counterpart of Weeks 2-5's
synchronous dispatchers: the Calendar booking dispatcher
(``send_queued.py::gated_calendar_booking_one``) emits
``calendar_booking_intent`` at send time but does NOT call Cal.com; the
matching ``calendar_booking_confirmed`` arrives later via THIS module
when the recipient actually books a slot.

Architecture (per ADR-0019 D66)
-------------------------------

Two thin shims share one parsing + emission core:

* **FastAPI route** (or equivalent WSGI/ASGI handler): production
  surface. Cal.com POSTs the webhook to a public endpoint the
  orchestrator hosts; the route delegates to :func:`process_payload`.

* **CLI replay** (``python -m orchestrator.cal_com_webhook replay
  --payload-file <path>`` — wired in Pillar I OSS bring-up): testing +
  recovery surface. Operators with late / missing webhooks can replay
  a stored payload through the same parsing core. Pillar I exposes the
  CLI ergonomic; Week 6 ships the function the CLI wraps.

Both shims call :func:`process_payload` which is the single source of
truth for: HMAC verification (D67), payload parsing (D71), intent-id
extraction (D65), idempotence check (re-receipts of the same booking
emit at most one ``calendar_booking_confirmed``), event emission.

Security posture (per ADR-0019 D67)
-----------------------------------

REFUSE-LOUD on HMAC signature mismatch. Cal.com signs webhook payloads
with a shared secret + HMAC-SHA256 (header ``X-Cal-Signature-256``).
The handler MUST verify the signature on every inbound webhook;
mismatch → reject with :class:`SignatureMismatchError` (HTTP 401 at the
route layer) + log + emit a ``cal_com_webhook_rejected`` event with
the reason. The asymmetric-failure-cost calculus:

* **Missed legitimate webhook** = ledger doesn't reflect the booking;
  operator notices when the booking shows up in their calendar but the
  ledger doesn't show it. Recoverable via CLI replay.
* **Forged webhook honored** = fake ``calendar_booking_confirmed``
  emitted; cross-channel rule fires against a non-existent event;
  downstream consumers (Pillar D reply-correlator, Pillar G
  observability, Pillar I tenant isolation) carry biased state.

The asymmetry — missed-legitimate is recoverable, forged-honored is
ledger-poisoning — biases the gate to refuse-loud. The empty-shared-
secret edge case (operator hasn't configured the secret yet) also
refuses-loud: an unconfigured webhook handler is a misconfigured
deployment, not a missing feature.

Schema versioning (per ADR-0019 D71)
------------------------------------

Cal.com has shipped multiple breaking payload-shape changes
historically. The handler reads ``triggerEvent`` + ``payload`` from
the top-level dict; intent_id extraction tries multiple locations in
priority order:

1. ``payload.metadata.intent_id`` (Cal.com's documented custom-input
   surface; the operator-default integration path).
2. ``payload.responses.intent_id`` (Cal.com's older custom-questions
   surface; pre-2024 deployments).
3. ``payload.bookingFieldsResponses.intent_id`` (Cal.com's newest
   booking-fields surface; 2025+ deployments).
4. The URL query string (the dispatcher's URL fragment per D65)
   parsed from ``payload.responses.location.value`` / similar
   originating-URL preservation. Last-resort fallback.

Unknown schema versions fall back to (4); a payload that exposes the
intent_id NOWHERE refuses-loud with :class:`UnknownPayloadSchemaError`
because the orchestrator cannot correlate the booking to its
originating intent without it.

Idempotence
-----------

Cal.com retries failed webhooks up to 5 times with exponential
backoff. The handler MUST be idempotent: a re-receipt of the same
``booking_id`` (or, when the booking_id is absent, the same intent_id)
emits at most one ``calendar_booking_confirmed``. The check is:

* Walk existing ``calendar_booking_confirmed`` events.
* If any carries the same ``intent_id`` (load-bearing field per
  ADR-0014 D33), short-circuit + return :class:`ProcessResult` with
  ``already_processed=True``.

Pillar I (multi-tenant) is the right home for tenant-scoped
idempotence keys; Week 6's single-tenant shape is the floor.

Dry-run + observability
-----------------------

The ``apply`` parameter to :func:`process_payload` matches reconcile's
convention: ``apply=True`` writes events; ``apply=False`` returns the
events that would be emitted without writing. Useful for the CLI
replay path's preflight surface (operators see what the handler would
do before they commit).

Cross-pillar impact
-------------------

* Pillar D's reply-correlator reads the ``calendar_booking_confirmed``
  event's ``intent_id`` to attribute calendar bookings to their
  originating outreach (which channel scheduled the booking).
* Pillar G observability per-channel funnel includes the calendar
  channel via the ``channel: calendar`` field stamp.
* Pillar I multi-tenant: a future per-tenant webhook handler routes
  inbound payloads to the right tenant's ledger via a tenant-id query
  param on the booking URL (e.g.
  ``cal.com/yourhandle/intro?intent_id=cb_<ULID>&tenant=acme``).

See ADR-0019 for the full Week 6 design.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import ledger as _ledger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# The signature header Cal.com sends per their webhook docs.
CAL_COM_SIGNATURE_HEADER = "X-Cal-Signature-256"
# Channel value per ADR-0014 D33.
CALENDAR_CHANNEL = "calendar"
# Intent-id prefix the dispatcher mints (per ADR-0019 D65 +
# ``send_queued.py::CALENDAR_BOOKING_INTENT_ID_PREFIX``). The webhook
# handler uses this to quickly classify "is this a calendar booking
# intent_id?" when scanning ambiguous strings.
CALENDAR_BOOKING_INTENT_ID_PREFIX = "cb_"
# Intent-id regex — anywhere the URL/payload exposes the intent_id, it
# matches ``cb_<26-char ULID>``. Pillar D's reply-classifier will reuse
# this regex to scan inbound reply bodies for the calendar booking
# intent_id when the recipient's reply references the booking.
INTENT_ID_RE = re.compile(r"(cb_[0-9A-HJKMNP-TV-Z]{26})")


# ---------------------------------------------------------------------------
# Result + error types
# ---------------------------------------------------------------------------


@dataclass
class ProcessResult:
    """What :func:`process_payload` did (or would do under dry-run).

    Mirrors the ``PassResult`` shape from :mod:`orchestrator.reconcile`
    so Pillar G observability can normalize across reconcile + webhook
    surfaces. The ``synthesized`` field carries the events the handler
    emitted (or would emit on ``apply=False``); the ``errors`` field
    carries non-fatal issues (the handler returns instead of raising
    when a schema-version fallback succeeds with a warning).
    """
    apply: bool
    already_processed: bool = False
    synthesized: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    booking_id: str | None = None
    intent_id: str | None = None
    schema_version: str | None = None


class SignatureMismatchError(Exception):
    """Raised when the inbound webhook's HMAC signature fails to verify.

    Per ADR-0019 D67's refuse-loud posture — every inbound webhook that
    fails verification is rejected (HTTP 401 at the route layer), the
    payload is dropped without emitting ``calendar_booking_confirmed``,
    and a ``cal_com_webhook_rejected`` event is appended to the ledger
    for operator visibility.
    """


class UnknownPayloadSchemaError(Exception):
    """Raised when the payload exposes no intent_id at any of the
    documented schema-version locations (per ADR-0019 D71).

    The handler tried metadata + responses + bookingFieldsResponses +
    the originating-URL query string; the intent_id is nowhere. Cal.com
    may have shipped another breaking schema change; the operator
    should investigate the payload and decide whether to extend the
    handler's parser or to manually emit the
    ``calendar_booking_confirmed`` via CLI.
    """


# ---------------------------------------------------------------------------
# HMAC signature verification (D67)
# ---------------------------------------------------------------------------


def verify_signature(
    *,
    raw_body: bytes,
    signature_header: str | None,
    shared_secret: str,
) -> bool:
    """Verify an inbound webhook's HMAC-SHA256 signature.

    Returns ``True`` if the signature matches; ``False`` otherwise.
    Refuses-loud (``False``) on:

    * Empty ``shared_secret`` — an unconfigured webhook handler is a
      misconfigured deployment, not a missing feature.
    * Missing ``signature_header`` — Cal.com always sends the
      ``X-Cal-Signature-256`` header on valid payloads; absent → bias
      toward refuse.
    * Bytes / hex mismatch — the canonical HMAC failure mode.

    Per ADR-0019 D67's asymmetric-failure-cost calculus: a forged
    payload that passed verification would emit a fake
    ``calendar_booking_confirmed`` and bias every downstream consumer;
    refusing-loud forecloses that path at the cost of operators
    needing to debug genuine signature mismatches.

    Uses :func:`hmac.compare_digest` for constant-time comparison
    (no timing-side-channel leak on the prefix that did match).
    """
    if not shared_secret:
        return False
    if not signature_header:
        return False
    expected = hmac.new(
        shared_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    # Cal.com's header may include a ``sha256=`` prefix per common
    # webhook conventions; strip it case-insensitively (some webhook
    # implementations emit ``SHA256=`` instead of ``sha256=``, and
    # rejecting those would be a silent availability failure rather
    # than a security gain — fail-closed on bytes mismatch is still
    # the failure mode for any forgery). Per Week 6 per-week review
    # webhook P2-1.
    candidate = signature_header
    if candidate[:7].lower() == "sha256=":
        candidate = candidate[7:]
    return hmac.compare_digest(expected, candidate)


# ---------------------------------------------------------------------------
# Intent-id extraction (D65 + D71)
# ---------------------------------------------------------------------------


def _extract_intent_id_from_url(url: str) -> str | None:
    """Pull ``cb_<ULID>`` out of a URL's query string.

    Cal.com preserves the originating booking URL in some payload
    shapes (per D71's schema-version observation); when the URL
    contains the dispatcher's ``?intent_id=cb_<ULID>`` query param,
    the handler reads it directly. Falls back to regex over the
    whole URL string for the (rare) case where the URL is
    URL-encoded oddly or the query-param parser fails.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        candidate = qs.get("intent_id", [None])[0]
        if candidate and candidate.startswith(CALENDAR_BOOKING_INTENT_ID_PREFIX):
            return candidate
    except Exception:
        pass
    # Last-resort regex scan over the URL string.
    m = INTENT_ID_RE.search(url)
    return m.group(1) if m else None


def extract_intent_id(payload: dict) -> tuple[str | None, str | None]:
    """Extract the booking's intent_id + the schema-version it lived in.

    Returns ``(intent_id, schema_version_tag)`` where ``schema_version_tag``
    is one of:

    * ``"metadata"`` — Cal.com's documented custom-input metadata block
      (the operator-default integration surface, 2024+).
    * ``"responses"`` — Cal.com's older custom-questions surface
      (pre-2024 deployments).
    * ``"booking_fields_responses"`` — Cal.com's newest booking-fields
      surface (2025+ deployments).
    * ``"originating_url"`` — last-resort fallback; the originating URL
      preserved somewhere in the payload (typically
      ``payload.bookingFieldsResponses.location`` or similar).

    Returns ``(None, None)`` if no intent_id is exposed anywhere in
    the payload; the caller raises :class:`UnknownPayloadSchemaError`.

    Per ADR-0019 D71's schema-versioning rationale: Cal.com has
    shipped multiple breaking shape changes; the handler's parser
    walks the documented locations in priority order. If a future
    Cal.com release ships another shape, extend this function with a
    new branch + a regression test.
    """
    if not isinstance(payload, dict):
        return None, None
    inner = payload.get("payload")
    if not isinstance(inner, dict):
        inner = payload

    # 1. payload.metadata.intent_id (Cal.com's documented surface).
    metadata = inner.get("metadata")
    if isinstance(metadata, dict):
        candidate = metadata.get("intent_id")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip(), "metadata"

    # 2. payload.responses.intent_id (older custom-questions surface).
    # Per Week 6 per-week review webhook P2-4: read once + branch by
    # shape (string OR {"value": str, "label": str} wrapper).
    responses = inner.get("responses")
    if isinstance(responses, dict):
        raw = responses.get("intent_id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip(), "responses"
        if isinstance(raw, dict):
            # Some Cal.com responses wrap values in
            # ``{"value": ..., "label": ...}``.
            val = raw.get("value")
            if isinstance(val, str) and val.strip():
                return val.strip(), "responses"

    # 3. payload.bookingFieldsResponses.intent_id (newest 2025+ surface).
    bfr = inner.get("bookingFieldsResponses")
    if isinstance(bfr, dict):
        candidate = bfr.get("intent_id")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip(), "booking_fields_responses"

    # 4. Originating-URL fallback. Multiple keys to check; the URL
    # might live under ``location.value`` (older), ``bookingURL`` (newer),
    # or ``referrer`` (some integrations).
    for key in ("bookingURL", "referrer", "booking_url"):
        url = inner.get(key)
        if isinstance(url, str):
            iid = _extract_intent_id_from_url(url)
            if iid:
                return iid, "originating_url"
    # location is sometimes wrapped.
    location = inner.get("location")
    if isinstance(location, dict):
        url = location.get("value") or location.get("url")
        if isinstance(url, str):
            iid = _extract_intent_id_from_url(url)
            if iid:
                return iid, "originating_url"
    elif isinstance(location, str):
        iid = _extract_intent_id_from_url(location)
        if iid:
            return iid, "originating_url"

    return None, None


def _extract_booking_id(payload: dict) -> str | None:
    """Pull Cal.com's per-booking identifier out of the payload.

    Cal.com identifies bookings via various keys depending on schema
    version: ``payload.bookingId`` (numeric, older), ``payload.uid``
    (string-UUID, newer), or ``payload.id``. The handler tries each
    in priority order. Returns ``None`` if the payload doesn't expose
    any of them — the handler still emits ``calendar_booking_confirmed``
    keyed by intent_id; the ``booking_id`` field on the emitted event
    is just ``None``.
    """
    if not isinstance(payload, dict):
        return None
    inner = payload.get("payload")
    if not isinstance(inner, dict):
        inner = payload
    for key in ("bookingId", "uid", "id"):
        candidate = inner.get(key)
        if candidate is None:
            continue
        return str(candidate)
    return None


# ---------------------------------------------------------------------------
# Idempotence check
# ---------------------------------------------------------------------------


def _already_confirmed(
    led: _ledger.Ledger,
    *,
    intent_id: str,
) -> bool:
    """Return True if a calendar_booking_confirmed already exists for
    ``intent_id``.

    Per ADR-0019 D66's idempotence requirement: Cal.com retries failed
    webhooks up to 5 times. The handler MUST be idempotent — a
    re-receipt emits at most one ``calendar_booking_confirmed``. The
    ledger's append-only structure means the natural shape is "scan
    existing _confirmed events; short-circuit on match" — which is
    what this function does.

    **Concurrency caveat (Week 6 per-week review webhook P2-2).**
    The check below uses ``_build_indexes(force=True)`` to force a
    fresh disk read on every call, which narrows the TOCTOU window
    between two ASGI workers handling simultaneous Cal.com retries.
    The window cannot be eliminated at this layer (a true compare-and-
    swap on append would require ledger-engine changes); the residual
    risk is two concurrent webhooks for the same intent_id BOTH passing
    the check before EITHER's ``led.append`` completes its fsync. In
    practice Cal.com's retry schedule (exponential backoff starting at
    ~30s) makes this near-impossible; Pillar H's daemon (single-process
    webhook consumer) closes the window entirely.

    Future Pillar G observability optimization: if the ledger grows
    large enough that the linear scan becomes hot, swap to an indexed
    lookup. Today's shape matches the rest of the framework's
    "walk-the-ledger-once" convention (cf. reconcile.run_pass_a).
    """
    # Force a fresh disk read so two ASGI workers handling Cal.com's
    # webhook retries don't both fail to see a competing append because
    # of mtime-stale index caches.
    led._build_indexes(force=True)
    for ev in led.all_events():
        if ev.type != "calendar_booking_confirmed":
            continue
        if ev.intent_id == intent_id:
            return True
    return False


# ---------------------------------------------------------------------------
# Core payload processor (the function both FastAPI + CLI replay wrap)
# ---------------------------------------------------------------------------


def process_payload(
    *,
    raw_body: bytes,
    signature_header: str | None,
    shared_secret: str,
    led: _ledger.Ledger,
    apply: bool = True,
    verify_sig: bool = True,
) -> ProcessResult:
    """Verify + parse + emit. The single source of truth both shims wrap.

    The processing pipeline (per ADR-0019 D66 + D67 + D68 + D71):

    1. Verify HMAC signature (D67 refuse-loud on mismatch).
    2. Parse JSON body. JSON parse failure emits a
       ``cal_com_webhook_rejected`` event + raises.
    3. Extract intent_id (D71 schema-version cascade). Missing →
       :class:`UnknownPayloadSchemaError` + rejected-event emission.
    4. Check idempotence (already_processed short-circuit).
    5. Emit ``calendar_booking_confirmed`` with channel=calendar +
       intent_id + booking_id + booking_url (round-tripped from the
       payload) + ``_emitted_by: "cal_com_webhook"`` for observability
       (distinct from ``_recovered_by: "reconcile"`` per ADR-0010's
       convention — the calendar-confirmed event has neither
       backfill-origin nor reconcile-origin; it's the canonical
       organic webhook emission).

    The trigger-event check ensures the handler only processes
    BOOKING_CREATED webhooks (not the various other Cal.com event
    types like BOOKING_RESCHEDULED, BOOKING_CANCELLED, MEETING_ENDED).
    BOOKING_CANCELLED is Pillar D's conversation-state concern per
    ADR-0014 D33 + ADR-0019 D70; handling it here would muddy the
    semantic boundary.

    Parameters
    ----------
    raw_body : bytes
        The exact bytes Cal.com POSTed. The HMAC verifies against
        these bytes (NOT a re-serialized dict — JSON round-trip
        changes byte-level whitespace, which breaks HMAC).
    signature_header : str | None
        Value of the ``X-Cal-Signature-256`` HTTP header.
    shared_secret : str
        Operator-configured webhook secret. From the operator's
        Cal.com dashboard.
    led : Ledger
        The ledger handle for emission.
    apply : bool
        ``True`` writes events to the ledger; ``False`` returns the
        events that would be emitted (used by the CLI replay --dry-run
        path).
    verify_sig : bool
        ``True`` (default) performs signature verification per D67;
        ``False`` skips it. Test fixtures pass ``verify_sig=False``
        with a known-bad secret to exercise the parsing path without
        forging HMAC signatures; PRODUCTION must always leave it
        ``True``.

    Raises
    ------
    SignatureMismatchError:
        Signature verification failed (refuse-loud per D67).
    UnknownPayloadSchemaError:
        Payload exposed no intent_id at any documented location.
    ValueError:
        JSON body could not be parsed.
    """
    result = ProcessResult(apply=apply)

    # 1. HMAC signature verification (D67 refuse-loud).
    if verify_sig:
        if not verify_signature(
            raw_body=raw_body,
            signature_header=signature_header,
            shared_secret=shared_secret,
        ):
            if apply:
                try:
                    led.append({
                        "type": "cal_com_webhook_rejected",
                        "channel": CALENDAR_CHANNEL,
                        "reason": "signature_mismatch",
                    })
                except Exception:  # pragma: no cover — ledger should not fail here
                    pass
            raise SignatureMismatchError(
                "Cal.com webhook HMAC signature did not match the "
                "operator's shared secret. Per ADR-0019 D67 the "
                "handler refuses-loud on signature mismatch."
            )

    # 2. JSON parse.
    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError) as exc:
        if apply:
            try:
                led.append({
                    "type": "cal_com_webhook_rejected",
                    "channel": CALENDAR_CHANNEL,
                    "reason": "invalid_json",
                    "error": f"{type(exc).__name__}: {exc}",
                })
            except Exception:  # pragma: no cover
                pass
        raise ValueError(
            f"Cal.com webhook body could not be parsed as JSON: "
            f"{type(exc).__name__}: {exc}"
        )

    # P1 from Week 6 per-week review (webhook handler): valid JSON that
    # parses to a non-dict (array / string / number / null) would pass
    # the HMAC check but then crash on ``payload.get(...)`` with an
    # uncaught ``AttributeError`` — propagating out of the route layer
    # as a 500, which Cal.com retries silently. Refuse-loud + emit a
    # rejected event so operators see the failure mode.
    if not isinstance(payload, dict):
        if apply:
            try:
                led.append({
                    "type": "cal_com_webhook_rejected",
                    "channel": CALENDAR_CHANNEL,
                    "reason": "invalid_payload_shape",
                    "got_type": type(payload).__name__,
                })
            except Exception:  # pragma: no cover
                pass
        raise ValueError(
            f"Cal.com webhook body parsed as "
            f"{type(payload).__name__!s}; expected dict per Cal.com's "
            f"documented payload shape."
        )

    # Trigger-event filter — only BOOKING_CREATED triggers an emit.
    # Cal.com's other trigger events (BOOKING_RESCHEDULED,
    # BOOKING_CANCELLED, MEETING_ENDED) are Pillar D's concern per
    # ADR-0014 D33's calendar_booking_cancelled distinction.
    trigger = (payload.get("triggerEvent") or "").strip().upper()
    if trigger and trigger != "BOOKING_CREATED":
        # Not an error; just a no-op. Emit nothing.
        result.errors.append(
            f"ignored non-BOOKING_CREATED trigger {trigger!r} "
            f"(Pillar D handles the other event types)"
        )
        return result

    # 3. Extract intent_id (D71 schema-version cascade).
    intent_id, schema_tag = extract_intent_id(payload)
    if not intent_id:
        if apply:
            try:
                led.append({
                    "type": "cal_com_webhook_rejected",
                    "channel": CALENDAR_CHANNEL,
                    "reason": "no_intent_id",
                })
            except Exception:  # pragma: no cover
                pass
        raise UnknownPayloadSchemaError(
            "Cal.com webhook payload exposed no intent_id at any of "
            "the documented locations (metadata / responses / "
            "bookingFieldsResponses / originating URL). Cal.com may "
            "have shipped a new schema shape; extend the handler's "
            "extract_intent_id() function with a new branch + a "
            "regression test."
        )
    result.intent_id = intent_id
    result.schema_version = schema_tag

    # 4. Idempotence check (Cal.com retries up to 5 times).
    if _already_confirmed(led, intent_id=intent_id):
        result.already_processed = True
        return result

    # 5. Emit calendar_booking_confirmed.
    booking_id = _extract_booking_id(payload)
    result.booking_id = booking_id

    # Pull a few diagnostic fields from the payload for observability.
    # Most Cal.com payloads carry attendee email / name / start time;
    # the handler stamps them on the confirmed event so Pillar G's
    # per-channel funnel dashboard can chart booking-to-call attribution
    # without re-fetching from Cal.com.
    inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    attendee_email: str | None = None
    if isinstance(inner, dict):
        attendees = inner.get("attendees")
        if isinstance(attendees, list) and attendees:
            first = attendees[0]
            if isinstance(first, dict):
                ae = first.get("email")
                if isinstance(ae, str):
                    attendee_email = ae

    start_time = None
    if isinstance(inner, dict):
        start_raw = inner.get("startTime") or inner.get("start_time")
        if isinstance(start_raw, str):
            start_time = start_raw

    event = {
        "type": "calendar_booking_confirmed",
        "intent_id": intent_id,
        "channel": CALENDAR_CHANNEL,
        "_emitted_by": "cal_com_webhook",
        "schema_version": schema_tag,
    }
    if booking_id:
        event["calendar_booking_id"] = booking_id
    if attendee_email:
        event["attendee_email"] = attendee_email
    if start_time:
        event["booking_start_time"] = start_time

    if apply:
        try:
            led.append(event)
        except Exception as exc:
            result.errors.append(
                f"ledger append failed for calendar_booking_confirmed "
                f"({intent_id}): {type(exc).__name__}: {exc}"
            )
            return result
    else:
        event["_dry_run"] = True
    result.synthesized.append(event)
    return result


# ---------------------------------------------------------------------------
# CLI replay surface (per ADR-0019 D66 — operator-deferred to Pillar I
# OSS bring-up's wider CLI ergonomic, but the function the CLI wraps
# ships here so tests can exercise the replay path directly)
# ---------------------------------------------------------------------------


def replay_from_file(
    *,
    payload_path: Path,
    signature_header: str | None,
    shared_secret: str,
    led: _ledger.Ledger,
    apply: bool = False,
    verify_sig: bool = True,
) -> ProcessResult:
    """Replay a stored Cal.com webhook payload from disk.

    Per ADR-0019 D66, the CLI replay path is the operator's recovery
    surface for missed / dead-lettered webhooks. Operators store the
    raw Cal.com payload (e.g. captured via the Cal.com dashboard's
    webhook history view) + their HTTP request's signature header, then
    invoke this function via a Pillar I CLI wrapper.

    ``apply=False`` (default) is the safer ergonomic — the operator
    sees what the handler WOULD emit before committing. ``apply=True``
    writes the event.

    Why default-dry-run vs the route's default-apply: the route is
    Cal.com's automatic POST surface (apply must default-True or
    bookings would never confirm); the CLI replay is operator-deliberate
    (apply must default-False or a misclick churns ledger state).
    """
    raw_body = payload_path.read_bytes()
    return process_payload(
        raw_body=raw_body,
        signature_header=signature_header,
        shared_secret=shared_secret,
        led=led,
        apply=apply,
        verify_sig=verify_sig,
    )


# ---------------------------------------------------------------------------
# Convenience: scan ledger for orphans (per ADR-0019 D68's deferred
# Pass G discussion — the function ships now so Pillar I operators can
# audit late-webhook state without waiting for a periodic reconcile pass)
# ---------------------------------------------------------------------------


def list_orphan_booking_intents(
    led: _ledger.Ledger,
    *,
    since: datetime | None = None,
) -> list[dict]:
    """Return ``calendar_booking_intent`` events without matching
    ``calendar_booking_confirmed`` (operator audit surface).

    Per ADR-0019 D68's recommended deferral of Pass G: the Cal.com
    webhook is the canonical recovery surface, so a periodic reconcile
    pass would duplicate effort. But operators occasionally want to
    audit "which calendar booking links never got booked?" — this
    function is that audit's foundation.

    Different from Pass G in two ways:

    1. **No grace-period abort emission.** The function only ENUMERATES
       orphans; it doesn't emit ``calendar_booking_aborted`` (which
       doesn't exist per ADR-0014 D33 anyway — calendar bookings have
       no abort case at the dispatcher level).
    2. **Operator-pull, not periodic-push.** Operators invoke this via
       a Pillar I CLI ergonomic when they want the audit; the
       framework doesn't run it on a schedule.

    If operational experience surfaces a recurring need for periodic
    aborts (e.g., "calendars get cluttered with abandoned booking
    links"), Pillar I can ship a Pass G in a future per-week-review
    follow-up. D68 names this as the deferred path.
    """
    confirmed_intent_ids: set[str] = set()
    intents: dict[str, dict] = {}
    for ev in led.all_events():
        if ev.type == "calendar_booking_intent":
            # P3 from Week 6 per-week review webhook: skip events
            # missing intent_id (e.g., written by a buggy earlier
            # release) — emitting them as `None`-keyed orphans would
            # confuse Pillar I's CLI rendering.
            if not ev.intent_id:
                continue
            if since is not None:
                try:
                    ev_ts = datetime.fromisoformat(
                        ev.ts.replace("Z", "+00:00"),
                    )
                except (ValueError, AttributeError):
                    continue
                if ev_ts < since:
                    continue
            intents[ev.intent_id] = {
                "intent_id": ev.intent_id,
                "person_id": ev.person_id,
                "ts": ev.ts,
            }
        elif ev.type == "calendar_booking_confirmed":
            if ev.intent_id:
                confirmed_intent_ids.add(ev.intent_id)
    return [
        v for k, v in intents.items()
        if k not in confirmed_intent_ids
    ]


__all__ = [
    "CAL_COM_SIGNATURE_HEADER",
    "CALENDAR_BOOKING_INTENT_ID_PREFIX",
    "CALENDAR_CHANNEL",
    "INTENT_ID_RE",
    "ProcessResult",
    "SignatureMismatchError",
    "UnknownPayloadSchemaError",
    "extract_intent_id",
    "list_orphan_booking_intents",
    "process_payload",
    "replay_from_file",
    "verify_signature",
]
