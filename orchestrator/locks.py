"""Marker-file locking for the outreach-factory dispatcher.

Locks are YAML files at `<vault>/.outreach-factory/locks/<sanitized>.lock`.
Each lock records the holder's agent_id, the prospect, the stage being
executed, and an ISO-8601 acquired_at timestamp. Locks older than
--max-age-min (default 30) are considered stale and may be broken.

CLI:

    python locks.py acquire --prospect <name> --stage <stage> [--agent-id <id>]
    python locks.py release --prospect <name>
    python locks.py list [--json]
    python locks.py clean-stale [--max-age-min 30] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml


STALE_AFTER_MIN_DEFAULT = 30


def _load_config() -> dict:
    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _vault_path(cfg: dict) -> Path:
    return Path(os.path.expanduser((cfg.get("vault") or {}).get("path") or "")).resolve()


def _locks_dir(vault: Path) -> Path:
    d = vault / ".outreach-factory" / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("_")
    return s or "unnamed"


def _lock_path(vault: Path, prospect: str) -> Path:
    return _locks_dir(vault) / f"{_sanitize(prospect)}.lock"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_minutes(iso_ts: str) -> float:
    try:
        ts = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 1e9  # unparseable = treat as stale
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0


def acquire(prospect: str, agent_id: str, stage: str, max_age_min: int = STALE_AFTER_MIN_DEFAULT) -> tuple[bool, str]:
    """Acquire a lock. Breaks stale locks (older than max_age_min). Returns (ok, msg)."""
    cfg = _load_config()
    vault = _vault_path(cfg)
    lp = _lock_path(vault, prospect)
    if lp.exists():
        try:
            existing = yaml.safe_load(lp.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            existing = {}
        existing_ts = existing.get("acquired_at") or ""
        age = _age_minutes(existing_ts)
        if age < max_age_min:
            return False, f"locked by {existing.get('agent_id', '?')} since {existing_ts} ({age:.1f} min ago)"
    payload = {
        "agent_id": agent_id,
        "prospect": prospect,
        "stage": stage,
        "acquired_at": _now_iso(),
    }
    lp.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return True, str(lp)


def release(prospect: str) -> tuple[bool, str]:
    cfg = _load_config()
    vault = _vault_path(cfg)
    lp = _lock_path(vault, prospect)
    if not lp.exists():
        return True, "no lock present (no-op)"
    lp.unlink()
    return True, f"released {lp}"


def list_locks() -> list[dict]:
    cfg = _load_config()
    vault = _vault_path(cfg)
    ld = _locks_dir(vault)
    out = []
    for lp in sorted(ld.glob("*.lock")):
        try:
            data = yaml.safe_load(lp.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {"raw": lp.read_text(encoding="utf-8")}
        data["_path"] = str(lp)
        data["_age_min"] = round(_age_minutes(data.get("acquired_at") or ""), 1)
        out.append(data)
    return out


def clean_stale(max_age_min: int = STALE_AFTER_MIN_DEFAULT) -> list[str]:
    cleaned = []
    for entry in list_locks():
        if entry.get("_age_min", 1e9) >= max_age_min:
            Path(entry["_path"]).unlink(missing_ok=True)
            cleaned.append(entry["_path"])
    return cleaned


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("acquire")
    a.add_argument("--prospect", required=True)
    a.add_argument("--agent-id", default=None)
    a.add_argument("--stage", required=True)
    a.add_argument("--max-age-min", type=int, default=STALE_AFTER_MIN_DEFAULT)

    r = sub.add_parser("release")
    r.add_argument("--prospect", required=True)

    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")

    cs = sub.add_parser("clean-stale")
    cs.add_argument("--max-age-min", type=int, default=STALE_AFTER_MIN_DEFAULT)
    cs.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "acquire":
        agent_id = args.agent_id or f"agent-{uuid.uuid4().hex[:8]}"
        ok, msg = acquire(args.prospect, agent_id, args.stage, args.max_age_min)
        print(json.dumps({"ok": ok, "agent_id": agent_id, "message": msg}))
        sys.exit(0 if ok else 1)

    elif args.cmd == "release":
        ok, msg = release(args.prospect)
        print(json.dumps({"ok": ok, "message": msg}))
        sys.exit(0 if ok else 1)

    elif args.cmd == "list":
        locks = list_locks()
        if args.json:
            print(json.dumps(locks, indent=2))
        else:
            if not locks:
                print("(no active locks)")
                return
            for lk in locks:
                stale = " ⚠STALE" if lk["_age_min"] >= STALE_AFTER_MIN_DEFAULT else ""
                print(f"  {lk.get('prospect', '?'):<30s}  stage={lk.get('stage', '?'):<11s}  agent={lk.get('agent_id', '?')}  age={lk['_age_min']:.1f}min{stale}")

    elif args.cmd == "clean-stale":
        cleaned = clean_stale(args.max_age_min)
        result = {"cleaned": cleaned, "count": len(cleaned)}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Released {len(cleaned)} stale lock(s).")
            for path in cleaned:
                print(f"  - {path}")


if __name__ == "__main__":
    main()
