"""Pillar I Week 1 + Week 1 follow-up — multi-tenant + OSS hardening
foundation (per ADR-0070 D371-D376 + the Pillar I Week 1 follow-up
addendum closing THREE P3 narrative-drift findings per the per-week-
reviewer pattern). Week 1 ships the **package shape** — frozen
dataclasses, closed-sets, and primitive signatures raising
:exc:`NotImplementedError`; Weeks 2-6 ship the bodies per ADR-0070 D376's
per-week trajectory table.

**Pillar I Week 1 follow-up** per the per-week-reviewer's independent
review of the W1 main commit `264f13d`: 0 P1 + 0 P2 + 3 P3 + 6 REFUTED
addressed — the **FIRST Pillar I ADR-vs-actual-impl drift** caught by
the per-week-reviewer's cross-pillar back-audit discipline extending
the Pillar H TEN consecutive catches (per the W12 follow-up P3-1
closure) to **ELEVEN consecutive weeks across the Pillar H + Pillar I
trajectory**. P3-1 closure — "18 P3 concerns" narrative claim
corrected to "15 P3 + 1 Deferred" (off-by-three narrative drift); P3-2
closure — "NINE consecutive ADR-vs-actual-impl drift catches" stale
count corrected to "TEN" per the W12 follow-up P3-1 closure; P3-3
closure — discipline-counts narrative drift in HANDOFF lines 80-82
standardized to post-W12-follow-up framing (THIRTY-EIGHT/THIRTY-FIVE/
THIRTY-SEVEN at Pillar I Week 1 close; THIRTY-NINE/THIRTY-SIX/THIRTY-
EIGHT at Pillar I Week 1 follow-up close). See
``docs/adr/0070-pillar-i-foundation.md`` §"Pillar I Week 1 follow-up
addendum" for the full closure narrative.

Per the per-pillar-foundation precedent (Pillar D ADR-0025 + Pillar E
ADR-0032 + Pillar F ADR-0038 + Pillar G ADR-0050 + Pillar H ADR-0060 —
each pillar's Week 1 ships module shape + closed-sets + signatures +
cross-pillar surface audit + exit-criterion vehicle scope + load-bearing
invariants + per-week trajectory table). This module is the canonical
target Weeks 2-6 satisfy.

The public surface — see :data:`__all__`:

* :class:`TenantConfig` — frozen dataclass naming per-tenant configuration
  (``tenant_id`` + per-tenant vault / ledger / policy directories +
  per-tenant OAuth token paths + per-tenant Grafana folder).
* :class:`TenantRegistry` — frozen dataclass aggregating multiple
  :class:`TenantConfig` instances (``tenants`` mapping ``tenant_id ->
  TenantConfig``); the multi-tenant operator's set-once at process start.
* :data:`TENANT_LIFECYCLE_STATES` — closed-set of the FOUR per-tenant
  lifecycle states (``provisioning`` / ``active`` / ``paused`` /
  ``deprovisioning``).
* :data:`TENANT_NEW_EVENT_CLASSES` — closed-set of the SIX new Pillar I
  event classes (``tenant_provisioned`` + ``tenant_paused`` +
  ``tenant_resumed`` + ``tenant_deprovisioned`` + ``init_wizard_completed``
  + ``auth_token_refreshed``).
* :data:`TENANT_OAUTH_TOKEN_SCOPES` — closed-set of OAuth token scopes
  Pillar I per-tenant operators provision (``gmail.send`` /
  ``gmail.readonly`` / ``linkedin.invite`` / ``linkedin.dm`` /
  ``twitter.dm`` / ``calendar.book``).
* :func:`init_multi_tenant` — instantiate :class:`TenantRegistry` from a
  list of :class:`TenantConfig` (Week 1 signature; **Week 2 body** per
  ADR-0071).
* :func:`resolve_per_tenant_ledger_dir` — resolve per-tenant ledger
  directory from a base path + ``tenant_id`` per D375 invariant (a) —
  per-tenant isolation (Week 1 signature; **Week 2 body** per ADR-0071).
* :func:`resolve_per_tenant_policy_dir` — resolve per-tenant policy
  directory from a base path + ``tenant_id`` (Week 1 signature; **Week 2
  body** per ADR-0071).

**Week 3** (ADR-0072 trajectory slot; see the ADR-0070 "Pillar I Week 3
addendum") ships the OSS bring-up container surface + per-tenant
observability isolation:

* :func:`build_per_tenant_compose_config` — generate a docker-compose
  manifest with one daemon service per tenant, each bind-mounting ONLY
  its own host directories (container-surface per-tenant isolation).
* :func:`resolve_per_tenant_grafana_folders` — resolve the per-tenant
  Grafana folder UID map; refuse-loud on a folder-UID collision
  (observability-surface per-tenant isolation).
* :data:`DEFAULT_DAEMON_IMAGE` — the shared OCI image tag the per-tenant
  daemon containers run (built once from ``infra/Dockerfile``).

**Week 5** (ADR-0074 trajectory slot; see the ADR-0070 "Pillar I Week 5
addendum") ships the CI bring-up surface + the per-tenant SLO surface:

* :func:`collect_per_tenant_slo_violations` — run the Pillar G SLO violation
  detector once per tenant against that tenant's OWN ledger; returns
  ``{tenant_id: [SLOViolation, …]}`` with zero cross-tenant aggregation
  (observability-surface extension of D375 invariant (a)) + the privacy
  invariant preserved (``SLOViolation`` carries no per-Person field).
* The CI surface itself lives in :mod:`orchestrator.ci` (the repo's first CI
  artifact) + ``.github/workflows/ci.yml`` — the price-update == ADR-amendment
  discipline check closing the Pillar A Week 6 §D3 deferral per ADR-0006.

**Pillar I load-bearing invariants** per ADR-0070 D375 (five invariants,
extending Pillar G Week 1 four invariants per ADR-0050 D276 + Pillar H
Week 1 four invariants per ADR-0060 D335):

1. **Per-tenant-isolation** — each tenant's daemon process is fully
   isolated; no cross-tenant data leakage at any surface (ledger + vault
   + Grafana + OAuth tokens). The :func:`resolve_per_tenant_ledger_dir`
   + :func:`resolve_per_tenant_policy_dir` primitives produce per-tenant
   directory paths; per-tenant Grafana folders isolate dashboards per
   Pillar G Week 4 trajectory.
2. **Per-tenant atomicity-preservation-across-process-boundary** —
   extends Pillar H D335 invariant 2 per-tenant; one daemon process per
   tenant (per ADR-0060 D335 invariant 1); per-tenant ledger directories
   preserve the append-only contract per I2 per-tenant.
3. **Init-wizard idempotence** — running the init wizard twice on the
   same user produces a NO-OP (idempotent per the existing Pillar B
   migration framework's precedent per ADR-0009 D9). The
   ``init_wizard_completed`` event class signals first-run completion;
   re-runs MAY emit but MUST NOT re-create OAuth tokens or vault
   directories.
4. **OSS-bring-up reproducibility** — ``git clone && docker compose up
   && doctor.py`` on a fresh VM produces a byte-identical-deterministic
   working system per ADR-0031 D140. The docker-compose container image
   + the doctor preflight + the init wizard form the canonical OSS
   bring-up surface; operators clone + compose up + doctor + send.
5. **CI bring-up reliability** — the CI surface fails reliably on any
   unaccompanied pricing-table change per ADR-0006 §"CI enforcement of
   the price-update == ADR-amendment discipline" + the Pillar A §D3
   deferred check landing at Pillar I Week 5 per the trajectory.

Per-pillar framework dependencies (compounded across Pillar A-H):

* **Pillar A** policy engine — per-tenant policy YAML files; the daemon's
  pre-flight gate consults the per-tenant policy state.
* **Pillar B** migration framework — per-tenant ledger directory schema
  + per-tenant vault schema; the init wizard runs migrations at first
  launch per ADR-0009 D9's idempotent auto-apply contract.
* **Pillar C** per-channel two-phase commit — per-tenant per-channel
  rate-limits; the per-channel intent/confirmed shape per ADR-0014 D33
  preserves per-tenant.
* **Pillar D** reconcile loop — per-tenant Pass A through O; each tenant's
  reconcile runs against its own ledger directory.
* **Pillar E** discovery dedup + cache + tier + lineage primitives —
  per-tenant cache; per-tenant tier weights.
* **Pillar F** voice corpus + Layer 5 backstop — per-tenant corpus
  directories; per-tenant voice-fidelity thresholds.
* **Pillar G** observability — per-tenant SLO surfaces + per-tenant
  Grafana folder isolation; the per-event-class catalog extends with the
  SIX Pillar I event classes per :data:`TENANT_NEW_EVENT_CLASSES`.
* **Pillar H** daemon — one daemon process per tenant per ADR-0060 D335
  invariant 1; per-tenant ``DaemonConfig.tenant_id`` field; per-tenant
  EventClassIndex + PersonEventIndex; per-tenant crash-recovery synthesis.

**Trajectory commitment — single-tenant-first-then-multi-tenant**
per ADR-0050 D276(d) + ADR-0060 D335 invariant 1 + ADR-0070 D371:

* **Single-tenant** is the framework default at Pillar I Week 1.
  Operators running one daemon per machine (or per container) get the
  full Pillar A-H feature set with ZERO operator-action-required at
  Pillar I Week 1 upgrade (the Pillar I extensions are opt-in via the
  :class:`TenantRegistry` set-once at process start).
* **Multi-tenant fan-out** (Pillar I scope) wires one daemon process per
  tenant. Per-tenant ledger directories isolate each tenant's event
  stream. Per-tenant policy YAML files. Per-tenant Grafana folder
  isolation. Per-tenant OAuth tokens.

See ``docs/adr/0070-pillar-i-foundation.md`` for the full Week 1 ADR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


#: Closed-set of the FOUR per-tenant lifecycle states per ADR-0070 D371.
#:
#: Each tenant transitions through:
#:
#: * ``"provisioning"`` — tenant is being set up; the init wizard is
#:   running OAuth flow + creating vault directories + applying migrations;
#:   the per-tenant daemon is NOT yet emitting events.
#: * ``"active"`` — tenant's per-tenant daemon is running; per-tenant
#:   reconcile passes are dispatching; operators see per-tenant events
#:   in the per-tenant ledger.
#: * ``"paused"`` — operator-deliberate pause without process exit per
#:   ADR-0060 §Downstream pillar impact's pre-reserved state; per-tenant
#:   daemon's per-stage worker pool stops accepting new tasks; in-flight
#:   tasks complete; ``tenant_paused`` event emits.
#: * ``"deprovisioning"`` — tenant is being removed; per-tenant daemon
#:   exits gracefully; per-tenant ledger + vault MAY be archived per
#:   the operator's data retention policy; ``tenant_deprovisioned`` event
#:   emits.
#:
#: The Pillar I Week 2 commit ships the per-tenant lifecycle state
#: machine body; Pillar I Week 1 pins the closed-set contract.
TENANT_LIFECYCLE_STATES: frozenset[str] = frozenset({
    "provisioning",
    "active",
    "paused",
    "deprovisioning",
})


#: Closed-set of the SIX new Pillar I event classes per ADR-0070 D371 +
#: the OSS bring-up trajectory.
#:
#: Mirrors the Pillar G + Pillar H closed-set discipline per ADR-0050
#: D272 + ADR-0060 D331 — Pillar I Week 2 extends
#: ``observability.EVENT_CLASS_CATALOG`` with these six classes; the
#: per-call ``collect_event_class_snapshots`` aggregates them uniformly
#: with prior-pillar event classes per ADR-0050 D272.
#:
#: * ``tenant_provisioned`` — emit on tenant lifecycle ``provisioning ->
#:   active`` transition; payload: ``tenant_id`` + ``provisioned_at_ts``
#:   + ``_emitted_by="multi_tenant"``.
#: * ``tenant_paused`` — emit on operator-deliberate pause; payload:
#:   ``tenant_id`` + ``paused_at_ts`` + ``reason`` (operator-supplied)
#:   + ``_emitted_by="multi_tenant"``.
#: * ``tenant_resumed`` — emit on operator-deliberate resume after pause;
#:   payload: ``tenant_id`` + ``resumed_at_ts`` + ``paused_duration_seconds``
#:   + ``_emitted_by="multi_tenant"``.
#: * ``tenant_deprovisioned`` — emit on tenant removal; payload:
#:   ``tenant_id`` + ``deprovisioned_at_ts`` + ``data_archived`` (bool)
#:   + ``_emitted_by="multi_tenant"``.
#: * ``init_wizard_completed`` — emit on init wizard first-run success;
#:   payload: ``tenant_id`` + ``completed_at_ts`` + ``wizard_steps``
#:   (list of completed step names) + ``_emitted_by="multi_tenant"``.
#: * ``auth_token_refreshed`` — emit on per-channel OAuth token refresh;
#:   payload: ``tenant_id`` + ``token_scope`` (member of
#:   :data:`TENANT_OAUTH_TOKEN_SCOPES`) + ``refreshed_at_ts``
#:   + ``_emitted_by="multi_tenant"``.
#:
#: The Pillar I Week 2 commit extends
#: ``observability.EVENT_CLASS_CATALOG`` to include these six classes
#: per the per-pillar mirror constants parity discipline; the Week 1
#: catalog regression-barrier test pins disjoint-from-EVENT_CLASS_CATALOG-
#: at-Week-1.
TENANT_NEW_EVENT_CLASSES: frozenset[str] = frozenset({
    "tenant_provisioned",
    "tenant_paused",
    "tenant_resumed",
    "tenant_deprovisioned",
    "init_wizard_completed",
    "auth_token_refreshed",
})


#: Closed-set of OAuth token scopes per-tenant operators provision per
#: ADR-0070 D371 + the per-channel scope discipline established at the
#: Pillar C per-channel two-phase commit per ADR-0014 D33.
#:
#: * ``"gmail.send"`` — Gmail send scope (per Pillar C Week 1 + Phase
#:   5.5 Gmail OAuth flow).
#: * ``"gmail.readonly"`` — Gmail read scope (per the inbox reconcile
#:   passes per ADR-0014/0017 — bounce + reply detection).
#: * ``"linkedin.invite"`` — LinkedIn invite scope (per Pillar C Week 2
#:   per ADR-0017).
#: * ``"linkedin.dm"`` — LinkedIn DM scope (per Pillar C Week 3 per
#:   ADR-0018).
#: * ``"twitter.dm"`` — Twitter DM scope (per Pillar C Week 5).
#: * ``"calendar.book"`` — Google Calendar scope (per Pillar C Week 6
#:   per ADR-0024).
#:
#: The :data:`TenantConfig.oauth_token_scopes` field carries a subset of
#: this closed-set per operator's per-channel adoption. Refuse-loud
#: rules at :class:`TenantConfig.__post_init__` reject scopes outside
#: this closed-set (Week 2 body lands the validation).
TENANT_OAUTH_TOKEN_SCOPES: frozenset[str] = frozenset({
    "gmail.send",
    "gmail.readonly",
    "linkedin.invite",
    "linkedin.dm",
    "twitter.dm",
    "calendar.book",
})


#: Canonical ``tenant_id`` pattern per ADR-0070 D371: lowercase-initial,
#: alphanumerics + ``_`` + ``-``, max 63 chars. The pattern is the
#: load-bearing per-tenant-isolation guard per D375 invariant (a) — it
#: bars path separators (``/``), parent refs (``..``), leading digits,
#: and uppercase, so per-tenant directory paths derived via
#: :func:`resolve_per_tenant_ledger_dir` / :func:`resolve_per_tenant_policy_dir`
#: cannot traverse outside their base directory.
_TENANT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")


def _validate_tenant_id(tenant_id: str) -> None:
    """Refuse-loud (``ValueError``) if ``tenant_id`` is not a non-empty
    string matching :data:`_TENANT_ID_PATTERN` per ADR-0070 D371 + the
    framework's refuse-loud convention per ADR-0001 D2."""

    if not isinstance(tenant_id, str) or not _TENANT_ID_PATTERN.match(tenant_id):
        raise ValueError(
            f"tenant_id {tenant_id!r} must be a non-empty string matching "
            r"'^[a-z][a-z0-9_-]{0,62}$'"
            " (lowercase-initial; alphanumerics + '_' + '-'; max 63 chars) "
            "per ADR-0070 D371. The pattern bars path separators + parent "
            "refs so per-tenant directory resolution cannot traverse outside "
            "the base dir (D375 invariant (a) per-tenant-isolation)."
        )


@dataclass(frozen=True)
class TenantConfig:
    """Per-tenant configuration per ADR-0070 D371 — Week 1 dataclass shape.

    Frozen dataclass naming per-tenant identity + per-tenant directory
    paths + per-tenant OAuth scope provisioning. The :func:`init_multi_tenant`
    primitive (Week 2 body) accepts a list of these + constructs a
    :class:`TenantRegistry`.

    Fields:

    * ``tenant_id`` — operator-deliberate per-tenant identifier; MUST be
      a non-empty string matching ``^[a-z][a-z0-9_-]{0,62}$`` (Week 2 body
      validates). Per-tenant directory paths derive from ``tenant_id``;
      collisions across tenants violate D375 invariant (a) per-tenant-
      isolation.
    * ``vault_dir`` — per-tenant Obsidian vault directory path; isolates
      per-tenant Person notes + touch notes + research dossiers + drafts.
    * ``ledger_dir`` — per-tenant ledger directory path; isolates per-
      tenant event stream per D375 invariant (b) per-tenant atomicity-
      preservation.
    * ``policy_dir`` — per-tenant policy YAML directory path; isolates
      per-tenant cooldown / suppression / sending-window / budget rules
      per Pillar A's policy engine.
    * ``oauth_token_path`` — per-tenant OAuth token file path; isolates
      per-tenant Gmail / LinkedIn / Twitter / Calendar credentials.
    * ``oauth_token_scopes`` — frozenset subset of
      :data:`TENANT_OAUTH_TOKEN_SCOPES` naming which scopes the operator
      provisioned for this tenant.
    * ``grafana_folder_uid`` — per-tenant Grafana folder UID for
      dashboard isolation per Pillar G Week 4's Grafana-as-code surface.
    * ``lifecycle_state`` — current per-tenant lifecycle state; member
      of :data:`TENANT_LIFECYCLE_STATES`; defaults to ``"provisioning"``.

    The frozen invariant matches the Pillar H :class:`DaemonConfig` +
    Pillar G :class:`MetricSnapshot` precedents — operators construct
    once + the registry validates + the daemon process boundary
    consumes.

    **Privacy invariant** per I8 + ADR-0050 D276(b) + ADR-0058 D323 +
    ADR-0060 D335 + D375 invariant (a) extension: the per-tenant
    surfaces MUST preserve the per-tenant isolation contract — tenant
    A's :class:`TenantConfig` MUST NOT leak through to tenant B's
    operator-visible surfaces.

    Week 2 body validates: ``tenant_id`` format + ``oauth_token_scopes``
    subset of :data:`TENANT_OAUTH_TOKEN_SCOPES` + ``lifecycle_state``
    member of :data:`TENANT_LIFECYCLE_STATES` + path field absoluteness.
    """

    tenant_id: str
    vault_dir: Path
    ledger_dir: Path
    policy_dir: Path
    oauth_token_path: Path
    oauth_token_scopes: frozenset[str]
    grafana_folder_uid: str
    lifecycle_state: str = "provisioning"

    def __post_init__(self) -> None:
        """Validate the per-tenant config per ADR-0070 D371 — Week 2 body.

        Refuse-loud (``ValueError``) per the framework's convention per
        ADR-0001 D2 on: ``tenant_id`` format, ``oauth_token_scopes``
        outside :data:`TENANT_OAUTH_TOKEN_SCOPES`, ``lifecycle_state``
        outside :data:`TENANT_LIFECYCLE_STATES`, and non-absolute path
        fields (per-tenant directory isolation per D375 invariant (a)
        requires absolute paths so per-tenant subtrees never alias).
        The frozen invariant is preserved — this validates only (no
        field mutation)."""

        _validate_tenant_id(self.tenant_id)

        bad_scopes = set(self.oauth_token_scopes) - TENANT_OAUTH_TOKEN_SCOPES
        if bad_scopes:
            raise ValueError(
                f"TenantConfig.oauth_token_scopes contains scopes outside "
                f"TENANT_OAUTH_TOKEN_SCOPES: {sorted(bad_scopes)}. Allowed: "
                f"{sorted(TENANT_OAUTH_TOKEN_SCOPES)}."
            )

        if self.lifecycle_state not in TENANT_LIFECYCLE_STATES:
            raise ValueError(
                f"TenantConfig.lifecycle_state {self.lifecycle_state!r} is not "
                f"a member of TENANT_LIFECYCLE_STATES "
                f"{sorted(TENANT_LIFECYCLE_STATES)}."
            )

        for field_name in ("vault_dir", "ledger_dir", "policy_dir", "oauth_token_path"):
            value = getattr(self, field_name)
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError(
                    f"TenantConfig.{field_name} must be an absolute Path; got "
                    f"{value!r}. Per-tenant directory isolation per D375 "
                    f"invariant (a) requires absolute paths."
                )


@dataclass(frozen=True)
class TenantRegistry:
    """Multi-tenant registry per ADR-0070 D371 — Week 1 dataclass shape.

    Frozen dataclass aggregating multiple :class:`TenantConfig` instances.
    The multi-tenant operator constructs ONE registry at process start
    via :func:`init_multi_tenant` (Week 2 body); the per-tenant daemon
    fan-out consumes the registry to spawn one daemon process per tenant.

    Fields:

    * ``tenants`` — mapping ``tenant_id -> TenantConfig``; immutable post-
      construction per the frozen invariant + the operator-deliberate
      set-once-at-process-start posture per ADR-0052 D286 + ADR-0053
      D288 + ADR-0054 D298 framework-neutrality contract.
    * ``shared_install_dir`` — the framework's install directory
      (containing the orchestrator/ source tree + the docker-compose
      manifest); shared across all tenants per the OSS bring-up
      trajectory.

    The registry's structural commitment per D375 invariant (a) per-
    tenant-isolation: querying ``registry.tenants[tenant_id]`` returns
    EXACTLY ONE :class:`TenantConfig` for that tenant; cross-tenant
    queries are NOT supported at the registry surface (the per-tenant
    daemon process boundary enforces isolation at runtime).
    """

    tenants: Mapping[str, TenantConfig]
    shared_install_dir: Path


def init_multi_tenant(
    tenants: list[TenantConfig],
    *,
    shared_install_dir: Path,
) -> TenantRegistry:
    """Construct a :class:`TenantRegistry` from a list of
    :class:`TenantConfig` instances per ADR-0070 D371 — Week 1 signature;
    Week 2 body per ADR-0071.

    Pre-flight checks (Week 2 body):

    1. Validate each :class:`TenantConfig` per its ``__post_init__``-
       equivalent invariants (``tenant_id`` format + ``oauth_token_scopes``
       subset + ``lifecycle_state`` member + path absoluteness).
    2. Validate no duplicate ``tenant_id`` across the list (refuse-loud
       on collision per the framework's refuse-loud convention per ADR-
       0001 D2).
    3. Validate ``shared_install_dir`` is absolute + exists.
    4. Construct the immutable :class:`TenantRegistry` with the
       canonical mapping ``tenant_id -> TenantConfig``.

    Returns the constructed registry; the operator's set-once at process
    start.
    """

    # 1. Each TenantConfig validated its own field invariants at
    #    construction (TenantConfig.__post_init__): tenant_id format +
    #    oauth_token_scopes subset + lifecycle_state member + path
    #    absoluteness. By the time they reach here they are well-formed.
    # 2. Refuse-loud on duplicate tenant_id — collisions would alias
    #    per-tenant directory paths, violating D375 invariant (a).
    seen: dict[str, TenantConfig] = {}
    for cfg in tenants:
        if cfg.tenant_id in seen:
            raise ValueError(
                f"init_multi_tenant: duplicate tenant_id {cfg.tenant_id!r} — "
                f"each tenant_id must be unique across the registry per D375 "
                f"invariant (a) per-tenant-isolation (collisions would alias "
                f"per-tenant directory paths)."
            )
        seen[cfg.tenant_id] = cfg

    # 3. shared_install_dir absolute + exists (the framework install
    #    directory containing the orchestrator/ source tree + the
    #    docker-compose manifest, per the OSS bring-up trajectory).
    if not isinstance(shared_install_dir, Path) or not shared_install_dir.is_absolute():
        raise ValueError(
            f"init_multi_tenant: shared_install_dir must be an absolute Path; "
            f"got {shared_install_dir!r}."
        )
    if not shared_install_dir.exists():
        raise ValueError(
            f"init_multi_tenant: shared_install_dir {shared_install_dir} does "
            f"not exist (the framework install directory must exist per the "
            f"OSS bring-up trajectory per ADR-0070 D375 invariant (d))."
        )

    # 4. Construct the immutable registry with the canonical mapping.
    return TenantRegistry(tenants=dict(seen), shared_install_dir=shared_install_dir)


def resolve_per_tenant_ledger_dir(
    base_ledger_dir: Path,
    *,
    tenant_id: str,
) -> Path:
    """Resolve per-tenant ledger directory from a base path + ``tenant_id``
    per ADR-0070 D371 + D375 invariant (a) — Week 1 signature; Week 2
    body per ADR-0071.

    The per-tenant ledger directory is the canonical isolation boundary
    for the per-tenant event stream per D375 invariant (b) per-tenant
    atomicity-preservation. Each tenant's daemon process appends to its
    own ledger directory; cross-tenant ledger access is NOT supported.

    Returns a :class:`Path` of the form ``base_ledger_dir / tenant_id``;
    the per-tenant directory's existence + writability is verified at
    the init wizard surface (Pillar I Week 4 per ADR-0073).
    """

    # tenant_id is validated FIRST — the format guard bars path
    # separators + parent refs so the resolved path cannot traverse
    # outside base_ledger_dir (the load-bearing per-tenant-isolation
    # guard per D375 invariant (a)).
    _validate_tenant_id(tenant_id)
    return base_ledger_dir / tenant_id


def resolve_per_tenant_policy_dir(
    base_policy_dir: Path,
    *,
    tenant_id: str,
) -> Path:
    """Resolve per-tenant policy directory from a base path + ``tenant_id``
    per ADR-0070 D371 + D375 invariant (a) — Week 1 signature; Week 2
    body per ADR-0071.

    The per-tenant policy directory contains per-tenant cooldown /
    suppression / sending-window / budget YAML files per Pillar A's
    policy engine; per-tenant operators set per-tenant rules.

    Returns a :class:`Path` of the form ``base_policy_dir / tenant_id``.
    """

    # tenant_id format guard FIRST per D375 invariant (a) (see
    # resolve_per_tenant_ledger_dir) — the per-tenant policy subtree
    # cannot traverse outside base_policy_dir.
    _validate_tenant_id(tenant_id)
    return base_policy_dir / tenant_id


# --------------------------------------------------------------------------
# Pillar I Week 3 (ADR-0072) — per-tenant container orchestration + per-tenant
# Grafana folder isolation. Both extend the W2 zero-cross-tenant-leak invariant
# (proven for ledgers by `test_pillar_I_per_tenant_isolated_ledgers_zero_leak`)
# to the container-runtime surface and the observability-dashboard surface.
# --------------------------------------------------------------------------

#: Default OCI image tag the per-tenant daemon containers run. The image is
#: built once from ``infra/Dockerfile`` and shared across all tenants; per-
#: tenant isolation is at the volume-mount + env grain, not the image.
DEFAULT_DAEMON_IMAGE: str = "outreach-factory:latest"

#: Canonical in-container mount points. Each tenant's host directories (which
#: ARE per-tenant-isolated by `resolve_per_tenant_*_dir`) bind-mount to these
#: fixed in-container paths, so the daemon entrypoint reads the same env in
#: every container regardless of the host layout.
_CONTAINER_LEDGER_DIR = "/data/ledger"
_CONTAINER_VAULT_DIR = "/data/vault"
_CONTAINER_POLICY_DIR = "/data/policy"
_CONTAINER_OAUTH_PATH = "/data/oauth.json"


def build_per_tenant_compose_config(
    registry: TenantRegistry,
    *,
    image: str = DEFAULT_DAEMON_IMAGE,
) -> dict:
    """Generate a docker-compose-shaped manifest for the multi-tenant fan-out
    per ADR-0070 D372 + ADR-0072 — one daemon service per tenant, each mounting
    ONLY its own host directories.

    This is the per-tenant container-orchestration primitive: the single-tenant
    default lives in ``infra/docker-compose.yml`` (the canonical
    ``git clone && docker compose up``); a multi-tenant operator serializes this
    dict to a generated compose file to fan one daemon process out per tenant
    (one container == one daemon process per ADR-0060 D335 invariant 1).

    The load-bearing contract — **container-surface per-tenant isolation**
    (D375 invariant (a)): tenant A's service bind-mounts ONLY tenant A's host
    ledger / vault / policy / oauth paths; no service references another
    tenant's host path. The per-container filesystem boundary is what enforces
    the cross-tenant no-leak guarantee at runtime.

    Returns a dict of the canonical compose shape ``{"services": {svc: {...}}}``.
    """

    services: dict[str, dict] = {}
    for tid, cfg in registry.tenants.items():
        services[f"daemon-{tid}"] = {
            "image": image,
            "container_name": f"outreach-factory-{tid}",
            "environment": {
                "OUTREACH_FACTORY_TENANT_ID": tid,
                "OUTREACH_FACTORY_LEDGER_DIR": _CONTAINER_LEDGER_DIR,
                "OUTREACH_FACTORY_VAULT_DIR": _CONTAINER_VAULT_DIR,
                "OUTREACH_FACTORY_POLICY_DIR": _CONTAINER_POLICY_DIR,
            },
            # Host path : in-container path. Every host path is under this
            # tenant's own isolated subtree (oauth token is read-only).
            "volumes": [
                f"{cfg.ledger_dir}:{_CONTAINER_LEDGER_DIR}",
                f"{cfg.vault_dir}:{_CONTAINER_VAULT_DIR}",
                f"{cfg.policy_dir}:{_CONTAINER_POLICY_DIR}",
                f"{cfg.oauth_token_path}:{_CONTAINER_OAUTH_PATH}:ro",
            ],
            "restart": "unless-stopped",
        }
    return {"services": services}


def resolve_per_tenant_grafana_folders(registry: TenantRegistry) -> dict[str, str]:
    """Resolve the per-tenant Grafana folder UID map per ADR-0070 D372 + the
    Pillar G Week 4 Grafana-as-code surface — ``{tenant_id: grafana_folder_uid}``.

    **Observability-surface per-tenant isolation** (D375 invariant (a)): each
    tenant's dashboards live in its OWN Grafana folder, so an operator viewing
    tenant A's folder never sees tenant B's panels. Two tenants sharing a folder
    UID would collapse that isolation — so this refuses-loud (``ValueError``) on
    a UID collision, mirroring `init_multi_tenant`'s duplicate-tenant_id guard.
    """

    folders: dict[str, str] = {}
    uid_owner: dict[str, str] = {}
    for tid, cfg in registry.tenants.items():
        uid = cfg.grafana_folder_uid
        if uid in uid_owner:
            raise ValueError(
                f"resolve_per_tenant_grafana_folders: tenants {uid_owner[uid]!r} "
                f"and {tid!r} share grafana_folder_uid {uid!r} — per-tenant "
                f"dashboard isolation per D375 invariant (a) requires distinct "
                f"folder UIDs (a collision would leak tenant dashboards across "
                f"the observability surface)."
            )
        uid_owner[uid] = tid
        folders[tid] = uid
    return folders


# --------------------------------------------------------------------------
# Pillar I Week 5 (ADR-0074 trajectory slot) — per-tenant SLO surface. The
# Pillar G SLO violation detector (`observability.detect_slo_violations`) is
# single-ledger; the per-tenant fan-out runs it against each tenant's OWN ledger
# so an operator's per-tenant SLO view never mixes two tenants' aggregates.
# Observability-surface extension of the D375 invariant (a) zero-cross-tenant-leak.
# --------------------------------------------------------------------------


def collect_per_tenant_slo_violations(
    registry: TenantRegistry,
    per_tenant_ledgers: Mapping[str, "object"],
    *,
    since_window: "timedelta",
    now: "datetime | None" = None,
    slo_config: "object | None" = None,
    detect_fn: "object | None" = None,
) -> dict[str, list]:
    """Per-tenant SLO violations — each tenant's violations computed from its
    OWN ledger per ADR-0074 + ADR-0056 D307-D313 + D375 invariant (a).

    Runs :func:`orchestrator.observability.detect_slo_violations` once per
    tenant against that tenant's ledger, returning ``{tenant_id: [SLOViolation,
    …]}``. Because each tenant is scored over a disjoint per-tenant ledger
    directory (per :func:`resolve_per_tenant_ledger_dir`), tenant A's SLO surface
    can never aggregate tenant B's events — the **observability-surface**
    extension of the per-tenant-isolation invariant.

    **Privacy invariant** per I8 + ADR-0050 D276(b) + ADR-0058 D323 + D375
    invariant (a): the returned ``SLOViolation`` values carry only
    ``slo_name`` / ``slo_threshold`` / ``observed_value`` / ``channel`` /
    ``window_seconds`` — NO ``person_id`` / body / source_list / any per-Person
    field — so a per-tenant SLO surface (Grafana panel, alert) cannot leak one
    tenant's per-Person data to another.

    Args:
        registry: the multi-tenant registry; iterated in its ``tenants`` order.
        per_tenant_ledgers: ``{tenant_id: Ledger}`` — each tenant's own ledger
            handle (opened on the per-tenant ledger directory). Refuse-loud
            (``KeyError`` via :exc:`ValueError`) if a registry tenant is missing.
        since_window: the SLO evaluation window, passed through per-tenant.
        now: deterministic-clock anchor, passed through per-tenant per the
            ADR-0034 D156 byte-identical-determinism contract.
        slo_config: optional :class:`~orchestrator.observability.SLOConfig`,
            passed through per-tenant (one config governs all tenants; per-tenant
            threshold overrides are a v2 concern).
        detect_fn: TEST-ONLY seam (mirrors the Pillar F ``embed_fn`` /
            ``retrieve_fn`` precedent per ADR-0039) — defaults to
            :func:`orchestrator.observability.detect_slo_violations`, imported
            lazily so this package stays import-light + free of any Pillar G
            load-order coupling.

    Returns:
        ``{tenant_id: list[SLOViolation]}`` — one entry per registry tenant.
    """

    if detect_fn is None:
        from orchestrator.observability import detect_slo_violations as _detect
        detect_fn = _detect

    per_tenant: dict[str, list] = {}
    for tid in registry.tenants:
        if tid not in per_tenant_ledgers:
            raise ValueError(
                f"collect_per_tenant_slo_violations: no ledger supplied for "
                f"registry tenant {tid!r} — each tenant must be scored over its "
                f"OWN ledger per D375 invariant (a) per-tenant-isolation."
            )
        per_tenant[tid] = list(
            detect_fn(
                per_tenant_ledgers[tid],
                since_window=since_window,
                now=now,
                slo_config=slo_config,
            )
        )
    return per_tenant


# --------------------------------------------------------------------------
# Pillar I Week 4 (ADR-0073 trajectory slot) — the init wizard. Takes a NEW
# operator from zero (clean clone) to a successful test send, then emits
# `init_wizard_completed`. The human-gated OAuth round-trip was verified once
# (2026-05-28); the wizard body is testable headlessly via the
# `gmail_authenticate_fn` seam (mirrors the W5 `detect_fn` + Pillar F `embed_fn`
# / `retrieve_fn` precedent) + a deterministic-clock `now` seam. Idempotent per
# D375 invariant (c): a re-run on a tenant that already completed is a NO-OP.
# --------------------------------------------------------------------------

#: Audit marker stamped on every Pillar I multi-tenant event payload at the
#: factory boundary per ADR-0010 D17 + the Pillar H ``build_*_payload``
#: precedent (the W3 follow-up P2-1 closure — :meth:`Ledger.append` only
#: ``setdefault``s ``v`` + ``ts``, so the factory stamps the marker itself).
EMITTED_BY = "multi_tenant"


#: Ordered closed-set of the init-wizard's zero-to-test-send steps per ADR-0070
#: D374 ROW 2 + ADR-0073. The wizard walks these IN ORDER; each step
#: refuse-louds with an operator-readable message naming the failing step
#: (R042 mitigation — per-step refuse-loud, NO Python traceback, per the
#: Pillar H W10-11 follow-up P1-1 closure's operator-facing-error discipline).
#:
#: * ``"gmail_oauth"`` — authenticate Gmail (the token round-trip the operator
#:   verified once); the ``gmail.send`` scope is the zero-to-test-send critical
#:   path. LinkedIn / Twitter / Calendar OAuth are out-of-band (LinkedIn MCP),
#:   NOT on this critical path.
#: * ``"vault_setup"`` — create the per-tenant vault directory + run the Pillar
#:   B migrations (idempotent per ADR-0009 D9 / surface-audit Concern B2).
#: * ``"first_prospect"`` — enroll the operator's first prospect → ``enrolled``.
#: * ``"test_send"`` — send a verification email to the operator's OWN address
#:   (send-to-self, so the wizard never spams a prospect) + read it back to
#:   confirm the send round-tripped.
INIT_WIZARD_STEPS: tuple[str, ...] = (
    "gmail_oauth",
    "vault_setup",
    "first_prospect",
    "test_send",
)


#: The wizard's default first prospect when the operator supplies none. The
#: ``.example`` TLD is RFC-2606 non-routable so an unattended run can never
#: reach a real inbox.
_DEFAULT_FIRST_PROSPECT: Mapping[str, str] = {
    "name": "Test Prospect",
    "email": "test-prospect@example.com",
}


class InitWizardError(RuntimeError):
    """An init-wizard step failed. Carries the failing ``step`` name so the
    operator knows exactly which step to retry per R042 (per-step refuse-loud;
    operator-readable message; NO Python traceback at the operator surface per
    the Pillar H W10-11 follow-up P1-1 closure)."""

    def __init__(self, step: str, message: str) -> None:
        self.step = step
        super().__init__(f"init wizard step {step!r} failed: {message}")


def _iso_z(dt: datetime) -> str:
    """ISO-8601 UTC, millisecond precision, trailing ``Z`` — matches
    :func:`orchestrator.ledger._now_iso`'s deterministic-sortable shape."""

    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def build_init_wizard_completed_payload(
    *,
    tenant_id: str,
    completed_at_ts: str,
    wizard_steps: Sequence[str],
) -> dict:
    """Build the emit-shape payload for the ``init_wizard_completed`` event per
    ADR-0070 D371 (event-class spec) + ADR-0073.

    Mirrors the Pillar G/H ``build_*_payload`` raw-primitive factory convention
    (ADR-0010 D17 + the Pillar H Week 2 follow-up P2-2 closure): refuse-loud at
    the factory boundary because there is no upstream invariant-bearing
    dataclass, and stamp ``_emitted_by`` here (``Ledger.append`` only fills
    ``v`` + ``ts``). The caller sets ``type``:
    ``led.append({"type": "init_wizard_completed", **payload})``.

    **Privacy invariant** per I8 + ADR-0050 D276(b) + D375 invariant (a): the
    payload carries only ``tenant_id`` + ``completed_at_ts`` + ``wizard_steps``
    + ``_emitted_by`` — NO per-Person field — so the per-tenant first-run audit
    surface cannot leak one tenant's prospect data to another.

    Raises:
        ValueError: if ``tenant_id`` is malformed (per :func:`_validate_tenant_id`),
            ``completed_at_ts`` is empty, or ``wizard_steps`` contains a step
            outside :data:`INIT_WIZARD_STEPS`.
    """

    _validate_tenant_id(tenant_id)
    if not completed_at_ts:
        raise ValueError(
            "build_init_wizard_completed_payload requires a non-empty "
            "completed_at_ts (ISO-8601 UTC); the init wizard derives it from "
            "the deterministic-clock `now` anchor."
        )
    steps = list(wizard_steps)
    bad = [s for s in steps if s not in INIT_WIZARD_STEPS]
    if bad:
        raise ValueError(
            f"build_init_wizard_completed_payload: wizard_steps contains steps "
            f"outside INIT_WIZARD_STEPS {list(INIT_WIZARD_STEPS)}: {bad}."
        )
    return {
        "tenant_id": tenant_id,
        "completed_at_ts": completed_at_ts,
        "wizard_steps": steps,
        "_emitted_by": EMITTED_BY,
    }


def _default_migration_apply_fn(config: TenantConfig) -> Callable[[], None]:
    """Production default for the wizard's ``vault_setup`` migration step:
    run the Pillar B :class:`MigrationRunner` against THIS tenant's own
    directories per surface-audit Concern B2 (per-tenant migration-state
    isolation; idempotent auto-apply per ADR-0009 D9). Imported lazily so the
    package stays import-light + free of any Pillar B load-order coupling (the
    W5 ``detect_fn`` lazy-import precedent)."""

    def _apply() -> None:
        from orchestrator.migrations.runner import MigrationRunner

        MigrationRunner(
            ledger_dir=config.ledger_dir,
            vault_dir=config.vault_dir,
            policy_dir=config.policy_dir,
        ).apply()

    return _apply


def _default_enroll(led: "object", prospect: Mapping[str, str], now: datetime) -> str:
    """Production default for the wizard's ``first_prospect`` step: append an
    ``enrolled`` event (stage ``queued`` per ``ledger._STAGE_BY_EVENT_TYPE``)
    for the operator's first prospect into THIS tenant's ledger."""

    name = (prospect.get("name") or "First Prospect").strip()
    email = (prospect.get("email") or "").strip()
    pid = "p_" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "first_prospect")
    led.append({
        "type": "enrolled",
        "person_id": pid,
        "channel": "email",
        "email": email,
        "ts": _iso_z(now),
        "source_skill": "init-wizard",
    })
    return pid


def run_init_wizard(
    config: TenantConfig,
    *,
    gmail_authenticate_fn: Callable[[], "object"],
    led: "object | None" = None,
    first_prospect: Mapping[str, str] | None = None,
    test_send_to: str | None = None,
    now: datetime | None = None,
    migration_apply_fn: Callable[[], None] | None = None,
    enroll_fn: Callable[["object", Mapping[str, str], datetime], str] | None = None,
) -> dict:
    """Take a NEW operator from zero (clean clone) to a successful test send,
    then emit ``init_wizard_completed`` — the Pillar I Week 4 body per ADR-0070
    D374 ROW 2 + ADR-0073.

    Walks :data:`INIT_WIZARD_STEPS` in order: ``gmail_oauth`` → ``vault_setup``
    → ``first_prospect`` → ``test_send``. Each step refuse-louds with an
    operator-readable :exc:`InitWizardError` naming the failing step (R042).

    **Idempotence** per D375 invariant (c): if THIS tenant's ledger already has
    an ``init_wizard_completed`` event, the wizard is a NO-OP — it re-authenticates
    NOTHING, re-creates NO directories, re-sends NO email, and emits NO second
    event (the gate runs FIRST, before any side effect). This is the structural
    underpinning the Pillar B migration framework's idempotence (ADR-0009 D9)
    provides for ``vault_setup`` per surface-audit Concern B2.

    Args:
        config: the tenant's :class:`TenantConfig`. The ``gmail.send`` scope
            MUST be provisioned (the zero-to-test-send critical path).
        gmail_authenticate_fn: TEST-ONLY/production seam — a zero-arg callable
            returning an authenticated Gmail client (``.sender_email`` +
            ``.send_email`` + ``.search_messages`` + ``.get_message``).
            Production: ``GmailClient.authenticate``; tests inject a FakeGmail
            (the canonical seam shape at ``tests/test_reconcile.py:78``). The
            CALL itself is the ``gmail_oauth`` step's token round-trip.
        led: the tenant's :class:`~orchestrator.ledger.Ledger`; opened on
            ``config.ledger_dir`` when None.
        first_prospect: ``{"name", "email"}`` the operator's first prospect;
            defaults to a non-routable ``.example`` placeholder.
        test_send_to: the test-send recipient; defaults to the authenticated
            client's own ``sender_email`` (send-to-self — the wizard never
            spams a prospect).
        now: deterministic-clock anchor per ADR-0034 D156; defaults to
            ``datetime.now(timezone.utc)``.
        migration_apply_fn: ``vault_setup`` migration seam; defaults to the
            real per-tenant :class:`MigrationRunner` (:func:`_default_migration_apply_fn`).
        enroll_fn: ``first_prospect`` enrollment seam; defaults to
            :func:`_default_enroll`.

    Returns:
        A dict with stable keys regardless of outcome — ``tenant_id`` +
        ``status`` (``"completed"`` | ``"already_completed"``) + ``completed``
        (bool) + ``wizard_steps`` (the steps run THIS call) + ``test_send_message_id``
        + ``test_send_to``.
    """

    now = now or datetime.now(timezone.utc)
    if led is None:
        from orchestrator import ledger as _ledger
        led = _ledger.Ledger(config.ledger_dir)

    # --- Idempotence gate (D375 invariant (c)) — runs FIRST, before any side
    # effect, so a re-run never re-auths / re-creates dirs / re-sends / re-emits.
    for ev in led.all_events():
        d = ev.to_dict()
        if d.get("type") == "init_wizard_completed" and d.get("tenant_id") == config.tenant_id:
            return {
                "tenant_id": config.tenant_id,
                "status": "already_completed",
                "completed": False,
                "wizard_steps": [],
                "test_send_message_id": None,
                "test_send_to": None,
            }

    completed_steps: list[str] = []

    # --- Step 1: gmail_oauth — the token round-trip (R042: refuse-loud per step).
    if "gmail.send" not in config.oauth_token_scopes:
        raise InitWizardError(
            "gmail_oauth",
            f"tenant {config.tenant_id!r} did not provision the 'gmail.send' "
            f"OAuth scope, which the zero-to-test-send critical path requires. "
            f"Add 'gmail.send' to the tenant's oauth_token_scopes and re-run "
            f"`init`.",
        )
    try:
        gmail = gmail_authenticate_fn()
    except Exception as exc:  # noqa: BLE001 — operator-facing refuse-loud boundary
        raise InitWizardError(
            "gmail_oauth",
            f"Gmail OAuth did not complete ({exc}). Re-run the consent flow; "
            f"check the token at {config.oauth_token_path}.",
        ) from None
    sender = getattr(gmail, "sender_email", None)
    if not sender:
        raise InitWizardError(
            "gmail_oauth",
            "Gmail authentication returned no sender_email — the token "
            "round-trip did not complete. Re-run the OAuth consent.",
        )
    completed_steps.append("gmail_oauth")

    # --- Step 2: vault_setup — create the vault dir + run migrations (idempotent).
    try:
        config.vault_dir.mkdir(parents=True, exist_ok=True)
        (migration_apply_fn or _default_migration_apply_fn(config))()
    except Exception as exc:  # noqa: BLE001 — operator-facing refuse-loud boundary
        raise InitWizardError(
            "vault_setup",
            f"vault/migration setup failed ({exc}). Check write permissions on "
            f"{config.vault_dir} and {config.ledger_dir}.",
        ) from None
    completed_steps.append("vault_setup")

    # --- Step 3: first_prospect — enroll the operator's first prospect.
    prospect = first_prospect or _DEFAULT_FIRST_PROSPECT
    try:
        person_id = (enroll_fn or _default_enroll)(led, prospect, now)
    except Exception as exc:  # noqa: BLE001 — operator-facing refuse-loud boundary
        raise InitWizardError(
            "first_prospect",
            f"enrolling the first prospect failed ({exc}).",
        ) from None
    completed_steps.append("first_prospect")

    # --- Step 4: test_send — send-to-self + read-back (the success proof).
    recipient = test_send_to or sender
    intent_marker = f"snd_initwiz_{config.tenant_id}"
    try:
        result = gmail.send_email(
            to=recipient,
            subject="Outreach Factory — init wizard test send",
            body=(
                "Automated zero-to-test-send verification from the Outreach "
                "Factory init wizard. Receiving this confirms your Gmail OAuth "
                "+ send path work."
            ),
            extra_headers={"X-Outreach-Intent-Id": intent_marker},
        )
        message_id = result[0] if isinstance(result, tuple) else result
        # Read-back round-trip (the human-verified shape): the sent message is
        # retrievable by its intent marker.
        if not gmail.search_messages(intent_marker):
            raise InitWizardError(
                "test_send",
                "the test send did not appear on read-back — it did not "
                "round-trip. Check the Gmail send quota + the 'gmail.send' scope.",
            )
    except InitWizardError:
        raise
    except Exception as exc:  # noqa: BLE001 — operator-facing refuse-loud boundary
        raise InitWizardError(
            "test_send",
            f"the test send failed ({exc}). Verify the 'gmail.send' scope + that "
            f"the Gmail API is enabled.",
        ) from None
    completed_steps.append("test_send")

    # --- All four steps green → emit init_wizard_completed (first-run signal).
    led.append({
        "type": "init_wizard_completed",
        **build_init_wizard_completed_payload(
            tenant_id=config.tenant_id,
            completed_at_ts=_iso_z(now),
            wizard_steps=completed_steps,
        ),
    })
    return {
        "tenant_id": config.tenant_id,
        "status": "completed",
        "completed": True,
        "wizard_steps": completed_steps,
        "test_send_message_id": message_id,
        "test_send_to": recipient,
    }


__all__ = [
    "TENANT_LIFECYCLE_STATES",
    "TENANT_NEW_EVENT_CLASSES",
    "TENANT_OAUTH_TOKEN_SCOPES",
    "TenantConfig",
    "TenantRegistry",
    "init_multi_tenant",
    "resolve_per_tenant_ledger_dir",
    "resolve_per_tenant_policy_dir",
    "DEFAULT_DAEMON_IMAGE",
    "build_per_tenant_compose_config",
    "resolve_per_tenant_grafana_folders",
    "collect_per_tenant_slo_violations",
    "EMITTED_BY",
    "INIT_WIZARD_STEPS",
    "InitWizardError",
    "build_init_wizard_completed_payload",
    "run_init_wizard",
]
