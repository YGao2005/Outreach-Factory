"""Ledger migration 0007 — backfill ``source_skill`` on historical ``enrolled`` events.

Pillar E Week 9-11 ledger migration. Per ADR-0036 D170, the migration
appends an ``enrolled_source_skill_backfill`` event paired with every
historical ``enrolled`` event that lacks the canonical ``source_skill``
field. The backfill event carries the normalized canonical value
(derived from the legacy ``enrolled.source`` via
:func:`orchestrator.discovery_lineage.normalize_legacy_source_to_skill`)
paired with the original event's ``ts`` via ``_backfill_of_ts``.

Why append (not in-place rewrite)
---------------------------------

Per ADR-0010 D14 the ledger forbids in-place event rewrites. The
discipline is load-bearing for the synthetic-replay vehicle (per
ADR-0013). The append-only-backfill pattern per D170 lets the
``source_skill`` field be directly readable from a ledger event
without rewriting any historical bytes:

1. Consumers post-Week-9-11 read ``enrolled.source_skill`` directly
   (the field is stamped at emit time per the enrollment.py extension
   shipping in this commit).
2. For historical events, consumers look for a paired
   ``enrolled_source_skill_backfill`` event (the migration's emission)
   via ``_backfill_of_ts == enrolled.ts``.
3. As a last resort, consumers inline-normalize ``enrolled.source`` via
   :func:`orchestrator.discovery_lineage.normalize_legacy_source_to_skill`.

Why per-event idempotence
-------------------------

Per ADR-0010 D15 the migration is idempotent at the per-event level:

* If an ``enrolled`` event already has a matching
  ``enrolled_source_skill_backfill`` event (from a prior migration
  apply OR a future reconcile pass), the migration does NOT append a
  duplicate.
* Re-running ``upgrade`` directly after success finds zero new
  backfill-needed events → ``affected_count=0`` → still emits the
  ``migration_event`` audit-trail event per ADR-0010 D17.

Why ``is_reversible=False``
---------------------------

Append-only ledger (ADR-0010 D14). Rolling back would require either
deleting bytes (forbidden) or appending a "re-open" event type
(unprecedented + couples downstream readers to migration-specific
shapes). Operators recovering from a bad apply restore the ledger
directory from backup + manually mark the migration un-applied via
:func:`orchestrator.migrations.state.mark_unapplied` (per the
ledger/0001 + ledger/0002 precedent).

Refuse-on-missing-ledger
------------------------

Same shape as ledger/0001 + ledger/0002: raises ``FileNotFoundError``
if ``ctx.ledger_dir`` does not exist. Operators with a fresh state
dir emit at least one event through the normal send path before
invoking the migration, or ``mkdir -p`` the directory.

Contract
--------

* **Append-only.** No historical events are rewritten; only new
  ``enrolled_source_skill_backfill`` events are appended.
* **Per-event idempotent.** Already-backfilled events are skipped.
* **Always emits ``migration_event``.** Per ADR-0010 D17 — every
  ledger migration's audit-trail event lands regardless of whether
  the apply did work.
* **Cross-pillar audit safe.** The new event class
  (``enrolled_source_skill_backfill``) is rejected by every existing
  closed-set predicate per ADR-0036 D171's verdicts.
* **Refuses-loud on unknown source_skill.** A legacy ``source`` value
  that normalizes to anything OTHER than the closed-set is the operator's
  signal to investigate — the migration raises rather than silently
  emitting an event with an unknown skill.

See ADR-0036 D170 for the design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..runner import RUNNER_VERSION
from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._ledger_io import (
    append_event_atomic,
    emit_migration_event,
    events_by_type,
    iter_events,
)


MIGRATION_ID = "0007_backfill_enrolled_source_skill"


# The new event class emitted by this migration. Reserved here as a
# module constant so consumers (the cross-pillar audit; future Pillar G
# dashboards) can import the type-name without re-typing the string.
BACKFILL_EVENT_TYPE = "enrolled_source_skill_backfill"


def _import_runtime_helpers():
    """Lazy-load orchestrator.discovery_lineage.

    Defers the import to runtime so test isolation stays clean (per
    the prior migration modules' convention).
    """
    from orchestrator import discovery_lineage as _dl
    return _dl


@dataclass
class BackfillEnrolledSourceSkill:
    """Append ``enrolled_source_skill_backfill`` for every historical
    ``enrolled`` event lacking ``source_skill``.

    Per ADR-0036 D170. See module docstring for the full contract.
    Thin dataclass implementing the ``Migration`` Protocol.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.LEDGER
    description: str = (
        "Append enrolled_source_skill_backfill events for every "
        "historical enrolled event that lacks the canonical "
        "source_skill field. Normalizes the legacy enrolled.source "
        "value via discovery_lineage.normalize_legacy_source_to_skill. "
        "Pillar E Week 9-11 — per ADR-0036 D170."
    )
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Append backfill events for every historical ``enrolled`` event
        lacking ``source_skill``.

        Walks the ledger twice:

        1. Pass 1 — identify ``enrolled`` events lacking ``source_skill``.
        2. Pass 2 — build the already-backfilled set from existing
           ``enrolled_source_skill_backfill`` events (idempotence).
        3. Append backfill events for the difference.

        Always emits one ``migration_event`` at the end per
        ADR-0010 D17.

        Raises
        ------
        FileNotFoundError:
            When ``ctx.ledger_dir`` does not exist on disk. Same
            posture as ledger/0001.
        ValueError:
            When a derived ``source_skill`` is somehow unknown (the
            normalize_legacy_source_to_skill should always return a
            valid enum value, so this is a defensive guard against
            future bugs).
        """
        if ctx.ledger_dir is None:
            raise ValueError(
                f"ledger migration {self.id!r} requires ctx.ledger_dir."
            )
        ledger_dir = Path(ctx.ledger_dir)
        if not ledger_dir.exists():
            raise FileNotFoundError(
                f"ledger migration {self.id!r}: ctx.ledger_dir does not "
                f"exist on disk: {ledger_dir}. Either initialize the "
                f"ledger via the normal send path or `mkdir -p {ledger_dir}` "
                f"before re-running apply."
            )

        _dl = _import_runtime_helpers()
        normalize_fn = _dl.normalize_legacy_source_to_skill

        # Pass 1 — find enrolled events lacking source_skill.
        enrolled_needing_backfill: list[dict] = []
        skipped_already_canonical = 0
        skipped_no_source = 0
        for ev in events_by_type(ledger_dir, "enrolled"):
            if ev.get("source_skill"):
                # Post-Week-9-11 emit — already has the canonical field.
                skipped_already_canonical += 1
                continue
            if not ev.get("source"):
                # Pre-source-attribution emit (very old events from
                # pre-Phase-5.5-Week-2). Can't backfill without a source;
                # the consumer's last-resort path will inline-normalize
                # to "manual" via normalize_legacy_source_to_skill(None).
                skipped_no_source += 1
                continue
            ts = ev.get("ts")
            person_id = ev.get("person_id")
            if not (ts and person_id):
                # Malformed event — refuse to backfill (the consumer
                # would have no pairing key).
                skipped_no_source += 1
                continue
            enrolled_needing_backfill.append(ev)

        # Pass 2 — build the already-backfilled set for idempotence.
        # Per Week 9-11 review P2-B — key on (ts, person_id) tuple, not
        # ts alone. Two enrolled events for different Persons sharing the
        # same `ts` (rare at production sub-ms precision; common in test
        # fixtures with hand-picked timestamps; possible in batch
        # imports with truncated-second timestamps) MUST each get their
        # own backfill event. A ts-only key would silently drop the
        # backfill for a third Person whose enrolled.ts matches a pair
        # already backfilled.
        already_backfilled_pairs: set[tuple[str, str]] = set()
        for ev in events_by_type(ledger_dir, BACKFILL_EVENT_TYPE):
            ts = ev.get("_backfill_of_ts")
            pid = ev.get("person_id")
            if ts and pid:
                already_backfilled_pairs.add((ts, pid))

        affected = 0
        skipped_idempotent = 0
        per_skill_count: dict[str, int] = {}

        for orig in enrolled_needing_backfill:
            orig_ts = orig["ts"]
            orig_pid = orig["person_id"]
            if (orig_ts, orig_pid) in already_backfilled_pairs:
                skipped_idempotent += 1
                continue

            canonical_skill = normalize_fn(orig.get("source"))
            if canonical_skill not in _dl.SOURCE_SKILLS:
                # Defensive guard — normalize_fn always returns a valid
                # value per its contract (unknown → "manual"); this
                # branch should be unreachable.
                raise ValueError(
                    f"normalize_legacy_source_to_skill returned an "
                    f"unknown canonical skill {canonical_skill!r} for "
                    f"legacy source={orig.get('source')!r}. The contract "
                    f"in discovery_lineage.py guarantees a value in "
                    f"SOURCE_SKILLS; this is a defensive guard."
                )

            payload = _dl.build_enrolled_source_skill_backfill_payload(
                person_id=orig["person_id"],
                source_skill=canonical_skill,
                backfill_of_ts=orig_ts,
                migration_id=self.id,
            )

            ctx.logger.info(
                "%s: appending backfill for enrolled event ts=%s "
                "person_id=%s legacy_source=%s → source_skill=%s",
                self.id, orig_ts, orig["person_id"],
                orig.get("source"), canonical_skill,
            )
            if not ctx.dry_run:
                append_event_atomic(ledger_dir, payload)
            affected += 1
            per_skill_count[canonical_skill] = (
                per_skill_count.get(canonical_skill, 0) + 1
            )

        verb = "would append" if ctx.dry_run else "appended"
        ctx.logger.info(
            "%s %d enrolled_source_skill_backfill events "
            "(per_skill=%s; "
            "%d already canonical; %d no source field; "
            "%d already backfilled — idempotent skip)",
            verb, affected, per_skill_count,
            skipped_already_canonical, skipped_no_source,
            skipped_idempotent,
        )

        if not ctx.dry_run:
            emit_migration_event(
                ledger_dir,
                migration_id=self.id,
                affected_count=affected,
                runner_version=RUNNER_VERSION,
                category=self.category.value,
                notes=(
                    f"per_skill={per_skill_count}; "
                    f"skipped_already_canonical={skipped_already_canonical}; "
                    f"skipped_no_source={skipped_no_source}; "
                    f"skipped_idempotent={skipped_idempotent}"
                ),
            )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} {affected} enrolled_source_skill_backfill "
                f"events (per_skill={per_skill_count}; "
                f"already_canonical={skipped_already_canonical}; "
                f"no_source={skipped_no_source}; "
                f"already_backfilled={skipped_idempotent})"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Append-only ledger — rollback unsupported.

        Per ADR-0010 D14 the ledger is append-only at the file level;
        the framework refuses ``rollback`` on ``is_reversible=False``
        migrations via ``MigrationNotReversibleError`` (the runner
        handles the refusal before this method is invoked).

        This stub is present for the Migration Protocol's shape; the
        runner's reversibility check prevents the actual call.
        """
        raise NotImplementedError(
            f"ledger migration {self.id!r} is append-only per "
            f"ADR-0010 D14; rollback is unsupported. Restore the "
            f"ledger directory from backup if a rollback is needed."
        )


MIGRATION: BackfillEnrolledSourceSkill = BackfillEnrolledSourceSkill()


__all__ = [
    "BACKFILL_EVENT_TYPE",
    "BackfillEnrolledSourceSkill",
    "MIGRATION",
    "MIGRATION_ID",
]
