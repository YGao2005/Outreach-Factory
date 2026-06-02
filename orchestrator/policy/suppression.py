"""Pillar A — list-based suppression rules + GDPR-forget support.

Three concrete rule classes, one per suppression dimension:

* :class:`SuppressEmailRule` (``suppression.email``) — exact-match block
  on the recipient email address.
* :class:`SuppressDomainRule` (``suppression.domain``) — block on the
  recipient's email domain (case-insensitive).
* :class:`SuppressIdentityKeyRule` (``suppression.identity-key``) —
  block when ``ctx.person_id`` (or any LinkedIn-shaped key derivable
  from it) matches an entry in the list.

Lists live in ``~/.outreach-factory/suppressions/*.yml``. Each file
carries a ``version:`` for migration discipline (Pillar B will own the
runner). The :func:`load_suppression_list_from_yaml` helper reads a
file into a :class:`SuppressionList`, which the three rule classes
consume directly.

Deliberate non-feature: ``block_when:``
---------------------------------------
Suppression rules do **not** accept a ``block_when:`` filter (cooldown
rules do). Suppression is a kill switch — a do-not-contact entry fires
on every send regardless of channel or register, by design. A future
contributor expecting parity with cooldown will reach for ``block_when:``
and find it missing; see ADR-0004 §Alternative 8 for the rationale.
Operators wanting per-register or per-channel scoping should encode it
in *list files* (one rule per file, different filenames) rather than as
a rule-level filter, so the "kill" semantics aren't masked by an
accidentally-narrow filter.

See ``docs/adr/0004-suppression-and-gdpr-forget.md`` for the binding
spec, including the GDPR ``forget`` cross-pillar contract.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from .engine import register_rule_class
from .types import Allow, Block, RuleContext, RuleResult


# Version of the suppression YAML format. Independent from the policy
# YAML version (``engine.SUPPORTED_POLICY_SCHEMA_VERSION``) because the
# two file types evolve at different cadences — bumping suppression's
# schema doesn't force a policy file rewrite.
SUPPORTED_SUPPRESSION_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Identity-key canonicalization
# ---------------------------------------------------------------------------


def _canon_linkedin(value: str) -> str:
    """Normalize a LinkedIn identifier to the ``in/<slug>`` shape.

    Accepts:

    * Full URLs (``https://www.linkedin.com/in/foo``).
    * Country-prefixed URLs (``https://uk.linkedin.com/in/foo``).
    * Bare ``in/<slug>`` strings.
    * Bare slugs (``foo``) — assumed to be person profiles.

    Returns the normalized ``in/<slug>`` (lowercased), or the original
    string lowercased if nothing matches. This mirrors the contract
    documented in ``orchestrator.identity._normalize_linkedin`` but is
    inlined here so the suppression module has no cross-package
    dependency on identity internals (which the suppression spec ADR-0004
    explicitly calls out as a coupling we don't want — suppression must
    work even if a future refactor moves identity normalization).
    """
    s = value.strip()
    if not s:
        return s
    lowered = s.lower()
    # URL form — pull the trailing /in/<slug> or /company/<slug>.
    if "linkedin.com/" in lowered:
        tail = lowered.split("linkedin.com/", 1)[1]
        # Strip query / hash / trailing slash.
        for sep in ("?", "#"):
            if sep in tail:
                tail = tail.split(sep, 1)[0]
        tail = tail.strip("/")
        parts = tail.split("/", 2)
        if len(parts) >= 2 and parts[0] in ("in", "pub", "company"):
            kind = "in" if parts[0] == "pub" else parts[0]
            return f"{kind}/{parts[1]}"
        # URL but didn't parse — fall through to raw lowercased form.
        return lowered
    # Bare ``pub/<slug>`` is the legacy LinkedIn person URL form — normalize
    # to ``in/<slug>`` for parity with the URL-form handling above. Without
    # this branch, a bare ``pub/foo`` falls through to the slug branch and
    # becomes ``in/pub/foo`` (a non-matching shape).
    if lowered.startswith("pub/"):
        rest = lowered[len("pub/"):]
        return f"in/{rest.split('/')[0]}"
    # Bare in/<slug> or company/<slug>.
    if lowered.startswith("in/") or lowered.startswith("company/"):
        prefix, _, rest = lowered.partition("/")
        return f"{prefix}/{rest.split('/')[0]}"
    # Bare slug → assume person.
    return f"in/{lowered.lstrip('/')}"


def _canon_identity_key(value: str) -> str:
    """Best-effort canonicalization for arbitrary identity-key entries.

    LinkedIn-shaped values go through :func:`_canon_linkedin`. Email-shaped
    values are lowercased. Everything else is lowercased + stripped.

    Identity-key suppression must canonicalize on both write *and* read so
    a user's entry of ``HTTPS://LinkedIn.COM/in/Foo`` matches a stored
    person_id ``in/foo`` (or vice versa). The ``pub/`` prefix (LinkedIn's
    legacy URL form) is included in the routing so bare ``pub/<slug>``
    entries normalize to ``in/<slug>`` — without ``pub/`` in this list,
    a bare ``pub/foo`` would return unchanged and never match a modern
    ``in/foo`` person_id.
    """
    s = value.strip()
    if not s:
        return s
    lowered = s.lower()
    if (
        "linkedin.com/" in lowered
        or lowered.startswith("in/")
        or lowered.startswith("company/")
        or lowered.startswith("pub/")
    ):
        return _canon_linkedin(s)
    return lowered


# ---------------------------------------------------------------------------
# SuppressionList — data-driven storage
# ---------------------------------------------------------------------------


@dataclass
class SuppressionList:
    """In-memory representation of one ``suppressions/*.yml`` file.

    Three dimensions stored as sets for O(1) membership tests. Email and
    domain dimensions are lowercased on load; identity-key entries are
    canonicalized via :func:`_canon_identity_key`.

    Empty fields are valid — a brand-new install ships an empty
    ``suppressions.yml`` and gradually accumulates entries as users
    unsubscribe / GDPR-forget requests land.
    """

    emails: set[str] = field(default_factory=set)
    domains: set[str] = field(default_factory=set)
    identity_keys: set[str] = field(default_factory=set)
    source_path: Path | None = None

    def has_email(self, email: str | None) -> bool:
        if not email:
            return False
        return email.lower().strip() in self.emails

    def has_domain(self, email: str | None) -> bool:
        if not email or "@" not in email:
            return False
        domain = email.split("@", 1)[1].lower().strip()
        return domain in self.domains

    def has_identity_key(self, person_id: str | None) -> bool:
        if not person_id:
            return False
        return _canon_identity_key(person_id) in self.identity_keys

    def merge(self, other: "SuppressionList") -> None:
        """In-place union of another list into this one."""
        self.emails |= other.emails
        self.domains |= other.domains
        self.identity_keys |= other.identity_keys


def load_suppression_list_from_yaml(path: Path) -> SuppressionList:
    """Parse one suppressions YAML file into a :class:`SuppressionList`.

    File shape::

        version: 1
        emails:
          - foo@bar.com
        domains:
          - spamtrap.io
        identity_keys:
          - in/john-doe
          - https://www.linkedin.com/in/jane-doe

    A missing file returns an empty list (greenfield OSS install must
    not block). An empty file (zero entries) is also valid.
    """
    p = Path(path)
    if not p.exists():
        return SuppressionList(source_path=p)

    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        return SuppressionList(source_path=p)
    if not isinstance(data, dict):
        raise ValueError(
            f"suppression file {p}: top-level must be a mapping, "
            f"got {type(data).__name__}",
        )

    if "version" not in data:
        raise ValueError(
            f"suppression file {p}: missing required 'version' key",
        )
    version = data["version"]
    if version != SUPPORTED_SUPPRESSION_SCHEMA_VERSION:
        raise ValueError(
            f"suppression file {p}: unsupported version {version!r} "
            f"(this build supports version "
            f"{SUPPORTED_SUPPRESSION_SCHEMA_VERSION})",
        )

    def _as_set(key: str, transform) -> set[str]:
        raw = data.get(key, []) or []
        if not isinstance(raw, list):
            raise ValueError(
                f"suppression file {p}: {key!r} must be a list, "
                f"got {type(raw).__name__}",
            )
        out: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                raise ValueError(
                    f"suppression file {p}: {key!r} entries must be "
                    f"strings, got {type(item).__name__}",
                )
            normalized = transform(item)
            if normalized:
                out.add(normalized)
        return out

    return SuppressionList(
        emails=_as_set("emails", lambda s: s.lower().strip()),
        domains=_as_set("domains", lambda s: s.lower().strip()),
        identity_keys=_as_set("identity_keys", _canon_identity_key),
        source_path=p,
    )


def load_suppression_dir(directory: Path) -> SuppressionList:
    """Merge every ``*.yml`` in ``directory`` into one SuppressionList.

    Used by the send-gate boot path — every file under
    ``~/.outreach-factory/suppressions/`` contributes entries. Missing
    directory returns an empty list (greenfield).
    """
    d = Path(directory)
    merged = SuppressionList(source_path=d)
    if not d.exists() or not d.is_dir():
        return merged
    for f in sorted(d.glob("*.yml")):
        merged.merge(load_suppression_list_from_yaml(f))
    return merged


# ---------------------------------------------------------------------------
# GDPR forget — atomic add to suppression
# ---------------------------------------------------------------------------


def forget_append(
    directory: Path,
    *,
    email: str | None = None,
    domain: str | None = None,
    identity_key: str | None = None,
    filename: str = "gdpr-forget.yml",
) -> Path:
    """Atomically append a forget entry to the suppressions directory.

    Pillar J's ``policy.py forget --person <id>`` calls this together
    with the ledger purge (see ADR-0004 §GDPR forget path). The append
    must be atomic with respect to the ledger purge — if the purge
    succeeds and this call fails, the suppression list is missing the
    forget entry and the rebuilt vault could re-enroll the person.

    Atomicity scope
    ---------------
    Atomicity here is *single-writer* file-level: write-temp-then-rename
    via the same target filename's ``.tmp`` suffix. **Concurrent calls
    from multiple processes (or interleaved within one process) WILL
    race on the fixed temp path** and corrupt the rename. The caller is
    responsible for serializing forget operations — Pillar J holds a
    lock spanning the ledger purge + this call per ADR-0004 §Decision
    step 2 + §Compliance I2. Do not call this from concurrent threads
    or processes without external mutual exclusion.

    The cross-pillar atomicity (ledger purge + suppression append both
    succeed-or-fail) is Pillar J's responsibility; this function
    guarantees only the file-level write-temp-then-rename.
    """
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    target = d / filename
    existing = load_suppression_list_from_yaml(target)

    if email:
        existing.emails.add(email.lower().strip())
    if domain:
        existing.domains.add(domain.lower().strip())
    if identity_key:
        existing.identity_keys.add(_canon_identity_key(identity_key))

    payload = {
        "version": SUPPORTED_SUPPRESSION_SCHEMA_VERSION,
        "emails": sorted(existing.emails),
        "domains": sorted(existing.domains),
        "identity_keys": sorted(existing.identity_keys),
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return target


# ---------------------------------------------------------------------------
# Rule classes
# ---------------------------------------------------------------------------


@dataclass
class SuppressEmailRule:
    """Block when ``ctx.email`` is in the per-email suppression list.

    Reason precedence: ``per-email`` is the most-specific match — if both
    an email rule and a domain rule would fire for the same send, the
    email rule firing first (rule-order in YAML) preserves the audit
    trail's specificity.
    """

    name: str
    suppressions: SuppressionList
    reason: str = "Recipient email is on the suppression list"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if self.suppressions.has_email(ctx.email):
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "dimension": "email",
                    "matched_email": (ctx.email or "").lower().strip(),
                    "source": str(self.suppressions.source_path)
                    if self.suppressions.source_path else None,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "SuppressEmailRule":
        _warn_if_block_when_present(spec)
        sup = _load_suppressions_from_spec(spec)
        return cls(
            name=spec["name"],
            suppressions=sup,
            reason=spec.get(
                "reason", "Recipient email is on the suppression list",
            ),
        )


@dataclass
class SuppressDomainRule:
    """Block when ``ctx.email``'s domain is in the per-domain suppression list.

    Case-insensitive on the domain (lowercase on both write and read).
    """

    name: str
    suppressions: SuppressionList
    reason: str = "Recipient domain is on the suppression list"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if self.suppressions.has_domain(ctx.email):
            domain = (ctx.email or "").split("@", 1)[-1].lower().strip() \
                if ctx.email else None
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "dimension": "domain",
                    "matched_domain": domain,
                    "source": str(self.suppressions.source_path)
                    if self.suppressions.source_path else None,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "SuppressDomainRule":
        _warn_if_block_when_present(spec)
        sup = _load_suppressions_from_spec(spec)
        return cls(
            name=spec["name"],
            suppressions=sup,
            reason=spec.get(
                "reason", "Recipient domain is on the suppression list",
            ),
        )


@dataclass
class SuppressIdentityKeyRule:
    """Block when ``ctx.person_id`` matches an entry in the identity-key list.

    LinkedIn-shaped entries are canonicalized to ``in/<slug>`` on both
    write and read so the YAML can be authored with full URLs and still
    match the canonical person_id form stored in vault frontmatter.
    """

    name: str
    suppressions: SuppressionList
    reason: str = "Person identity key is on the suppression list"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if self.suppressions.has_identity_key(ctx.person_id):
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "dimension": "identity_key",
                    "matched_key": _canon_identity_key(ctx.person_id or ""),
                    "source": str(self.suppressions.source_path)
                    if self.suppressions.source_path else None,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "SuppressIdentityKeyRule":
        _warn_if_block_when_present(spec)
        sup = _load_suppressions_from_spec(spec)
        return cls(
            name=spec["name"],
            suppressions=sup,
            reason=spec.get(
                "reason", "Person identity key is on the suppression list",
            ),
        )


def _warn_if_block_when_present(spec: dict[str, Any]) -> None:
    """Warn (stderr) when a suppression rule's YAML includes ``block_when:``.

    Suppression is a kill switch (ADR-0004 §Alternative 8 + class
    docstrings); the rule classes deliberately do NOT consume
    ``block_when:``. Operators who copy/paste a cooldown / budget rule
    template into a suppression rule expect the filter to scope, but
    it's silently ignored — typo class the holistic review caught as
    P2-2. Warn at load time so the operator notices their filter has
    no effect; mirrors the cross-channel rule's same-channel-overlap
    warning convention (``cross_channel.py:CrossChannelTouchRule.from_yaml``).
    Does NOT raise — the rule still loads and still kills correctly;
    the warning is process feedback for the operator.
    """
    if "block_when" in spec and spec["block_when"]:
        print(
            f"WARNING: suppression rule {spec.get('name')!r} has a "
            f"'block_when:' filter, but suppression rules are kill "
            f"switches (ADR-0004 §Alternative 8) — the filter is "
            f"silently ignored at evaluation. The rule will fire on "
            f"every send regardless. If you want per-register / "
            f"per-channel scoping, split the list into separate files "
            f"(one rule per file) rather than adding 'block_when:'.",
            file=sys.stderr,
        )


def _load_suppressions_from_spec(spec: dict[str, Any]) -> SuppressionList:
    """Resolve the spec's ``source:`` to a concrete SuppressionList.

    Two forms supported:

    * ``source: path/to/file.yml`` — load one file.
    * ``source: { dir: path/to/dir/ }`` — merge every ``*.yml`` in dir.

    Relative paths resolve to the user-home suppression directory
    (``~/.outreach-factory/suppressions/``) per the SoT registry row.

    Missing ``source:`` raises. The asymmetric-failure-cost principle
    (ADR-0001 §0, ADR-0004 §0) compels: a suppression rule with no list
    silently allows every send — the exact false-positive class the
    suppression rule is supposed to block. Operators must opt in
    explicitly. Unit-test code that wants to inject a pre-built
    ``SuppressionList`` constructs the rule class directly
    (``SuppressEmailRule(name=..., suppressions=...)``); the ``from_yaml``
    path is for operator-authored config only.
    """
    if "source" not in spec:
        raise ValueError(
            f"suppression rule {spec.get('name')!r}: 'source' is required "
            f"(a suppression rule with no list silently allows every send, "
            f"which is the failure mode suppression exists to prevent). "
            f"Use 'source: path/to/file.yml' or 'source: {{dir: path/}}'.",
        )
    src = spec["source"]
    if isinstance(src, str):
        return load_suppression_list_from_yaml(_resolve_source_path(src))
    if isinstance(src, dict) and "dir" in src:
        return load_suppression_dir(_resolve_source_path(src["dir"]))
    raise ValueError(
        f"suppression rule {spec.get('name')!r}: 'source' must be a "
        f"string path or {{dir: ...}} mapping, got {type(src).__name__}",
    )


def _resolve_source_path(value: str) -> Path:
    """Resolve a relative source path against ``~/.outreach-factory/suppressions/``.

    Absolute paths are returned as-is. ``~`` expansion is applied.
    """
    p = Path(value).expanduser()
    if p.is_absolute():
        return p
    return Path.home() / ".outreach-factory" / "suppressions" / p


# Register rule classes under their YAML discriminators (ADR-0004).
register_rule_class("suppression.email", SuppressEmailRule)
register_rule_class("suppression.domain", SuppressDomainRule)
register_rule_class("suppression.identity-key", SuppressIdentityKeyRule)
