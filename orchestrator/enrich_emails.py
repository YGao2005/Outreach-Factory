#!/usr/bin/env python3
"""
enrich_emails.py — Common-pattern email guesser + tiered verifier for queued Person notes.

Reads Person notes in your queue whose `email:` field is empty, looks up the
company's website domain in the companion Company note, writes a common-pattern
guess to the email field, and verifies the guess at one of two tiers:

  Tier 2 (default): Reoon Email Verifier in power mode — catches dead-domain
    bounces AND catch-all-risk bounces. Requires a Reoon API key. ~$0.005/check.
  Tier 1 (--mx-only): domain-level MX check via dnspython — free, no API. Tells
    you the domain CAN receive mail, but doesn't verify the specific mailbox
    (~5-10% bounce on valid domains, vs ~50%+ on invalid). Right default for
    OSS users without a Reoon key.

Why no PDL: PDL free tier returns booleans for email fields, not strings.
Why no SMTP RCPT TO: dead — Google MX returns 250 OK for everything.

The default pattern is `firstname@domain` — the modal address shape at
founder-direct cold sends to <50-person companies (~70% hit rate). If a
guess bounces, pivot manually to firstname.lastname@ etc.

Config-driven: reads ~/.outreach-factory/config.yml (override with
$OUTREACH_FACTORY_CONFIG env var) for vault paths and Reoon key location.

Usage:
    python3 enrich_emails.py                   # process all queued; Tier 2 (Reoon)
    python3 enrich_emails.py --mx-only         # Tier 1 (MX-check, free)
    python3 enrich_emails.py --no-verify       # guess only, no verification
    python3 enrich_emails.py --dry-run         # show what would happen, write nothing
    python3 enrich_emails.py --name "Jonas"    # only process names matching substring
    python3 enrich_emails.py --pattern dot     # use firstname.lastname@ pattern instead
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import yaml

# Try the package path first so test environments that have aliased
# ``orchestrator.X`` reuse the SAME module objects pytest+conftest
# loaded (avoids the bare-name path creating a SECOND module tree
# under ``policy.types`` / ``policy.engine`` and silently producing
# instance-check failures across tests). Fall back to bare imports
# when running as ``python orchestrator/enrich_emails.py`` (the
# legacy CLI invocation where ``orchestrator/`` itself is on sys.path).
try:
    from orchestrator import ledger as _ledger
    from orchestrator import email_verification_cache as _cache
    from orchestrator import env_loader as _env_loader
    from orchestrator.policy.budget import COST_RATES_USD as _COST_RATES_USD
    _LEDGER_AVAILABLE = True
except ImportError:
    try:
        import ledger as _ledger
        import email_verification_cache as _cache
        import env_loader as _env_loader
        from policy.budget import COST_RATES_USD as _COST_RATES_USD
        _LEDGER_AVAILABLE = True
    except ImportError:
        _LEDGER_AVAILABLE = False
        _ledger = None  # type: ignore[assignment]
        _cache = None  # type: ignore[assignment]
        _env_loader = None  # type: ignore[assignment]
        _COST_RATES_USD = {}


def _lazy_verify_mx(*args, **kwargs):
    """Lazy entry point for ``verify_email.verify_mx``.

    Imported lazily so importing this module doesn't pull in
    ``dnspython`` — which lets the cost-event helpers (`emit_reoon_cost_event`)
    be tested in environments that don't have dnspython installed.
    The vault-walking CLI path (which actually calls verify_mx) still
    requires dnspython at runtime, exactly as before.
    """
    from verify_email import verify_mx  # noqa: WPS433
    return verify_mx(*args, **kwargs)


verify_mx = _lazy_verify_mx

REOON_ENDPOINT = "https://emailverifier.reoon.com/api/v1/verify"
REOON_TIMEOUT_S = 30  # power mode is 5-15s; allow margin
REOON_KEY_DEFAULT = Path.home() / ".outreach-factory" / "credentials" / "reoon_api_key.txt"

PATTERNS = {
    "first": lambda first, last, dom: f"{first}@{dom}",
    "dot": lambda first, last, dom: f"{first}.{last}@{dom}",
    "first_lastinitial": lambda first, last, dom: f"{first}{last[0]}@{dom}" if last else None,
    "firstinitial_last": lambda first, last, dom: f"{first[0]}{last}@{dom}" if last else None,
}

# Reoon status → action.
HARD_SKIP_STATUSES = {"invalid", "disposable", "spamtrap"}
RISK_STATUSES = {"catch_all"}
SAFE_STATUSES = {"safe"}


def _config_path() -> Path:
    return Path(os.environ.get("OUTREACH_FACTORY_CONFIG", "~/.outreach-factory/config.yml")).expanduser()


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        sys.exit(
            f"ERROR: config not found at {path}\n"
            f"Copy config-template/config.example.yml to ~/.outreach-factory/config.yml and fill in your values."
        )
    return yaml.safe_load(path.read_text())


def queue_dir(config: dict) -> Path:
    v = config["vault"]
    return (Path(v["path"]).expanduser() / v["people_dir"] / v["queue_subdir"])


def companies_dir(config: dict) -> Path:
    v = config["vault"]
    return (Path(v["path"]).expanduser() / v["companies_dir"])


def reoon_key_path(config: dict) -> Path:
    """Resolve Reoon API key path. Order: config field → legacy default."""
    configured = (config.get("email_enrich") or {}).get("reoon_key_path", "").strip()
    return Path(configured).expanduser() if configured else REOON_KEY_DEFAULT


def parse_frontmatter(text: str) -> dict[str, str]:
    """Crude line-based YAML parse for flat scalars only."""
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter opener")
    end_marker = text.index("\n---\n", 4)
    fm: dict[str, str] = {}
    for line in text[4:end_marker].split("\n"):
        if not line or line[0] in (" ", "-", "#"):
            continue
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm


def is_email_empty(fm: dict[str, str]) -> bool:
    return not fm.get("email", "").strip()


def company_wikilink_to_filename(wikilink: str) -> str | None:
    m = re.match(r'\[\[([^\]]+)\]\]', wikilink.strip())
    return m.group(1) if m else None


def find_company_website(company_name: str, companies_root: Path) -> str | None:
    """Walk all subfolders of the companies dir for `<company>.md`, return its website field."""
    if not company_name:
        return None
    for path in companies_root.rglob(f"{company_name}.md"):
        try:
            fm = parse_frontmatter(path.read_text())
            return fm.get("website", "").strip() or None
        except (ValueError, OSError):
            continue
    return None


def domain_from_website(website: str) -> str | None:
    if not website:
        return None
    m = re.match(r"https?://(?:www\.)?([^/]+)", website)
    return m.group(1).lower() if m else None


def split_name(full_name: str) -> tuple[str, str]:
    """Return (first_lower, last_lower). Handles compound surnames by taking the last token."""
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0].lower(), "")
    last = re.sub(r"[^a-zA-Z]", "", parts[-1]).lower()
    return (parts[0].lower(), last)


def load_reoon_key(key_path: Path) -> str:
    """Resolve the Reoon API key. ``$REOON_API_KEY`` (from the environment or
    ~/.outreach-factory/.env) wins; else read `key_path`. Fail loud if neither
    yields a key."""
    if _env_loader is not None:
        env_key = _env_loader.get_secret("REOON_API_KEY")
        if env_key:
            return env_key
    if not key_path.exists():
        raise SystemExit(
            f"Reoon API key not found: set $REOON_API_KEY (or in "
            f"~/.outreach-factory/.env), or create {key_path} (chmod 600) / set "
            f"email_enrich.reoon_key_path in your config, or run with "
            f"--mx-only / --no-verify."
        )
    key = key_path.read_text().strip()
    if not key:
        raise SystemExit(f"Reoon API key file {key_path} is empty.")
    return key


def _safe_append_cache_event(led: "object | None", event: dict) -> None:
    """Local best-effort ledger append for cache-primitive event emits.

    Per the HANDOFF-pillar-e-week-4.md §Design-decisions discipline
    (inherited from ADR-0033 D149's pillar-primitive-as-sibling shape):
    each module owns its own emit error handling — don't cross-import
    underscore-prefixed helpers from sibling primitives. The cache
    primitive's :func:`email_verification_cache._safe_append` and this
    helper share shape but live in their owning modules.

    A ledger I/O failure must not block the verification (the cache_hit
    event is the cost-attribution signal; losing it loses one row of
    Pillar G observability, not the cache behavior itself). Print
    stderr warning + continue.
    """
    if led is None:
        return
    try:
        led.append(event)
    except (OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write(
            f"WARNING: ledger append failed for "
            f"{event.get('type')}: {exc}\n"
        )


def verify_with_reoon(
    email: str,
    api_key: str,
    *,
    led: "object | None" = None,
    person_id: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Call Reoon power-mode verifier. Returns dict with at least `status` + `overall_score`.

    Per ADR-0034 D158 (Pillar E Week 4-5 — email-verification cache
    primitive integration) the function gains a cache-lookup prelude:
    when ``led`` is provided + the cache primitive is importable, the
    wrapper queries
    :func:`orchestrator.email_verification_cache.lookup_cache` BEFORE
    making the HTTP request. On a cache hit (a recent Reoon
    verification for the same email exists within the 30-day TTL per
    ADR-0034 D157), the wrapper:

    * Short-circuits the Reoon HTTP call (no cost).
    * Emits a ``email_verification_cache_hit`` event (NEW per ADR-0032
      D146) carrying the cached outcome + age + the ``channel:
      "email"`` invariant.
    * Returns the cached Reoon response dict verbatim — caller code
      consuming the return value (:func:`apply_verification_to_text`)
      sees the same shape it would see from a fresh Reoon call.
    * Does NOT emit ``cost_incurred`` — the cache hit IS the cost-
      avoidance signal per ADR-0032 D144; co-emission would double-
      count in Pillar G dashboards.

    On a cache miss (no recent match OR ``led is None`` OR cache
    primitive unavailable), the wrapper falls through to the existing
    Reoon HTTP path UNCHANGED + emits ``cost_incurred`` per ADR-0006
    (extended to carry the ``email`` + ``verification_response``
    fields per ADR-0034 D156 — the cache substrate).

    A cache-lookup failure (corrupt ledger; index error) MUST NOT
    block the verification — the cache is FAST-PATH; the broken-cache
    path falls through to Reoon HTTP with a stderr warning.

    Backwards compatibility: the legacy two-arg signature
    ``verify_with_reoon(email, api_key)`` is preserved. Callers that
    don't pass ``led`` get the pre-Pillar-E-Week-4 behavior (HTTP
    call, no cache lookup, no internal cost emit) — the caller is
    responsible for the separate :func:`emit_reoon_cost_event` invocation
    in that mode.

    Note: the primary call site :func:`process_one` was refactored at
    Week 4-5 to pass ``led`` + ``person_id`` + ``run_id`` (so the cost
    emit now happens INSIDE this function for the production path).
    The legacy two-arg path remains for external callers + test code
    only — future call sites SHOULD pass ``led`` to gain the cache
    + the centralized cost-emit semantics. A new call site without
    ``led`` would silently lose cache observability AND require
    redundant manual cost-emit plumbing.

    Args:
        email: The email address to verify.
        api_key: The Reoon API key.
        led: Optional ledger handle for cache lookup + event emission.
            ``None`` preserves the pre-Pillar-E-Week-4 behavior (no
            cache; no cost emit from this function).
        person_id: Optional person attribution for the cache_hit /
            cost_incurred events. Stamped on whichever event the
            cache decision emits.
        run_id: Optional run attribution for the cost_incurred event
            (cache_hit events do not carry ``run_id`` — they are
            cost-avoidance signals not run-attributable spending).

    Returns:
        The Reoon response dict (verbatim from HTTP or verbatim from
        cache — the shape is identical).

    Raises:
        urllib.error.URLError / HTTPError / TimeoutError on HTTP
        failure (the caller decides whether to skip the prospect —
        fail loud, per Rule 10). ValueError if the Reoon response
        body lacks the ``status`` field. The cache-lookup path does
        NOT raise these — a malformed cached response yields a miss
        + falls through to HTTP.
    """
    # Per ADR-0034 D158 — cache-lookup prelude. Only when the caller
    # opts in via ``led`` AND the cache primitive imported cleanly.
    if led is not None and _LEDGER_AVAILABLE and _cache is not None:
        try:
            cache_result = _cache.lookup_cache(email, ledger=led)
        except Exception as exc:
            # Broken cache MUST NOT block verification. Stderr warn
            # + fall through to HTTP per the cache-as-FAST-PATH
            # discipline (HANDOFF-pillar-e-week-4.md §Design-decisions).
            sys.stderr.write(
                f"WARNING: email_verification_cache.lookup_cache "
                f"raised for {email!r}: {exc}; falling through to Reoon "
                "HTTP call.\n"
            )
            cache_result = None
        if cache_result is not None and cache_result.is_cache_hit:
            payload = _cache.build_email_verification_cache_hit_payload(
                cache_result, email, person_id=person_id,
            )
            _safe_append_cache_event(led, payload)
            return cache_result.cached_response

    # Cache miss (or no ledger / no cache module): existing Reoon HTTP
    # path — unchanged from pre-Pillar-E-Week-4 behavior.
    params = urllib.parse.urlencode({"email": email, "key": api_key, "mode": "power"})
    url = f"{REOON_ENDPOINT}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "outreach-factory/1.0"})
    with urllib.request.urlopen(req, timeout=REOON_TIMEOUT_S) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if "status" not in data:
        raise ValueError(f"Reoon response missing `status` field: {body[:200]}")

    # Per ADR-0034 D156 — when caller opted in via ``led``, this
    # function is the sole emitter of cost_incurred for Reoon (the
    # extension carries ``email`` + ``verification_response`` so the
    # next lookup_cache call can find this event as the cache
    # substrate). When ``led`` is absent (legacy two-arg signature),
    # the cost emit remains the caller's responsibility via the
    # existing :func:`emit_reoon_cost_event` helper at the call site.
    if led is not None and _LEDGER_AVAILABLE:
        emit_reoon_cost_event(
            led, person_id=person_id, run_id=run_id,
            email=email, verification_response=data,
        )

    return data


def emit_reoon_cost_event(
    led: "object | None",
    *,
    person_id: str | None = None,
    run_id: str | None = None,
    email: str | None = None,
    verification_response: dict | None = None,
) -> None:
    """Emit a ``cost_incurred`` event for one successful Reoon verify call.

    Per ADR-0006 §Emit-site contract: emit at the API-call SUCCESS path
    only — we don't pay for HTTP-error failures (Reoon's
    pricing/terms-of-service confirm only billable calls are scored).

    Caller passes the Ledger instance (or None if running in a context
    without ledger access — the legacy CLI path stays usable without
    touching the ledger). Failure to record the cost event is logged
    and swallowed: the API call already succeeded, and rolling it
    back over an audit-trail miss would be worse than the slight
    under-report.

    Per-prospect attribution: ``person_id`` if known. The enrich_emails
    CLI knows the Person it's enriching (it's the loop variable), so
    the caller can pass ``person_id``. Run-level overhead emissions
    (e.g. API auth probes) carry ``person_id=None``.

    Per ADR-0034 D156 (Pillar E Week 4-5 — email-verification cache
    substrate): the event carries two additional fields when the
    caller provides them:

    * ``email`` — the email address that was verified. The cache
      primitive's :func:`email_verification_cache.lookup_cache`
      filters cost events by this field; future cache hits for the
      same email find this event as the substrate.
    * ``verification_response`` — the Reoon response dict
      (preserved verbatim). The cache primitive returns this dict
      as the cached response on hit; the caller's downstream
      consumers see the same shape as a fresh Reoon call.

    Both fields are optional kwargs (``None`` defaults). Pre-Pillar-
    E-Week-4 cost events lacking these fields are invisible to the
    cache (treated as miss); existing operators populate the cache
    going forward from the next Reoon call. The fields are content-
    additive — the existing :class:`policy.budget.BudgetWindowCapRule`
    consumer ignores the additional fields (per ADR-0006 §LedgerLike
    Protocol shape).
    """
    if led is None or not _LEDGER_AVAILABLE:
        return
    rate = _COST_RATES_USD.get("reoon", {}).get("verify", 0.0)
    try:
        led.append({
            "type": "cost_incurred",
            "source": "reoon",
            "amount_usd": float(rate),
            "units": 1,
            "model_or_endpoint": "verifier/power",
            "person_id": person_id,
            "run_id": run_id,
            "email": email,
            "verification_response": verification_response,
        })
    except Exception as exc:
        sys.stderr.write(
            f"WARNING: cost_incurred append failed for reoon verify: {exc}\n"
        )


def upsert_frontmatter_field(text: str, key: str, value: str) -> str:
    """Update `key: ...` in frontmatter if present; else insert before closing `---`.

    Only touches the leading frontmatter block. Idempotent.
    """
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter opener")
    end_idx = text.index("\n---\n", 4)
    block = text[4:end_idx]
    rest = text[end_idx:]

    line_re = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    new_line = f"{key}: {value}"
    if line_re.search(block):
        block = line_re.sub(new_line, block, count=1)
    else:
        block = block.rstrip("\n") + "\n" + new_line
    return "---\n" + block + rest


def write_email_with_comment(text: str, email: str, comment: str) -> str:
    """Replace empty `email:` line with `email: <addr>  # <comment>`."""
    return re.sub(
        r"^email:\s*$",
        f"email: {email}  # {comment}",
        text,
        count=1,
        flags=re.MULTILINE,
    )


def apply_verification_to_text(
    text: str,
    *,
    guess: str,
    pattern_label: str,
    alts: list[str],
    verification: dict | None,
) -> tuple[str, str, str]:
    """Apply guess + (optional) verification result to note text.

    Returns (new_text, outcome, detail) where outcome is one of:
      'safe'           — guess written, no risk flag
      'catch_all'      — guess written, email_risk=catch_all
      'hard_skip'      — guess NOT written (status invalid/disposable/spamtrap)
      'guess_only'     — no verification was attempted; guess written unverified
    """
    today = date.today().isoformat()
    alts_str = f" | alts: {', '.join(alts)}" if alts else ""

    if verification is None:
        comment = f"guess-unverified ({pattern_label}){alts_str}"
        new = write_email_with_comment(text, guess, comment)
        return new, "guess_only", guess

    status = (verification.get("status") or "").lower()
    score = verification.get("overall_score")
    score_str = str(score) if score is not None else "?"

    new = text

    if status in HARD_SKIP_STATUSES:
        # Don't write the bad guess. Record the attempt + reason so reruns don't repeat.
        new = upsert_frontmatter_field(new, "email_verified_status", status)
        new = upsert_frontmatter_field(new, "email_verified_score", score_str)
        new = upsert_frontmatter_field(new, "email_verified_at", today)
        new = upsert_frontmatter_field(new, "email_skip_reason", f'"reoon-{status}: {guess}"')
        return new, "hard_skip", f"{guess} → {status}"

    if status in RISK_STATUSES:
        comment = f"guess-verified-catch_all ({pattern_label}){alts_str}"
        new = write_email_with_comment(new, guess, comment)
        new = upsert_frontmatter_field(new, "email_verified_status", status)
        new = upsert_frontmatter_field(new, "email_verified_score", score_str)
        new = upsert_frontmatter_field(new, "email_verified_at", today)
        new = upsert_frontmatter_field(new, "email_risk", "catch_all")
        return new, "catch_all", f"{guess} (score {score_str})"

    if status in SAFE_STATUSES:
        comment = f"guess-verified-safe ({pattern_label}){alts_str}"
        new = write_email_with_comment(new, guess, comment)
        new = upsert_frontmatter_field(new, "email_verified_status", status)
        new = upsert_frontmatter_field(new, "email_verified_score", score_str)
        new = upsert_frontmatter_field(new, "email_verified_at", today)
        return new, "safe", f"{guess} (score {score_str})"

    # Unknown status — fail loud rather than guessing routing.
    raise ValueError(f"Unknown Reoon status {status!r} for {guess}; full response: {verification}")


def apply_mx_to_text(
    text: str,
    *,
    guess: str,
    pattern_label: str,
    alts: list[str],
    mx_result: dict,
) -> tuple[str, str, str]:
    """Apply Tier-1 MX result to note text.

    Returns (new_text, outcome, detail) where outcome is one of:
      'domain_valid_unverified'  — domain has MX (or A-fallback); guess written
      'domain_invalid'           — no MX, no A-record; guess NOT written
    """
    today = date.today().isoformat()
    alts_str = f" | alts: {', '.join(alts)}" if alts else ""

    if not mx_result["ok"]:
        new = text
        new = upsert_frontmatter_field(new, "email_verified_status", "domain_invalid")
        new = upsert_frontmatter_field(new, "email_verified_at", today)
        new = upsert_frontmatter_field(
            new, "email_skip_reason", f'"mx-check: {mx_result["reason"]} ({guess})"'
        )
        return new, "domain_invalid", f"{guess} → {mx_result['reason']}"

    mx_brief = "a-record" if not mx_result["has_mx"] else f"{len(mx_result['mx_hosts'])} mx"
    comment = f"guess-mx-only ({pattern_label}, {mx_brief}){alts_str}"
    new = write_email_with_comment(text, guess, comment)
    new = upsert_frontmatter_field(new, "email_verified_status", "domain_valid_unverified")
    new = upsert_frontmatter_field(new, "email_verified_at", today)
    return new, "domain_valid_unverified", f"{guess} ({mx_brief})"


def process_one(
    filepath: Path,
    primary_pattern: str,
    dry_run: bool,
    verify_mode: str,
    reoon_key: str | None,
    companies_root: Path,
    led: "object | None" = None,
    run_id: str | None = None,
) -> dict:
    """Process a single Person note. verify_mode: 'reoon' | 'mx_only' | 'off'."""
    text = filepath.read_text()
    try:
        fm = parse_frontmatter(text)
    except ValueError as e:
        return {"name": filepath.stem, "status": "skip", "reason": f"parse: {e}"}

    if fm.get("type") != "person":
        return {"name": filepath.stem, "status": "skip", "reason": "not type=person"}

    if not is_email_empty(fm):
        return {"name": filepath.stem, "status": "skip", "reason": f"email already set: {fm['email'][:40]}"}

    if fm.get("email_skip_reason"):
        return {"name": filepath.stem, "status": "skip", "reason": f"prior skip: {fm['email_skip_reason'][:40]}"}

    name = fm.get("name") or filepath.stem
    company_link = fm.get("company", "")
    company_name = company_wikilink_to_filename(company_link) or ""
    website = find_company_website(company_name, companies_root) or ""
    domain = domain_from_website(website)

    if not domain:
        return {"name": name, "status": "fail", "reason": f"no domain (company={company_name!r})"}

    first, last = split_name(name)
    if not first:
        return {"name": name, "status": "fail", "reason": "could not parse first name"}

    primary = PATTERNS[primary_pattern](first, last, domain)
    if not primary:
        return {"name": name, "status": "fail", "reason": f"pattern {primary_pattern!r} requires last name"}

    alts: list[str] = []
    for pname, fn in PATTERNS.items():
        if pname == primary_pattern:
            continue
        alt = fn(first, last, domain)
        if alt and alt != primary and alt not in alts:
            alts.append(alt)

    if verify_mode == "mx_only":
        mx_result = verify_mx(domain)
        try:
            new_text, outcome, detail = apply_mx_to_text(
                text, guess=primary, pattern_label=primary_pattern, alts=alts, mx_result=mx_result
            )
        except ValueError as e:
            return {"name": name, "status": "fail", "reason": str(e)}
    else:
        verification: dict | None = None
        if verify_mode == "reoon":
            assert reoon_key is not None
            try:
                # Per ADR-0034 D158: pass led / person_id / run_id so
                # verify_with_reoon performs the cache prelude AND owns
                # the cost emit (cache hit → email_verification_cache_hit
                # event INSTEAD of cost_incurred; cache miss → HTTP call
                # + cost_incurred per ADR-0006 unchanged, extended with
                # email + verification_response per D156).
                # TODO(yang, 2026-05-18): swap person_id to the real
                # identity.read_person_keys()[0] once Pillar E Week 9-11
                # lands the per-skill discovery_lineage stamping refactor.
                # Today the vault filename stem is the only stable
                # identifier this script has — good enough for the
                # budget rule's per-person attribution, but it breaks
                # if the Person note gets renamed.
                verification = verify_with_reoon(
                    primary, reoon_key,
                    led=led, person_id=filepath.stem, run_id=run_id,
                )
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as e:
                # Per ADR-0006 §Emit-site contract: do NOT emit
                # cost_incurred on failure (Reoon does not bill
                # non-200 responses). The failure itself is the
                # caller-visible signal. The cache primitive's lookup
                # is read-only — no event was emitted on the lookup
                # path either; the failure surface is unchanged.
                return {"name": name, "status": "fail", "reason": f"reoon: {e}"}

        try:
            new_text, outcome, detail = apply_verification_to_text(
                text,
                guess=primary,
                pattern_label=primary_pattern,
                alts=alts,
                verification=verification,
            )
        except ValueError as e:
            return {"name": name, "status": "fail", "reason": str(e)}

    if not dry_run and new_text != text:
        filepath.write_text(new_text)

    return {"name": name, "status": outcome, "email": primary, "alts": alts, "detail": detail}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--name", default="", help="Substring filter on filename")
    parser.add_argument(
        "--pattern",
        choices=sorted(PATTERNS.keys()),
        default="first",
        help="Primary email pattern. Default: 'first' (firstname@domain).",
    )
    verify_group = parser.add_mutually_exclusive_group()
    verify_group.add_argument(
        "--mx-only",
        dest="verify_mode",
        action="store_const",
        const="mx_only",
        help="Tier 1 verify: domain MX-check only (free, no API). Right default for OSS.",
    )
    verify_group.add_argument(
        "--no-verify",
        dest="verify_mode",
        action="store_const",
        const="off",
        help="Skip verification entirely (faster, but bad addresses get queued).",
    )
    parser.set_defaults(verify_mode="reoon")
    args = parser.parse_args()

    config = load_config()
    queue = queue_dir(config)
    companies = companies_dir(config)
    if not queue.exists():
        raise SystemExit(f"queue not found: {queue} (check vault.* keys in your config)")

    reoon_key = load_reoon_key(reoon_key_path(config)) if args.verify_mode == "reoon" else None

    files = sorted(queue.glob("*.md"))
    if args.name:
        files = [f for f in files if args.name.lower() in f.stem.lower()]

    verify_label = {
        "reoon": "verify=Reoon (Tier 2)",
        "mx_only": "verify=MX-only (Tier 1)",
        "off": "verify=OFF",
    }[args.verify_mode]
    print(
        f"Processing {len(files)} queued Person note(s); pattern={args.pattern}; {verify_label}"
        + (" [DRY RUN]" if args.dry_run else "")
    )
    print()

    # Open the ledger for cost-event emission (ADR-0006). Quietly
    # skip if the ledger module isn't importable — the legacy enrich
    # CLI must keep working in environments that haven't synced
    # orchestrator/policy/.
    led = None
    run_id = None
    if _LEDGER_AVAILABLE and args.verify_mode == "reoon" and not args.dry_run:
        import uuid as _uuid
        ldir_env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
        ldir = Path(os.path.expanduser(ldir_env)).resolve() if ldir_env \
            else _ledger.DEFAULT_LEDGER_DIR
        led = _ledger.Ledger(ldir)
        run_id = f"enrich-{_uuid.uuid4().hex[:10]}"

    rows = [
        process_one(
            f, args.pattern, args.dry_run, args.verify_mode, reoon_key,
            companies, led=led, run_id=run_id,
        )
        for f in files
    ]

    print(f"{'NAME':<32} {'OUTCOME':<11} {'DETAIL':<48} ALTS")
    print("-" * 120)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        alts = r.get("alts") or []
        detail = r.get("detail") or r.get("email") or r.get("reason", "")
        alts_brief = (", ".join(alts[:3]) + (" …" if len(alts) > 3 else "")) if alts else ""
        print(f"{r['name'][:32]:<32} {r['status']:<11} {detail[:48]:<48} {alts_brief}")
    print()

    written = (
        counts.get("safe", 0)
        + counts.get("catch_all", 0)
        + counts.get("guess_only", 0)
        + counts.get("domain_valid_unverified", 0)
    )
    skipped_bad = counts.get("hard_skip", 0) + counts.get("domain_invalid", 0)
    print(
        f"Summary: {written} written ({counts.get('safe',0)} safe, "
        f"{counts.get('catch_all',0)} catch_all, {counts.get('guess_only',0)} unverified, "
        f"{counts.get('domain_valid_unverified',0)} mx-only) | "
        f"{skipped_bad} skipped-bad | {counts.get('skip',0)} no-op | {counts.get('fail',0)} failed."
    )
    if args.verify_mode == "reoon":
        reoon_calls = (
            counts.get("safe", 0) + counts.get("catch_all", 0) + counts.get("hard_skip", 0)
        )
        print(f"Reoon calls made (approx): {reoon_calls}. Quota: 600/mo recurring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
