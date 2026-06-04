"""Content distribution dispatcher - the draft-and-manual posting path.

The broadcast analog of the cold-email ``gated_send_one`` (send_queued.py). It
consumes the read-only due-posts worklist from ``content_scheduler`` and, for
each due post, either auto-publishes (only when a real posting client exists AND
``auto_publish`` is on) or produces a DRAFT-AND-REMIND action for the operator to
paste. In v2 every channel is draft-and-manual (ADR-0082 D414): no real posting
client exists, so the placeholder client routes every channel to a reminder.

The spine invariant (do not violate)
------------------------------------
The ledger is the source of truth. The scheduler decides eligibility/timing
read-only; THIS module is the only content surface that WRITES distribution
events, and it does so through the two-phase commit. It does NOT bypass a
guardrail: every would-be post passes the policy ``gate`` before it is posted or
surfaced. Communities never auto-post (structural: the placeholder client cannot
post them, and no real community client is wired in v2).

Human-gated posting (ADR-0082 D414)
-----------------------------------
A post is auto-published ONLY when ``calendar.auto_publish`` is on AND the posting
client ``can_post`` the channel. Otherwise it becomes a :class:`DraftReminder`
(the text + the target + a "post this yourself" note). Critically, an intent is
written ONLY on the auto-publish path: a draft-and-manual post writes NO
``distribution_intent`` (it would be an orphan-by-design that reconcile would
chase). The post lands in the ledger only when the operator confirms it via
:func:`confirm_manual_post` (or the Scrapling reconcile read-back detects it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import ledger as _ledger  # noqa: E402
import content as _content  # noqa: E402
import content_scheduler as _scheduler  # noqa: E402


# ---------------------------------------------------------------------------
# Posting client seam (ADR-0082 D414)
# ---------------------------------------------------------------------------


class NoPostingClient(Exception):
    """Raised by a placeholder posting client: this channel cannot auto-post.

    The dispatcher treats it as "route to draft-and-manual", never as a failure.
    """


class PlaceholderPostingClient:
    """The v2 posting client: refuse-loud, never fabricates a post.

    ``can_post`` is False for every channel, so the dispatcher always routes to a
    draft-and-remind. A real client (LinkedIn OAuth, paid X API, a static-site
    blog writer) is a later seam swap: implement ``can_post`` + ``post`` and the
    dispatcher auto-publishes when ``auto_publish`` is on.
    """

    def can_post(self, channel: str) -> bool:
        return False

    def post(self, channel: str, body: str, *, intent_id: str) -> str:
        raise NoPostingClient(
            f"no posting client for channel {channel!r}; v2 is draft-and-manual "
            f"(ADR-0082 D414). Paste it yourself."
        )


#: A human-readable "where to post this" hint per channel.
TARGET_HINT: dict[str, str] = {
    "linkedin_post": "Post to your LinkedIn feed",
    "x_post": "Post to your X timeline",
    "x_thread": "Post as an X thread",
    "blog": "Publish to your blog",
    "newsletter": "Send to your newsletter list",
    "reddit": "Post to the target subreddit (mind the sub's norms)",
    "hn": "Submit to Hacker News",
    "discord": "Post to the target Discord channel",
}


def target_hint(channel: str) -> str:
    return TARGET_HINT.get(channel, f"Post to {channel}")


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftReminder:
    """One post the operator should paste themselves (the v2 default action)."""

    content_id: str
    channel: str
    register: str
    body: str
    target_hint: str
    requires_manual_post: bool


@dataclass
class DispatchOutcome:
    """The result of one dispatch pass."""

    reminders: list[DraftReminder] = field(default_factory=list)
    auto_posted: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "reminders": [
                {
                    "content_id": r.content_id,
                    "channel": r.channel,
                    "register": r.register,
                    "target_hint": r.target_hint,
                    "requires_manual_post": r.requires_manual_post,
                }
                for r in self.reminders
            ],
            "auto_posted": list(self.auto_posted),
            "blocked": list(self.blocked),
        }


#: A policy gate seam (ADR-0082 D417, implemented in the guardrails slice). Given
#: a due post + the events + now, return a block-info dict (with ``rule`` +
#: ``reason``) to refuse, or None to allow. The dispatcher emits ``policy_blocked``
#: from the returned dict.
GateFn = Callable[[_scheduler.PostAction, list, datetime], "dict | None"]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch_due_posts(
    led: _ledger.Ledger,
    calendar: _scheduler.CalendarConfig,
    *,
    now: datetime,
    resolve_body: Callable[[str, str], "str | None"],
    posting_client: object | None = None,
    gate: GateFn | None = None,
) -> DispatchOutcome:
    """Consume the due-posts worklist and post or draft-and-remind each.

    ``resolve_body(content_id, channel)`` returns the variant body (the bodies
    live in the vault, not the ledger - the privacy invariant keeps prose out of
    the aggregate surface). A due post with no resolvable body is recorded as
    blocked (``reason="missing_body"``), never silently dropped.

    Read-and-write: the only content surface that appends distribution events,
    always via the two-phase commit, only on the auto-publish path.
    """
    client = posting_client or PlaceholderPostingClient()
    events = led.all_events()
    due = _scheduler.compute_due_posts(events, calendar, now=now)
    outcome = DispatchOutcome()

    for action in due:
        body = resolve_body(action.content_id, action.channel)
        if not body:
            outcome.blocked.append({
                "content_id": action.content_id,
                "channel": action.channel,
                "reason": "missing_body",
            })
            continue

        if gate is not None:
            block = gate(action, events, now)
            if block is not None:
                led.append({"type": "policy_blocked", **block})
                outcome.blocked.append(block)
                continue

        auto = bool(calendar.auto_publish) and bool(client.can_post(action.channel))
        if not auto:
            # Draft-and-manual: NO intent written (no orphan-by-design). The post
            # enters the ledger only when the operator confirms it.
            outcome.reminders.append(DraftReminder(
                content_id=action.content_id,
                channel=action.channel,
                register=action.register,
                body=body,
                target_hint=target_hint(action.channel),
                requires_manual_post=action.requires_manual_post,
            ))
            continue

        # Auto-publish path (a real client + auto_publish on): two-phase commit.
        intent_id = _content.new_distribution_intent_id()
        led.append({**_content.build_distribution_intent_payload(
            content_id=action.content_id, channel=action.channel,
            intent_id=intent_id, body_hash=action.body_hash), "type": "distribution_intent"})
        try:
            post_id = client.post(action.channel, body, intent_id=intent_id)
        except Exception as exc:  # noqa: BLE001 - record any client failure
            led.append({**_content.build_distribution_failed_payload(
                content_id=action.content_id, channel=action.channel,
                intent_id=intent_id, error_class=type(exc).__name__,
                error_message=str(exc)), "type": "distribution_failed"})
            outcome.blocked.append({
                "content_id": action.content_id, "channel": action.channel,
                "reason": "post_failed", "error": str(exc),
            })
            continue
        led.append({**_content.build_distribution_confirmed_payload(
            content_id=action.content_id, channel=action.channel,
            intent_id=intent_id, post_id=post_id,
            body_hash=action.body_hash), "type": "distribution_confirmed"})
        outcome.auto_posted.append({
            "content_id": action.content_id, "channel": action.channel,
            "post_id": post_id,
        })

    return outcome


def confirm_manual_post(
    led: _ledger.Ledger,
    *,
    content_id: str,
    channel: str,
    post_id: str,
    body_hash: str,
) -> str:
    """Record a post the operator published by hand (the draft-and-manual close).

    Writes the two-phase pair (intent + confirmed) so the piece transitions to
    ``posted`` and drops out of the due list. Returns the synthesized intent_id.
    The operator runs this after pasting (or the Scrapling reconcile read-back
    calls it when it detects the post landed).
    """
    intent_id = _content.new_distribution_intent_id()
    led.append({**_content.build_distribution_intent_payload(
        content_id=content_id, channel=channel, intent_id=intent_id,
        body_hash=body_hash), "type": "distribution_intent"})
    led.append({**_content.build_distribution_confirmed_payload(
        content_id=content_id, channel=channel, intent_id=intent_id,
        post_id=post_id, body_hash=body_hash), "type": "distribution_confirmed"})
    return intent_id


__all__ = [
    "DispatchOutcome",
    "DraftReminder",
    "GateFn",
    "NoPostingClient",
    "PlaceholderPostingClient",
    "TARGET_HINT",
    "confirm_manual_post",
    "dispatch_due_posts",
    "target_hint",
]
