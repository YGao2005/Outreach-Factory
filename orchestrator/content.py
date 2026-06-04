"""Content distribution entity - the broadcast surface's value types + sources.

The cold-email engine is 1:1 outbound. This is the 1:many BROADCAST surface on
the SAME spine: take the operator's own work (a shipped feature in a codebase, a
new or high-ranked research paper, a notes file), draft ONE canonical piece, and
project it per channel. "Turn Claude into a CMO": configurable input -> one
canonical source-of-truth piece -> register-aware projections per channel.

This module owns the ENTITY (the content piece + its per-channel variants), the
TYPED SOURCE REGISTRY (the operator's "config what to outreach, easily" surface),
the ONE genuinely-new primitive (the codebase salience selector that decides
which commits are announce-worthy), the refuse-loud ledger event builders, and
the read-only derived-state walk. The deterministic scheduler that decides which
approved posts are DUE lives in ``orchestrator/content_scheduler.py`` (it mirrors
``orchestrator/followup.py``); the per-channel posting clients arrive in Phase 2.

The spine invariant (do not violate)
------------------------------------
The ledger is the source of truth for STATE (drafted -> humanized -> approved ->
posted -> engagement). The canonical body is the source of truth for SUBSTANCE.
The per-channel variants are denormalized views of the canonical, exactly as
vault notes are denormalized views of the ledger. Eligibility + timing are
computed by READING the ledger, deterministically. Nothing here posts, mutates
the vault, or bypasses a guardrail; every actual post passes the policy engine at
post time, exactly like a send passes the send gates.

Hub-and-spoke (ADR-0082 D407)
-----------------------------
A variant is a register-aware RE-EXPRESSION of the canonical's substance, NOT a
mechanical truncation of its bytes. X gets the same claims in X's voice and shape
(a thread, a hook), not the canonical's first 280 characters. Identical or
mechanically-truncated cross-posting is FORBIDDEN and structurally rejected by
:func:`validate_adaptation` (the binding adaptation-refusal test pins it). A CMO
that clips one body across N channels reads as a cross-post bot, the fastest way
to torch the reputation the spine protects.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# Bare import per the orchestrator/ scripts' import convention (added to
# sys.path by conftest.py + the send path's bootstrap). Imports ONLY the ledger
# + stdlib so the surface stays off the heavy operations tier, mirroring
# followup.py's lean-import discipline.
import ledger as _ledger  # noqa: E402


# ---------------------------------------------------------------------------
# Closed sets (per the per-pillar mirror constants parity discipline)
# ---------------------------------------------------------------------------

#: The NEW event classes the content surface emits (ADR-0082 D408). Mirrors
#: ``observability.EVENT_CLASS_CATALOG``'s content block; the symmetric
#: assertion is a regression-barrier test (R031-shape closed-set discipline).
CONTENT_NEW_EVENT_CLASSES: frozenset[str] = frozenset({
    "content_drafted",
    "content_humanized",
    "content_review_approved",
    "content_review_rejected",
    "distribution_intent",
    "distribution_confirmed",
    "distribution_failed",
    "engagement_observed",
})

#: Every channel the broadcast surface can target. The platform post id is the
#: per-channel two-phase correlation key (the analog of ``gmail_message_id``).
POST_CHANNELS: frozenset[str] = frozenset({
    "linkedin_post",
    "x_post",
    "x_thread",
    "blog",
    "newsletter",
    "reddit",
    "hn",
    "discord",
})

#: Communities are DRAFT-AND-MANUAL-POST in v1, structurally (ADR-0082 D411(2)).
#: The dispatcher has NO auto-post path for these; the system produces the text +
#: the target + a "post this yourself" reminder. Auto-promotion here is a ban +
#: reputation landmine.
COMMUNITY_CHANNELS: frozenset[str] = frozenset({"reddit", "hn", "discord"})

#: Owned channels (you control the destination): safe to auto-publish.
OWNED_CHANNELS: frozenset[str] = frozenset({"blog", "newsletter"})

#: Channels with a client we own + where posting is normal: auto-publishable
#: (behind ``auto_publish``, off by default).
AUTO_CHANNELS: frozenset[str] = frozenset({"linkedin_post", "x_post", "x_thread"})

#: The content registers (ADR-0082 D406). A post is not a thread is not an essay;
#: each carries a per-channel default, a length feel, and a norm checklist (the
#: checklists live in the draft-content skill, not here).
CONTENT_REGISTERS: frozenset[str] = frozenset({"post", "thread", "essay"})

#: The per-channel default register. A LinkedIn post and an X post are ``post``;
#: an X thread is ``thread``; blog + newsletter are long-form ``essay``.
CHANNEL_DEFAULT_REGISTER: dict[str, str] = {
    "linkedin_post": "post",
    "x_post": "post",
    "x_thread": "thread",
    "blog": "essay",
    "newsletter": "essay",
    "reddit": "post",
    "hn": "post",
    "discord": "post",
}

#: The source types the typed registry accepts (ADR-0082 D410).
SOURCE_TYPES: frozenset[str] = frozenset({"codebase", "paper_feed"})

#: The salience selectors a ``codebase`` source can name. ``shipped_feature`` is
#: the ONE genuinely-new primitive in this milestone (most commits are not
#: content). The analog, over diffs, of ScholarFeed's ``llm_significance`` over
#: papers.
SALIENCE_SELECTORS: frozenset[str] = frozenset({"shipped_feature"})

#: The content-piece pipeline stages (the ``pipeline_stage:`` frontmatter on a
#: Content note). The review gate is approved -> scheduled (manual, mirroring
#: outreach's drafted -> ready); ``scheduled`` is carried by the approval event's
#: ``scheduled_at`` rather than a distinct stage.
CONTENT_STAGES: tuple[str, ...] = ("drafted", "humanized", "approved", "posted")

#: Event-type -> content stage, for :func:`derived_content_stage`. Rejections +
#: confirmed posts are handled specially in the walk.
_CONTENT_STAGE_BY_EVENT_TYPE: dict[str, str] = {
    "content_drafted": "drafted",
    "content_humanized": "humanized",
    "content_review_approved": "approved",
}

#: Stage rank for the rollup (later/higher wins).
_STAGE_RANK: dict[str, int] = {s: i for i, s in enumerate(CONTENT_STAGES)}

#: The marker stamped on every event this module builds (ADR-0010 D17
#: raw-primitive-factory convention).
EMITTED_BY: str = "content"


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentVariant:
    """One per-channel projection of the canonical (ADR-0082 D407).

    A register-aware re-expression of the canonical's substance, never a byte
    slice of it. ``body_hash`` is the no-double-post guard key (hash of the
    normalized body + channel).
    """

    channel: str
    register: str
    body: str
    scheduled_at: str | None = None  # ISO ts the operator scheduled this for

    @property
    def body_hash(self) -> str:
        return variant_body_hash(self.channel, self.body)


@dataclass(frozen=True)
class ContentPiece:
    """ONE canonical source-of-truth piece + its per-channel projections.

    The ``canonical`` is the long-form substance (the claims, the story); the
    ``variants`` are the spokes. Review the canonical once, glance the
    projections.
    """

    content_id: str
    source_ref: str  # the originating source key (a commit range, an arXiv id)
    topic: str
    canonical: str
    variants: tuple[ContentVariant, ...] = ()

    def variant_for(self, channel: str) -> ContentVariant | None:
        for v in self.variants:
            if v.channel == channel:
                return v
        return None


@dataclass(frozen=True)
class SourceCandidate:
    """One thing a source surfaced as worth drafting (the salience output).

    The generation skill turns a candidate into a :class:`ContentPiece`. Carries
    the hook material (a verbatim, verifiable fact) the draft is built from.
    """

    source_id: str
    kind: str  # member of SOURCE_TYPES
    ref: str  # the candidate key (a commit sha / range, an arXiv id)
    title: str
    summary: str
    salience_reason: str
    registers: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Typed source registry (ADR-0082 D410) - the operator's easy-config surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodebaseSource:
    """A ``codebase`` source: announce-worthy feature ships from a repo."""

    source_id: str
    repo: Path
    salience: str  # member of SALIENCE_SELECTORS
    since: str  # the commit-range anchor (a git ref, or "last_post")
    registers: tuple[str, ...]
    kind: str = "codebase"


@dataclass(frozen=True)
class PaperFeedSource:
    """A ``paper_feed`` source: new / high-ranked papers via the ScholarFeed MCP.

    The "salience" is just a filter the MCP already exposes, so this adapter is
    mostly wiring (the codebase salience selector is the net-new primitive).
    """

    source_id: str
    provider: str
    min_rank: float
    max_age_days: int
    topics: tuple[str, ...]
    registers: tuple[str, ...]
    kind: str = "paper_feed"


ContentSource = CodebaseSource | PaperFeedSource


def content_sources_from_config(block: object) -> list[ContentSource]:
    """Parse ``content.sources`` into typed sources (ADR-0082 D410).

    Refuse-loud on malformed input (the refuse-don't-guess discipline): an
    unknown source ``type``, a bad salience selector, or a bad register raises
    :class:`ValueError` rather than silently drafting from a misconfigured
    source. ``None`` / an empty list yields ``[]`` (no sources configured).
    """
    if block is None:
        return []
    if not isinstance(block, (list, tuple)):
        raise ValueError(
            f"content.sources must be a list, got {type(block).__name__}"
        )
    out: list[ContentSource] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(block):
        if not isinstance(raw, dict):
            raise ValueError(f"content.sources[{i}] must be a mapping, got {raw!r}")
        sid = raw.get("id")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"content.sources[{i}] is missing a string 'id'")
        if sid in seen_ids:
            raise ValueError(f"content.sources[{i}] duplicate id {sid!r}")
        seen_ids.add(sid)
        stype = raw.get("type")
        if stype not in SOURCE_TYPES:
            raise ValueError(
                f"content.sources[{i}] type must be one of {sorted(SOURCE_TYPES)!r}, "
                f"got {stype!r}"
            )
        registers = _parse_registers(raw.get("registers"), where=f"content.sources[{i}]")
        if stype == "codebase":
            out.append(_parse_codebase_source(sid, raw, registers, i))
        else:
            out.append(_parse_paper_feed_source(sid, raw, registers, i))
    return out


def _parse_registers(raw: object, *, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{where}.registers must be a list, got {type(raw).__name__}")
    bad = [r for r in raw if r not in CONTENT_REGISTERS and r not in POST_CHANNELS]
    if bad:
        raise ValueError(
            f"{where}.registers has unknown entr(ies) {bad!r}; allowed registers "
            f"{sorted(CONTENT_REGISTERS)!r} or channels {sorted(POST_CHANNELS)!r}"
        )
    return tuple(raw)


def _parse_codebase_source(
    sid: str, raw: dict, registers: tuple[str, ...], i: int,
) -> CodebaseSource:
    repo = raw.get("repo")
    if not isinstance(repo, str) or not repo:
        raise ValueError(f"content.sources[{i}] (codebase) needs a string 'repo' path")
    salience = raw.get("salience", "shipped_feature")
    if salience not in SALIENCE_SELECTORS:
        raise ValueError(
            f"content.sources[{i}] salience must be one of "
            f"{sorted(SALIENCE_SELECTORS)!r}, got {salience!r}"
        )
    since = raw.get("since", "last_post")
    if not isinstance(since, str) or not since:
        raise ValueError(f"content.sources[{i}] (codebase) 'since' must be a string")
    return CodebaseSource(
        source_id=sid,
        repo=Path(repo).expanduser(),
        salience=salience,
        since=since,
        registers=registers,
    )


def _parse_paper_feed_source(
    sid: str, raw: dict, registers: tuple[str, ...], i: int,
) -> PaperFeedSource:
    provider = raw.get("provider", "scholarfeed_mcp")
    if not isinstance(provider, str) or not provider:
        raise ValueError(f"content.sources[{i}] (paper_feed) 'provider' must be a string")
    flt = raw.get("filter") or {}
    if not isinstance(flt, dict):
        raise ValueError(f"content.sources[{i}] (paper_feed) 'filter' must be a mapping")
    try:
        min_rank = float(flt.get("min_rank", 0.0))
    except (TypeError, ValueError):
        raise ValueError(f"content.sources[{i}] filter.min_rank must be a number")
    if not 0.0 <= min_rank <= 1.0:
        raise ValueError(
            f"content.sources[{i}] filter.min_rank must be in [0, 1], got {min_rank}"
        )
    try:
        max_age_days = int(flt.get("max_age_days", 7))
    except (TypeError, ValueError):
        raise ValueError(f"content.sources[{i}] filter.max_age_days must be an int")
    if max_age_days < 1:
        raise ValueError(
            f"content.sources[{i}] filter.max_age_days must be >= 1, got {max_age_days}"
        )
    topics_raw = flt.get("topics") or []
    if not isinstance(topics_raw, (list, tuple)):
        raise ValueError(f"content.sources[{i}] filter.topics must be a list")
    return PaperFeedSource(
        source_id=sid,
        provider=provider,
        min_rank=min_rank,
        max_age_days=max_age_days,
        topics=tuple(str(t) for t in topics_raw),
        registers=registers,
    )


# ---------------------------------------------------------------------------
# The codebase salience selector (ADR-0082 D410) - the ONE net-new primitive
# ---------------------------------------------------------------------------

#: Conventional-commit type tokens that signal an announce-worthy ship. A
#: release tag ALWAYS qualifies regardless of type.
DEFAULT_FEATURE_TYPES: frozenset[str] = frozenset({"feat", "feature"})

#: The conventional-commit type prefix, e.g. ``feat(scope): ...`` -> ``feat``.
_CONVENTIONAL_RE = re.compile(r"^([a-z]+)(?:\([^)]*\))?(!)?:\s")


@dataclass(frozen=True)
class CommitCandidate:
    """One announce-worthy commit the salience selector kept."""

    sha: str
    subject: str
    salience_reason: str
    ts: str = ""
    tags: tuple[str, ...] = ()


def _conventional_type(subject: str) -> str | None:
    """Extract the conventional-commit type token, or ``None`` if unconventional.

    ``feat: x`` -> ``feat``; ``fix(api)!: y`` -> ``fix``; ``random subject`` ->
    ``None``.
    """
    m = _CONVENTIONAL_RE.match(subject.strip())
    return m.group(1) if m else None


def select_shipped_features(
    commits: Iterable[dict],
    *,
    feature_types: frozenset[str] = DEFAULT_FEATURE_TYPES,
) -> list[CommitCandidate]:
    """The salience selector: which commits are announce-worthy (ADR-0082 D410).

    PURE function over a list of commit dicts (``{sha, subject, body?, tags?,
    ts?}``). A commit is announce-worthy when EITHER it carries a release tag OR
    its subject is a conventional-commit of a ``feature_types`` type. Everything
    else (chore / docs / test / ci / refactor / style / build / perf / fix /
    revert / unconventional noise) is dropped. Most commits are not content; this
    is the diff-side analog of ScholarFeed's ``llm_significance`` over papers.

    Deterministic + side-effect-free, so it is unit-testable in isolation; the
    git plumbing that produces ``commits`` lives in :func:`git_commits_since`.
    """
    out: list[CommitCandidate] = []
    for c in commits:
        sha = str(c.get("sha", "")).strip()
        subject = str(c.get("subject", "")).strip()
        if not sha or not subject:
            continue
        tags = tuple(str(t) for t in (c.get("tags") or []) if str(t).strip())
        ts = str(c.get("ts", ""))
        if tags:
            out.append(
                CommitCandidate(
                    sha=sha,
                    subject=subject,
                    salience_reason=f"release tag {tags[0]}",
                    ts=ts,
                    tags=tags,
                )
            )
            continue
        ctype = _conventional_type(subject)
        if ctype is not None and ctype in feature_types:
            out.append(
                CommitCandidate(
                    sha=sha,
                    subject=subject,
                    salience_reason=f"{ctype}: feature ship",
                    ts=ts,
                    tags=tags,
                )
            )
    return out


def git_commits_since(repo: Path, since: str) -> list[dict]:
    """Read commits in ``repo`` since the ``since`` ref (the impure plumbing).

    Defensive: returns ``[]`` if ``repo`` is not a git repo or git is missing,
    so a misconfigured source degrades to "no candidates" rather than raising.
    The pure salience selector (:func:`select_shipped_features`) is the tested
    core; this thin shell is integration-covered.
    """
    if since == "last_post":
        # No anchor resolution in Phase 1: the caller resolves "last_post" from
        # the ledger before calling. Fall back to the last 20 commits.
        rev_range = "-n", "20"
    else:
        rev_range = (f"{since}..HEAD",)
    fmt = "%H%x1f%s%x1f%cI%x1f%D"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "log", f"--pretty=format:{fmt}", *rev_range],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    commits: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) < 3:
            continue
        sha, subject, cts = parts[0], parts[1], parts[2]
        refs = parts[3] if len(parts) > 3 else ""
        tags = [
            r.strip()[5:]
            for r in refs.split(",")
            if r.strip().startswith("tag: ")
        ]
        commits.append({"sha": sha, "subject": subject, "ts": cts, "tags": tags})
    return commits


def filter_papers(
    papers: Iterable[dict],
    *,
    min_rank: float,
    max_age_days: int,
    topics: tuple[str, ...] = (),
    now: datetime,
) -> list[SourceCandidate]:
    """Filter a paper feed to the qualifying candidates (ADR-0082 D410).

    PURE function: keep papers with ``rank >= min_rank`` published within
    ``max_age_days`` of ``now`` (and, if ``topics`` is non-empty, matching at
    least one topic by category or title substring). The ScholarFeed MCP supplies
    ``papers``; this filter is the testable salience for the paper feed.
    """
    cutoff = now - timedelta(days=max_age_days)
    topics_lower = tuple(t.lower() for t in topics)
    out: list[SourceCandidate] = []
    for p in papers:
        try:
            rank = float(p.get("rank", p.get("llm_rank", 0.0)))
        except (TypeError, ValueError):
            rank = 0.0
        if rank < min_rank:
            continue
        pub = _parse_iso(p.get("published") or p.get("date") or p.get("ts"))
        if pub is not None and pub < cutoff:
            continue
        if topics_lower:
            hay = (
                str(p.get("title", "")).lower()
                + " "
                + " ".join(str(c).lower() for c in (p.get("categories") or []))
            )
            if not any(t in hay for t in topics_lower):
                continue
        arxiv_id = str(p.get("arxiv_id", p.get("id", ""))).strip()
        out.append(
            SourceCandidate(
                source_id="paper_feed",
                kind="paper_feed",
                ref=arxiv_id,
                title=str(p.get("title", "")).strip(),
                summary=str(p.get("llm_summary", p.get("summary", ""))).strip(),
                salience_reason=f"rank {rank:.2f}"
                + (f", topics {list(topics)}" if topics else ""),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Hub-and-spoke adaptation guard (ADR-0082 D407 + D411(3))
# ---------------------------------------------------------------------------


def _normalize_body(s: str) -> str:
    """Collapse whitespace + lowercase for body comparison."""
    return re.sub(r"\s+", " ", s or "").strip().lower()


def variant_body_hash(channel: str, body: str) -> str:
    """The no-double-post guard key: sha256 of the normalized body + channel."""
    h = hashlib.sha256()
    h.update(channel.encode("utf-8"))
    h.update(b"\x1f")
    h.update(_normalize_body(body).encode("utf-8"))
    return f"sha256:{h.hexdigest()}"


def is_mechanical_truncation(canonical: str, variant_body: str) -> bool:
    """True if ``variant_body`` is a byte-clip of ``canonical`` (a prefix).

    Catches the cross-post-bot failure mode: a variant that is just the
    canonical's first N characters rather than a register-aware re-expression. A
    legitimately shorter variant re-words the substance; it does not start as a
    literal prefix of the canonical.
    """
    nv = _normalize_body(variant_body)
    nc = _normalize_body(canonical)
    if not nv or not nc:
        return False
    if nv == nc:
        return True
    # A short variant that is a literal leading slice of the canonical.
    return len(nv) < len(nc) and nc.startswith(nv)


def validate_adaptation(piece: ContentPiece) -> None:
    """Refuse identical or mechanically-truncated cross-posting (ADR-0082 D407).

    Raises :class:`ValueError` if two variants share a normalized body, or if any
    variant is a mechanical truncation of the canonical. The generation skill +
    the binding adaptation-refusal test call this; it is the STRUCTURAL guarantee
    that "Claude as CMO" does not degrade into a cross-post bot.
    """
    seen: dict[str, str] = {}
    for v in piece.variants:
        if v.channel not in POST_CHANNELS:
            raise ValueError(
                f"variant channel {v.channel!r} not in POST_CHANNELS "
                f"{sorted(POST_CHANNELS)!r}"
            )
        if v.register not in CONTENT_REGISTERS:
            raise ValueError(
                f"variant register {v.register!r} not in CONTENT_REGISTERS "
                f"{sorted(CONTENT_REGISTERS)!r}"
            )
        norm = _normalize_body(v.body)
        if not norm:
            raise ValueError(f"variant for {v.channel!r} has an empty body")
        if norm in seen:
            raise ValueError(
                f"identical cross-post: {v.channel!r} and {seen[norm]!r} share the "
                f"same body. Each channel must be a register-aware re-expression, "
                f"not the same text."
            )
        seen[norm] = v.channel
        if is_mechanical_truncation(piece.canonical, v.body):
            raise ValueError(
                f"variant for {v.channel!r} is a mechanical truncation of the "
                f"canonical. A spoke re-expresses the substance in the channel's "
                f"voice; it is not the canonical's first N characters."
            )


# ---------------------------------------------------------------------------
# Refuse-loud event builders (ADR-0010 D17; _emitted_by="content")
# ---------------------------------------------------------------------------


def _require(value: object, name: str) -> None:
    if not value:
        raise ValueError(f"{name} required")


def _require_channel(channel: str) -> None:
    if channel not in POST_CHANNELS:
        raise ValueError(
            f"channel must be one of {sorted(POST_CHANNELS)!r}, got {channel!r}"
        )


def build_content_drafted_payload(*, content_id: str, source_ref: str, topic: str) -> dict:
    """Piece-level marker: the canonical was drafted. Caller sets ``type``."""
    _require(content_id, "content_id")
    _require(source_ref, "source_ref")
    return {
        "content_id": content_id,
        "source_ref": source_ref,
        "topic": topic or "",
        "channel": None,  # piece-level per ADR-0014 D33 (no channel yet)
        "_emitted_by": EMITTED_BY,
    }


def build_content_humanized_payload(*, content_id: str) -> dict:
    """Piece-level marker: the variants were humanized per spoke."""
    _require(content_id, "content_id")
    return {"content_id": content_id, "channel": None, "_emitted_by": EMITTED_BY}


def build_content_review_approved_payload(
    *, content_id: str, channel: str, scheduled_at: str, body_hash: str, register: str,
) -> dict:
    """Per-channel review gate pass + schedule (the manual gate, ADR-0082 D411).

    Carries the ``scheduled_at`` the scheduler reads to decide DUE, the
    ``body_hash`` the no-double-post guard reads, and the ``register``.
    """
    _require(content_id, "content_id")
    _require_channel(channel)
    _require(scheduled_at, "scheduled_at")
    _require(body_hash, "body_hash")
    if register not in CONTENT_REGISTERS:
        raise ValueError(
            f"register must be one of {sorted(CONTENT_REGISTERS)!r}, got {register!r}"
        )
    return {
        "content_id": content_id,
        "channel": channel,
        "scheduled_at": scheduled_at,
        "body_hash": body_hash,
        "register": register,
        "_emitted_by": EMITTED_BY,
    }


def build_content_review_rejected_payload(
    *, content_id: str, channel: str, reason: str,
) -> dict:
    """Per-channel review gate reject (sends the piece back to drafting)."""
    _require(content_id, "content_id")
    _require_channel(channel)
    return {
        "content_id": content_id,
        "channel": channel,
        "reason": reason or "",
        "_emitted_by": EMITTED_BY,
    }


def build_distribution_intent_payload(
    *, content_id: str, channel: str, intent_id: str, body_hash: str,
) -> dict:
    """Two-phase commit phase 1 (Phase 2 dispatcher writes this)."""
    _require(content_id, "content_id")
    _require_channel(channel)
    _require(intent_id, "intent_id")
    _require(body_hash, "body_hash")
    return {
        "content_id": content_id,
        "channel": channel,
        "intent_id": intent_id,
        "body_hash": body_hash,
        "_emitted_by": EMITTED_BY,
    }


def build_distribution_confirmed_payload(
    *, content_id: str, channel: str, intent_id: str, post_id: str, body_hash: str,
) -> dict:
    """Two-phase commit phase 2: the post landed; ``post_id`` is the read-back key.

    Carries ``body_hash`` (ADR-0082 D416) so the no-double-post guard reads the
    posted variant's hash directly off the confirmed event without an
    intent-join.
    """
    _require(content_id, "content_id")
    _require_channel(channel)
    _require(intent_id, "intent_id")
    _require(post_id, "post_id")
    _require(body_hash, "body_hash")
    return {
        "content_id": content_id,
        "channel": channel,
        "intent_id": intent_id,
        "post_id": post_id,
        "body_hash": body_hash,
        "_emitted_by": EMITTED_BY,
    }


def build_distribution_failed_payload(
    *, content_id: str, channel: str, intent_id: str, error_class: str, error_message: str,
) -> dict:
    """Two-phase commit failure outcome."""
    _require(content_id, "content_id")
    _require_channel(channel)
    _require(intent_id, "intent_id")
    return {
        "content_id": content_id,
        "channel": channel,
        "intent_id": intent_id,
        "error_class": error_class or "",
        "error_message": error_message or "",
        "_emitted_by": EMITTED_BY,
    }


def build_engagement_observed_payload(
    *, content_id: str, channel: str, metrics: dict, observed_at: str,
) -> dict:
    """Per-piece per-channel engagement at a ts (the feedback loop, ADR-0082 D409).

    ``metrics`` is whatever the channel exposes (likes / reshares / comments /
    impressions). Best-effort: a channel with no readable signal simply never
    emits this, and the report says "no signal" rather than guessing.

    DELTA semantics (ADR-0082 D416): the metrics here are the DELTA since the
    last observation, NOT a cumulative snapshot. ``build_content_report`` SUMS
    ``engagement_observed`` metrics, so re-polling a post and emitting cumulative
    snapshots would double-count. The ingest pass computes the delta with
    :func:`compute_engagement_delta` before emitting; summing the deltas
    reconstructs the cumulative total. Metric values must be non-negative ints.
    """
    _require(content_id, "content_id")
    _require_channel(channel)
    _require(observed_at, "observed_at")
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be a mapping")
    for k, v in metrics.items():
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ValueError(
                f"engagement metric {k!r} must be a non-negative int delta, got {v!r}"
            )
    return {
        "content_id": content_id,
        "channel": channel,
        "metrics": dict(metrics),
        "observed_at": observed_at,
        "_emitted_by": EMITTED_BY,
    }


def prior_engagement(
    events: Iterable[object], content_id: str, channel: str,
) -> dict[str, int]:
    """Sum prior ``engagement_observed`` deltas for a (content_id, channel).

    The cumulative total observed so far, reconstructed from the ledger (the
    source of truth, no state outside it). The ingest pass subtracts this from a
    fresh cumulative scrape to get the next delta (:func:`compute_engagement_delta`).
    """
    totals: dict[str, int] = {}
    for raw in events:
        ev = _coerce_event(raw)
        if ev.get("type") != "engagement_observed":
            continue
        if ev.get("content_id") != content_id or ev.get("channel") != channel:
            continue
        for k, v in (ev.get("metrics") or {}).items():
            try:
                totals[str(k)] = totals.get(str(k), 0) + int(v)
            except (TypeError, ValueError):
                continue
    return totals


def compute_engagement_delta(
    events: Iterable[object],
    content_id: str,
    channel: str,
    scraped_metrics: dict,
) -> dict[str, int]:
    """The non-negative per-metric delta to emit given a fresh CUMULATIVE scrape.

    ``scraped_metrics`` is the current cumulative count from the channel (e.g.
    the post now shows 37 likes). Returns ``current - prior`` per metric, floored
    at 0 (counts only go up; a lower scrape is a transient read error, not a
    negative delta). Metrics whose delta is 0 are dropped (no-op observation).
    Emitting this delta keeps the SUM-based report's cumulative correct.
    """
    prior = prior_engagement(events, content_id, channel)
    delta: dict[str, int] = {}
    for k, v in (scraped_metrics or {}).items():
        try:
            cur = int(v)
        except (TypeError, ValueError):
            continue
        d = cur - prior.get(str(k), 0)
        if d > 0:
            delta[str(k)] = d
    return delta


# ---------------------------------------------------------------------------
# Read-only derived-state walk (the entity owns its own stage walk)
# ---------------------------------------------------------------------------


def _coerce_event(ev: object) -> dict:
    """Accept either a raw event dict or a :class:`ledger.Event`."""
    if hasattr(ev, "to_dict"):
        return ev.to_dict()  # type: ignore[attr-defined]
    return dict(ev)  # type: ignore[arg-type]


def _parse_iso(s: object) -> datetime | None:
    """Parse an ISO-8601 ts; ``None`` on missing/malformed input (UTC-promoted)."""
    if not isinstance(s, str) or not s:
        return None
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def derived_content_stage(events: Iterable[object], content_id: str) -> str | None:
    """Replay the content lifecycle for ``content_id`` -> current stage.

    The content-piece analog of :meth:`ledger.Ledger.derived_stage`. Returns the
    highest-rank stage reached: ``drafted`` < ``humanized`` < ``approved`` <
    ``posted``. A confirmed post on ANY channel is terminal (``posted``); a
    rejection with no later approval drops the piece back to ``drafted``. Returns
    ``None`` when the content_id is unseen. Read-only.
    """
    stage: str | None = None
    any_approved = False
    any_rejected_after_approval = False
    posted = False
    for raw in events:
        ev = _coerce_event(raw)
        if ev.get("content_id") != content_id:
            continue
        t = ev.get("type")
        if t == "distribution_confirmed":
            posted = True
        elif t == "content_review_approved":
            any_approved = True
            any_rejected_after_approval = False
        elif t == "content_review_rejected":
            if not any_approved:
                any_rejected_after_approval = True
        mapped = _CONTENT_STAGE_BY_EVENT_TYPE.get(t)
        if mapped is not None and (
            stage is None or _STAGE_RANK[mapped] > _STAGE_RANK.get(stage, -1)
        ):
            stage = mapped
    if posted:
        return "posted"
    if stage is None:
        return None
    if any_rejected_after_approval and stage == "drafted":
        return "drafted"
    return stage


def new_content_id() -> str:
    """A sortable, collision-resistant content-piece id (``cpc_<ULID>``)."""
    return _ledger.new_intent_id(prefix="cpc_")


def new_distribution_intent_id() -> str:
    """A sortable two-phase distribution intent id (``cont_<ULID>``)."""
    return _ledger.new_intent_id(prefix="cont_")


__all__ = [
    "AUTO_CHANNELS",
    "CHANNEL_DEFAULT_REGISTER",
    "COMMUNITY_CHANNELS",
    "CONTENT_NEW_EVENT_CLASSES",
    "CONTENT_REGISTERS",
    "CONTENT_STAGES",
    "CodebaseSource",
    "CommitCandidate",
    "ContentPiece",
    "ContentSource",
    "ContentVariant",
    "DEFAULT_FEATURE_TYPES",
    "EMITTED_BY",
    "OWNED_CHANNELS",
    "POST_CHANNELS",
    "PaperFeedSource",
    "SALIENCE_SELECTORS",
    "SOURCE_TYPES",
    "SourceCandidate",
    "build_content_drafted_payload",
    "build_content_humanized_payload",
    "build_content_review_approved_payload",
    "build_content_review_rejected_payload",
    "build_distribution_confirmed_payload",
    "build_distribution_failed_payload",
    "build_distribution_intent_payload",
    "build_engagement_observed_payload",
    "compute_engagement_delta",
    "content_sources_from_config",
    "derived_content_stage",
    "filter_papers",
    "prior_engagement",
    "git_commits_since",
    "is_mechanical_truncation",
    "new_content_id",
    "new_distribution_intent_id",
    "select_shipped_features",
    "validate_adaptation",
    "variant_body_hash",
]
