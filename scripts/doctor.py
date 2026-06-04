#!/usr/bin/env python3
"""
doctor.py - preflight checker for outreach-factory.

Reports which features are ready and what's missing. Run after install,
or any time something feels off:

    python3 scripts/doctor.py            # human-readable report
    python3 scripts/doctor.py --json     # machine-readable for /init or scripting
    python3 scripts/doctor.py --quiet    # only print failures

Exit codes:
    0 - all required checks pass (factory is usable, optional features may vary)
    1 - at least one required check failed (factory is not usable as-is)

What it checks:
    Required:
      • config exists + parses
      • factory.home resolves and contains skills/ + orchestrator/
      • vault.path + vault.{people,companies,lead_lists}_dir exist
      • Python deps from orchestrator/requirements.txt importable
      • Pillar B migration framework - warn when migrations are pending
        (Week 2 default; OUTREACH_FACTORY_STRICT_MIGRATIONS=1 opts into
        Week 6 strict mode that promotes WARN to FAIL; Pillar I flips
        strict as the default and removes the env var)

    Optional (each unlocks one or more features):
      • MCP servers (obsidian / linkedin / ScraplingServer) - discovery and
        the LinkedIn channel; the core onboarding + email send loop needs none
        of them (it runs on config + Gmail + the markdown vault)
      • Reoon API key - Tier 2 email verification (Tier 1 MX-check works without)
      • Gmail credentials - /send-outreach Gmail channel
      • Twitter cookies - /research-prospect cross-platform scrape
      • LinkedIn cookies - discovery + send-outreach LinkedIn channels
                          (this lives inside the linkedin MCP config, not visible here)

MCP reachability caveat: this script can verify a server is *configured* in
~/.claude.json or .mcp.json, but it can't probe live MCP servers because they
are session-scoped to a Claude Code interactive session. Reachability is
tested implicitly on first skill invocation.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

OK = "ok"
WARN = "warn"
FAIL = "fail"

ICONS = {OK: "✓", WARN: "⚠", FAIL: "✗"}

# MCP servers are NOT required for the core path. Onboarding (`config` / `init`
# / `status`) and the email draft+send loop run on config + Gmail + the markdown
# vault (the vault is plain `.md` files; the deterministic writeback in
# skills/send-outreach/scripts/vault.py reads/writes them directly). These three
# unlock discovery and the LinkedIn channel only, so they are OPTIONAL features:
# a missing one WARNs with what it enables and never fails the preflight.
FEATURE_MCPS: tuple[tuple[str, str], ...] = (
    ("obsidian",
     "vault search/patch in the discovery + send skills (/find-leads, "
     "/research-prospect, /send-outreach); the skills also work on the vault's "
     "markdown files directly"),
    ("linkedin",
     "the LinkedIn send channel and LinkedIn discovery (/find-leads, "
     "/research-prospect, /competitor-customers)"),
    ("ScraplingServer",
     "web-scrape discovery in /find-leads and /research-prospect"),
)


def _config_path() -> Path:
    return Path(os.environ.get("OUTREACH_FACTORY_CONFIG", "~/.outreach-factory/config.yml")).expanduser()


def _result(name: str, status: str, message: str, hint: str = "", enables: str = "") -> dict:
    return {"name": name, "status": status, "message": message, "hint": hint, "enables": enables}


# ============================================================
# Config + factory home
# ============================================================
def check_config() -> tuple[dict, dict | None]:
    """Returns (CheckResult, parsed_config_or_None)."""
    path = _config_path()
    if not path.exists():
        return (
            _result(
                "config",
                FAIL,
                f"config not found at {path}",
                hint="cp config-template/config.example.yml ~/.outreach-factory/config.yml && edit",
            ),
            None,
        )
    try:
        import yaml

        cfg = yaml.safe_load(path.read_text())
        return (_result("config", OK, f"parsed {path}"), cfg)
    except ImportError:
        return (
            _result(
                "config",
                FAIL,
                "pyyaml not installed (can't parse config)",
                hint="pip install -r orchestrator/requirements.txt",
            ),
            None,
        )
    except Exception as e:
        return (
            _result("config", FAIL, f"config parse error: {e.__class__.__name__}: {e}"),
            None,
        )


def check_factory_home(config: dict) -> dict:
    home_str = (config.get("factory") or {}).get("home", "").strip()
    if not home_str:
        return _result("factory.home", FAIL, "factory.home not set in config")
    home = Path(home_str).expanduser()
    if not home.exists():
        return _result("factory.home", FAIL, f"{home} does not exist", hint="check the path or `git clone` the repo there")
    missing = [d for d in ("skills", "orchestrator") if not (home / d).is_dir()]
    if missing:
        return _result(
            "factory.home",
            FAIL,
            f"{home} is missing required subdirs: {', '.join(missing)}",
            hint="check that factory.home points at the cloned outreach-factory repo root",
        )
    return _result("factory.home", OK, f"{home} (skills/ + orchestrator/ present)")


# ============================================================
# Vault
# ============================================================
def check_vault(config: dict) -> dict:
    v = config.get("vault") or {}
    path_str = v.get("path", "").strip()
    if not path_str:
        return _result(
            "vault", FAIL, "vault.path not set in config",
            hint="point vault.path at a plain folder of .md files (an Obsidian "
                 "vault works, but the Obsidian app is not required)",
        )
    vault = Path(path_str).expanduser()
    if not vault.exists():
        return _result(
            "vault", FAIL, f"{vault} does not exist",
            hint="point vault.path at your markdown CRM root: a plain folder of "
                 ".md files (the Obsidian app is not required), then run "
                 "`outreach-factory migrate` to scaffold it",
        )

    missing = [
        f"{name}={v.get(name)!r}"
        for name in ("people_dir", "companies_dir", "lead_lists_dir")
        if not v.get(name) or not (vault / v[name]).is_dir()
    ]
    if missing:
        return _result(
            "vault",
            FAIL,
            f"{vault} missing subdirs: {', '.join(missing)}",
            hint="run `outreach-factory migrate` to create them, or fix the names "
                 "in config (Obsidian default uses '10 People' etc.)",
        )

    # queue_subdir is sometimes auto-created at first run - warn if missing, don't fail
    queue_sub = v.get("queue_subdir", "").strip()
    if queue_sub and not (vault / v["people_dir"] / queue_sub).is_dir():
        return _result(
            "vault",
            WARN,
            f"{vault}/{v['people_dir']}/{queue_sub} not yet created (will be auto-created at first /find-leads)",
        )
    return _result("vault", OK, f"{vault} (people/companies/lead_lists/queue all present)")


# ============================================================
# Python deps
# ============================================================
def check_python_deps() -> dict:
    needed = {
        "yaml": "pyyaml",
        "dns.resolver": "dnspython",
    }
    missing = []
    for module, pkg in needed.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(pkg)
    if missing:
        return _result(
            "python_deps",
            FAIL,
            f"missing: {', '.join(missing)}",
            hint="pip install -r orchestrator/requirements.txt",
        )
    return _result("python_deps", OK, f"all importable ({', '.join(needed.values())})")


# ============================================================
# MCPs
# ============================================================
def _load_claude_json() -> dict:
    path = Path("~/.claude.json").expanduser()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _load_project_mcp(cwd: Path) -> dict:
    """Read .mcp.json in cwd if present (project-shared MCP config)."""
    candidate = cwd / ".mcp.json"
    if not candidate.exists():
        return {}
    try:
        return (json.loads(candidate.read_text()) or {}).get("mcpServers", {}) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def check_mcp(server_name: str, enables: str = "") -> dict:
    """An OPTIONAL feature MCP. Configured -> OK; missing -> WARN (never FAIL),
    because none of these are needed for onboarding or the core email send
    loop. ``enables`` describes what the server unlocks so the operator can
    decide whether they want it."""
    user_servers = _load_claude_json().get("mcpServers", {}) or {}
    project_servers = _load_project_mcp(Path.cwd())
    if server_name in user_servers:
        return _result(
            f"mcp.{server_name}", OK,
            "configured in ~/.claude.json (reachability tested on first skill invocation)",
            enables=enables,
        )
    if server_name in project_servers:
        return _result(
            f"mcp.{server_name}", OK,
            f"configured in {Path.cwd() / '.mcp.json'}",
            enables=enables,
        )
    hint = "optional; not needed for onboarding or the core email send loop. See INSTALL.md (MCP servers)."
    if enables:
        hint = f"optional; enables {enables} (not needed for the core path). See INSTALL.md (MCP servers)."
    return _result(
        f"mcp.{server_name}", WARN,
        "not configured in ~/.claude.json or local .mcp.json",
        hint=hint,
        enables=enables,
    )


# ============================================================
# Optional features
# ============================================================
def check_reoon_key(config: dict) -> dict:
    enrich = config.get("email_enrich") or {}
    key_path_str = enrich.get("reoon_key_path", "").strip()
    if not key_path_str:
        return _result(
            "reoon_key",
            WARN,
            "email_enrich.reoon_key_path not set - falling back to Tier 1 MX-check (free)",
            hint="set reoon_key_path in config to enable Tier 2 (Reoon power-mode verify)",
            enables="/research-prospect Tier 2 verification",
        )
    key_path = Path(key_path_str).expanduser()
    if not key_path.exists():
        return _result(
            "reoon_key",
            WARN,
            f"reoon_key_path set to {key_path} but file missing - falling back to Tier 1 MX-check",
            hint=f"create {key_path} (chmod 600) with your Reoon API key",
            enables="/research-prospect Tier 2 verification",
        )
    return _result(
        "reoon_key",
        OK,
        f"{key_path} present",
        enables="/research-prospect Tier 2 verification",
    )


def check_gmail_creds(config: dict) -> dict:
    send = config.get("email_send") or {}
    if not send.get("gmail_api"):
        return _result(
            "gmail_creds",
            WARN,
            "email_send.gmail_api is false - Gmail send disabled",
            hint="set gmail_api: true and configure gmail_credentials_path / gmail_token_path",
            enables="/send-outreach Gmail channel",
        )
    # The Google send libraries live in skills/send-outreach/requirements.txt,
    # NOT orchestrator/requirements.txt. With gmail_api on but those missing,
    # `init` crashes on import; surface that here so doctor is not falsely green.
    try:
        importlib.import_module("google.auth")
    except ImportError:
        return _result(
            "gmail_creds",
            FAIL,
            "gmail_api is true but the Google send deps are not installed",
            hint="pip install -r skills/send-outreach/requirements.txt",
            enables="/send-outreach Gmail channel",
        )
    creds_str = send.get("gmail_credentials_path", "").strip()
    creds = (
        Path(creds_str).expanduser()
        if creds_str
        else Path("~/.outreach-factory/credentials/gmail_credentials.json").expanduser()
    )
    if not creds.exists():
        return _result(
            "gmail_creds",
            FAIL,
            f"gmail credentials not at {creds}",
            hint="download OAuth JSON from Google Cloud Console; see docs/OPTIONAL-FEATURES.md",
            enables="/send-outreach Gmail channel",
        )
    return _result("gmail_creds", OK, f"{creds} present", enables="/send-outreach Gmail channel")


def check_deliverability(config: dict) -> dict:
    """Inspect SPF / DKIM / DMARC on the sending domain (the domain of
    founder.email). A sending domain with no email authentication is the
    number-one 'it bounced / landed in spam' cause.

    Resilient by design: this does live DNS lookups, so a resolver failure
    WARNs (never FAILs), and an unset/placeholder domain is skipped. Probes a
    focused DKIM selector set so the preflight stays fast.
    """
    founder = config.get("founder") or {}
    email = (founder.get("email") or "").strip()

    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from orchestrator import dns_check
    except Exception as exc:
        return _result("deliverability", WARN, f"dns_check not importable: {exc}")

    domain = dns_check.domain_of_email(email)
    if not domain or domain in ("example.com", "yourcompany.com"):
        return _result(
            "deliverability", WARN,
            "no real sending domain configured (founder.email unset or a placeholder)",
            hint="set founder.email to your real sending address to check SPF/DKIM/DMARC",
            enables="cold email that reaches the inbox",
        )

    # Shared consumer-provider mailboxes manage SPF/DKIM/DMARC themselves and you
    # cannot set DNS on them, so a "missing SPF" verdict there is just noise.
    # Say the honest thing instead.
    shared_providers = {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
        "msn.com", "yahoo.com", "ymail.com", "icloud.com", "me.com", "aol.com",
        "proton.me", "protonmail.com",
    }
    if domain in shared_providers:
        return _result(
            "deliverability", WARN,
            f"sending from a shared provider mailbox ({domain})",
            hint="SPF/DKIM/DMARC are managed by the provider, not you; nothing to "
                 "fix here. Cold-email deliverability tuning and the warming ramp "
                 "apply once you send from your own domain (a provider mailbox is "
                 "fine for low volume).",
            enables="cold email that reaches the inbox",
        )

    send = config.get("email_send") or {}
    provider = "resend" if (send.get("resend_api_key") or "").strip() else "google"
    try:
        report = dns_check.inspect_domain(
            domain, provider=provider, rua_email=email,
            dkim_selectors=("google", "resend", "default", "selector1", "selector2"),
        )
    except Exception as exc:
        return _result(
            "deliverability", WARN,
            f"could not query DNS for {domain} ({type(exc).__name__}); skipping",
            hint="re-run with network access to check SPF/DKIM/DMARC",
        )

    if report.all_present and not (report.spf.weak or report.dmarc.weak):
        return _result(
            "deliverability", OK,
            f"{domain}: SPF + DKIM + DMARC all published",
            enables="cold email that reaches the inbox",
        )

    fixes = [
        f"{c.kind.upper()} {'MISSING' if not c.present else 'WEAK'}: {c.recommendation}"
        for c in (report.spf, report.dmarc, report.dkim)
        if (not c.present or c.weak) and c.recommendation
    ]
    return _result(
        "deliverability", WARN,
        f"{domain}: {report.summary}",
        hint="  |  ".join(fixes),
        enables="cold email that reaches the inbox",
    )


def check_migrations(config: dict | None) -> dict:
    """Detect pending Pillar B migrations.

    Per Pillar B Week 2: warn when migrations are pending. The
    factory still runs (operators may not have applied migrations
    yet, and the migration framework refuses partial-apply at the
    state-file level), but the operator is alerted that schema-
    versioned features may behave on un-migrated data until apply
    runs.

    Per Pillar B Week 6 (ADR-0013 D26): operators can opt into
    strict mode by setting ``OUTREACH_FACTORY_STRICT_MIGRATIONS=1``
    (exact-match per D29; any other value - ``"true"`` / ``"yes"`` /
    ``"on"`` / ``"0"`` / empty / case variants - is treated as
    not-strict). Strict mode promotes pending-migrations from WARN
    to FAIL, which causes the doctor's exit code to be 1 and
    surfaces a "STRICT mode" prefix in the message so the operator
    can confirm the flag took effect.

    Pillar I (Weeks 43-48) will flip strict as the default and
    remove the env var, once operators have had ~37 weeks to
    internalize the migration discipline. The Week 6 feature flag
    is the soft-rollout precursor.

    WARN (not FAIL) by default per ADR-0009 D5 / D12. The
    asymmetric-failure-cost calculus: a default-strict refuse
    (operator is mid-applying, doctor blocks) is worse than a
    default-soft warn (operator sees the notice and applies on
    their schedule). Operators who want belt-and-suspenders
    enforcement opt in via the env var.
    """
    # doctor.py is invoked as `python scripts/doctor.py` - the repo
    # root is one level above this file. Adding it to sys.path lets us
    # import `orchestrator.migrations` regardless of cwd.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from orchestrator.migrations import MigrationRunner
    except ImportError as exc:
        return _result(
            "migrations", WARN,
            f"migration framework not importable: {exc}",
            hint=f"expected orchestrator/ under {repo_root}; check "
                 f"that this script lives in scripts/ at the repo root",
        )

    vault_dir = None
    if config:
        path_str = (config.get("vault") or {}).get("path", "").strip()
        if path_str:
            candidate = Path(path_str).expanduser()
            if candidate.exists():
                vault_dir = candidate

    # Evaluate Path.home() at call time (not import time) so tests
    # that monkeypatch HOME see the right state dir. The runner's
    # DEFAULT_STATE_DIR is frozen at module-import time, which is too
    # early for the test harness.
    state_dir = Path.home() / ".outreach-factory"
    try:
        runner = MigrationRunner(state_dir=state_dir, vault_dir=vault_dir)
        pending = runner.pending()
    except Exception as exc:
        return _result(
            "migrations", WARN,
            f"migration runner construction failed: "
            f"{exc.__class__.__name__}: {exc}",
            hint="see ADR-0009; check ~/.outreach-factory/"
                 "migrations.state.json for corruption",
        )

    if not pending:
        return _result(
            "migrations", OK,
            "no pending migrations",
        )

    listing = ", ".join(f"{m.category.value}/{m.id}" for m in pending)

    # The operator command to apply pending migrations. The CLI wraps the
    # runner so it sets sys.path + creates the vault/ledger/policy dirs itself
    # (the old hand-edited REPL one-liner crashed on a fresh clone: a bare
    # `import ledger` and a missing policy dir). Surfaced inline in both the
    # WARN + FAIL hints.
    apply_cmd = "outreach-factory migrate"

    # Per ADR-0013 D26 + D29: exact-match "1" opts into strict mode.
    # Read at call time (not import time) so the test harness's
    # monkeypatch.setenv lands. Any other value - including "true",
    # "yes", "on", "0", empty, or case variants - is NOT strict; the
    # exact-match contract gives operators a single unambiguous value
    # to learn.
    strict_mode = os.environ.get("OUTREACH_FACTORY_STRICT_MIGRATIONS") == "1"
    if strict_mode:
        return _result(
            "migrations", FAIL,
            f"STRICT mode: {len(pending)} pending: {listing}",
            hint=f"OUTREACH_FACTORY_STRICT_MIGRATIONS=1 is set; apply: "
                 f"{apply_cmd}  (or unset the env var to demote to "
                 f"WARN; see INSTALL.md \"Apply pending migrations\")",
        )
    return _result(
        "migrations", WARN,
        f"{len(pending)} pending: {listing}",
        hint=f"apply: {apply_cmd}  (see INSTALL.md \"Apply pending "
             f"migrations\" - Pillar I will harden this to refuse-on-"
             f"pending; opt in early via "
             f"OUTREACH_FACTORY_STRICT_MIGRATIONS=1)",
    )


def check_twitter_cookies(config: dict) -> dict:
    cookies_str = (config.get("scraper_auth") or {}).get("twitter_cookies_path", "").strip()
    if not cookies_str:
        return _result(
            "twitter_cookies",
            WARN,
            "scraper_auth.twitter_cookies_path not set - Twitter scrape falls back to bio-only",
            enables="/research-prospect Twitter cross-platform scrape",
        )
    cookies = Path(cookies_str).expanduser()
    if not cookies.exists():
        return _result(
            "twitter_cookies",
            WARN,
            f"twitter_cookies_path set to {cookies} but file missing",
            hint="export logged-in cookies as JSON; see skills/research-prospect/auth/README.md",
            enables="/research-prospect Twitter cross-platform scrape",
        )
    return _result(
        "twitter_cookies",
        OK,
        f"{cookies} present",
        enables="/research-prospect Twitter cross-platform scrape",
    )


# ============================================================
# Reporting
# ============================================================
def render_human(required: list[dict], optional: list[dict], quiet: bool) -> str:
    lines: list[str] = []

    def render_section(title: str, items: list[dict], show_optional_hint: bool = False) -> None:
        lines.append(f"\n{title}:")
        for r in items:
            if quiet and r["status"] == OK:
                continue
            icon = ICONS[r["status"]]
            lines.append(f"  {icon} {r['name']:<22} {r['message']}")
            if show_optional_hint and r.get("enables") and r["status"] == OK:
                lines.append(f"     → enables: {r['enables']}")
            if r.get("hint") and r["status"] != OK:
                lines.append(f"     hint: {r['hint']}")

    render_section("Required", required)
    render_section("Optional features", optional, show_optional_hint=True)

    req_fail = [r for r in required if r["status"] == FAIL]
    req_warn = [r for r in required if r["status"] == WARN]
    opt_pass = sum(1 for r in optional if r["status"] == OK)
    lines.append("")
    if not req_fail:
        # Exit code is 0 here: the core onboarding + email send path is usable.
        # WARNs (e.g. pending migrations, which `init` applies) are advisory,
        # not blockers, so do not tell the newcomer to "fix failures".
        warn_note = ""
        if req_warn:
            n = len(req_warn)
            warn_note = f" ({n} warning{'s' if n != 1 else ''}, e.g. pending migrations that `init` applies)"
        lines.append(
            f"Core path: usable{warn_note}.   Optional features ready: {opt_pass}/{len(optional)}"
        )
    else:
        names = ", ".join(r["name"] for r in req_fail)
        lines.append(
            f"Core path: BLOCKED. Fix the required failure(s) before the factory will work: {names}."
        )
    return "\n".join(lines)


def render_json(required: list[dict], optional: list[dict]) -> str:
    req_pass = sum(1 for r in required if r["status"] == OK)
    opt_pass = sum(1 for r in optional if r["status"] == OK)
    payload = {
        "required": required,
        "optional": optional,
        "summary": {
            "required_pass": req_pass,
            "required_total": len(required),
            "optional_pass": opt_pass,
            "optional_total": len(optional),
            "all_required_ok": req_pass == len(required),
        },
    }
    return json.dumps(payload, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser(description="outreach-factory preflight checker")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of human-readable")
    ap.add_argument("--quiet", action="store_true", help="only show failures (human mode)")
    args = ap.parse_args()

    cfg_check, config = check_config()
    required: list[dict] = [cfg_check]

    if config is not None:
        required.append(check_factory_home(config))
        required.append(check_vault(config))
    required.append(check_python_deps())
    required.append(check_migrations(config))

    # MCP servers are optional features (discovery + the LinkedIn channel), not
    # part of the core onboarding + email send path, so they live in `optional`
    # and WARN (never FAIL) when missing. The exit code reflects "is the core
    # path usable", not "is every feature wired".
    optional: list[dict] = []
    for server, enables in FEATURE_MCPS:
        optional.append(check_mcp(server, enables))
    if config is not None:
        optional.append(check_reoon_key(config))
        optional.append(check_gmail_creds(config))
        optional.append(check_deliverability(config))
        optional.append(check_twitter_cookies(config))

    if args.json:
        print(render_json(required, optional))
    else:
        print(render_human(required, optional, args.quiet))

    return 0 if all(r["status"] != FAIL for r in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
