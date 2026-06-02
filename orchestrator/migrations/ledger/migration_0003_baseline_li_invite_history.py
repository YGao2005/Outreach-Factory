"""Ledger migration 0003 — backfill retroactive LinkedIn invite history.

Pillar C Week 2's first per-channel ledger migration. Mirrors
``ledger/0002_backfill_send_history`` in shape but scoped to LinkedIn
invites: walks the operator's vault for ``sent: true`` LinkedIn touch
notes and emits retroactive ``li_invite_intent`` + ``li_invite_confirmed``
event pairs so the post-migration ledger holds the same two-phase shape
production dispatchers (ADR-0015) emit going forward.

What it does
------------

Reconstructs LinkedIn-invite history from the vault's current state by
emitting retroactive event pairs per matched touch note. Each event
carries ``_recovered_by: "backfill"`` so downstream readers can
distinguish synthetic backfill from organically-emitted events. Per
ADR-0014 D33 + D35:

1. **Per pair** — ``li_invite_intent`` + ``li_invite_confirmed`` both
   stamped ``channel: "linkedin"`` (D33 invariant). ``intent_id`` is
   deterministic (``bf_li_<sha256(person_id|date|action|touch_stem)[:16]>``)
   so re-runs are idempotent without ledger duplication.
2. **One audit-trail event** — ``migration_event`` with
   ``channel="linkedin"`` per ADR-0014 D35 + diagnostic fields:
   ``linkedin_pairs_emitted``, ``linkedin_pairs_skipped``,
   ``touches_without_person_match``, ``touches_skipped_not_invite``.

Distinguishing invite vs DM (ADR-0015 D38)
------------------------------------------

Pre-Pillar-C touch notes don't distinguish invite vs DM at the
frontmatter level — operators wrote "linkedin invite" or "linkedin dm"
in the filename but the frontmatter typically just says
``channel: linkedin``. This migration uses a **filename-pattern
heuristic for backfill ONLY**:

* Filename contains ``invite`` or ``connect`` → invite. Walked.
* Filename contains ``dm`` or ``message`` → DM. Skipped (Week 3's
  ``ledger/0004_baseline_li_dm_history`` migration walks these).
* Default — neither pattern matches → invite. (Pre-Pillar-C touches
  empirically tend to be invites; the historical-prevalence default
  reduces the operator's manual triage. Operators with vault notes
  that diverge from this convention can override per ADR-0015 D38.)

Going forward, the Week 2 LinkedIn dispatcher writes
``linkedin_action: invite | dm`` on every new touch note (per the
companion vault migration ``vault/0003_add_linkedin_action_to_touch_notes``);
when present, the migration honors that field in preference to the
filename heuristic. Operators who run ``vault/0003`` before
``ledger/0003`` get the explicit-field path; operators who skip
``vault/0003`` get the heuristic fallback.

Why ``is_reversible=False``
---------------------------

Append-only ledger (ADR-0010 D14). Rolling back would require either
deleting bytes (forbidden) or inventing a "re-open" event type
(unprecedented). Operators recovering from a bad apply restore the
ledger directory from backup + manually mark the migration un-applied
via :func:`orchestrator.migrations.state.mark_unapplied`. For operators
who have been using LinkedIn invites via the pre-Pillar-C MCP-mediated
flow AND want their historical state preserved as-is (no retroactive
backfill emissions), the ADR-0015 §"Existing-operator seed" subsection
documents a one-time ``mark_applied`` incantation to skip this
migration entirely.

Cross-category dependency on vault/0002 + (optionally) vault/0003
-----------------------------------------------------------------

This migration READS Person notes to find their ``id:`` field (stamped
by vault/0002, same pattern as ledger/0002) AND optionally reads touch
notes for a ``linkedin_action:`` field (stamped by vault/0003 when
present). Touches without a matched Person ``id`` surface in the
``touches_without_person_match`` diagnostic. Touches without
``linkedin_action:`` fall back to the filename heuristic.

ADR-0013 D27 + ADR-0014 D34 document the cross-category ordering
contract (VAULT → LEDGER → POLICY); ``ledger/0003`` slots into the
existing apply order without amendment.

Per-event atomicity
-------------------

Each append goes through :func:`._ledger_io.append_event_atomic`,
which delegates to :meth:`orchestrator.ledger.Ledger.append` — the
``O_APPEND + fcntl.lockf + fsync`` durability path every concurrent
writer in the system shares. A crash mid-batch leaves emitted events
durably on disk; the runner's state-file pointer does NOT advance
(ADR-0009 D4); re-running ``apply`` re-invokes ``upgrade`` from
scratch and the per-event idempotence checks (existing intent_id set,
per-touch dedup) skip already-emitted events.

Refuse-on-missing-vault
-----------------------

The migration requires ``ctx.vault_dir is not None`` (because it
reads touch notes from the vault). Raises ``ValueError`` if vault_dir
is unset — same shape as vault migrations + ledger/0002.

Refuse-on-missing-ledger
------------------------

Same shape as ledger/0001 + ledger/0002: raises ``FileNotFoundError``
if ``ctx.ledger_dir`` does not exist. Operators with a fresh state dir
emit at least one event through the normal send path before invoking
the migration, or ``mkdir -p`` the directory.

See ADR-0015 for the full Week 2 design (per-channel dispatcher
generalization, MCP correlation strategy, filename heuristic
rationale, operator-seed pattern).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..runner import RUNNER_VERSION
from ..types import MigrationCategory, MigrationContext, MigrationResult
from ..vault._vault_io import (
    is_obsidian_conflict_file,
    is_person_note,
    is_touch_note,
    iter_touch_notes,
)
from ._ledger_io import (
    append_event_atomic,
    emit_migration_event,
    iter_events,
)


MIGRATION_ID = "0003_baseline_li_invite_history"

# Default people sub-dir. Matches ``ledger/0002.PEOPLE_SUBDIR`` for
# consistency — ledger/0003 reads Person notes for ``id:`` lookup the
# same way ledger/0002 does. Future Pillar I OSS hardening exposes
# this as a config knob (operators with renamed subdirs).
PEOPLE_SUBDIR = "10 People"

# LinkedIn channel value per ADR-0014 D33. Every event this migration
# emits carries ``channel: "linkedin"`` — the cross-channel rule
# (ADR-0003) discriminates on this field.
LINKEDIN_CHANNEL = "linkedin"

# Synthetic intent id prefix — ``bf_li_`` distinguishes from live ULIDs
# (``snd_`` / ``li_`` per Pillar C dispatcher conventions) AND from
# email backfill (``bf_`` from ledger/0002). A reader scanning the
# ledger can instantly tell which sends came from LinkedIn-invite
# retroactive reconstruction vs email-send retroactive reconstruction
# vs live LinkedIn invites.
SYNTHETIC_INTENT_PREFIX = "bf_li_"

# ``_recovered_by`` value on every event this migration emits. Shares
# the ``"backfill"`` tag with ledger/0002 per ADR-0013 Alternative 12
# rationale — operators filtering by ``_recovered_by`` benefit from
# one tag for the Phase-5.5-shape semantic class regardless of which
# migration emitted it. The ``migration_id`` field on each
# migration_event provides the per-migration discriminator when needed.
RECOVERED_BY_TAG = "backfill"

# Filename-pattern heuristic for distinguishing invite vs DM touches.
# ADR-0015 D38 rationale + alternatives. Compiled at module load.
_INVITE_PATTERN = re.compile(r"\b(?:invite|connect)\b", re.IGNORECASE)
_DM_PATTERN = re.compile(r"\b(?:dm|message)\b", re.IGNORECASE)

# Per-touch ``linkedin_action`` frontmatter field. When present, the
# migration honors it in preference to the filename heuristic per
# ADR-0015 D38. Companion vault migration ``vault/0003`` stamps this
# field; this constant is the field name both modules agree on.
LINKEDIN_ACTION_FIELD = "linkedin_action"
LINKEDIN_ACTION_INVITE = "invite"
LINKEDIN_ACTION_DM = "dm"


# ---------------------------------------------------------------------------
# Helpers — inlined from ledger/0002's shape because the production
# backfill_ledger script doesn't handle LinkedIn-specific event types
# (the script ships emails-only; Pillar C generalizes the shape via the
# migration framework, not the standalone script). Any divergence from
# ledger/0002's logic should be intentional + called out in ADR-0015.
# ---------------------------------------------------------------------------


@dataclass
class _PersonRecord:
    """One Person note's identity-lookup state.

    Smaller than ledger/0002's ``_PersonRecord`` because this migration
    only needs the ``id:`` → name mapping for touch correlation; we
    don't emit ``enrolled`` events here (ledger/0002 owns that
    invariant; re-emitting would duplicate).
    """
    path: Path
    name: str
    person_id: str | None


@dataclass
class _LinkedInTouchRecord:
    """One LinkedIn touch note's invite-history-relevant state."""
    path: Path
    person_link_name: str | None
    date_ts: str
    sent_at_ts: str | None
    linkedin_action: str | None  # 'invite' / 'dm' / None per vault/0003


@dataclass
class _BackfillCounts:
    """Per-category emit counts surfaced in MigrationResult.notes.

    Wrong-channel filtering happens inside
    :func:`_walk_linkedin_touch_records` (every touch the walker yields
    already passed the ``channel: linkedin`` check). The walker
    returns only LinkedIn touches, so a wrong-channel count would
    necessarily be zero from this dataclass's perspective; we
    deliberately omit the field rather than expose a misleading
    "always zero" counter to Pillar G's migration_event consumers.
    Per Week 2 per-week review P2-3.
    """
    linkedin_pairs_emitted: int = 0
    linkedin_pairs_skipped: int = 0
    touches_without_person_match: list[str] = field(default_factory=list)
    touches_skipped_not_invite: list[str] = field(default_factory=list)


def _parse_frontmatter(path: Path) -> dict | None:
    """Read + parse a markdown file's frontmatter dict.

    Returns ``None`` for files without frontmatter or with malformed
    YAML — the caller silently skips. Mirrors
    ``ledger/0002._parse_frontmatter`` shape; we duplicate rather than
    import because ``_vault_io.read_person_frontmatter`` raises on
    malformed YAML (vault migrations refuse loud) whereas ledger
    backfill prefers to skip silently (a single touch note with bad
    YAML shouldn't block backfilling every other LinkedIn touch).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:end].lstrip("\n"))
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _date_to_iso(value: Any, *, fallback_mtime: float | None = None) -> str:
    """Coerce a frontmatter date value to an ISO 8601 UTC string.

    Mirrors ``ledger/0002._date_to_iso``. Accepts datetime / date /
    'YYYY-MM-DD' strings; falls back to file mtime; final fallback is
    ``now()``. The fallback is silent — we don't refuse to backfill a
    LinkedIn invite just because the operator's ``date:`` field was
    edited away.
    """
    if value is not None:
        if hasattr(value, "isoformat"):
            try:
                if isinstance(value, datetime):
                    dt = (
                        value if value.tzinfo
                        else value.replace(tzinfo=timezone.utc)
                    )
                else:
                    dt = datetime(
                        value.year, value.month, value.day,
                        tzinfo=timezone.utc,
                    )
                return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            except (TypeError, ValueError):
                pass
        if isinstance(value, str):
            s = value.strip()
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            except ValueError:
                m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
                if m:
                    return f"{m.group(1)}T00:00:00.000Z"
    if fallback_mtime is not None:
        dt = datetime.fromtimestamp(fallback_mtime, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _person_link_to_name(value: Any) -> str | None:
    """Extract bare display name from an Obsidian wikilink ``[[Name]]``.

    Mirrors ``ledger/0002._person_link_to_name``.
    """
    if not value:
        return None
    if isinstance(value, str):
        m = re.match(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", value.strip())
        return (m.group(1).strip() if m else value.strip()) or None
    return None


def _walk_person_records(people_dir: Path) -> list[_PersonRecord]:
    """Yield one PersonRecord per Person note under ``people_dir``.

    Mirrors ``ledger/0002._walk_person_records`` but slimmer (no
    ``created_ts`` / ``last_touch`` — this migration only needs the
    name → id mapping). The ``type:`` check is delegated to the shared
    :func:`..vault._vault_io.is_person_note` predicate (robust to
    non-string ``type:`` values per Pillar B Week 2 P2-1).
    """
    out: list[_PersonRecord] = []
    if not people_dir.exists():
        return out
    for note in sorted(people_dir.rglob("*.md")):
        rel = note.relative_to(people_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if is_obsidian_conflict_file(note.name):
            continue
        fm = _parse_frontmatter(note)
        if not is_person_note(fm):
            continue
        out.append(_PersonRecord(
            path=note.resolve(),
            name=str(fm.get("name") or note.stem).strip(),
            person_id=(str(fm["id"]).strip() if fm.get("id") else None),
        ))
    return out


def _classify_linkedin_action(
    touch_path: Path,
    explicit_field: str | None,
) -> str:
    """Return 'invite' | 'dm' for a LinkedIn touch.

    Per ADR-0015 D38:

    1. If the touch frontmatter declares ``linkedin_action:`` (set by
       vault/0003 or by a Pillar-C-aware operator), honor that value.
       Unknown values fall through to the heuristic.
    2. Else apply the filename-pattern heuristic:
       * filename matches ``invite|connect`` → invite
       * filename matches ``dm|message`` → dm
       * default (neither matches) → invite (historical-prevalence
         default per ADR-0015 D38 rationale).

    The default-to-invite is operator-deliberate: pre-Pillar-C touch
    notes empirically tend to be invites (the LinkedIn DM register
    landed in the dispatch-outreach skill later than the connection-
    request register did); operators with vault notes that diverge
    can stamp ``linkedin_action: dm`` manually or run vault/0003 with
    a per-operator override.

    **If you change the patterns here, mirror the change in the vault
    module's twin function**
    (:func:`orchestrator.migrations.vault.migration_0003_add_linkedin_action_to_touch_notes._classify_action_from_filename`).
    The two functions MUST stay consistent — the ledger migration's
    fallback path (when frontmatter lacks ``linkedin_action:``) must
    produce the SAME classification the vault migration would have
    stamped. Divergence would silently produce inconsistent invite-vs-DM
    classifications. Per Week 2 per-week review P3-1.
    """
    if explicit_field in (LINKEDIN_ACTION_INVITE, LINKEDIN_ACTION_DM):
        return explicit_field
    name = touch_path.name
    if _INVITE_PATTERN.search(name):
        return LINKEDIN_ACTION_INVITE
    if _DM_PATTERN.search(name):
        return LINKEDIN_ACTION_DM
    return LINKEDIN_ACTION_INVITE


def _walk_linkedin_touch_records(
    conv_dir_iter_touches,
) -> list[_LinkedInTouchRecord]:
    """Yield one ``_LinkedInTouchRecord`` per LinkedIn ``sent: true``
    touch note.

    Mirrors ``ledger/0002._walk_touch_records`` but scoped to LinkedIn
    touches. The ``channel: linkedin`` predicate is the load-bearing
    filter — every LinkedIn touch must declare it (Pillar B Week 6 +
    Pillar C Week 1 conventions); touches without it are silently
    skipped.

    Accepts a pre-built iterator (rather than re-walking the dir) so
    the caller can substitute a test fake without reaching into
    private file IO. The production caller uses
    :func:`..vault._vault_io.iter_touch_notes`.

    Returns
    -------
    list[_LinkedInTouchRecord]:
        One record per matched touch. The caller filters
        invite-vs-DM via :func:`_classify_linkedin_action`.
    """
    out: list[_LinkedInTouchRecord] = []
    for note in conv_dir_iter_touches:
        fm = _parse_frontmatter(note)
        if not is_touch_note(fm):
            continue
        if not bool(fm.get("sent")):
            continue
        if (fm.get("channel") or "").strip().lower() != LINKEDIN_CHANNEL:
            continue
        try:
            mtime = note.stat().st_mtime
        except OSError:
            mtime = None
        date_ts = _date_to_iso(fm.get("date"), fallback_mtime=mtime)
        sent_at_ts = None
        if fm.get("sent_at"):
            sent_at_ts = _date_to_iso(
                fm.get("sent_at"), fallback_mtime=mtime,
            )
        explicit_action = fm.get(LINKEDIN_ACTION_FIELD)
        if isinstance(explicit_action, str):
            explicit_action = explicit_action.strip().lower() or None
        else:
            explicit_action = None
        out.append(_LinkedInTouchRecord(
            path=note.resolve(),
            person_link_name=_person_link_to_name(fm.get("person")),
            date_ts=date_ts,
            sent_at_ts=sent_at_ts,
            linkedin_action=explicit_action,
        ))
    return out


def _synth_intent_id(
    person_id: str,
    date_iso: str,
    action: str,
    touch_stem: str | None,
) -> str:
    """Deterministic synthetic intent id for LinkedIn-invite backfill.

    ``bf_li_`` prefix distinguishes from live LinkedIn ULIDs (``li_``)
    + from email backfill (``bf_``) + from live email ULIDs (``snd_``).
    The ``action`` discriminator (``"invite"``) ensures Week 3's
    DM backfill (``ledger/0004``) can produce distinct intent_ids for
    DMs sent the same day as invites — hash-collision-free.

    The touch_stem discriminator is load-bearing: two real LinkedIn
    invite touches to the same person on the same day (initial + retry,
    or reconnection attempts) are distinct sends — without the stem
    they'd hash-collide. Mirrors ``ledger/0002._synth_intent_id``.
    """
    parts = [person_id, date_iso[:10], action]
    if touch_stem:
        parts.append(touch_stem)
    payload = "|".join(parts).encode("utf-8")
    h = hashlib.sha256(payload).hexdigest()[:16]
    return f"{SYNTHETIC_INTENT_PREFIX}{h}"


def _build_name_to_id(persons: list[_PersonRecord]) -> dict[str, str]:
    """Map display-name (case-insensitive) → person_id.

    Indexes both ``name:`` and the filename stem. Skips persons
    without a ``person_id`` set. Mirrors
    ``ledger/0002._build_name_to_id``.
    """
    out: dict[str, str] = {}
    for p in persons:
        if not p.person_id:
            continue
        out.setdefault(p.name.strip().lower(), p.person_id)
        out.setdefault(p.path.stem.strip().lower(), p.person_id)
    return out


@dataclass
class BaselineLinkedInInviteHistory:
    """Emit retroactive ``li_invite_intent`` + ``li_invite_confirmed`` pairs.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work lives in
    :meth:`upgrade`. :meth:`downgrade` raises ``NotImplementedError``
    per the append-only-ledger constraint.

    Module-level singleton ``MIGRATION`` is registered in
    ``ledger/__init__.py::MIGRATIONS`` so the runner discovers it.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.LEDGER
    description: str = (
        "Backfill retroactive li_invite_intent + li_invite_confirmed "
        "event pairs from LinkedIn touch notes "
        "(Pillar C Week 2 — first per-channel ledger migration)"
    )
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Emit retroactive LinkedIn invite pairs + migration_event.

        Walks ``<ctx.vault_dir>/40 Conversations/`` for ``sent: true``
        LinkedIn touch notes; classifies each via the
        :func:`_classify_linkedin_action` heuristic (or the
        ``linkedin_action:`` frontmatter field when set); emits
        retroactive ``li_invite_intent`` + ``li_invite_confirmed`` pairs
        for invite-classified touches; ends with one
        ``migration_event`` carrying ``channel="linkedin"`` per
        ADR-0014 D35.

        Returns a ``MigrationResult`` whose ``affected_count`` is the
        total count of primary events emitted (one count per emitted
        pair — the migration_event itself does not count).

        Side effects on a successful apply:

        * ``2 * pairs_emitted + 1`` events appended to the ledger
          (intent + confirmed per pair; ``+ 1`` for the migration_event).
        * Zero vault writes.
        * Zero policy writes.

        On dry-run (``ctx.dry_run=True``): no on-disk mutation. The
        ``MigrationResult`` carries the same counts as a real apply
        would produce (iteration is identical; the
        ``append_event_atomic`` calls AND the closing
        ``emit_migration_event`` call are both skipped per ADR-0010
        D17 "a dry run mutates nothing").

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None`` (the backfill needs to
            read touch notes).
        FileNotFoundError:
            When ``ctx.ledger_dir`` does not exist on disk.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"ledger migration {self.id!r} requires ctx.vault_dir "
                f"(the backfill reads LinkedIn touch notes to "
                f"reconstruct invite history); set vault.path in "
                f"~/.outreach-factory/config.yml or pass an explicit "
                f"vault_dir to the runner.",
            )
        ledger_dir = Path(ctx.ledger_dir)
        if not ledger_dir.exists():
            raise FileNotFoundError(
                f"ledger migration {self.id!r} requires "
                f"ctx.ledger_dir to be an existing directory; got "
                f"{ledger_dir!s}. Either point the runner at the "
                f"correct ledger dir or `mkdir -p` it before "
                f"applying.",
            )

        people_dir = ctx.vault_dir / PEOPLE_SUBDIR

        persons = _walk_person_records(people_dir)
        touches = _walk_linkedin_touch_records(
            iter_touch_notes(ctx.vault_dir),
        )
        name_to_id = _build_name_to_id(persons)

        # Build existing-state indexes from the ledger so we can dedup
        # on re-run. The relevant set is every ``li_invite_intent``
        # event's ``intent_id`` — production dispatcher emissions
        # (live ``li_<ULID>``) AND prior backfill emissions
        # (``bf_li_<hash>``) AND any pre-Pillar-C synthetic events
        # (the fixture's Carol pair is ``li_synthetic_carol_01``).
        # All three classes share the same intent_id-uniqueness contract.
        existing_li_invite_intents: set[str] = set()
        for e in iter_events(ledger_dir):
            if e.get("type") == "li_invite_intent":
                iid = e.get("intent_id")
                if iid:
                    existing_li_invite_intents.add(iid)

        counts = _BackfillCounts()
        emitted_intents_this_run: set[str] = set()

        # Walk LinkedIn touches and emit pairs for invite-classified
        # touches. DM-classified touches are skipped (Week 3's
        # ledger/0004 will pick them up). Email touches were never
        # walked (the channel filter in _walk_linkedin_touch_records
        # excluded them).
        for t in touches:
            if not t.person_link_name:
                counts.touches_without_person_match.append(str(t.path))
                continue
            pid = name_to_id.get(t.person_link_name.strip().lower())
            if not pid:
                counts.touches_without_person_match.append(str(t.path))
                continue
            action = _classify_linkedin_action(t.path, t.linkedin_action)
            if action != LINKEDIN_ACTION_INVITE:
                # DM or unknown → skip; Week 3's ledger/0004 walks DM touches.
                counts.touches_skipped_not_invite.append(str(t.path))
                continue

            send_ts = t.sent_at_ts or t.date_ts
            intent_id = _synth_intent_id(
                pid, send_ts, action, touch_stem=t.path.stem,
            )
            if (intent_id in existing_li_invite_intents
                    or intent_id in emitted_intents_this_run):
                counts.linkedin_pairs_skipped += 1
                continue

            intent_evt = {
                "type": "li_invite_intent",
                "person_id": pid,
                "intent_id": intent_id,
                # D33 invariant — every two-phase event carries channel.
                "channel": LINKEDIN_CHANNEL,
                "touch_note": str(t.path),
                "ts": send_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            confirm_evt = {
                "type": "li_invite_confirmed",
                "person_id": pid,
                "intent_id": intent_id,
                # D33 invariant — denormalize from the paired intent so
                # the cross-channel rule (ADR-0003) can discriminate.
                # ledger/0002 paid the price of OMITTING this and Pillar
                # C Week 1's coherence test stub surfaced the gap; this
                # migration ships it correct from day one.
                "channel": LINKEDIN_CHANNEL,
                # Traceability — mirror the intent event's touch_note
                # so queries on li_invite_confirmed can find the
                # source touch without a join through intent_id. The
                # backfill knows the touch path at confirm-emit time
                # (the live dispatcher does NOT — it composes the
                # event from runtime state — but the backfill walks
                # static vault state so the path is always known).
                # Per Week 2 per-week review P2-4.
                "touch_note": str(t.path),
                "ts": send_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            if not ctx.dry_run:
                append_event_atomic(ledger_dir, intent_evt)
                append_event_atomic(ledger_dir, confirm_evt)
            emitted_intents_this_run.add(intent_id)
            counts.linkedin_pairs_emitted += 1

        verb = "would emit" if ctx.dry_run else "emitted"
        ctx.logger.info(
            "%s: %s %d LinkedIn invite pair(s); "
            "skipped %d already-present / %d non-invite; "
            "%d touch(es) without person match",
            self.id, verb,
            counts.linkedin_pairs_emitted,
            counts.linkedin_pairs_skipped,
            len(counts.touches_skipped_not_invite),
            len(counts.touches_without_person_match),
        )

        affected = counts.linkedin_pairs_emitted

        notes_msg = (
            f"{verb} {counts.linkedin_pairs_emitted} LinkedIn invite "
            f"pair(s); {counts.linkedin_pairs_skipped} already present; "
            f"{len(counts.touches_skipped_not_invite)} non-invite "
            f"(reserved for ledger/0004_baseline_li_dm_history); "
            f"{len(counts.touches_without_person_match)} touch(es) "
            f"without person match"
        )

        # Per ADR-0010 D17 + ADR-0014 D35: emit migration_event on
        # EVERY apply (audit-trail continuity even on no-op), with the
        # ``channel="linkedin"`` kwarg so Pillar G observability can
        # query per-channel without text-matching against migration_id.
        # Dry-run skips emission per ADR-0010 D17 (a dry run mutates
        # nothing).
        if not ctx.dry_run:
            emit_migration_event(
                ledger_dir,
                migration_id=self.id,
                affected_count=affected,
                runner_version=RUNNER_VERSION,
                category=self.category.value,
                channel=LINKEDIN_CHANNEL,
                notes=notes_msg,
                linkedin_pairs_emitted=counts.linkedin_pairs_emitted,
                linkedin_pairs_skipped=counts.linkedin_pairs_skipped,
                touches_without_person_match=len(
                    counts.touches_without_person_match,
                ),
                touches_skipped_not_invite=len(
                    counts.touches_skipped_not_invite,
                ),
            )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=notes_msg,
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Refuse — ledger is append-only.

        Raises ``NotImplementedError``; the runner translates this
        into ``MigrationNotReversibleError``. Per ADR-0010 D14 every
        ledger migration is ``is_reversible=False`` and ``downgrade``
        raises here; the runner refuses ``rollback`` BEFORE invoking
        ``downgrade`` (it checks ``is_reversible`` first), so this
        body is only reached if a caller bypasses the runner.
        """
        raise NotImplementedError(
            f"ledger migration {self.id!r} is structurally "
            f"irreversible (append-only ledger; see ADR-0010 D14). "
            f"The runner refuses rollback with "
            f"MigrationNotReversibleError. To recover from a bad "
            f"apply: restore the ledger directory from backup and "
            f"re-run from a state-file checkpoint, OR follow the "
            f"ADR-0015 §'Existing-operator seed' incantation to mark "
            f"the migration applied without re-applying."
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: BaselineLinkedInInviteHistory = BaselineLinkedInInviteHistory()


__all__ = [
    "BaselineLinkedInInviteHistory",
    "LINKEDIN_ACTION_DM",
    "LINKEDIN_ACTION_FIELD",
    "LINKEDIN_ACTION_INVITE",
    "LINKEDIN_CHANNEL",
    "MIGRATION",
    "MIGRATION_ID",
    "PEOPLE_SUBDIR",
    "RECOVERED_BY_TAG",
    "SYNTHETIC_INTENT_PREFIX",
]
