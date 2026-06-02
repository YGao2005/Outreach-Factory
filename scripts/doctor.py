#!/usr/bin/env python3
"""
doctor.py — preflight checker for outreach-factory.

Reports which features are ready and what's missing. Run after install,
or any time something feels off:

    python3 scripts/doctor.py            # human-readable report
    python3 scripts/doctor.py --json     # machine-readable for /init or scripting
    python3 scripts/doctor.py --quiet    # only print failures

Exit codes:
    0 — all required checks pass (factory is usable, optional features may vary)
    1 — at least one required check failed (factory is not usable as-is)

What it checks:
    Required:
      • config exists + parses
      • factory.home resolves and contains skills/ + orchestrator/
      • vault.path + vault.{people,companies,lead_lists}_dir exist
      • Python deps from orchestrator/requirements.txt importable
      • MCP servers obsidian / linkedin / ScraplingServer configured
      • Pillar B migration framework — warn when migrations are pending
        (Week 2 default; OUTREACH_FACTORY_STRICT_MIGRATIONS=1 opts into
        Week 6 strict mode that promotes WARN→FAIL; Pillar I flips
        strict as the default and removes the env var)

    Optional (each unlocks one or more features):
      • Voice corpus (embeddings.npy + index.json) — voice translator
      • Reoon API key — Tier 2 email verification (Tier 1 MX-check works without)
      • Gmail credentials — /send-outreach Gmail channel
      • Twitter cookies — /research-prospect cross-platform scrape
      • LinkedIn cookies — discovery + send-outreach LinkedIn channels
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

REQUIRED_MCPS = ("obsidian", "linkedin", "ScraplingServer")


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
        return _result("vault", FAIL, "vault.path not set in config")
    vault = Path(path_str).expanduser()
    if not vault.exists():
        return _result("vault", FAIL, f"{vault} does not exist", hint="point vault.path at your markdown CRM root")

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
            hint="create them or fix the names in config (Obsidian default uses '10 People' etc.)",
        )

    # queue_subdir is sometimes auto-created at first run — warn if missing, don't fail
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
        "numpy": "numpy",
        "sentence_transformers": "sentence-transformers",
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


def check_mcp(server_name: str) -> dict:
    user_servers = _load_claude_json().get("mcpServers", {}) or {}
    project_servers = _load_project_mcp(Path.cwd())
    if server_name in user_servers:
        return _result(
            f"mcp.{server_name}", OK, f"configured in ~/.claude.json (reachability tested on first skill invocation)"
        )
    if server_name in project_servers:
        return _result(
            f"mcp.{server_name}", OK, f"configured in {Path.cwd() / '.mcp.json'}"
        )
    return _result(
        f"mcp.{server_name}",
        FAIL,
        "not configured in ~/.claude.json or local .mcp.json",
        hint=f"see INSTALL.md → MCP servers section for setup",
    )


# ============================================================
# Optional features
# ============================================================
def check_voice_corpus(config: dict) -> dict:
    corpus_dir_str = (config.get("voice") or {}).get("corpus_dir", "").strip()
    if not corpus_dir_str or corpus_dir_str.startswith("/path/to/"):
        return _result(
            "voice_corpus",
            FAIL,
            "voice.corpus_dir not configured",
            hint="see voice/README.md for the manual build path from a Gmail Takeout mbox",
            enables="/draft-outreach voice-translate (RAG retrieval against your email corpus)",
        )
    corpus = Path(corpus_dir_str).expanduser()
    emb = corpus / "embeddings.npy"
    idx = corpus / "index.json"
    missing = [str(p.name) for p in (emb, idx) if not p.exists()]
    if missing:
        return _result(
            "voice_corpus",
            FAIL,
            f"corpus dir exists but missing: {', '.join(missing)}",
            hint=f"build it via voice/build_index.py (see voice/README.md)",
            enables="/draft-outreach voice-translate",
        )
    return _result(
        "voice_corpus",
        OK,
        f"{corpus} (embeddings.npy + index.json present)",
        enables="/draft-outreach voice-translate",
    )


def check_reoon_key(config: dict) -> dict:
    enrich = config.get("email_enrich") or {}
    key_path_str = enrich.get("reoon_key_path", "").strip()
    if not key_path_str:
        return _result(
            "reoon_key",
            WARN,
            "email_enrich.reoon_key_path not set — falling back to Tier 1 MX-check (free)",
            hint="set reoon_key_path in config to enable Tier 2 (Reoon power-mode verify)",
            enables="/research-prospect Tier 2 verification",
        )
    key_path = Path(key_path_str).expanduser()
    if not key_path.exists():
        return _result(
            "reoon_key",
            WARN,
            f"reoon_key_path set to {key_path} but file missing — falling back to Tier 1 MX-check",
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
            "email_send.gmail_api is false — Gmail send disabled",
            hint="set gmail_api: true and configure gmail_credentials_path / gmail_token_path",
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
    (exact-match per D29; any other value — ``"true"`` / ``"yes"`` /
    ``"on"`` / ``"0"`` / empty / case variants — is treated as
    not-strict). Strict mode promotes pending-migrations from WARN
    to FAIL, which causes the doctor's exit code to be 1 and
    surfaces a "STRICT mode" prefix in the message so the operator
    can confirm the flag took effect.

    Pillar I (Weeks 43–48) will flip strict as the default and
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
    # doctor.py is invoked as `python scripts/doctor.py` — the repo
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

    # The actual REPL command operators need to apply pending migrations.
    # Surfaced inline in both WARN + FAIL hints (Pillar B Week 6
    # parallel-review P1 fix per `.planning/REVIEW-pillar-b-operator-ux.md`
    # §P1-1). The Pillar I CLI work absorbs this into a proper
    # `python -m orchestrator.migrations apply` invocation; until then
    # the REPL one-liner is the canonical operator path.
    apply_repl = (
        "python -c \"from pathlib import Path; "
        "from orchestrator.migrations import MigrationRunner; "
        "MigrationRunner(vault_dir=Path('~/your-vault').expanduser())"
        ".apply()\""
    )

    # Per ADR-0013 D26 + D29: exact-match "1" opts into strict mode.
    # Read at call time (not import time) so the test harness's
    # monkeypatch.setenv lands. Any other value — including "true",
    # "yes", "on", "0", empty, or case variants — is NOT strict; the
    # exact-match contract gives operators a single unambiguous value
    # to learn.
    strict_mode = os.environ.get("OUTREACH_FACTORY_STRICT_MIGRATIONS") == "1"
    if strict_mode:
        return _result(
            "migrations", FAIL,
            f"STRICT mode: {len(pending)} pending: {listing}",
            hint=f"OUTREACH_FACTORY_STRICT_MIGRATIONS=1 is set; apply: "
                 f"{apply_repl}  (or unset the env var to demote to "
                 f"WARN; see INSTALL.md \"Apply pending migrations\")",
        )
    return _result(
        "migrations", WARN,
        f"{len(pending)} pending: {listing}",
        hint=f"apply: {apply_repl}  (see INSTALL.md \"Apply pending "
             f"migrations\" — Pillar I will harden this to refuse-on-"
             f"pending; opt in early via "
             f"OUTREACH_FACTORY_STRICT_MIGRATIONS=1)",
    )


def check_twitter_cookies(config: dict) -> dict:
    cookies_str = (config.get("scraper_auth") or {}).get("twitter_cookies_path", "").strip()
    if not cookies_str:
        return _result(
            "twitter_cookies",
            WARN,
            "scraper_auth.twitter_cookies_path not set — Twitter scrape falls back to bio-only",
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

    req_pass = sum(1 for r in required if r["status"] == OK)
    opt_pass = sum(1 for r in optional if r["status"] == OK)
    lines.append("")
    if req_pass == len(required):
        lines.append(f"Required: {req_pass}/{len(required)} ✓   Optional features ready: {opt_pass}/{len(optional)}")
    else:
        lines.append(
            f"Required: {req_pass}/{len(required)} — fix the failures above before the factory will work."
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
    for server in REQUIRED_MCPS:
        required.append(check_mcp(server))
    required.append(check_migrations(config))

    optional: list[dict] = []
    if config is not None:
        optional.append(check_voice_corpus(config))
        optional.append(check_reoon_key(config))
        optional.append(check_gmail_creds(config))
        optional.append(check_twitter_cookies(config))

    if args.json:
        print(render_json(required, optional))
    else:
        print(render_human(required, optional, args.quiet))

    return 0 if all(r["status"] != FAIL for r in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
