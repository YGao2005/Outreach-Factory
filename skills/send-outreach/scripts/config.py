"""Paths and constants for send-outreach skill.

Loads from ~/.outreach-factory/config.yml at import time. The legacy aiyara-coupled
constants (VAULT_ROOT, CREDENTIALS_DIR, etc.) are still exposed for back-compat with
the rest of the scripts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml


# Load ~/.outreach-factory/.env so secret env vars (e.g. the suppression-check
# secret) are visible to downstream os.environ reads. env_loader lives in
# orchestrator/; add it to sys.path defensively (send_queued.py already
# bootstraps orchestrator/, but standalone callers of this module may not).
_ORCH_DIR = Path(__file__).resolve().parents[3] / "orchestrator"
if _ORCH_DIR.exists() and str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))
try:
    import env_loader as _env_loader

    _env_loader.load_env()
except Exception:  # noqa: BLE001 — .env is optional; never block config load
    _env_loader = None


# Honor an explicit override so a single machine can carry multiple tenant
# configs (one config file per tenant) and select one per invocation:
#   OUTREACH_FACTORY_CONFIG=~/.outreach-factory/config.other.yml python ...
# Unset falls back to the canonical default at ~/.outreach-factory/config.yml.
CONFIG_PATH = Path(
    os.path.expanduser(os.environ.get("OUTREACH_FACTORY_CONFIG", "").strip())
    or (Path.home() / ".outreach-factory" / "config.yml")
)
DEFAULT_CREDENTIALS_DIR = Path.home() / ".outreach-factory" / "credentials"


def _expand(p: str) -> Path:
    """Expand ~ and $VAR in a path."""
    return Path(os.path.expandvars(os.path.expanduser(p)))


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        print(
            f"\nERROR: {CONFIG_PATH} not found.\n"
            "\nCreate it by running:\n"
            "  mkdir -p ~/.outreach-factory\n"
            "  cp <outreach-factory-repo>/config-template/config.example.yml ~/.outreach-factory/config.yml\n"
            "  # then edit ~/.outreach-factory/config.yml with your values\n",
            file=sys.stderr,
        )
        sys.exit(2)
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


_cfg = _load_config()


def _section(name: str) -> dict[str, Any]:
    s = _cfg.get(name) or {}
    if not isinstance(s, dict):
        return {}
    return s


_vault = _section("vault")
_email = _section("email_send")
_founder = _section("founder")


# --- Vault paths ---

VAULT_ROOT = _expand(_vault.get("path") or "")
PEOPLE_DIR = VAULT_ROOT / (_vault.get("people_dir") or "10 People")
CONVERSATIONS_DIR = VAULT_ROOT / (_vault.get("conversations_dir") or "40 Conversations")


# --- Gmail OAuth ---

CREDENTIALS_DIR = DEFAULT_CREDENTIALS_DIR
GMAIL_CREDENTIALS = _expand(_email.get("gmail_credentials_path") or "") if _email.get("gmail_credentials_path") else CREDENTIALS_DIR / "gmail_credentials.json"
GMAIL_TOKEN = _expand(_email.get("gmail_token_path") or "") if _email.get("gmail_token_path") else CREDENTIALS_DIR / "gmail_token.json"

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


# --- LinkedIn manifest + limits ---

LINKEDIN_MANIFEST_PATH = (
    _expand(_email.get("linkedin_manifest_path") or "")
    if _email.get("linkedin_manifest_path")
    else Path.home() / ".outreach-factory" / "linkedin_manifest.json"
)
LINKEDIN_WEEKLY_INVITE_LIMIT = int(_email.get("linkedin_weekly_invite_limit") or 100)


# --- Sender identity ---

SENDER_NAME = _email.get("sender_name") or _founder.get("name") or ""


# --- Security / compliance (Pillar J J7) ---
# Operator-supplied CAN-SPAM physical address + one-click unsubscribe config.
# Surfaced here so send_queued.main() can build a SecurityConfig and stamp the
# footer + List-Unsubscribe headers onto every outbound email. Missing section
# -> all None -> main() skips the footer (back-compat with a minimal config that
# has no `security:` block; SecurityConfig itself refuses-loud on an empty
# address, so a half-configured section fails fast rather than sending a
# non-compliant email).
_security = _section("security")
SECURITY_PHYSICAL_MAILING_ADDRESS = _security.get("physical_mailing_address") or None
SECURITY_UNSUBSCRIBE_BASE_URL = _security.get("unsubscribe_base_url") or None
SECURITY_UNSUBSCRIBE_MAILTO = _security.get("unsubscribe_mailto") or None

# Pre-send suppression check. When the URL is set, send_queued.main() queries
# `<url>/<token>` (token = the same opaque sha256(person_id) marker the J7
# unsubscribe link uses) and SKIPS any recipient who has unsubscribed. The API
# secret is resolved generically (no tenant-specific naming in core): the env
# var named in `suppression_check_secret_env` wins, else the file at
# `suppression_check_secret_path` (both resolved via env_loader.get_secret).
# Empty/absent URL -> no check.
SECURITY_SUPPRESSION_CHECK_URL = _security.get("suppression_check_url") or None
SECURITY_SUPPRESSION_CHECK_SECRET_ENV = _security.get("suppression_check_secret_env") or None
SECURITY_SUPPRESSION_CHECK_SECRET_PATH = _security.get("suppression_check_secret_path") or None


# --- Touch note discovery ---
# Generalized from the cold-touch-specific glob. Any .md under CONVERSATIONS_DIR
# with `type: touch` frontmatter is a candidate. The frontmatter filter does the
# actual selection (the glob just narrows the file walk).
TOUCH_NOTE_GLOB = "**/*.md"
