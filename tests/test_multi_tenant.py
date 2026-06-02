"""Pillar I Week 1 + Week 2 — multi-tenant contract tests (per ADR-0070 D371 + D376).

Per the per-pillar-foundation precedent (Pillar G Week 1 shipped
``tests/test_observability.py`` with 19 contract-level tests pinning
the module shape + closed-sets + signature; Pillar H Week 1 shipped
``tests/test_daemon.py`` with 34 contract-level tests). This file pins
the Pillar I Week 1 contract:

* :class:`TenantConfig` dataclass shape (fields + frozen invariant +
  defaults).
* :class:`TenantRegistry` dataclass shape (fields + frozen invariant).
* :data:`TENANT_LIFECYCLE_STATES` closed-set contents + frozen.
* :data:`TENANT_NEW_EVENT_CLASSES` closed-set contents + frozen +
  subset-of-EVENT_CLASS_CATALOG-at-Week-2 (the catalog extension).
* :data:`TENANT_OAUTH_TOKEN_SCOPES` closed-set contents + frozen.
* Primitive bodies (init_multi_tenant + resolve_per_tenant_ledger_dir
  + resolve_per_tenant_policy_dir) — Week 2 behavioral assertions per
  ADR-0070 D376 (Week 1 shipped the NotImplementedError signatures).
* Public surface (``__all__``).

Test classes:

* ``TestTenantLifecycleStates`` — closed-set contents + frozen.
* ``TestTenantNewEventClasses`` — closed-set contents + frozen +
  subset-of-EVENT_CLASS_CATALOG-at-Week-2 + disjoint-from-Pillar-H-
  DAEMON_NEW_EVENT_CLASSES + naming-convention.
* ``TestTenantOauthTokenScopes`` — closed-set contents + frozen.
* ``TestTenantConfig`` — frozen invariant + field presence + default
  for ``lifecycle_state``.
* ``TestTenantRegistry`` — frozen invariant + field presence.
* ``TestInitMultiTenant`` — signature presence + Week 2 registry
  construction.
* ``TestResolvePerTenantLedgerDir`` — signature presence + Week 2
  isolated-path resolution.
* ``TestResolvePerTenantPolicyDir`` — signature presence + Week 2
  isolated-path resolution.
* ``TestPublicSurface`` — re-export shape per
  ``orchestrator/multi_tenant/__init__.py``.
* ``TestCrossPillarClosedSetDisjointness`` — Pillar I closed-sets
  disjoint from prior-pillar closed-sets per the per-pillar mirror
  constants parity discipline (ADR-0070 D375 + the W8 follow-up P2-1
  precedent).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from orchestrator import multi_tenant as _mt
from orchestrator.multi_tenant import (
    TENANT_LIFECYCLE_STATES,
    TENANT_NEW_EVENT_CLASSES,
    TENANT_OAUTH_TOKEN_SCOPES,
    TenantConfig,
    TenantRegistry,
    init_multi_tenant,
    resolve_per_tenant_ledger_dir,
    resolve_per_tenant_policy_dir,
)


# Helper for the test substrate.
def _make_tenant_config(tenant_id: str = "tenant_a") -> TenantConfig:
    """Construct a syntactically valid :class:`TenantConfig` for tests."""

    return TenantConfig(
        tenant_id=tenant_id,
        vault_dir=Path(f"/tmp/{tenant_id}/vault"),
        ledger_dir=Path(f"/tmp/{tenant_id}/ledger"),
        policy_dir=Path(f"/tmp/{tenant_id}/policy"),
        oauth_token_path=Path(f"/tmp/{tenant_id}/oauth.json"),
        oauth_token_scopes=frozenset({"gmail.send"}),
        grafana_folder_uid=f"folder-{tenant_id}",
    )


class TestTenantLifecycleStates:
    """:data:`TENANT_LIFECYCLE_STATES` closed-set contract per ADR-0070
    D371."""

    def test_closed_set_contents(self) -> None:
        assert TENANT_LIFECYCLE_STATES == frozenset({
            "provisioning",
            "active",
            "paused",
            "deprovisioning",
        })

    def test_is_frozenset(self) -> None:
        assert isinstance(TENANT_LIFECYCLE_STATES, frozenset)

    def test_cannot_mutate(self) -> None:
        with pytest.raises(AttributeError):
            TENANT_LIFECYCLE_STATES.add("running")  # type: ignore[attr-defined]


class TestTenantNewEventClasses:
    """:data:`TENANT_NEW_EVENT_CLASSES` closed-set contract per ADR-0070
    D371 + the per-pillar mirror constants parity discipline."""

    def test_closed_set_contents(self) -> None:
        assert TENANT_NEW_EVENT_CLASSES == frozenset({
            "tenant_provisioned",
            "tenant_paused",
            "tenant_resumed",
            "tenant_deprovisioned",
            "init_wizard_completed",
            "auth_token_refreshed",
        })

    def test_is_frozenset(self) -> None:
        assert isinstance(TENANT_NEW_EVENT_CLASSES, frozenset)

    def test_cannot_mutate(self) -> None:
        with pytest.raises(AttributeError):
            TENANT_NEW_EVENT_CLASSES.add("tenant_archived")  # type: ignore[attr-defined]

    def test_size_is_six(self) -> None:
        """SIX new event classes at Pillar I Week 1 per ADR-0070 D371.

        Mirrors Pillar H Week 6 closure's discipline (the W6 follow-up
        P3-6 closure pins the substantive size assertion); Pillar I
        Week 2 adds the catalog extension regression-barrier test
        verifying ``observability.EVENT_CLASS_CATALOG`` includes these
        SIX classes per the per-pillar mirror constants parity.
        """

        assert len(TENANT_NEW_EVENT_CLASSES) == 6

    def test_subset_of_event_class_catalog_at_week_2(self) -> None:
        """Pillar I Week 2 ships the catalog extension — the SIX new event
        classes are NOW in ``observability.EVENT_CLASS_CATALOG`` per the
        per-pillar mirror constants parity discipline (ADR-0070 D376 +
        the Pillar H Week 2 precedent per ADR-0061 D338).
        """

        from orchestrator.observability import EVENT_CLASS_CATALOG

        assert TENANT_NEW_EVENT_CLASSES <= EVENT_CLASS_CATALOG

    def test_naming_convention_lowercase_underscore(self) -> None:
        """Per ADR-0050 D272 + the existing event-class naming convention:
        lowercase with underscores; no hyphens or camelCase.
        """

        for name in TENANT_NEW_EVENT_CLASSES:
            assert name == name.lower(), name
            assert "-" not in name, name
            assert " " not in name, name


class TestTenantOauthTokenScopes:
    """:data:`TENANT_OAUTH_TOKEN_SCOPES` closed-set contract per ADR-0070
    D371 + the per-channel scope discipline."""

    def test_closed_set_contents(self) -> None:
        assert TENANT_OAUTH_TOKEN_SCOPES == frozenset({
            "gmail.send",
            "gmail.readonly",
            "linkedin.invite",
            "linkedin.dm",
            "twitter.dm",
            "calendar.book",
        })

    def test_is_frozenset(self) -> None:
        assert isinstance(TENANT_OAUTH_TOKEN_SCOPES, frozenset)

    def test_cannot_mutate(self) -> None:
        with pytest.raises(AttributeError):
            TENANT_OAUTH_TOKEN_SCOPES.add("slack.send")  # type: ignore[attr-defined]

    def test_size_is_six(self) -> None:
        """SIX OAuth scopes at Pillar I Week 1 per ADR-0070 D371 +
        the per-channel scope discipline (one per channel + Gmail's
        readonly subset).
        """

        assert len(TENANT_OAUTH_TOKEN_SCOPES) == 6


class TestTenantConfig:
    """:class:`TenantConfig` dataclass contract per ADR-0070 D371."""

    def test_is_frozen(self) -> None:
        config = _make_tenant_config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.tenant_id = "other"  # type: ignore[misc]

    def test_required_fields(self) -> None:
        """Pin the field shape per ADR-0070 D371 — Week 1 contract."""

        fields = {f.name for f in dataclasses.fields(TenantConfig)}
        assert fields == {
            "tenant_id",
            "vault_dir",
            "ledger_dir",
            "policy_dir",
            "oauth_token_path",
            "oauth_token_scopes",
            "grafana_folder_uid",
            "lifecycle_state",
        }

    def test_lifecycle_state_defaults_to_provisioning(self) -> None:
        config = _make_tenant_config()
        assert config.lifecycle_state == "provisioning"
        assert config.lifecycle_state in TENANT_LIFECYCLE_STATES

    def test_holds_canonical_path_types(self) -> None:
        config = _make_tenant_config()
        assert isinstance(config.vault_dir, Path)
        assert isinstance(config.ledger_dir, Path)
        assert isinstance(config.policy_dir, Path)
        assert isinstance(config.oauth_token_path, Path)

    def test_oauth_scopes_is_frozenset(self) -> None:
        config = _make_tenant_config()
        assert isinstance(config.oauth_token_scopes, frozenset)


class TestTenantRegistry:
    """:class:`TenantRegistry` dataclass contract per ADR-0070 D371."""

    def test_is_frozen(self) -> None:
        registry = TenantRegistry(
            tenants={"tenant_a": _make_tenant_config("tenant_a")},
            shared_install_dir=Path("/opt/outreach-factory"),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            registry.shared_install_dir = Path("/other")  # type: ignore[misc]

    def test_required_fields(self) -> None:
        """Pin the field shape per ADR-0070 D371."""

        fields = {f.name for f in dataclasses.fields(TenantRegistry)}
        assert fields == {"tenants", "shared_install_dir"}

    def test_holds_mapping_and_path(self) -> None:
        config_a = _make_tenant_config("tenant_a")
        config_b = _make_tenant_config("tenant_b")
        registry = TenantRegistry(
            tenants={"tenant_a": config_a, "tenant_b": config_b},
            shared_install_dir=Path("/opt/outreach-factory"),
        )
        assert registry.tenants["tenant_a"] is config_a
        assert registry.tenants["tenant_b"] is config_b
        assert isinstance(registry.shared_install_dir, Path)


class TestInitMultiTenant:
    """:func:`init_multi_tenant` signature contract per ADR-0070 D371.

    Week 1 ships the signature only; Week 2 ships the body per ADR-0070
    D376 trajectory + ADR-0071.
    """

    def test_signature_exists(self) -> None:
        assert callable(init_multi_tenant)

    def test_week_2_constructs_registry(self, tmp_path) -> None:
        """Pillar I Week 2 body — constructs a :class:`TenantRegistry`
        mapping ``tenant_id -> TenantConfig`` per ADR-0070 D371.
        ``shared_install_dir`` must exist (the framework install dir per
        D375 invariant (d)); ``tmp_path`` does."""

        cfg = _make_tenant_config("tenant_a")
        registry = init_multi_tenant([cfg], shared_install_dir=tmp_path)
        assert isinstance(registry, TenantRegistry)
        assert registry.tenants == {"tenant_a": cfg}
        assert registry.shared_install_dir == tmp_path

    def test_week_2_refuses_duplicate_tenant_id(self, tmp_path) -> None:
        """Refuse-loud on duplicate ``tenant_id`` per ADR-0070 D375
        invariant (a) — collisions would alias per-tenant directory paths."""

        cfg = _make_tenant_config("dup")
        with pytest.raises(ValueError, match="duplicate tenant_id"):
            init_multi_tenant([cfg, cfg], shared_install_dir=tmp_path)


class TestResolvePerTenantLedgerDir:
    """:func:`resolve_per_tenant_ledger_dir` signature contract per
    ADR-0070 D371 + D375 invariant (a) per-tenant-isolation."""

    def test_signature_exists(self) -> None:
        assert callable(resolve_per_tenant_ledger_dir)

    def test_week_2_produces_isolated_path(self) -> None:
        """Pillar I Week 2 body — resolves ``base / tenant_id``; the
        tenant_id format guard bars path-traversal per ADR-0070 D375
        invariant (a) per-tenant-isolation."""

        out = resolve_per_tenant_ledger_dir(
            Path("/var/outreach-factory/ledger"), tenant_id="tenant_a")
        assert out == Path("/var/outreach-factory/ledger/tenant_a")
        with pytest.raises(ValueError):
            resolve_per_tenant_ledger_dir(
                Path("/var/outreach-factory/ledger"), tenant_id="../evil")


class TestResolvePerTenantPolicyDir:
    """:func:`resolve_per_tenant_policy_dir` signature contract per
    ADR-0070 D371 + D375 invariant (a) per-tenant-isolation."""

    def test_signature_exists(self) -> None:
        assert callable(resolve_per_tenant_policy_dir)

    def test_week_2_produces_isolated_path(self) -> None:
        """Pillar I Week 2 body — resolves ``base / tenant_id``; traversal
        barred per ADR-0070 D375 invariant (a) per-tenant-isolation."""

        out = resolve_per_tenant_policy_dir(
            Path("/var/outreach-factory/policy"), tenant_id="tenant_a")
        assert out == Path("/var/outreach-factory/policy/tenant_a")
        with pytest.raises(ValueError):
            resolve_per_tenant_policy_dir(
                Path("/var/outreach-factory/policy"), tenant_id="bad/slash")


class TestPublicSurface:
    """Re-export shape per ``orchestrator/multi_tenant/__init__.py``."""

    def test_all_contents(self) -> None:
        """Per the per-pillar-foundation precedent, ``__all__`` is the
        operator-visible surface; pin verbatim.
        """

        assert set(_mt.__all__) == {
            "TENANT_LIFECYCLE_STATES",
            "TENANT_NEW_EVENT_CLASSES",
            "TENANT_OAUTH_TOKEN_SCOPES",
            "TenantConfig",
            "TenantRegistry",
            "init_multi_tenant",
            "resolve_per_tenant_ledger_dir",
            "resolve_per_tenant_policy_dir",
            # Week 3 (ADR-0072 slot) — container + Grafana isolation surface.
            "DEFAULT_DAEMON_IMAGE",
            "build_per_tenant_compose_config",
            "resolve_per_tenant_grafana_folders",
            # Week 5 (ADR-0074 slot) — per-tenant SLO surface.
            "collect_per_tenant_slo_violations",
            # Week 4 (ADR-0073 slot) — init wizard surface.
            "EMITTED_BY",
            "INIT_WIZARD_STEPS",
            "InitWizardError",
            "build_init_wizard_completed_payload",
            "run_init_wizard",
        }

    def test_all_names_resolve(self) -> None:
        """Every name in ``__all__`` resolves at the module surface."""

        for name in _mt.__all__:
            assert hasattr(_mt, name), name


class TestCrossPillarClosedSetDisjointness:
    """Per-pillar mirror constants parity discipline per ADR-0070 D375 +
    the Pillar H W8 follow-up P2-1 precedent.

    The Pillar I closed-sets MUST be disjoint from prior-pillar closed-
    sets to preserve the structural commitment that each pillar's
    closed-set carries a distinct semantic. Pillar I Week 2 extends
    ``observability.EVENT_CLASS_CATALOG`` with
    :data:`TENANT_NEW_EVENT_CLASSES` per the catalog mirror parity;
    Week 1 verifies disjointness BEFORE the union.
    """

    def test_tenant_new_event_classes_disjoint_from_daemon_new_event_classes(
        self,
    ) -> None:
        """Pillar I :data:`TENANT_NEW_EVENT_CLASSES` MUST be disjoint
        from Pillar H :data:`orchestrator.daemon.DAEMON_NEW_EVENT_CLASSES`
        per the cross-pillar closed-set discipline.
        """

        from orchestrator.daemon import DAEMON_NEW_EVENT_CLASSES

        assert TENANT_NEW_EVENT_CLASSES.isdisjoint(DAEMON_NEW_EVENT_CLASSES)

    def test_tenant_lifecycle_states_disjoint_from_daemon_lifecycle_states(
        self,
    ) -> None:
        """Pillar I :data:`TENANT_LIFECYCLE_STATES` MUST be disjoint
        from Pillar H :data:`orchestrator.daemon.DAEMON_LIFECYCLE_STATES`
        — the per-tenant lifecycle is a DIFFERENT semantic from the
        per-daemon-process lifecycle per ADR-0070 D371 (the daemon
        lifecycle is the process state machine; the tenant lifecycle
        is the operator-visible state of a tenant's installation).
        """

        from orchestrator.daemon import DAEMON_LIFECYCLE_STATES

        assert TENANT_LIFECYCLE_STATES.isdisjoint(DAEMON_LIFECYCLE_STATES)

    def test_tenant_oauth_token_scopes_naming_convention(self) -> None:
        """The OAuth scope names follow ``<channel>.<action>`` convention
        per the per-channel two-phase commit per ADR-0014 D33 + the per-
        channel SDK discipline.
        """

        for scope in TENANT_OAUTH_TOKEN_SCOPES:
            assert "." in scope, scope
            channel, action = scope.split(".", 1)
            assert channel.isalpha(), channel
            assert action.replace("_", "").isalnum(), action


class TestPillarIW1FollowupSubstantiveConcernCounts:
    """Pillar I Week 1 follow-up P3-1 closure regression-barriers per the
    FIRST Pillar I ADR-vs-actual-impl drift caught by the per-week-
    reviewer's cross-pillar back-audit discipline extending the Pillar H
    TEN consecutive catches (per the W12 follow-up P3-1 closure) to
    ELEVEN consecutive weeks across the Pillar H + Pillar I trajectory.

    The W1 main commit narrative claimed "18 P3 concerns documented for
    Pillar I Week 2-6 trajectory" at HANDOFF doc line 153 + the commit
    message §D373 narrative; the actual count post-W1-main was **15 P3
    concerns + 1 P2 concern (G1) + 1 Deferred (H4)** per the Pillar I
    cross-pillar surface audit at ``.planning/REVIEW-pillar-i-surface-
    audit.md``. Off-by-three drift.

    These regression-barriers pin the SUBSTANTIVE concern counts in the
    audit doc via ``grep -c`` invocations — mirrors the Pillar H Week 12
    follow-up's `TestW12FollowupCatalogClaimSubstantive` × 2 regression-
    barriers that pinned the substantive claims after the TENTH ADR-vs-
    actual-impl drift in Pillar H.

    The audit doc is gitignored (per ``.gitignore``'s ``.planning/REVIEW-
    *.md`` pattern); these tests are SKIPPED if the audit doc is not
    present (e.g., on a fresh clone) — per the per-pillar-foundation
    precedent that gitignored docs MAY be absent at clone time. The
    tests RUN at the author's environment where the audit doc IS
    present + verify the substantive concern counts via ``grep -c``.
    """

    @pytest.fixture
    def audit_doc_path(self) -> Path:
        """Resolve the audit doc path; skip if not present."""

        repo_root = Path(__file__).resolve().parent.parent
        audit_path = repo_root / ".planning" / "REVIEW-pillar-i-surface-audit.md"
        if not audit_path.exists():
            pytest.skip(
                f"Audit doc {audit_path} not present (gitignored per "
                ".planning/REVIEW-*.md). Test runs at the author's "
                "environment where the doc IS present."
            )
        return audit_path

    def test_audit_doc_p3_concern_count_is_fifteen(self, audit_doc_path: Path) -> None:
        """Per the FIRST Pillar I ADR-vs-actual-impl drift closure
        (P3-1) — the audit doc has FIFTEEN P3 concerns documented for
        Pillar I Week 2-6 trajectory. The W1 main commit narrative
        claimed "18 P3 concerns" off-by-three; this regression-barrier
        pins the substantive count.
        """

        import re

        content = audit_doc_path.read_text(encoding="utf-8")
        # Count occurrences of "**Concern <letter><digits> (P3" — the
        # canonical P3 concern marker convention in the audit doc.
        p3_count = len(re.findall(r"\*\*Concern [A-Z][0-9]+ \(P3", content))
        assert p3_count == 15, (
            f"P3-1 closure substantive claim violated — audit doc has "
            f"{p3_count} P3 concerns (expected 15 per Pillar I Week 1 "
            f"follow-up P3-1 closure). The W1 main commit narrative "
            f"claim of '18 P3' was the FIRST Pillar I ADR-vs-actual-"
            f"impl drift caught by the per-week-reviewer extending the "
            f"Pillar H TEN consecutive catches to ELEVEN consecutive "
            f"weeks across the Pillar H + Pillar I trajectory."
        )

    def test_audit_doc_p2_concern_count_is_one(self, audit_doc_path: Path) -> None:
        """Per the P3-1 closure — the audit doc has ONE P2 concern
        (Concern G1: Pillar G ``_BREAKDOWN_DIMS_ALLOWED`` does NOT
        include ``tenant_id``; Pillar I Week 2+ extends).
        """

        import re

        content = audit_doc_path.read_text(encoding="utf-8")
        p2_count = len(re.findall(r"\*\*Concern [A-Z][0-9]+ \(P2", content))
        assert p2_count == 1, (
            f"P3-1 closure substantive claim violated — audit doc has "
            f"{p2_count} P2 concerns (expected 1 per Pillar I Week 1 "
            f"follow-up P3-1 closure)."
        )

    def test_audit_doc_deferred_concern_count_is_one(
        self, audit_doc_path: Path
    ) -> None:
        """Per the P3-1 closure — the audit doc has ONE Deferred concern
        (Concern H4: Pillar H W7 follow-up NEW-2 shutdown-during-in-
        flight-reconcile regression-barrier; lands at Pillar I Week 5
        CI surface).
        """

        import re

        content = audit_doc_path.read_text(encoding="utf-8")
        deferred_count = len(re.findall(r"\(Deferred from", content))
        assert deferred_count == 1, (
            f"P3-1 closure substantive claim violated — audit doc has "
            f"{deferred_count} Deferred concerns (expected 1 per Pillar "
            f"I Week 1 follow-up P3-1 closure: the Pillar H W7 follow-"
            f"up NEW-2 shutdown-during-in-flight-reconcile regression-"
            f"barrier deferred to Pillar I Week 5 CI surface)."
        )


# --------------------------------------------------------------------------
# Pillar I Week 4 (ADR-0073) — init wizard. The L0 golden-path row + the two
# coherence rows cover the happy path + isolation + idempotence; these unit
# tests pin the per-step refuse-loud (R042) + the emit-factory boundary the
# higher-level rows don't exercise.
# --------------------------------------------------------------------------


class _FakeGmail:
    """Init-wizard test seam — send + read-back, with knobs for the failure
    modes the per-step refuse-loud guards (no sender_email; send raises;
    send does not round-trip)."""

    def __init__(self, sender_email="operator@gmail.test", round_trips=True,
                 raise_on_send=False):
        self.sender_email = sender_email
        self.round_trips = round_trips
        self.raise_on_send = raise_on_send
        self.sent: list = []

    def send_email(self, to, subject, body, extra_headers=None, **_kw):
        if self.raise_on_send:
            raise RuntimeError("Gmail API send failed: quota exceeded")
        mid = f"m_{len(self.sent) + 1}"
        self.sent.append({"id": mid, "threadId": f"th_{mid}", "to": to,
                          "headers": dict(extra_headers or {}), "body": body})
        return mid, f"th_{mid}"

    def search_messages(self, query, max_results=100):
        if not self.round_trips:
            return []
        iid = "X-Outreach-Intent-Id"
        return [{"id": m["id"], "threadId": m["threadId"]} for m in self.sent
                if query in m["body"] or query == m["headers"].get(iid)]

    def get_message(self, msg_id):
        return next((m for m in self.sent if m["id"] == msg_id), None)


def _wizard_config(tmp_path: Path, *, scopes=frozenset({"gmail.send"})) -> TenantConfig:
    root = tmp_path / "tenant_a"
    return TenantConfig(
        tenant_id="tenant_a", vault_dir=root / "vault", ledger_dir=root / "ledger",
        policy_dir=root / "policy", oauth_token_path=root / "oauth.json",
        oauth_token_scopes=scopes, grafana_folder_uid="folder-tenant_a",
    )


from datetime import datetime, timezone  # noqa: E402 — local to the W4 section

_W4_NOW = datetime(2026, 5, 28, 17, 0, 0, tzinfo=timezone.utc)


class TestInitWizardStepsAndEmitFactory:
    """:data:`INIT_WIZARD_STEPS` + :func:`build_init_wizard_completed_payload`
    contract per ADR-0073."""

    def test_steps_are_the_ordered_four(self) -> None:
        assert _mt.INIT_WIZARD_STEPS == (
            "gmail_oauth", "vault_setup", "first_prospect", "test_send",
        )
        assert _mt.EMITTED_BY == "multi_tenant"

    def test_payload_shape_is_privacy_clean(self) -> None:
        payload = _mt.build_init_wizard_completed_payload(
            tenant_id="tenant_a", completed_at_ts="2026-05-28T17:00:00.000Z",
            wizard_steps=list(_mt.INIT_WIZARD_STEPS),
        )
        assert payload == {
            "tenant_id": "tenant_a",
            "completed_at_ts": "2026-05-28T17:00:00.000Z",
            "wizard_steps": ["gmail_oauth", "vault_setup", "first_prospect", "test_send"],
            "_emitted_by": "multi_tenant",
        }
        # I8 / D375 invariant (a): no per-Person field in the audit payload.
        assert not ({"person_id", "email", "body", "draft_body"} & set(payload))

    def test_payload_refuses_unknown_step(self) -> None:
        with pytest.raises(ValueError, match="outside INIT_WIZARD_STEPS"):
            _mt.build_init_wizard_completed_payload(
                tenant_id="tenant_a", completed_at_ts="2026-05-28T17:00:00.000Z",
                wizard_steps=["gmail_oauth", "linkedin_oauth"],
            )

    def test_payload_refuses_empty_ts_and_bad_tenant_id(self) -> None:
        with pytest.raises(ValueError, match="completed_at_ts"):
            _mt.build_init_wizard_completed_payload(
                tenant_id="tenant_a", completed_at_ts="", wizard_steps=[])
        with pytest.raises(ValueError):
            _mt.build_init_wizard_completed_payload(
                tenant_id="../evil", completed_at_ts="2026-05-28T17:00:00.000Z",
                wizard_steps=[])


class TestInitWizardBody:
    """:func:`run_init_wizard` happy path + per-step refuse-loud (R042)."""

    def _run(self, cfg, gmail, **over):
        from orchestrator import ledger as _ledger
        kwargs = dict(
            gmail_authenticate_fn=lambda: gmail,
            led=_ledger.Ledger(cfg.ledger_dir),
            first_prospect={"name": "Dana Reyes", "email": "dana@loopwell.example"},
            now=_W4_NOW, migration_apply_fn=lambda: None,
        )
        kwargs.update(over)
        return _mt.run_init_wizard(cfg, **kwargs)

    def test_happy_path_completes_and_emits(self, tmp_path) -> None:
        from orchestrator import ledger as _ledger
        cfg = _wizard_config(tmp_path)
        gmail = _FakeGmail()
        result = self._run(cfg, gmail)
        assert result["completed"] is True
        assert result["wizard_steps"] == list(_mt.INIT_WIZARD_STEPS)
        assert len(gmail.sent) == 1
        # The first_prospect step emitted an `enrolled` event into the ledger.
        types = {e.to_dict()["type"] for e in _ledger.Ledger(cfg.ledger_dir).all_events()}
        assert {"enrolled", "init_wizard_completed"} <= types

    def test_refuses_loud_when_gmail_send_scope_missing(self, tmp_path) -> None:
        cfg = _wizard_config(tmp_path, scopes=frozenset({"gmail.readonly"}))
        with pytest.raises(_mt.InitWizardError) as ei:
            self._run(cfg, _FakeGmail())
        assert ei.value.step == "gmail_oauth"

    def test_refuses_loud_when_auth_returns_no_sender(self, tmp_path) -> None:
        cfg = _wizard_config(tmp_path)
        with pytest.raises(_mt.InitWizardError) as ei:
            self._run(cfg, _FakeGmail(sender_email=""))
        assert ei.value.step == "gmail_oauth"

    def test_refuses_loud_when_test_send_does_not_round_trip(self, tmp_path) -> None:
        cfg = _wizard_config(tmp_path)
        with pytest.raises(_mt.InitWizardError) as ei:
            self._run(cfg, _FakeGmail(round_trips=False))
        assert ei.value.step == "test_send"
        # NO init_wizard_completed when a step refused-loud.
        from orchestrator import ledger as _ledger
        assert not [e for e in _ledger.Ledger(cfg.ledger_dir).all_events()
                    if e.to_dict()["type"] == "init_wizard_completed"]

    def test_refuses_loud_when_send_raises(self, tmp_path) -> None:
        cfg = _wizard_config(tmp_path)
        with pytest.raises(_mt.InitWizardError) as ei:
            self._run(cfg, _FakeGmail(raise_on_send=True))
        assert ei.value.step == "test_send"

    def test_idempotent_rerun_is_noop(self, tmp_path) -> None:
        from orchestrator import ledger as _ledger
        cfg = _wizard_config(tmp_path)
        gmail = _FakeGmail()
        self._run(cfg, gmail)
        n_events = len(_ledger.Ledger(cfg.ledger_dir).all_events())
        rerun = self._run(cfg, gmail)
        assert rerun["completed"] is False and rerun["status"] == "already_completed"
        assert len(gmail.sent) == 1
        assert len(_ledger.Ledger(cfg.ledger_dir).all_events()) == n_events
