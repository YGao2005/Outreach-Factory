"""L0 — spine-liveness golden path (CI-blocking layer).

The binding definition-of-done: a real persona's outreach goes end-to-end
through the orchestrator SPINE (Python primitives), every stage transition is
visible, and the funnel SEES the run. External boundaries (Gmail/LinkedIn/LLM)
are mocked here; the real-LLM/real-send layer is L1 (see GOLDEN-PATH-HARNESS.md).

Each test is a labeled thread-in from §5 of the spec. Tests that are RED against
current `main` are the executable Tier-3 punch-list — they are marked xfail with
the exact next step, NOT skipped, so they stay visible in CI output.

Discipline (from the project's drift history — all 3 Pillar H P1s were assumed
signatures): every call here uses a signature derived from the source, not
narrative. If an assertion fails on a signature, that is a real finding.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest


# --------------------------------------------------------------------------
# Helper: the canonical lifecycle-event sequence the FUNNEL reads.
# Stage markers (research_complete/draft_complete/review_approved) are the
# spine's expected inputs from the agent layer (L1); appended here directly.
# `ledger._STAGE_BY_EVENT_TYPE` maps: enrolled→queued, research_complete→
# researched, draft_complete→drafted, review_approved→ready, *_confirmed→sent,
# reply_classified→replied, conversation_outcome→outcome_terminal.
# --------------------------------------------------------------------------
def _emit_funnel_contract_sequence(led, persona, now: datetime):
    pid = "p_" + persona["prospect"]["name"].lower().replace(" ", "_").replace(".", "")
    iid = "snd_" + pid

    def ts(mins_ago: int) -> str:
        return (now - timedelta(minutes=mins_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    sequence = [
        {"type": "enrolled", "person_id": pid, "channel": "email", "ts": ts(60),
         "source_skill": persona["pipeline"][0]},
        {"type": "research_complete", "person_id": pid, "ts": ts(50)},
        {"type": "draft_complete", "person_id": pid, "ts": ts(40)},
        {"type": "review_approved", "person_id": pid, "ts": ts(30)},
        {"type": "send_intent", "person_id": pid, "intent_id": iid, "channel": "email", "ts": ts(25)},
        {"type": "send_confirmed", "person_id": pid, "intent_id": iid, "channel": "email", "ts": ts(24)},
        {"type": "reply_received", "person_id": pid, "channel": "email", "ts": ts(10)},
        {"type": "reply_classified", "person_id": pid, "channel": "email",
         "classification_method": "rule", "category": persona["expected_reply_class"], "ts": ts(9)},
        {"type": "conversation_outcome", "person_id": pid, "channel": "email",
         "outcome": "closed_won", "ts": ts(5)},
    ]
    for ev in sequence:
        led.append(ev)
    return pid, iid


class TestGoldenPathL0Aiyara:
    """L0 thread-in for the TRAINING persona (Aiyara). One test per pillar."""

    # ---- Pillar E: discovery → real `enrolled` emit -----------------------
    def test_pillar_E_enrollment_emits_enrolled(self, tmp_path, tmp_ledger, aiyara_persona):
        from orchestrator import enrollment

        vault = tmp_path / "vault"
        (vault / "10 People").mkdir(parents=True)
        cfg = {"vault": {"path": str(vault), "people_dir": "10 People",
                         "queue_subdir": "🟦 Queue", "active_subdir": "🟧 Active"}}
        res = enrollment.enroll_person(
            aiyara_persona["prospect"]["name"],
            emails=[aiyara_persona["prospect"]["email"]],
            cfg=cfg,
        )
        assert res["status"] == "created", f"Pillar E — enroll_person status: {res}"
        types = {e.to_dict()["type"] for e in tmp_ledger.all_events()}
        assert "enrolled" in types, f"Pillar E — no `enrolled` event; got {types}"

    # ---- Pillar A: policy gate refuses a duplicate cold-pitch -------------
    def test_pillar_A_policy_blocks_duplicate_cold_pitch(self, tmp_ledger, golden_now):
        from orchestrator.policy import engine, cooldown as cd, types as t

        pid, iid = "p_dana", "snd_prior"
        prior = (golden_now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        tmp_ledger.append({"type": "send_intent", "person_id": pid, "intent_id": iid,
                           "channel": "email", "register": "cold-pitch", "ts": prior})
        tmp_ledger.append({"type": "send_confirmed", "person_id": pid, "intent_id": iid,
                           "channel": "email", "ts": prior})

        rule = cd.NoDuplicateRegisterRule(name="no-double-cold-pitch",
                                          block_when={"register": "cold-pitch"})
        ctx = t.RuleContext(person_id=pid, channel="email", register="cold-pitch",
                            email="dana@loopwell.example", email_domain="loopwell.example",
                            now=golden_now, timezone="UTC", ledger=tmp_ledger)
        verdict = engine.evaluate([rule], ctx)
        assert isinstance(verdict, t.Block), \
            f"Pillar A — expected Block on duplicate cold-pitch, got {verdict!r}"

    # ---- Pillar G: the funnel SEES a full golden-path run (killer) --------
    def test_pillar_G_funnel_nonempty_after_full_run(self, tmp_ledger, aiyara_persona, golden_now):
        from orchestrator import funnel

        _emit_funnel_contract_sequence(tmp_ledger, aiyara_persona, golden_now)
        report = funnel.build_report(tmp_ledger, now=golden_now)
        stages = report["prospect_funnel"]["per_stage_event_count"]

        assert stages["queued"] >= 1, f"Pillar G — funnel blind to enrolled; {stages}"
        assert stages["sent"] >= 1, f"Pillar G — funnel blind to send_confirmed; {stages}"
        assert stages["replied"] >= 1, f"Pillar G — funnel blind to reply_classified; {stages}"
        assert stages["outcome_terminal"] >= 1, f"Pillar G — funnel blind to outcome; {stages}"

    # ---- Pillar H: the daemon initializes against the golden ledger -------
    def test_pillar_H_daemon_initializes(self, tmp_path):
        from orchestrator.daemon import DaemonConfig, init_daemon

        (tmp_path / "vault").mkdir()
        (tmp_path / "ledger").mkdir()
        cfg = DaemonConfig(vault_dir=tmp_path / "vault", ledger_dir=tmp_path / "ledger")
        runner = init_daemon(
            cfg,
            migration_apply_fn=lambda: None,
            otel_meter_init_fn=lambda *a, **k: None,
            otel_tracer_init_fn=lambda *a, **k: None,
            prometheus_start_fn=lambda *a, **k: None,
        )
        assert runner.lifecycle_state == "initializing", \
            f"Pillar H — daemon init state: {runner.lifecycle_state}"


class TestGoldenPathL0MultiTenant:
    """L0 thread-in for Pillar I (multi-tenant) — §5: the golden path runs for
    BOTH personas in ISOLATED per-tenant ledgers; zero cross-tenant leak.

    This is the Week 2 slice of the §5 Pillar I assertion (the full
    both-personas-end-to-end-under-the-daemon run is the Week 6 stable-flip).
    The real Week 2 primitives — `init_multi_tenant` +
    `resolve_per_tenant_ledger_dir` (ADR-0070 D371) — build two isolated
    tenants from the personas' own `tenant_id`s, and the funnel sees each run
    without the tenants' event streams crossing."""

    def test_pillar_I_per_tenant_isolated_ledgers_zero_leak(
        self, tmp_path, aiyara_persona, scholarfeed_persona, golden_now,
    ):
        from orchestrator import funnel, ledger as _ledger
        from orchestrator.multi_tenant import (
            TenantConfig, init_multi_tenant, resolve_per_tenant_ledger_dir,
        )

        base_ledger = tmp_path / "ledgers"

        def _cfg(persona):
            tid = persona["tenant_id"]
            root = tmp_path / tid
            # Per-tenant ledger dir resolved by the real Week 2 primitive.
            return TenantConfig(
                tenant_id=tid,
                vault_dir=root / "vault",
                ledger_dir=resolve_per_tenant_ledger_dir(base_ledger, tenant_id=tid),
                policy_dir=root / "policy",
                oauth_token_path=root / "oauth.json",
                oauth_token_scopes=frozenset({"gmail.send"}),
                grafana_folder_uid=f"folder-{tid}",
            )

        # The real Week 2 body constructs the registry (shared_install_dir must
        # exist — tmp_path does — and refuses-loud on duplicate tenant_id).
        registry = init_multi_tenant(
            [_cfg(aiyara_persona), _cfg(scholarfeed_persona)],
            shared_install_dir=tmp_path,
        )
        assert set(registry.tenants) == {"aiyara", "scholarfeed"}, \
            f"Pillar I — registry tenants: {set(registry.tenants)}"

        # Run each persona's golden funnel-contract sequence into its OWN
        # per-tenant ledger.
        leds, pids = {}, {}
        for persona in (aiyara_persona, scholarfeed_persona):
            tid = persona["tenant_id"]
            led = _ledger.Ledger(registry.tenants[tid].ledger_dir)
            pids[tid], _ = _emit_funnel_contract_sequence(led, persona, golden_now)
            leds[tid] = led

        # Isolation: distinct ledger dirs, each under the shared base.
        dir_a = registry.tenants["aiyara"].ledger_dir
        dir_s = registry.tenants["scholarfeed"].ledger_dir
        assert dir_a != dir_s and dir_a.parent == base_ledger and dir_s.parent == base_ledger, \
            f"Pillar I — per-tenant ledger dirs not isolated: {dir_a} / {dir_s}"
        assert pids["aiyara"] != pids["scholarfeed"], \
            f"Pillar I — personas collide on person_id: {pids}"

        # Zero cross-tenant leak + the funnel SEES each tenant's run.
        for tid, led in leds.items():
            seen = {e.to_dict().get("person_id") for e in led.all_events()}
            assert seen == {pids[tid]}, \
                f"Pillar I — cross-tenant leak in {tid} ledger: {seen}"
            stages = funnel.build_report(led, now=golden_now)["prospect_funnel"]["per_stage_event_count"]
            assert stages["sent"] >= 1, f"Pillar I — funnel blind to {tid} run: {stages}"

    def test_pillar_I_w3_container_and_grafana_isolation(
        self, tmp_path, aiyara_persona, scholarfeed_persona,
    ):
        """Pillar I Week 3 (ADR-0072) — the per-tenant CONTAINER surface and
        the per-tenant GRAFANA surface preserve the same zero-cross-tenant-leak
        invariant the W2 test proved for ledgers. `build_per_tenant_compose_config`
        emits one daemon service per tenant whose volume mounts reference ONLY
        that tenant's own host directories; `resolve_per_tenant_grafana_folders`
        gives each tenant a distinct dashboard folder."""
        from orchestrator.multi_tenant import (
            DEFAULT_DAEMON_IMAGE, TenantConfig, build_per_tenant_compose_config,
            init_multi_tenant, resolve_per_tenant_grafana_folders,
            resolve_per_tenant_ledger_dir, resolve_per_tenant_policy_dir,
        )

        base = tmp_path / "ledgers"

        def _cfg(persona):
            tid = persona["tenant_id"]
            root = tmp_path / tid
            return TenantConfig(
                tenant_id=tid,
                vault_dir=root / "vault",
                ledger_dir=resolve_per_tenant_ledger_dir(base, tenant_id=tid),
                policy_dir=resolve_per_tenant_policy_dir(base, tenant_id=tid),
                oauth_token_path=root / "oauth.json",
                oauth_token_scopes=frozenset({"gmail.send"}),
                grafana_folder_uid=f"folder-{tid}",
            )

        registry = init_multi_tenant(
            [_cfg(aiyara_persona), _cfg(scholarfeed_persona)],
            shared_install_dir=tmp_path,
        )

        # --- Container surface: one service per tenant, isolated volumes. ---
        compose = build_per_tenant_compose_config(registry)
        services = compose["services"]
        assert set(services) == {"daemon-aiyara", "daemon-scholarfeed"}, \
            f"Pillar I W3 — compose services: {set(services)}"

        host_paths_by_tid = {}
        other = {"aiyara": "scholarfeed", "scholarfeed": "aiyara"}
        for tid in ("aiyara", "scholarfeed"):
            svc = services[f"daemon-{tid}"]
            assert svc["image"] == DEFAULT_DAEMON_IMAGE, \
                f"Pillar I W3 — {tid} not on the shared image: {svc['image']}"
            assert svc["environment"]["OUTREACH_FACTORY_TENANT_ID"] == tid, \
                f"Pillar I W3 — {tid} tenant_id env: {svc['environment']}"
            # Host side of each `host:container[:ro]` mount must carry THIS
            # tenant's own id as a directory segment and never the other
            # tenant's — no service can reach into a foreign tenant's subtree.
            hosts = {v.split(":")[0] for v in svc["volumes"]}
            for h in hosts:
                parts = Path(h).parts
                assert tid in parts, \
                    f"Pillar I W3 — {tid} mount lacks its own tenant segment: {h}"
                assert other[tid] not in parts, \
                    f"Pillar I W3 — {tid} mounts foreign tenant {other[tid]}'s path: {h}"
            host_paths_by_tid[tid] = hosts

        leak = host_paths_by_tid["aiyara"] & host_paths_by_tid["scholarfeed"]
        assert not leak, f"Pillar I W3 — cross-tenant volume-mount leak: {leak}"

        # --- Grafana surface: one distinct dashboard folder per tenant. ---
        folders = resolve_per_tenant_grafana_folders(registry)
        assert folders == {"aiyara": "folder-aiyara", "scholarfeed": "folder-scholarfeed"}, \
            f"Pillar I W3 — grafana folders: {folders}"
        assert len(set(folders.values())) == len(folders), \
            f"Pillar I W3 — grafana folder UIDs not disjoint: {folders}"

    def test_pillar_I_w5_ci_discipline_and_per_tenant_slo_isolation(
        self, tmp_path, aiyara_persona, scholarfeed_persona, golden_now,
    ):
        """Pillar I Week 5 (ADR-0074 trajectory slot) — the W5 surface threads
        into the golden path: (1) the per-tenant SLO surface scores each tenant
        over its OWN ledger with zero cross-tenant aggregation + the privacy
        invariant; (2) the CI cochange-discipline refuses-loud on an unaccompanied
        pricing-table change; (3) R040 — per-tenant ledger dirs are disjoint
        subtrees (no write contention via aliasing); (4) R041 — the per-tenant
        daemon's startup latency is operator-visible via `daemon_started`."""
        from orchestrator import ledger as _ledger
        from orchestrator.ci import check_cochange_discipline
        from orchestrator.daemon import DaemonConfig, build_daemon_started_payload
        from orchestrator.daemon.runner import _compute_config_hash
        from orchestrator.multi_tenant import (
            TenantConfig, collect_per_tenant_slo_violations, init_multi_tenant,
            resolve_per_tenant_ledger_dir,
        )
        from orchestrator.observability import SLOViolation

        base_ledger = tmp_path / "ledgers"

        def _cfg(persona):
            tid = persona["tenant_id"]
            root = tmp_path / tid
            return TenantConfig(
                tenant_id=tid, vault_dir=root / "vault",
                ledger_dir=resolve_per_tenant_ledger_dir(base_ledger, tenant_id=tid),
                policy_dir=root / "policy", oauth_token_path=root / "oauth.json",
                oauth_token_scopes=frozenset({"gmail.send"}),
                grafana_folder_uid=f"folder-{tid}",
            )

        registry = init_multi_tenant(
            [_cfg(aiyara_persona), _cfg(scholarfeed_persona)],
            shared_install_dir=tmp_path,
        )

        # Both personas run end-to-end into their OWN per-tenant ledgers. The
        # funnel sequence's send_intent→send_confirmed gap is 60s, which trips
        # the 5s send_latency_p99 SLO — a real violation computed per-tenant.
        leds = {}
        for persona in (aiyara_persona, scholarfeed_persona):
            tid = persona["tenant_id"]
            led = _ledger.Ledger(registry.tenants[tid].ledger_dir)
            _emit_funnel_contract_sequence(led, persona, golden_now)
            leds[tid] = led

        window = timedelta(hours=2)

        # (1a) Real detector, per-tenant. Each tenant is scored over its own
        # ledger; both surface the send_latency_p99 violation.
        per_tenant = collect_per_tenant_slo_violations(
            registry, leds, since_window=window, now=golden_now,
        )
        assert set(per_tenant) == {"aiyara", "scholarfeed"}, \
            f"Pillar I W5 — per-tenant SLO keys: {set(per_tenant)}"
        for tid, violations in per_tenant.items():
            names = {v.slo_name for v in violations}
            assert "send_latency_p99" in names, \
                f"Pillar I W5 — {tid} missing per-tenant send_latency_p99: {names}"

        # (1b) Privacy invariant: an SLOViolation carries NO per-Person field —
        # tenant A's SLO surface cannot leak tenant B's per-Person data.
        slo_fields = {f.name for f in __import__("dataclasses").fields(SLOViolation)}
        forbidden = {"person_id", "body", "source_list", "draft_body", "raw_body",
                     "claim_text", "query_text", "exemplar_body", "dossier_body"}
        assert slo_fields & forbidden == set(), \
            f"Pillar I W5 — SLOViolation leaks a per-Person field: {slo_fields & forbidden}"

        # (1c) Isolation via the TEST-ONLY detect_fn seam: each tenant's detect
        # call receives EXACTLY that tenant's own ledger object — never the
        # other's (the direct cross-tenant-no-leak proof).
        seen: list = []

        def _spy_detect(led, *, since_window, now=None, slo_config=None):
            seen.append(led)
            return []

        collect_per_tenant_slo_violations(
            registry, leds, since_window=window, now=golden_now, detect_fn=_spy_detect,
        )
        assert seen == [leds[tid] for tid in registry.tenants], \
            "Pillar I W5 — per-tenant SLO detect did not receive each tenant's own ledger in isolation"

        # (2) CI cochange-discipline: budget.py alone refuses-loud; co-changing
        # ADR-0006 satisfies it (the price-update == ADR-amendment discipline).
        budget = "orchestrator/policy/budget.py"
        adr6 = "docs/adr/0006-budget-rules-and-cost-events.md"
        assert check_cochange_discipline([budget]), \
            "Pillar I W5 — CI must refuse an unaccompanied budget.py (pricing-table) change"
        assert not check_cochange_discipline([budget, adr6]), \
            "Pillar I W5 — CI must pass when budget.py + ADR-0006 co-change"

        # (3) R040 — per-tenant ledger dirs are disjoint subtrees under the
        # shared base (no aliasing → no cross-tenant write contention).
        dirs = {tid: registry.tenants[tid].ledger_dir for tid in registry.tenants}
        assert len(set(dirs.values())) == len(dirs), \
            f"Pillar I W5 (R040) — per-tenant ledger dirs alias: {dirs}"
        for d in dirs.values():
            assert d.parent == base_ledger, \
                f"Pillar I W5 (R040) — ledger dir escaped the shared base: {d}"

        # (4) R041 — the per-tenant daemon's startup latency is operator-visible:
        # `daemon_started` surfaces `startup_seconds` (the Grafana panel source).
        cfg = DaemonConfig(vault_dir=tmp_path / "v", ledger_dir=dirs["aiyara"],
                           tenant_id="aiyara")
        started = build_daemon_started_payload(
            pid=4321, version="1.0.0", config_hash=_compute_config_hash(cfg),
            startup_seconds=1.5,
        )
        assert started["startup_seconds"] == 1.5, \
            f"Pillar I W5 (R041) — daemon_started must surface startup_seconds: {started}"

    def test_pillar_I_w4_init_wizard_zero_to_test_send(
        self, tmp_path, aiyara_persona, scholarfeed_persona, golden_now,
    ):
        """Pillar I Week 4 (ADR-0073) — the init-wizard surface threads into the
        golden path: a NEW operator goes zero (clean clone) → Gmail OAuth →
        vault setup → first prospect → a successful test send, and
        `init_wizard_completed` lands in THIS tenant's ledger. The send boundary
        is the FakeGmail seam at L0 (the real OAuth round-trip was human-verified
        once, 2026-05-28; §0 forbids re-running it in the loop); the < 10-min
        wall-clock compresses to the deterministic-clock anchor. Cross-tenant
        isolation (D375 invariant (a)) + init-wizard idempotence (D375 invariant
        (c)) both hold."""
        from orchestrator import ledger as _ledger
        from orchestrator.multi_tenant import (
            INIT_WIZARD_STEPS, TenantConfig, init_multi_tenant,
            resolve_per_tenant_ledger_dir, run_init_wizard,
        )

        class _WizardGmail:
            """FakeGmail with the send + read-back surface the wizard's
            test_send step exercises (tests/test_reconcile.py:78 shape + send_email)."""

            def __init__(self, sender_email="operator@gmail.test"):
                self.sender_email = sender_email
                self.sent: list = []

            def send_email(self, to, subject, body, extra_headers=None, **_kw):
                mid = f"m_{len(self.sent) + 1}"
                self.sent.append({"id": mid, "threadId": f"th_{mid}", "to": to,
                                  "headers": dict(extra_headers or {}), "body": body})
                return mid, f"th_{mid}"

            def search_messages(self, query, max_results=100):
                iid = "X-Outreach-Intent-Id"
                return [{"id": m["id"], "threadId": m["threadId"]} for m in self.sent
                        if query in m["body"] or query == m["headers"].get(iid)]

            def get_message(self, msg_id):
                return next((m for m in self.sent if m["id"] == msg_id), None)

        base_ledger = tmp_path / "ledgers"

        def _cfg(persona):
            tid = persona["tenant_id"]
            root = tmp_path / tid
            return TenantConfig(
                tenant_id=tid, vault_dir=root / "vault",
                ledger_dir=resolve_per_tenant_ledger_dir(base_ledger, tenant_id=tid),
                policy_dir=root / "policy", oauth_token_path=root / "oauth.json",
                oauth_token_scopes=frozenset({"gmail.send"}),
                grafana_folder_uid=f"folder-{tid}",
            )

        registry = init_multi_tenant(
            [_cfg(aiyara_persona), _cfg(scholarfeed_persona)],
            shared_install_dir=tmp_path,
        )

        # The NEW operator (aiyara tenant) runs the init wizard zero-to-test-send.
        aiyara = registry.tenants["aiyara"]
        led_a = _ledger.Ledger(aiyara.ledger_dir)
        gmail = _WizardGmail()
        result = run_init_wizard(
            aiyara, gmail_authenticate_fn=lambda: gmail, led=led_a,
            first_prospect={"name": aiyara_persona["prospect"]["name"],
                            "email": aiyara_persona["prospect"]["email"]},
            now=golden_now, migration_apply_fn=lambda: None,
        )

        # Zero-to-test-send completed all four steps + a real send round-tripped.
        assert result["completed"] is True, f"Pillar I W4 — wizard incomplete: {result}"
        assert result["wizard_steps"] == list(INIT_WIZARD_STEPS), \
            f"Pillar I W4 — wizard steps: {result['wizard_steps']}"
        assert len(gmail.sent) == 1, f"Pillar I W4 — test send did not happen: {gmail.sent}"

        # init_wizard_completed lands in THIS tenant's ledger; spine field is `type`.
        wiz = [e.to_dict() for e in led_a.all_events()
               if e.to_dict()["type"] == "init_wizard_completed"]
        assert len(wiz) == 1 and wiz[0]["tenant_id"] == "aiyara" \
            and wiz[0]["_emitted_by"] == "multi_tenant", \
            f"Pillar I W4 — init_wizard_completed payload: {wiz}"

        # Cross-tenant isolation (D375 invariant (a)): scholarfeed's ledger never
        # saw the aiyara wizard run.
        led_s = _ledger.Ledger(registry.tenants["scholarfeed"].ledger_dir)
        assert [e for e in led_s.all_events()
                if e.to_dict()["type"] == "init_wizard_completed"] == [], \
            "Pillar I W4 — cross-tenant leak: scholarfeed ledger saw aiyara's wizard"

        # Idempotence (D375 invariant (c)): a re-run (fresh handle, same dir) is a
        # NO-OP — no second send, no second emit.
        rerun = run_init_wizard(
            aiyara, gmail_authenticate_fn=lambda: gmail,
            led=_ledger.Ledger(aiyara.ledger_dir),
            first_prospect={"name": aiyara_persona["prospect"]["name"],
                            "email": aiyara_persona["prospect"]["email"]},
            now=golden_now, migration_apply_fn=lambda: None,
        )
        assert rerun["completed"] is False and rerun["status"] == "already_completed", \
            f"Pillar I W4 — re-run not a NO-OP: {rerun}"
        assert len(gmail.sent) == 1, "Pillar I W4 — idempotence: re-run re-sent the test email"
        again = [e.to_dict() for e in _ledger.Ledger(aiyara.ledger_dir).all_events()
                 if e.to_dict()["type"] == "init_wizard_completed"]
        assert len(again) == 1, \
            f"Pillar I W4 — idempotence: second init_wizard_completed emitted: {again}"

    def test_pillar_I_w6_both_personas_end_to_end_under_daemon(
        self, tmp_path, aiyara_persona, scholarfeed_persona, golden_now,
    ):
        """Pillar I Week 6 (Stable flip) — the §5 Pillar I assertion's FULL
        form, which the W2 row named as the Week 6 stable-flip: BOTH personas
        run the golden path end-to-end in ISOLATED per-tenant ledgers UNDER THE
        DAEMON (each tenant's daemon reaches "ready" via the REAL
        DaemonRunner.run, then shuts down cleanly), the funnel SEES each run,
        and zero cross-tenant leak holds. The 3-row OSS-bring-up / init-wizard /
        CI binding exit-criterion lives at tests/test_multi_channel_coherence.py
        ::TestPillarIExitCriterion (exercised under gate.py --full)."""
        import asyncio
        from contextlib import nullcontext

        from orchestrator import funnel, ledger as _ledger
        from orchestrator.daemon import DaemonConfig, DaemonRunner
        from orchestrator.multi_tenant import (
            TenantConfig, init_multi_tenant, resolve_per_tenant_ledger_dir,
        )
        from tests._daemon_test_helpers import (
            _StubAppRunner, _TEST_PAST_STARTED_AT_TS,
        )

        base_ledger = tmp_path / "ledgers"

        def _cfg(persona):
            tid = persona["tenant_id"]
            root = tmp_path / tid
            return TenantConfig(
                tenant_id=tid, vault_dir=root / "vault",
                ledger_dir=resolve_per_tenant_ledger_dir(base_ledger, tenant_id=tid),
                policy_dir=root / "policy", oauth_token_path=root / "oauth.json",
                oauth_token_scopes=frozenset({"gmail.send"}),
                grafana_folder_uid=f"folder-{tid}",
            )

        registry = init_multi_tenant(
            [_cfg(aiyara_persona), _cfg(scholarfeed_persona)],
            shared_install_dir=tmp_path,
        )
        assert set(registry.tenants) == {"aiyara", "scholarfeed"}, \
            f"Pillar I W6 — registry tenants: {set(registry.tenants)}"

        async def _run_daemon_to_ready(tid):
            vault = tmp_path / tid / "vault"
            led_dir = registry.tenants[tid].ledger_dir
            vault.mkdir(parents=True, exist_ok=True)
            led_dir.mkdir(parents=True, exist_ok=True)
            runner = DaemonRunner(
                config=DaemonConfig(vault_dir=vault, ledger_dir=led_dir, tenant_id=tid),
                config_hash="a" * 64, pid=4321,
                started_at_ts=_TEST_PAST_STARTED_AT_TS, version="0.1.0",
                lifecycle_state="initializing",
            )
            emits: list = []
            task = asyncio.create_task(runner.run(
                attach_signal_handlers_fn=lambda r, **kw: None,
                serve_health_endpoint_fn=lambda port, **kw: asyncio.sleep(
                    0, result=_StubAppRunner()),
                traced_stage_fn=lambda stage, operation, **kw: nullcontext(),
                emit_fn=emits.append, tick_seconds=0.001,
            ))
            await asyncio.sleep(0.01)
            ready = runner.lifecycle_state == "ready"
            runner.shutdown("operator_requested", emit_fn=emits.append)
            return ready, await task, emits

        pids = {}
        for persona in (aiyara_persona, scholarfeed_persona):
            tid = persona["tenant_id"]
            # The tenant's daemon reaches "ready" then shuts down cleanly.
            ready, exit_code, emits = asyncio.run(_run_daemon_to_ready(tid))
            assert ready, f"Pillar I W6 — {tid} daemon did not reach ready"
            assert exit_code == 0, f"Pillar I W6 — {tid} daemon unclean exit: {exit_code}"
            assert any(e["type"] == "daemon_started" for e in emits), \
                f"Pillar I W6 — {tid} emitted no daemon_started: {[e['type'] for e in emits]}"
            # The tenant's golden path runs into its OWN ledger; funnel sees it.
            led = _ledger.Ledger(registry.tenants[tid].ledger_dir)
            pids[tid], _ = _emit_funnel_contract_sequence(led, persona, golden_now)
            stages = funnel.build_report(led, now=golden_now)["prospect_funnel"]["per_stage_event_count"]
            assert stages["sent"] >= 1 and stages["outcome_terminal"] >= 1, \
                f"Pillar I W6 — funnel blind to {tid} run: {stages}"

        # Zero cross-tenant leak: each ledger only ever saw its own person_id.
        assert pids["aiyara"] != pids["scholarfeed"], \
            f"Pillar I W6 — personas collide on person_id: {pids}"
        for tid in ("aiyara", "scholarfeed"):
            led = _ledger.Ledger(registry.tenants[tid].ledger_dir)
            seen = {e.to_dict().get("person_id") for e in led.all_events()
                    if e.to_dict().get("person_id")}
            assert seen == {pids[tid]}, \
                f"Pillar I W6 — cross-tenant leak in {tid}: {seen}"


class TestGoldenPathL0Findings:
    """Findings the harness surfaces against current `main` — the punch-list.
    These are honest reds: xfail with the exact next step so they stay in CI."""

    def test_finding1_funnel_counts_real_state_transitions(self, tmp_ledger, golden_now):
        """FINDING-1 CLOSED (funnel-side fix; .planning/GOLDEN-PATH-HARNESS.md): the
        production transition path emits type='state_transition'; the funnel now
        counts it by its `to` stage. Permanent regression barrier — must stay green."""
        from orchestrator import state_machine as sm, funnel

        # record_transition writes via OUTREACH_FACTORY_LEDGER_DIR (set by tmp_ledger).
        sm.record_transition("p_x", "queued", "researched", skill="research-prospect")
        types = {e.to_dict()["type"] for e in tmp_ledger.all_events()}
        assert "state_transition" in types, f"real transition path emits {types}"

        report = funnel.build_report(tmp_ledger, now=golden_now)
        stages = report["prospect_funnel"]["per_stage_event_count"]
        assert stages["researched"] >= 1, (
            f"FINDING-1 — funnel must count state_transition(to=researched); got {stages}")

    def test_pillar_C_reconcile_pass_a_synthesizes_confirmed(self, tmp_ledger, golden_now):
        from orchestrator import reconcile as _reconcile

        iid = "snd_golden_c"
        old = (golden_now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        tmp_ledger.append({"type": "send_intent", "person_id": "p_c", "intent_id": iid,
                           "channel": "email", "ts": old})

        # Mirrors the canonical FakeGmail at tests/test_reconcile.py:78 — Pass A's
        # _search_intent calls search_messages → get_message (reverified against the
        # X-Outreach-Intent-Id header). The prior stub omitted get_message, so the
        # AttributeError was swallowed by run_pass_a and nothing confirmed.
        class _FakeGmailPassA:
            sender_email = "me@example.test"

            def search_messages(self, query, max_results=100):
                return [{"id": "m1", "threadId": "th_1"}]

            def get_message(self, msg_id):
                return {"id": "m1", "threadId": "th_1", "payload": {"headers": [
                    {"name": "X-Outreach-Intent-Id", "value": iid}]}}

            def get_thread(self, thread_id):
                return {"id": "th_1", "messages": [
                    {"id": "m1", "headers": [{"name": "X-Outreach-Intent-Id", "value": iid}]}]}

        _reconcile.reconcile(passes="A", since=golden_now - timedelta(days=1),
                             led=tmp_ledger, gmail=_FakeGmailPassA(),
                             apply=True, min_intent_age=timedelta(0))
        confirmed = [e.to_dict() for e in tmp_ledger.all_events()
                     if e.to_dict()["type"] == "send_confirmed"]
        assert confirmed, "Pillar C — reconcile did not confirm the orphaned send_intent"
        # SYNTHESIZED (not appended directly): the recovery marker + intent link prove
        # it came from Pass A, not the test.
        assert confirmed[0].get("_recovered_by") == "reconcile", \
            f"Pillar C — send_confirmed not synthesized by reconcile: {confirmed[0]}"
        assert confirmed[0].get("intent_id") == iid, \
            f"Pillar C — send_confirmed not linked to the send_intent: {confirmed[0]}"


class TestGoldenPathL0SecurityCompliance:
    """L0 thread-in for Pillar J (security + compliance) — the §5 assertion:
    *"send carries CAN-SPAM footer + ``List-Unsubscribe`` header; ``forget
    --person`` purges persona (tombstone) leaving audit."* Plus the rest of
    the J surface (J1 OAuth rotation, J8 audit export, R001 identity audit,
    J2/J3 scanning).

    These are the executable Pillar J punch-list — xfail with the exact next
    step (per ADR-0076 D387's per-week trajectory) so they stay visible in
    CI until the per-week (Ralph) / FENCED (human) build turns each green.
    Discipline: every call uses a signature derived from
    ``orchestrator/security/__init__.py`` (ADR-0076 D377), not narrative.
    When an xfail flips green via ``gate.py --require``, REMOVE its marker so
    it becomes a permanent regression barrier (RALPH-PROMPT §4)."""

    # ---- J7 (Ralph W4): CAN-SPAM footer + one-click List-Unsubscribe ------
    # GREEN since W4 (ADR-0079 D394) — permanent regression barrier (xfail removed).
    def test_pillar_J_send_carries_canspam_footer_and_list_unsubscribe_header(self):
        from orchestrator.security import (
            CANSPAM_REQUIRED_HEADERS, SecurityConfig,
            build_canspam_footer, build_list_unsubscribe_headers,
        )

        cfg = SecurityConfig(
            physical_mailing_address="Aiyara, 2120 University Ave, Berkeley, CA 94704, USA",
            unsubscribe_base_url="https://aiyara.example/u",
        )
        unsub_url = f"{cfg.unsubscribe_base_url}?t=tok_dana"

        # Footer carries BOTH the physical mailing address (CAN-SPAM) and the
        # unsubscribe link.
        footer = build_canspam_footer(
            physical_mailing_address=cfg.physical_mailing_address,
            unsubscribe_url=unsub_url,
        )
        assert "Berkeley, CA 94704" in footer, \
            f"J7 — footer missing CAN-SPAM physical address: {footer!r}"
        assert unsub_url in footer, f"J7 — footer missing unsubscribe link: {footer!r}"

        # One-click headers per RFC 8058 + RFC 2369.
        headers = build_list_unsubscribe_headers(unsubscribe_url=unsub_url,
                                                 mailto="mailto:unsub@aiyara.example")
        assert CANSPAM_REQUIRED_HEADERS <= set(headers), \
            f"J7 — missing required headers {CANSPAM_REQUIRED_HEADERS - set(headers)}: {headers}"
        assert unsub_url in headers["List-Unsubscribe"], \
            f"J7 — List-Unsubscribe missing URL: {headers}"
        assert "One-Click" in headers["List-Unsubscribe-Post"], \
            f"J7 — List-Unsubscribe-Post not one-click: {headers}"

    # ---- J1 (W2, ADR-0077): OAuth refresh-and-retry on a mid-batch 401 ----
    # GREEN since ADR-0077 — permanent regression barrier (xfail removed).
    def test_pillar_J_oauth_refresh_and_retry_on_midbatch_401(self, tmp_ledger, golden_now):
        from orchestrator.security import send_with_token_rotation

        calls = {"send": 0, "refresh": 0}

        class _Expired401(Exception):
            pass

        def _send_fn():
            calls["send"] += 1
            if calls["send"] == 1:          # token expired exactly mid-batch
                raise _Expired401("401 invalid_grant")
            return ("m_ok", "th_ok")        # retry after refresh succeeds

        def _refresh_fn():
            calls["refresh"] += 1

        result = send_with_token_rotation(
            _send_fn, refresh_fn=_refresh_fn, led=tmp_ledger,
            tenant_id="aiyara", token_scope="gmail.send", now=golden_now,
        )

        assert result == ("m_ok", "th_ok"), f"J1 — retry did not return the send result: {result}"
        assert calls["refresh"] == 1, f"J1 — refresh not called exactly once: {calls}"
        # The rotation is itself audit-worthy: auth_token_refreshed lands.
        types = [e.to_dict()["type"] for e in tmp_ledger.all_events()]
        assert "auth_token_refreshed" in types, f"J1 — no auth_token_refreshed emit: {types}"

    # ---- J8 (Ralph W3): audit-log export covers the whole run -------------
    # GREEN since W3 (ADR-0078 D391) — permanent regression barrier (xfail removed).
    def test_pillar_J_audit_log_export_covers_golden_run(
        self, tmp_path, tmp_ledger, aiyara_persona, golden_now,
    ):
        from orchestrator.security import export_audit_log

        _emit_funnel_contract_sequence(tmp_ledger, aiyara_persona, golden_now)
        n_before = len(list(tmp_ledger.all_events()))

        out = tmp_path / "audit.jsonl"
        result = export_audit_log(tmp_ledger, out_path=out, out_format="jsonl",
                                  redact=True, now=golden_now)

        assert out.exists(), "J8 — export produced no file"
        # Covers the run: every prior event accounted for in the export count.
        assert result["n_events"] >= n_before, \
            f"J8 — export n_events {result.get('n_events')} < ledger {n_before}"
        # READ-ONLY contract (ADR-0059 D325): export only APPENDS its own
        # audit_log_exported marker; it never rewrites prior events.
        types = [e.to_dict()["type"] for e in tmp_ledger.all_events()]
        assert "audit_log_exported" in types, f"J8 — no audit_log_exported emit: {types}"
        # Redact-by-default: no cleartext per-Person id leaks into the export.
        assert "p_dana_reyes" not in out.read_text(), \
            "J8 — redacted export leaked a cleartext person_id"

    # ---- R001 (Ralph W3): identity-key mutation leaves an audit trail -----
    # GREEN since W3 (ADR-0078 D392) — permanent regression barrier (xfail removed).
    def test_pillar_J_identity_keys_modified_emits_audit(self, tmp_ledger, golden_now):
        from orchestrator.security import build_identity_keys_modified_payload

        ts = golden_now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = build_identity_keys_modified_payload(
            person_id="p_dana_reyes",
            before_keys=["em:dana@loopwell.example"],
            after_keys=["em:dana@loopwell.example", "li:in/dana-reyes"],
            actor="operator", modified_at_ts=ts,
        )
        assert payload["type"] == "identity_keys_modified", f"R001 — type: {payload.get('type')}"
        assert payload["before_keys"] != payload["after_keys"], "R001 — must record the delta"
        assert payload["actor"] == "operator", f"R001 — actor: {payload.get('actor')}"
        assert payload["_emitted_by"] == "security", f"R001 — _emitted_by: {payload.get('_emitted_by')}"

        # The audit event lands in the ledger (the trail manual merges lack today).
        tmp_ledger.append(payload)
        types = [e.to_dict()["type"] for e in tmp_ledger.all_events()]
        assert "identity_keys_modified" in types, f"R001 — audit not in ledger: {types}"

    # ---- J2 + J3 (Ralph W3): supply-chain scanning is wired --------------
    # NOTE: a REPO-STATE assertion, not a persona-flow one — J2/J3 are CI/config
    # surfaces that emit no ledger events (ADR-0076 D378). This is the
    # "zero unpatched CVEs > 14d" *substrate proxy*: the scanning machinery
    # exists + runs. Human disposition of findings is the v1-release gate.
    # GREEN since W3 (ADR-0078 D390) — permanent regression barrier (xfail removed).
    def test_pillar_J_secret_and_dependency_scanning_wired(self):
        from orchestrator.security import SECURITY_SCANNERS

        repo = Path(__file__).resolve().parents[2]
        precommit = repo / ".pre-commit-config.yaml"
        dependabot = repo / ".github" / "dependabot.yml"
        workflows = repo / ".github" / "workflows"

        assert precommit.exists() and "gitleaks" in precommit.read_text(), \
            "J2 — gitleaks not wired in .pre-commit-config.yaml"
        assert dependabot.exists(), "J3 — .github/dependabot.yml missing"
        osv_wired = workflows.is_dir() and any(
            "osv-scanner" in p.read_text() for p in workflows.glob("*.y*ml")
        )
        assert osv_wired, "J3 — no osv-scanner workflow under .github/workflows/"
        # All three documented scanners are accounted for.
        assert SECURITY_SCANNERS == {"gitleaks", "dependabot", "osv-scanner"}, \
            f"J2/J3 — SECURITY_SCANNERS drift: {SECURITY_SCANNERS}"

    # ---- J6: forget crypto-shred. GREEN since 2026-06-01 (ADR-0080 built +
    # un-fenced under human authorship); permanent regression barrier.
    def test_pillar_J_forget_person_crypto_shred_leaves_audit(
        self, tmp_path, tmp_ledger, golden_now,
    ):
        from orchestrator.security import build_gdpr_forget_payload, forget_person

        # The tombstone payload carries a HASH ref, never the cleartext id.
        ts = golden_now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        tomb = build_gdpr_forget_payload(
            person_ref="sha256:deadbeef", key_destroyed=True, n_events_shredded=4,
            suppression_appended=True, vault_purged=True, forgotten_at_ts=ts,
            audit={"requested_by": "operator", "reason": "gdpr_art17"},
        )
        assert tomb["type"] == "gdpr_forget", f"J6 — type: {tomb.get('type')}"
        assert tomb["person_ref"].startswith("sha256:"), f"J6 — person_ref not a hash: {tomb}"
        assert "person_id" not in tomb, "J6 — tombstone leaked a cleartext person_id"
        assert tomb["key_destroyed"] is True, f"J6 — key not shredded: {tomb}"

        # An in-memory keystore implementing the J5 Protocol (the test seam).
        class _FakeKeystore:
            backend = "passphrase_argon2id"

            def __init__(self):
                self._keys = {"p_dana_reyes": b"\x01" * 32}

            def get_key(self, key_id):
                return self._keys[key_id]

            def put_key(self, key_id, key):
                self._keys[key_id] = key

            def destroy_key(self, key_id):
                return self._keys.pop(key_id, None) is not None

        vault = tmp_path / "vault"
        (vault / "10 People").mkdir(parents=True)
        (vault / "10 People" / "Dana Reyes.md").write_text("dana@loopwell.example")
        sup = tmp_path / "suppressions"

        result = forget_person(
            "p_dana_reyes", led=tmp_ledger, vault_dir=vault, suppressions_dir=sup,
            keystore=_FakeKeystore(), now=golden_now,
        )

        # Crypto-shred + suppression + vault purge + audit all landed.
        assert result["key_destroyed"] is True, f"J6 — key not destroyed: {result}"
        assert (sup / "gdpr-forget.yml").exists(), "J6 — suppression entry not appended"
        assert not (vault / "10 People" / "Dana Reyes.md").exists(), "J6 — vault Person not purged"
        types = [e.to_dict()["type"] for e in tmp_ledger.all_events()]
        assert "gdpr_forget" in types, f"J6 — no gdpr_forget tombstone: {types}"

    # ---- J5: credentials encrypted at rest. GREEN since 2026-06-01
    # (ADR-0080 built + un-fenced under human authorship); regression barrier.
    def test_pillar_J_credentials_encrypted_at_rest(self):
        import pytest as _pytest

        from orchestrator.security import (
            CREDENTIAL_KEYSTORE_BACKENDS, decrypt_credential,
            encrypt_credential, resolve_keystore,
        )

        keystore = resolve_keystore(backend="passphrase_argon2id",
                                    passphrase="correct horse battery staple 9z!")
        assert keystore.backend in CREDENTIAL_KEYSTORE_BACKENDS, \
            f"J5 — unknown backend: {keystore.backend}"

        plaintext = b"oauth-refresh-token-secret"
        kid = "aiyara:gmail.send"
        ct = encrypt_credential(plaintext, keystore=keystore, key_id=kid)
        assert ct != plaintext and b"oauth-refresh" not in ct, \
            "J5 — credential not encrypted at rest (plaintext leak)"
        assert decrypt_credential(ct, keystore=keystore, key_id=kid) == plaintext, \
            "J5 — round-trip decrypt mismatch"

        # Crypto-shred (the J6 erasure primitive): destroy the key -> ciphertext
        # is unrecoverable.
        keystore.destroy_key(kid)
        with _pytest.raises(Exception):
            decrypt_credential(ct, keystore=keystore, key_id=kid)
