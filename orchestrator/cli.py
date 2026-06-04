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
  status     What went out, who replied, what is queued, and whether it is
             safe to send more today. A lean read over the ledger.
  migrate    Scaffold the vault + state dirs and apply pending migrations.
             The OAuth-free path to a doctor-green install.
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


def _seed_config_defaults(text: str) -> str:
    """Fill the two paths the CLI can know for the user, so a freshly copied
    config works without hand-editing: factory.home (this repo's root, which
    the CLI already knows as REPO_ROOT) and a default vault.path under the
    factory home. Targeted line replacements so the template's inline comments
    survive (a YAML round-trip would strip them). Best-effort: a placeholder
    that is not found (template changed) is left untouched."""
    default_vault = DEFAULT_HOME / "vault"
    replacements = {
        '  home: "~/code/outreach-factory"': f'  home: "{REPO_ROOT}"',
        '  path: "/path/to/your/vault"': f'  path: "{default_vault}"',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def cmd_config(_args) -> int:
    """Copy the config + .env templates into ~/.outreach-factory/ (no overwrite).

    The config copy is seeded with the two paths the CLI can know for you:
    factory.home (this repo) and a default vault.path. That removes two
    hand-edits a new user would otherwise have to get exactly right before
    `migrate`/`init`/the skills work (the skills read factory.home, so a wrong
    value there fails past doctor)."""
    DEFAULT_HOME.mkdir(parents=True, exist_ok=True)
    targets = [
        (CONFIG_TEMPLATE, DEFAULT_HOME / "config.yml"),
        (ENV_TEMPLATE, DEFAULT_HOME / ".env"),
    ]
    for src, dst in targets:
        if dst.exists():
            print(f"  exists, leaving as-is: {dst}")
        else:
            text = src.read_text()
            if src == CONFIG_TEMPLATE:
                text = _seed_config_defaults(text)
            dst.write_text(text)
            print(f"  created: {dst}  (from {src.name})")
    print(f"\n  Auto-filled factory.home ({REPO_ROOT}) and a default vault.path")
    print(f"  ({DEFAULT_HOME / 'vault'}); edit either if you want it elsewhere.")
    print("\nNext: fill in company + founder identity (and founder.email), then")
    print("run `outreach-factory migrate`, then `outreach-factory init`.")
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
    """Parse examples/demo/reference-touches.md into exemplar dicts (stdlib only).

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
    corpus_path = DEMO_DIR / "reference-touches.md"
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
    print("  [3 of 4]  REFERENCE TOUCHES  (human-written examples in this register)")
    print(thin)
    print(
        f"  This is a cold-pitch, so the {len(cold)} cold-pitch examples below\n"
        f"  (of {len(corpus)} total in examples/demo/reference-touches.md) are the\n"
        f"  reference the humanizer reads for tone. No model, no embeddings, no\n"
        f"  retrieval: the agent just reads them.\n"
    )
    for ex in cold:
        subject = ex.get("subject") or "(no subject)"
        print(f"    --- {ex.get('id')}  {ex.get('date')}  subject: {subject}")
        print(_indent((ex.get("body") or "").strip(), 6))
        print()

    print(thin)
    print("  [4 of 4]  FINAL DRAFT  (rewritten inline against the anti-tell checklist)")
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
    # flush so this banner lands before any stderr the auth step may emit
    # (a missing-credentials runbook prints to stderr from inside the wizard).
    print(f"Onboarding from {cfg_path}\n", flush=True)

    if args.dry_run:
        # Validate the full wiring without real OAuth, real send, or touching
        # the real ledger/vault: redirect dirs to a throwaway home.
        import tempfile

        home = Path(tempfile.mkdtemp(prefix="of-init-dryrun-"))
        cfg.setdefault("vault", {})["path"] = str(home / "vault")
        tenant_cfg = _tenant_config_from_user_config(cfg, home=home)
        # Echo the operator's REAL configured sender so the preview reflects
        # their config, not a placeholder. A real run sends to-self at
        # founder.email, so the dry-run names the same recipient.
        dryrun_sender = (cfg.get("founder") or {}).get("email") or "you@example.com"
        gmail_authenticate_fn = lambda: _DryRunGmail(sender_email=dryrun_sender)  # noqa: E731
        migration_apply_fn = lambda: None  # noqa: E731
        print("(dry-run: fake Gmail seam, throwaway dirs, no real send)\n")
    else:
        home = DEFAULT_HOME
        tenant_cfg = _tenant_config_from_user_config(cfg, home=home)
        # Scaffold the vault subdirs the skills + doctor expect. Idempotent and
        # OAuth-free, so even if the Gmail step below stalls, the vault is sane.
        _scaffold_vault_subdirs(cfg)
        if str(SEND_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SEND_SCRIPTS))
        try:
            from gmail_client import GmailClient  # real OAuth round-trip
        except ImportError as exc:
            print(
                f"\n✗ The Gmail send dependencies are not installed ({exc}).\n"
                f"  Install them, then re-run `outreach-factory init`:\n\n"
                f"      pip install -r skills/send-outreach/requirements.txt\n",
                file=sys.stderr,
            )
            return 1

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


def _scaffold_vault_subdirs(cfg: dict) -> list[Path]:
    """Create the vault root + the people/companies/lead_lists subdirs the
    skills and `doctor` expect, reading the (possibly renamed) subdir names
    from config. Idempotent. Needs no Gmail or OAuth, so it brings a fresh
    vault to a doctor-green shape even on a machine that has not finished
    Google sign-in. Returns the subdirs ensured (empty when vault.path unset).

    No migration creates these: the vault baseline migrations READ '10 People'
    etc., they do not make them, and the wizard only mkdirs the vault root. So
    this is the one place the CRM skeleton gets laid down.
    """
    vault = cfg.get("vault") or {}
    path = vault.get("path")
    if not path:
        return []
    root = Path(os.path.expanduser(str(path)))
    names = [
        vault.get("people_dir") or "10 People",
        vault.get("companies_dir") or "20 Companies",
        vault.get("lead_lists_dir") or "60 Lead Lists",
    ]
    root.mkdir(parents=True, exist_ok=True)
    ensured: list[Path] = []
    for name in names:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        ensured.append(d)
    return ensured


def cmd_migrate(_args) -> int:
    """Scaffold state dirs + apply pending Pillar B migrations. The OAuth-free
    path to a sane, doctor-green install.

    Creates the vault (+ its subdirs) and the ledger/policy state dirs, then
    runs the migration runner against THIS install's directories. A user who is
    blocked on Google OAuth can still reach a working vault with this. It
    replaces the hand-edited REPL one-liner the docs used to print, which broke
    on a fresh clone two ways: a bare `import ledger` that only resolves with
    orchestrator/ on sys.path (this command runs through cli.py, so it does),
    and a missing policy dir the runner refused to write into (created here).
    """
    import yaml

    cfg_path = _config_path()
    if not cfg_path.exists():
        print(
            f"No config at {cfg_path}.\n"
            f"Run `outreach-factory config` first (copies the template), then edit it.",
            file=sys.stderr,
        )
        return 2
    cfg = yaml.safe_load(cfg_path.read_text()) or {}

    # Resolve dirs through the SAME bridge `init` uses, so `migrate` and `init`
    # always operate on identical directories (no policy-vs-policies split).
    tenant_cfg = _tenant_config_from_user_config(cfg, home=DEFAULT_HOME)
    for d in (tenant_cfg.vault_dir, tenant_cfg.ledger_dir, tenant_cfg.policy_dir):
        d.mkdir(parents=True, exist_ok=True)
    _scaffold_vault_subdirs(cfg)
    print(f"Vault scaffolded at {tenant_cfg.vault_dir}")

    from orchestrator.migrations.runner import MigrationRunner

    runner = MigrationRunner(
        ledger_dir=tenant_cfg.ledger_dir,
        vault_dir=tenant_cfg.vault_dir,
        policy_dir=tenant_cfg.policy_dir,
    )
    pending = runner.pending()
    if not pending:
        print("No pending migrations. Already up to date.")
        print("Run `outreach-factory doctor` to confirm.")
        return 0

    print(f"Applying {len(pending)} pending migration(s)... "
          "(ignore any Obsidian Sync cautions below if you do not use Obsidian)")
    results = runner.apply()
    applied = [r for r in results if getattr(r, "applied", False)]
    for r in applied:
        print(f"  applied {r.category.value}/{r.migration_id}")
    print(
        f"\n✓ {len(applied)} migration(s) applied. "
        f"Run `outreach-factory doctor` to confirm a green vault + no pending."
    )
    return 0


def _status_ledger_dir() -> Path:
    """Where the ledger lives. Honors OUTREACH_FACTORY_LEDGER_DIR (the same
    override the send path reads) so `status` reflects the ledger the sends
    actually wrote to."""
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR", "").strip()
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return DEFAULT_HOME / "ledger"


def _load_status_config() -> dict | None:
    """Parse the user config once for the status command. Returns the parsed
    dict, or None when no config exists or it does not parse (status then runs
    in its degraded, config-free mode)."""
    cfg_path = _config_path()
    if not cfg_path.exists():
        return None
    try:
        import yaml

        return yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return None


def _status_daily_cap(cfg: dict | None) -> int | None:
    """The optional daily email send cap (email_send.daily_send_cap in config).

    Returns None when no config exists or the key is unset/invalid, in which
    case status shows the raw send count without a headroom figure.
    """
    if not cfg:
        return None
    cap = (cfg.get("email_send") or {}).get("daily_send_cap")
    try:
        return int(cap) if cap is not None else None
    except (TypeError, ValueError):
        return None


def _status_warming_decision(cfg: dict | None, events, now):
    """Compute today's warming-ramp decision from config + the events already
    loaded in cmd_status. Returns ``(decision, total_weeks)`` or None when
    warming is unconfigured / disabled / un-cappable (status then skips the
    line). Degrades gracefully: any parse error returns None rather than
    raising, so a malformed warming block never breaks `status`.

    Reads warming.start_date (the ramp anchor) + email_send.daily_send_cap
    (the ceiling clamp). An explicit start_date is honored; otherwise the
    warming module infers it from the earliest send_confirmed in ``events``.
    """
    if not cfg:
        return None
    warming_cfg = cfg.get("warming") or {}
    if not isinstance(warming_cfg, dict):
        return None
    # Opt-in: only surface the line when warming is explicitly enabled.
    if not warming_cfg.get("enabled"):
        return None
    cap = _status_daily_cap(cfg)
    if cap is None:
        return None

    from datetime import datetime, timezone

    from orchestrator import warming as _warming

    start_raw = warming_cfg.get("start_date")
    start_date = None
    if start_raw:
        try:
            start_date = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            start_date = None

    # Optional schedule override: weeks_to_full (int) or explicit fractions.
    schedule = None
    if warming_cfg.get("weeks_to_full") is not None:
        try:
            schedule = int(warming_cfg["weeks_to_full"])
        except (TypeError, ValueError):
            schedule = None
    elif isinstance(warming_cfg.get("fractions"), (list, tuple)):
        schedule = list(warming_cfg["fractions"])

    try:
        decision = _warming.compute_ramp(
            now=now, start_date=start_date, daily_send_cap=cap,
            events=events, schedule=schedule,
        )
        total = _warming.total_weeks(schedule, daily_send_cap=cap)
    except Exception:
        return None
    return decision, total


# Gate-refusal event types the send path emits (see orchestrator/ledger.py
# "Event types" -> Health). Surfacing these is the point: the guardrails are
# invisible until you can see them working.
_STATUS_BLOCK_TYPES = ("dedup_blocked", "cooldown_blocked", "policy_blocked")


def _status_followup_lines(cfg, events, now) -> list[str] | None:
    """Build the follow-up status block: who is due now (per step) + the
    per-touch send counts. Returns a list of printable lines, or None when the
    follow-up config is absent / unparseable (status then skips the section).

    Reuses the events already loaded by cmd_status (no second ledger walk). The
    due list comes from the SAME deterministic engine the dispatch skill +
    send path consult, so status, dispatch, and the gate never disagree.
    """
    if not cfg:
        return None
    try:
        from orchestrator import followup as _followup

        cadence = _followup.cadence_config_from_dict(cfg.get("followup"))
    except Exception:
        return None

    # Per-touch send counts come from the followup_step tag the send path stamps
    # on every send_confirmed (0 = cold, 1 = first follow-up, ...).
    per_touch: dict[int, int] = {}
    for e in events:
        if e.get("type") == "send_confirmed" and (e.get("channel") or "email") == "email":
            step = e.get("followup_step")
            step = step if isinstance(step, int) else 0
            per_touch[step] = per_touch.get(step, 0) + 1

    if not cadence.enabled:
        # A quiet nudge only when there is a sequence worth following up.
        if sum(per_touch.values()) > 0:
            return ["    follow-ups off (set followup.enabled: true in config to "
                    "sequence non-repliers)"]
        return None

    due = _followup.compute_due_followups(events, cadence, now=now)
    by_step: dict[int, int] = {}
    for a in due:
        by_step[a.next_step] = by_step.get(a.next_step, 0) + 1

    steps_desc = ", ".join(
        f"+{s.after_business_days}" for s in cadence.steps
    ) or "none"
    lines = [
        f"\n  FOLLOW-UPS  (max {cadence.max_touches} touches; "
        f"steps at {steps_desc} business days)"
    ]
    if due:
        detail = ", ".join(
            f"follow-up {step}: {by_step[step]}" for step in sorted(by_step)
        )
        lines.append(f"    due now         {len(due)}   ({detail})")
    else:
        lines.append("    due now         0")
    if per_touch:
        touch_detail = ", ".join(
            f"touch {step + 1}: {per_touch[step]}" for step in sorted(per_touch)
        )
        lines.append(f"    sent by touch   {touch_detail}")
    return lines


def cmd_status(_args) -> int:
    """Print what the operator actually wants to know: what went out, who
    replied, what is queued, and whether it is safe to send more today.

    A lean read over the append-only ledger (the source of truth). No daemon,
    no Grafana, no OpenTelemetry. Degrades gracefully on a fresh install (empty
    ledger) and when reply/bounce events are absent (an operator who does not
    run reconcile simply sees zero replies, not an error).
    """
    from datetime import datetime, timedelta, timezone

    from orchestrator import ledger as _ledger

    ledger_dir = _status_ledger_dir()
    led = _ledger.Ledger(ledger_dir)
    events = led.all_events()

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    week_ago_iso = (now - timedelta(days=7)).isoformat()

    sent_today: dict[str, int] = {}
    sent_week: dict[str, int] = {}
    replies_today = replies_week = 0
    bounces_today = bounces_week = 0
    blocks_today: dict[str, int] = {}
    blocks_week = 0

    for e in events:
        ts = e.ts or ""
        t = e.get("type")
        in_today = ts[:10] == today
        in_week = ts >= week_ago_iso
        if t == "send_confirmed":
            ch = e.get("channel") or "email"
            if in_today:
                sent_today[ch] = sent_today.get(ch, 0) + 1
            if in_week:
                sent_week[ch] = sent_week.get(ch, 0) + 1
        elif t == "reply_received":
            replies_today += 1 if in_today else 0
            replies_week += 1 if in_week else 0
        elif t == "bounce_detected":
            bounces_today += 1 if in_today else 0
            bounces_week += 1 if in_week else 0
        elif t in _STATUS_BLOCK_TYPES:
            if in_today:
                reason = e.get("reason") or t
                blocks_today[reason] = blocks_today.get(reason, 0) + 1
            blocks_week += 1 if in_week else 0

    funnel = _ledger.funnel(led, since=now - timedelta(days=30))
    stages = funnel["persons_reached_stage"]

    rule = "=" * 60
    print(rule)
    print(f"  OUTREACH FACTORY STATUS   {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  ledger: {ledger_dir}")
    print(rule)

    if not events:
        print("\n  No activity recorded yet. Once you send your first touch")
        print("  (/send-outreach or `outreach-factory init`), it shows up here.\n")
        return 0

    cfg = _load_status_config()
    emails_today = sent_today.get("email", 0)
    cap = _status_daily_cap(cfg)
    print(f"\n  TODAY  ({today})")
    if cap is not None:
        remaining = max(0, cap - emails_today)
        flag = "  OVER CAP" if emails_today > cap else ""
        print(f"    emails sent     {emails_today} / {cap}   ({remaining} remaining today){flag}")
    else:
        print(f"    emails sent     {emails_today}   (set email_send.daily_send_cap in config to track headroom)")
    other_today = {c: n for c, n in sent_today.items() if c != "email"}
    if other_today:
        print(f"    other channels  " + ", ".join(f"{c}: {n}" for c, n in sorted(other_today.items())))
    print(f"    replies in      {replies_today}")
    print(f"    bounces         {bounces_today}")
    if blocks_today:
        total_blocked = sum(blocks_today.values())
        detail = ", ".join(f"{r}: {n}" for r, n in sorted(blocks_today.items(), key=lambda kv: -kv[1]))
        print(f"    blocked         {total_blocked}   ({detail})")
    else:
        print(f"    blocked         0")

    # Warming-ramp ceiling for today (reuses the events already loaded). The
    # framework owns the ramp + health gate; it surfaces the ceiling here so
    # the operator can respect it. It does not yet hard-gate the send path.
    warming_result = _status_warming_decision(cfg, events, now)
    if warming_result is not None:
        from orchestrator import warming as _warming

        decision, total = warming_result
        print(f"    {_warming.status_line(decision, total=total)}")
    elif cfg is not None and (cfg.get("warming") or {}).get("enabled") is None:
        # Config present but no warming block: a quiet nudge, not an error.
        print("    warming ceiling ramp not configured (add a 'warming:' section to config)")

    week_sent_total = sum(sent_week.values())
    print(f"\n  LAST 7 DAYS")
    by_ch = ", ".join(f"{c}: {n}" for c, n in sorted(sent_week.items())) or "none"
    print(f"    sent            {week_sent_total}   ({by_ch})")
    print(f"    replies         {replies_week}")
    print(f"    bounces         {bounces_week}")
    print(f"    blocked         {blocks_week}")

    followup_lines = _status_followup_lines(cfg, events, now)
    if followup_lines:
        for line in followup_lines:
            print(line)

    print(f"\n  PIPELINE  (last 30 days, from the ledger)")
    for s in ("queued", "researched", "drafted", "ready", "sent"):
        print(f"    {s:<12}{stages.get(s, 0)}")

    print()
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

    sub.add_parser(
        "status",
        help="What went out, who replied, what is queued, and today's headroom.",
    ).set_defaults(func=cmd_status)

    sub.add_parser(
        "migrate",
        help="Scaffold the vault + state dirs and apply pending migrations (no OAuth needed).",
    ).set_defaults(func=cmd_migrate)

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
