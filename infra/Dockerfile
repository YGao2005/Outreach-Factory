# Per-tenant daemon image (Pillar I Week 3, ADR-0070 D372 + ADR-0072).
#
# One container == one daemon process (ADR-0060 D335 invariant 1). The image is
# built once and shared across tenants; per-tenant isolation is at the bind-
# mount + env grain (see infra/docker-compose.yml for the single-tenant default
# and multi_tenant.build_per_tenant_compose_config for the multi-tenant fan-out).
#
# Pinned base + pinned deps for byte-identical-deterministic OSS bring-up per
# ADR-0070 D375 invariant (d): `git clone && docker compose up` reproduces the
# same working system on a fresh VM.
FROM python:3.13-slim

WORKDIR /app

# Dependencies first so the layer caches independently of source edits.
COPY orchestrator/requirements.txt /app/orchestrator/requirements.txt
RUN pip install --no-cache-dir -r /app/orchestrator/requirements.txt

# Orchestrator source.
COPY orchestrator/ /app/orchestrator/

# Both the repo root (for `from orchestrator import ...`) AND the orchestrator/
# dir (for the bare `import ledger` / `import observability` convention used
# throughout the package) on the path — mirrors tests/conftest.py's two
# sys.path insertions so production import resolution matches the test harness.
ENV PYTHONPATH=/app:/app/orchestrator
ENV PYTHONUNBUFFERED=1

# Per-tenant data is bind-mounted at these canonical in-container paths by the
# compose service (build_per_tenant_compose_config uses the same constants).
ENV OUTREACH_FACTORY_LEDGER_DIR=/data/ledger
ENV OUTREACH_FACTORY_VAULT_DIR=/data/vault
ENV OUTREACH_FACTORY_POLICY_DIR=/data/policy

# Headless per-tenant daemon loop. The interactive first-run OAuth + first-send
# is the Pillar I Week 4 init wizard (ADR-0073); this is the steady-state loop.
CMD ["python", "-m", "orchestrator.daemon"]
