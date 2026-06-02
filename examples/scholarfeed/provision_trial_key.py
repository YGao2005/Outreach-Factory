#!/usr/bin/env python3
"""Provision a ScholarFeed 2-week Pro trial key for a cold-outreach recipient.

Calls the live admin endpoint (POST .../admin/trial-keys) — idempotent on email —
and returns the one-time ``api_key`` to embed as the outreach CTA. The admin secret
is read from ``$SCHOLARFEED_ADMIN_SECRET`` or the ``scholarfeed.admin_secret_path``
file named in the operator config. The secret is NEVER hardcoded or committed.

Usage:
  python provision_trial_key.py --email researcher@uni.edu [--name LABEL]
                                [--trial-days 14] [--json] [--dry-run]

Config is selected via $OUTREACH_FACTORY_CONFIG (default ~/.outreach-factory/config.yml):
  scholarfeed:
    admin_trial_keys_url: https://api.scholarfeed.org/api/v1/admin/trial-keys
    admin_secret_path: ~/.outreach-factory/scholarfeed_admin_secret.txt
    trial_days: 14

Output: the ``api_key`` (sf_…) on stdout (pipeable); a one-line summary on stderr.
Exit non-zero with an operator-readable message on a missing secret, a 409
(recipient is an active paid subscriber — won't downgrade), or any HTTP/network error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

DEFAULT_URL = "https://api.scholarfeed.org/api/v1/admin/trial-keys"


def _config_path() -> Path:
    override = os.environ.get("OUTREACH_FACTORY_CONFIG", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / ".outreach-factory" / "config.yml"


def _scholarfeed_cfg() -> dict:
    p = _config_path()
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text()) or {}
    sf = data.get("scholarfeed")
    return sf if isinstance(sf, dict) else {}


def _resolve_secret(cfg: dict) -> str:
    # Env first (override / CI), then the secret-file path named in config.
    env = os.environ.get("SCHOLARFEED_ADMIN_SECRET", "").strip()
    if env:
        return env
    path = cfg.get("admin_secret_path")
    if path:
        f = Path(os.path.expanduser(str(path)))
        if f.exists():
            return f.read_text().strip()
    return ""


def provision(
    email: str,
    *,
    name: str | None = None,
    trial_days: int | None = None,
    dry_run: bool = False,
) -> dict | None:
    cfg = _scholarfeed_cfg()
    url = cfg.get("admin_trial_keys_url") or DEFAULT_URL
    secret = _resolve_secret(cfg)
    if not secret:
        sys.exit(
            "ERROR: no admin secret found. Set $SCHOLARFEED_ADMIN_SECRET, or point "
            "scholarfeed.admin_secret_path in your outreach-factory config at a "
            "readable secret file."
        )

    body: dict[str, object] = {"email": email}
    if name:
        body["name"] = name
    td = trial_days if trial_days is not None else cfg.get("trial_days")
    if td:
        body["trial_days"] = int(td)

    if dry_run:
        masked = (secret[:4] + "…" + secret[-2:]) if len(secret) > 6 else "…"
        print("DRY RUN — would POST (no request sent):")
        print(f"  url:     {url}")
        print(f"  headers: X-Admin-Secret: {masked} ; Content-Type: application/json")
        print(f"  body:    {json.dumps(body)}")
        return None

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"X-Admin-Secret": secret, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:  # 4xx/5xx
        detail = e.read().decode(errors="replace")
        if e.code == 409:
            sys.exit(
                f"REFUSED (409): {email} is an active paid subscriber — the endpoint "
                f"won't downgrade a customer. {detail}"
            )
        sys.exit(f"ERROR {e.code} from trial-keys endpoint: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR reaching {url}: {e.reason}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Mint a ScholarFeed 2-week Pro trial key (cold-outreach CTA)."
    )
    ap.add_argument("--email", required=True, help="recipient email (idempotent key)")
    ap.add_argument("--name", default=None, help="key label (default: trial:<email>)")
    ap.add_argument("--trial-days", type=int, default=None, help="1-60, default 14")
    ap.add_argument("--json", action="store_true", help="print the full JSON response")
    ap.add_argument(
        "--dry-run", action="store_true", help="print the request without sending it"
    )
    args = ap.parse_args(argv)

    data = provision(
        args.email, name=args.name, trial_days=args.trial_days, dry_run=args.dry_run
    )
    if data is None:  # dry-run
        return 0

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(data.get("api_key", ""))  # stdout = the key (pipeable)
        print(
            f"# account={data.get('account')} tier={data.get('tier')} "
            f"limit={data.get('daily_call_limit')}/day "
            f"expires={data.get('trial_expires_at')} "
            f"prefix={data.get('key_prefix')} "
            f"revoked_prior={data.get('revoked_prior_keys')}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
