# ADR-0036: Pillar E Week 9-11 — per-skill discovery_lineage stamping refactor + research-prospect integration

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** E (Discovery quality + lineage — Week 9-11 per-skill stamping refactor + vault migration + research-prospect integration)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0032 (Pillar E Week 1 foundation) pinned the discovery-lineage shape (D142), the pre-enrichment dedup contract (D143), the email-verification cache shape (D144), the tier auto-assignment substrate (D145), the cross-pillar surface audit (D146), the exit-criterion vehicle scope (D147), and the privacy-respecting invariant (D148). ADR-0033 (Pillar E Week 2) shipped the dedup primitive module (`orchestrator/discovery_dedup.py`) + the per-skill integration in `find-leads` + Amendment 2026-05-24 extending integration to `find-funded-founders` (Phase 4f) + `competitor-customers` (Phase 3e). ADR-0034 (Pillar E Week 4-5) shipped the email-verification cache primitive module (`orchestrator/email_verification_cache.py`) + the wrap inside `orchestrator/enrich_emails.py::verify_with_reoon` + the content-additive cost-event schema extension (`email` + `verification_response` fields per D156). ADR-0035 (Pillar E Week 6-8) shipped the tier auto-assignment primitive module (`orchestrator/tier_assignment.py`) + the operator-tunable per-signal weights config (`config-template/tier_weights.example.yml`) + the operator-invoked CLI surface (`python orchestrator/tier_assignment.py suggest --person <id> [--apply]`). All four prior primitives share the structural shape: per-call primitive + event-emit-shape factory + ledger substrate + CLI surface + per-week cross-pillar audit row extension.

**Pillar E Week 9-11 is the per-skill discovery_lineage stamping refactor + the coordinating vault migration + the research-prospect integration.** The handoff (`.planning/HANDOFF-pillar-e-week-9.md` — committed in the Week 6-8 main commit) scopes Week 9-11 to: (a) a new top-level module `orchestrator/discovery_lineage.py` carrying the `DiscoveryLineage` dataclass + the canonical `SOURCE_SKILLS` enum home (moved from `discovery_dedup.py:96`) + the frontmatter serialize/deserialize factories; (b) a vault migration `vault/0005_add_discovery_lineage_to_identity_keys` backfilling the `identity_keys.discovery_lineage:` sub-block on pre-Pillar-E-Week-9-11 Person notes; (c) a ledger migration `ledger/0007_backfill_enrolled_source_skill` appending synthetic backfill events for historical `enrolled` events that lack the `source_skill` field (analog of the rename per the P3-A from Week 1's audit — the append-only ledger forbids in-place rewrites per ADR-0010 D14); (d) coordinated per-skill integration in all four discovery skills' SKILL.md files (find-leads, find-funded-founders, competitor-customers, research-prospect) + the new `enroll_person` kwargs surface; (e) the cross-pillar audit row extension walking the new block + the new event class + the new field's consumer surfaces; (f) the un-skip of the remaining three `TestDiscoveryLineage` coherence rows.

The split — dedup in Week 2-3 + cache in Week 4-5 + tier-suggestion in Week 6-8 + per-skill lineage stamping deferred to Week 9-11 — bounds each week's failure radius: a stamping-refactor bug in Week 9-11 is one Python module + two migrations + four SKILL.md frontmatter templates + their tests; a multi-pillar rework that bundled stamping with any of the prior primitives would compound risk. The Week 9-11 commit is the LAST primitive-shipping week before Week 12's exit-criterion test un-skip + Pillar E Stable flip.

The six concerns this ADR resolves:

1. **The discovery-lineage primitive module's PLACEMENT must be pinned before the implementation lands.** Four plausible homes: (a) `orchestrator/discovery_lineage.py` (top-level, sibling of `discovery_dedup.py` + `email_verification_cache.py` + `tier_assignment.py` + `enrollment.py` + `identity.py`); (b) inside `orchestrator/enrollment.py` (conflates lineage-as-provenance with enrollment-as-creation); (c) inside `orchestrator/identity.py` (conflates lineage-as-provenance with identity-as-resolution); (d) inside `orchestrator/discovery_dedup.py` (conflates lineage with dedup — the dedup primitive is one CONSUMER of the lineage's `source_skill` field, not the owner of the lineage primitive); (e) a new `orchestrator/discovery/` subpackage gathering dedup + lineage + tier under one namespace (over-organization for one module in Week 9-11; the precedent at Pillar E primitives is sibling-at-top-level). D166 picks (a). The placement mirrors ADR-0033 D149's + ADR-0034 D154's + ADR-0035 D160's sibling-of-existing-primitives shape — the lineage primitive IS a Pillar E primitive in its own right.

2. **The `DiscoveryLineage` dataclass's SHAPE + construction-time invariants must be pinned per ADR-0032 D142's schema.** Per D142 the four required fields are `source_skill` (closed enum) + `source_list` (operator-private free-form) + `scraped_at` (ISO 8601 UTC timestamp) + `raw_input_hash` (SHA256-prefixed hex). D142 names the construction-time enum-validation requirement; D167 pins the actual enforcement (frozen dataclass + `__post_init__` validating the enum membership + the sha256-prefix check + the empty-string refusal for the two free-form fields). The canonical `SOURCE_SKILLS: frozenset[str]` enum's home moves from `discovery_dedup.py:96` (Week 2's temporary reservation per ADR-0033's authoring note) to `discovery_lineage.py` (the primitive's own home); `discovery_dedup.py` updates to import from the canonical home (single source of truth). D167 also pins the `build_discovery_lineage_dict(...)` factory for frontmatter serialization + the `parse_discovery_lineage_dict(...)` factory for frontmatter deserialization — both used by enrollment (write side) + the tier primitive (read side) + future Pillar G dashboards.

3. **The VAULT MIGRATION's BACKFILL STRATEGY must be pinned with operator-visible degradation.** Per D142 + the §Existing-operator seed convention from prior Pillar E weeks, the vault migration backfills the `identity_keys.discovery_lineage:` sub-block on existing Person notes. Four plausible backfill sources, in operator-trustworthiness order: (a) parse the operator's `_source.md` files (if present in the vault — the operator's own curated lead-list metadata is the richest provenance); (b) read the existing `source_channel:` Person frontmatter field (the discovery skills' legacy field — present on most post-Phase-5.5 enrollments); (c) read the legacy `enrolled` event's `source` field from the ledger (denormalized provenance — works even when the Person note's frontmatter has been hand-edited); (d) fall back to `source_skill: manual` (the floor — every pre-Week-9-11 Person without parseable provenance gets the manual default). D168 picks the cascade (a) → (b) → (c) → (d) with operator-visible stderr summary at apply time: the migration logs the count of Persons backfilled per source + the count of fall-back-to-manual + the operator's manual-resolution path (run `python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>` for any Person whose source_skill should be a non-manual value).

4. **The PER-SKILL INTEGRATION TRAJECTORY must be pinned — four skills simultaneously.** Two plausible trajectories: (a) staggered per-skill integration across Weeks 9 + 10 + 11 (mirroring the dedup primitive's two-week per-skill trajectory at Week 2 + Week 3 + Week 9-11 per ADR-0033 D152); (b) single-commit four-skill integration (Week 9-11 ships all four simultaneously). D169 picks (b). The rationale: the lineage stamping is structurally simpler than the dedup-primitive integration — the dedup integration added a pre-enrichment phase to each skill (a new SKILL.md sub-phase + a new CLI invocation + new bucket types in the lead-list table); the lineage stamping is one frontmatter sub-block added to the existing enrollment template + the four new flags on the existing `python enrollment.py enroll` invocation. The single-commit shape lands the canonical block uniformly across all four skills; an operator running any discovery skill post-Week-9-11 gets the canonical block stamped. D169 also pins the integration site (the `enroll_person` kwargs surface gains `lineage: DiscoveryLineage | None` + four new CLI flags `--source-skill / --source-list / --scraped-at / --raw-input-hash` on the existing `enroll` subcommand) + the research-prospect integration's special shape (per-prospect rather than per-list — its `source_list` value inherits from the existing Person's `source_list` if any, OR falls back to a new conventional value `[[research-prospect-deep-dives]]`; per-prospect dedup-check sub-phase added per D152's deferred trajectory).

5. **The LEDGER MIGRATION must rename `enrolled.source` → `enrolled.source_skill` per the P3-A from Week 1's audit, but the ledger is APPEND-ONLY.** Per ADR-0010 D14 the ledger forbids in-place event rewrites. Three plausible append-only patterns for the rename: (a) emit a new event class `enrolled_source_skill_backfill` paired with each historical `enrolled` event (the migration walks every pre-Week-9-11 `enrolled` event lacking the `source_skill` field, normalizes the legacy `enrolled.source` value via `discovery_lineage.normalize_legacy_source_to_skill()`, appends a backfill event carrying the normalized value + `_backfill_of: <original_ts>` + `_recovered_by: migration_0007_...`); (b) append a synthetic duplicate `enrolled` event with the canonical `source_skill` field (rejected — DOUBLES the enrollment count for every affected Person, breaks any consumer counting enrollments); (c) skip the migration entirely and inline-normalize at every consumer (rejected — every future consumer needs to know about the legacy `enrolled.source` field + the normalization map; the migration's role is to make `source_skill` directly readable from a ledger event, eliminating the inline-normalization burden). D170 picks (a). The migration's `is_reversible=False` per the append-only ledger discipline (analog of ledger/0001 + ledger/0002). The cross-pillar audit's row treatment of the new event class verifies every closed-set consumer rejects the new type (the new event class adds zero downstream broadening per the audit's verdict).

6. **The cross-pillar surface audit (per ADR-0032 D146) MUST be extended row-by-row each Pillar E week.** Week 9-11 ships THREE new surfaces (the `identity_keys.discovery_lineage:` Person frontmatter block + the `enrolled.source_skill` ledger event field + the `enrolled_source_skill_backfill` ledger event class). Each surface needs an audit row treatment per ADR-0033 D153 + ADR-0034 D158 + ADR-0035 D165 conventions: walk every existing Pillar A/B/C/D + prior-Pillar-E consumer, verify each is either closed-set-protected or by-design-broadening. D171 names the audit extension + the per-consumer verdicts.

Risks this ADR mitigates by design: **R001 (identity-graph false-merge cascade)** is not regressed — the discovery_lineage sub-block is INSIDE the existing `identity_keys:` block but is OPAQUE TO the identity resolver (`identity.find_matches` reads only the `linkedin` / `emails` / `github` / `twitter` / `alt_names` sub-fields; the new `discovery_lineage` sub-field is structurally ignored by the resolver). **R018 (discovery-source poisoning)** is mitigated by design — the `raw_input_hash` field surfaces the operator's scrape provenance for post-hoc audit (an operator who suspects a lead list was poisoned can grep `enrolled.discovery_lineage.raw_input_hash == <suspect_hash>` to identify every affected Person). **R020 (email-verification cache staleness)** is unchanged — the lineage primitive does not depend on the cache primitive's substrate. **R021 (tier-weights config drift)** is unchanged — the lineage primitive operates upstream of the tier primitive; the tier primitive's `discovery_lineage.source_skill` consumption now reads the canonical field (post-Week-9-11) or the legacy `source_channel` fallback (pre-Week-9-11) — the tier primitive's fallback path stays in place at Week 9-11 ship time per the operator-comfort discipline. The asymmetric-failure-cost calculus per PILLAR-PLAN §0 carries: a false-positive stamping (e.g. mis-attributing a competitor-customers discovery to find-leads) is one operator-visible field on the Person note + one ledger event — the operator corrects via the CLI's `--source-skill` override; a false-negative stamping (the canonical block absent on a NEW enrollment) is caught by the un-skipped `TestDiscoveryLineage::test_every_new_enrollment_carries_canonical_discovery_lineage` coherence test — fails loud at CI before the regression lands in production. Both failure costs are bounded + asymmetric in the operator-friendly direction.

One new risk surfaces in this ADR's authoring + named in `docs/RISK-REGISTER.md`:
- **R022 (discovery_lineage backfill heuristic precision)** — the vault migration's backfill cascade (D168) prefers `_source.md` files when parseable, falls back through `source_channel:` → ledger `enrolled.source` → `source_skill: manual`. The cascade's per-source confidence is bounded but not guaranteed: (a) `_source.md` parsing depends on the operator's file-shape convention (markdown vs YAML vs free-form); (b) `source_channel:` legacy values use shortened naming (`"funded-founders"` not `"find-funded-founders"`) — the normalization map MUST cover every legacy value; (c) Persons enrolled via the legacy `enroll_person` path before the `source_channel:` field convention land on the `source_skill: manual` floor. Mitigation by design: the migration's stderr summary names the per-source backfill count at apply time + names the count that fell to manual; operators rerun `python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>` per-Person to correct any false-manual; the per-week reviewer's category §3 (per §D171) pins this as a follow-up check.

R001 + R018 + R019 + R020 + R021 (named in ADR-0032 + ADR-0035 §Context) carry the design-time mitigation forward; the Week 9-11 implementation does not regress these.

## Decision

### D166. Discovery-lineage primitive module placement — `orchestrator/discovery_lineage.py`

The discovery-lineage primitive ships as a single top-level module under `orchestrator/`, sibling of every other Pillar E primitive + the Pillar 5.5 primitives + the Pillar D primitive:

```
orchestrator/
├── discovery_lineage.py             ← NEW (Pillar E Week 9-11)
├── tier_assignment.py               ← Pillar E Week 6-8 (the SIBLING primitive)
├── email_verification_cache.py      ← Pillar E Week 4-5 (sibling primitive)
├── discovery_dedup.py               ← Pillar E Week 2 (sibling primitive — imports SOURCE_SKILLS from discovery_lineage)
├── enrich_emails.py                 ← Pillar A Week 4 (Reoon call site)
├── enrollment.py                    ← Pillar 5.5 Week 1b (consumes DiscoveryLineage for write-side stamping)
├── identity.py                      ← Pillar 5.5 Week 1b
├── reply_classifier.py              ← Pillar D Week 2
├── ledger.py
├── reconcile.py
├── policy/
│   └── tier.py                      ← Pillar A's tier RULE (consumer of operator-stamped value)
└── ...
```

**The lineage primitive is a Pillar E primitive, not a sub-helper of any prior module.** Like the dedup primitive (per ADR-0033 D149) + the cache primitive (per ADR-0034 D154) + the tier primitive (per ADR-0035 D160), the lineage primitive OWNS a canonical schema (the `DiscoveryLineage` dataclass + the `SOURCE_SKILLS` enum) + EXPORTS factories (`build_discovery_lineage_dict` + `parse_discovery_lineage_dict`) + DEFINES the construction-time validation. The four-step substrate decoupling per ADR-0032 D142 + this Week 9-11 commit:

1. **Lineage primitive OWNS** the canonical schema + the enum + the validation (Week 9-11 ships).
2. **Discovery skills CONSUME** the schema at enrollment time (each skill's CLI invocation stamps the four fields via the new enrollment kwargs).
3. **Enrollment primitive WRITES** the lineage as an `identity_keys.discovery_lineage:` sub-block to Person frontmatter + denormalizes it to the emitted `enrolled` event (existing enrollment.py extended per D170).
4. **Tier primitive + future Pillar G dashboards READ** the canonical lineage via `parse_discovery_lineage_dict` (Week 9-11 makes this read canonical; the tier primitive's legacy `source_channel` fallback stays in place for operator-comfort during the migration window).

Putting the lineage primitive INSIDE any existing module would collapse the four-step decoupling — operators reading `enrollment.py` would conflate the lineage-as-provenance with the enrollment-as-creation. The sibling-of-existing-primitives placement (D166's choice) preserves the separation.

**Top-level placement matches the existing per-primitive convention.** `orchestrator/discovery_dedup.py` + `orchestrator/email_verification_cache.py` + `orchestrator/tier_assignment.py` are each Pillar E primitives at this level. The lineage primitive follows the same shape. An `orchestrator/discovery/` subpackage would be over-organization for Week 9-11's ~500 LOC + would require coordinated import-path migration across the prior three Pillar E primitives — the cost is higher than the structural benefit at Week 9-11's scope. The subpackage rationale resurfaces in a future Pillar I OSS bring-up week IF the discovery surface grows to 4+ modules (e.g., per-tenant lineage namespace per the Pillar I forward-reference).

**Why NOT inside `orchestrator/enrollment.py`?** Conflates lineage-as-provenance with enrollment-as-creation. `enrollment.py` is the post-enrichment write-side primitive — it stamps `identity_keys`, mints person_ids, emits `enrolled` events. The lineage primitive's job is to DEFINE the schema + VALIDATE the values + PROVIDE the factories; the write-side consumption inside `enrollment.py` is one CALLER of the lineage primitive, not the owner. Putting the schema + the validation inside `enrollment.py` would (i) bloat the enrollment surface; (ii) tempt a future contributor to inline-validate at every call site (the operator-private fields' validation must be centralized so a future skill author cannot accidentally bypass it); (iii) couple the read-side consumers (tier primitive + future Pillar G dashboards) to the write-side module (they would have to import enrollment.py just to parse the lineage block — circular import risk).

**Why NOT inside `orchestrator/identity.py`?** Conflates lineage-as-provenance with identity-as-key-resolution. `identity.py` is the strict-policy resolver — it intersects identity keys + refuses ambiguous matches. The lineage primitive is structurally ADJACENT to identity (the `discovery_lineage:` block lives as a sub-block of `identity_keys:` per D142) but the resolver does NOT consult the lineage sub-block at all — only the strong-key sub-fields (`linkedin` / `emails` / `github` / `twitter`). Putting the lineage primitive inside `identity.py` would (i) suggest the resolver consults the lineage (it doesn't); (ii) co-mingle key-resolution semantics with provenance semantics; (iii) bloat `identity.py` past its single-purpose contract.

**Why NOT inside `orchestrator/discovery_dedup.py`?** Conflates lineage-as-provenance with dedup-as-prevention. The dedup primitive (Week 2) was the FIRST consumer of the `source_skill` enum (the dedup primitive emits events stamping `source_skill: <skill>`); the Week 2 ADR-0033's authoring note explicitly reserved the `SOURCE_SKILLS` enum at `discovery_dedup.py:96` "with the canonical home moving to `orchestrator/discovery_lineage.py` in a future Pillar E week." Week 9-11 IS that future week. The canonical home move + the broader lineage primitive don't belong in the dedup module — the dedup module is the consumer of the enum, not its owner.

**Why NOT an `orchestrator/discovery/` subpackage?** Over-organization for Week 9-11's scope (~500 LOC of lineage primitive + tests). The single-file convention used by every other Pillar E primitive is the precedent. The subpackage rationale resurfaces IF a future week adds a sibling lineage-related primitive (e.g., per-tenant lineage namespaces; provenance-graph traversal; multi-source attribution). At Week 9-11 the prior three Pillar E primitives stay at top-level; the lineage primitive joins them.

### D167. `DiscoveryLineage` dataclass shape — construction-time invariants + canonical SOURCE_SKILLS home

Per ADR-0032 D142's schema + the construction-time validation requirement. The `DiscoveryLineage` dataclass:

```python
from dataclasses import dataclass
from typing import ClassVar

# Canonical home for the closed-enum of discovery skills. Moves
# from discovery_dedup.py:96 (Week 2 reservation) to here per
# D166 module placement.
SOURCE_SKILLS: frozenset[str] = frozenset({
    "find-leads",
    "find-funded-founders",
    "competitor-customers",
    "research-prospect",
    "manual",
})


_SHA256_HEX_LEN: int = 64


@dataclass(frozen=True)
class DiscoveryLineage:
    """The provenance of a Person enrollment per ADR-0032 D142.

    Frozen + construction-time-validated. The four required fields
    capture WHICH discovery skill surfaced the prospect, WHICH
    operator-supplied list the surface came from, WHEN the scrape
    landed, and WHAT the canonical raw-input hash was (for
    dedup-of-scrapes + provenance audit).

    Constructed at the discovery skill's enrollment site; serialized
    via :func:`build_discovery_lineage_dict` into the Person
    frontmatter's ``identity_keys.discovery_lineage:`` sub-block +
    denormalized into the emitted ``enrolled`` event's
    ``source_skill`` / ``source_list`` / ``scraped_at`` /
    ``raw_input_hash`` fields per D170.

    Construction-time invariants:

    * ``source_skill`` MUST be one of :data:`SOURCE_SKILLS` —
      ``ValueError`` on unknown values (refuse-loud per D167).
    * ``source_list`` MUST be a non-empty string —
      ``ValueError`` on empty / whitespace-only values.
    * ``scraped_at`` MUST be an ISO 8601 UTC timestamp matching
      ``YYYY-MM-DDTHH:MM:SSZ`` — ``ValueError`` on shape
      violations. (Tolerant of fractional seconds + explicit
      ``+00:00`` offset; rejects naive timestamps.)
    * ``raw_input_hash`` MUST be ``"sha256:<64-hex>"`` —
      ``ValueError`` on prefix mismatch or wrong-length hex.

    Operator-private posture for ``source_list`` per ADR-0032
    D148 — the framework treats the field as an opaque string +
    Pillar G dashboards filter on ``source_skill`` but NEVER on
    ``source_list``.
    """

    source_skill: str
    source_list: str
    scraped_at: str
    raw_input_hash: str

    def __post_init__(self) -> None:
        if self.source_skill not in SOURCE_SKILLS:
            raise ValueError(
                f"source_skill {self.source_skill!r} not in "
                f"SOURCE_SKILLS {sorted(SOURCE_SKILLS)!r}; per "
                f"ADR-0032 D142 the enum is closed-set + "
                f"construction-time-validated"
            )
        if not (
            isinstance(self.source_list, str)
            and self.source_list.strip()
        ):
            raise ValueError(
                f"source_list must be a non-empty string per "
                f"ADR-0032 D142; got {self.source_list!r}"
            )
        if not _is_iso8601_utc(self.scraped_at):
            raise ValueError(
                f"scraped_at must be ISO 8601 UTC (YYYY-MM-"
                f"DDTHH:MM:SSZ) per ADR-0032 D142; got "
                f"{self.scraped_at!r}"
            )
        if not _is_sha256_prefixed(self.raw_input_hash):
            raise ValueError(
                f"raw_input_hash must be 'sha256:<64-hex>' per "
                f"ADR-0032 D142; got {self.raw_input_hash!r}"
            )
```

**Why a frozen dataclass (rejected: dict; rejected: pydantic model; rejected: TypedDict).** Three reasonable shapes: (a) frozen dataclass with `__post_init__` validation (D167's choice); (b) plain dict (no construction-time validation); (c) pydantic model (extra dependency for one class). The rationale:

* **(a) honors the Pillar E primitive convention.** Every prior Pillar E primitive's emit-shape class is a frozen dataclass: `DedupResult` (ADR-0033 D149), `EmailVerificationCacheResult` (ADR-0034 D155), `TierSuggestion` (ADR-0035 D161). The lineage primitive's data class follows the same shape — immutable, validated-at-construction, hashable + comparable.
* **(b) skips the validation.** The closed-enum + sha256-prefix invariants exist ONLY at the validation site — a dict-shaped lineage would push the validation to every call site, inviting drift (the prior Pillar B Week 6 P2 incidents — see `_vault_io.is_note_type`'s consolidation — are the precedent for centralizing repeated validation).
* **(c) adds a dependency.** `pydantic` is not in the framework's dependency manifest; introducing it for one class would force every consumer to import + every test environment to install. The frozen-dataclass shape is the right grain.

**Why the SOURCE_SKILLS canonical home moves here (vs staying in `discovery_dedup.py`).** Three plausible homes: (a) `discovery_lineage.py` (D167's choice — the canonical owner of the lineage primitive); (b) `discovery_dedup.py:96` (Week 2's temporary reservation per ADR-0033's authoring note); (c) `enrollment.py` (one of the consumers — but consumer-owns-schema collapses the four-step decoupling D166 preserves). D167 picks (a). The rationale:

* **The enum is the lineage's schema.** The `SOURCE_SKILLS` enum is the closed-set of values the `source_skill` field can take per ADR-0032 D142. Owning the schema next to the data class (vs in a consumer module) is the structural shape every Pillar E primitive ships (the dedup primitive's `_RESULT_STATUSES` lives next to `DedupResult`; the tier primitive's `SUGGESTED_TIERS` lives next to `TierSuggestion`; the lineage primitive's `SOURCE_SKILLS` lives next to `DiscoveryLineage`).
* **`discovery_dedup.py` becomes a consumer.** Post-Week-9-11, `discovery_dedup.py` imports `SOURCE_SKILLS` from `discovery_lineage.py`. The authoring note at `discovery_dedup.py:86-95` explicitly anticipated this move. The Week 9-11 commit removes the local copy + updates the import (any test referencing the dedup module's local `SOURCE_SKILLS` continues to work via the import — Python re-exports automatically; no test breakage expected).

**Frontmatter serialization factories — `build_discovery_lineage_dict` + `parse_discovery_lineage_dict`.** Two helpers cover the round-trip:

```python
def build_discovery_lineage_dict(lineage: DiscoveryLineage) -> dict:
    """Render a :class:`DiscoveryLineage` as the canonical YAML-ready dict.

    The output is the exact shape that goes into the Person
    frontmatter's ``identity_keys.discovery_lineage:`` sub-block +
    the ``enrolled`` event's denormalized ``discovery_lineage:``
    field. Key order matches the D142 schema (source_skill +
    source_list + scraped_at + raw_input_hash) for operator-readable
    YAML ordering.
    """
    return {
        "source_skill": lineage.source_skill,
        "source_list": lineage.source_list,
        "scraped_at": lineage.scraped_at,
        "raw_input_hash": lineage.raw_input_hash,
    }


def parse_discovery_lineage_dict(
    block: dict | None,
) -> DiscoveryLineage | None:
    """Parse a frontmatter sub-block (or `enrolled` event payload)
    back into a :class:`DiscoveryLineage` instance.

    Returns ``None`` when ``block`` is ``None`` (the lineage is
    absent on legacy Person notes; the caller decides how to handle).
    Raises ``ValueError`` via the dataclass's ``__post_init__`` if
    any field violates D142's invariants.

    Tolerant of:
    * Missing optional fields (raises ValueError — every field is
      required per D142).
    * Extra fields (silently ignored — future Pillar E weeks MAY
      extend the schema; the parser is forward-compatible).
    """
    if block is None:
        return None
    if not isinstance(block, dict):
        raise ValueError(
            f"discovery_lineage block must be a dict; got "
            f"{type(block).__name__}"
        )
    return DiscoveryLineage(
        source_skill=block.get("source_skill"),
        source_list=block.get("source_list"),
        scraped_at=block.get("scraped_at"),
        raw_input_hash=block.get("raw_input_hash"),
    )
```

**Why two factories (rejected: one bidirectional method; rejected: dataclass-asdict).** Three plausible shapes: (a) two free functions (`build_*` + `parse_*`) — D167's choice; (b) instance methods (`lineage.to_dict()` + `DiscoveryLineage.from_dict(...)`); (c) `dataclasses.asdict()` for write + manual dict construction for read. The free-function shape mirrors the dedup primitive's `build_discovery_dedup_hit_payload` / `build_discovery_dedup_conflict_payload` factories — operators reading the module see the I/O-boundary surface alongside the data class. Instance methods would scatter the I/O surface (callers must know to call `.to_dict()`); `asdict` would skip the deterministic key ordering D167 pins (Python's `asdict` honors field-declaration order but emits all fields including private ones — the explicit build factory is safer + more readable).

**Legacy-source normalization helper.** D170's ledger migration + the tier primitive's legacy-fallback path both need to map legacy `source_channel` values to canonical `source_skill` enum values. The mapping:

```python
LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL: dict[str, str] = {
    # Canonical mappings — the legacy field's shortened naming.
    "find-leads": "find-leads",
    "funded-founders": "find-funded-founders",
    "competitor-customers": "competitor-customers",
    "research-prospect": "research-prospect",
    # Permissive — operator-typed variants.
    "find-funded-founders": "find-funded-founders",
    "manual": "manual",
}


def normalize_legacy_source_to_skill(value: str | None) -> str:
    """Map a legacy ``source_channel`` value to a canonical
    ``source_skill`` enum value. Unknown values + ``None`` map to
    ``"manual"`` — the lossy floor per the §Existing-operator seed.

    The mapping IS the rename trajectory: pre-Pillar-E-Week-9-11
    Person notes carry ``source_channel: <legacy>``; the
    normalization makes them readable as canonical ``source_skill``
    without rewriting the legacy field.
    """
    if value is None:
        return "manual"
    return LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL.get(value, "manual")
```

The helper centralizes the legacy-value drift so the vault migration's backfill, the ledger migration's backfill, the tier primitive's legacy fallback path, and any future consumer all share one source of truth for the mapping.

### D168. Vault migration `vault/0005_add_discovery_lineage_to_identity_keys` — backfill strategy + new helper

The vault migration stamps the `identity_keys.discovery_lineage:` sub-block on every pre-Week-9-11 Person note. Per ADR-0011 D11's per-file atomic contract (tmp-then-rename with fsync). Migration shape:

```python
from dataclasses import dataclass
from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._vault_io import (
    extend_frontmatter_nested_block_text,  # NEW helper (D168)
    is_person_note,
    iter_person_notes,
    read_person_frontmatter,
    remove_frontmatter_nested_field_text,  # NEW helper (D168)
    write_person_frontmatter_atomic,
)


MIGRATION_ID = "0005_add_discovery_lineage_to_identity_keys"


@dataclass
class AddDiscoveryLineageToIdentityKeys:
    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.VAULT
    description: str = (
        "Add identity_keys.discovery_lineage: sub-block to every "
        "Person note with an existing identity_keys: block. "
        "Backfill cascade: _source.md if parseable → source_channel: "
        "frontmatter field → ledger enrolled.source → manual. "
        "Pillar E Week 9-11 — per ADR-0036 D168."
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult: ...
    def downgrade(self, ctx: MigrationContext) -> MigrationResult: ...


MIGRATION: AddDiscoveryLineageToIdentityKeys = (
    AddDiscoveryLineageToIdentityKeys()
)
```

**Backfill cascade per the operator-trustworthiness order:**

| Order | Source | Confidence | Coverage in Yang's vault |
|---|---|---|---|
| 1 | `_source.md` parseable | High (operator-curated list metadata; usually carries `source_skill` + `source_list` + `scraped_at` + the raw seed URL) | TBD per `_source.md` file convention (~5-10% of legacy Persons) |
| 2 | `source_channel:` frontmatter | Medium (the discovery skills' legacy field — present on most post-Phase-5.5 enrollments via the existing find-leads / find-funded-founders / competitor-customers SKILL.md templates) | ~60-70% of legacy Persons (every Person enrolled via a discovery skill since Phase 5.5) |
| 3 | Ledger `enrolled.source` | Medium (the ledger event's `source` field — present on every enrolled event since the field was added in Phase 5.5 Week 2; resilient to operator hand-edits of the Person frontmatter) | ~80-90% of legacy Persons (every Person with at least one enrolled event) |
| 4 | `source_skill: manual` floor | Low (no provenance available; the operator's manual-resolution path) | The residual ~5-15% — pre-Phase-5.5 enrollments + manually-edited frontmatter without source fields |

The migration logs the per-source backfill count at apply time:

```
INFO 0005_add_discovery_lineage_to_identity_keys: stamping discovery_lineage
INFO   from _source.md: 12 Persons (high-confidence)
INFO   from source_channel: frontmatter: 287 Persons (medium-confidence)
INFO   from ledger enrolled.source: 31 Persons (medium-confidence)
INFO   fallback to source_skill: manual: 18 Persons (low-confidence)
INFO total: 348 Persons stamped; 0 skipped (no identity_keys block); 0 errored
WARNING 18 Persons fell to source_skill: manual. Review with:
WARNING   python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>
WARNING for any Person whose source_skill should be a non-manual value.
```

The fall-back-to-manual count + the operator-resolution path is the R022 mitigation surface.

**`source_list` cascade per the source:**

| If source is... | source_list value... |
|---|---|
| `_source.md` (parseable) | The list filename (e.g., `[[2026-05-13-funded-founders]]`) extracted from `_source.md`'s `list:` field or the `_source.md`'s containing dir name |
| `source_channel:` frontmatter | The Person frontmatter's `source_list:` field if present; else the conventional `[[legacy-{source_channel}]]` tag (e.g., `[[legacy-find-leads]]`) |
| Ledger `enrolled.source` | The ledger event's `source_list` field if present; else the conventional `[[legacy-{normalized-skill}]]` tag |
| `source_skill: manual` floor | `[[legacy-manual]]` (the conventional manual-attribution tag) |

**`scraped_at` cascade per the source:**

| If source is... | scraped_at value... |
|---|---|
| `_source.md` (parseable) | The `scraped_at:` field from `_source.md` if present; else the file's mtime ISO 8601 |
| `source_channel:` frontmatter | The Person frontmatter's `created:` field if present; else the file's mtime ISO 8601 |
| Ledger `enrolled.source` | The `enrolled` event's `ts` field |
| `source_skill: manual` floor | The migration's apply-time ISO 8601 timestamp (with note in stderr: "manually-stamped at migration time") |

**`raw_input_hash` cascade per the source:**

| If source is... | raw_input_hash value... |
|---|---|
| `_source.md` (parseable) | The `raw_input_hash:` field from `_source.md` if present; else `sha256:<sha256-of-_source.md's-raw-text>` |
| `source_channel:` frontmatter | `sha256:<sha256-of-Person-note's-frontmatter-as-canonical-yaml>` (deterministic per-Person fingerprint) |
| Ledger `enrolled.source` | `sha256:<sha256-of-enrolled-event-payload-as-canonical-json>` (deterministic per-event fingerprint) |
| `source_skill: manual` floor | `sha256:<sha256-of-"manual:" + person_id>` (deterministic per-Person fingerprint for dedup-of-scrapes by `raw_input_hash`) |

The cascade order + the per-field cascades are operator-readable in the migration's module-level docstring; the per-Person backfill provenance is logged at INFO level (every backfilled Person's source-of-record is named in the log) so an operator can audit the migration's per-Person decisions post-apply.

**Why D168 ships TWO new `_vault_io` helpers — `extend_frontmatter_nested_block_text` + `remove_frontmatter_nested_field_text`.** The existing `add_frontmatter_block_text` (Pillar B Week 6 second follow-up) ADDS a NEW top-level block; D168 needs to EXTEND an EXISTING top-level block (the `identity_keys:` block) with a new nested sub-block (`discovery_lineage:` as a child of `identity_keys`). The existing `remove_frontmatter_field_text` REMOVES a top-level field; D168's downgrade needs to remove a nested sub-block. Three plausible approaches:

* **(a) Two new surgical helpers** (D168's choice). Mirrors the existing helpers' design — preserves comments + ordering of every other line. Targeted regex-based insert/remove at the nested level.
* **(b) Full YAML round-trip per-Person** — `yaml.safe_dump` the whole frontmatter dict with the extended `identity_keys` block. **Rejected** — destroys comments + reorders fields (operators' hand-curated YAML order is operator-visible).
* **(c) String concatenation inside the existing helper** — extend `add_frontmatter_block_text` to support nested insertion. **Rejected** — bloats the helper's surface + breaks the "one-level only" simplicity that the existing tests rely on.

The new helpers' signatures:

```python
def extend_frontmatter_nested_block_text(
    text: str,
    parent_key: str,
    child_key: str,
    child_block: dict,
    indent: int = 2,
) -> str:
    """Insert ``<child_key>:`` followed by a nested mapping block as
    the last child of an existing top-level ``<parent_key>:`` block.

    Strict insert — refuses to extend a parent that already contains
    ``<child_key>``; refuses if ``<parent_key>`` is not present. The
    caller handles idempotence (skip if the child is already present
    with the desired shape) before calling.

    Sibling to :func:`add_frontmatter_block_text` for nested-map
    extension. Pillar E Week 9-11 vault migration 0005 ships the
    discovery_lineage sub-block inside the existing identity_keys
    block; future Pillar E (or Pillar I) migrations needing similar
    nested-block insertion import this helper.

    Output shape: indented line per dict entry, appended as the last
    children of the parent block. Inherits ``_format_yaml_value``'s
    scalar conventions.

    Raises
    ------
    FrontmatterError:
        When ``text`` has no frontmatter delimiters; when
        ``<parent_key>:`` is not present at the top level of the
        frontmatter; when ``<child_key>`` is already present as a
        child of ``<parent_key>``; when any value in
        ``child_block`` is itself a list or dict (single-level
        nesting only).
    """


def remove_frontmatter_nested_field_text(
    text: str,
    parent_key: str,
    child_key: str,
) -> str:
    """Remove a nested sub-block from inside an existing top-level
    block. Inverse of :func:`extend_frontmatter_nested_block_text`.

    Preserves the rest of the parent block + every other line +
    comment. If the child is absent OR the parent is absent,
    returns ``text`` unchanged (idempotent removal — downgrade
    re-run is safe).

    Removes ONLY immediate children of the named parent. A
    deeper-nested key cannot be removed; that's a yet-deeper
    transformation requiring a YAML round-trip.
    """
```

**Why `is_reversible=True`?** The migration's inverse (remove the `discovery_lineage` sub-block) is well-defined + per-file atomic. The downgrade is the inverse of the upgrade; an operator who needs to roll back (e.g., a Pillar E Week 9-11 bug surfaces post-apply) can do so via `python -m orchestrator.migrations doctor rollback --migration vault/0005_...` (per the existing migration framework's rollback discipline). This mirrors `vault/0004`'s reversible posture (per ADR-0028 D119); `vault/0001` + `vault/0002`'s irreversible posture was for migrations that synthesized non-recoverable state (the migration's effect cannot be inverted in general).

### D169. Per-skill integration trajectory — single-commit four-skill stamping

Pillar E Week 9-11's commit ships the lineage stamping in all four discovery skills simultaneously, contrast to ADR-0033 D152's two-week staggered dedup-primitive trajectory (Week 2 find-leads + Week 3 find-funded-founders + competitor-customers + Week 9-11 research-prospect). Three plausible trajectories:

* **(a) Single-commit four-skill stamping** (D169's choice). All four skills' SKILL.md files + the `enroll_person` kwargs surface land together in the Week 9-11 main commit.
* **(b) Per-week staggered stamping** (mirroring the dedup primitive's two-week trajectory). Week 9 ships find-leads stamping; Week 10 ships find-funded-founders + competitor-customers; Week 11 ships research-prospect. **Rejected** — the staggered trajectory was right for the dedup primitive because the per-skill integration added a NEW pre-enrichment phase (a new SKILL.md sub-phase + a new CLI invocation + new bucket types). The lineage stamping is structurally simpler — one frontmatter sub-block added to the existing enrollment template + the four new flags on the existing `python enrollment.py enroll` invocation; the staggered split would inflate the commit count without proportional risk reduction.
* **(c) Defer per-skill stamping to Pillar I** (rely on the vault migration's backfill alone for legacy Persons + leave NEW enrollments un-stamped at Pillar E). **Rejected** — defeats D142's "every NEW Person enrollment carries the canonical block" invariant; the coherence test `TestDiscoveryLineage::test_every_new_enrollment_carries_canonical_discovery_lineage` requires per-skill stamping at Week 9-11.

**The integration site — `enroll_person` kwargs + CLI flags.** The `enrollment.enroll_person` function gains one new optional kwarg + four new CLI flags:

```python
def enroll_person(
    name: str,
    frontmatter: dict | None = None,
    body: str = "",
    cfg: dict | None = None,
    *,
    linkedin: str | None = None,
    emails: list[str] | None = None,
    github: str | None = None,
    twitter: str | None = None,
    alt_names: list[str] | None = None,
    lineage: DiscoveryLineage | None = None,  # NEW per D169
) -> dict:
    ...
```

When `lineage` is provided, `enroll_person`:
1. Includes `discovery_lineage: <dict>` as a sub-field of the `identity_keys` block in the Person frontmatter (via the new `_serialize_keys_block` extension).
2. Emits the `enrolled` event with `source_skill` + `source_list` + `scraped_at` + `raw_input_hash` denormalized from the lineage (per D170).
3. Stamps the same four fields on `enrollment_skipped_exists` + `enrollment_conflict` + `needs_identity_upgrade` events (symmetric per the Pillar E Week 1 P2-A pattern).

When `lineage` is None (back-compat — pre-Week-9-11 callers + the manual `python enrollment.py enroll` invocation without lineage flags), `enroll_person` falls back to the existing `fm_in.get("source_channel") or fm_in.get("source")` precedence + stamps the legacy `source` + `source_list` fields on the events (unchanged from Phase 5.5).

The CLI gains four flags + the existing `--frontmatter` continues to work:

```
python enrollment.py enroll --name <name> \
    [--linkedin <url>] [--email <addr> ...] \
    [--github <h>] [--twitter <h>] [--alt-name <name> ...] \
    [--frontmatter @file.yml | "<yaml>"] [--body @file.md | "<text>"] \
    [--source-skill <one of find-leads/find-funded-founders/competitor-customers/research-prospect/manual>] \
    [--source-list <list>] \
    [--scraped-at <iso8601-utc>] \
    [--raw-input-hash <sha256:hex>] \
    [--json]
```

When all four lineage flags are present (or are auto-defaulted — `--scraped-at` defaults to now-UTC; `--raw-input-hash` defaults to `sha256:<sha256-of-the-canonical-identity-keys>`), the CLI constructs a `DiscoveryLineage` instance + passes it as `lineage` to `enroll_person`. When any flag is absent without an auto-default, the CLI falls back to the legacy `--frontmatter`-driven path (back-compat for operators not yet updated to the lineage flags).

**Per-skill SKILL.md changes (Week 9-11):**

| Skill | Phase touched | Change |
|---|---|---|
| `find-leads` | Phase 4.5 (auto-enrollment) | The `python enrollment.py enroll` invocation gains four new flags: `--source-skill find-leads --source-list <list> --scraped-at <iso> --raw-input-hash sha256:<hex>`. The frontmatter YAML payload's `source_channel:` field is preserved (back-compat) but the lineage flags are the new canonical surface. |
| `find-funded-founders` | Phase 5.5 (auto-enrollment) | Same — four new flags. `--source-skill find-funded-founders`. |
| `competitor-customers` | Phase 4.5 (auto-enrollment) | Same — four new flags. `--source-skill competitor-customers`. |
| `research-prospect` | NEW Phase 4 sub-phase (per-prospect dedup + per-prospect stamping) | Phase 4 is the existing "Write/update vault entities" phase. NEW sub-phase 4a inserts a pre-update dedup-check (per ADR-0033 D152's deferred trajectory for research-prospect). NEW sub-phase 4b extends the Person frontmatter with the `discovery_lineage:` sub-block. The lineage flags' values: `--source-skill research-prospect --source-list <inherited from existing person OR [[research-prospect-deep-dives]]> --scraped-at <now> --raw-input-hash <sha256-of-canonical-input>`. |

The find-leads + find-funded-founders + competitor-customers integration is structurally identical (the four flags added to the existing CLI invocation in the existing auto-enrollment phase). The research-prospect integration is structurally different because research-prospect operates per-prospect rather than per-list — the SKILL.md changes are more substantive (one new sub-phase for dedup + one new sub-phase for lineage stamping).

**Why research-prospect ALSO ships the dedup integration in Week 9-11.** Per ADR-0033 D152 + the Pillar E Week 2 trajectory table, research-prospect was deferred to Week 9-11 for two reasons: (a) the dedup check is per-prospect not per-list (structurally different from the other three skills' per-list integration); (b) the dedup check coincides naturally with the discovery_lineage stamping refactor. Week 9-11 honors both — the research-prospect integration adds a pre-update dedup-check (using the existing `discovery_dedup.check_dedup` primitive) + adds the discovery_lineage stamping (using the new `enroll_person` lineage kwarg). The two integrations land together in the same SKILL.md changes.

### D170. Rename `enrolled.source` → `enrolled.source_skill` — append-only ledger backfill via ledger migration 0007

The ledger migration `ledger/0007_backfill_enrolled_source_skill` ships the append-only-ledger-compatible version of the rename per the P3-A finding from Pillar E Week 1's surface audit. Per ADR-0010 D14 the ledger forbids in-place event rewrites. D170's design uses a new event class `enrolled_source_skill_backfill` paired with each historical `enrolled` event.

**The forward emission shape (post-Week-9-11).** `enrollment.py::enroll_person` emits the `enrolled` event with BOTH `source` (back-compat) AND `source_skill` (canonical) fields:

```python
event_payload = {
    "type": "enrolled",
    "person_id": person_id,
    "note_path": str(target),
    "candidate_name": name,
    "identity_keys": keys.to_serializable(),
    # Legacy source attribution (back-compat — pre-Week-9-11 consumers
    # read this field; post-Week-9-11 consumers prefer source_skill).
    "source": source_skill_or_legacy,
    "source_list": source_list,
    # Canonical source attribution (per ADR-0036 D170 — the renamed field).
    "source_skill": source_skill_or_legacy,
    # Lineage sub-fields (per ADR-0036 D170 — denormalized from the
    # Person frontmatter's identity_keys.discovery_lineage sub-block).
    "scraped_at": scraped_at_or_none,
    "raw_input_hash": raw_input_hash_or_none,
    # Existing fields preserved.
    ...
}
```

The `source` + `source_skill` fields carry the SAME normalized value (via `discovery_lineage.normalize_legacy_source_to_skill`). For NEW enrollments with the lineage kwarg, the value is the canonical enum (e.g., `"find-funded-founders"`); for back-compat enrollments without the lineage kwarg, the value is the legacy `source_channel` field's value (e.g., `"funded-founders"`) — the normalization helper maps it to canonical for `source_skill` while preserving the legacy spelling for `source` (so existing tests asserting on `event["source"] == "funded-founders"` continue to pass).

Wait — actually, the cleaner shape: BOTH `source` and `source_skill` carry the CANONICAL value (the normalization happens at emit time). Pre-Week-9-11 tests asserting `event["source"] == "find-funded-founders"` continue to pass because the existing tests already use the canonical form per the existing convention in `tests/test_enrollment.py:378` (`assert enrolled["source"] == "find-funded-founders"`); tests asserting `event["source"] == "funded-founders"` (legacy spelling) — none exist per a grep across the test suite — would need updating.

**The backfill migration's shape.** `ledger/0007_backfill_enrolled_source_skill` walks every historical `enrolled` event that lacks the `source_skill` field, appends an `enrolled_source_skill_backfill` event per such enrolled event:

```python
{
    "type": "enrolled_source_skill_backfill",
    "person_id": <same as original enrolled event>,
    "source_skill": <normalized via discovery_lineage.normalize_legacy_source_to_skill from original enrolled.source>,
    "_backfill_of_ts": <original enrolled event's ts>,
    "_recovered_by": "migration_0007_backfill_enrolled_source_skill",
    "channel": "none",  # per ADR-0014 D33 channel-on-every-event invariant
}
```

Consumers reading `source_skill` for a Person walk the ledger:
1. Find the latest `enrolled` event for `person_id`.
2. If `event["source_skill"]` is present (post-Week-9-11), use it.
3. Else look for an `enrolled_source_skill_backfill` event with `_backfill_of_ts == event["ts"]` (the migration's backfill emission). If present, use its `source_skill`.
4. Else inline-normalize `event["source"]` via `discovery_lineage.normalize_legacy_source_to_skill`.

The closed-set audit treatment for the new event class: every existing closed-set predicate (`_STAGE_BY_EVENT_TYPE`, `REPLY_EVENT_TYPES`, `_INTENT_TYPES + _OUTCOME_TYPES`, etc.) rejects the new event type (per the verdict in D171). The cross-pillar audit's Week 9-11 section walks every consumer + names the verdict.

**Why NOT in-place rewrite of the historical `enrolled.source` field.** Per ADR-0010 D14 the ledger forbids in-place rewrites; the discipline is load-bearing per the synthetic-replay vehicle per ADR-0013. An in-place rewrite would (i) violate the append-only invariant; (ii) require the migration framework to gain "rewrite" semantics it does not have; (iii) couple the migration to per-file-format knowledge of the JSONL files (currently the migration framework operates at the per-event-append level).

**Why NOT a duplicate `enrolled` event for each historical event.** Doubles the enrollment count for affected Persons — breaks any consumer counting enrollments (e.g., `backfill_ledger.py:393` walks `enrolled` events; the funnel CLI's enrollment-count metric; future Pillar G dashboards). The new event class avoids the double-count.

**Why NOT inline-normalize at every consumer.** Every future consumer would need to know about the legacy `enrolled.source` field + the normalization map. The migration's role is to make `source_skill` directly readable from a ledger event — consumers post-Week-9-11 read `enrolled.source_skill` directly (no normalization needed for new events) or `enrolled_source_skill_backfill.source_skill` (no normalization needed for historical events). The legacy inline-normalization is the fallback path for any consumer that walks pre-Week-9-11 events directly (e.g., the funnel CLI's pre-Week-9-11-date range) — but the migration ensures EVERY historical event has a backfill event pair, so the fallback is operator-correctable via the apply.

**Symmetric stamping on enrollment-adjacent events.** The Pillar E Week 1 P2-A pattern (per `.planning/REVIEW-pillar-e-surface-audit.md` §3) ships the `source` field on `enrolled` + `enrollment_skipped_exists` + `enrollment_conflict` + `needs_identity_upgrade`. D170 extends the symmetry — the `source_skill` field stamps on all four events. The `scraped_at` + `raw_input_hash` lineage sub-fields stamp on `enrolled` only (they identify the discovery event, not the post-discovery enrollment outcome).

**Migration `is_reversible=False`.** Per the append-only ledger discipline (analog of ledger/0001 + ledger/0002). The migration's audit-trail event records the schema bump per ADR-0010 D17.

### D171. Cross-pillar audit row extension — `.planning/REVIEW-pillar-e-surface-audit.md` §40+

Per ADR-0032 D146 + ADR-0033 D153 + ADR-0034 D158 + ADR-0035 D165 conventions, the Week 9-11 commit extends the cross-pillar surface audit with a new section walking the three new surfaces' consumer paths.

**The three new surfaces:**

1. **`identity_keys.discovery_lineage:` Person frontmatter sub-block** — new structural field inside an existing block. Consumers:
   * `identity.py::find_matches` + `identity.py::resolve_strict` — reads `identity_keys.linkedin / emails / github / twitter / alt_names`; does NOT read `discovery_lineage`. **Verdict: by-design ignore — closed-set-protected.**
   * `enrollment.py::_serialize_keys_block` — extended in D169 to include `discovery_lineage` when the `lineage` kwarg is provided. **Verdict: by-design extension — by-design-broadening.**
   * `tier_assignment.py::compute_tier_from_signals` — reads `discovery_lineage.source_skill` per ADR-0035 D162; the post-Week-9-11 path reads the canonical field; the legacy `source_channel` fallback stays in place per operator-comfort. **Verdict: by-design extension — by-design-broadening.**
   * Future Pillar G dashboards (forward-reference) — aggregate by `discovery_lineage.source_skill` (per D148 the privacy invariant: NEVER by `source_list`). **Verdict: by-design extension — future-broadening; D148 invariant enforced via the funnel CLI test pin.**
   * Pass C heal (reconcile.py) — heals `pipeline_stage:` + `conversation_status:`; does NOT touch `identity_keys`. **Verdict: by-design ignore — closed-set-protected.**

2. **`enrolled.source_skill` ledger event field** — new field on an existing event class. Consumers walking `enrolled` events:
   * `backfill_ledger.py:393` (`if any(e.get("type") == "enrolled" for e in events)`) — filters on type; doesn't read sub-fields. **Verdict: type-only filter — closed-set-protected.**
   * `backfill_ledger.py:495` (`if any(e.get("type") == "enrolled" for e in events)`) — same. **Verdict: type-only filter — closed-set-protected.**
   * `backfill_ledger.py:340` (the backfill emit path) — emits enrolled events with `source` field; post-Week-9-11 the emit shape SHOULD also include `source_skill` for symmetric stamping. **Verdict: emit-side extension — by-design-broadening.**
   * `funnel.py` (forward-reference for future Pillar G `--breakdown source_skill` extension per D148) — reads the field if Pillar G ships the breakdown. **Verdict: future-by-design — D148 invariant covers.**
   * `tests/test_enrollment.py:378` (`assert enrolled["source"] == "find-funded-founders"`) — asserts on `source`; post-Week-9-11 the new tests assert on `source_skill`. **Verdict: test-side extension — existing tests preserved.**

3. **`enrolled_source_skill_backfill` ledger event class** — entirely new event type. Consumers (closed-set predicates):
   * `_STAGE_BY_EVENT_TYPE` (ledger.py:137 — `"enrolled": "queued"`) — closed dispatch table; the new event type is absent → **closed-set-protected, by-design**.
   * `derived_stage` — same dispatch table → **closed-set-protected**.
   * `reachable_pipeline_stages` — same dispatch table → **closed-set-protected**.
   * `derived_conversation_status` — filters on REPLY_EVENT_TYPES + suppression + state-change events; new type absent → **closed-set-protected**.
   * `derived_conversation_outcome` — `type == "conversation_outcome"` filter; new type absent → **closed-set-protected**.
   * `CrossChannelTouchRule.evaluate` — `endswith("_confirmed")` predicate; new type doesn't match → **literal-string-filtered, by-design**.
   * `BudgetWindowCapRule.evaluate` — `type == "cost_incurred"` filter; new type doesn't match → **literal-string-filtered**.
   * `CooldownRule._confirmed_send_intent_pairs` — `type in {"send_intent", "send_confirmed"}`; new type absent → **literal-string-filtered**.
   * `DomainThrottleRule.evaluate` — `type != "send_confirmed"`; new type doesn't match → **literal-string-filtered**.
   * `Ledger.last_send_for` — `_INTENT_TYPES + _OUTCOME_TYPES`; new type absent → **closed-set-protected**.
   * Pass G's reply classifier idempotence index — `REPLY_EVENT_TYPES` filter; new type absent → **closed-set-protected**.
   * Pass M's auto-unsubscribe — `category=unsubscribe` filter on `reply_classified` events; new type absent → **closed-set-protected**.
   * Pass N's conversation state machine — reply + classified + suppression + state-change events filter; new type absent → **closed-set-protected**.
   * Pass O's conversation outcome — `*_confirmed` filter; new type absent → **closed-set-protected**.
   * Pillar D funnel CLI (`orchestrator/funnel.py::build_report`) — `reply_classified` + `conversation_outcome` filter; new type absent → **closed-set-protected**.
   * Pillar A/B/C/D/E (Weeks 1-8) consumers from the Weeks 1-8 audit — all closed-set-protected or literal-string-filtered by the same shape.

**Verdict for Week 9-11's audit extension:** Zero new P1 latent-bug patterns introduced by Week 9-11's three new surfaces. The new identity_keys sub-block is ignored by the resolver + read by-design by the tier primitive + future dashboards; the new `source_skill` field is by-design-broadening on the existing enrolled event class; the new `enrolled_source_skill_backfill` event class is rejected by every closed-set predicate.

**One P2 candidate flagged for per-week reviewer follow-up:** the per-skill integration uniformity. Four discovery skills + four enrollment templates; if any skill's template diverges from the canonical shape, the cross-skill coherence test surfaces the divergence at Week 12 exit-criterion verification. The Week 9-11 per-week reviewer must verify all four skills' SKILL.md files carry the identical `discovery_lineage:` block + the identical CLI flag set on the `python enrollment.py enroll` invocation.

**Pin:** `.planning/REVIEW-pillar-e-surface-audit.md` extended in this commit with the Week 9-11 section. Future Pillar E weeks (12) consult the audit + extend it per the per-week-review-with-follow-up-commit discipline (Pillar A + B + C + D + E pattern).

## Alternatives considered

### D166-Alt1: Place the lineage primitive inside `orchestrator/enrollment.py`

A new `DiscoveryLineage` class + `build_discovery_lineage_dict` factory inside the enrollment module. **Rejected** because:

* Conflates lineage-as-provenance with enrollment-as-creation. The lineage primitive's job is to DEFINE the schema + VALIDATE the values + PROVIDE the factories; the write-side consumption inside `enrollment.py` is one CALLER of the lineage primitive, not the owner.
* Tempts a future contributor to inline-validate at every call site (the operator-private fields' validation must be centralized).
* Couples the read-side consumers (tier primitive + future Pillar G dashboards) to the write-side module — they would have to import `enrollment.py` just to parse the lineage block (circular import risk).
* The sibling-of-existing-primitives precedent (every Pillar E primitive's own module) is the right grain.

### D166-Alt2: Place the lineage primitive inside `orchestrator/identity.py`

Co-locate with the strict-policy resolver. **Rejected** because:

* The resolver does NOT consult the lineage at all — only the strong-key sub-fields (`linkedin` / `emails` / `github` / `twitter`).
* Putting the lineage primitive inside `identity.py` would suggest the resolver consults it (it doesn't) — operator-confusing API surface.
* Bloats `identity.py` past its single-purpose contract (key resolution).

### D166-Alt3: Place the lineage primitive inside `orchestrator/discovery_dedup.py`

Where the `SOURCE_SKILLS` enum was reserved (Week 2). **Rejected** because:

* The dedup primitive is one CONSUMER of the lineage's `source_skill` field, not the owner of the lineage primitive.
* The Week 2 ADR-0033's authoring note explicitly reserved the enum at `discovery_dedup.py:96` with the canonical home moving to `orchestrator/discovery_lineage.py` in a future Pillar E week. Week 9-11 IS that future week.
* The lineage primitive is structurally broader than dedup — it also serves the tier primitive + future Pillar G dashboards + future Pillar I CLIs.

### D166-Alt4: Spin up an `orchestrator/discovery/` subpackage

Gather dedup + lineage + tier under one namespace. **Rejected** because:

* Over-organization for Week 9-11's scope. The single-file convention used by every other Pillar E primitive is the precedent.
* Would require coordinated import-path migration across the prior three Pillar E primitives — the cost is higher than the structural benefit.
* The subpackage rationale resurfaces in a future Pillar I OSS bring-up week IF the discovery surface grows to 4+ modules (e.g., per-tenant lineage namespace).

### D167-Alt1: Plain dict (no `DiscoveryLineage` dataclass)

Treat the lineage as a free dict + validate at the call site. **Rejected** because:

* Skips construction-time validation — the closed-enum + sha256-prefix invariants exist ONLY at the validation site; a dict-shaped lineage pushes validation to every call site, inviting drift.
* Prior Pillar B Week 6 P2 incidents (`_vault_io.is_note_type`'s consolidation) are the precedent for centralizing repeated validation — Week 9-11 avoids repeating the lesson.
* Frozen dataclass is the Pillar E primitive convention (every emit-shape class is one).

### D167-Alt2: Pydantic model

Use `pydantic.BaseModel` for stronger validation + JSON-schema export. **Rejected** because:

* `pydantic` is not in the framework's dependency manifest; introducing it for one class would force every consumer to import + every test environment to install.
* The frozen-dataclass shape covers the validation needs at Pillar E's scope; pydantic's incremental value (JSON-schema export, ORM-style validators) is not load-bearing at Week 9-11.

### D167-Alt3: TypedDict

Use `typing.TypedDict` for type-checking at the cost of runtime validation. **Rejected** because:

* TypedDict provides no runtime validation (type-checking only at static-analysis time); the operator-private fields' construction-time enforcement is the load-bearing invariant.
* Construction-time refusal of unknown `source_skill` values is the D142 contract; a future skill author who omits the enum extension fails loudly at construction time, not silently at consumer time.

### D167-Alt4: Keep `SOURCE_SKILLS` in `discovery_dedup.py`

Leave the Week 2 reservation in place; the lineage primitive re-exports from the dedup module. **Rejected** because:

* The enum's natural home is next to the lineage primitive (which owns the schema). Re-exporting from a consumer module collapses the four-step substrate decoupling D166 preserves.
* The Week 2 ADR-0033's authoring note explicitly committed to the canonical-home move in a future Pillar E week.

### D168-Alt1: YAML round-trip for the migration's per-Person rewrite

`yaml.safe_dump` the whole frontmatter dict with the extended `identity_keys` block. **Rejected** because:

* Destroys comments (operators hand-curate frontmatter comments — a YAML round-trip strips them all).
* Reorders fields (operators' hand-curated YAML order is operator-visible — a YAML round-trip's default ordering is alphabetical, not declaration-order).
* The Pillar B Week 6 second follow-up's `add_frontmatter_block_text` precedent picks surgical edits over YAML round-trip for the same reasons.

### D168-Alt2: Skip the vault migration; rely on per-skill stamping going forward

Backfill is operator-deferred — operators run a Pillar I CLI to backfill manually. **Rejected** because:

* The legacy Person notes (the operator's existing ~500 Persons) are the bulk of the corpus; without backfill, the canonical `discovery_lineage:` field is absent on the majority of the operator's vault.
* The `TestDiscoveryLineage::test_every_new_enrollment_carries_canonical_discovery_lineage` coherence test pins the NEW enrollment shape, but legacy Person notes lacking the block create a permanent split (some Persons have the block; some don't) — the migration normalizes the corpus at Week 9-11.
* The §Existing-operator seed convention from prior Pillar E weeks requires a one-time backfill step; D168 ships it.

### D168-Alt3: Backfill from ledger only (no `_source.md` parsing)

Use the ledger's `enrolled.source` field as the only backfill source. **Rejected** because:

* The ledger's `source` field uses legacy shortened naming (`"funded-founders"` not `"find-funded-founders"`) and lacks the `source_list` + `scraped_at` + `raw_input_hash` fields entirely; the migration would have to synthesize three of the four required fields from defaults.
* The `_source.md` files (when present) carry richer provenance — the operator's curated list metadata captures the original scrape URL + the scrape timestamp + the list filename. Falling back to the ledger discards this richer signal.
* The cascade (a) → (b) → (c) → (d) is the operator-trustworthiness-ordered approach; ledger-only is one fallback within the cascade.

### D168-Alt4: Backfill from `_source.md` only (no `source_channel` fallback)

Refuse to backfill Persons whose vault lacks `_source.md` files. **Rejected** because:

* Many operators (Yang included) do not maintain `_source.md` files — the operator's vault may have rich `source_channel:` frontmatter without the corresponding `_source.md`.
* Refusing to backfill Persons without `_source.md` would leave the canonical `discovery_lineage:` field absent on 60-90% of the corpus (per the per-source coverage table); the cascade's medium-confidence fallbacks (b) + (c) cover the bulk.
* The fall-back-to-manual floor (d) handles the residual; the operator-readable stderr summary surfaces the count for post-apply audit.

### D169-Alt1: Staggered per-week per-skill stamping

Week 9 ships find-leads; Week 10 ships find-funded-founders + competitor-customers; Week 11 ships research-prospect. **Rejected** because:

* The staggered trajectory was right for the dedup primitive (Week 2 + Week 3) because the per-skill integration added a NEW pre-enrichment phase (a new SKILL.md sub-phase + new bucket types). The lineage stamping is structurally simpler — one frontmatter sub-block addition + four new CLI flags.
* The staggered split would inflate the commit count without proportional risk reduction.
* Single-commit four-skill stamping lands the canonical block uniformly; an operator running any discovery skill post-Week-9-11 gets the canonical block stamped.

### D169-Alt2: Defer per-skill stamping to Pillar I

Rely on the vault migration's backfill alone for legacy Persons + leave NEW enrollments un-stamped at Pillar E. **Rejected** because:

* Defeats D142's "every NEW Person enrollment carries the canonical block" invariant.
* The `TestDiscoveryLineage::test_every_new_enrollment_carries_canonical_discovery_lineage` coherence test requires per-skill stamping at Week 9-11.
* Leaving the canonical block absent on NEW enrollments while backfilling on LEGACY ones creates a split (legacy Persons have the block via migration; NEW Persons lack the block) — the inverse of the desired shape.

### D169-Alt3: Auto-derive `source_skill` from the calling skill's name via a sniffing hook

Replace the explicit `--source-skill` flag with auto-detection from `sys.argv[0]` or environment variables. **Rejected** because:

* Magic auto-detection is fragile — a future skill author wrapping `enrollment.py` from a non-skill context (a Pillar I CLI helper; a debug script) would silently mis-stamp.
* The explicit-flag shape forces the discovery skill's intent to surface in the operator-visible CLI invocation (the SKILL.md's `python enrollment.py enroll --source-skill find-leads ...` is operator-readable).
* The closed-enum + construction-time validation catches the typo case loudly; auto-detection would silently mis-stamp.

### D169-Alt4: Bundle the lineage flags into a single `--lineage <json>` flag

`python enrollment.py enroll --lineage '{"source_skill": "find-leads", "source_list": "...", ...}'`. **Rejected** because:

* JSON-in-a-bash-arg is fragile (quoting + escaping + shell-interpolation hazards).
* Four explicit flags are more operator-readable + match the established `enroll_person` kwargs convention.
* The flags' defaults (`--scraped-at` defaults to now-UTC; `--raw-input-hash` defaults to deterministic per-input fingerprint) work naturally with per-flag defaulting; a JSON shape would require either always-pass-all-fields or a deeper merging shape.

### D170-Alt1: In-place rewrite of historical `enrolled.source` field

Edit the JSONL files directly — replace `"source":` with `"source_skill":` in every historical event. **Rejected** because:

* Violates the append-only ledger invariant per ADR-0010 D14 (load-bearing for the synthetic-replay vehicle per ADR-0013).
* Requires the migration framework to gain "rewrite" semantics it does not have.
* Couples the migration to per-file-format knowledge of the JSONL files (currently the migration framework operates at the per-event-append level).

### D170-Alt2: Append a duplicate `enrolled` event for each historical event

The migration appends a NEW `enrolled` event with the canonical `source_skill` field. **Rejected** because:

* Doubles the enrollment count for affected Persons — breaks any consumer counting enrollments (`backfill_ledger.py:393`; the funnel CLI's enrollment-count metric; future Pillar G dashboards).
* Pollutes the audit trail with synthetic-but-indistinguishable events.

### D170-Alt3: Skip the ledger migration; inline-normalize at every consumer

Every consumer reading `source_skill` walks the legacy `source` field + applies `normalize_legacy_source_to_skill` inline. **Rejected** because:

* Every future consumer needs to know about the legacy `enrolled.source` field + the normalization map.
* The migration's role is to make `source_skill` directly readable from a ledger event — eliminating the inline-normalization burden.
* The new event class shape (D170's choice) lets consumers walk a single field name (`source_skill`) on either the original event or the backfill event.

### D170-Alt4: Use `enrolled_v2` event class for the rename

Rename the entire event class rather than adding a field. **Rejected** because:

* The `enrolled` event class carries far more than the renamed field — `person_id`, `note_path`, `candidate_name`, `identity_keys`, `source_list`, etc. Renaming the class would require every consumer to add `or enrolled_v2` to every `type == "enrolled"` filter.
* The additive `source_skill` field is the minimum-disruption shape; the new event class shape is reserved for the backfill case (D170's choice).

### D171-Alt1: Spawn a code-reviewer agent for the audit extension

Delegate the per-consumer walk to a sub-agent. **Rejected** because:

* The per-week-reviewer discipline (Pillar A + B + C + D + E pattern) handles this — Week 9-11's per-week reviewer surfaces the audit extension as part of the standard review pass.
* The cross-pillar audit is a load-bearing artifact; the inline-in-ADR approach plus the audit document extension are both first-class artifacts.

### D171-Alt2: Skip the audit extension; rely on per-week reviews to catch broadening surfaces

Leave the audit document at Week 6-8's state; the per-week reviewer surfaces any new latent-bug pattern. **Rejected** because:

* The audit is the LOAD-BEARING anti-regression surface map per ADR-0032 D146 + ADR-0033 D153 + ADR-0034 D158 + ADR-0035 D165. Skipping the extension would create a permanent gap (a future Pillar E or Pillar F week's audit would have to retroactively cover Week 9-11's surfaces).
* The per-week reviewer's role is to verify the audit extension is correct, not to write it from scratch.

### D171-Alt3: Defer the audit extension to a Week 9-11 follow-up commit

Ship the primitive in the main commit; the audit extension comes later. **Rejected** because:

* The atomicity contract per Pillar E's discipline is "primitive + audit + ADR + tests + handoff land together."
* Splitting the audit into a follow-up commit would let a P1 latent-bug pattern slip through if the follow-up is delayed.

## Consequences

### Positive consequences

* **`identity_keys.discovery_lineage:` sub-block is canonical.** Every NEW Person enrollment from any of the four discovery skills carries the four required fields (D142's invariant from Week 1 is now enforced at the per-skill stamping site).
* **`SOURCE_SKILLS` enum has a canonical home.** The Week 2 reservation in `discovery_dedup.py:96` is resolved — the enum lives in `discovery_lineage.py` with construction-time validation via `DiscoveryLineage.__post_init__`. Future skill authors extending the enum coordinate with one ADR amendment.
* **Tier primitive's signal source is canonical.** The Week 6-8 tier primitive's `discovery_lineage.source_skill` read path is now backed by an actually-stamped field (vs the legacy `source_channel` fallback); the tier suggestions become more reliable post-Week-9-11 as the corpus migrates.
* **Provenance audit is operator-readable.** The `raw_input_hash` field surfaces the operator's scrape provenance — an operator suspecting a lead list was poisoned (R018) can grep `enrolled.discovery_lineage.raw_input_hash == <suspect_hash>` to identify every affected Person.
* **The cross-pillar audit's coverage stays comprehensive.** Week 9-11's three new surfaces are each verdicted per consumer — every Pillar A/B/C/D/E (Weeks 1-8) surface is re-audited against the new shapes. Zero new P1 latent-bug patterns introduced.
* **The legacy `source_channel` fallback paths stay in place for operator-comfort.** The tier primitive's fallback (per ADR-0035 D162) + the enrollment.py's fm_in.get fallback continue to work — operators with pre-Week-9-11 Person notes (those not yet migrated) continue to enroll + retier without disruption.
* **Symmetric stamping closes the Week 1 P2-A pattern.** The four enrollment-adjacent event classes (`enrolled` + `enrollment_skipped_exists` + `enrollment_conflict` + `needs_identity_upgrade`) all carry the new `source_skill` field per the same precedent that closed the original P2-A finding on `needs_identity_upgrade`.

### Negative consequences

* **Test count grows by ~70+ unit tests + 4 un-skipped coherence rows.** The lineage primitive's invariants + the vault migration's backfill paths + the ledger migration's append-only-backfill shape + the per-skill integration smoke tests + the un-skipped coherence rows all need explicit coverage. The growth is bounded (~70 tests vs Week 6-8's 53 + Week 4-5's 50 — proportional to the work).
* **Pending migration count rises from 17 to 19.** Two new migrations (vault/0005 + ledger/0007) land. Operators apply via the existing `python -m orchestrator.migrations doctor apply` path; the per-migration Obsidian-Sync warning surfaces per the existing convention. **Note on numbering:** the next ledger migration is `0007` (not `0006`) because the existing ledger migration sequence ships through `0006_baseline_calendar_booking_history`; `0007` is the next sequential slot.
* **`SOURCE_SKILLS` import-path change in `discovery_dedup.py`.** The local copy at `discovery_dedup.py:96` is removed + replaced with an import from `discovery_lineage.py`. Any test referencing the dedup module's `SOURCE_SKILLS` continues to work via Python's re-export semantics (the dedup module imports the name → the name is accessible via the dedup module's namespace); no test breakage expected.
* **`_vault_io.py` gains two new helpers (`extend_frontmatter_nested_block_text` + `remove_frontmatter_nested_field_text`).** The module's surface grows by ~120 LOC + corresponding tests. The new helpers are Pillar E Week 9-11-specific; future Pillar E weeks (or Pillar I OSS bring-up) MAY consume them for further nested-block extensions.
* **Risk register adds R022 (discovery_lineage backfill heuristic precision).** The per-week reviewer's category §3 carries the mitigation forward; future Pillar I doctor preflight MAY extend the backfill-confidence reporting.
* **Operator one-time migration burden.** Operators apply the two new migrations via `python -m orchestrator.migrations doctor apply` — the vault migration touches every Person note (Obsidian Sync warning applies); the ledger migration walks every `events-*.jsonl` file. For Yang's ~500-Person corpus, the apply runs in <10 seconds total.

### Risks

The asymmetric-failure-cost calculus (PILLAR-PLAN §0) carries:

* **Stamping failure (P1):** the `enroll_person` kwarg path silently skips the lineage stamping on a NEW enrollment. **Bounded by** the un-skipped `TestDiscoveryLineage::test_every_new_enrollment_carries_canonical_discovery_lineage` test failing loud at CI; the operator-readable stderr at enrollment time naming the absent kwarg.
* **Backfill mis-attribution (P2):** the vault migration mis-attributes a Person's `source_skill` (e.g., maps a legacy `source_channel: "competitor-customers"` to `source_skill: "find-leads"`). **Bounded by** the normalization map's coverage of every legacy value + the per-source backfill count logged at apply time; operators can correct any mis-attribution via the per-Person CLI override.
* **Legacy `SOURCE_SKILLS` import drift (P3):** a future contributor adds a new skill to `discovery_dedup.py`'s local re-export but not to `discovery_lineage.py`'s canonical home. **Bounded by** the single-source-of-truth import discipline post-Week-9-11 — `discovery_dedup.py` imports from `discovery_lineage.py`; future skill author edits ONE module.
* **Ledger backfill incompleteness (P2):** the ledger migration walks every `events-*.jsonl` file but misses a per-Person edge case (e.g., a Person whose `enrolled` event was emitted by `backfill_ledger.py` rather than `enrollment.py` — the field shape MAY differ). **Bounded by** the test coverage of every emit-site for `enrolled` events; the migration's per-event count logged at apply time + the operator-visible stderr if any emit-site shape mismatches.

The framework's existing safeguards bound the false-merge / false-attribution failure modes by design.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The ledger remains append-only; the rename per D170 is implemented via a new event class (`enrolled_source_skill_backfill`) appended per historical `enrolled` event lacking `source_skill`. No in-place rewrites.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The lineage primitive does not change send-path semantics — it operates at the discovery + enrollment phase, upstream of the dispatcher's two-phase commit.
* **I3 — Atomic per-Person enrollment.** Preserved. The lineage stamping is part of the enrollment transaction (the Person note write + the `enrolled` event emit + the lineage stamping all happen inside `enroll_person`'s atomic boundary).
* **I4 — Per-channel state isolation.** Preserved. The lineage primitive is channel-agnostic (mirrors the dedup primitive per ADR-0033 + the tier primitive per ADR-0035). The new event class carries `channel: "none"` per the channel-on-every-event invariant.
* **I5 — Migration framework discipline.** Preserved. The two new migrations (vault/0005 + ledger/0007) ship via the existing `MigrationRunner` substrate per ADR-0009. The vault migration is reversible per ADR-0011 D11; the ledger migration is irreversible per the append-only ledger discipline (analog of ledger/0001 + ledger/0002).
* **I6 — Channel-on-every-event invariant.** Preserved. The new `enrolled_source_skill_backfill` event class carries `channel: "none"` per ADR-0014 D33. The extended `enrolled` event continues to carry the existing channel context (typically absent — `enrolled` is itself channel-agnostic; the channel-on-every-event invariant applies to send-path events per ADR-0014 D33's scope).
* **I7 — Refuse-loud on operator misconfiguration.** Preserved. The `DiscoveryLineage.__post_init__` refuses unknown `source_skill` values + malformed timestamps + malformed sha256 hashes. The vault migration logs the per-source backfill count + the fall-back-to-manual count for operator audit. The ledger migration emits the standard `migration_event` audit-trail event per ADR-0010 D17.
* **I8 — Privacy-respecting (`source_list` operator-private).** Preserved. The Layer 1 defense per ADR-0032 D148 (the `test_source_list_is_operator_private` test corpus pin) continues to hold — the funnel CLI's `--breakdown` dimensions do not include `source_list`. Future Pillar G dashboards filter on `source_skill` (operator-deliberate aggregation level) but NEVER on `source_list`.

## Downstream pillar impact

* **Pillar F (multi-source enrichment expansion).** Future Pillar F enrichment-skill authors stamp the canonical `discovery_lineage:` block at their own enrollment sites via the established `lineage` kwarg shape. The closed-enum extension (a new `source_skill` value) requires one ADR amendment + one `SOURCE_SKILLS` extension in `discovery_lineage.py`.
* **Pillar G (observability).** The Pillar G funnel CLI extension `--breakdown source_skill` is operator-deliberate (per D148 the privacy invariant — `source_skill` is operator-friendly aggregation; `source_list` is operator-private). The post-Week-9-11 ledger carries `source_skill` directly on every `enrolled` event (vs the pre-Week-9-11 inline normalization burden). Pillar G dashboards reading the field can short-circuit the legacy normalization.
* **Pillar H (real-time + scale).** The lineage primitive is read-only at the dispatcher's hot path (the dispatcher reads `discovery_lineage.source_skill` for per-skill rate-limiting per a future Pillar H surface — TBD). The frozen-dataclass shape + the construction-time validation keep the per-call cost bounded.
* **Pillar I (multi-tenant + OSS hardening).** Pillar I's CLI surface ships `python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>` for per-Person operator correction of any vault migration's mis-attribution. Pillar I's doctor preflight extension verifies the `SOURCE_SKILLS` enum is in sync between `discovery_lineage.py` (canonical) + `discovery_dedup.py` (import). Per-tenant lineage namespace is a Pillar I forward-reference.
* **Pillar J (compliance + audit).** GDPR-purge transaction extends to purge the `discovery_lineage.raw_input_hash` field from a Person's identity_keys block when the Person requests forget (the hash is derived from the operator's scrape input; if the scrape included PII, the hash IS PII per a strict reading). The cross-pillar audit's GDPR row covers this in a future Pillar J week.

## Migration / rollout

**Week 9-11 ships TWO new migrations:**

1. **`vault/0005_add_discovery_lineage_to_identity_keys`** — adds the `identity_keys.discovery_lineage:` sub-block to every pre-Week-9-11 Person note with an existing `identity_keys:` block. Idempotent + reversible + per-file atomic via tmp-then-rename. Backfill cascade per D168: `_source.md` → `source_channel:` → ledger `enrolled.source` → `source_skill: manual`. Operator-readable stderr summary at apply time.

2. **`ledger/0007_backfill_enrolled_source_skill`** — appends `enrolled_source_skill_backfill` events for every historical `enrolled` event lacking `source_skill`. Idempotent (re-running emits only for events without an existing backfill event) + irreversible per the append-only ledger discipline. Operator-readable summary at apply time naming the count of backfill events emitted.

**Rollout step ordering:**

1. **Operator updates the framework** to Week 9-11's commit (the standard `git pull` + `pip install -e .` if applicable).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — applies vault/0005 + ledger/0007 in the framework's standard order (vault before ledger per ADR-0013 D27).
3. **Operator reviews the vault migration's stderr summary** — verifies the per-source backfill counts + the fall-back-to-manual count. For any Person mis-attributed, the operator runs `python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>` per-Person.
4. **Operator runs discovery skills as usual** — every NEW enrollment from find-leads / find-funded-founders / competitor-customers / research-prospect carries the canonical `discovery_lineage:` block. The tier primitive's signal source is now canonical.

**Per ADR-0028 D119 + the Obsidian-Sync warning convention:** the vault migration's apply prints the standard warning at start ("quit Obsidian before running apply"). The ledger migration is append-only + does not interact with the operator's Obsidian Sync surface.

## Existing-operator seed

Per the §Existing-operator seed convention from ADR-0033 + ADR-0034 + ADR-0035, the per-skill commit's `existing-operator seed` step:

1. **No new factory file ships in Week 9-11.** The lineage primitive's schema lives entirely in `orchestrator/discovery_lineage.py`; the closed-enum + the validation are framework-side, not operator-tunable. (Future Pillar I OSS bring-up MAY ship a `config-template/discovery_lineage.example.yml` for per-tenant lineage namespaces — TBD.)

2. **The two migrations carry the existing-operator-seed action.** Operators run `python -m orchestrator.migrations doctor apply` to backfill the lineage on legacy Person notes + the ledger's historical `enrolled` events.

3. **Per-Person operator correction surface.** The Pillar I CLI's `python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>` allows the operator to correct any per-Person mis-attribution. The vault migration's stderr summary names the count of fall-back-to-manual Persons; operators run the per-Person CLI per-Person.

4. **The four discovery skills' enrollment templates DO change.** Operators running find-leads / find-funded-founders / competitor-customers / research-prospect see the new `--source-skill / --source-list / --scraped-at / --raw-input-hash` flags on the `python enrollment.py enroll` invocation. The SKILL.md files document the new shape; the existing `--frontmatter` path continues to work for back-compat.

## References

- **ADR-0032 (D142 + D146 + D148)** — Pillar E foundation (the canonical discovery_lineage shape + the cross-pillar audit + the privacy invariant).
- **ADR-0033 (D149-D153)** — Pillar E Week 2-3 dedup primitive + per-skill integration discipline (D152 names the research-prospect Week 9-11 deferred slot; D149 establishes the sibling-of-existing-primitives module placement convention).
- **ADR-0034 (D154-D159)** — Pillar E Week 4-5 email verification cache primitive (D156 establishes the content-additive cost-event schema extension pattern).
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier auto-assignment primitive (D162 establishes the legacy `source_channel` fallback path; D163 establishes the YAML-tunable config convention; D165 establishes the cross-pillar audit row extension precedent).
- **ADR-0010 (D14 + D17)** — ledger migration framework (append-only invariant; migration_event audit-trail convention).
- **ADR-0011 (D11)** — vault migration framework (per-file atomic; reversible posture; tmp-then-rename + fsync).
- **ADR-0014 (D33)** — channel-on-every-event invariant (the new `enrolled_source_skill_backfill` event carries `channel: "none"`).
- **ADR-0028 (D119)** — vault/0004 precedent for reversible vault migration with surgical edits + Obsidian Sync warning convention.
- **`.planning/REVIEW-pillar-e-surface-audit.md`** — the load-bearing cross-pillar audit; Week 9-11 extends with §40+.
- **`.planning/HANDOFF-pillar-e-week-9.md`** — this week's handoff document (committed in the Week 6-8 main commit).
- **`docs/PILLAR-PLAN.md` §6 Pillar E row** — the per-week trajectory ticker.
- **`docs/SOURCES-OF-TRUTH.md` Discovery-lineage row** — the SoT registry's pre-declared row (Pillar E formalizes the contract).
- **`docs/RISK-REGISTER.md` R022** — the new risk added in this ADR (discovery_lineage backfill heuristic precision).
