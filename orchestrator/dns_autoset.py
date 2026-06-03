"""Opt-in Cloudflare DNS auto-set: create/verify SPF + DMARC TXT records.

The default onboarding path is guide-and-verify: ``dns_check`` tells the
operator the exact SPF/DMARC records to add, and they paste them into their DNS
provider by hand. That is deliberately the default because it works for every
provider and never touches a write-scoped API token.

This module is the OPT-IN convenience layer for operators whose DNS lives on
Cloudflare. Given a Cloudflare API token (read from the ``CLOUDFLARE_API_TOKEN``
env var by ``/onboard`` Phase 3, never from config.yml), it auto-detects the
zone for the domain and creates the recommended SPF + DMARC TXT records via the
Cloudflare API. The record VALUES come from ``orchestrator.dns_check`` so the
auto-set path and the guide path can never drift.

Invariants:
  * Refuse-loud. Missing/blank token, or a domain whose zone is not on this
    Cloudflare account, raises ``DnsAutosetError`` rather than silently no-op.
  * Idempotent. An equivalent TXT record already present is a no-op; re-running
    ``ensure_records`` is safe.
  * DKIM is NOT auto-set. DKIM keys are minted in the email provider's admin
    console (Google Workspace / Resend), not by writing a value we know; the
    operator publishes the provider-given record by hand. ``dns_check.check_dkim``
    documents this.

Network-isolated for testing: every HTTP call goes through an injected ``http``
callable. The default lazily builds a thin urllib-based live client, imported
INSIDE the method so this module imports without ``requests`` (or anything
beyond the stdlib) installed. Tests inject a fake that captures requests and
returns canned Cloudflare JSON, so a unit test never hits the network.

Off the core send path: this is onboarding tooling and must stay import-lean
(stdlib + ``orchestrator.dns_check`` only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from orchestrator import dns_check

# Base URL for the Cloudflare v4 API. Centralized so the captured-request
# assertions in the tests pin one canonical contract.
CF_API_BASE = "https://api.cloudflare.com/client/v4"


class DnsAutosetError(RuntimeError):
    """Raised when auto-set cannot proceed: blank token, no zone on the
    account, or the Cloudflare API returns a non-success response. Refuse-loud
    rather than silently leaving DNS unchanged."""


# A response-like object: anything exposing ``.status_code`` (int) and a
# ``.json()`` method returning the parsed body. The injected fake and the live
# urllib client both satisfy this.
class _ResponseLike:  # documentation-only protocol surface
    status_code: int

    def json(self) -> Any:  # pragma: no cover - structural type only
        ...


# The HTTP seam: http(method, url, *, headers=None, json=None) -> _ResponseLike.
HttpCallable = Callable[..., Any]


# A short list of common two-label public suffixes so a subdomain like
# ``mail.example.co.uk`` resolves to the registrable zone ``example.co.uk``
# rather than ``co.uk``. This is a pragmatic subset, not the full Public Suffix
# List: it covers the suffixes outreach operators actually use, and Cloudflare
# itself is the final authority (find_zone_id queries the account's real zones,
# so a wrong guess simply fails refuse-loud instead of writing to the wrong
# place). The single-label common case (``example.com``) needs no table.
_TWO_LABEL_SUFFIXES: frozenset[str] = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "sch.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.nz", "net.nz", "org.nz",
    "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
    "co.kr", "or.kr",
    "co.in", "net.in", "org.in", "ac.in", "gov.in",
    "com.sg", "edu.sg", "gov.sg",
    "com.hk", "edu.hk", "org.hk",
    "com.br", "net.br", "org.br",
    "com.mx",
    "co.za",
})


def registrable_domain(domain: str) -> str:
    """The registrable (apex) domain for ``domain``: the Cloudflare zone name.

    ``mail.example.com`` -> ``example.com``; ``example.co.uk`` and
    ``mail.example.co.uk`` -> ``example.co.uk``; ``example.com`` -> itself.
    Lowercased, with any trailing dot and leading/trailing whitespace stripped.
    Raises ``DnsAutosetError`` on an empty or single-label input.
    """
    d = (domain or "").strip().lower().rstrip(".")
    if not d or "." not in d:
        raise DnsAutosetError(
            f"cannot derive a Cloudflare zone from {domain!r}: not a domain"
        )
    labels = d.split(".")
    last_two = ".".join(labels[-2:])
    if last_two in _TWO_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def _http_live(method: str, url: str, *, headers: Optional[dict] = None,
               json: Any = None) -> Any:
    """Default live HTTP client (stdlib ``urllib`` only, imported lazily).

    Returns a tiny response shim exposing ``.status_code`` and ``.json()`` so
    the live path matches the fake the tests inject. Imported inside the
    function so ``orchestrator.dns_autoset`` imports with nothing beyond the
    stdlib present."""
    import json as _json  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    data = None
    req_headers = dict(headers or {})
    if json is not None:
        data = _json.dumps(json).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

    class _Resp:
        def __init__(self, status: int, body: bytes):
            self.status_code = status
            self._body = body

        def json(self) -> Any:
            if not self._body:
                return {}
            return _json.loads(self._body.decode("utf-8"))

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return _Resp(resp.status, resp.read())
    except urllib.error.HTTPError as exc:
        # Cloudflare returns its JSON error envelope in the body even on 4xx;
        # surface the status + body so the caller can refuse-loud with detail.
        return _Resp(exc.code, exc.read())


@dataclass(frozen=True)
class EnsureResult:
    """The outcome of ``ensure_records``: per-record actions plus the optional
    post-write re-verification report from ``dns_check.inspect_domain``."""

    zone_id: str
    spf: dict
    dmarc: dict
    post_check: Optional[dns_check.DomainReport] = None
    notes: List[str] = field(default_factory=list)


class CloudflareDNSWriter:
    """Thin Cloudflare DNS writer for the SPF + DMARC TXT records.

    Construct with the API token (and optionally an injected ``http`` seam).
    Refuses-loud on a blank token. All network access goes through ``http`` so
    tests run fully offline.
    """

    def __init__(self, token: str, http: Optional[HttpCallable] = None):
        if not token or not str(token).strip():
            raise DnsAutosetError(
                "Cloudflare API token is empty. Set CLOUDFLARE_API_TOKEN (it is "
                "OPT-IN; the default onboarding path is guide-and-verify, where "
                "you paste the records from `doctor` by hand). Refusing to "
                "proceed."
            )
        self._token = str(token).strip()
        self._http: HttpCallable = http or _http_live

    # low-level request helper --------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        """Issue one Cloudflare API call and return the parsed body. Refuses-
        loud on a non-2xx status or a ``success: false`` envelope."""
        url = f"{CF_API_BASE}{path}"
        resp = self._http(method, url, headers=self._headers(), json=json)
        status = getattr(resp, "status_code", None)
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise DnsAutosetError(
                f"Cloudflare {method} {path} returned an unparseable body "
                f"(status={status}): {exc}"
            ) from exc
        if status is None or status < 200 or status >= 300:
            raise DnsAutosetError(
                f"Cloudflare {method} {path} failed (status={status}): "
                f"{_cf_errors(body)}"
            )
        if isinstance(body, dict) and body.get("success") is False:
            raise DnsAutosetError(
                f"Cloudflare {method} {path} reported failure: {_cf_errors(body)}"
            )
        return body

    # zone discovery ------------------------------------------------------

    def find_zone_id(self, domain: str) -> str:
        """Return the Cloudflare zone id for ``domain``'s registrable apex.

        Queries ``GET /zones?name=<apex>`` and returns ``result[0].id``.
        Refuses-loud if the account has no matching zone (the operator's domain
        is not on this Cloudflare account)."""
        apex = registrable_domain(domain)
        body = self._request("GET", f"/zones?name={apex}")
        result = body.get("result") if isinstance(body, dict) else None
        if not result:
            raise DnsAutosetError(
                f"no Cloudflare zone found for {apex!r} on this account. The "
                f"CLOUDFLARE_API_TOKEN must belong to the account that hosts "
                f"this domain's DNS. (Auto-set is OPT-IN; the default path is "
                f"to paste the records by hand.)"
            )
        zone_id = result[0].get("id")
        if not zone_id:
            raise DnsAutosetError(
                f"Cloudflare returned a zone for {apex!r} with no id: {result[0]!r}"
            )
        return zone_id

    # TXT upsert ----------------------------------------------------------

    def upsert_txt(self, zone_id: str, name: str, content: str) -> dict:
        """Create the TXT record at ``name`` with value ``content`` if no
        equivalent value already exists; otherwise no-op (idempotent).

        Returns ``{"action": "created"|"exists"|"updated", "name", "content",
        "record_id"?}``. Cloudflare stores TXT values unquoted in ``content``;
        we compare on the unquoted, stripped value so a re-run is a no-op."""
        listing = self._request(
            "GET", f"/zones/{zone_id}/dns_records?type=TXT&name={name}"
        )
        records = listing.get("result") if isinstance(listing, dict) else None
        records = records or []
        want = _normalize_txt(content)
        for rec in records:
            if _normalize_txt(rec.get("content", "")) == want:
                return {
                    "action": "exists",
                    "name": name,
                    "content": content,
                    "record_id": rec.get("id"),
                }
        created = self._request(
            "POST", f"/zones/{zone_id}/dns_records",
            json={"type": "TXT", "name": name, "content": content},
        )
        rec = created.get("result") if isinstance(created, dict) else None
        return {
            "action": "created",
            "name": name,
            "content": content,
            "record_id": (rec or {}).get("id"),
        }

    # the high-level entry point ------------------------------------------

    def ensure_records(
        self, domain: str, *,
        provider: str = "google",
        rua_email: Optional[str] = None,
        resolve: Optional[dns_check.Resolver] = None,
    ) -> EnsureResult:
        """Ensure the recommended SPF (apex) + DMARC (``_dmarc.<domain>``) TXT
        records exist on Cloudflare for ``domain``.

        The record VALUES come straight from ``dns_check.generate_spf_record``
        and ``dns_check.generate_dmarc_record`` so this path can never drift
        from the guide-and-verify path. DKIM is intentionally NOT auto-set
        (provider-console only).

        If ``resolve`` is given, re-verifies via ``dns_check.inspect_domain``
        afterward and attaches the report as ``post_check`` (note: a freshly
        written record may not have propagated to the resolver yet).
        """
        zone_id = self.find_zone_id(domain)

        spf_value = dns_check.generate_spf_record(provider)
        dmarc_value = dns_check.generate_dmarc_record("none", rua_email)

        spf = self.upsert_txt(zone_id, domain, spf_value)
        dmarc = self.upsert_txt(zone_id, f"_dmarc.{domain}", dmarc_value)

        notes = [
            "DKIM is NOT auto-set: DKIM keys are generated in your email "
            "provider's admin console (Google Workspace: Apps > Gmail > "
            "Authenticate email; Resend: add the domain in the dashboard). "
            "Publish the provider-given TXT record by hand."
        ]

        post_check = None
        if resolve is not None:
            post_check = dns_check.inspect_domain(
                domain, resolve=resolve, provider=provider, rua_email=rua_email,
            )

        return EnsureResult(
            zone_id=zone_id, spf=spf, dmarc=dmarc,
            post_check=post_check, notes=notes,
        )


def _normalize_txt(value: str) -> str:
    """Normalize a TXT value for equivalence comparison: strip whitespace and
    a single layer of surrounding double-quotes (Cloudflare may store either
    quoted or unquoted), then collapse internal whitespace runs."""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return " ".join(v.split())


def _cf_errors(body: Any) -> str:
    """Render the Cloudflare error envelope's ``errors`` list into one string
    for refuse-loud messages."""
    if isinstance(body, dict):
        errs = body.get("errors")
        if errs:
            parts = []
            for e in errs:
                if isinstance(e, dict):
                    parts.append(f"{e.get('code', '?')}: {e.get('message', '')}")
                else:
                    parts.append(str(e))
            return "; ".join(parts)
    return str(body)
