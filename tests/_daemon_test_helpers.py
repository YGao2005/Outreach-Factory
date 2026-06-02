"""Pillar H Week 5 follow-up — shared test helpers for daemon contract
tests + multi-channel coherence tests (per per-week-reviewer P3-2 +
P3-3 closures).

Per Pillar H Week 3 follow-up P3-6 closure precedent — when a test
helper is consumed across multiple test classes / modules, promote
it to a module-level helper instead of duplicating inline class
definitions. The W5 follow-up extends this discipline across modules:
``_StubAppRunner`` was duplicated THREE times (test_daemon.py:2967,
test_multi_channel_coherence.py:9306 + 9475); the W5 follow-up
consolidates here.

Also hosts the past-date constant ``_TEST_PAST_STARTED_AT_TS``
documented per Pillar H Week 5 follow-up P3-3 closure — the run() +
shutdown() body arithmetic ``startup_seconds = now - started_at`` +
``uptime_seconds = now - started_at`` BOTH refuse-loud at the factory
boundary per Pillar H Week 2 follow-up P2-2 + Week 3 follow-up P2-2
closures if the value is < 0. A future test author copying the
DaemonRunner construction pattern without using this constant could
write a test that fails non-determinically; the named constant +
this docstring's explanation are the guard rail.
"""

from __future__ import annotations


#: Pillar H Week 5 follow-up P3-3 closure — past-date constant for
#: tests that construct :class:`orchestrator.daemon.runner.DaemonRunner`.
#: The run() + shutdown() bodies parse this via
#: ``datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")`` per ADR-0061
#: D339's ``_utc_iso_now`` contract; the value MUST be unambiguously
#: in the past relative to wall-clock now so the factory's refuse-loud
#: at ``startup_seconds >= 0.0`` + ``uptime_seconds >= 0.0`` per the
#: Pillar H Week 2 follow-up P2-2 + Week 3 follow-up P2-2 closures
#: succeeds.
_TEST_PAST_STARTED_AT_TS: str = "2020-01-01T00:00:00.000Z"


class _StubAppRunner:
    """Async-cleanup stub for :class:`aiohttp.web.AppRunner` per the
    Pillar H Week 5 test pattern — substituted via
    ``serve_health_endpoint_fn`` test-only seam to avoid real HTTP port
    binding during the per-stage tick loop verification.

    Pillar H Week 5 follow-up P3-2 closure — promoted from inline class
    duplication across tests/test_daemon.py + tests/test_multi_channel_coherence.py
    per the Pillar H Week 3 follow-up P3-6 closure's DRY discipline.
    """

    def __init__(self) -> None:
        self.cleanup_called: bool = False

    async def cleanup(self) -> None:
        self.cleanup_called = True
