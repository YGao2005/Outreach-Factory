"""Tests for orchestrator/dns_autoset.py (opt-in Cloudflare DNS auto-set).

Offline by construction: every test injects a fake HTTP client that captures
the outbound requests and returns canned Cloudflare JSON, so no network call
happens. Core-tier (DNS + onboarding is a core job): do NOT add this file to
tests/conftest.py _OPERATIONS_TEST_FILES.

The fake pins the Cloudflare API contract: the captured method/url/body are
asserted so a drift in the request shape (wrong path, wrong record name,
quoting, etc.) fails here rather than against the live API.
"""

from __future__ import annotations

import pytest

from orchestrator import dns_autoset as A
from orchestrator import dns_check


# --- fake HTTP client ------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    """Captures every (method, url, headers, json) and returns canned bodies.

    ``routes`` maps a ``(method, url_predicate)`` to a response. To keep tests
    terse, the responses are configured by a small handler that inspects the
    method + url and returns a ``_FakeResp``. The default handler models a
    Cloudflare account with one zone and an initially-empty TXT record set;
    POSTed TXT records are remembered so a second list-call sees them (proving
    idempotence).
    """

    def __init__(self, *, zone_result=None, fail_status=None, fail_body=None):
        self.calls: list[dict] = []
        # Default: one zone named acme.com.
        self._zone_result = (
            zone_result if zone_result is not None
            else [{"id": "zone123", "name": "acme.com"}]
        )
        # Records keyed by name -> list of {"id", "content"}.
        self._records: dict[str, list[dict]] = {}
        self._next_id = 1
        self._fail_status = fail_status
        self._fail_body = fail_body

    def seed_txt(self, name: str, content: str):
        rec = {"id": f"seeded{self._next_id}", "content": content}
        self._next_id += 1
        self._records.setdefault(name, []).append(rec)
        return rec

    def __call__(self, method, url, *, headers=None, json=None):
        self.calls.append({
            "method": method, "url": url, "headers": headers, "json": json,
        })
        if self._fail_status is not None:
            return _FakeResp(self._fail_status, self._fail_body or {
                "success": False,
                "errors": [{"code": 1003, "message": "boom"}],
            })

        # Zone lookup: GET /zones?name=<apex>
        if method == "GET" and "/zones?name=" in url:
            return _FakeResp(200, {"success": True, "result": self._zone_result})

        # TXT list: GET /zones/<id>/dns_records?type=TXT&name=<name>
        if method == "GET" and "/dns_records?type=TXT&name=" in url:
            name = url.split("name=", 1)[1]
            return _FakeResp(200, {
                "success": True, "result": list(self._records.get(name, [])),
            })

        # TXT create: POST /zones/<id>/dns_records
        if method == "POST" and url.endswith("/dns_records"):
            name = json["name"]
            rec = {"id": f"new{self._next_id}", "content": json["content"]}
            self._next_id += 1
            self._records.setdefault(name, []).append(rec)
            return _FakeResp(200, {"success": True, "result": rec})

        raise AssertionError(f"unexpected request: {method} {url}")

    # convenience accessors for assertions
    def methods_urls(self):
        return [(c["method"], c["url"]) for c in self.calls]

    def posts(self):
        return [c for c in self.calls if c["method"] == "POST"]


# --- refuse-loud on missing token -----------------------------------------

def test_blank_token_refuses_loud():
    for bad in ("", "   ", "\t\n"):
        with pytest.raises(A.DnsAutosetError):
            A.CloudflareDNSWriter(bad, http=FakeHttp())


def test_none_token_refuses_loud():
    with pytest.raises(A.DnsAutosetError):
        A.CloudflareDNSWriter(None, http=FakeHttp())  # type: ignore[arg-type]


# --- registrable domain (apex vs subdomain) --------------------------------

def test_registrable_domain_apex_and_subdomain():
    assert A.registrable_domain("acme.com") == "acme.com"
    assert A.registrable_domain("mail.acme.com") == "acme.com"
    assert A.registrable_domain("a.b.acme.com") == "acme.com"
    # Two-label public suffix.
    assert A.registrable_domain("example.co.uk") == "example.co.uk"
    assert A.registrable_domain("mail.example.co.uk") == "example.co.uk"
    # Normalization: case + trailing dot.
    assert A.registrable_domain("MAIL.Acme.com.") == "acme.com"


def test_registrable_domain_refuses_non_domain():
    for bad in ("", "localhost", "   "):
        with pytest.raises(A.DnsAutosetError):
            A.registrable_domain(bad)


# --- find_zone_id ----------------------------------------------------------

def test_find_zone_id_parses_cf_response():
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)
    zid = w.find_zone_id("mail.acme.com")
    assert zid == "zone123"
    # The zone query uses the registrable apex, not the subdomain.
    method, url = http.methods_urls()[0]
    assert method == "GET"
    assert url == f"{A.CF_API_BASE}/zones?name=acme.com"
    # Bearer auth header is set.
    assert http.calls[0]["headers"]["Authorization"] == "Bearer tok"


def test_find_zone_id_refuses_when_no_zone():
    http = FakeHttp(zone_result=[])
    w = A.CloudflareDNSWriter("tok", http=http)
    with pytest.raises(A.DnsAutosetError) as exc:
        w.find_zone_id("notmine.com")
    assert "notmine.com" in str(exc.value)


# --- upsert_txt: create when absent ----------------------------------------

def test_upsert_txt_creates_when_absent():
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)
    res = w.upsert_txt("zone123", "acme.com", "v=spf1 include:_spf.google.com ~all")
    assert res["action"] == "created"
    posts = http.posts()
    assert len(posts) == 1
    body = posts[0]["json"]
    assert body == {
        "type": "TXT",
        "name": "acme.com",
        "content": "v=spf1 include:_spf.google.com ~all",
    }
    assert posts[0]["url"] == f"{A.CF_API_BASE}/zones/zone123/dns_records"


# --- upsert_txt: idempotent no-op when present -----------------------------

def test_upsert_txt_noops_when_present():
    http = FakeHttp()
    http.seed_txt("acme.com", "v=spf1 include:_spf.google.com ~all")
    w = A.CloudflareDNSWriter("tok", http=http)
    res = w.upsert_txt("zone123", "acme.com", "v=spf1 include:_spf.google.com ~all")
    assert res["action"] == "exists"
    # No POST issued: pure no-op.
    assert http.posts() == []


def test_upsert_txt_noops_on_quoted_equivalent():
    # Cloudflare may store the value quoted; an equivalent value is still a no-op.
    http = FakeHttp()
    http.seed_txt("acme.com", '"v=spf1 include:_spf.google.com ~all"')
    w = A.CloudflareDNSWriter("tok", http=http)
    res = w.upsert_txt("zone123", "acme.com", "v=spf1 include:_spf.google.com ~all")
    assert res["action"] == "exists"
    assert http.posts() == []


def test_upsert_txt_rerun_is_noop():
    # First run creates, second run finds the created record -> no-op.
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)
    first = w.upsert_txt("zone123", "acme.com", "v=spf1 include:amazonses.com ~all")
    assert first["action"] == "created"
    second = w.upsert_txt("zone123", "acme.com", "v=spf1 include:amazonses.com ~all")
    assert second["action"] == "exists"
    # Exactly one POST across both runs.
    assert len(http.posts()) == 1


# --- ensure_records: SPF at apex + DMARC at _dmarc, values from dns_check ---

def test_ensure_records_sets_spf_apex_and_dmarc():
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)
    result = w.ensure_records("acme.com", provider="google",
                              rua_email="dmarc@acme.com")

    assert result.zone_id == "zone123"
    assert result.spf["action"] == "created"
    assert result.dmarc["action"] == "created"

    posts = http.posts()
    by_name = {p["json"]["name"]: p["json"] for p in posts}

    # SPF lands at the apex with the EXACT value dns_check recommends.
    expected_spf = dns_check.generate_spf_record("google")
    assert by_name["acme.com"] == {
        "type": "TXT", "name": "acme.com", "content": expected_spf,
    }

    # DMARC lands at _dmarc.<domain> with the EXACT value dns_check recommends.
    expected_dmarc = dns_check.generate_dmarc_record("none", "dmarc@acme.com")
    assert by_name["_dmarc.acme.com"] == {
        "type": "TXT", "name": "_dmarc.acme.com", "content": expected_dmarc,
    }


def test_ensure_records_resend_provider_value():
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)
    w.ensure_records("acme.com", provider="resend")
    posts = http.posts()
    spf = next(p for p in posts if p["json"]["name"] == "acme.com")
    assert spf["json"]["content"] == dns_check.generate_spf_record("resend")
    assert "include:amazonses.com" in spf["json"]["content"]


# --- ensure_records: DKIM is NOT auto-set ----------------------------------

def test_ensure_records_does_not_autoset_dkim():
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)
    result = w.ensure_records("acme.com")
    posted_names = [p["json"]["name"] for p in http.posts()]
    # Only SPF (apex) and DMARC (_dmarc) are written; nothing at a DKIM
    # selector like google._domainkey.<domain>.
    assert set(posted_names) == {"acme.com", "_dmarc.acme.com"}
    assert not any("_domainkey" in n for n in posted_names)
    # The result documents that DKIM is provider-console-only.
    assert any("DKIM" in note for note in result.notes)


# --- ensure_records: idempotent (re-run writes nothing) --------------------

def test_ensure_records_is_idempotent():
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)
    w.ensure_records("acme.com", rua_email="dmarc@acme.com")
    assert len(http.posts()) == 2  # SPF + DMARC created
    # Re-run: both records now exist -> no new POSTs.
    result2 = w.ensure_records("acme.com", rua_email="dmarc@acme.com")
    assert len(http.posts()) == 2  # unchanged
    assert result2.spf["action"] == "exists"
    assert result2.dmarc["action"] == "exists"


# --- ensure_records: optional post-write re-verification -------------------

def test_ensure_records_post_check_with_injected_resolver():
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)

    # Inject a dns_check resolver that reports the just-written records as
    # published (simulating propagation). Offline: a dict-backed resolver.
    spf_val = dns_check.generate_spf_record("google")
    dmarc_val = dns_check.generate_dmarc_record("none", None)
    published = {
        "acme.com": [spf_val],
        "_dmarc.acme.com": [dmarc_val],
        "google._domainkey.acme.com": ["v=DKIM1; k=rsa; p=MIGf..."],
    }

    def resolve(name):
        return list(published.get(name, []))

    result = w.ensure_records("acme.com", resolve=resolve)
    assert result.post_check is not None
    assert result.post_check.spf.present
    assert result.post_check.dmarc.present


def test_ensure_records_no_post_check_without_resolver():
    http = FakeHttp()
    w = A.CloudflareDNSWriter("tok", http=http)
    result = w.ensure_records("acme.com")
    assert result.post_check is None


# --- refuse-loud on a Cloudflare API failure -------------------------------

def test_request_failure_refuses_loud():
    http = FakeHttp(fail_status=403, fail_body={
        "success": False,
        "errors": [{"code": 9109, "message": "Unauthorized to access requested resource"}],
    })
    w = A.CloudflareDNSWriter("tok", http=http)
    with pytest.raises(A.DnsAutosetError) as exc:
        w.find_zone_id("acme.com")
    assert "9109" in str(exc.value) or "Unauthorized" in str(exc.value)


def test_success_false_envelope_refuses_loud():
    # 200 status but success:false (Cloudflare's soft-error shape).
    http = FakeHttp()

    def failing(method, url, *, headers=None, json=None):
        http.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return _FakeResp(200, {"success": False, "errors": [{"code": 81044, "message": "nope"}]})

    w = A.CloudflareDNSWriter("tok", http=failing)
    with pytest.raises(A.DnsAutosetError):
        w.find_zone_id("acme.com")
