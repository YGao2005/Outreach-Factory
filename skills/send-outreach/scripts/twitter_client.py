"""Twitter client adapter — Pillar C Week 5 (ADR-0018).

Wraps a cookie-scrape MCP surface (`mcp__scraplingserver__*` or
equivalent per the operator's environment) for the Twitter DM
dispatcher (`gated_tw_dm_one` in :mod:`send_queued`) AND reconcile
Pass F (`run_pass_f` in :mod:`reconcile`).

Per ADR-0018 D59, this module ships as a thin reference adapter — the
actual cookie-scrape MCP wiring is environment-specific (the operator
must capture browser cookies from a logged-in Twitter session and
configure the MCP). Pillar I OSS bring-up's concern is the
operator-facing cookie-capture story; until then, programmatic
callers inject a fake (e.g. ``FakeTwitter`` in
``tests/test_reconcile_tw_dm.py`` + ``tests/test_send_gate_twitter_dm.py``).

The two surfaces this module exposes:

* :class:`TwitterClient` — the dispatcher-side client with a
  ``send_dm`` method. Live wiring deferred to Pillar I; this stub
  raises if instantiated without an MCP-bound implementation.

* :func:`build_reconcile_adapter` — the reconcile-side adapter that
  the CLI's :func:`reconcile._build_twitter_adapter` shim discovers.
  Returns ``None`` when no live MCP is wired (the CLI then records
  "Pass F requires a Twitter client" per ADR-0018's rollout doc).

Per ADR-0018 D59 the live wiring shape is operator-deliberate; the
adapter's import-time side effect is zero (no cookies read at import
time, no MCP probes). The operator runs `python -m
orchestrator.twitter check-cookies` (a future Pillar I CLI ergonomic)
to validate session state before bulk sends.
"""

from __future__ import annotations

from typing import Optional


class TwitterClient:
    """Pillar I-deferred stub.

    Per ADR-0018 D59, the live cookie-scrape MCP wiring is operator-
    environment-specific. This stub exists so the import path stays
    valid (tests inject fakes via duck typing; CLI's
    ``_build_twitter_adapter`` returns ``None`` gracefully via the
    sentinel-on-import pattern below).

    To exercise the dispatcher live, replace this class body with a
    cookie-scrape MCP wrapper that exposes:

    * ``send_dm(twitter_handle: str, message: str, intent_id: str)
      -> str | None`` returning an optional thread_id.
    * ``list_recent_dms(limit: int = 100) -> list[dict]`` returning
      DM conversations shaped per :class:`reconcile.TwitterClientLike`.
    """

    def __init__(self):
        raise NotImplementedError(
            "TwitterClient is a Pillar I-deferred stub. Inject a fake "
            "(tests) or wait for the OSS bring-up's reference adapter."
        )

    def send_dm(
        self,
        *,
        twitter_handle: str,
        message: str,
        intent_id: str,
    ) -> Optional[str]:
        """Placeholder; the live adapter wraps the cookie-scrape MCP."""
        raise NotImplementedError

    def list_recent_dms(self, limit: int = 100) -> list[dict]:
        """Placeholder; the live adapter wraps the cookie-scrape MCP."""
        raise NotImplementedError


def build_reconcile_adapter():
    """Return an adapter satisfying :class:`reconcile.TwitterClientLike`.

    Pillar I-deferred per ADR-0018 §Migration/rollout item 4. Today
    returns ``None`` so the reconcile CLI records "Pass F requires a
    Twitter client" per the same shape as Pass A's missing-Gmail
    error. Tests inject fakes via the ``twitter=`` kwarg to
    :func:`reconcile.reconcile` directly.

    When the operator wires their cookie-scrape MCP, this function
    returns a live client instance.
    """
    return None
