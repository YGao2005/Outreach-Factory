"""Unified .env loading + secret resolution for the outreach factory.

One place for credentials. API keys and admin secrets live in the operator's
``~/.outreach-factory/.env`` (override the path with ``$OUTREACH_FACTORY_ENV``),
NOT in the YAML config and NOT in git. Values already present in the process
environment always win over the ``.env`` file, so a shell export or a CI secret
overrides the file.

OAuth artifacts (Gmail ``credentials.json`` / ``token.json``) are multi-field
files, not single-string secrets, so they stay under
``~/.outreach-factory/credentials/`` and are handled by the Gmail client
directly. This module is only for single-string secrets.

NOTE: this file is intentionally NOT named ``secrets.py`` — the send-outreach
scripts put ``orchestrator/`` on ``sys.path`` and import by bare name, which
would shadow the Python standard-library ``secrets`` module.
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_LOADED = False


def _default_env_path() -> Path:
    override = os.environ.get("OUTREACH_FACTORY_ENV", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".outreach-factory" / ".env"


def load_env(path: str | Path | None = None, *, override: bool = False) -> None:
    """Load the operator's ``.env`` into ``os.environ`` once (idempotent).

    Uses ``python-dotenv`` when installed; falls back to a minimal parser so the
    factory still runs without the dependency. Existing environment variables
    are preserved unless ``override=True``.
    """
    global _ENV_LOADED
    if _ENV_LOADED and path is None:
        return

    env_path = Path(os.path.expanduser(str(path))) if path is not None else _default_env_path()
    if env_path.exists():
        try:
            from dotenv import load_dotenv  # type: ignore

            load_dotenv(env_path, override=override)
        except ImportError:
            _load_env_fallback(env_path, override=override)

    if path is None:
        _ENV_LOADED = True


def _load_env_fallback(env_path: Path, *, override: bool) -> None:
    """Minimal KEY=VALUE parser (used only if python-dotenv is absent)."""
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = val


def get_secret(
    env_name: str | None = None,
    *,
    file_path: str | Path | None = None,
) -> str | None:
    """Resolve a single-string secret.

    Order: process environment (after :func:`load_env`) first, then a
    chmod-600 secret file. Returns ``None`` if neither yields a value; callers
    that REQUIRE the secret should refuse-loud on ``None`` with an
    operator-readable message.
    """
    load_env()
    if env_name:
        val = os.environ.get(env_name, "").strip()
        if val:
            return val
    if file_path:
        p = Path(os.path.expanduser(str(file_path)))
        if p.exists():
            content = p.read_text().strip()
            if content:
                return content
    return None
