"""DNS deliverability inspection: SPF / DMARC / DKIM detect + record generation.

Cold email that bounces or lands in spam because the sending domain has no SPF,
DKIM, or DMARC is the number-one "it did not work for me" cause. This module
inspects a domain's published DNS, reports concretely what is present and what
is missing, and generates the exact records to add.

It is part of the onboarding job (the `doctor` deliverability check uses it, and
the planned `/onboard` skill reuses it for the DNS phase). It is NOT on the send
path.

Network-isolated for testing: every lookup goes through an injected
``resolve_txt`` callable. The default resolver uses dnspython; tests pass a fake
resolver so unit tests run offline. A resolver returns the TXT strings published
at a name, or an empty list for NXDOMAIN / timeout / no-records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

# Type of a TXT resolver: name -> published TXT strings (empty list if none).
Resolver = Callable[[str], List[str]]

# DKIM selectors are provider-specific and there is no way to enumerate them from
# DNS, so we probe the common ones. Google Workspace publishes at "google";
# Resend at "resend"; the rest are widely-used defaults across providers.
COMMON_DKIM_SELECTORS: tuple[str, ...] = (
    "google", "resend", "default", "selector1", "selector2",
    "s1", "s2", "k1", "mail", "dkim", "mandrill", "mailjet",
)

# Recommended SPF includes per supported sending provider.
_SPF_INCLUDES = {
    "google": "include:_spf.google.com",
    "gmail": "include:_spf.google.com",
    "resend": "include:amazonses.com",
}


def resolve_txt_dnspython(name: str, *, lifetime: float = 5.0) -> List[str]:
    """Default live resolver (dnspython). Returns [] on any lookup failure so
    callers never crash on NXDOMAIN / timeout / no TXT records. ``lifetime``
    bounds the total query time so a slow/unresponsive nameserver cannot hang a
    preflight. dnspython is imported lazily so this module imports without it."""
    try:
        import dns.resolver  # noqa: PLC0415
    except Exception:
        return []
    try:
        answers = dns.resolver.resolve(name, "TXT", lifetime=lifetime)
    except Exception:
        return []
    out: List[str] = []
    for rdata in answers:
        # A TXT record is one or more quoted strings; dnspython exposes them as
        # .strings (bytes chunks) which concatenate into the logical value.
        try:
            chunks = b"".join(rdata.strings).decode("utf-8", "replace")
        except Exception:
            chunks = str(rdata).strip('"')
        out.append(chunks)
    return out


@dataclass(frozen=True)
class RecordCheck:
    """One authentication record's status."""

    kind: str               # "spf" | "dmarc" | "dkim"
    present: bool
    value: str | None       # the found record, if present
    detail: str             # human note ("policy=none", "selector=google", ...)
    recommendation: str | None  # the record/action to add if missing or weak
    weak: bool = False      # present but not protective (e.g. DMARC p=none)


@dataclass(frozen=True)
class DomainReport:
    domain: str
    spf: RecordCheck
    dmarc: RecordCheck
    dkim: RecordCheck

    @property
    def all_present(self) -> bool:
        return self.spf.present and self.dmarc.present and self.dkim.present

    @property
    def missing(self) -> list[str]:
        return [c.kind for c in (self.spf, self.dmarc, self.dkim) if not c.present]

    @property
    def summary(self) -> str:
        bits = []
        for c in (self.spf, self.dmarc, self.dkim):
            if not c.present:
                bits.append(f"{c.kind.upper()} missing")
            elif c.weak:
                bits.append(f"{c.kind.upper()} weak ({c.detail})")
            else:
                bits.append(f"{c.kind.upper()} ok")
        return ", ".join(bits)


def generate_spf_record(provider: str = "google") -> str:
    """The recommended SPF TXT value for a sending provider.

    ``~all`` (softfail) is the conservative default: it asserts the listed
    senders are authorized without hard-failing everything else while you
    confirm nothing legitimate sends from elsewhere.
    """
    include = _SPF_INCLUDES.get((provider or "").lower(), "")
    return f"v=spf1 {include} ~all".replace("  ", " ").strip()


def generate_dmarc_record(policy: str = "none", rua_email: str | None = None) -> str:
    """The recommended _dmarc TXT value. ``p=none`` is the right starting policy
    (monitor only); ramp to ``quarantine`` then ``reject`` once SPF+DKIM are
    confirmed aligned. ``rua`` collects aggregate reports if an address is given.
    """
    rec = f"v=DMARC1; p={policy};"
    if rua_email:
        rec += f" rua=mailto:{rua_email};"
    return rec


def check_spf(domain: str, resolve: Resolver, *, provider: str = "google") -> RecordCheck:
    records = resolve(domain)
    spf = [r for r in records if r.lower().startswith("v=spf1")]
    if not spf:
        return RecordCheck(
            "spf", False, None, "no v=spf1 record published",
            recommendation=f'add a TXT record on {domain}:  {generate_spf_record(provider)}',
        )
    # More than one SPF record is itself an error (receivers may permerror).
    if len(spf) > 1:
        return RecordCheck(
            "spf", True, spf[0], f"{len(spf)} SPF records (only one is valid)",
            recommendation="merge into a single v=spf1 TXT record", weak=True,
        )
    return RecordCheck("spf", True, spf[0], "published", recommendation=None)


def check_dmarc(domain: str, resolve: Resolver, *, rua_email: str | None = None) -> RecordCheck:
    records = resolve(f"_dmarc.{domain}")
    dmarc = [r for r in records if r.lower().startswith("v=dmarc1")]
    if not dmarc:
        return RecordCheck(
            "dmarc", False, None, "no _dmarc record published",
            recommendation=f'add a TXT record on _dmarc.{domain}:  {generate_dmarc_record("none", rua_email)}',
        )
    value = dmarc[0]
    policy = "none"
    for part in value.split(";"):
        part = part.strip()
        if part.lower().startswith("p="):
            policy = part.split("=", 1)[1].strip().lower() or "none"
            break
    weak = policy == "none"
    rec = None
    if weak:
        rec = (f"policy is p=none (monitor only); once SPF+DKIM are aligned, "
               f"ramp _dmarc.{domain} to p=quarantine then p=reject")
    return RecordCheck("dmarc", True, value, f"policy={policy}", recommendation=rec, weak=weak)


def check_dkim(
    domain: str, resolve: Resolver, *,
    selectors: tuple[str, ...] = COMMON_DKIM_SELECTORS,
) -> RecordCheck:
    for selector in selectors:
        records = resolve(f"{selector}._domainkey.{domain}")
        if any(("v=dkim1" in r.lower()) or ("k=rsa" in r.lower() and "p=" in r.lower()) for r in records):
            return RecordCheck("dkim", True, None, f"selector={selector}", recommendation=None)
    return RecordCheck(
        "dkim", False, None,
        f"no DKIM key at the common selectors ({', '.join(selectors[:4])}, ...)",
        recommendation=(
            "DKIM is set up in your email provider's admin console, not by hand. "
            "Google Workspace: Apps > Google Workspace > Gmail > Authenticate email, "
            "then publish the TXT record it gives you. Resend: add the domain in the "
            "Resend dashboard and publish the records it generates."
        ),
    )


def inspect_domain(
    domain: str, *,
    resolve: Resolver | None = None,
    provider: str = "google",
    rua_email: str | None = None,
    dkim_selectors: tuple[str, ...] = COMMON_DKIM_SELECTORS,
) -> DomainReport:
    """Inspect SPF + DMARC + DKIM for a domain. Pass ``resolve`` to inject a
    resolver (tests do this); defaults to the live dnspython resolver."""
    r = resolve or resolve_txt_dnspython
    return DomainReport(
        domain=domain,
        spf=check_spf(domain, r, provider=provider),
        dmarc=check_dmarc(domain, r, rua_email=rua_email),
        dkim=check_dkim(domain, r, selectors=dkim_selectors),
    )


def domain_of_email(email: str) -> str | None:
    """The domain part of an email address, lowercased, or None if not an
    address. A placeholder like ``example.com`` is returned as-is; the caller
    decides whether to skip it."""
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].strip().lower() or None
