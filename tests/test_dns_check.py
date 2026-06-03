"""Tests for orchestrator/dns_check.py (deliverability inspection).

Offline by construction: every test injects a fake resolver (a dict of
name -> TXT strings), so no DNS queries happen. This is core-tier (the
deliverability check is part of the onboarding job).
"""

from __future__ import annotations

from orchestrator import dns_check as D


def _resolver(mapping: dict[str, list[str]]):
    def _r(name: str) -> list[str]:
        return list(mapping.get(name, []))
    return _r


# --- SPF -------------------------------------------------------------------

def test_spf_present_is_ok():
    r = _resolver({"acme.com": ["v=spf1 include:_spf.google.com ~all"]})
    c = D.check_spf("acme.com", r)
    assert c.present and not c.weak and c.recommendation is None


def test_spf_missing_recommends_the_exact_record():
    r = _resolver({"acme.com": ["some-other-txt=value"]})
    c = D.check_spf("acme.com", r, provider="google")
    assert not c.present
    assert "v=spf1 include:_spf.google.com ~all" in c.recommendation


def test_spf_multiple_records_is_weak():
    r = _resolver({"acme.com": ["v=spf1 include:a ~all", "v=spf1 include:b ~all"]})
    c = D.check_spf("acme.com", r)
    assert c.present and c.weak
    assert "only one is valid" in c.detail


# --- DMARC -----------------------------------------------------------------

def test_dmarc_reject_is_strong():
    r = _resolver({"_dmarc.acme.com": ["v=DMARC1; p=reject; rua=mailto:dmarc@acme.com"]})
    c = D.check_dmarc("acme.com", r)
    assert c.present and not c.weak and c.detail == "policy=reject"


def test_dmarc_none_is_weak_and_says_to_ramp():
    r = _resolver({"_dmarc.acme.com": ["v=DMARC1; p=none"]})
    c = D.check_dmarc("acme.com", r)
    assert c.present and c.weak and c.detail == "policy=none"
    assert "quarantine" in c.recommendation and "reject" in c.recommendation


def test_dmarc_missing_recommends_record_on_the_dmarc_subdomain():
    c = D.check_dmarc("acme.com", _resolver({}), rua_email="dmarc@acme.com")
    assert not c.present
    assert "_dmarc.acme.com" in c.recommendation
    assert "v=DMARC1; p=none;" in c.recommendation
    assert "rua=mailto:dmarc@acme.com" in c.recommendation


# --- DKIM ------------------------------------------------------------------

def test_dkim_found_at_google_selector():
    r = _resolver({"google._domainkey.acme.com": ["v=DKIM1; k=rsa; p=MIGf..."]})
    c = D.check_dkim("acme.com", r)
    assert c.present and c.detail == "selector=google"


def test_dkim_missing_points_at_the_provider_console():
    c = D.check_dkim("acme.com", _resolver({}))
    assert not c.present
    assert "admin console" in c.recommendation


# --- aggregate -------------------------------------------------------------

def test_inspect_domain_all_present():
    r = _resolver({
        "acme.com": ["v=spf1 include:_spf.google.com ~all"],
        "_dmarc.acme.com": ["v=DMARC1; p=reject"],
        "google._domainkey.acme.com": ["v=DKIM1; k=rsa; p=key"],
    })
    rep = D.inspect_domain("acme.com", resolve=r)
    assert rep.all_present and rep.missing == []
    assert "SPF ok" in rep.summary and "DMARC ok" in rep.summary and "DKIM ok" in rep.summary


def test_inspect_domain_greenfield_reports_all_missing():
    rep = D.inspect_domain("acme.com", resolve=_resolver({}))
    assert not rep.all_present
    assert set(rep.missing) == {"spf", "dmarc", "dkim"}


# --- generators + helpers --------------------------------------------------

def test_generate_spf_for_resend():
    assert D.generate_spf_record("resend") == "v=spf1 include:amazonses.com ~all"


def test_generate_dmarc_with_rua():
    assert D.generate_dmarc_record("quarantine", "x@acme.com") == \
        "v=DMARC1; p=quarantine; rua=mailto:x@acme.com;"


def test_domain_of_email():
    assert D.domain_of_email("Yang@Acme.COM") == "acme.com"
    assert D.domain_of_email("not-an-email") is None
    assert D.domain_of_email("") is None


# --- doctor glue (offline; monkeypatch the inspector so no DNS happens) -----

import sys
from pathlib import Path

import pytest


@pytest.fixture
def doctor_mod():
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import doctor
    return doctor


def test_doctor_skips_placeholder_domain(doctor_mod):
    res = doctor_mod.check_deliverability({"founder": {"email": "you@example.com"}})
    assert res["status"] == "warn"
    assert "no real sending domain" in res["message"]


def test_doctor_reports_missing_records_with_fixes(doctor_mod, monkeypatch):
    report = D.DomainReport(
        domain="acme.com",
        spf=D.check_spf("acme.com", lambda n: []),       # missing
        dmarc=D.check_dmarc("acme.com", lambda n: ["v=DMARC1; p=reject"]),  # ok
        dkim=D.check_dkim("acme.com", lambda n: []),      # missing
    )
    monkeypatch.setattr(D, "inspect_domain", lambda *a, **k: report)
    res = doctor_mod.check_deliverability({"founder": {"email": "me@acme.com"}})
    assert res["status"] == "warn"
    assert "SPF MISSING" in res["hint"] and "DKIM MISSING" in res["hint"]
    assert "v=spf1 include:_spf.google.com ~all" in res["hint"]


def test_doctor_ok_when_all_present(doctor_mod, monkeypatch):
    report = D.DomainReport(
        domain="acme.com",
        spf=D.check_spf("acme.com", lambda n: ["v=spf1 include:_spf.google.com ~all"]),
        dmarc=D.check_dmarc("acme.com", lambda n: ["v=DMARC1; p=reject"]),
        dkim=D.check_dkim("acme.com", lambda n: ["v=DKIM1; k=rsa; p=k"]),
    )
    monkeypatch.setattr(D, "inspect_domain", lambda *a, **k: report)
    res = doctor_mod.check_deliverability({"founder": {"email": "me@acme.com"}})
    assert res["status"] == "ok"
    assert "all published" in res["message"]
