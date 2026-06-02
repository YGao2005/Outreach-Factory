# ADR-0070: Pillar I foundation — multi-tenant + OSS hardening primitive shape, Docker container runtime decision, cross-pillar integration audit, exit-criterion vehicle scope, per-tenant load-bearing invariants, per-week trajectory

- **Status:** Accepted
- **Date:** 2026-05-28
- **Pillar:** I (Multi-tenant + OSS hardening — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001-0008 shipped Pillar A (declarative policy engine). ADRs 0009-0013 shipped Pillar B (migration framework + synthetic-replay exit-criterion vehicle). ADRs 0014-0024 shipped Pillar C (multi-channel coherence — four channels, six reconcile passes, five per-channel policy migrations). ADRs 0025-0031 shipped Pillar D (reply + conversation handling — rule + LLM classifier, auto-unsubscribe, conversation state machine, win/loss attribution, funnel CLI). ADRs 0032-0037 shipped Pillar E (discovery quality + lineage — dedup + email-verification cache + tier auto-assignment + discovery_lineage stamping + three-skills-one-day binding exit-criterion). ADRs 0038-0049 shipped Pillar F (voice corpus + draft quality — voice-corpus schema + canonical location, embedding-retrieval primitive, per-register adapters, threshold loader + CLI, FIVE-layer hallucination-detection defense across Layers 1-5, per-claim-type corpus + measurement, voice-fidelity scoring, fuzzy-match Layer 3 extension, Layer 4 post-engine guard, Layer 3 corpus revision with paraphrased-ready pairs + bound tightening, and Layer 5 reconcile heal-pass refusal closing the FIVE-layer defense + binding 200-draft eval set + Stable flip). ADRs 0050-0059 shipped Pillar G (Observability — per-event-class observability primitive + OTel SDK metrics + Prometheus exporter + Grafana-as-code first dashboard + OTel tracing + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + Grafana per-Person dashboard + funnel CLI extension with three binding-question report sections + Stable flip). ADRs 0060-0069 shipped Pillar H (Daemon + dispatcher — daemon module + per-stage worker pool + per-event-class index + crash-recovery synthesis + operator-deliberate pre-flight reconcile + Grafana per-daemon dashboard with SEVEN panels + Stable flip). **Pillar H is Stable as of 2026-05-28.** Pillar I / J are unblocked from the "H stable" dependency.

Pillar I — Multi-tenant + OSS hardening (`docs/PILLAR-PLAN.md` §2 Pillar I, Weeks 43-48) — extends the substrate at the OSS bring-up + multi-tenant end: every operator's path from `git clone` to a working install must be reproducible (Docker compose for one-command-up; init wizard for new users; vault schema migration framework runs at every launch); the framework must support multi-user mode via per-tenant process isolation + per-tenant vault/OAuth/policy isolation; the first CI surface lands in the repo. The substrate is in place — Pillar A's policy engine + Pillar B's migration framework + Pillar C's per-channel two-phase commit + Pillar D's reconcile loop + Pillar E's discovery primitives + Pillar F's draft-quality + Pillar G's OTel SDK + Prometheus + Grafana + Pillar H's daemon — what Pillar I Week 1 needs is the **convention-setting decisions** the next five weeks build on.

Pillar H's Week 12 retrospective (`.planning/RETRO-pillar-h.md` §"What to do differently in Pillar I") named ELEVEN carry-forward recommendations: (1) adopt the per-week-reviewer pattern's compounded disciplines from Day 1 (Pillar H's TEN consecutive ADR-vs-actual-impl drift catches + THREE P1 escalations is the empirical evidence per the Pillar H Week 12 follow-up P3-1 closure naming the TENTH drift — Pillar I authors carry FIRST-class reviewer attention from Day 1); (2) cross-pillar back-audit at Pillar I Week 1 audits Pillar A-H surfaces (every prior pillar's Week 1 audit caught ≥1 P2); (3) design Pillar I's per-tenant load-bearing invariants at Week 1; (4) the per-tenant-symmetry-with-shared-aggregation pattern at Week 1 (Pillar D's per-channel reply detection + Pillar E's per-skill integration + Pillar F's per-register adapters + Pillar G's framework adoption + Pillar H's daemon all shipped per-pillar fan-outs via shared-helper-with-thin-adapters convention); (5) the per-pillar mirror constants parity pattern continues; (6) the TEST-ONLY embed_fn + retrieve_fn seam preservation pattern generalizes; (7) the READ-ONLY funnel CLI contract per ADR-0059 D325 generalizes; (8) the framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 + the W4 follow-up P2-1 closure generalizes; (9) the closed-set discipline + the privacy invariant generalize; (10) the Pillar H W7 follow-up NEW-2 deferred item (shutdown-during-in-flight-reconcile) is structurally Pillar-I-scope; (11) the Pillar H W8 follow-up P3-6 deferred item (`_data` field naming convention) is structurally Pillar-I-scope.

The six concerns this ADR's design resolves:

1. **Per-tenant primitive shape must be pinned before per-week 2+ adapters ship.** PILLAR-PLAN §2 Pillar I names the multi-tenant deliverable — per-user vault isolation + per-user OAuth tokens + process-per-user with shared install layer — but does not pin the per-tenant API surface. D371 pins `orchestrator/multi_tenant/` package shape: `TenantConfig` (frozen dataclass) + `TenantRegistry` (frozen dataclass) + `TENANT_LIFECYCLE_STATES` closed-set + `TENANT_NEW_EVENT_CLASSES` closed-set + `TENANT_OAUTH_TOKEN_SCOPES` closed-set + `init_multi_tenant` + `resolve_per_tenant_ledger_dir` + `resolve_per_tenant_policy_dir` signatures. The Week 1 commit ships the module shape + signatures; Weeks 2-6 ship the implementation bodies per D376's per-week trajectory table.

2. **Container runtime decision — Docker vs podman vs nomad vs kubernetes.** PILLAR-PLAN §2 Pillar I names "Docker compose for one-command-up; cloud deploy templates (Fly.io / Railway / Render)" — Docker compose is the canonical OSS bring-up shape. The Week 1 commit pins the choice so per-week implementations don't reopen the question. D372 picks **Docker** (containerd-backed; docker-compose for local OSS bring-up; per-tenant container = one daemon process per ADR-0060 D335 invariant 1) as the canonical container runtime. Per the rationale at D372: Docker is the operator-tested choice (Fly.io / Railway / Render all accept Docker images); docker-compose is the canonical OSS one-command-up shape; the per-tenant container model preserves Pillar H's process-isolation invariant per D335 (1); kubernetes is structurally heavier than the v1 OSS bring-up requires; podman + nomad are alternative runtimes operators wire via the framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 + the W4 follow-up P2-1 closure's seam-vs-fork two-tiered distinction.

3. **Cross-pillar surface audit — THE load-bearing anti-regression decision.** Per Pillar A/B/C/D/E/F/G/H Week 1 precedents (every prior pillar's Week 1 audit caught ≥1 pre-existing P2): Pillar A surfaced policy-engine version concerns; Pillar B surfaced `ledger/0002`'s channel-field gap; Pillar C surfaced Pass A's channel-filter gap; Pillar D surfaced Pass B's channel-on-every-event gap; Pillar E surfaced `needs_identity_upgrade`'s source-attribution gap; Pillar F surfaced the all-cited-claims-path vacuity gap in `tests/test_multi_channel_coherence.py::TestHallucinationDetection`; Pillar G surfaced `funnel.py`'s ts-missing posture gap; Pillar H surfaced the cross-pillar daemon-consumer surface gap. Pillar I Week 1's per-week reviewer MUST audit existing Pillar A/B/C/D/E/F/G/H surfaces for symmetric assumptions when Pillar I's commit silently introduces the per-tenant fan-out + the container boundary + the init wizard. D373 pins the audit + names the load-bearing concerns: (a) does Pillar A's policy engine per-tenant policy YAML hot-reload preserve under SIGHUP per Pillar H Week 7's `reload_policy` body? (b) does Pillar B's migration framework's auto-apply contract hold under per-tenant directory schema? (c) does the per-Person lock primitive per Phase 5.5 hold under per-tenant container isolation? (d) does Pillar G's stateless-aggregation contract per R033 hold per-tenant? (e) does Pillar H's daemon's per-stage worker pool preserve per-tenant under one-container-per-tenant? (f) does the init wizard's idempotence contract hold across re-runs per ADR-0009 D9? `.planning/REVIEW-pillar-i-surface-audit.md` is the load-bearing artifact future Pillar I weeks extend.

4. **The Pillar I exit-criterion verification vehicle must exist in Week 1.** Per PILLAR-PLAN §2 Pillar I binding text: *"`git clone && docker compose up && doctor.py` on a fresh VM produces a working system; init wizard takes a new user from zero to a successful test send in < 10 minutes; CI fails any unaccompanied pricing-table change."* Without the vehicle landing in Week 1, the cross-cutting properties (OSS bring-up reproducibility + init wizard idempotence + CI bring-up reliability + per-tenant isolation + per-tenant observability preservation) would only surface end-of-pillar, repeating Pillar B Week 5 + Pillar C Week 12 + Pillar D Week 12 + Pillar E Week 12 + Pillar F Week 12 + Pillar G Week 12 + Pillar H Week 12's pattern. D374 names the vehicle scope: `tests/test_multi_channel_coherence.py` is EXTENDED with `TestPillarIPerTenant` + `TestPillarIPerTenantObservabilityIntegration` + `TestPillarIExitCriterion` test classes (Option A per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183 + ADR-0050 D275 + ADR-0060 D334 single-file rationale inherited). The file currently sits at ~10550 LOC at Pillar H Week 12 follow-up close — TRIPLY past the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266 + the Pillar G Week 12 retrospective + the Pillar H Week 12 retrospective — but the Pillar I Week 1 commit does NOT split (the per-pillar test classes' Week 1 stubs belong adjacent to the per-pillar primitive contracts they verify; the split argument resurfaces if Pillar I's Week 2+ commits add another ~1500 LOC, becoming a Pillar I Week N reviewer's call per the Pillar H Week 12 precedent).

5. **Per-tenant load-bearing invariants.** Per RETRO-pillar-h.md item 3 (continuing Pillar D Week 1's CAN-SPAM precedent per ADR-0025 D97 + Pillar E Week 1's privacy precedent per ADR-0032 D148 + Pillar F Week 1's hallucination-detection FIVE-layer precedent per ADR-0038 D180 + Pillar G Week 1's four invariants per ADR-0050 D276 + Pillar H Week 1's four invariants per ADR-0060 D335) — Pillar I ships its load-bearing invariants at Week 1. D375 names FIVE: (a) **per-tenant-isolation** — each tenant's daemon process is fully isolated; no cross-tenant data leakage at any surface (ledger + vault + Grafana + OAuth tokens); the `resolve_per_tenant_ledger_dir` + `resolve_per_tenant_policy_dir` primitives produce per-tenant directory paths; per-tenant Grafana folders isolate dashboards; (b) **per-tenant atomicity-preservation-across-process-boundary** — extends Pillar H D335 invariant 2 per-tenant; one daemon process per tenant per ADR-0060 D335 invariant 1; per-tenant ledger directories preserve the append-only contract per I2 per-tenant; (c) **init-wizard idempotence** — running the init wizard twice on the same user produces a NO-OP (idempotent per the existing Pillar B migration framework's precedent per ADR-0009 D9); the `init_wizard_completed` event class signals first-run completion; re-runs MAY emit but MUST NOT re-create OAuth tokens or vault directories; (d) **OSS-bring-up reproducibility** — `git clone && docker compose up && doctor.py` on a fresh VM produces a byte-identical-deterministic working system per ADR-0031 D140; the docker-compose container image + the doctor preflight + the init wizard form the canonical OSS bring-up surface; (e) **CI bring-up reliability** — the CI surface fails reliably on any unaccompanied pricing-table change per ADR-0006 §"CI enforcement of the price-update == ADR-amendment discipline" + the Pillar A §D3 deferred check landing at Pillar I Week 5 per the trajectory.

6. **Per-week trajectory table — D376.** The structural commitment Weeks 2-6 satisfy; matches Pillar G Week 1's D273 trajectory shape + Pillar H Week 1's D332 trajectory shape. SIX weeks total (Pillar I budgeted Weeks 43-48 per PILLAR-PLAN §2 Pillar I); each week's deliverable + ADR named at design time so per-week 2+ authors do NOT re-decide scope.

Risks this ADR mitigates by design: **R005 (Gmail API quota exhaustion)** continues mitigated by per-channel rate-limit policies; the per-tenant container model SCALES the quota concern (each tenant runs its own quota window per Gmail's per-account API limits — per-tenant operators avoid cross-tenant quota contention). **R016 (LLM cost runaway)** continues mitigated by Pillar A's budget rules; per-tenant budget rules isolate per-tenant LLM spend. **R023 (hallucination-detection false-negative)** continues mitigated by Pillar F's FIVE-layer defense closed at Layer 5 per ADR-0049 D262; per-tenant containers do NOT modify the Layer 5 backstop. **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — Pillar I per-tenant audit-tooling extends with per-tenant labels per the multi-tenant fan-out trajectory; the cache-substrate divergence concern at multi-tenant scale is structurally addressed by per-tenant ledger isolation (each tenant's daemon walks its own ledger; cross-tenant aggregations live at the Pillar I per-tenant audit-tooling surface). **R037 (Daemon process-restart silent state loss)** — OPERATIONALLY LANDED at Pillar H Week 10-11; Pillar I per-tenant operators get the per-tenant version of the crash-recovery synthesis via `_recover_from_prior_crash` invoked per-tenant.

Three new risks surface in this ADR's authoring + named in `docs/RISK-REGISTER.md`:

- **R040 (Per-tenant ledger directory contention at multi-process write)** — operators running many small tenants on the same machine MAY surface ledger directory contention at the OS-filesystem level (per-tenant directories share a parent directory + per-OS inotify limits + per-OS file-descriptor limits). Severity 2 / likelihood 2 (single-machine multi-tenant operators at v2 scale ~100 tenants per machine would surface the limit; v1 scale ~10 tenants per machine is well within limits). Mitigation by design: D371 pins per-tenant ledger directories at separate filesystem subtrees (`base_ledger_dir / tenant_id`); operators wanting cross-machine fan-out wire one machine per tenant via the cloud deploy templates per D372. Pillar I Week 5 CI surface includes a per-tenant contention regression-barrier; v2-scale operators get a Pillar J trajectory note for per-tenant storage tier optimization.

- **R041 (Docker container daemon-restart cycle inflates startup latency)** — per-tenant Docker containers MAY restart on operator-deliberate config changes (docker-compose down + up); each per-tenant restart pays the Pillar H Week 8 per-event-class index materialization startup cost (~1-2s at v1 scale ~5K events; ~10s at v2 scale ~100K events per tenant). Severity 2 / likelihood 3 (operators iterating per-tenant config see the restart cycle frequently; cumulative startup time at v2 scale MAY exceed 60s for ~10 tenants). Mitigation by design: D372 pins Docker healthcheck + restart-policy at the compose manifest level; the per-tenant daemon's startup `daemon_started` event surfaces the startup time per the operator-visible Pillar H Grafana dashboard. Pillar I Week 3 ships the docker-compose manifest with the operator-tunable healthcheck + restart policy; Pillar I Week 5 CI surface includes a startup-latency regression-barrier.

- **R042 (Init wizard OAuth-flow failure modes operator-confusing)** — the Pillar I init wizard walks operators through Gmail OAuth → LinkedIn OAuth → Twitter OAuth → Google Calendar OAuth → first prospect → first send; each OAuth surface has distinct failure modes (token revocation; scope mismatch; provider rate-limit; network failure). Without per-step refuse-loud + operator-readable error messages, operators MAY hit a failure mode + not know which step to retry. Severity 2 / likelihood 3 (first-time operators are by-definition unfamiliar; OAuth flows are the most error-prone surface in the framework). Mitigation by design: D374 pins per-step refuse-loud + operator-readable error messages at every init wizard surface; the `init_wizard_completed` event class signals successful completion + carries the list of completed step names per `wizard_steps` payload field. Pillar I Week 4 ships the init wizard body with the per-step refuse-loud + the operator-readable error message convention per ADR-0001 D2 + the Pillar H W10-11 follow-up P1-1 closure's discipline (operator-readable error message; NO Python traceback at operator-facing surfaces).

The Pillar G framework adoption surfaces (OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension with three binding-question report sections) preserve verbatim. The Pillar H daemon surfaces preserve verbatim. The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The Pillar D + E + F + G + H binding exit-criterion tests STAY GREEN. The brand-and-legal-liability invariant + the privacy invariant + the FIVE-layer hallucination-detection defense all hold with FULL weight.

## Decision

### D371. `orchestrator/multi_tenant/` package shape — module + dataclasses + closed-sets + signatures

Pillar I ships the `orchestrator/multi_tenant/` package (NEW Week 1; Week 2+ ships the bodies). The Week 1 commit ships the **package shape** + **the closed-set enumeration of per-tenant lifecycle states + new event classes + OAuth token scopes** + **the `TenantConfig` / `TenantRegistry` dataclasses** + **the `init_multi_tenant` / `resolve_per_tenant_ledger_dir` / `resolve_per_tenant_policy_dir` primitive signatures**. The Week 2+ commits ship the implementation bodies per D376's per-week trajectory table.

The contract:

```python
# Pillar I Week 1 ships the contract; Weeks 2-6 ship the bodies.
from orchestrator.multi_tenant import (
    TenantConfig,                   # frozen dataclass — per-tenant config
    TenantRegistry,                 # frozen dataclass — multi-tenant aggregator
    TENANT_LIFECYCLE_STATES,        # frozenset — 4 states
    TENANT_NEW_EVENT_CLASSES,       # frozenset — 6 new Pillar I event classes
    TENANT_OAUTH_TOKEN_SCOPES,      # frozenset — 6 OAuth scopes (per channel)
    init_multi_tenant,              # ([TenantConfig], *, shared_install_dir) -> TenantRegistry  [Week 2]
    resolve_per_tenant_ledger_dir,  # (base_path, *, tenant_id) -> Path             [Week 2]
    resolve_per_tenant_policy_dir,  # (base_path, *, tenant_id) -> Path             [Week 2]
)

tenant_a = TenantConfig(
    tenant_id="tenant_a",
    vault_dir=Path("/var/outreach-factory/tenant_a/vault"),
    ledger_dir=Path("/var/outreach-factory/tenant_a/ledger"),
    policy_dir=Path("/var/outreach-factory/tenant_a/policy"),
    oauth_token_path=Path("/var/outreach-factory/tenant_a/oauth.json"),
    oauth_token_scopes=frozenset({"gmail.send", "linkedin.invite"}),
    grafana_folder_uid="folder-tenant-a",
)
registry = init_multi_tenant(
    [tenant_a, tenant_b],
    shared_install_dir=Path("/opt/outreach-factory"),
)   # Week 2 body
```

**SIX new event classes** at `TENANT_NEW_EVENT_CLASSES` per the per-pillar-foundation precedent (Pillar G Week 1 added two new classes via `OBSERVABILITY_NEW_EVENT_CLASSES`; Pillar H Week 1 added five via `DAEMON_NEW_EVENT_CLASSES` → six at W6; Pillar I adds six via `TENANT_NEW_EVENT_CLASSES`):

* `tenant_provisioned` — emit on tenant lifecycle `provisioning → active` transition; payload: `tenant_id` + `provisioned_at_ts` + `_emitted_by="multi_tenant"`.
* `tenant_paused` — emit on operator-deliberate pause; payload: `tenant_id` + `paused_at_ts` + `reason` (operator-supplied) + `_emitted_by="multi_tenant"`.
* `tenant_resumed` — emit on operator-deliberate resume after pause; payload: `tenant_id` + `resumed_at_ts` + `paused_duration_seconds` + `_emitted_by="multi_tenant"`.
* `tenant_deprovisioned` — emit on tenant removal; payload: `tenant_id` + `deprovisioned_at_ts` + `data_archived` (bool) + `_emitted_by="multi_tenant"`.
* `init_wizard_completed` — emit on init wizard first-run success; payload: `tenant_id` + `completed_at_ts` + `wizard_steps` (list of completed step names) + `_emitted_by="multi_tenant"`.
* `auth_token_refreshed` — emit on per-channel OAuth token refresh; payload: `tenant_id` + `token_scope` (member of `TENANT_OAUTH_TOKEN_SCOPES`) + `refreshed_at_ts` + `_emitted_by="multi_tenant"`.

Pillar I Week 2 extends `observability.EVENT_CLASS_CATALOG` with these six classes; the per-call `collect_event_class_snapshots` aggregates them uniformly with prior-pillar event classes per ADR-0050 D272. The Week 1 commit pins the closed-set; the Week 2 catalog extension is the symmetric assertion.

**FOUR per-tenant lifecycle states** at `TENANT_LIFECYCLE_STATES`:

* `"provisioning"` — tenant is being set up; init wizard runs OAuth flow + creates vault directories + applies migrations; per-tenant daemon is NOT yet emitting events.
* `"active"` — tenant's per-tenant daemon is running; per-tenant reconcile passes are dispatching; operators see per-tenant events in the per-tenant ledger.
* `"paused"` — operator-deliberate pause without process exit per ADR-0060 §Downstream pillar impact's pre-reserved state; per-tenant daemon's per-stage worker pool stops accepting new tasks; in-flight tasks complete; `tenant_paused` event emits.
* `"deprovisioning"` — tenant is being removed; per-tenant daemon exits gracefully; per-tenant ledger + vault MAY be archived per the operator's data retention policy; `tenant_deprovisioned` event emits.

The closed-set discipline + the regression-barrier test pins the contract. Pillar I Week 2 ships the per-tenant lifecycle state machine body.

**SIX OAuth token scopes** at `TENANT_OAUTH_TOKEN_SCOPES`:

* `"gmail.send"` — Gmail send scope (per Pillar C Week 1 + Phase 5.5 Gmail OAuth flow).
* `"gmail.readonly"` — Gmail read scope (per the inbox reconcile passes — bounce + reply detection).
* `"linkedin.invite"` — LinkedIn invite scope (per Pillar C Week 2).
* `"linkedin.dm"` — LinkedIn DM scope (per Pillar C Week 3).
* `"twitter.dm"` — Twitter DM scope (per Pillar C Week 5).
* `"calendar.book"` — Google Calendar scope (per Pillar C Week 6).

**Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 + Pillar H ADR-0060 D335** holds across the multi-tenant surface. The `TenantConfig` dataclass contains tenant_id + directory paths + OAuth scope frozenset + grafana folder UID + lifecycle state; NEVER `person_id` / body content / source_list. The SIX Pillar I event classes' payloads contain `tenant_id` + lifecycle timestamps + audit markers; NEVER any per-Person field. **NEW Pillar I invariant — cross-tenant isolation:** tenant A's audit surface MUST NOT leak tenant B's per-Person data; the per-tenant container model enforces this at runtime; the per-tenant daemon process boundary enforces this at the API surface. The Pillar I per-week-reviewer's privacy invariant check is the structural barrier.

### D372. Docker container runtime decision + framework-neutrality contract

The Pillar I container runtime is **Docker** (containerd-backed; docker-compose for local OSS bring-up; per-tenant container = one daemon process per ADR-0060 D335 invariant 1) at Week 1. The Pillar I Week 3 ships the `docker-compose.yml` + `Dockerfile` per ADR-0072.

Rationale (the four reasons per the Context section):

* Operator-tested choice — Fly.io / Railway / Render all accept Docker images; the OSS bring-up trajectory per PILLAR-PLAN §2 Pillar I names "cloud deploy templates" for these targets.
* Canonical OSS one-command-up shape — `git clone && docker compose up` is the operator-tested convention; the framework's per-pillar surfaces all consume the Docker container's filesystem (vault + ledger + policy directories mounted as Docker volumes).
* Per-tenant process-isolation preservation — Docker's per-container process isolation preserves Pillar H D335 invariant 1 (one daemon process per tenant); the per-tenant Docker container is exactly one daemon process.
* Kubernetes is structurally heavier than v1 OSS bring-up requires — kubernetes adds the orchestration layer + the resource limits + the per-tenant namespacing complexity; v1 OSS bring-up needs single-machine multi-tenant + cloud-template-per-tenant; v2+ operators wanting kubernetes wire it via the framework-neutrality contract.

Multi-runtime / per-container-runtime support (podman / nomad / kubernetes) is operator-deliberate fork at v1; Pillar I Week 1 ships Docker single-runtime per the framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 + the W4 follow-up P2-1 closure's seam-vs-fork two-tiered distinction. Operators wanting alternative container runtimes:

* **Tier 1 (seam — substitute BACKENDS):** The Pillar I per-tenant container's environment variables + volume mounts are the canonical seam; operators can run the same `orchestrator/multi_tenant/` Python module under podman / kubernetes / nomad by adapting the manifest's per-container shape. The Python primitive surface is runtime-neutral.
* **Tier 2 (fork — substitute FUNCTION BODIES):** Operators wanting alternative container orchestration (kubernetes Deployments / nomad jobs / podman pods) MUST fork the docker-compose manifest; the framework's per-tenant Python primitives preserve.

**Per-week trajectory table** (the structural commitment Weeks 2-6 satisfy; matches Pillar G Week 1's D273 + Pillar H Week 1's D332 shape):

| Week | Deliverable | New ADR? |
|---|---|---|
| 1 | Multi-tenant module shape + closed-sets + dataclasses + signatures + cross-pillar surface audit + exit-criterion vehicle + per-tenant load-bearing invariants + per-week trajectory (this commit, ADR-0070) | ADR-0070 |
| 2 | `TenantConfig` validation + `TenantRegistry` construction + per-tenant DaemonConfig extension with `tenant_id` field + per-tenant ledger directory resolution body + EVENT_CLASS_CATALOG extension with the SIX Pillar I event classes | ADR-0071 |
| 3 | `docker-compose.yml` + `Dockerfile` + per-tenant container orchestration + per-tenant Grafana folder isolation per Pillar G Week 4 trajectory | ADR-0072 |
| 4 | Init wizard body + Gmail OAuth flow + LinkedIn OAuth flow + first-send verification + `init_wizard_completed` event emit | ADR-0073 |
| 5 | CI bring-up + first CI surface + Pillar A §D3 deferred pricing-table check + per-tenant contention regression-barrier + startup-latency regression-barrier | ADR-0074 |
| 6 | Binding exit-criterion test un-skip + Pillar I Stable flip + retrospective + handoff to Pillar J | ADR-0075 |

Pillar H's per-week-handoff convention + per-week-review-with-follow-up-commit + per-ADR ≥3-rejected-alternatives + §Downstream-pillar-impact + holistic-exit-review discipline all carry-forward to Pillar I weeks.

### D373. Cross-pillar surface audit at `.planning/REVIEW-pillar-i-surface-audit.md`

`.planning/REVIEW-pillar-i-surface-audit.md` is the load-bearing anti-regression artifact future Pillar I weeks extend. The Week 1 audit walks every Pillar A/B/C/D/E/F/G/H surface that touches per-tenant scope / per-tenant directory paths / per-tenant OAuth tokens / per-tenant policy state / per-tenant observability / per-tenant daemon process for whether Pillar I's per-tenant fan-out silently broadens the assumption space.

The audit's load-bearing concerns:

* **Pillar A policy engine's per-tenant policy YAML hot-reload contract** — Pillar H Week 7's `reload_policy` body per ADR-0066 D356 is single-tenant; the per-tenant fan-out per D371 preserves the structural contract — each per-tenant daemon reloads its own per-tenant policy YAML. The Pillar I per-tenant audit verifies the per-tenant container's SIGHUP signal handler invokes the per-tenant `reload_policy()` path; cross-tenant signal delivery is prevented by Docker's per-container signal isolation.
* **Pillar B migration framework's auto-apply contract per-tenant** — `MigrationRunner.apply()` per ADR-0009 D9 is currently single-tenant; the per-tenant fan-out per D371 + D375 invariant (c) init-wizard-idempotence preserves the contract — each per-tenant daemon's startup invokes `MigrationRunner.apply()` against its own per-tenant ledger directory. The init wizard's idempotence per D375 invariant (c) preserves the migration framework's idempotence per ADR-0009 D9.
* **Per-Person lock primitive per Phase 5.5 per-tenant** — file-based locks via `fcntl` on the Person's directory; per-tenant Docker containers each have their own mounted vault directory; the per-tenant lock primitive preserves at the per-tenant grain (each tenant's container holds its own per-Person locks; cross-tenant lock acquisition is prevented by per-container filesystem isolation).
* **Pillar G stateless-aggregation contract per R033 per-tenant** — `observability.collect_event_class_snapshots` re-walks the ledger per call; per-tenant Docker containers each walk their own per-tenant ledger; the contract preserves at the per-tenant grain. The funnel CLI's READ-ONLY contract per ADR-0059 D325 + the byte-identical determinism per ADR-0031 D140 both preserve. **NEW Pillar I per-tenant audit-tooling consumer surface** (Pillar I Week 5+) — cross-tenant aggregations live at a SEPARATE per-tenant audit-tooling primitive, NOT the per-tenant primitive (the per-tenant primitive aggregates within a tenant; cross-tenant aggregation walks every per-tenant ledger directory).
* **Per-channel two-phase commit per ADR-0014 D33 per-tenant** — `send_intent` + `send_confirmed` pairs preserve per-tenant; the per-tenant daemon's per-stage worker pool dispatches against per-tenant Gmail credentials; cross-tenant send is prevented by per-tenant OAuth token isolation per D375 invariant (a).
* **Pillar F Layer 5 backstop per ADR-0049 D262 per-tenant** — Pass C's `ratifies_ready` predicate per-tenant refuses heal-to-`ready` without per-tenant `draft_ready` event; the per-tenant daemon's per-stage `ready` dispatch consults the per-tenant Pass C check; the FIVE-layer defense closed at Layer 5 preserves verbatim per-tenant.
* **Pillar H daemon's per-stage worker pool per-tenant** — Pillar H per-tenant audit-tooling extends `_recover_from_prior_crash` with per-tenant labels per D375 invariant (b); per-tenant containers each invoke crash-recovery synthesis against their own ledger; cross-tenant synthesis is prevented by per-tenant ledger directory isolation.

The audit's per-week-reviewer carry-forward checklist applies the SEVEN compounded disciplines from Pillar H Week 12 follow-up:

* Cell-level matrix coverage (THIRTY-SEVEN consecutive weeks at start of Pillar I Week 1).
* Behavioral-passthrough-not-signature-only (THIRTY-FOUR consecutive weeks).
* Module-level docstring drift (THIRTY-SIX consecutive weeks; Pillar I Week 1 extends `orchestrator/multi_tenant/__init__.py` + the daemon module docstring naming Pillar I trajectory).
* Per-pillar mirror constants parity (the SIX Pillar I event classes mirror the closed-set discipline per ADR-0050 D272 + ADR-0058 D322 + ADR-0060 D331; Pillar I Week 2 adds the catalog extension regression-barrier test).
* Cross-pillar back-audit (the audit's purpose; Pillar H surfaced TEN consecutive ADR-vs-actual-impl drifts + THREE P1 escalations per the W12 follow-up P3-1 closure — Pillar I Week 1 author MUST verify ADR-0070 narrative claims match actual implementation before commit per the Pillar H retrospective's "What to do differently in Pillar I" guidance).
* Framework-neutrality contract (the Docker decision at D372 preserves the contract; alternative container runtimes wire via the seam-vs-fork two-tiered distinction).
* Privacy invariant (the per-tenant surfaces preserve the I8 + ADR-0050 D276(b) + ADR-0058 D323 contract; the NEW per-tenant cross-tenant isolation extension is the structural extension).

### D374. Exit-criterion vehicle scope at `tests/test_multi_channel_coherence.py`

`tests/test_multi_channel_coherence.py` extends with THREE new test classes:

* `TestPillarIPerTenant` — per-week trajectory stubs (8 rows) un-skipping progressively as the per-week bodies land (Week 2: 4 rows; Week 3: 1 row; Week 4: 2 rows; Week 5: 1 row).
* `TestPillarIPerTenantObservabilityIntegration` — Pillar I ↔ Pillar G + Pillar H integration stubs (3 rows) for the catalog extension + per-tenant Grafana folder + per-tenant SLO surfaces.
* `TestPillarIExitCriterion::test_git_clone_docker_compose_up_doctor_produces_working_system` — the binding exit-criterion test stub (1 row) un-skipped at Pillar I Week 6.

The binding test verifies THREE rows (OSS bring-up reproducibility + init wizard zero-to-test-send-in-<10-min + CI bring-up reliability); the substrate is the hermetic Docker environment fixture per PILLAR-PLAN §2 Pillar I exit criterion; the < 10 min init wizard compresses to < 60s under the test via deterministic-clock seam.

Pillar G Week 1 (per ADR-0050 D275) shipped 12 stub rows; Pillar H Week 1 (per ADR-0060 D334) shipped 14 stub rows; Pillar I Week 1 ships 12 stub rows (TestPillarIPerTenant × 8 + TestPillarIPerTenantObservabilityIntegration × 3 + TestPillarIExitCriterion × 1) matching the scale of the per-week trajectory + the consumer surface.

**Cumulative coherence-vehicle size at Pillar I Week 1:** ~10800 LOC (Pillar H Week 12 follow-up close base of ~10550 + Pillar I Week 1 stubs ~250). The split argument per ADR-0037 D172 is TRIPLY LIVE; the Pillar I Week 1 reviewer's call whether to split. The Pillar H Week 12 reviewer did NOT split; precedent recommends Pillar I Week 1 also does NOT split (the per-pillar test classes' Week 1 stubs belong adjacent to the per-pillar primitive contracts they verify per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183 + ADR-0050 D275 + ADR-0060 D334 single-file rationale).

### D375. Per-tenant load-bearing invariants (FIVE; extending Pillar H Week 1 FOUR invariants per ADR-0060 D335)

1. **Per-tenant-isolation.** Each tenant's daemon process is fully isolated; no cross-tenant data leakage at any surface (ledger + vault + Grafana + OAuth tokens). The `resolve_per_tenant_ledger_dir` + `resolve_per_tenant_policy_dir` primitives produce per-tenant directory paths; per-tenant Docker containers each mount their own per-tenant directories as Docker volumes; per-tenant Grafana folders isolate dashboards per Pillar G Week 4 trajectory; per-tenant OAuth tokens isolate per-channel credentials. **Cross-tenant isolation:** tenant A's audit surface MUST NOT leak tenant B's per-Person data; the per-tenant container model enforces this at runtime; the per-tenant daemon process boundary enforces this at the API surface. The privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 EXTENDS to per-tenant.

2. **Per-tenant atomicity-preservation-across-process-boundary.** Extends Pillar H D335 invariant 2 per-tenant; one daemon process per tenant per ADR-0060 D335 invariant 1; per-tenant ledger directories preserve the append-only contract per I2 per-tenant. Per-tenant crash-recovery synthesis via Pillar H W10-11 `_recover_from_prior_crash` invoked per-tenant; per-tenant daemon contributes NO new state that bypasses the per-tenant ledger.

3. **Init-wizard idempotence.** Running the init wizard twice on the same user produces a NO-OP (idempotent per the existing Pillar B migration framework's precedent per ADR-0009 D9). The `init_wizard_completed` event class signals first-run completion; re-runs MAY emit but MUST NOT re-create OAuth tokens or vault directories. The init wizard's per-step refuse-loud per R042 mitigation surfaces operator-readable error messages at every step.

4. **OSS-bring-up reproducibility.** `git clone && docker compose up && doctor.py` on a fresh VM produces a byte-identical-deterministic working system per ADR-0031 D140. The docker-compose container image + the doctor preflight + the init wizard form the canonical OSS bring-up surface; operators clone + compose up + doctor + send. The per-tenant Docker container's image build is reproducible (pinned base image + pinned Python version + pinned dependencies per `orchestrator/requirements.txt`); the `doctor.py` preflight reports any environment drift.

5. **CI bring-up reliability.** The CI surface fails reliably on any unaccompanied pricing-table change per ADR-0006 §"CI enforcement of the price-update == ADR-amendment discipline" + the Pillar A §D3 deferred check landing at Pillar I Week 5 per the trajectory. The CI check shape is `git diff --name-only HEAD^ HEAD | grep -q budget.py` AND `git diff --name-only HEAD^ HEAD | grep -q 0006-budget-rules-and-cost-events.md` (both files must change together; refuse-loud if budget.py changes alone). The same check shape generalizes to any future "constant + ADR" pair.

### D376. Per-week trajectory (matches Pillar G ADR-0050 D273 + Pillar H ADR-0060 D332 shape)

Per D372's trajectory table above. Six weeks total (Pillar I budgeted Weeks 43-48); each week's deliverable + ADR named at design time so per-week 2+ authors do NOT re-decide scope.

## Alternatives considered

### D371 alternatives (per-tenant primitive shape)

1. **Extend `orchestrator/daemon/` with per-tenant fields instead of a new `orchestrator/multi_tenant/` package.** Rejected — the per-tenant scope is structurally distinct from the per-daemon scope; the Pillar H daemon package is one-daemon-process-shape; the Pillar I multi-tenant package is multi-daemon-orchestration-shape. Co-locating would conflate the two abstractions; the cross-pillar surface audit per D373 would surface the conflation as a P2. Pillar H's `DaemonConfig` extends with an optional `tenant_id` field at Pillar I Week 2 per ADR-0071; the operator-deliberate per-tenant config lives at `TenantConfig` in the multi_tenant package.

2. **Ship a thin `orchestrator/multi_tenant/cli.py` script-only surface instead of a Python package.** Rejected — the per-pillar-foundation precedent ships a Python package + module shape + signatures at Week 1; the per-week 2+ implementations consume the package's primitives. A script-only surface would not surface the per-pillar mirror constants parity discipline (`TENANT_LIFECYCLE_STATES` + `TENANT_NEW_EVENT_CLASSES` + `TENANT_OAUTH_TOKEN_SCOPES` would not have a structural home).

3. **Defer the multi_tenant module to Pillar I Week 2.** Rejected per the per-pillar-foundation precedent — Pillar G Week 1 + Pillar H Week 1 (ADR-0050 D272 + ADR-0060 D331) shipped the per-pillar module shape + signature at Week 1 + the body at Week 2+. The Week 1 commit's module shape is the structural commitment Weeks 2-6 satisfy; deferring would force the per-week-2+ ADRs to also pin the module shape (double-deciding the same question).

4. **Ship per-tenant fan-out as a runtime configuration of the existing single-tenant daemon (toggle via env var) instead of a per-tenant module.** Rejected — the per-tenant operator's mental model is "one daemon per tenant" (per ADR-0060 D335 invariant 1); env-var toggle would force a single daemon process to multiplex tenants, violating Pillar H's process-isolation invariant. The per-tenant container model (one Docker container per tenant) is the operator-tested shape; the per-tenant module's primitives orchestrate the per-tenant containers.

### D372 alternatives (container runtime)

1. **Podman.** Rejected at v1 — podman's rootless model is operator-attractive but the OSS bring-up trajectory's cloud deploy templates (Fly.io / Railway / Render) all canonically accept Docker images; podman compatibility is via the Docker-compatible CLI shim but the per-cloud-template's first-class support is Docker. Operators preferring podman wire via the framework-neutrality contract's Tier 2 fork.

2. **Kubernetes.** Rejected at v1 — kubernetes is structurally heavier than the v1 OSS bring-up requires (per-tenant namespaces + per-tenant resource limits + per-tenant secrets + per-tenant ConfigMaps + per-tenant network policies). The v1 multi-tenant scope is single-machine multi-tenant + cloud-template-per-tenant; v2+ operators wanting kubernetes wire via the framework-neutrality contract's Tier 2 fork. Pillar J's SLSA supply-chain attestation MAY surface kubernetes as a v2 first-class target.

3. **Nomad.** Rejected — nomad is operator-attractive at the Hashicorp-stack-aligned operators but the OSS bring-up trajectory's three cloud deploy templates (Fly.io / Railway / Render) all canonically accept Docker images, not nomad jobs. Operators preferring nomad wire via the framework-neutrality contract's Tier 2 fork.

4. **No container runtime (native systemd per-tenant).** Rejected — native systemd per-tenant requires per-tenant Linux user accounts + per-tenant systemd units + per-tenant SELinux policies; the OSS bring-up's "git clone && docker compose up" one-command-up shape per PILLAR-PLAN §2 Pillar I is incompatible with native systemd's per-host installation footprint. Operators preferring native systemd wire via the framework-neutrality contract's Tier 2 fork.

### D373 alternatives (cross-pillar surface audit scope)

1. **Skip the audit at Pillar I Week 1; defer to Pillar I Week 3 + the per-pillar-week trajectory.** Rejected per every prior pillar's Week 1 audit caught ≥1 P2 — the audit's structural value is at Week 1, before the per-week 2+ commits accumulate symmetric-assumption regressions. Pillar H Week 1's audit caught the cross-pillar daemon-consumer surface gap + closed at Week 2 per the per-week-handoff convention.

2. **Audit ONLY the immediately-adjacent surfaces (Pillar H daemon + Pillar G observability) — defer Pillar A/B/C/D/E/F to per-pillar-I per-week audits.** Rejected per the per-pillar-foundation precedent — every prior pillar audited ALL prior pillars at Week 1. The audit's structural value is the cross-pillar back-audit discipline; narrowing the scope at Week 1 would lose the structural value. Pillar H Week 1 audited Pillar A/B/C/D/E/F/G; Pillar I Week 1 audits Pillar A/B/C/D/E/F/G/H.

3. **Audit at the per-pillar-foundation ADR level only — do NOT extend per-week.** Rejected — every prior pillar's audit grew with per-week extensions; the per-week extension is the per-week-reviewer's load-bearing checklist row. Without per-week extension, the per-week-reviewer pattern's value compounds less.

### D374 alternatives (exit-criterion vehicle scope)

1. **Ship the binding test in a separate `tests/test_multi_tenant_e2e.py` instead of extending the cross-pillar coherence vehicle.** Rejected per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183 + ADR-0050 D275 + ADR-0060 D334 — the single-file canonical vehicle (`tests/test_multi_channel_coherence.py`) is the operator-readable cross-pillar coherence surface. Separating Pillar I's binding test would split the operator's reading surface; the per-pillar-foundation precedent's single-file rationale generalizes. Note: the cumulative size at Pillar I Week 1 (~10800 LOC) crosses the ~7500 LOC split threshold TRIPLY; the split argument resurfaces at the Pillar I Week N reviewer's discretion per ADR-0037 D172.

2. **Use a real fresh-VM `git clone && docker compose up` substrate instead of a hermetic Docker environment fixture.** Rejected per the practical operator-time constraint — a real fresh-VM bring-up cannot be a unit test; the structural commitment (OSS bring-up reproducibility + init wizard idempotence + CI bring-up reliability) compresses to the hermetic Docker environment fixture without losing coverage. Operators wanting a real fresh-VM bring-up wire it as a Pillar I CI surface per the OSS bring-up trajectory.

3. **Skip the binding test stub at Week 1; defer to Week 6.** Rejected per the per-pillar-foundation precedent — Pillar D + E + F + G + H Week 1 each shipped the binding test stub at Week 1 (un-skipped at Week 12 / final pillar week). The Week 1 stub commits the structural commitment to the binding test's per-row verification scope; the per-pillar-week trajectory + the per-week-reviewer's per-row coverage check both reference the stub.

### D375 alternatives (per-tenant load-bearing invariants)

1. **Skip the FIVE invariants at Week 1; defer to per-pillar-week ADRs.** Rejected per the per-pillar-foundation precedent — Pillar D's CAN-SPAM legal-liability invariant landed at Pillar D Week 1 per ADR-0025 D97; Pillar F's FIVE-layer defense landed at Pillar F Week 1 per ADR-0038 D180; Pillar G's FOUR invariants landed at Pillar G Week 1 per ADR-0050 D276; Pillar H's FOUR invariants landed at Pillar H Week 1 per ADR-0060 D335. The Week 1 invariants are the structural commitments Weeks 2-6 satisfy.

2. **Define only THREE invariants (per-tenant-isolation + init-wizard-idempotence + OSS-bring-up-reproducibility); defer atomicity-preservation + CI-bring-up-reliability to per-week.** Rejected — the five invariants are mutually-coupled (per-tenant-isolation enables per-tenant atomicity-preservation; init-wizard-idempotence makes OSS-bring-up-reproducibility safe across re-runs; CI-bring-up-reliability is the structural commitment to the deferred Pillar A §D3 check landing at Pillar I Week 5). Splitting would weaken the structural commitment.

3. **Add a SIXTH invariant: per-tenant resource isolation (CPU + memory limits per tenant container).** Considered + REJECTED at Week 1 — resource isolation is a v2+ operator concern (~100 tenants on one machine surfaces resource contention); v1 multi-tenant scope is ~10 tenants per machine; resource limits at the Docker container level are operator-deliberate per the per-cloud-template's per-tenant config. Pillar J's security + compliance pillar MAY surface resource isolation as a v2 first-class invariant.

### D376 alternatives (per-week trajectory table)

1. **Compress to FOUR weeks (Week 1 + Week 2 + Week 4 + Week 6) instead of SIX.** Rejected — PILLAR-PLAN §2 Pillar I budgets Weeks 43-48 (6 weeks); the Pillar I scope (multi-tenant + OSS hardening + CI bring-up + init wizard) is structurally distinct from prior pillars at the OSS bring-up grain; compression would force per-week 2 to also ship docker-compose + init wizard, conflating three structural decisions in one week.

2. **Defer CI bring-up to Pillar J (security + compliance).** Rejected per PILLAR-PLAN §2 Pillar I — the CI bring-up is named at Pillar I per the deferred Pillar A §D3 check landing at Pillar I per ADR-0006 §"CI enforcement". Pillar J's security + compliance is structurally distinct (OAuth token rotation + secret scanning + dependency vulnerability scanning + SLSA + encrypted-at-rest credentials).

3. **Defer init wizard to Pillar J.** Rejected per PILLAR-PLAN §2 Pillar I — the init wizard is named at Pillar I per the OSS bring-up trajectory (init wizard takes a new user from zero to a successful test send in < 10 minutes). The init wizard's idempotence per D375 invariant (c) is the structural Pillar I invariant; Pillar J's GDPR-compliant data deletion is structurally distinct.

## Consequences

### Positive

- **Pillar I Week 1's framework decisions are pinned before per-week 2+ implementations.** D371 pins the multi-tenant module shape; D372 pins the Docker container runtime; D375 pins the five load-bearing invariants; D376 pins the per-week trajectory. Weeks 2-6 satisfy the structural commitments without re-deciding the framework choice.
- **The per-pillar-foundation precedent extends to Pillar I.** Pillar D + E + F + G + H all shipped Week 1 with module shape + signature + binding test stub + cross-pillar audit + load-bearing invariants; Pillar I Week 1 follows the same pattern.
- **The per-week-reviewer's checklist for Pillar I carries the THIRTY-SEVEN-consecutive-weeks track record forward.** Cell-level matrix coverage + behavioral-passthrough + module-level docstring drift + cross-pillar back-audit + per-pillar mirror constants parity + framework-neutrality contract + privacy invariant — all carry-forward.
- **The closed-set discipline extends to Pillar I** — `TENANT_LIFECYCLE_STATES` + `TENANT_NEW_EVENT_CLASSES` + `TENANT_OAUTH_TOKEN_SCOPES` are R031-shape regression-barriers + the Week 2 catalog extension's symmetric-assertion regression-barrier test catches drift.
- **The privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 + ADR-0060 D335 EXTENDS to per-tenant cross-tenant isolation.** The `TenantConfig` dataclass + the SIX Pillar I event class payloads + every per-tenant surface preserves the per-tenant isolation contract — tenant A's audit surface MUST NOT leak tenant B's per-Person data.
- **The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 + the W4 follow-up P2-1 closure extends to Pillar I** — Docker is the framework default at v1; operators wanting podman / kubernetes / nomad wire via the seam-vs-fork two-tiered distinction.

### Negative

- **The Pillar I Week 1 commit is larger than Pillar H Week 1's commit** — Pillar H Week 1 shipped the `orchestrator/daemon/` package at ~500 LOC + ADR-0060 ~500 LOC + audit ~500 LOC + tests ~400 LOC + coherence stubs ~200 LOC; Pillar I Week 1 ships the `orchestrator/multi_tenant/` package at ~350 LOC + ADR-0070 ~600 LOC + audit ~500 LOC + tests ~400 LOC + coherence stubs ~250 LOC. The per-pillar-foundation precedent's per-week-1-commit-size growth is monotonic; Pillar I's growth reflects the multi-tenant + OSS bring-up structural complexity.
- **The Pillar I Week 2+ bodies represent significant per-week implementation work** — the per-week-2+ ADRs (ADR-0071 through ADR-0075) will be commensurately substantial; the per-pillar-week trajectory budget (6 weeks) is shorter than Pillar G + Pillar H (12 weeks each) but the structural scope is narrower (OSS bring-up + CI bring-up vs framework adoption + daemon foundation).
- **The Docker single-runtime choice at v1 is a deferral to operator-fork for podman / kubernetes / nomad.** Operators preferring alternative container runtimes wire via the framework-neutrality contract's Tier 2 fork; the framework default + the test substrate use Docker. Pillar J's SLSA supply-chain attestation MAY surface kubernetes as a v2 first-class target.
- **The single-machine multi-tenant scope at v1 is a deferral to per-cloud-template-per-tenant.** Operators running ~10 tenants per machine see no contention; operators running ~100 tenants per machine surface R040 (per-tenant ledger directory contention); v2+ operators wire one machine per tenant via the cloud deploy templates per D372.

### Neutral

- **No new pip dependencies at Pillar I Week 1.** The multi_tenant module's Week 1 surface is stdlib (`dataclasses` + `pathlib` + `typing`); the Week 2+ bodies add no NEW pip deps (the per-tenant fan-out consumes the existing Pillar A-H surfaces). Week 3 adds the docker-compose manifest (NOT a pip dep) + the Dockerfile (NOT a pip dep). Week 4 init wizard MAY add an interactive prompt library (TBD per ADR-0073).
- **No new ledger migrations at Pillar I Week 1.** The pending count stays at 19 (UNCHANGED from Pillar H Week 12 follow-up). Pillar I Week 2 MAY ship a `vault/0008_add_tenant_id_to_person_notes` migration if the per-tenant fan-out requires per-tenant vault schema extension; the operator-deliberate single-tenant path remains UNCHANGED at v1.
- **No new event classes at Pillar I Week 1 in `EVENT_CLASS_CATALOG`.** The SIX new event classes at `TENANT_NEW_EVENT_CLASSES` are named at design time; the Week 2 catalog extension is the symmetric-assertion regression-barrier test target. The catalog stays content-additive at Week 1 (ZERO new entries).
- **No changes to the Pillar G framework adoption surfaces.** OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + Grafana per-Person dashboard + funnel CLI extension all preserve verbatim. The multi_tenant package CONSUMES these surfaces per-tenant.
- **No changes to the Pillar H daemon surface.** DaemonConfig + DaemonRunner + init_daemon + attach_signal_handlers + serve_health_endpoint + the SIX emit factories + the EIGHT closed-sets + per-event-class index materialization + per-append observer seam + crash-recovery synthesis + operator-deliberate pre-flight reconcile + Grafana per-daemon dashboard with SEVEN panels all preserve verbatim. Pillar I Week 2 extends DaemonConfig with an optional `tenant_id` field per ADR-0071; the operator-deliberate single-tenant default preserves.
- **No changes to the binding exit-criterion tests of Pillar D / E / F / G / H.** All five STAY GREEN across the Pillar I Week 1 commit + the Pillar I Week 1 follow-up commit (if any P2s surface per the per-week-reviewer pattern).

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant + EXTENDED — per-tenant ledger directories preserve the per-tenant event stream's SoT posture; the per-tenant primitive aggregations derive from per-tenant ledger walks; no cached cross-tenant state.
- **I2 (Atomicity contract).** Compliant + EXTENDED — D375 invariant 2 (per-tenant atomicity-preservation-across-process-boundary) is the structural commitment. Per-tenant daemons contribute NO new state that bypasses the per-tenant ledger; the per-channel two-phase intent/confirmed pairs per ADR-0014 D33 still complete via per-tenant reconcile passes.
- **I3 (Single source of truth).** Compliant — every per-tenant observability primitive's aggregation derives from the per-tenant ledger walk; no cached cross-tenant state; per-tenant Docker containers each walk their own per-tenant ledger.
- **I4 (Determinism).** Compliant + EXTENDED — D374 + the binding exit-criterion test ROW 1 + the OSS-bring-up reproducibility per D375 invariant (d) all preserve; the docker-compose container image build is reproducible (pinned base image + pinned Python version + pinned dependencies).
- **I5 (Refuse loud).** Compliant — the init wizard's per-step refuse-loud per R042 mitigation; the `init_multi_tenant` body's per-tenant config validation per ADR-0070 D371; the per-tenant daemon's pre-flight checks (per-tenant migrations applied + per-tenant policy loaded + per-tenant OTel SDK initialized + per-tenant Prometheus exporter listening) MUST all succeed before per-tenant transition to `"active"`.
- **I6 (No silent state).** Compliant — every per-tenant lifecycle transition emits a ledger event (`tenant_provisioned` / `tenant_paused` / `tenant_resumed` / `tenant_deprovisioned`); every operator-visible state derives from the per-tenant ledger walk.
- **I7 (Refuse loud on broken pipelines).** Compliant — D375 invariant 3 (init-wizard-idempotence) + invariant 5 (CI-bring-up-reliability) both refuse-loud on failure. The init wizard's per-step refuse-loud surfaces operator-readable error messages; the CI check fails loud on unaccompanied pricing-table change.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant + EXTENDED — D375 invariant 1 (per-tenant-isolation) extends I8 to per-tenant cross-tenant isolation. The `TenantConfig` dataclass + the SIX Pillar I event class payloads + every per-tenant surface preserves the per-tenant isolation contract — tenant A's audit surface MUST NOT leak tenant B's per-Person data. The Pillar I per-week-reviewer's privacy invariant check is the structural barrier.
- **The channel-on-every-event invariant per ADR-0014 D33** — Unaffected — Pillar I's per-tenant fan-out does NOT introduce new event classes that carry `channel` directly (the SIX Pillar I event classes are per-tenant-lifecycle events without channel context); the per-channel two-phase commit per ADR-0014 D33 preserves verbatim at the per-tenant per-channel dispatcher layer.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar I does NOT modify the per-send gate; the CAN-SPAM compliance per Pillar D preserves verbatim per-tenant.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — Pillar I does NOT modify the Layer 1-5 surfaces; the Pillar F primitive surfaces + Layer 5 backstop preserve verbatim per-tenant.
- **The one-CLI-invocation invariant per ADR-0050 D276(a)** — Preserved — per-tenant operators invoking `python orchestrator/funnel.py --since N --tenant <id>` (Pillar I Week 2+) get the same byte-identical output per ADR-0031 D140; Pillar I's per-tenant filter is opt-in.
- **The READ-ONLY funnel CLI contract per ADR-0059 D325** — Preserved — Pillar I per-tenant fan-out MAY extend the funnel CLI with `--tenant <id>` filtering at Week 2+; the READ-ONLY contract preserves.
- **The byte-identical determinism contract per ADR-0031 D140** — Preserved + EXTENDED — D375 invariant (d) OSS-bring-up reproducibility extends the determinism contract to the docker-compose container image + the doctor preflight.
- **The Pillar H per-daemon load-bearing invariants per ADR-0060 D335** — Preserved + EXTENDED — D375 invariants 1 + 2 extend Pillar H D335 invariants 1 + 2 per-tenant. The Pillar H atomicity contract holds per-tenant; the Pillar H graceful-shutdown holds per-tenant container.

## Downstream pillar impact

- **Pillar J (Security + compliance).** GDPR-purge transaction per ADR-0050 §Downstream extends to the per-tenant fan-out — per-tenant GDPR-purge invalidates per-tenant ledger entries + emits per-tenant purge events. The per-tenant container model isolates per-tenant purge from cross-tenant data. OAuth token rotation per Pillar J extends to the per-tenant `auth_token_refreshed` event class; per-tenant operators see per-tenant token rotation events in their per-tenant ledger. SLSA supply-chain attestation per Pillar J extends to the per-tenant Docker container image + the docker-compose manifest. Secret scanning per Pillar J extends to the per-tenant OAuth token files. Encrypted-at-rest credentials per Pillar J extends to the per-tenant `oauth_token_path` per `TenantConfig`.

## Migration / rollout

- **Operator-side action required at Pillar I Week 1 upgrade:** **NONE — content-additive at the framework boundary.** The Week 1 commit adds the `orchestrator/multi_tenant/` package + the tests + the ADR + the audit doc + the test class stubs in `tests/test_multi_channel_coherence.py`. Operators continue to invoke `python orchestrator/funnel.py --since N` + the per-skill `claude /find-leads` / `/research-prospect` / `/draft-outreach` / `/send-outreach` surfaces unchanged. Single-tenant operators see ZERO operator-action-required at Pillar I Week 1.
- **Recommended (optional):** operators wanting to PREVIEW the Pillar I multi-tenant surface at Week 1 do NOT have a body to invoke (the Week 1 commit ships signatures + `NotImplementedError` raises); the operator-visible multi-tenant primitive ships at Pillar I Week 2+.
- **No ledger schema migration** — Week 1 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes in `EVENT_CLASS_CATALOG`** — Week 1 ships the SIX classes at `TENANT_NEW_EVENT_CLASSES` as a named-at-design-time closed-set; the Week 2 catalog extension is the symmetric-assertion regression-barrier test target.
- **No new pip dependencies at Pillar I Week 1** — the multi_tenant module's Week 1 surface is stdlib (`dataclasses` + `pathlib` + `typing`); Week 3 adds the docker-compose manifest (NOT a pip dep); Week 4 init wizard MAY add an interactive prompt library (TBD per ADR-0073).

## Existing-operator seed

Operator action required at Pillar I Week 1: **NONE — content-additive at the framework boundary.**

Recommended (optional): operators following the Pillar I per-week trajectory consume the per-week handoff docs at `.planning/HANDOFF-pillar-i-week-N.md` + the per-week ADRs at `docs/adr/007N-pillar-i-week-N-*.md`. Operators waiting for the Pillar I multi-tenant land the body at Pillar I Week 2+ per D376's trajectory.

Single-tenant operators continue to invoke the framework's existing CLI surface (`python orchestrator/funnel.py` + the per-skill surfaces) without modification. The Pillar I multi-tenant fan-out is opt-in via the `TenantRegistry` set-once at process start (Week 2+); operators NOT setting up `TenantRegistry` see the existing single-tenant behavior unchanged.

## References

- **ADR-0069** (Pillar H Week 12 — binding exit-criterion + funnel CLI extension + Pillar H Stable flip + retrospective + handoff to Pillar I). D367-D370. **D370's handoff doc at `.planning/HANDOFF-pillar-i-week-1.md` is the canonical Pillar H → Pillar I trajectory bridge.**
- **ADR-0068** (Pillar H Week 10-11 — crash recovery hardening). D364-D366. **`_recover_from_prior_crash` extends per-tenant at Pillar I Week 2+.**
- **ADR-0067** (Pillar H Week 8-9 — per-event-class index materialization + per-append observer seam). D359-D363. **EventClassIndex + PersonEventIndex extend per-tenant labels at Pillar I Week 2+.**
- **ADR-0066** (Pillar H Week 7 — reload_policy body + dispatch_fn seam). D356-D358. **Per-tenant SIGHUP signal handler invokes per-tenant reload_policy at Pillar I Week 3+.**
- **ADR-0060** (Pillar H Week 1 foundation — daemon module shape + load-bearing invariants + per-event-class indexing trajectory). D331-D336. **The per-pillar-foundation precedent for Pillar I Week 1's structure + D335 invariant 1 (one daemon process per tenant) is the structural commitment Pillar I per-tenant fan-out preserves.**
- **ADR-0059** (Pillar G Week 12 — binding exit-criterion + funnel CLI extension + Pillar G Stable flip). D325-D330. **D325's READ-ONLY funnel CLI contract preserves; Pillar I Week 2+ extends with `--tenant <id>` filtering preserving READ-ONLY.**
- **ADR-0058** (Pillar G Week 10-11 — per-Person observability surface adapters). D319-D324. **Per-Person primitives extend per-tenant breakdown dimension at Pillar I Week 2+.**
- **ADR-0056** (Pillar G Week 7-8 — SLO violation detector + Slack webhook). D307-D313. **Per-tenant SLO surfaces preserve privacy invariant per Pillar I D375 invariant (a) cross-tenant isolation.**
- **ADR-0054** (Pillar G Week 5 — OTel tracing initialization). D294-D299. **Per-tenant OTel SDK initialization at Pillar I Week 2+.**
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring + first Grafana-as-code dashboard). D288-D293. **D291's Prometheus HTTP exposition server's `127.0.0.1` security-by-default bind generalizes to per-tenant Docker container at Pillar I Week 3.**
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization). D282-D287. **D286's framework-neutrality contract generalizes to the Docker container runtime decision per ADR-0070 D372.**
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape). D272-D277. **The per-pillar-foundation precedent for Pillar I Week 1's structure + D276(d) single-tenant default preserves at Pillar I Week 1; multi-tenant fan-out is opt-in.**
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + Pillar F Stable flip). D262-D271. **The Layer 5 backstop preserves verbatim per-tenant.**
- **ADR-0038** (Pillar F foundation — FIVE-layer hallucination-detection defense). D180. **The Pillar F FIVE-layer defense preserves verbatim per-tenant.**
- **ADR-0037** (Pillar E Week 12 — Pillar E Stable flip). D172. **The cumulative single-file coherence vehicle's ~7500 LOC split threshold remains TRIPLY LIVE at Pillar I Week 1 (~10800 LOC); Pillar I Week N may surface the split argument again.**
- **ADR-0032** (Pillar E foundation — discovery quality + lineage). D148's privacy invariant. **Preserved + EXTENDED per-tenant cross-tenant isolation per Pillar I D375 invariant (a).**
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract). **Preserved + EXTENDED per ADR-0070 D375 invariant (d) OSS-bring-up reproducibility.**
- **ADR-0025** (Pillar D foundation). D97 (legal-liability invariant — CAN-SPAM compliance) + D101 (Pillar D foundation's single-file coherence vehicle). **The CAN-SPAM invariant preserves verbatim per-tenant.**
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant). **Preserved per-tenant per-channel.**
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). **The Pillar I per-tenant event classes emit `_emitted_by="multi_tenant"` per the audit-marker discipline.**
- **ADR-0009** (Pillar B foundation — migration framework + idempotent auto-apply contract). D9. **The Pillar I init wizard's idempotence per D375 invariant (c) generalizes the Pillar B migration framework's idempotence to the init wizard surface.**
- **ADR-0006** (Pillar A — budget rules + cost events). §"CI enforcement of the price-update == ADR-amendment discipline". **The Pillar A §D3 deferred check lands at Pillar I Week 5 per ADR-0070 D375 invariant (e) + D376 trajectory.**
- **ADR-0001** (Pillar A foundation — declarative policy engine). D2 (refuse-loud convention). **Preserved at every Pillar I per-step refuse-loud surface.**
- `.planning/REVIEW-pillar-i-surface-audit.md` — cross-pillar surface audit (Pillar I Week 1 baseline; Weeks 2-6 sections per the per-week-handoff convention).
- `.planning/HANDOFF-pillar-i-week-1.md` — Pillar H → Pillar I trajectory bridge (existing; Pillar I Week 1 author appends close + Week 2 trajectory).
- `.planning/RETRO-pillar-h.md` — Pillar H retrospective (calibration + what to do differently in Pillar I + carry-forwards into Pillar I).
- `docs/PILLAR-PLAN.md` §2 Pillar I + §6 Pillar I row Week 1 status flip + Notes column appended Week 1 close summary.
- `docs/RISK-REGISTER.md` R040 + R041 + R042 NEW.
- `docs/SOURCES-OF-TRUTH.md` — per-tenant-state row added with Pillar I Week 1 ADR-0070 reference.
- `orchestrator/multi_tenant/` (NEW package: `__init__.py`) — Pillar I Week 1 module shape + closed-sets + dataclasses + signatures per D371.
- `tests/test_multi_tenant.py` (NEW; ~400 LOC + 32 contract-level tests) — covers the closed-sets + dataclass invariants + primitive signatures.
- `tests/test_multi_channel_coherence.py` extended with `TestPillarIPerTenant` × 8 + `TestPillarIPerTenantObservabilityIntegration` × 3 + `TestPillarIExitCriterion` × 1 stubs (12 rows skipped at Week 1; un-skipping progressively per D376's trajectory).

## Pillar I Week 1 follow-up addendum

The Pillar I Week 1 main commit `264f13d` shipped the per-pillar-foundation per D371-D376; the per-week independent reviewer at Phase 3 of the Pillar I Week 1 workflow caught **3 P3 narrative-drift findings** the inline author missed (mirroring the Pillar H Week 12 follow-up's review of `e6bad16` which caught 3 P3s including the TENTH ADR-vs-actual-impl drift per the W12 follow-up P3-1 closure). The Pillar I Week 1 follow-up commit closes these per the per-pillar-foundation precedent of Pillar G Week 12 follow-up `43612a8` + Pillar H Week 1 follow-up `452d7ae` + Pillar H Weeks 2-12 follow-ups.

**P3-1 closure** — **FIRST Pillar I ADR-vs-actual-impl drift** (the per-week-reviewer's cross-pillar back-audit discipline EXTENDED from TEN consecutive Pillar H catches to ELEVEN consecutive weeks across the Pillar H + Pillar I trajectory). The W1 main commit's narrative (commit message §D373 + `.planning/HANDOFF-pillar-i-week-1.md` line 153) claimed "1 P2 + **18 P3** concerns documented for Pillar I Week 2-6 trajectory" — but `grep -c "Concern [A-Z][0-9]\+ (P3" .planning/REVIEW-pillar-i-surface-audit.md` returns **15 P3**; total concerns are 17 (1 P2 G1 substantively named + 15 P3 + 1 Deferred H4 from Pillar H W7 follow-up NEW-2). Off-by-three drift. **Severity P3** — narrative-only; the audit doc IS the load-bearing artifact + each concern IS individually documented + the P2 concern G1 IS substantively named; no production code path broken. **P3-1 CLOSED** via HANDOFF doc line 153 narrative correction ("18 P3" → "15 P3 + 1 Deferred from Pillar H W7 follow-up NEW-2") + NEW `TestPillarIW1FollowupSubstantiveConcernCounts` × 3 regression-barrier tests at `tests/test_multi_tenant.py` pinning the substantive concern counts (`test_audit_doc_p3_concern_count_is_fifteen` + `test_audit_doc_p2_concern_count_is_one` + `test_audit_doc_deferred_concern_count_is_one`).

**P3-2 closure** — stale "NINE consecutive ADR-vs-actual-impl drift catches" count at ADR-0070 lines 14 + 158 + `.planning/REVIEW-pillar-i-surface-audit.md` §10 line 154. The W1 main commit's ADR was authored against the pre-W12-follow-up state; the actual count post-W12-follow-up is **TEN** consecutive Pillar H weeks per the W12 follow-up P3-1 closure naming the TENTH drift (W2 P3-8 → W3 P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2 → W7 P1-1 → W8 follow-up P2-1 → W9 follow-up P2-1 → W10-11 main P1-1 → W12 main P3-1). The W1 main commit message body correctly says TEN; the ADR-0070 + audit narrative was stale. **Severity P3** — narrative-only; the substantive claim that the per-week-reviewer pattern HAS empirical structural value IS preserved; the "THREE P1 escalations" half of the claim IS correct. **P3-2 CLOSED** via "NINE" → "TEN" at ADR-0070:14 + ADR-0070:158 + audit §10 line 154 naming the W12 follow-up P3-1 closure source-of-correction + the FIRST Pillar I follow-up drift catch extending the count to ELEVEN consecutive weeks.

**P3-3 closure** — discipline-counts narrative drift at `.planning/HANDOFF-pillar-i-week-1.md` lines 80-82. The W1 main commit's HANDOFF doc lines 80-82 said "**THIRTY-SIX** consecutive weeks at Pillar H Week 12 close → **THIRTY-SEVEN** after Pillar I Week 1" + "**THIRTY-THREE** → **THIRTY-FOUR**" + "**THIRTY-FIVE** → **THIRTY-SIX**" — but per the W12 follow-up P3-3 closure's standardization (the W10-11 follow-up convention of "includes current commit" preserved), the post-W12-follow-up counts are **THIRTY-SEVEN / THIRTY-FOUR / THIRTY-SIX** + at Pillar I Week 1 close **THIRTY-EIGHT / THIRTY-FIVE / THIRTY-SEVEN**. The W1 main commit message body correctly uses THIRTY-EIGHT / THIRTY-FIVE / THIRTY-SEVEN; the HANDOFF doc was authored pre-W12-follow-up + didn't get re-aligned. **Severity P3** — narrative-only; the substantive claim that the per-week-reviewer disciplines have COMPOUNDED across consecutive weeks IS preserved. **P3-3 CLOSED** via standardization on post-W12-follow-up framing (THIRTY-EIGHT cell-coverage + THIRTY-FIVE behavioral-passthrough + THIRTY-SEVEN module-docstring-drift post-W1 main; THIRTY-NINE / THIRTY-SIX / THIRTY-EIGHT post-W1 follow-up) at HANDOFF lines 80-82.

**REFUTED concerns** (preserved from the W1 main review):

1. First per-tenant ADR — expect ADR-vs-actual-impl drift per the Pillar H precedent — VERIFIED at the narrative level (P3-1 + P3-2 + P3-3 above) but ZERO drift at the code level. `TenantConfig` field list verified field-by-field matches ADR D371 verbatim; the SIX event classes verbatim match; the SIX OAuth scopes verbatim match; the signatures of `init_multi_tenant`/`resolve_per_tenant_ledger_dir`/`resolve_per_tenant_policy_dir` verbatim match; NotImplementedError messages name Week 2 + ADR-0070. NO P1 or P2 production-default breakage at Pillar I W1.
2. `tests/test_multi_channel_coherence.py` ~10800 LOC split argument — Pillar I Week 1 reviewer's call to NOT split, matching the Pillar H Week 12 reviewer's precedent.
3. Per-tenant ledger directory contention (R040) named at Week 1 — VERIFIED.
4. CI bring-up scope creep at Week 5 — VERIFIED (ADR-0070 D376 Week 5 row + D375 invariant (e) + audit doc §11 explicitly name the Pillar A §D3 deferred pricing-table check as the CANONICAL FIRST CI surface).
5. Docker decision irreversibility — VERIFIED (D372 + audit §10 framework-neutrality contract row + ADR-0070 §Consequences (Negative) item 3 + the seam-vs-fork two-tiered distinction per W4 follow-up P2-1 closure all preserve operator choice).
6. W7 follow-up NEW-2 (shutdown-during-in-flight-reconcile) + W8 follow-up P3-6 (`_data` field naming) STAYS DEFERRED — VERIFIED in audit doc §8 Concern H4 + HANDOFF "Deferred items" §97-100.

**Per-week-reviewer disciplines status after Week 1 follow-up:**

* **Cell-level matrix coverage** — **THIRTY-NINE** consecutive weeks (Pillar F W6-W12 + Pillar G W2-W12 + W12 follow-up + Pillar H W1 follow-up + W2 + W2 follow-up + W3 + W3 follow-up + W4 + W4 follow-up + W5 + W5 follow-up + W6 + W6 follow-up + W7 + W7 follow-up + W8 + W8 follow-up + W9 + W9 follow-up + W10-11 + W10-11 follow-up + W12 + W12 follow-up + Pillar I W1 + Pillar I W1 follow-up; +3 net new W1 follow-up regression-barrier tests 32 → 35 multi-tenant contract-level tests).
* **Behavioral-passthrough-not-signature-only** — **THIRTY-SIX** consecutive weeks. The W1 follow-up regression-barriers exercise the actual audit doc concern counts via `grep -c` invocations — the FIRST behavioral-passthrough application of the discipline at Pillar I.
* **Module-level docstring drift** — **THIRTY-EIGHT** consecutive weeks (`orchestrator/multi_tenant/__init__.py` + `orchestrator/daemon/__init__.py` module docstrings extended naming Pillar I Week 1 follow-up + the THREE P3 closure categories).
* **Per-pillar mirror constants parity** — PRESERVED (the THREE Pillar I closed-sets preserve verbatim; the SIX-element `TENANT_NEW_EVENT_CLASSES` + the SIX-element `TENANT_OAUTH_TOKEN_SCOPES` + the FOUR-element `TENANT_LIFECYCLE_STATES` preserve — no new closed-set at W1 follow-up).
* **Cross-pillar back-audit** — EXTENDED to **ELEVEN** consecutive weeks across the Pillar H + Pillar I trajectory (Pillar H TEN per the W12 follow-up P3-1 closure + Pillar I W1 follow-up FIRST drift catch). The per-week-reviewer pattern's empirical structural value at Pillar I Week 1 IS validated by this catch — the per-pillar-foundation precedent's "First per-tenant ADR — expect ADR-vs-actual-impl drift" prediction from the Pillar H retrospective IS confirmed.
* **Framework-neutrality contract** — PRESERVED (Docker decision at D372 preserves the contract; alternative container runtimes wire via the seam-vs-fork two-tiered distinction).
* **Privacy invariant** — PRESERVED + EXTENDED per-tenant cross-tenant isolation per D375 invariant (a). The W1 follow-up does NOT alter the privacy posture.

orchestrator/multi_tenant/__init__.py changes: module-level docstring extension naming Pillar I Week 1 follow-up + the THREE P3 closure categories (P3-1 + P3-2 + P3-3) + the FIRST Pillar I ADR-vs-actual-impl drift naming + the per-pillar-foundation precedent of Pillar H Week 12 follow-up `03f59cd` + Pillar G Week 12 follow-up `43612a8` + Pillar H Week 1 follow-up `452d7ae`.

orchestrator/daemon/__init__.py changes: module-level docstring extension naming Pillar I Week 1 follow-up + the THREE P3 closure categories.

tests/test_multi_tenant.py changes: NEW `TestPillarIW1FollowupSubstantiveConcernCounts` class with THREE regression-barrier tests (`test_audit_doc_p3_concern_count_is_fifteen` + `test_audit_doc_p2_concern_count_is_one` + `test_audit_doc_deferred_concern_count_is_one`) per the P3-1 closure substantive claim + the FIRST Pillar I ADR-vs-actual-impl drift trace.

Net new tests: +3 (32 → 35 multi-tenant contract-level tests). 4216 total passing post-follow-up (was 4213 + 3 net new); 25 skipped UNCHANGED.

ZERO new ADRs (the follow-up's fixes are: ADR-0070 narrative corrections + audit doc + HANDOFF doc + module-docstring extensions + NEW regression-barrier test class — all in the spirit of ADR-0070's existing decisions per the per-pillar-foundation precedent). ZERO new ledger migrations (pending stays at 19). ZERO new event classes. ZERO new closed-sets. ZERO new pip dependencies. ZERO new R-risks. The Pillar D + E + F + G + H binding exit-criterion tests STAY GREEN at all six rows. The Pillar G framework adoption surfaces preserve VERBATIM. The Pillar H daemon surfaces preserve VERBATIM. The Pillar B Ledger surface preserves verbatim. The Pillar F primitive surfaces + Layer 5 backstop preserve verbatim. The Pillar I Week 1 main commit's surfaces preserve VERBATIM; the W1 follow-up only EXTENDS via the THREE P3 closure categories per the per-pillar-foundation precedent.

## Pillar I Week 2 addendum — primitive bodies + catalog extension

Week 2 ships the bodies the Week 1 signatures reserved (per D376 trajectory),
threaded into the golden path as the first executable Pillar I assertion:

- `init_multi_tenant` body — validates no duplicate `tenant_id` (refuse-loud per
  D375 invariant (a)) + `shared_install_dir` absolute & exists; returns the frozen
  `TenantRegistry`. `TenantConfig.__post_init__` validates id format + oauth-scope
  subset + lifecycle-state membership + path absoluteness.
- `resolve_per_tenant_ledger_dir` / `resolve_per_tenant_policy_dir` bodies —
  `base / tenant_id`, with the `^[a-z][a-z0-9_-]{0,62}$` guard barring traversal
  so a per-tenant subtree can neither alias another's nor escape the base.
- `observability.EVENT_CLASS_CATALOG` extended with the SIX `TENANT_NEW_EVENT_CLASSES`
  (mirror-parity per ADR-0050 D272); `DaemonConfig.tenant_id: str | None = None`
  added and folded into `_compute_config_hash` so per-tenant daemons get distinct
  config identities (None default preserves single-tenant operators).

**Golden-path thread-in (binding proof):** `tests/golden_path/test_l0_spine_liveness.py::
TestGoldenPathL0MultiTenant::test_pillar_I_per_tenant_isolated_ledgers_zero_leak` runs
BOTH personas (aiyara + scholarfeed) into per-tenant ledgers resolved by the real
primitives, asserting isolated dirs + zero cross-tenant person_id leak + the funnel
sees each run. `gate.py --require ...` → GREEN. The §5 Pillar I row's full
both-personas-end-to-end-under-the-daemon run is the Week 6 stable-flip.

Test trajectory: the 4 Week-1 "still-a-stub" regression tests in `tests/test_multi_tenant.py`
flip to Week-2 behavioral assertions; 5 coherence stubs un-skip (Weeks 3-6 stay skipped).

### Pre-commit verification

| Claim | Verification command | Output (pasted) |
|---|---|---|
| `init_multi_tenant` keyword-only `shared_install_dir` | `python -c "import inspect,orchestrator.multi_tenant as m;print(inspect.signature(m.init_multi_tenant))"` | `(tenants: 'list[TenantConfig]', *, shared_install_dir: 'Path') -> 'TenantRegistry'` |
| `resolve_per_tenant_ledger_dir` keyword-only `tenant_id` | `…print(inspect.signature(m.resolve_per_tenant_ledger_dir))` | `(base_ledger_dir: 'Path', *, tenant_id: 'str') -> 'Path'` |
| catalog now includes the 6 Pillar I classes | `python -c "import orchestrator.multi_tenant as m,orchestrator.observability as o;print(m.TENANT_NEW_EVENT_CLASSES<=o.EVENT_CLASS_CATALOG)"` | `True` |
| `DaemonConfig.tenant_id` defaults None | `python -c "from orchestrator.daemon import DaemonConfig as D;print(D.__dataclass_fields__['tenant_id'].default)"` | `None` |

## Pillar I Week 3 addendum — container orchestration + Grafana folder isolation (fills the ADR-0072 trajectory slot)

Week 3 ships the OSS bring-up container surface + the per-tenant observability-folder
isolation per the D372 trajectory, threaded into the golden path as the second
executable Pillar I assertion. Following the W2-addendum precedent, the W3 ADR slot is
documented here in ADR-0070 rather than as a separate file.

- **Container artifacts** — `infra/Dockerfile` (pinned `python:3.13-slim`; `PYTHONPATH=/app:/app/orchestrator` mirrors `tests/conftest.py`'s two insertions so production import resolution matches the harness; `CMD python -m orchestrator.daemon`) + `infra/docker-compose.yml` (single-tenant default: `git clone && docker compose up` → one daemon, one container, per ADR-0060 D335 invariant 1).
- **Container entrypoint** — NEW `orchestrator/daemon/__main__.py`: `build_config_from_env()` assembles `DaemonConfig` from `OUTREACH_FACTORY_{LEDGER,VAULT,POLICY}_DIR` + optional `TENANT_ID` (refuse-loud `SystemExit(2)` on a missing required dir); `main()` calls `init_daemon` (production defaults → real migrations + OTel + Prometheus) + `asyncio.run(runner.run())`. The interactive first-run OAuth/first-send stays Week 4 (ADR-0073).
- **Per-tenant container orchestration** — `build_per_tenant_compose_config(registry)` emits one daemon service per tenant, each bind-mounting ONLY its own host ledger/vault/policy/oauth paths to the canonical in-container mounts. Container-surface extension of the D375 invariant (a) zero-cross-tenant-leak.
- **Per-tenant Grafana folder isolation** — `resolve_per_tenant_grafana_folders(registry)` returns `{tenant_id: grafana_folder_uid}`, refuse-loud on a folder-UID collision (mirrors `init_multi_tenant`'s duplicate-tenant_id guard). Observability-surface extension of the same invariant; consumes the `cost.yml` "per-tenant dashboard folders" seam Pillar G reserved.

**Golden-path thread-in (binding proof):** `tests/golden_path/test_l0_spine_liveness.py::TestGoldenPathL0MultiTenant::test_pillar_I_w3_container_and_grafana_isolation` builds the registry from BOTH personas, asserts each daemon service mounts only its own tenant's host subtree (no foreign-tenant segment, pairwise-disjoint host paths) + the two tenants get disjoint Grafana folders. `gate.py --require test_pillar_I_w3_container_and_grafana_isolation` → GREEN.

Test trajectory: 2 coherence stubs un-skip (`test_docker_compose_one_command_up_produces_running_daemon` + `test_grafana_per_tenant_folder_isolates_dashboards`); Weeks 4-6 stay skipped.

### Pre-commit verification

| Claim | Verification command | Output (pasted) |
|---|---|---|
| `build_per_tenant_compose_config` signature | `python -c "import inspect,orchestrator.multi_tenant as m;print(inspect.signature(m.build_per_tenant_compose_config))"` | `(registry: 'TenantRegistry', *, image: 'str' = 'outreach-factory:latest') -> 'dict'` |
| `resolve_per_tenant_grafana_folders` signature | `…print(inspect.signature(m.resolve_per_tenant_grafana_folders))` | `(registry: 'TenantRegistry') -> 'dict[str, str]'` |
| entrypoint builder signature | `python -c "import inspect,orchestrator.daemon.__main__ as e;print(inspect.signature(e.build_config_from_env))"` | `() -> 'DaemonConfig'` |
| Dockerfile CMD runs the daemon module | `grep -c 'orchestrator.daemon' infra/Dockerfile` | `≥1` |

## Pillar I Week 5 addendum — CI bring-up + per-tenant SLO surface (fills the ADR-0074 trajectory slot)

Week 5 ships the repo's **first CI surface** + the per-tenant SLO surface per the D372/D376 trajectory, threaded into the golden path as the third executable Pillar I assertion. Following the W2/W3-addendum precedent, the W5 ADR slot is documented here in ADR-0070 rather than as a separate file. This closes the Pillar A Week 6 **§D3 deferral** (ADR-0006 §"CI enforcement of the price-update == ADR-amendment discipline": *"that decision belongs in Pillar I where the OSS-hardening week range owns the CI bring-up"*).

- **CI cochange-discipline primitive** — NEW `orchestrator/ci/` package: `check_cochange_discipline(changed_paths, *, diffs=None, pairs=COCHANGE_PAIRS)` returns a `DisciplineViolation` per pair whose source changed without its governing ADR. `COCHANGE_PAIRS` is the R031-shape closed-set seeding the `budget.py:COST_RATES_USD` ↔ ADR-0006 pair (ADR-0006 §D3's generalization to "any constant + ADR pair"). Strict file-level mode honors D375 invariant 5's `--name-only` shape; the optional `diffs` map applies ADR-0006 §D3's "change to the `COST_RATES_USD` block" content refinement so an unrelated `budget.py` edit does not false-positive-refuse. Refuse-loud per ADR-0001 D2 + the W10-11 follow-up P1-1 operator-readable-error discipline (message names the source + ADR + how to resolve; NO traceback).
- **CI workflow** — NEW `.github/workflows/ci.yml` (the first `.github/` artifact): a `golden-path-gate` job runs `gate.py --full` and a `cochange-discipline` job runs `python -m orchestrator.ci` (a thin git-plumbing wrapper at `orchestrator/ci/__main__.py` over the load-bearing primitive). Until now L0 ran locally/pre-commit (GOLDEN-PATH-HARNESS §10.4); the gate is now CI-blocking.
- **Per-tenant SLO surface** — `collect_per_tenant_slo_violations(registry, per_tenant_ledgers, *, since_window, now=None, slo_config=None, detect_fn=None)` runs the Pillar G `detect_slo_violations` once per tenant against that tenant's OWN ledger → `{tenant_id: [SLOViolation, …]}`. Observability-surface extension of D375 invariant (a): zero cross-tenant aggregation. The `detect_fn` TEST-ONLY seam (ADR-0039 `embed_fn`/`retrieve_fn` precedent) keeps the package import-light via lazy import. The privacy invariant holds by construction — `SLOViolation` carries only `slo_name`/`slo_threshold`/`observed_value`/`channel`/`window_seconds`, no per-Person field.
- **R040 + R041 regression-barriers** — the golden-path W5 test pins R040 (per-tenant ledger dirs are disjoint subtrees under the shared base → no aliasing/write-contention) + R041 (`daemon_started` surfaces `startup_seconds` → per-tenant startup latency is operator-visible per the Pillar H Grafana panel).

**Golden-path thread-in (binding proof):** `tests/golden_path/test_l0_spine_liveness.py::TestGoldenPathL0MultiTenant::test_pillar_I_w5_ci_discipline_and_per_tenant_slo_isolation` builds the registry from BOTH personas, scores per-tenant SLOs over each tenant's own ledger (isolation proven via the `detect_fn` seam receiving each tenant's own ledger object), asserts the CI discipline refuses-loud on an unaccompanied `budget.py` change, and pins R040 + R041. `gate.py --require test_pillar_I_w5_ci_discipline_and_per_tenant_slo_isolation` → GREEN.

Test trajectory: 2 coherence rows un-skip (`test_ci_fails_unaccompanied_pricing_table_change` + `test_per_tenant_slo_surfaces_preserve_privacy_invariant`); Weeks 4 (human-gated OAuth) + 6 (Stable flip) stay skipped.

### Pre-commit verification

| Claim | Verification command | Output (pasted) |
|---|---|---|
| `check_cochange_discipline` signature | `python -c "import inspect,orchestrator.ci as c;print(inspect.signature(c.check_cochange_discipline))"` | `(changed_paths: 'Iterable[str]', *, diffs: 'Mapping[str, str] | None' = None, pairs: 'Sequence[CoChangePair]' = (…COST_RATES_USD…)) -> 'tuple[DisciplineViolation, ...]'` |
| `collect_per_tenant_slo_violations` signature | `python -c "import inspect,orchestrator.multi_tenant as m;print(inspect.signature(m.collect_per_tenant_slo_violations))"` | `(registry: 'TenantRegistry', per_tenant_ledgers: "Mapping[str, 'object']", *, since_window, now=None, slo_config=None, detect_fn=None) -> 'dict[str, list]'` |
| R041 surface — `daemon_started` carries `startup_seconds` | `python -c "import inspect,orchestrator.daemon as d;print(inspect.signature(d.build_daemon_started_payload))"` | `(pid: 'int', version: 'str', config_hash: 'str', startup_seconds: 'float') -> 'dict[str, Any]'` |
| `COCHANGE_PAIRS` pins budget↔ADR-0006 (R031-shape) | `python -c "from orchestrator.ci import COCHANGE_PAIRS;print({p.source:p.adr for p in COCHANGE_PAIRS})"` | `{'orchestrator/policy/budget.py': 'docs/adr/0006-budget-rules-and-cost-events.md'}` |
| CI workflow invokes the gate + the check | `grep -c 'orchestrator.ci\|gate.py' .github/workflows/ci.yml` | `6` |

## Pillar I Week 4 addendum — init wizard + Gmail OAuth flow (fills the ADR-0073 trajectory slot)

Week 4 ships the init-wizard body — the zero-to-test-send OSS bring-up surface per the D372/D376 trajectory, threaded into the golden path as the fourth executable Pillar I assertion. It lands AFTER W5 because its OAuth round-trip was human-gated (GOLDEN-PATH-HARNESS §9): the human completed real Gmail consent + a real first-send once (2026-05-28; authenticated `you@example.com`, refresh token at `~/.outreach-factory/credentials/gmail_token.json`). With that precondition met, the body is testable headlessly via a `gmail_authenticate_fn` seam + a deterministic-clock `now` — the loop does NOT re-run real OAuth or real sends. Following the W2/W3/W5-addendum precedent, the W4 ADR slot is documented here in ADR-0070 rather than as a separate file.

- **Init wizard body** — `run_init_wizard(config, *, gmail_authenticate_fn, led=None, first_prospect=None, test_send_to=None, now=None, migration_apply_fn=None, enroll_fn=None)` walks the ordered `INIT_WIZARD_STEPS` (`gmail_oauth` → `vault_setup` → `first_prospect` → `test_send`). `gmail_authenticate_fn` is the OAuth seam (production: `GmailClient.authenticate`; tests: a FakeGmail per `tests/test_reconcile.py:78` + a `send_email`). The `test_send` step sends to the operator's OWN address (send-to-self, so the wizard never spams a prospect) and reads it back to confirm the round-trip. `vault_setup` consumes the per-tenant `MigrationRunner` (surface-audit Concern B2) via the `migration_apply_fn` seam.
- **Per-step refuse-loud (R042)** — each step raises `InitWizardError(step=…)` with an operator-readable message naming the failing step (missing `gmail.send` scope; auth returns no `sender_email`; send raises; send does not round-trip), NO Python traceback per the W10-11 follow-up P1-1 operator-facing-error discipline.
- **`init_wizard_completed` emit** — `build_init_wizard_completed_payload(*, tenant_id, completed_at_ts, wizard_steps)` builds the privacy-clean payload (`tenant_id` + `completed_at_ts` + `wizard_steps` + `_emitted_by="multi_tenant"`; NO per-Person field per I8 + D375 invariant (a)), stamped at the factory boundary per the Pillar H `build_*_payload` precedent; the wizard appends `{"type": "init_wizard_completed", **payload}` after all four steps pass.
- **Idempotence (D375 invariant (c))** — the wizard reads the tenant's ledger FIRST; a prior `init_wizard_completed` for the tenant makes the whole call a NO-OP (no re-auth, no re-created dirs, no re-send, no second emit), underpinned by the Pillar B migration framework's idempotence per ADR-0009 D9.

**Golden-path thread-in (binding proof):** `tests/golden_path/test_l0_spine_liveness.py::TestGoldenPathL0MultiTenant::test_pillar_I_w4_init_wizard_zero_to_test_send` builds the registry from BOTH personas, runs the wizard zero-to-test-send for the aiyara tenant under the FakeGmail seam + the deterministic clock, asserts `init_wizard_completed` lands in aiyara's ledger (4 steps), the scholarfeed ledger stays untouched (cross-tenant isolation), and a re-run is a NO-OP (idempotence). `gate.py --require test_pillar_I_w4_init_wizard_zero_to_test_send` → GREEN.

Test trajectory: 2 coherence rows un-skip (`test_init_wizard_takes_new_user_from_zero_to_test_send` + `test_init_wizard_idempotent_on_rerun`); Week 6 (Stable flip) stays skipped.

### Pre-commit verification

| Claim | Verification command | Output (pasted) |
|---|---|---|
| `run_init_wizard` signature | `python -c "import inspect,orchestrator.multi_tenant as m;print(inspect.signature(m.run_init_wizard))"` | `(config: 'TenantConfig', *, gmail_authenticate_fn: "Callable[[], 'object']", led: "'object \| None'" = None, first_prospect: 'Mapping[str, str] \| None' = None, test_send_to: 'str \| None' = None, now: 'datetime \| None' = None, migration_apply_fn: 'Callable[[], None] \| None' = None, enroll_fn: …) -> 'dict'` |
| `build_init_wizard_completed_payload` signature | `…print(inspect.signature(m.build_init_wizard_completed_payload))` | `(*, tenant_id: 'str', completed_at_ts: 'str', wizard_steps: 'Sequence[str]') -> 'dict'` |
| `INIT_WIZARD_STEPS` ordered four | `python -c "import orchestrator.multi_tenant as m;print(m.INIT_WIZARD_STEPS)"` | `('gmail_oauth', 'vault_setup', 'first_prospect', 'test_send')` |
| `vault_setup` consumes the real `MigrationRunner.apply` | `python -c "import inspect;from orchestrator.migrations.runner import MigrationRunner as R;print(inspect.signature(R.apply))"` | `(self, category: 'MigrationCategory \| None' = None) -> 'list[MigrationResult]'` |
