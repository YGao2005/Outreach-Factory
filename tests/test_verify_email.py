"""Tests for orchestrator/verify_email.py.

Live DNS by default (these tests touch the network — skip with -k 'not live'
in offline/CI envs without DNS). Domains chosen for stability:
  - google.com   — has MX (gmail), reliable
  - example.com  — has MX per IANA, reliable
  - this-domain-does-not-exist-aiyara-test-12345.com — NXDOMAIN
"""
from __future__ import annotations

import pytest

from orchestrator.verify_email import verify_mx


@pytest.mark.live
def test_verify_mx_returns_ok_for_google():
    result = verify_mx("google.com")
    assert result["ok"] is True
    assert result["has_mx"] is True
    assert len(result["mx_hosts"]) > 0
    assert result["domain"] == "google.com"


@pytest.mark.live
def test_verify_mx_returns_nxdomain_for_garbage():
    result = verify_mx("this-domain-does-not-exist-aiyara-test-12345.com")
    assert result["ok"] is False
    assert "does not exist" in result["reason"]


def test_verify_mx_handles_empty_domain():
    result = verify_mx("")
    assert result["ok"] is False
    assert result["reason"] == "empty domain"


def test_verify_mx_handles_whitespace():
    result = verify_mx("   ")
    assert result["ok"] is False


def test_verify_mx_lowercases_domain():
    result = verify_mx("Example.COM")
    assert result["domain"] == "example.com"


def test_verify_mx_returns_dict_shape_on_failure():
    """The contract: even on failure, all 5 keys are present."""
    result = verify_mx("")
    assert set(result.keys()) == {"ok", "domain", "has_mx", "mx_hosts", "reason"}
    assert result["mx_hosts"] == []
    assert result["has_mx"] is False
