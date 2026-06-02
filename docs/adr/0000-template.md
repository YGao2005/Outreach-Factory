# ADR-NNNN: {Title — short, decision-oriented}

- **Status:** {Proposed | Accepted | Superseded by ADR-NNNN | Deprecated}
- **Date:** {YYYY-MM-DD}
- **Pillar:** {A–J or "cross-cutting"}
- **Deciders:** {who signed off}

## Context

What forces are at play? What constraint, incident, or scale concern made this decision necessary now? Cite specific code paths, prior ADRs, postmortems, or HANDOFF sections. Keep this honest — if the context is "we want to do X because it's cleaner," say so; if it's a load-bearing failure mode from the risk register, cite the row.

## Decision

The decision in one paragraph. Active voice. Concrete enough that a contributor six months from now can tell whether a proposed change conforms or violates it.

## Alternatives considered

Each alternative gets a heading + 1–3 sentences. **Why it was rejected** is the load-bearing part — without it, the ADR collapses into "we picked X because we picked X." If an alternative would have been chosen under different constraints, name the constraint.

### Alternative 1: {name}
Brief description. **Rejected because:** {load-bearing reason}.

### Alternative 2: {name}
Brief description. **Rejected because:** {load-bearing reason}.

## Consequences

### Positive
- {What this enables}

### Negative
- {What this costs us; what becomes harder}

### Neutral / observability
- {What changes in operations, monitoring, support burden}

## Compliance with invariants

Which of I1–I8 (see `docs/PILLAR-PLAN.md` §1) does this decision touch? If it weakens any invariant, **say so explicitly** and link the compensating control or follow-up ADR.

## Migration / rollout

If this changes existing code or data, link the migration in `orchestrator/migrations/` and the synthetic before-state snapshot test. If there's no migration, state why (greenfield, additive, etc.).

## Pre-commit verification

Derive, don't assert. Every claim this ADR makes about code that lives elsewhere — a function signature, a count, a constant's value, another module's behavior — MUST be pasted from a command, not paraphrased from memory. 8 of the 11 ADR-vs-actual-impl drifts caught across Pillars H–I (including all 3 P1s) were assertions a one-line command would have falsified. Paste each command + its output below; a later edit that changes the referenced code makes this block fail review. If this ADR references no external code, write "N/A — additive/greenfield."

| Claim in this ADR | Verification command | Output (pasted) |
|---|---|---|
| {e.g. `reconcile.reconcile` is keyword-only, takes `led: Ledger` + required `since`} | `python -c "import inspect, reconcile; print(inspect.signature(reconcile.reconcile))"` | {paste} |
| {e.g. EVENT_CLASS_CATALOG has N entries} | `python -c "from orchestrator.observability import EVENT_CLASS_CATALOG as c; print(len(c))"` | {paste} |

## References

- Linked HANDOFF / postmortem / risk-register row
- Related ADRs (predecessors, alternatives discussed elsewhere)
- Code locations where this decision is enforced
