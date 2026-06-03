"""Lean observability shim for the core send path.

The cold-send path wraps each stage in a ``traced_stage`` span and records
per-channel send latency. The full OpenTelemetry implementation lives in
``observability.py`` and is an OPT-IN, advanced-tier concern: it pulls the
opentelemetry SDK + Prometheus exporter, which an adopter who only wants to send
compliant, deduplicated cold email should not have to install.

This module is the default. It provides the two symbols the send path imports
(``traced_stage`` + ``get_send_latency_histogram``) as no-ops, so importing the
send path needs neither opentelemetry nor the heavy ``observability`` module.

Opt in to real OTel spans by setting ``OUTREACH_FACTORY_OTEL=1`` (and installing
the opentelemetry deps in ``orchestrator/requirements.txt``); the shim then
delegates to ``observability.py`` lazily. If the flag is set but the SDK or the
module is unavailable, the shim warns once and stays no-op so a send never fails
on telemetry.

Keep this module dependency-light: it is on the core import path guarded by
``tests/test_import_graph_lean.py``. Do not import opentelemetry or any
operations-tier module at module scope here.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator


def _otel_opted_in() -> bool:
    return os.environ.get("OUTREACH_FACTORY_OTEL", "") not in ("", "0", "false", "False")


# Lazily-resolved real backend. None = not yet resolved; False = tried + failed
# (do not retry); a module = resolved real observability backend.
_backend_cache: object = None
_warned = False


def _backend():
    """Resolve the real observability module when OTel is opted in, else None.

    Lazy + cached. The import happens INSIDE this function (never at module
    scope) so the no-op default path keeps the core send import lean.
    """
    global _backend_cache, _warned
    if not _otel_opted_in():
        return None
    if _backend_cache is None:
        try:
            import observability as _obs  # noqa: PLC0415, lazy by design
            _backend_cache = _obs
        except Exception as exc:  # SDK absent / import error
            if not _warned:
                print(
                    "WARNING: OUTREACH_FACTORY_OTEL is set but the observability "
                    f"backend is unavailable ({type(exc).__name__}: {exc}); "
                    "continuing with no-op spans.",
                    file=sys.stderr,
                )
                _warned = True
            _backend_cache = False  # sentinel: tried + failed
    return _backend_cache or None


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None


class _NoopHistogram:
    def record(self, *_args, **_kwargs) -> None:
        return None


_NOOP_HISTOGRAM = _NoopHistogram()


@contextmanager
def traced_stage(stage, operation, *, attributes=None, tracer=None) -> Iterator[object]:
    """No-op stand-in for :func:`observability.traced_stage`.

    Delegates to the real OTel helper when ``OUTREACH_FACTORY_OTEL=1`` and the
    backend imports; otherwise yields a no-op span whose ``set_attribute`` is a
    no-op. The call signature mirrors the real helper so the swap is invisible
    to call sites.
    """
    backend = _backend()
    if backend is not None:
        with backend.traced_stage(
            stage, operation, attributes=attributes, tracer=tracer,
        ) as span:
            yield span
        return
    yield _NoopSpan()


def get_send_latency_histogram(*args, **kwargs):
    """No-op stand-in for :func:`observability.get_send_latency_histogram`.

    Returns a recorder whose ``record(value, attributes)`` is a no-op, unless
    OTel is opted in and the backend imports, in which case it delegates.
    """
    backend = _backend()
    if backend is not None:
        return backend.get_send_latency_histogram(*args, **kwargs)
    return _NOOP_HISTOGRAM
