"""Tier 1 email verification — domain-level MX check (free, no API).

verify_mx() answers a single question: can this domain RECEIVE mail at all?
It does NOT verify the specific mailbox — that's Reoon (Tier 2) or SMTP RCPT
(unreliable). For Tier 1, "has MX records OR A-record fallback" is enough to
ship at modal-pattern risk (~5-10% bounce rate on valid domains, vs ~50%+
bounce on invalid domains).

Per RFC 5321 §5.1: a domain without MX records can still receive mail at its
A-record. So MX-absent + A-present = ok=True (with has_mx=False flagged).

Usage:
    python3 verify_email.py --domain example.com
    python3 verify_email.py --domain example.com --json

As a library:
    from verify_email import verify_mx
    result = verify_mx("example.com", timeout_s=5.0)
    if result["ok"]:
        ...
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    import dns.exception
    import dns.rdatatype
    import dns.resolver
except ImportError:
    sys.stderr.write(
        "ERROR: dnspython not installed. Run:\n"
        "    pip install -r orchestrator/requirements.txt\n"
    )
    sys.exit(1)


def verify_mx(domain: str, timeout_s: float = 5.0) -> dict:
    """Return {"ok", "domain", "has_mx", "mx_hosts", "reason"} for `domain`.

    ok=True means the domain CAN receive mail (MX records present OR A-record
    fallback per RFC 5321 §5.1). Does NOT verify the mailbox — that's Tier 2.

    Network errors (timeout, NXDOMAIN, generic DNS error) are caught and
    returned as ok=False with a reason string. Never raises.
    """
    domain = (domain or "").strip().lower()
    result: dict = {
        "ok": False,
        "domain": domain,
        "has_mx": False,
        "mx_hosts": [],
        "reason": "",
    }
    if not domain:
        result["reason"] = "empty domain"
        return result

    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout_s
    resolver.lifetime = timeout_s

    try:
        mx_answers = resolver.resolve(domain, dns.rdatatype.MX)
        hosts = sorted(
            (str(r.exchange).rstrip(".") for r in mx_answers),
            key=lambda h: (h == "", h),
        )
        result.update(ok=True, has_mx=True, mx_hosts=hosts, reason="mx records present")
        return result
    except dns.resolver.NoAnswer:
        # No MX — try A-record fallback (RFC 5321 §5.1)
        pass
    except dns.resolver.NXDOMAIN:
        result["reason"] = "domain does not exist"
        return result
    except dns.exception.Timeout:
        result["reason"] = f"timeout after {timeout_s}s"
        return result
    except dns.exception.DNSException as e:
        result["reason"] = f"dns error: {e.__class__.__name__}"
        return result

    try:
        resolver.resolve(domain, dns.rdatatype.A)
        result.update(ok=True, has_mx=False, reason="a-record fallback (no mx)")
        return result
    except dns.resolver.NXDOMAIN:
        result["reason"] = "domain does not exist"
    except dns.resolver.NoAnswer:
        result["reason"] = "no mx and no a record"
    except dns.exception.Timeout:
        result["reason"] = f"timeout after {timeout_s}s"
    except dns.exception.DNSException as e:
        result["reason"] = f"dns error: {e.__class__.__name__}"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Tier 1 email domain verification (MX-check, free).")
    ap.add_argument("--domain", required=True, help="domain to check, e.g. example.com")
    ap.add_argument("--timeout", type=float, default=5.0, help="DNS timeout in seconds")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of human-readable")
    args = ap.parse_args()

    result = verify_mx(args.domain, timeout_s=args.timeout)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "OK " if result["ok"] else "BAD"
        host_brief = f" ({len(result['mx_hosts'])} mx)" if result["has_mx"] else ""
        print(f"{status}  {result['domain']}{host_brief}  — {result['reason']}")
        if result["has_mx"]:
            for h in result["mx_hosts"]:
                print(f"      mx: {h}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
