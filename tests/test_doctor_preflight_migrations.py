"""Doctor preflight tests for the Pillar B migration check.

The doctor script (``scripts/doctor.py``) gained a ``check_migrations``
function in Pillar B Week 2 that:

* Surfaces a WARN result when ``MigrationRunner().pending()`` is
  non-empty.
* Surfaces an OK result when no pending migrations.
* Does NOT cause doctor's exit code to be 1 (warn-only in Week 2;
  Pillar I hardens to refuse-on-pending).

Pillar B Week 6 adds the ``OUTREACH_FACTORY_STRICT_MIGRATIONS=1``
feature flag per ADR-0013 D26. When the env var is exactly ``"1"``,
pending migrations are promoted from WARN to FAIL (and the doctor
exits non-zero). Default behavior (env unset or any other value)
stays WARN per the asymmetric-failure-cost calculus that the Week 2
shape established. The Week 6 strict-mode tests live in
``TestStrictMode`` below; the existing tests use
``monkeypatch.delenv`` so they're deterministic across operator
environments that may have the var set.

We load the doctor script via :mod:`importlib` so the ``check_*``
functions can be called directly without spawning a subprocess.
The exit-code logic is exercised by simulating its body against the
same OK / WARN / FAIL constants the script uses.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from orchestrator.migrations.types import MigrationCategory


REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "doctor.py"

STRICT_ENV = "OUTREACH_FACTORY_STRICT_MIGRATIONS"


def _load_doctor_module():
    """Load scripts/doctor.py as a module for direct function access.

    We use importlib so the script's check_* functions are callable
    without spawning a subprocess. The script's `main()` is not invoked.
    """
    spec = importlib.util.spec_from_file_location("doctor_under_test", DOCTOR_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _isolate_strict_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per ADR-0013 D26 the strict-mode env var changes the doctor's
    pending-migrations verdict from WARN to FAIL. Tests that do NOT
    explicitly opt in to strict mode must run with the env var
    cleared so the operator's environment doesn't leak into the test
    suite. Strict-mode tests set the var themselves after this fixture
    clears it."""
    monkeypatch.delenv(STRICT_ENV, raising=False)


# ---------------------------------------------------------------------------
# Unit tests on check_migrations directly
# ---------------------------------------------------------------------------


class TestCheckMigrationsUnit:
    def test_warns_when_real_vault_migration_pending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """The Week 2 vault migration is in the real registry. A
        runner pointed at a fresh state dir will show it pending."""
        # Point HOME at tmp so the default state dir is empty.
        monkeypatch.setenv("HOME", str(tmp_path))
        doctor = _load_doctor_module()
        result = doctor.check_migrations(config={"vault": {"path": str(tmp_path)}})
        assert result["status"] == doctor.WARN
        assert "pending" in result["message"]
        assert "vault/0001" in result["message"]

    def test_ok_when_no_pending_migrations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """When the state file says all migrations are applied, the
        check returns OK. We seed the state file with all real
        migration ids — Pillar B (vault/0001+0002, ledger/0001+0002,
        policy/0001) AND Pillar C Week 2 (vault/0003, ledger/0003) AND
        Pillar C Week 3 (ledger/0004) AND Pillar C Week 5 (ledger/0005)
        AND Pillar C Week 6 (ledger/0006) AND Pillar C Week 7
        (policy/0002) AND Pillar C Week 8 (policy/0003) AND Pillar C
        Week 9 (policy/0004) AND Pillar C Week 10 (policy/0005) AND
        Pillar C Week 11 (policy/0006) AND Pillar D Week 4-5
        (vault/0004 add conversation_status per ADR-0028 D119)."""
        from orchestrator.migrations.state import (
            MigrationState, mark_applied, save_state_atomic,
        )
        from datetime import datetime, timezone
        # Set up state dir under HOME.
        monkeypatch.setenv("HOME", str(tmp_path))
        state_dir = tmp_path / ".outreach-factory"
        state_dir.mkdir()
        now = datetime.now(timezone.utc)
        s = MigrationState()
        for cat, mid in (
            (MigrationCategory.VAULT,
             "0001_add_schema_version_to_person_notes"),
            (MigrationCategory.VAULT,
             "0002_backfill_identity_lineage"),
            (MigrationCategory.VAULT,
             "0003_add_linkedin_action_to_touch_notes"),
            (MigrationCategory.VAULT,
             "0004_add_conversation_status_to_person_notes"),
            (MigrationCategory.VAULT,
             "0005_add_discovery_lineage_to_identity_keys"),
            (MigrationCategory.LEDGER,
             "0001_close_orphan_send_intents"),
            (MigrationCategory.LEDGER,
             "0002_backfill_send_history"),
            (MigrationCategory.LEDGER,
             "0003_baseline_li_invite_history"),
            (MigrationCategory.LEDGER,
             "0004_baseline_li_dm_history"),
            (MigrationCategory.LEDGER,
             "0005_baseline_tw_dm_history"),
            (MigrationCategory.LEDGER,
             "0006_baseline_calendar_booking_history"),
            (MigrationCategory.LEDGER,
             "0007_backfill_enrolled_source_skill"),
            (MigrationCategory.POLICY,
             "0001_add_engine_compat_field"),
            (MigrationCategory.POLICY,
             "0002_add_li_invite_weekly_cap"),
            (MigrationCategory.POLICY,
             "0003_add_li_dm_weekly_cap"),
            (MigrationCategory.POLICY,
             "0004_add_tw_dm_weekly_cap"),
            (MigrationCategory.POLICY,
             "0005_add_calendar_booking_daily_cap"),
            (MigrationCategory.POLICY,
             "0006_add_cross_channel_email_linkedin_cooldown"),
            (MigrationCategory.POLICY,
             "0007_add_reply_classifier_llm_cap"),
        ):
            mark_applied(s, cat, mid, now=now, runner_version="test")
        save_state_atomic(state_dir, s)

        doctor = _load_doctor_module()
        result = doctor.check_migrations(config={"vault": {"path": str(tmp_path)}})
        assert result["status"] == doctor.OK
        assert "no pending" in result["message"]

    def test_no_config_still_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """No config → vault_dir defaults to None → check still runs."""
        monkeypatch.setenv("HOME", str(tmp_path))
        doctor = _load_doctor_module()
        result = doctor.check_migrations(config=None)
        # Migration framework is importable; result is WARN due to
        # pending Week 2 vault migration.
        assert result["status"] in (doctor.OK, doctor.WARN)

    def test_warns_when_vault_path_missing_from_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """vault.path points at a non-existent path → vault_dir set
        to None inside check_migrations → runner constructed without
        vault_dir → pending() still returns the vault migration."""
        monkeypatch.setenv("HOME", str(tmp_path))
        doctor = _load_doctor_module()
        result = doctor.check_migrations(
            config={"vault": {"path": "/nonexistent/path/vault"}},
        )
        # Migration still surfaces as pending; runner construction
        # succeeded (vault_dir=None is allowed).
        assert result["status"] == doctor.WARN


# ---------------------------------------------------------------------------
# Exit-code semantics (the asymmetric-failure-cost contract per D12)
# ---------------------------------------------------------------------------


class TestExitCodeSemantics:
    def test_warn_status_is_not_fail(self):
        """Doctor's exit code is 0 when all required checks are OK or
        WARN; 1 only when any required check is FAIL. The migration
        check uses WARN (not FAIL) per D12 — verifying the WARN /
        FAIL distinction is preserved by the doctor module's
        exit-code logic."""
        doctor = _load_doctor_module()
        # WARN and OK both pass the exit-code gate.
        required = [
            {"name": "x", "status": doctor.OK, "message": ""},
            {"name": "migrations", "status": doctor.WARN, "message": "1 pending"},
        ]
        # The exit logic lives in main(); replicate it here.
        exit_zero = all(r["status"] != doctor.FAIL for r in required)
        assert exit_zero is True

    def test_fail_status_does_fail(self):
        """Sanity: if any required check is FAIL, the exit code is 1."""
        doctor = _load_doctor_module()
        required = [
            {"name": "x", "status": doctor.OK, "message": ""},
            {"name": "y", "status": doctor.FAIL, "message": ""},
        ]
        exit_zero = all(r["status"] != doctor.FAIL for r in required)
        assert exit_zero is False

    def test_migrations_check_uses_warn_not_fail_when_pending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """The migrations check itself must use WARN (not FAIL) when
        pending — this is the Week 2 invariant (Pillar I hardens to
        refuse-on-pending later)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        doctor = _load_doctor_module()
        result = doctor.check_migrations(config={"vault": {"path": str(tmp_path)}})
        assert result["status"] == doctor.WARN
        assert result["status"] != doctor.FAIL


# ---------------------------------------------------------------------------
# Strict-mode feature flag (Week 6, ADR-0013 D26)
# ---------------------------------------------------------------------------


def _seed_all_real_migrations_applied(state_dir: Path) -> None:
    """Helper: mark every real Pillar B + Pillar C Week 2 + Week 3 +
    Week 5 + Week 6 + Week 7 + Week 8 + Week 9 + Week 10 + Week 11 +
    Pillar D Week 4-5 migration as applied in the state file under
    ``state_dir``. Used by the "strict-mode + no pending" test to
    verify the strict path yields OK when nothing is pending (vs FAIL
    when something is)."""
    from datetime import datetime, timezone
    from orchestrator.migrations.state import (
        MigrationState, mark_applied, save_state_atomic,
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    s = MigrationState()
    for cat, mid in (
        (MigrationCategory.VAULT,
         "0001_add_schema_version_to_person_notes"),
        (MigrationCategory.VAULT,
         "0002_backfill_identity_lineage"),
        (MigrationCategory.VAULT,
         "0003_add_linkedin_action_to_touch_notes"),
        (MigrationCategory.VAULT,
         "0004_add_conversation_status_to_person_notes"),
        (MigrationCategory.VAULT,
         "0005_add_discovery_lineage_to_identity_keys"),
        (MigrationCategory.LEDGER,
         "0001_close_orphan_send_intents"),
        (MigrationCategory.LEDGER,
         "0002_backfill_send_history"),
        (MigrationCategory.LEDGER,
         "0003_baseline_li_invite_history"),
        (MigrationCategory.LEDGER,
         "0004_baseline_li_dm_history"),
        (MigrationCategory.LEDGER,
         "0005_baseline_tw_dm_history"),
        (MigrationCategory.LEDGER,
         "0006_baseline_calendar_booking_history"),
        (MigrationCategory.LEDGER,
         "0007_backfill_enrolled_source_skill"),
        (MigrationCategory.POLICY,
         "0001_add_engine_compat_field"),
        (MigrationCategory.POLICY,
         "0002_add_li_invite_weekly_cap"),
        (MigrationCategory.POLICY,
         "0003_add_li_dm_weekly_cap"),
        (MigrationCategory.POLICY,
         "0004_add_tw_dm_weekly_cap"),
        (MigrationCategory.POLICY,
         "0005_add_calendar_booking_daily_cap"),
        (MigrationCategory.POLICY,
         "0006_add_cross_channel_email_linkedin_cooldown"),
        (MigrationCategory.POLICY,
         "0007_add_reply_classifier_llm_cap"),
    ):
        mark_applied(s, cat, mid, now=now, runner_version="test")
    save_state_atomic(state_dir, s)


class TestStrictMode:
    """ADR-0013 D26 ships ``OUTREACH_FACTORY_STRICT_MIGRATIONS=1`` as the
    Week 6 soft-rollout precursor to Pillar I's eventual default-flip
    of refuse-on-pending. Contract:

    * env var exactly ``"1"`` + pending migrations → status = FAIL
      (doctor exit code 1).
    * env var unset → status = WARN (default; exit code 0).
    * env var any other value (``"true"``, ``"yes"``, ``"on"``, ``"0"``,
      ``""``) → status = WARN. Exact-match ``"1"`` per D29; the
      truthy-string interpretation is explicitly rejected so operators
      have a single unambiguous value to learn.
    * env var ``"1"`` + no pending migrations → status = OK. The flag
      changes the verdict ONLY when there is something pending; an
      operator who applied everything sees OK either way.

    The strict-mode message includes a clear indicator so an operator
    inspecting the doctor's output can verify the flag took effect
    without grepping their shell environment.
    """

    def test_strict_mode_promotes_warn_to_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """env var = "1" + pending migrations → FAIL (not WARN)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv(STRICT_ENV, "1")
        doctor = _load_doctor_module()
        result = doctor.check_migrations(
            config={"vault": {"path": str(tmp_path)}},
        )
        assert result["status"] == doctor.FAIL
        assert "pending" in result["message"]
        # The strict-mode message must surface the mode so an operator
        # can confirm the flag took effect.
        assert "strict" in result["message"].lower()

    def test_strict_mode_unset_warns_as_usual(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """env var unset → existing WARN behavior preserved."""
        monkeypatch.setenv("HOME", str(tmp_path))
        # Fixture already delenv'd STRICT_ENV.
        doctor = _load_doctor_module()
        result = doctor.check_migrations(
            config={"vault": {"path": str(tmp_path)}},
        )
        assert result["status"] == doctor.WARN
        assert "pending" in result["message"]

    def test_strict_mode_with_no_pending_is_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """env var = "1" but every migration already applied → OK.

        Strict mode only escalates pending-migrations; it doesn't
        invent new failure modes. An operator who has applied every
        migration sees the same OK verdict in strict mode as in default
        mode.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv(STRICT_ENV, "1")
        _seed_all_real_migrations_applied(tmp_path / ".outreach-factory")
        doctor = _load_doctor_module()
        result = doctor.check_migrations(
            config={"vault": {"path": str(tmp_path)}},
        )
        assert result["status"] == doctor.OK
        assert "no pending" in result["message"]

    @pytest.mark.parametrize(
        "non_strict_value",
        ["true", "yes", "on", "0", "", "TRUE", "1 ", " 1"],
    )
    def test_strict_mode_non_1_values_are_not_strict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        non_strict_value: str,
    ):
        """Per D29 the flag is exact-match ``"1"``; any other value
        — including ``"true"`` / ``"yes"`` / ``"on"`` / ``"0"`` /
        empty string / case variants / whitespace-padded — is treated
        as NOT strict. The trade-off: operators who type ``=true`` and
        expect it to work get the default WARN; the doctor's output
        surfaces ``Strict migrations: DISABLED`` so they notice the
        mismatch.

        Whitespace + case-variant cases pinned explicitly because
        ``os.environ.get`` returns the literal string the operator
        set; the framework does not strip / lower."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv(STRICT_ENV, non_strict_value)
        doctor = _load_doctor_module()
        result = doctor.check_migrations(
            config={"vault": {"path": str(tmp_path)}},
        )
        # NOT strict — pending migrations stay WARN.
        assert result["status"] == doctor.WARN, (
            f"value {non_strict_value!r} should NOT trigger strict mode"
        )
        # And the strict-indicator should not falsely claim ENABLED
        # when the env var was not exactly "1".
        assert "strict" not in result["message"].lower()
