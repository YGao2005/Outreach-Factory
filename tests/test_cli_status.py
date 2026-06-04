"""Tests for `outreach-factory status` (cli.cmd_status).

The status command is a lean read over the ledger (the source of truth): what
went out, who replied, what is blocked, and whether there is headroom under the
daily cap. These tests pin the counts + the graceful empty/no-cap degradation.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from orchestrator import cli
from orchestrator import ledger as _ledger


def _run_status() -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.cmd_status(None)
    return rc, buf.getvalue()


@pytest.fixture
def ledger_env(tmp_path, monkeypatch):
    ldir = tmp_path / "ledger"
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(ldir))
    # Point config at a nonexistent path so no daily cap is read.
    monkeypatch.setenv("OUTREACH_FACTORY_CONFIG", str(tmp_path / "nonexistent.yml"))
    return ldir


def test_status_empty_ledger_is_friendly(ledger_env):
    rc, out = _run_status()
    assert rc == 0
    assert "No activity recorded yet" in out


def test_status_counts_today_sends_replies_blocks(ledger_env):
    led = _ledger.Ledger(ledger_env)
    led.append({"type": "send_confirmed", "channel": "email", "person_id": "p1", "intent_id": "i1"})
    led.append({"type": "send_confirmed", "channel": "email", "person_id": "p2", "intent_id": "i2"})
    led.append({"type": "dedup_blocked", "reason": "already_sent", "person_id": "p2"})
    led.append({"type": "policy_blocked", "reason": "domain-cooldown", "person_id": "p3"})
    led.append({"type": "reply_received", "person_id": "p1"})

    rc, out = _run_status()
    assert rc == 0
    assert "emails sent     2" in out
    assert "replies in      1" in out
    # Blocks surface with their reason breakdown (the guardrails made visible).
    assert "blocked         2" in out
    assert "already_sent: 1" in out
    assert "domain-cooldown: 1" in out


def test_status_no_cap_hints_how_to_set_one(ledger_env):
    led = _ledger.Ledger(ledger_env)
    led.append({"type": "send_confirmed", "channel": "email", "person_id": "p1", "intent_id": "i1"})
    rc, out = _run_status()
    assert rc == 0
    assert "daily_send_cap" in out  # the hint to configure headroom tracking


def test_status_with_cap_shows_remaining(tmp_path, monkeypatch):
    ldir = tmp_path / "ledger"
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(ldir))
    cfg = tmp_path / "config.yml"
    cfg.write_text("email_send:\n  daily_send_cap: 25\n")
    monkeypatch.setenv("OUTREACH_FACTORY_CONFIG", str(cfg))

    led = _ledger.Ledger(ldir)
    led.append({"type": "send_confirmed", "channel": "email", "person_id": "p1", "intent_id": "i1"})

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.cmd_status(None)
    out = buf.getvalue()
    assert "1 / 25" in out
    assert "24 remaining" in out


def test_status_shows_followups_due_when_enabled(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    ldir = tmp_path / "ledger"
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(ldir))
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "followup:\n"
        "  enabled: true\n"
        "  max_touches: 3\n"
        "  steps:\n"
        "    - after_business_days: 3\n"
        "    - after_business_days: 5\n"
    )
    monkeypatch.setenv("OUTREACH_FACTORY_CONFIG", str(cfg))

    # A cold touch 14 days ago, no reply since -> due for follow-up 1.
    ts = (datetime.now(timezone.utc) - timedelta(days=14)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    led = _ledger.Ledger(ldir)
    led.append({"type": "send_intent", "channel": "email", "person_id": "p1",
                "intent_id": "i1", "register": "cold-pitch", "ts": ts})
    led.append({"type": "send_confirmed", "channel": "email", "person_id": "p1",
                "intent_id": "i1", "followup_step": 0, "ts": ts})

    rc, out = _run_status()
    assert rc == 0
    assert "FOLLOW-UPS" in out
    assert "due now         1" in out
    assert "follow-up 1: 1" in out
    assert "touch 1: 1" in out


def test_status_followups_off_is_quiet_nudge(tmp_path, monkeypatch):
    ldir = tmp_path / "ledger"
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(ldir))
    cfg = tmp_path / "config.yml"
    cfg.write_text("followup:\n  enabled: false\n")
    monkeypatch.setenv("OUTREACH_FACTORY_CONFIG", str(cfg))

    led = _ledger.Ledger(ldir)
    led.append({"type": "send_confirmed", "channel": "email", "person_id": "p1",
                "intent_id": "i1", "followup_step": 0})

    rc, out = _run_status()
    assert rc == 0
    assert "follow-ups off" in out
    assert "FOLLOW-UPS" not in out  # the full section stays hidden when disabled
