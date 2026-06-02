"""Pillar D Week 4-5 — auto-unsubscribe handler.

Per ADR-0025 D100 + ADR-0026 D107 + ADR-0028: the handler reads
``reply_classified`` events filtered to ``category=unsubscribe`` and
writes the matching email / domain / identity_key to the
auto-unsubscribe suppression YAML. The next dispatcher gate refuses
the next send to the prospect (CAN-SPAM compliance posture preserved).

The write contract is **YAML-first + ledger-second** per ADR-0025
D100's load-bearing write order:

  1. ``forget_append`` writes the email / domain / identity_key to
     ``~/.outreach-factory/suppressions/auto-unsubscribe.yml`` via the
     existing Pillar A primitive (ADR-0004). The file is updated
     atomically (write-temp-then-rename). After this returns, the
     suppression is LIVE — any dispatcher that subsequently calls
     ``load_suppression_dir`` on a gate evaluation sees the new entry.
  2. The handler appends a ``suppression_added`` event to the ledger
     correlating back to the originating ``reply_classified`` event.

If the YAML write succeeds + the ledger append fails (crash, disk
full, etc.), the suppression is LIVE despite the audit trail being
incomplete. The reconcile pass surfaces the inconsistency on next run.

If the YAML write fails, the handler propagates the exception — no
``suppression_added`` lands. Operator sees the failure; the
classification stays in the ledger; re-running the handler on next
``--full`` retries (idempotent — see below).

Idempotence — per ADR-0028 D117 (carry-forward of the Week 2 P2-B
finding):

  The handler deduplicates by ``(reply_message_id, channel)`` before
  writing. Concurrent Pass G runs (Pillar H daemon + a manual
  ``--passes G`` invocation racing on the in-memory idempotence index)
  CAN produce duplicate ``reply_classified`` events for the same
  ``(reply_message_id, channel)`` pair per ADR-0026 §Negative
  consequences. A naive handler would double-write to the YAML +
  emit two ``suppression_added`` events for one real unsubscribe
  action — the YAML content is set-idempotent so no corruption, but
  the audit trail diverges + Pillar G dashboards double-count.

  The handler builds:

  * ``already_suppressed`` — the set of (reply_message_id, channel)
    pairs already covered by a ``suppression_added`` event in the
    ledger. Cross-run idempotence.

  * ``seen_this_batch`` — the set of (reply_message_id, channel) pairs
    seen WITHIN the current handler invocation. Within-run defense
    against duplicate classified events Pass G may have emitted on a
    race.

The handler reuses ``policy.suppression.forget_append`` (the existing
Pillar A primitive per ADR-0004); the suppression-rule contract is
UNCHANGED. The handler is a NEW caller of the existing primitive.

Suppression-target dimension resolution
---------------------------------------

The handler resolves the (dimension, value) target per channel:

* ``channel == "email"``: look up the originating reply event by
  ``reply_message_id`` (the gmail_message_id on Pass B's emit shape);
  parse the ``from`` header for the email address; emit
  ``suppressed_dimension=email``. If the email cannot be resolved
  (legacy emit without ``from`` header, malformed header), fall back
  to ``suppressed_dimension=identity_key`` with the ``person_id`` as
  the value.

* ``channel in {linkedin, twitter, calendar}``: emit
  ``suppressed_dimension=identity_key`` with the ``person_id`` as
  the value. LinkedIn / Twitter / calendar events don't carry email
  addresses on the reply emit shape; the identity-key suppression
  dimension is the right surface (ADR-0004's
  ``SuppressIdentityKeyRule`` already canonicalizes ``in/<slug>``
  forms; ``person_id`` carries the canonical shape).

Auto-unsubscribe YAML filename
------------------------------

The handler writes to ``auto-unsubscribe.yml`` (NOT ``gdpr-forget.yml``
— see ADR-0028 §Alternatives). Operators reading the suppression
directory see one file per write-source:

  * ``gdpr-forget.yml`` — Pillar A's GDPR-forget surface; manual
    operator action via ``policy.py forget --person <id>``.
  * ``auto-unsubscribe.yml`` — Pillar D's auto-unsubscribe surface;
    classifier-driven writes from this handler.

The directory-merge semantics in ``load_suppression_dir`` (ADR-0004)
union both files, so dispatcher gates see the combined set — operators
don't have to wire a second source.

Failure mode matrix (per ADR-0025 D100)
---------------------------------------

  * LLM hallucinates ``category=unsubscribe`` →
    impossible per ADR-0025 D97 (unsubscribe is rule-based ONLY;
    ``ClassifierResult.__post_init__`` refuses construction with
    method!=rule).
  * Classifier rule misclassifies (false-positive unsubscribe) →
    the asymmetric-failure-cost calculus per PILLAR-PLAN §0: one
    missed conversation > one CAN-SPAM violation. Operator-tunable
    via the unsubscribe-patterns.yml.
  * Race between detection + dispatch →
    YAML-first guarantees the suppression is live BEFORE the audit
    trail; the dispatcher's NEXT gate evaluation refuses. Pillar H
    SIGHUP closes the in-process race window (future).
  * YAML write fails →
    handler propagates the exception; no ``suppression_added`` lands;
    operator sees the failure. Re-run handler is idempotent.
  * Ledger append fails after YAML write →
    suppression is LIVE; audit trail is incomplete; reconcile
    surfaces the inconsistency on next run via the existing health-
    check primitives.
  * Concurrent handler runs producing duplicate writes →
    the cross-run (reply_message_id, channel) dedup forecloses;
    second handler sees the first's ``suppression_added`` event +
    skips.
"""

from __future__ import annotations

import email.utils
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ledger as _ledger
from policy.suppression import forget_append


# Per ADR-0028 D115 — the suppression YAML file the handler writes.
# Distinct from ``gdpr-forget.yml`` (Pillar A's manual surface per ADR-
# 0004) so operators reading the suppression directory see one file
# per write-source. The directory-merge in ADR-0004's
# ``load_suppression_dir`` unions both files.
AUTO_UNSUBSCRIBE_FILENAME: str = "auto-unsubscribe.yml"


# Per ADR-0028 D115 — the default suppressions directory. Mirrors the
# Pillar A convention from ``policy.suppression`` (no shared constant
# today; the path is consistent across surfaces). The
# ``OUTREACH_FACTORY_SUPPRESSIONS_DIR`` env var overrides for tests +
# per-environment injection (analogous to ``OUTREACH_FACTORY_LEDGER_DIR``
# in ledger.py).
DEFAULT_SUPPRESSIONS_DIR: Path = (
    Path.home() / ".outreach-factory" / "suppressions"
)


def suppressions_dir_default() -> Path:
    """Resolve the per-operator suppressions directory.

    Reads ``OUTREACH_FACTORY_SUPPRESSIONS_DIR`` env var when set
    (test injection + per-environment overrides) and falls back to
    :data:`DEFAULT_SUPPRESSIONS_DIR`.
    """
    env = os.environ.get("OUTREACH_FACTORY_SUPPRESSIONS_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return DEFAULT_SUPPRESSIONS_DIR


# Per RFC 5322 + email.utils.parseaddr — extract the bare email from
# a ``From:`` header. ``parseaddr`` is tolerant of "Display Name"
# <addr@host> + bare addr@host shapes; returns ("", "") on failures.
def _extract_email_from_header(from_header: str | None) -> str | None:
    """Parse the bare email address out of an RFC 5322 ``From:`` header.

    Returns ``None`` when the header is missing, empty, or unparseable.
    """
    if not from_header or not isinstance(from_header, str):
        return None
    _name, addr = email.utils.parseaddr(from_header)
    if not addr or "@" not in addr:
        return None
    return addr.lower().strip()


@dataclass(frozen=True)
class SuppressionTarget:
    """The resolved (dimension, value) the handler will write to YAML.

    Per ADR-0028 D115 + ADR-0004's existing suppression dimensions —
    ``email`` / ``domain`` / ``identity_key``. The Week 4-5 handler
    emits ``email`` (when resolvable from the originating Pass B reply
    event's ``from`` header) or ``identity_key`` (fallback + the only
    option for LinkedIn / Twitter / calendar channels).
    """

    dimension: str  # "email" | "domain" | "identity_key"
    value: str


def _extract_thread_key(reply_event: dict) -> str | None:
    """Pull the per-channel thread key out of a reply event.

    Per ADR-0025 D98 — the conversation-state machine's
    ``thread_key`` field. Each channel uses a distinct field name on
    the reply event:

    * email → ``gmail_thread_id`` (Pass B emits this)
    * linkedin (invite) → ``linkedin_invitation_id`` (Pass H emits)
    * linkedin (DM) → ``linkedin_thread_id`` (Pass I emits)
    * twitter → ``twitter_thread_id`` (Pass J emits)
    * calendar → ``calendar_booking_intent_id`` (deferred per ADR-0027
      D113; handler tolerates absence by returning None — the calendar
      channel reaches the handler ONLY if a future Pillar I week
      ships Pass K with a comment surface)

    Returns the thread-key string or ``None`` when no field matches.
    Used by the conversation state machine (``orchestrator/
    conversation_state.py``); the handler itself doesn't consume the
    thread key (it writes to the suppression YAML by person), but the
    helper lives here so both auto_unsubscribe + conversation_state
    share one source-of-truth for the per-channel field names.
    """
    for field_name in (
        "gmail_thread_id",
        "linkedin_thread_id",
        "linkedin_invitation_id",
        "twitter_thread_id",
        "calendar_booking_intent_id",
    ):
        v = reply_event.get(field_name)
        if isinstance(v, str) and v:
            return v
    return None


def resolve_suppression_target(
    classified_event: dict,
    led: "_ledger.Ledger",
) -> SuppressionTarget:
    """Resolve the (dimension, value) target for one classified event.

    Per ADR-0028 D115:

    * ``channel == "email"`` and the originating reply event carries a
      parseable ``from`` header → ``email`` dimension with the bare
      address as value.
    * ``channel == "email"`` and the email can't be resolved (legacy
      emit / malformed header) → fall back to ``identity_key`` with
      ``person_id`` as value.
    * ``channel in {linkedin, twitter, calendar}`` → ``identity_key``
      with ``person_id`` as value. The non-email reply emit shapes
      (Pass H / I / J per ADR-0027 D112) don't carry the recipient's
      email; identity_key + person_id (canonicalized to ``in/<slug>``
      shape by ``SuppressIdentityKeyRule`` per ADR-0004) is the right
      surface.

    Returns a :class:`SuppressionTarget`. Raises :class:`ValueError`
    when the classified event is missing both ``channel`` and
    ``person_id`` — the handler can't surface anything useful for an
    event so malformed; refuse-loud at the boundary.
    """
    channel = classified_event.get("channel") or "email"
    person_id = classified_event.get("person_id")
    reply_mid = classified_event.get("reply_message_id")

    if channel == "email" and reply_mid:
        # Look up the originating reply event for the ``from`` header.
        # Pass B's emit shape carries the address as
        # ``"from": headers.get("from", "")``; the gmail_message_id
        # is the lookup key + lands in ``_idx_gmail_msg`` per the
        # ledger's existing indexing.
        original = led.query_by_gmail_message_id(reply_mid)
        if original is not None:
            from_header = original.get("from")
            addr = _extract_email_from_header(from_header)
            if addr:
                return SuppressionTarget(dimension="email", value=addr)

    # Fallback path — non-email channels OR email-channel where the
    # ``from`` header couldn't be parsed. Use the identity_key
    # dimension with the canonical ``person_id``.
    if not person_id:
        raise ValueError(
            "auto_unsubscribe: classified event has neither a resolvable "
            f"email nor a person_id (channel={channel!r}, "
            f"reply_message_id={reply_mid!r}). Cannot resolve suppression "
            "target."
        )
    return SuppressionTarget(dimension="identity_key", value=str(person_id))


def build_suppression_added_payload(
    classified_event: dict,
    target: SuppressionTarget,
    yaml_path: Path,
) -> dict:
    """Construct the ``suppression_added`` event payload (no append).

    Per ADR-0025 D100's event shape. Single source of truth for the
    payload across the live + dry-run paths (mirrors the
    ``build_classified_payload`` shape from
    ``orchestrator/reply_classifier.py`` per the Week 2 follow-up's
    P3-C carry-forward).

    The ``source_reply_classified_event`` correlation key is a dict
    keyed by ``(reply_message_id, channel)`` per ADR-0026 D104 — the
    same pair that discriminates the originating event. A future
    Pillar G dashboard can join ``suppression_added`` →
    ``reply_classified`` on this key directly.
    """
    channel = classified_event.get("channel") or "email"
    reply_mid = classified_event.get("reply_message_id")
    payload: dict = {
        "type": "suppression_added",
        "person_id": classified_event.get("person_id"),
        "channel": channel,
        "suppressed_dimension": target.dimension,
        "suppressed_value": target.value,
        "source_reply_classified_event": {
            "reply_message_id": reply_mid,
            "channel": channel,
            "ts": classified_event.get("ts"),
        },
        "yaml_file": str(yaml_path),
        "_emitted_by": "auto_unsubscribe_handler",
    }
    return payload


@dataclass
class AutoUnsubscribeResult:
    """What one ``run_auto_unsubscribe`` invocation observed + wrote.

    Mirrors the ``PassResult`` shape from ``orchestrator/reconcile.py``
    so the handler integrates cleanly into the reconcile chain (Pass M
    wraps this) — but lives here as a distinct class because the
    handler may also be invoked standalone (Pillar I CLI surface) +
    the field set is auto-unsubscribe-specific (``yaml_writes`` is
    not a generic PassResult field).

    Fields:

    * ``examined`` — count of ``category=unsubscribe`` classified
      events the handler considered (including duplicates filtered
      out by dedup).
    * ``synthesized`` — list of ``suppression_added`` events the
      handler appended (or would append, in dry-run mode).
    * ``yaml_writes`` — list of YAML paths the handler wrote to
      (one entry per unique suppression target; multiple events for
      the same target collapse to one write since
      ``SuppressionList`` is set-idempotent).
    * ``deduped`` — count of classified events the handler skipped
      because their (reply_message_id, channel) pair already had a
      ``suppression_added`` event (cross-run idempotence) OR was
      already processed within this batch.
    * ``errors`` — operator-visible error strings the handler
      captured without aborting.
    """

    examined: int = 0
    synthesized: list[dict] = field(default_factory=list)
    yaml_writes: list[Path] = field(default_factory=list)
    deduped: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "examined": self.examined,
            "synthesized": len(self.synthesized),
            "yaml_writes": len(self.yaml_writes),
            "deduped": self.deduped,
            "errors": len(self.errors),
        }


def _already_suppressed_keys(led: "_ledger.Ledger") -> set[tuple[str, str]]:
    """Build the (reply_message_id, channel) pair set covered by
    existing ``suppression_added`` events in the ledger.

    Per ADR-0028 D117 — the cross-run dedup keying. One ledger walk
    builds the in-memory set; the handler skips classified events
    whose pair is already covered.

    Walks ``led.all_events()`` for events of type
    ``suppression_added``; reads the
    ``source_reply_classified_event`` correlation dict on each + adds
    the pair. Events missing the correlation dict (defensive — a
    future contributor could land an out-of-shape event) contribute
    nothing to the set; the handler then DOES re-process the matching
    classified event. The asymmetric-failure-cost calculus: a
    duplicate ledger entry is operator-visible + recoverable; missing
    a real unsubscribe is a CAN-SPAM violation. The handler biases
    toward emit-twice (and the operator can grep + tidy) over
    emit-zero (and the prospect gets another email).
    """
    out: set[tuple[str, str]] = set()
    for e in led.all_events():
        if e.get("type") != "suppression_added":
            continue
        src = e.get("source_reply_classified_event")
        if not isinstance(src, dict):
            continue
        mid = src.get("reply_message_id")
        ch = src.get("channel")
        if mid and ch:
            out.add((str(mid), str(ch)))
    return out


def run_auto_unsubscribe(
    *,
    led: "_ledger.Ledger",
    suppressions_dir: Path,
    since: datetime,
    apply: bool,
) -> AutoUnsubscribeResult:
    """Walk ``reply_classified`` events; auto-suppress + emit
    ``suppression_added`` per ADR-0025 D100.

    The contract (per ADR-0028 §D115-D117):

    1. **Input filter.** ``e.type == "reply_classified"`` AND
       ``e.category == "unsubscribe"`` AND ``e.ts >= since``. Pillar D
       Week 4-5's exclusive consumer of the classifier emit; the
       long-tail categories (ooo / wrong_person / interest /
       rejection) do NOT trigger auto-suppression (the legal-liability
       rule-based-ONLY invariant from ADR-0025 D97 stays).
    2. **Dedup.** Skip events whose (reply_message_id, channel) pair
       is already in the cross-run ``already_suppressed`` set
       (existing ``suppression_added`` events) OR has been processed
       within this batch (``seen_this_batch``). Per ADR-0028 D117 the
       LOAD-BEARING Week 2 P2-B carry-forward.
    3. **Resolve target.** Per :func:`resolve_suppression_target` —
       email-with-from-header → email dimension; everything else →
       identity_key dimension.
    4. **Write YAML FIRST.** ``forget_append`` writes to
       ``<suppressions_dir>/auto-unsubscribe.yml`` (atomic per-file
       per ADR-0004 + the existing primitive's write-temp-then-rename
       contract). On exception: capture in ``errors`` + continue —
       no ``suppression_added`` lands for the failed YAML write.
    5. **Append ledger event SECOND.** ``suppression_added`` via
       ``led.append``. On exception: capture in ``errors`` + continue
       — the YAML is LIVE; the audit trail is incomplete; reconcile
       surfaces the inconsistency on next run.

    Dry-run path: synthesizes the event payload (via
    :func:`build_suppression_added_payload`) + stamps ``_dry_run:
    True``; no YAML write + no ledger append. The dry-run path is
    operator-facing diagnostic for "what WOULD the handler do?"
    without taking the irreversible action.

    Returns an :class:`AutoUnsubscribeResult` summarizing what the
    handler observed + wrote. Per ADR-0028 D120, Pass M wraps this
    function as a reconcile pass; the standalone-function shape lets
    the future Pillar I CLI also expose the handler directly.
    """
    result = AutoUnsubscribeResult()
    since_iso = (
        since.isoformat() if since.tzinfo
        else since.replace(tzinfo=timezone.utc).isoformat()
    )

    # Cross-run dedup index (per ADR-0028 D117).
    already_suppressed = _already_suppressed_keys(led)
    # Within-batch dedup (per ADR-0028 D117; defense-in-depth against
    # duplicate classified events Pass G may have emitted on a race).
    seen_this_batch: set[tuple[str, str]] = set()

    yaml_path = suppressions_dir / AUTO_UNSUBSCRIBE_FILENAME
    yaml_writes_so_far: set[str] = set()

    for e in led.all_events():
        if e.get("type") != "reply_classified":
            continue
        if e.get("category") != "unsubscribe":
            continue
        if (e.get("ts") or "") < since_iso:
            continue

        reply_mid = e.get("reply_message_id")
        ch = e.get("channel")
        if not reply_mid or not ch:
            # Defensive — a classified event without the discriminator
            # pair can't be idempotently keyed. Skip + surface for
            # operator review. Should never happen — the classifier
            # always stamps both.
            result.errors.append(
                f"reply_classified event missing reply_message_id or "
                f"channel (person={e.get('person_id')!r}, ts="
                f"{e.get('ts')!r}); skipped."
            )
            continue

        result.examined += 1
        key = (str(reply_mid), str(ch))

        # Dedup — cross-run first (the cheap check) then within-batch.
        if key in already_suppressed or key in seen_this_batch:
            result.deduped += 1
            continue

        # Resolve target. The handler refuses-loud on classified events
        # that can't be resolved (no email + no person_id — should
        # never happen per the classifier's emit shape per ADR-0025
        # D97, but defense in depth + surfacing makes a future emit
        # regression loud).
        try:
            target = resolve_suppression_target(e.to_dict() if hasattr(e, "to_dict") else dict(e), led)
        except ValueError as exc:
            result.errors.append(
                f"resolve_suppression_target failed for "
                f"reply_message_id={reply_mid!r}, channel={ch!r}: {exc}"
            )
            continue

        payload = build_suppression_added_payload(
            e.to_dict() if hasattr(e, "to_dict") else dict(e),
            target,
            yaml_path,
        )

        if not apply:
            payload["_dry_run"] = True
            result.synthesized.append(payload)
            # Mark seen so subsequent duplicate classified events in
            # the same dry-run don't double-emit.
            seen_this_batch.add(key)
            continue

        # Apply path — YAML FIRST per ADR-0025 D100's load-bearing
        # write order. The YAML append is atomic per
        # ``forget_append``'s write-temp-then-rename contract.
        try:
            kwargs: dict = {}
            if target.dimension == "email":
                kwargs["email"] = target.value
            elif target.dimension == "domain":
                kwargs["domain"] = target.value
            elif target.dimension == "identity_key":
                kwargs["identity_key"] = target.value
            else:
                # Defensive — SuppressionTarget construction should
                # forbid this, but catch the impossible case.
                result.errors.append(
                    f"unknown suppressed_dimension {target.dimension!r} "
                    f"for reply_message_id={reply_mid!r}; skipped."
                )
                continue
            written_path = forget_append(
                suppressions_dir,
                filename=AUTO_UNSUBSCRIBE_FILENAME,
                **kwargs,
            )
        except (OSError, ValueError) as exc:
            # YAML write failed. Per ADR-0025 D100's failure-mode
            # matrix: propagate-via-errors-list; the
            # ``suppression_added`` ledger event does NOT land — the
            # operator sees the failure + can re-run.
            result.errors.append(
                f"forget_append failed for "
                f"reply_message_id={reply_mid!r}, "
                f"dimension={target.dimension!r}, "
                f"value={target.value!r}: {exc}"
            )
            continue

        path_str = str(written_path.resolve())
        if path_str not in yaml_writes_so_far:
            yaml_writes_so_far.add(path_str)
            result.yaml_writes.append(written_path)

        # Ledger append SECOND. Per ADR-0025 D100's failure-mode
        # matrix: an append failure leaves the YAML LIVE + the audit
        # trail incomplete; reconcile surfaces on next run. We capture
        # the error + continue to the next classified event.
        try:
            persisted = led.append(payload)
            result.synthesized.append(persisted)
        except (OSError, ValueError) as exc:
            result.errors.append(
                f"ledger append failed for suppression_added "
                f"(reply_message_id={reply_mid!r}, "
                f"channel={ch!r}): {exc}"
            )
            # Mark seen anyway — the YAML is LIVE; re-running the
            # handler would not re-emit (the cross-run dedup would
            # MISS this since the suppression_added didn't land, but
            # the within-batch dedup catches the same-batch case;
            # cross-run is a known limitation surfaced via reconcile).
            seen_this_batch.add(key)
            continue

        seen_this_batch.add(key)

    return result


__all__ = [
    "AUTO_UNSUBSCRIBE_FILENAME",
    "AutoUnsubscribeResult",
    "DEFAULT_SUPPRESSIONS_DIR",
    "SuppressionTarget",
    "build_suppression_added_payload",
    "resolve_suppression_target",
    "run_auto_unsubscribe",
    "suppressions_dir_default",
]
