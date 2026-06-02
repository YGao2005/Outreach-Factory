"""Pillar C Week 6 — Cal.com webhook handler tests.

Per ADR-0019 D66 + D67 + D71:

* D66: FastAPI route + CLI replay share one parsing+emission core
  (:func:`orchestrator.cal_com_webhook.process_payload`). These tests
  exercise the core directly; the FastAPI / CLI wrappers are thin
  shims tested elsewhere (or via integration tests in Pillar I).
* D67: refuse-loud on HMAC signature mismatch. Tests assert that
  ``SignatureMismatchError`` raises + ``cal_com_webhook_rejected``
  emits + NO ``calendar_booking_confirmed`` lands.
* D71: schema-version cascade. Tests cover all four documented payload
  locations + the unknown-schema raise path.

Idempotence: Cal.com retries up to 5 times per their docs; the handler
short-circuits on re-receipt via the existing-confirmed-intent_id
check. Tests pin this.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest


# --- bootstrap (mirror test_send_gate_calendar_booking.py) ----------------

_REPO = Path(__file__).resolve().parent.parent
_ORCH = _REPO / "orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

import ledger as _ledger
import cal_com_webhook as wh


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SHARED_SECRET = "test-secret-do-not-use-in-prod-12345"


@pytest.fixture
def tmp_ledger(tmp_path):
    d = tmp_path / "ledger"
    d.mkdir()
    return _ledger.Ledger(d)


def _sign(body: bytes, secret: str = SHARED_SECRET) -> str:
    """Generate the HMAC-SHA256 signature header Cal.com would send."""
    return hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()


def _booking_payload(
    intent_id: str = "cb_TESTTESTTESTTESTTESTTESTTE",
    *,
    booking_id: str | int | None = "booking-123",
    location: str = "metadata",
    attendee_email: str | None = "guest@example.com",
    start_time: str | None = "2026-06-01T15:00:00Z",
    trigger: str = "BOOKING_CREATED",
) -> dict:
    """Construct a Cal.com webhook payload with the intent_id at the
    documented schema-version location.

    ``location`` selects which field carries the intent_id:
      * "metadata" → ``payload.metadata.intent_id``
      * "responses" → ``payload.responses.intent_id``
      * "booking_fields" → ``payload.bookingFieldsResponses.intent_id``
      * "originating_url" → ``payload.bookingURL`` (URL with ?intent_id=)
      * "none" → no intent_id anywhere (forces UnknownPayloadSchemaError)
    """
    inner: dict = {}
    if booking_id is not None:
        inner["bookingId"] = booking_id
    if attendee_email:
        inner["attendees"] = [{"email": attendee_email, "name": "Guest"}]
    if start_time:
        inner["startTime"] = start_time

    if location == "metadata":
        inner["metadata"] = {"intent_id": intent_id}
    elif location == "responses":
        inner["responses"] = {"intent_id": intent_id}
    elif location == "booking_fields":
        inner["bookingFieldsResponses"] = {"intent_id": intent_id}
    elif location == "originating_url":
        inner["bookingURL"] = f"https://cal.com/acme/intro?intent_id={intent_id}"
    elif location == "none":
        pass

    return {
        "triggerEvent": trigger,
        "payload": inner,
    }


def _raw(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# verify_signature
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_valid_signature_returns_true(self):
        body = b'{"a":1}'
        sig = _sign(body)
        assert wh.verify_signature(
            raw_body=body, signature_header=sig,
            shared_secret=SHARED_SECRET,
        ) is True

    def test_invalid_signature_returns_false(self):
        body = b'{"a":1}'
        assert wh.verify_signature(
            raw_body=body, signature_header="invalid_sig",
            shared_secret=SHARED_SECRET,
        ) is False

    def test_missing_signature_header_returns_false(self):
        body = b'{"a":1}'
        assert wh.verify_signature(
            raw_body=body, signature_header=None,
            shared_secret=SHARED_SECRET,
        ) is False

    def test_empty_shared_secret_returns_false(self):
        """An unconfigured webhook handler refuses-loud — per D67's
        misconfigured-deployment rationale."""
        body = b'{"a":1}'
        sig = _sign(body, "")
        assert wh.verify_signature(
            raw_body=body, signature_header=sig,
            shared_secret="",
        ) is False

    def test_sha256_prefix_accepted(self):
        """Common webhook convention prefixes the hex with ``sha256=``;
        the handler tolerates either form."""
        body = b'{"a":1}'
        sig = _sign(body)
        assert wh.verify_signature(
            raw_body=body, signature_header=f"sha256={sig}",
            shared_secret=SHARED_SECRET,
        ) is True

    def test_sha256_prefix_case_insensitive(self):
        """Per Week 6 per-week review webhook P2-1: the ``sha256=``
        prefix is stripped case-insensitively. Some webhook
        implementations emit ``SHA256=`` (HTTP header values are
        case-sensitive but case-conventions vary across providers);
        a case-sensitive strip would silently fail-closed on
        legitimately-signed payloads."""
        body = b'{"a":1}'
        sig = _sign(body)
        # Uppercase prefix.
        assert wh.verify_signature(
            raw_body=body, signature_header=f"SHA256={sig}",
            shared_secret=SHARED_SECRET,
        ) is True
        # Mixed case.
        assert wh.verify_signature(
            raw_body=body, signature_header=f"Sha256={sig}",
            shared_secret=SHARED_SECRET,
        ) is True

    def test_constant_time_compare_used(self):
        """The handler MUST use hmac.compare_digest (no timing leak).
        Sanity check by patching the import — if the implementation
        used == it would still pass tests, but the docstring + module
        symbol-reference asserts the discipline."""
        import inspect
        src = inspect.getsource(wh.verify_signature)
        assert "compare_digest" in src


# ---------------------------------------------------------------------------
# extract_intent_id — schema-version cascade (D71)
# ---------------------------------------------------------------------------


class TestExtractIntentId:
    def test_extracts_from_metadata(self):
        payload = _booking_payload(
            intent_id="cb_FROMMETADATA1234567890ABCDE",
            location="metadata",
        )
        iid, tag = wh.extract_intent_id(payload)
        assert iid == "cb_FROMMETADATA1234567890ABCDE"
        assert tag == "metadata"

    def test_extracts_from_responses(self):
        payload = _booking_payload(
            intent_id="cb_FROMRESPONSES1234567890ABC",
            location="responses",
        )
        iid, tag = wh.extract_intent_id(payload)
        assert iid == "cb_FROMRESPONSES1234567890ABC"
        assert tag == "responses"

    def test_extracts_from_booking_fields(self):
        payload = _booking_payload(
            intent_id="cb_FROMBOOKINGFIELDS1234567AB",
            location="booking_fields",
        )
        iid, tag = wh.extract_intent_id(payload)
        assert iid == "cb_FROMBOOKINGFIELDS1234567AB"
        assert tag == "booking_fields_responses"

    def test_extracts_from_originating_url(self):
        payload = _booking_payload(
            intent_id="cb_FROMURL1234567890ABCDEFGH",
            location="originating_url",
        )
        iid, tag = wh.extract_intent_id(payload)
        assert iid == "cb_FROMURL1234567890ABCDEFGH"
        assert tag == "originating_url"

    def test_extracts_from_responses_wrapped_value(self):
        """Per Week 6 per-week review webhook P2-4: some Cal.com
        responses wrap the intent_id value in ``{"value": ..., "label": ...}``.
        The handler tolerates either bare-string or wrapped-dict shape
        at the responses path."""
        payload = {
            "triggerEvent": "BOOKING_CREATED",
            "payload": {
                "responses": {
                    "intent_id": {
                        "value": "cb_WRAPPED12345678901234ABCD",
                        "label": "Internal ID",
                    },
                },
            },
        }
        iid, tag = wh.extract_intent_id(payload)
        assert iid == "cb_WRAPPED12345678901234ABCD"
        assert tag == "responses"

    def test_returns_none_when_intent_id_absent_everywhere(self):
        payload = _booking_payload(location="none")
        iid, tag = wh.extract_intent_id(payload)
        assert iid is None
        assert tag is None

    def test_priority_order_metadata_wins_over_responses(self):
        """When both metadata + responses carry an intent_id, metadata
        wins per the schema-version cascade priority."""
        payload = {
            "triggerEvent": "BOOKING_CREATED",
            "payload": {
                "metadata": {"intent_id": "cb_METADATA1234567890ABCDEFG"},
                "responses": {"intent_id": "cb_RESPONSES1234567890ABCDEF"},
            },
        }
        iid, tag = wh.extract_intent_id(payload)
        assert iid == "cb_METADATA1234567890ABCDEFG"
        assert tag == "metadata"

    def test_url_query_parser_with_ampersand(self):
        """Originating URL with multiple query params extracts cleanly."""
        payload = {
            "triggerEvent": "BOOKING_CREATED",
            "payload": {
                "bookingURL": (
                    "https://cal.com/acme/intro"
                    "?event=intro30&intent_id=cb_AMPERSAND123456789ABCDEF&"
                    "utm_source=email"
                ),
            },
        }
        iid, tag = wh.extract_intent_id(payload)
        assert iid == "cb_AMPERSAND123456789ABCDEF"
        assert tag == "originating_url"

    def test_top_level_payload_alias(self):
        """A bare top-level dict (no ``payload`` wrap) also works."""
        flat = {
            "triggerEvent": "BOOKING_CREATED",
            "metadata": {"intent_id": "cb_FLAT12345678901234567890123"},
        }
        # Cal.com always wraps with ``payload``; the helper's
        # tolerant-fallback behavior is for defensive parsing of
        # malformed integrations.
        iid, tag = wh.extract_intent_id(flat)
        assert iid == "cb_FLAT12345678901234567890123"
        assert tag == "metadata"


# ---------------------------------------------------------------------------
# process_payload — happy path
# ---------------------------------------------------------------------------


class TestProcessPayloadHappyPath:
    def test_emits_calendar_booking_confirmed(self, tmp_ledger):
        payload = _booking_payload()
        body = _raw(payload)
        sig = _sign(body)
        result = wh.process_payload(
            raw_body=body, signature_header=sig,
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        assert result.intent_id == "cb_TESTTESTTESTTESTTESTTESTTE"
        assert result.booking_id == "booking-123"
        assert result.already_processed is False
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert len(emitted) == 1
        ev = emitted[0]
        assert ev.get("channel") == "calendar"
        assert ev.get("intent_id") == "cb_TESTTESTTESTTESTTESTTESTTE"
        assert ev.get("calendar_booking_id") == "booking-123"
        assert ev.get("_emitted_by") == "cal_com_webhook"

    def test_emitted_event_carries_schema_version(self, tmp_ledger):
        """Per D71 + ADR-0019 §"Schema versioning": every emitted
        confirmed event records which schema location the intent_id
        was found at, so Pillar G observability can chart Cal.com
        schema-version drift over time."""
        payload = _booking_payload(location="metadata")
        body = _raw(payload)
        result = wh.process_payload(
            raw_body=body, signature_header=_sign(body),
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        assert result.schema_version == "metadata"
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert emitted[0].get("schema_version") == "metadata"

    def test_stamps_attendee_email_when_present(self, tmp_ledger):
        payload = _booking_payload(attendee_email="alice@acme.com")
        body = _raw(payload)
        wh.process_payload(
            raw_body=body, signature_header=_sign(body),
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert emitted[0].get("attendee_email") == "alice@acme.com"

    def test_stamps_booking_start_time_when_present(self, tmp_ledger):
        payload = _booking_payload(start_time="2026-06-15T10:00:00Z")
        body = _raw(payload)
        wh.process_payload(
            raw_body=body, signature_header=_sign(body),
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert emitted[0].get("booking_start_time") == "2026-06-15T10:00:00Z"


# ---------------------------------------------------------------------------
# process_payload — signature mismatch (D67 refuse-loud)
# ---------------------------------------------------------------------------


class TestSignatureMismatch:
    def test_invalid_signature_raises(self, tmp_ledger):
        payload = _booking_payload()
        body = _raw(payload)
        with pytest.raises(wh.SignatureMismatchError):
            wh.process_payload(
                raw_body=body, signature_header="bogus_sig",
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )

    def test_invalid_signature_emits_rejected_event(self, tmp_ledger):
        payload = _booking_payload()
        body = _raw(payload)
        try:
            wh.process_payload(
                raw_body=body, signature_header="bogus_sig",
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )
        except wh.SignatureMismatchError:
            pass
        rejected = [
            e for e in tmp_ledger.all_events()
            if e.type == "cal_com_webhook_rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0].get("reason") == "signature_mismatch"
        assert rejected[0].get("channel") == "calendar"

    def test_signature_mismatch_does_not_emit_confirmed(self, tmp_ledger):
        """The crucial security property: refuse-loud paths NEVER
        land a calendar_booking_confirmed (forged-honored would
        poison every downstream consumer)."""
        payload = _booking_payload()
        body = _raw(payload)
        try:
            wh.process_payload(
                raw_body=body, signature_header="bogus_sig",
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )
        except wh.SignatureMismatchError:
            pass
        confirmed = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert confirmed == []

    def test_empty_secret_refuses_loud(self, tmp_ledger):
        """Misconfigured deployment refuses every payload."""
        payload = _booking_payload()
        body = _raw(payload)
        sig = _sign(body, "")
        with pytest.raises(wh.SignatureMismatchError):
            wh.process_payload(
                raw_body=body, signature_header=sig,
                shared_secret="", led=tmp_ledger,
            )

    def test_verify_sig_false_bypass_is_explicit(self, tmp_ledger):
        """Per Week 6 per-week review webhook P2-3: pin the
        ``verify_sig=False`` test-only bypass as deliberate.

        Production callers always leave ``verify_sig=True``; the
        docstring names the kwarg as test-only. The regression pin
        ensures the bypass path stays explicitly opt-in (a future
        refactor that flipped the default would silently disable
        every operator's signature verification — a critical
        security regression).
        """
        payload = _booking_payload(
            intent_id="cb_BYPASS123456789012345ABCDE",
        )
        body = _raw(payload)
        # A deliberately-wrong signature.
        result = wh.process_payload(
            raw_body=body, signature_header="completely_invalid_sig",
            shared_secret=SHARED_SECRET, led=tmp_ledger,
            verify_sig=False,  # The test-only bypass per docstring.
        )
        # Even with the bad signature, the payload is processed.
        assert result.intent_id == "cb_BYPASS123456789012345ABCDE"
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert len(emitted) == 1
        # No rejected event emitted (signature was skipped, not failed).
        rejected = [
            e for e in tmp_ledger.all_events()
            if e.type == "cal_com_webhook_rejected"
        ]
        assert rejected == []


# ---------------------------------------------------------------------------
# process_payload — schema errors (D71)
# ---------------------------------------------------------------------------


class TestSchemaErrors:
    def test_no_intent_id_raises_unknown_schema(self, tmp_ledger):
        payload = _booking_payload(location="none")
        body = _raw(payload)
        with pytest.raises(wh.UnknownPayloadSchemaError):
            wh.process_payload(
                raw_body=body, signature_header=_sign(body),
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )

    def test_no_intent_id_emits_rejected_event(self, tmp_ledger):
        payload = _booking_payload(location="none")
        body = _raw(payload)
        try:
            wh.process_payload(
                raw_body=body, signature_header=_sign(body),
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )
        except wh.UnknownPayloadSchemaError:
            pass
        rejected = [
            e for e in tmp_ledger.all_events()
            if e.type == "cal_com_webhook_rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0].get("reason") == "no_intent_id"

    def test_invalid_json_raises_value_error(self, tmp_ledger):
        body = b"this is not json"
        with pytest.raises(ValueError):
            wh.process_payload(
                raw_body=body, signature_header=_sign(body),
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )

    def test_invalid_json_emits_rejected_event(self, tmp_ledger):
        body = b"not_json_at_all"
        try:
            wh.process_payload(
                raw_body=body, signature_header=_sign(body),
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )
        except ValueError:
            pass
        rejected = [
            e for e in tmp_ledger.all_events()
            if e.type == "cal_com_webhook_rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0].get("reason") == "invalid_json"

    def test_non_dict_json_payload_refuses_loud(self, tmp_ledger):
        """Per Week 6 per-week review webhook P1: valid JSON that parses
        to a non-dict (array / string / number / null) would pass HMAC
        verification but crash on payload.get(...) with an uncaught
        AttributeError. The handler refuses-loud at the type-guard
        AFTER signature verification + emits cal_com_webhook_rejected
        with reason=invalid_payload_shape."""
        # JSON array — valid syntactically but wrong shape.
        body = b'[{"triggerEvent": "BOOKING_CREATED"}]'
        with pytest.raises(ValueError, match="expected dict"):
            wh.process_payload(
                raw_body=body, signature_header=_sign(body),
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )
        rejected = [
            e for e in tmp_ledger.all_events()
            if e.type == "cal_com_webhook_rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0].get("reason") == "invalid_payload_shape"
        assert rejected[0].get("got_type") == "list"
        # No calendar_booking_confirmed (security property — the type
        # guard prevents the uncaught-exception path).
        confirmed = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert confirmed == []

    def test_non_dict_json_string_payload_refuses_loud(self, tmp_ledger):
        """A bare JSON string (e.g. ``"hello"``) also refuses-loud."""
        body = b'"just a string"'
        with pytest.raises(ValueError, match="expected dict"):
            wh.process_payload(
                raw_body=body, signature_header=_sign(body),
                shared_secret=SHARED_SECRET, led=tmp_ledger,
            )
        rejected = [
            e for e in tmp_ledger.all_events()
            if e.type == "cal_com_webhook_rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0].get("got_type") == "str"


# ---------------------------------------------------------------------------
# process_payload — idempotence (Cal.com retries up to 5 times)
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_re_receipt_short_circuits(self, tmp_ledger):
        """A re-receipt of the same payload emits no second
        calendar_booking_confirmed."""
        payload = _booking_payload(
            intent_id="cb_IDEMP1234567890ABCDEFGHIJ",
        )
        body = _raw(payload)
        sig = _sign(body)
        # First receipt.
        r1 = wh.process_payload(
            raw_body=body, signature_header=sig,
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        assert r1.already_processed is False
        # Second receipt (Cal.com retried).
        r2 = wh.process_payload(
            raw_body=body, signature_header=sig,
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        assert r2.already_processed is True
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert len(emitted) == 1

    def test_idempotence_keyed_by_intent_id(self, tmp_ledger):
        """The dedup key is intent_id (not booking_id). Two payloads
        for distinct bookings to the same intent_id are dedup'd; two
        payloads with same booking_id but distinct intent_ids are
        independent (would not normally happen — but tests the dedup
        criterion explicitly)."""
        body_a = _raw(_booking_payload(
            intent_id="cb_DEDUP1KEY1234567890ABCDEF",
        ))
        body_b = _raw(_booking_payload(
            intent_id="cb_DEDUP2KEY1234567890ABCDEF",
        ))
        wh.process_payload(
            raw_body=body_a, signature_header=_sign(body_a),
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        wh.process_payload(
            raw_body=body_b, signature_header=_sign(body_b),
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert len(emitted) == 2


# ---------------------------------------------------------------------------
# process_payload — trigger filtering
# ---------------------------------------------------------------------------


class TestTriggerFilter:
    def test_non_booking_created_trigger_ignored(self, tmp_ledger):
        """Cal.com's BOOKING_CANCELLED / RESCHEDULED / MEETING_ENDED
        are Pillar D's concern; the calendar webhook handler emits
        nothing for them."""
        payload = _booking_payload(trigger="BOOKING_CANCELLED")
        body = _raw(payload)
        result = wh.process_payload(
            raw_body=body, signature_header=_sign(body),
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert emitted == []
        assert any("BOOKING_CANCELLED" in err for err in result.errors)


# ---------------------------------------------------------------------------
# process_payload — apply=False (dry-run for CLI replay)
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_apply_false_emits_no_events(self, tmp_ledger):
        """``apply=False`` returns the would-emit event in
        ``ProcessResult.synthesized`` without writing to the ledger."""
        payload = _booking_payload(
            intent_id="cb_DRYRUN12345678901234567ABC",
        )
        body = _raw(payload)
        result = wh.process_payload(
            raw_body=body, signature_header=_sign(body),
            shared_secret=SHARED_SECRET, led=tmp_ledger,
            apply=False,
        )
        assert len(result.synthesized) == 1
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert emitted == []
        # The synthesized event has _dry_run: True (matches reconcile's
        # convention).
        assert result.synthesized[0].get("_dry_run") is True


# ---------------------------------------------------------------------------
# replay_from_file (CLI replay path)
# ---------------------------------------------------------------------------


class TestReplayFromFile:
    def test_replay_from_disk_path(self, tmp_path, tmp_ledger):
        """The CLI replay function reads a stored payload + processes."""
        payload = _booking_payload(
            intent_id="cb_REPLAY123456789012345ABCDE",
        )
        body = _raw(payload)
        sig = _sign(body)
        payload_path = tmp_path / "webhook_payload.json"
        payload_path.write_bytes(body)
        result = wh.replay_from_file(
            payload_path=payload_path, signature_header=sig,
            shared_secret=SHARED_SECRET, led=tmp_ledger,
            apply=True,
        )
        assert result.intent_id == "cb_REPLAY123456789012345ABCDE"
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert len(emitted) == 1

    def test_replay_default_is_dry_run(self, tmp_path, tmp_ledger):
        """Per ADR-0019 D66: CLI replay defaults to apply=False (safer
        ergonomic). Operators explicitly --apply when they're ready."""
        payload = _booking_payload(
            intent_id="cb_REPLAYNOAPPLY12345678ABCD",
        )
        body = _raw(payload)
        payload_path = tmp_path / "webhook_payload.json"
        payload_path.write_bytes(body)
        result = wh.replay_from_file(
            payload_path=payload_path, signature_header=_sign(body),
            shared_secret=SHARED_SECRET, led=tmp_ledger,
        )
        emitted = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert emitted == []
        assert len(result.synthesized) == 1


# ---------------------------------------------------------------------------
# list_orphan_booking_intents (audit surface per D68)
# ---------------------------------------------------------------------------


class TestListOrphanBookingIntents:
    def test_returns_orphan_intents(self, tmp_ledger):
        """A calendar_booking_intent without a paired _confirmed is an
        orphan; the audit function returns it."""
        tmp_ledger.append({
            "type": "calendar_booking_intent",
            "intent_id": "cb_ORPHAN1234567890ABCDEFGHIJ",
            "person_id": "alice-li", "channel": "calendar",
        })
        orphans = wh.list_orphan_booking_intents(tmp_ledger)
        assert len(orphans) == 1
        assert orphans[0]["intent_id"] == "cb_ORPHAN1234567890ABCDEFGHIJ"

    def test_excludes_confirmed_intents(self, tmp_ledger):
        """A calendar_booking_intent paired with a _confirmed event is
        NOT an orphan."""
        tmp_ledger.append({
            "type": "calendar_booking_intent",
            "intent_id": "cb_COMPLETE12345678901234567A",
            "person_id": "bob-li", "channel": "calendar",
        })
        tmp_ledger.append({
            "type": "calendar_booking_confirmed",
            "intent_id": "cb_COMPLETE12345678901234567A",
            "person_id": "bob-li", "channel": "calendar",
        })
        orphans = wh.list_orphan_booking_intents(tmp_ledger)
        assert orphans == []


# ---------------------------------------------------------------------------
# Module-level public-surface pinning
# ---------------------------------------------------------------------------


class TestModulePublicSurface:
    def test_module_exports(self):
        """Per ADR-0019 the module exposes the named symbols
        (regression pin against rename without ADR update)."""
        for name in (
            "process_payload",
            "replay_from_file",
            "verify_signature",
            "extract_intent_id",
            "list_orphan_booking_intents",
            "SignatureMismatchError",
            "UnknownPayloadSchemaError",
            "ProcessResult",
            "CAL_COM_SIGNATURE_HEADER",
            "CALENDAR_BOOKING_INTENT_ID_PREFIX",
            "CALENDAR_CHANNEL",
            "INTENT_ID_RE",
        ):
            assert hasattr(wh, name), (
                f"orchestrator.cal_com_webhook must expose {name!r} "
                f"per ADR-0019."
            )

    def test_signature_header_constant(self):
        assert wh.CAL_COM_SIGNATURE_HEADER == "X-Cal-Signature-256"

    def test_channel_constant(self):
        assert wh.CALENDAR_CHANNEL == "calendar"

    def test_intent_id_prefix_matches_dispatcher(self):
        """The webhook handler's prefix MUST match the dispatcher's
        prefix or the URL-fragment intent-id round-trip per D65
        breaks. Pin both sides."""
        assert wh.CALENDAR_BOOKING_INTENT_ID_PREFIX == "cb_"
