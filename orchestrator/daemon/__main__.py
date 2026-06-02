"""Container entrypoint for the per-tenant daemon (Pillar I Week 3, ADR-0072).

This is the ``CMD`` the ``infra/Dockerfile`` image runs and the
``infra/docker-compose.yml`` service invokes: ``python -m orchestrator.daemon``.
It reads the per-tenant config from the environment the container sets (the
per-tenant compose service injects ``OUTREACH_FACTORY_TENANT_ID`` +
``OUTREACH_FACTORY_LEDGER_DIR`` + ``OUTREACH_FACTORY_VAULT_DIR`` +
``OUTREACH_FACTORY_POLICY_DIR`` per :func:`multi_tenant.build_per_tenant_compose_config`),
builds a :class:`DaemonConfig`, initializes the daemon via :func:`init_daemon`
(production defaults — real migrations + OTel + Prometheus), and runs the async
main loop until shutdown.

Refuse-loud (``SystemExit`` with a non-zero code) if a required directory env
var is missing — the OSS bring-up trajectory's "fail with an operator-readable
message" convention per R042. The interactive first-run OAuth + first-send is
the Pillar I Week 4 init wizard (ADR-0073); this entrypoint is the headless
container loop that runs once a tenant is provisioned.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from orchestrator.daemon import DaemonConfig, init_daemon


def _require_dir_env(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(
            f"{name} is required — the per-tenant daemon container must be "
            f"started with {name} pointing at the tenant's bind-mounted "
            f"directory (see infra/docker-compose.yml + "
            f"multi_tenant.build_per_tenant_compose_config).\n"
        )
        raise SystemExit(2)
    return Path(value)


def build_config_from_env() -> DaemonConfig:
    """Assemble the :class:`DaemonConfig` from the container environment.

    Separated from :func:`main` so it is unit-testable without starting the
    real OTel / Prometheus servers that :func:`init_daemon` boots."""

    ledger_dir = _require_dir_env("OUTREACH_FACTORY_LEDGER_DIR")
    vault_dir = _require_dir_env("OUTREACH_FACTORY_VAULT_DIR")
    kwargs: dict = {"ledger_dir": ledger_dir, "vault_dir": vault_dir}

    policy_dir = os.environ.get("OUTREACH_FACTORY_POLICY_DIR")
    if policy_dir:
        kwargs["policy_dir"] = Path(policy_dir)
    tenant_id = os.environ.get("OUTREACH_FACTORY_TENANT_ID")
    if tenant_id:
        kwargs["tenant_id"] = tenant_id

    return DaemonConfig(**kwargs)


def main() -> int:
    config = build_config_from_env()
    runner = init_daemon(config)
    return asyncio.run(runner.run())


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    raise SystemExit(main())
