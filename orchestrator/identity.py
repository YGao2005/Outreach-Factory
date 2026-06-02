"""Identity layer for the outreach-factory pipeline.

Replaces the brittle name-only dedup in state_machine.find_person_note with
a multi-key identity-graph match. Every Person note carries an `identity_keys`
block in frontmatter; matching is on stable identifiers (LinkedIn slug, email,
GitHub handle, Twitter handle), not display name.

Strict resolution policy (2026-05-15):
    0 candidates  -> new person, mint ID
    1 candidate   -> confident match, return existing
    2+ candidates -> conflict, refuse to enroll, write conflict report,
                     surface for manual resolution

Falsely merging two distinct people is catastrophic for cold outreach
(wrong personalization, possible legal/reputation damage); missing a merge
just costs one duplicate enrollment that the user catches at draft review.
Asymmetric cost -> strict policy.

CLI:

    python identity.py compute      --name <n> [--linkedin <url>] [--email <addr> ...] \\
                                    [--github <h>] [--twitter <h>]
    python identity.py find-matches --linkedin <url> | --email <addr> | --github <h> | --twitter <h>
    python identity.py resolve      [same flags as find-matches; plus optional --name]
    python identity.py read         --path <person_note.md>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityKeys:
    """Normalized identifiers for one person.

    All string fields are normalized at construction (see `compute_keys`).
    `emails` and `alt_names` are frozensets so equality is order-independent.

    The `country` field is the recipient-country signal that drives
    Pillar A Week 3 sending-window timezone inference (ADR-0005).
    It is NOT a match key — two records sharing a country do not match
    on identity. It's stored on `IdentityKeys` only so the gate's
    `identity.read_person_keys` call surfaces it alongside the other
    person-shaped data without a second I/O pass. Free-form string;
    the consumer (`orchestrator.policy.tz_inference`) handles
    normalization.
    """

    linkedin: str | None = None              # e.g. "in/dylan-txa"
    emails: frozenset[str] = frozenset()
    github: str | None = None
    twitter: str | None = None
    alt_names: frozenset[str] = frozenset()  # normalized lowercase, diacritic-stripped
    country: str | None = None               # ADR-0005; not a match key

    def is_empty(self) -> bool:
        return not (self.linkedin or self.emails or self.github or self.twitter)

    def has_strong_key(self) -> bool:
        """A 'strong' key is one stable enough to mint a non-tmp ID from."""
        return bool(self.linkedin) or bool(self.emails)

    def to_serializable(self) -> dict:
        return {
            "linkedin": self.linkedin,
            "emails": sorted(self.emails),
            "github": self.github,
            "twitter": self.twitter,
            "alt_names": sorted(self.alt_names),
            "country": self.country,
        }


@dataclass(frozen=True)
class Match:
    """A Person note whose identity_keys intersect the candidate's."""

    note_path: Path
    person_id: str
    matched_classes: frozenset[str]   # subset of {"linkedin","email","github","twitter"}
    matched_values: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Conflict:
    """Strict-policy refusal: 2+ existing Person notes match the candidate."""

    candidate_keys: IdentityKeys
    matches: list[Match]
    report_path: Path


@dataclass
class IndexEntry:
    """One row of a pre-built people-dir index. Used by backfill (O(N) reads)
    so we don't re-walk the vault per candidate (O(N²))."""

    note_path: Path
    person_id: str | None
    keys: IdentityKeys


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


_LINKEDIN_URL_RE = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(in|pub|company)/([^/?#\s]+)",
    re.IGNORECASE,
)

_GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([^/?#\s]+)", re.IGNORECASE
)

_TWITTER_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([^/?#\s]+)", re.IGNORECASE
)

# RFC 5322 is famously gnarly; we use a permissive practical check.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _normalize_linkedin(value: str | None) -> str | None:
    """Returns 'in/<slug>' or 'company/<slug>' (lowercased), or None.

    We deliberately keep the 'in/' vs 'company/' prefix so a personal profile
    can never match a company page on the same slug (rare but possible).

    Emits a stderr warning when the input *looks* LinkedIn-shaped (contains
    'linkedin.com' or 'linkedin') but doesn't parse — silently dropping a
    presumed identifier creates a missed-dedup hazard (a candidate with a
    malformed scraped URL would fall through to -em/-tmp ID and never match
    an existing record that had a valid LinkedIn). Discovery skills should
    surface this so the scraper can be fixed.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    m = _LINKEDIN_URL_RE.search(raw)
    if m:
        kind = m.group(1).lower()
        slug = m.group(2).strip().lower().rstrip("/")
        # 'pub' is an old LinkedIn URL format; treat as 'in'.
        if kind == "pub":
            kind = "in"
        return f"{kind}/{slug}"
    # Raw slug (no URL chrome) — assume person profile.
    s = raw.lower().strip("/")
    if "/" in s:
        # Already has a kind prefix?
        prefix, _, rest = s.partition("/")
        if prefix in ("in", "company"):
            return f"{prefix}/{rest.split('/')[0]}"
        # Unknown shape — refuse rather than guess wrong, but surface it.
        if "linkedin" in raw.lower():
            print(
                f"identity._normalize_linkedin: dropping LinkedIn-shaped input "
                f"that didn't parse: {value!r}",
                file=sys.stderr,
            )
        return None
    # Bare slug — assume person.
    return f"in/{s}"


def _normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    s = value.strip().lower()
    if not s or not _EMAIL_RE.match(s):
        return None
    return s


def _normalize_github(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    m = _GITHUB_URL_RE.search(raw)
    if m:
        return m.group(1).strip().lower().rstrip("/")
    return raw.lstrip("@").lower().strip("/") or None


def _normalize_twitter(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    m = _TWITTER_URL_RE.search(raw)
    if m:
        return m.group(1).strip().lower().rstrip("/")
    return raw.lstrip("@").lower().strip("/") or None


def _normalize_alt_name(value: str) -> str:
    """NFC-normalize, strip diacritics, lowercase, collapse whitespace.

    Used only for the alt_names set — not for matching primary identity
    (names are too unstable). alt_names exist mainly for diagnostic context
    in conflict reports, not as a load-bearing match key.
    """
    s = unicodedata.normalize("NFKD", value or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _normalize_emails(values: Iterable[str] | None) -> frozenset[str]:
    if not values:
        return frozenset()
    out: set[str] = set()
    for v in values:
        ne = _normalize_email(v)
        if ne:
            out.add(ne)
    return frozenset(out)


def _normalize_alt_names(values: Iterable[str] | None) -> frozenset[str]:
    if not values:
        return frozenset()
    out: set[str] = set()
    for v in values:
        na = _normalize_alt_name(v)
        if na:
            out.add(na)
    return frozenset(out)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def compute_keys(
    *,
    name: str | None = None,
    email: str | None = None,
    emails: Iterable[str] | None = None,
    linkedin_url: str | None = None,
    github: str | None = None,
    twitter: str | None = None,
    alt_names: Iterable[str] | None = None,
    country: str | None = None,
) -> IdentityKeys:
    """Single entry point: raw inputs in, normalized IdentityKeys out.

    `email` (singular) and `emails` (plural) are both accepted and unioned;
    discovery skills tend to pass one, backfill paths pass many.

    `name` is folded into `alt_names` (alongside any extra alt_names passed)
    so the conflict-report diagnostic has it available without needing a
    separate field.

    `country` is stored verbatim (after strip) — normalization happens at
    the consumer (`tz_inference.infer_timezone`) since the same field is
    consumed by multiple lookups (alpha-2 code, full name, "City, Country"
    parsing). Storing the normalized form here would lose information.
    """
    all_emails: list[str] = []
    if email:
        all_emails.append(email)
    if emails:
        all_emails.extend(emails)

    all_names: list[str] = []
    if name:
        all_names.append(name)
    if alt_names:
        all_names.extend(alt_names)

    country_norm = country.strip() if isinstance(country, str) else None
    if not country_norm:
        country_norm = None

    return IdentityKeys(
        linkedin=_normalize_linkedin(linkedin_url),
        emails=_normalize_emails(all_emails),
        github=_normalize_github(github),
        twitter=_normalize_twitter(twitter),
        alt_names=_normalize_alt_names(all_names),
        country=country_norm,
    )


# ---------------------------------------------------------------------------
# Intersection
# ---------------------------------------------------------------------------


def keys_intersect(a: IdentityKeys, b: IdentityKeys) -> frozenset[str]:
    """Returns the set of matching key classes between two IdentityKeys.

    Classes are: 'linkedin', 'email', 'github', 'twitter'.
    `alt_names` is NOT a match class — names are too unstable for dedup.
    """
    matched: set[str] = set()
    if a.linkedin and b.linkedin and a.linkedin == b.linkedin:
        matched.add("linkedin")
    if a.emails and b.emails and (a.emails & b.emails):
        matched.add("email")
    if a.github and b.github and a.github == b.github:
        matched.add("github")
    if a.twitter and b.twitter and a.twitter == b.twitter:
        matched.add("twitter")
    return frozenset(matched)


def keys_intersect_detail(a: IdentityKeys, b: IdentityKeys) -> dict[str, list[str]]:
    """Like keys_intersect but returns the actual matching values per class.

    Used in conflict reports for diagnostic context.
    """
    detail: dict[str, list[str]] = {}
    if a.linkedin and b.linkedin and a.linkedin == b.linkedin:
        detail["linkedin"] = [a.linkedin]
    inter = a.emails & b.emails if (a.emails and b.emails) else frozenset()
    if inter:
        detail["email"] = sorted(inter)
    if a.github and b.github and a.github == b.github:
        detail["github"] = [a.github]
    if a.twitter and b.twitter and a.twitter == b.twitter:
        detail["twitter"] = [a.twitter]
    return detail


# ---------------------------------------------------------------------------
# ID minting
# ---------------------------------------------------------------------------


_SLUG_SAFE_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    s = _normalize_alt_name(value)
    s = _SLUG_SAFE_RE.sub("-", s).strip("-")
    return s or "unknown"


def mint_id(
    keys: IdentityKeys,
    *,
    name_fallback: str | None = None,
    company_slug: str | None = None,
    year: int | None = None,
) -> str:
    """Deterministic ID with provenance suffix.

      <slug>-li             when LinkedIn slug present
      <sha256(email)[:12]>-em   when no LinkedIn but verified email
      <name>-<company>-<yyyy>-tmp   otherwise (cannot pass send gate)

    The suffix lets a reader tell at a glance how confident the identity is.
    A `-tmp` ID requires an identity upgrade (via /research-prospect populating
    email or LinkedIn) before any send can proceed.
    """
    if keys.linkedin:
        # LinkedIn slug like "in/dylan-txa" -> "dylan-txa-li"
        slug = keys.linkedin.split("/", 1)[-1]
        return f"{_slugify(slug)}-li"

    if keys.emails:
        # Sort for determinism — same email set always mints same ID.
        primary_email = sorted(keys.emails)[0]
        h = hashlib.sha256(primary_email.encode("utf-8")).hexdigest()[:12]
        return f"{h}-em"

    # Fallback: name + company + year. Marked -tmp; gates check this suffix.
    # The year part alone is NOT considered identifying — it would make every
    # 2026 unknown collide. Year is appended only when name/company are present.
    name_part = _slugify(name_fallback or "")
    company_part = _slugify(company_slug or "")
    year_part = str(year or datetime.now(timezone.utc).year)
    identifying = [p for p in (name_part, company_part) if p and p != "unknown"]
    if not identifying:
        # Truly nothing identifying — timestamp ensures uniqueness while
        # making it obvious in the ledger that this record needs upgrading.
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"unknown-{ts}-tmp"
    return f"{'-'.join(identifying + [year_part])}-tmp"


def id_is_temporary(person_id: str | None) -> bool:
    return bool(person_id) and person_id.endswith("-tmp")


def id_is_strong(person_id: str | None) -> bool:
    return bool(person_id) and (person_id.endswith("-li") or person_id.endswith("-em"))


# ---------------------------------------------------------------------------
# Reading Person notes
# ---------------------------------------------------------------------------


def _parse_frontmatter(note_path: Path) -> dict | None:
    try:
        text = note_path.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:end].lstrip("\n"))
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _coerce_email_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Single email string — possibly empty.
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return []


def read_person_keys(note_path: Path) -> tuple[str | None, IdentityKeys] | None:
    """Parse identity from a Person note.

    Returns (person_id, IdentityKeys) on success, or None if the file isn't
    a person note (missing frontmatter, wrong type, etc.).

    Prefers the new `identity_keys:` block. Falls back to legacy top-level
    fields (linkedin:, email:) so existing notes work before migration.
    """
    fm = _parse_frontmatter(note_path)
    if not fm:
        return None
    if (fm.get("type") or "").strip() != "person":
        return None

    person_id: str | None = fm.get("id") or None
    name: str = (fm.get("name") or note_path.stem or "").strip()

    # Country signal precedence (ADR-0005):
    #   1. identity_keys.country (the canonical source going forward).
    #   2. Top-level `location:` — accepts both string form ("City, Country")
    #      and dict form ({city, country}). Most existing Person notes
    #      store location as a string (per skills/research-prospect SKILL.md
    #      schema); we tolerate both shapes so a backfill into structured
    #      form (Pillar E) can happen without changing this reader.
    # The signal is stored verbatim (post-strip) here; `tz_inference`
    # normalizes at the consumer.
    country: str | None = None
    ik_block = fm.get("identity_keys") or {}
    if isinstance(ik_block, dict) and ik_block.get("country"):
        country = str(ik_block["country"]).strip() or None
    if country is None:
        loc = fm.get("location")
        if isinstance(loc, str):
            country = loc.strip() or None
        elif isinstance(loc, dict):
            c = loc.get("country")
            if c:
                country = str(c).strip() or None

    if isinstance(ik_block, dict) and ik_block:
        keys = compute_keys(
            name=name,
            emails=_coerce_email_list(ik_block.get("emails")),
            linkedin_url=ik_block.get("linkedin"),
            github=ik_block.get("github"),
            twitter=ik_block.get("twitter"),
            alt_names=ik_block.get("alt_names") or [],
            country=country,
        )
    else:
        # Legacy fallback: use top-level fields.
        keys = compute_keys(
            name=name,
            email=fm.get("email"),
            linkedin_url=fm.get("linkedin"),
            github=fm.get("github"),
            twitter=fm.get("twitter"),
            country=country,
        )

    return person_id, keys


# ---------------------------------------------------------------------------
# Indexing + matching
# ---------------------------------------------------------------------------


def build_index(people_dir: Path) -> list[IndexEntry]:
    """Walk the people_dir tree once and return all (path, id, keys).

    Backfill paths build this once and reuse; single-enrollment paths can
    use the convenience find_matches() which builds + queries in one call.
    """
    entries: list[IndexEntry] = []
    for note in sorted(people_dir.rglob("*.md")):
        # Skip hidden / conflict-suffix files (Obsidian Sync writes these).
        rel = note.relative_to(people_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if ".conflicted" in note.name or note.name.endswith(".conflict.md"):
            continue
        parsed = read_person_keys(note)
        if parsed is None:
            continue
        person_id, keys = parsed
        entries.append(IndexEntry(note_path=note.resolve(), person_id=person_id, keys=keys))
    return entries


def find_matches_in_index(
    candidate: IdentityKeys, index: list[IndexEntry]
) -> list[Match]:
    """Return all index entries whose keys intersect the candidate's."""
    out: list[Match] = []
    for entry in index:
        classes = keys_intersect(candidate, entry.keys)
        if not classes:
            continue
        detail = keys_intersect_detail(candidate, entry.keys)
        out.append(
            Match(
                note_path=entry.note_path,
                person_id=entry.person_id or "",
                matched_classes=classes,
                matched_values=detail,
            )
        )
    return out


def find_matches(candidate: IdentityKeys, people_dir: Path) -> list[Match]:
    """Convenience: build_index + find_matches_in_index in one call.

    O(N) per call. For loops over many candidates, prefer build_index + reuse.
    """
    return find_matches_in_index(candidate, build_index(people_dir))


# ---------------------------------------------------------------------------
# Resolution (strict policy)
# ---------------------------------------------------------------------------


def _conflict_report_path(conflicts_dir: Path) -> Path:
    """Unique path per conflict, even when two fire in the same second.

    Uses microsecond precision plus a 4-char random suffix so a parallel
    enrollment burst (two skills enrolling the same conflicting candidate
    simultaneously) cannot clobber reports.
    """
    conflicts_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H-%M-%S")
    micro = f"{now.microsecond:06d}"
    suffix = os.urandom(2).hex()  # 4 hex chars
    return conflicts_dir / f"{ts}-{micro}-{suffix}.yml"


def _write_conflict_report(
    candidate: IdentityKeys,
    matches: list[Match],
    report_path: Path,
    *,
    reason: str,
) -> None:
    body = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "candidate": candidate.to_serializable(),
        "matched_records": [
            {
                "note_path": str(m.note_path),
                "person_id": m.person_id,
                "matched_classes": sorted(m.matched_classes),
                "matched_values": m.matched_values,
            }
            for m in matches
        ],
        # Manual resolution workflow. Merge/split CLI subcommands are planned
        # for Phase 5.5 Week 2; until then, edit the frontmatter directly.
        # Whichever path you take, append a note explaining the decision to
        # the resolved Person note so the audit trail is preserved.
        "how_to_resolve": [
            "Option 1 — SAME PERSON, two notes (most common case):",
            "  a. Pick the canonical Person note (usually the one with more",
            "     pipeline history: filled status, touch records, last_touch date).",
            "  b. Manually copy identity_keys (linkedin / emails / github / twitter)",
            "     from the other note(s) into the canonical note's identity_keys",
            "     block, unioning the values.",
            "  c. Move any unique body content from the other note(s) into the",
            "     canonical note's Notes section.",
            "  d. Delete the other note(s).",
            "",
            "Option 2 — TWO DIFFERENT PEOPLE who share an identifier",
            "          (e.g. shared family/work email, cofounder mailbox):",
            "  a. Identify which Person note legitimately owns the shared key.",
            "  b. Remove the shared key from the other note's identity_keys block.",
            "  c. If the candidate is the legitimately-owning third party,",
            "     allow enrollment to retry (the conflict is resolved once",
            "     the shared key only appears on one existing record).",
            "",
            "Option 3 — CANDIDATE IS WRONG (bad scrape, hallucinated identifier):",
            "  Discard the candidate. No vault change needed.",
            "",
            "After resolving, re-run the discovery skill or enrollment command",
            "that surfaced this conflict — it should now succeed.",
        ],
    }
    report_path.write_text(
        yaml.safe_dump(body, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _is_ambiguous_single_class_email_match(
    candidate: IdentityKeys, match: Match
) -> bool:
    """Strict-policy refinement (2026-05-15):

    A sole `email` match is normally treated as confident — but if the candidate
    has its own LinkedIn that differs from the existing record's LinkedIn, the
    shared email is more likely a shared inbox (family, cofounder, alias) than
    same-person evidence. Escalate to Conflict in that case rather than silently
    absorbing the candidate.

    Returns True if the match should be escalated to Conflict, False otherwise.
    """
    if match.matched_classes != frozenset({"email"}):
        return False
    if not candidate.linkedin:
        return False  # candidate has no LinkedIn to compare against
    existing = read_person_keys(match.note_path)
    if existing is None:
        return False
    _existing_id, existing_keys = existing
    if existing_keys.linkedin and existing_keys.linkedin != candidate.linkedin:
        return True
    return False


def resolve_strict(
    candidate: IdentityKeys,
    matches: list[Match],
    conflicts_dir: Path,
) -> Match | Conflict | None:
    """Apply the strict matching policy.

    Returns:
        None      -> 0 matches: caller should mint a new ID + create note
        Match     -> 1 confident match: caller should treat as existing
        Conflict  -> 2+ matches OR 1 ambiguous single-class-email match;
                     caller MUST refuse to enroll; report written

    Strict-policy refinement for single-class email matches: if the only
    matched class is `email` and the candidate has a LinkedIn that differs
    from the existing record's LinkedIn, escalate to Conflict (shared family
    or work email scenario). See _is_ambiguous_single_class_email_match.
    """
    if not matches:
        return None

    if len(matches) == 1:
        m = matches[0]
        if _is_ambiguous_single_class_email_match(candidate, m):
            report_path = _conflict_report_path(conflicts_dir)
            _write_conflict_report(
                candidate, [m], report_path,
                reason=("single-class email match with distinct LinkedIn — "
                        "shared email is ambiguous; manual resolution required"),
            )
            return Conflict(
                candidate_keys=candidate, matches=[m], report_path=report_path,
            )
        return m

    report_path = _conflict_report_path(conflicts_dir)
    _write_conflict_report(
        candidate, matches, report_path,
        reason=f"{len(matches)} existing Person records match candidate identity keys",
    )
    return Conflict(candidate_keys=candidate, matches=matches, report_path=report_path)


# ---------------------------------------------------------------------------
# Config + defaults
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _vault_people_dir(cfg: dict) -> Path | None:
    v = cfg.get("vault") or {}
    vault_path = Path(os.path.expanduser(v.get("path") or ""))
    if not vault_path.exists():
        return None
    people_dir = vault_path / (v.get("people_dir") or "10 People")
    return people_dir if people_dir.exists() else None


def _default_conflicts_dir() -> Path:
    return Path.home() / ".outreach-factory" / "conflicts"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_keys_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--name", default=None)
    p.add_argument("--linkedin", dest="linkedin_url", default=None)
    p.add_argument("--email", action="append", default=None,
                   help="repeat for multiple emails")
    p.add_argument("--github", default=None)
    p.add_argument("--twitter", default=None)


def _keys_from_args(args) -> IdentityKeys:
    return compute_keys(
        name=args.name,
        emails=args.email,
        linkedin_url=args.linkedin_url,
        github=args.github,
        twitter=args.twitter,
    )


def _match_to_dict(m: Match) -> dict:
    return {
        "note_path": str(m.note_path),
        "person_id": m.person_id,
        "matched_classes": sorted(m.matched_classes),
        "matched_values": m.matched_values,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compute", help="Normalize raw inputs into IdentityKeys")
    _add_keys_args(c)
    c.add_argument("--json", action="store_true")
    c.add_argument("--mint-id", action="store_true",
                   help="Also mint and print the deterministic person_id")
    c.add_argument("--company", default=None, help="for -tmp ID minting only")

    fm = sub.add_parser("find-matches", help="Find Person notes matching given keys")
    _add_keys_args(fm)
    fm.add_argument("--json", action="store_true")

    rs = sub.add_parser("resolve", help="Apply strict policy: None | Match | Conflict")
    _add_keys_args(rs)
    rs.add_argument("--json", action="store_true")
    rs.add_argument("--conflicts-dir", default=None,
                    help="Override default ~/.outreach-factory/conflicts/")

    rd = sub.add_parser("read", help="Parse identity from a Person note")
    rd.add_argument("--path", required=True)
    rd.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "compute":
        keys = _keys_from_args(args)
        out: dict = keys.to_serializable()
        if args.mint_id:
            out["person_id"] = mint_id(keys, name_fallback=args.name,
                                       company_slug=args.company)
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print(yaml.safe_dump(out, sort_keys=False, allow_unicode=True), end="")
        sys.exit(0)

    if args.cmd == "find-matches":
        cfg = _load_config()
        people_dir = _vault_people_dir(cfg)
        if people_dir is None:
            print(json.dumps({"ok": False, "reason": "vault.people_dir not resolvable"}))
            sys.exit(2)
        keys = _keys_from_args(args)
        if keys.is_empty():
            print(json.dumps({"ok": False, "reason": "no identity keys provided"}))
            sys.exit(2)
        matches = find_matches(keys, people_dir)
        result = {
            "ok": True,
            "candidate": keys.to_serializable(),
            "match_count": len(matches),
            "matches": [_match_to_dict(m) for m in matches],
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if not matches:
                print("(no matches)")
            for m in matches:
                classes = ",".join(sorted(m.matched_classes))
                print(f"  {m.person_id or '(no id)'}\t[{classes}]\t{m.note_path}")
        sys.exit(0)

    if args.cmd == "resolve":
        cfg = _load_config()
        people_dir = _vault_people_dir(cfg)
        if people_dir is None:
            print(json.dumps({"ok": False, "reason": "vault.people_dir not resolvable"}))
            sys.exit(2)
        keys = _keys_from_args(args)
        if keys.is_empty():
            print(json.dumps({"ok": False, "reason": "no identity keys provided"}))
            sys.exit(2)
        conflicts_dir = Path(args.conflicts_dir) if args.conflicts_dir else _default_conflicts_dir()
        matches = find_matches(keys, people_dir)
        resolution = resolve_strict(keys, matches, conflicts_dir)
        if resolution is None:
            result = {"ok": True, "resolution": "new",
                      "candidate": keys.to_serializable()}
        elif isinstance(resolution, Match):
            result = {"ok": True, "resolution": "match",
                      "match": _match_to_dict(resolution)}
        else:
            result = {"ok": False, "resolution": "conflict",
                      "report_path": str(resolution.report_path),
                      "match_count": len(resolution.matches),
                      "matches": [_match_to_dict(m) for m in resolution.matches]}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"resolution: {result['resolution']}")
            if result["resolution"] == "match":
                print(f"  matched: {result['match']['note_path']}")
            elif result["resolution"] == "conflict":
                print(f"  report:  {result['report_path']}")
                for m in result["matches"]:
                    classes = ",".join(m["matched_classes"])
                    print(f"  - {m['person_id'] or '(no id)'} [{classes}] {m['note_path']}")
        sys.exit(0 if result["ok"] else 1)

    if args.cmd == "read":
        path = Path(args.path)
        parsed = read_person_keys(path)
        if parsed is None:
            print(json.dumps({"ok": False, "reason": "not a person note or unparseable"}))
            sys.exit(1)
        person_id, keys = parsed
        out = {
            "ok": True,
            "path": str(path),
            "person_id": person_id,
            "keys": keys.to_serializable(),
            "is_temporary": id_is_temporary(person_id),
            "has_strong_key": keys.has_strong_key(),
        }
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print(yaml.safe_dump(out, sort_keys=False, allow_unicode=True), end="")
        sys.exit(0)


if __name__ == "__main__":
    main()
