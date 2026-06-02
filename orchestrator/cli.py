#!/usr/bin/env python3
"""outreach-factory command-line entrypoint.

The dedicated onboarding surface. Subcommands:

  demo       Zero-setup walkthrough on a fake prospect: prints the four
             pipeline stages from committed sample files. No Gmail, no API,
             no model download. The live version is `/draft-outreach --demo`.
  init       Zero-to-test-send onboarding. Builds a TenantConfig from your
             ~/.outreach-factory/config.yml and runs the init wizard
             (Gmail OAuth -> vault setup -> first prospect -> a test send).
             Idempotent: re-running after success is a no-op.
  doctor     Run the preflight checks (scripts/doctor.py).
  config     Copy the config + .env templates into ~/.outreach-factory/.

Run via the `bin/outreach-factory` shim or `python3 -m orchestrator.cli`.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# This module lives at orchestrator/cli.py. Put the repo root on sys.path so
# `import orchestrator.multi_tenant` works when run as a plain script.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SEND_SCRIPTS = REPO_ROOT / "skills" / "send-outreach" / "scripts"
CONFIG_TEMPLATE = REPO_ROOT / "config-template" / "config.example.yml"
ENV_TEMPLATE = REPO_ROOT / "config-template" / ".env.example"
DEFAULT_HOME = Path.home() / ".outreach-factory"
DEMO_DIR = REPO_ROOT / "examples" / "demo"


def _config_path() -> Path:
    override = os.environ.get("OUTREACH_FACTORY_CONFIG", "").strip()
    return Path(os.path.expanduser(override)) if override else DEFAULT_HOME / "config.yml"


def _slug_tenant_id(name: str) -> str:
    """Derive a valid tenant_id (^[a-z][a-z0-9_-]{0,62}$) from a company name."""
    s = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
    if not s or not s[0].isalpha():
        s = "tenant" + (f"-{s}" if s else "")
    return s[:63]


def _tenant_config_from_user_config(cfg: dict, *, home: Path):
    """Bridge the single-tenant user config.yml to the multi-tenant TenantConfig
    the init wizard consumes. Directory defaults match the canonical factory
    locations under ~/.outreach-factory/ so the wizard's enrollment + test send
    land where the skills and daemon read."""
    from orchestrator.multi_tenant import TENANT_OAUTH_TOKEN_SCOPES, TenantConfig

    company = cfg.get("company") or {}
    factory = cfg.get("factory") or {}
    vault = cfg.get("vault") or {}
    email = cfg.get("email_send") or {}

    tenant_id = factory.get("tenant_id") or _slug_tenant_id(company.get("name", "tenant"))

    vault_path = vault.get("path")
    if not vault_path:
        raise SystemExit(
            "ERROR: vault.path is not set in your config. Fill it in and re-run `init`."
        )
    vault_dir = Path(os.path.expanduser(str(vault_path))).resolve()

    token_path = email.get("gmail_token_path")
    oauth_token_path = (
        Path(os.path.expanduser(str(token_path))).resolve()
        if token_path
        else home / "credentials" / "gmail_token.json"
    )

    # The onboarding critical path only needs send + readback.
    scopes = frozenset({"gmail.send", "gmail.readonly"}) & TENANT_OAUTH_TOKEN_SCOPES

    return TenantConfig(
        tenant_id=tenant_id,
        vault_dir=vault_dir,
        ledger_dir=home / "ledger",
        policy_dir=home / "policy",
        oauth_token_path=oauth_token_path,
        oauth_token_scopes=scopes,
        grafana_folder_uid=f"folder-{tenant_id}",
        lifecycle_state="active",
    )


class _DryRunGmail:
    """Fake Gmail client for `init --dry-run`: exercises the wizard's send +
    read-back surface WITHOUT real OAuth or a real send. Mirrors the seam shape
    at tests/test_reconcile.py:78."""

    def __init__(self, sender_email: str = "you@example.com") -> None:
        self.sender_email = sender_email
        self.sent: list[dict] = []

    def send_email(self, to, subject, body, extra_headers=None, **_kw):
        mid = f"m_{len(self.sent) + 1}"
        self.sent.append(
            {"id": mid, "threadId": f"th_{mid}", "to": to,
             "headers": dict(extra_headers or {}), "body": body}
        )
        return mid, f"th_{mid}"

    def search_messages(self, query, max_results=100):
        hdr = "X-Outreach-Intent-Id"
        return [
            {"id": m["id"], "threadId": m["threadId"]}
            for m in self.sent
            if query in m["body"] or query == m["headers"].get(hdr)
        ]

    def get_message(self, msg_id):
        return next((m for m in self.sent if m["id"] == msg_id), None)


def cmd_config(_args) -> int:
    """Copy the config + .env templates into ~/.outreach-factory/ (no overwrite)."""
    DEFAULT_HOME.mkdir(parents=True, exist_ok=True)
    targets = [
        (CONFIG_TEMPLATE, DEFAULT_HOME / "config.yml"),
        (ENV_TEMPLATE, DEFAULT_HOME / ".env"),
    ]
    for src, dst in targets:
        if dst.exists():
            print(f"  exists, leaving as-is: {dst}")
        else:
            dst.write_text(src.read_text())
            print(f"  created: {dst}  (from {src.name})")
    print("\nNext: edit the files above, then run `outreach-factory init`.")
    return 0


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file's leading frontmatter from its body using only the
    standard library. The demo's frontmatter is flat ``key: value`` scalars, so
    a full YAML parser is not needed; keeping the demo dependency-free means
    `bin/outreach-factory demo` runs on a bare clone with nothing installed.

    Returns ``({}, text)`` when there is no frontmatter block.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) != 3:
        return {}, text
    fm: dict[str, str] = {}
    for line in parts[1].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm, parts[2].lstrip("\n")


def _indent(text: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join(pad + line if line else line for line in text.splitlines())


def _parse_demo_corpus(text: str) -> list[dict]:
    """Parse examples/demo/voice-corpus.md into exemplar dicts (stdlib only).

    Each exemplar is a ``## id | register | channel | date`` block with an
    optional ``Subject:`` line followed by the body. Prose before the first
    ``##`` header is ignored.
    """
    exemplars: list[dict] = []
    current: dict | None = None
    body_lines: list[str] = []

    def _flush() -> None:
        if current is not None:
            current["body"] = "\n".join(body_lines).strip()
            exemplars.append(current)

    for line in text.splitlines():
        if line.startswith("## "):
            _flush()
            fields = [f.strip() for f in line[3:].split("|")]
            fields += [""] * (4 - len(fields))
            current = {
                "id": fields[0], "register": fields[1],
                "channel": fields[2], "date": fields[3], "subject": None,
            }
            body_lines = []
        elif current is not None:
            if current["subject"] is None and line.startswith("Subject:"):
                current["subject"] = line.split(":", 1)[1].strip()
            else:
                body_lines.append(line)
    _flush()
    return exemplars


def cmd_demo(_args) -> int:
    """Zero-setup walkthrough: print the four pipeline stages for a fake
    prospect using only committed sample files. No Gmail, no MCP, no API, no
    model download. The live, agent-generated version is `/draft-outreach
    --demo` inside Claude Code (see examples/demo/README.md)."""
    prospect_path = DEMO_DIR / "vault" / "Riley Okafor.md"
    corpus_path = DEMO_DIR / "voice-corpus.md"
    scaffold_path = DEMO_DIR / "scaffold.md"
    draft_path = DEMO_DIR / "sample-draft.md"

    missing = [p for p in (prospect_path, corpus_path, scaffold_path, draft_path) if not p.exists()]
    if missing:
        print("ERROR: demo files are missing:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return 2

    rule = "=" * 70
    thin = "-" * 70
    print(rule)
    print("  THE OUTREACH FACTORY DEMO")
    print("  no setup, no API, no Gmail, no model download")
    print(rule)
    print(
        "\n  Scenario: you are Devon, building Carillon (a small open-source\n"
        "  library for typed background jobs). You want to cold-email Riley\n"
        "  Okafor, who just published a postmortem about a job queue losing\n"
        "  tasks. Below is what the factory does, stage by stage. Everything\n"
        "  here is fake; nothing is sent.\n"
    )

    fm, body = _split_frontmatter(prospect_path.read_text(encoding="utf-8"))
    print(thin)
    print("  [1 of 4]  PROSPECT  (a real run fills this via /research-prospect)")
    print(thin)
    print(f"  name:    {fm.get('name')}")
    print(f"  company: {fm.get('company')}")
    print(f"  email:   {fm.get('email')}")
    print(f"  send as: register={fm.get('register')}  channel={fm.get('channel')}")
    print(f"  source:  examples/demo/vault/{prospect_path.name}\n")
    print(_indent(body.strip()))
    print()

    print(thin)
    print("  [2 of 4]  SCAFFOLD  (the LLM proposes options, never prose)")
    print(thin)
    print(_indent(scaffold_path.read_text(encoding="utf-8").strip()))
    print()

    corpus = _parse_demo_corpus(corpus_path.read_text(encoding="utf-8"))
    cold = [e for e in corpus if e.get("register") == "cold-pitch"]
    print(thin)
    print("  [3 of 4]  VOICE EXEMPLARS  (your own past emails ground the rewrite)")
    print(thin)
    print(
        f"  This is a cold-pitch, so the {len(cold)} cold-pitch exemplars below\n"
        f"  (of {len(corpus)} total in examples/demo/voice-corpus.md) are the\n"
        f"  voice the rewrite matches. No similarity model runs in the demo.\n"
    )
    for ex in cold:
        subject = ex.get("subject") or "(no subject)"
        print(f"    --- {ex.get('id')}  {ex.get('date')}  subject: {subject}")
        print(_indent((ex.get("body") or "").strip(), 6))
        print()

    print(thin)
    print("  [4 of 4]  FINAL DRAFT  (rewritten inline in the agent's voice)")
    print(thin)
    print(_indent(draft_path.read_text(encoding="utf-8").strip()))
    print()

    print(rule)
    print("  The final draft above was generated by the agent and committed for")
    print("  this demo. To generate a FRESH one live (subscription-billed, no")
    print("  API), run this inside Claude Code:")
    print("\n      /draft-outreach --demo\n")
    print("  When you are ready to run your own outreach for real:")
    print("\n      ./bin/outreach-factory config   # copy the templates, then edit")
    print("      ./bin/outreach-factory init     # OAuth -> vault -> test send")
    print(rule)
    return 0


def cmd_doctor(_args) -> int:
    """Delegate to the existing preflight checker."""
    import runpy

    doctor = REPO_ROOT / "scripts" / "doctor.py"
    if not doctor.exists():
        print(f"ERROR: {doctor} not found.", file=sys.stderr)
        return 2
    sys.argv = [str(doctor)]
    try:
        runpy.run_path(str(doctor), run_name="__main__")
    except SystemExit as exc:  # doctor.py exits with its own code
        return int(exc.code or 0)
    return 0


def cmd_init(args) -> int:
    import yaml

    from orchestrator.multi_tenant import (
        INIT_WIZARD_STEPS, InitWizardError, run_init_wizard,
    )

    cfg_path = _config_path()
    if not cfg_path.exists():
        print(
            f"No config at {cfg_path}.\n"
            f"Run `outreach-factory config` first (copies the template), then edit it.",
            file=sys.stderr,
        )
        return 2

    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    print(f"Onboarding from {cfg_path}\n")

    if args.dry_run:
        # Validate the full wiring without real OAuth, real send, or touching
        # the real ledger/vault: redirect dirs to a throwaway home.
        import tempfile

        home = Path(tempfile.mkdtemp(prefix="of-init-dryrun-"))
        cfg.setdefault("vault", {})["path"] = str(home / "vault")
        tenant_cfg = _tenant_config_from_user_config(cfg, home=home)
        gmail_authenticate_fn = lambda: _DryRunGmail()  # noqa: E731
        migration_apply_fn = lambda: None  # noqa: E731
        print("(dry-run: fake Gmail seam, throwaway dirs, no real send)\n")
    else:
        home = DEFAULT_HOME
        tenant_cfg = _tenant_config_from_user_config(cfg, home=home)
        if str(SEND_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SEND_SCRIPTS))
        from gmail_client import GmailClient  # real OAuth round-trip

        gmail_authenticate_fn = GmailClient.authenticate
        migration_apply_fn = None  # use the wizard's real per-tenant migration runner

    try:
        result = run_init_wizard(
            tenant_cfg,
            gmail_authenticate_fn=gmail_authenticate_fn,
            migration_apply_fn=migration_apply_fn,
        )
    except InitWizardError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        print(f"  Fix the '{exc.step}' step above and re-run `outreach-factory init`.",
              file=sys.stderr)
        return 1

    if result["status"] == "already_completed":
        print("✓ Already onboarded (init wizard previously completed). Nothing to do.")
        return 0

    for step in INIT_WIZARD_STEPS:
        mark = "✓" if step in result["wizard_steps"] else "·"
        print(f"  {mark} {step}")
    print(
        f"\n✓ Onboarding complete for tenant '{result['tenant_id']}'. "
        f"Test send to {result['test_send_to']} round-tripped."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="outreach-factory",
        description="Outreach Factory onboarding + operations CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Zero-to-test-send onboarding (runs the init wizard).")
    p_init.add_argument(
        "--dry-run", action="store_true",
        help="Validate the wiring with a fake Gmail seam and throwaway dirs; no real OAuth/send.",
    )
    p_init.set_defaults(func=cmd_init)

    sub.add_parser(
        "demo",
        help="Zero-setup walkthrough on a fake prospect (no Gmail/API/model download).",
    ).set_defaults(func=cmd_demo)

    sub.add_parser("doctor", help="Run preflight checks (scripts/doctor.py).").set_defaults(
        func=cmd_doctor
    )
    sub.add_parser("config", help="Copy config + .env templates into ~/.outreach-factory/.").set_defaults(
        func=cmd_config
    )

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
