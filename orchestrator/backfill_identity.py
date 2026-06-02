"""One-time migration: backfill `id` + `identity_keys` blocks on Person notes.

Phase 5.5 Week 1b. Before the identity layer can be load-bearing for send
gates, existing Person notes need explicit identity records. This script
walks the people directory, computes identity keys from current legacy
frontmatter (top-level `linkedin:`, `email:`, etc.), detects dup clusters
via identity-graph intersection, and writes results in two modes:

  - `--dry-run` (default): emit a per-note report + a conflicts file at
    `~/.outreach-factory/migration-conflicts.yml`. No vault mutation.
  - `--apply`: write `id:` + `identity_keys:` blocks into each note's
    frontmatter (surgically, preserving everything else). Refuses to run
    if `migration-conflicts.yml` has unresolved entries.

Resolution workflow:
  1. Run `--dry-run` → review proposed keys + conflicts.
  2. For each conflict cluster: manually merge (copy keys from secondary
     notes into the canonical, delete secondaries) or split (remove the
     shared key from one note). Edit `migration-conflicts.yml` to mark
     each conflict `resolved: true`, OR delete the file entirely once
     all clusters are handled.
  3. Re-run `--dry-run` to confirm conflicts are zero.
  4. Run `--apply` → frontmatter is updated in place.
  5. `--validate` (any time) → assert every Person note has `id` +
     `identity_keys` and no two notes share any strong key.

Insertion strategy: surgical, NOT a yaml round-trip. We parse the
existing frontmatter to read it, then insert two new lines (id +
identity_version) and one new block (identity_keys:) immediately after
the existing `type:` line in the raw text. This preserves quoting style,
field order, comments, and multi-line scalars — important because the reference operator's
Person notes have hand-curated structure that yaml.safe_dump would
flatten.

CLI:

    python backfill_identity.py --dry-run [--vault-path <p>] [--json]
    python backfill_identity.py --apply   [--vault-path <p>] [--json]
    python backfill_identity.py --validate [--vault-path <p>] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import identity


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _resolve_people_dir(cfg: dict, override: str | None) -> Path | None:
    if override:
        p = Path(os.path.expanduser(override)).resolve()
        return p if p.exists() else None
    v = cfg.get("vault") or {}
    vault_path = Path(os.path.expanduser(v.get("path") or ""))
    if not vault_path.exists():
        return None
    people_dir = vault_path / (v.get("people_dir") or "10 People")
    return people_dir if people_dir.exists() else None


def _conflicts_file() -> Path:
    return Path.home() / ".outreach-factory" / "migration-conflicts.yml"


# ---------------------------------------------------------------------------
# Frontmatter parsing + surgical rewrite
# ---------------------------------------------------------------------------


@dataclass
class ParsedNote:
    """Snapshot of a Person note's identity-relevant state.

    `raw_text` and `fm_text_lines` (the literal line list of the
    frontmatter block) are kept so we can splice new keys in without
    reformatting the rest.
    """
    path: Path
    raw_text: str
    fm_text: str
    fm_text_lines: list[str]
    body_text: str
    frontmatter: dict
    has_id: bool
    has_identity_keys: bool
    existing_id: str | None
    keys: identity.IdentityKeys
    proposed_id: str
    proposed_keys_block: dict      # what we'd write
    skip_reason: str | None = None


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return (frontmatter_text, body_text) or None if no frontmatter."""
    if not text.startswith("---"):
        return None
    # Find the closing fence — must be on its own line.
    m = re.search(r"\n---[ \t]*(?:\n|$)", text)
    if not m:
        return None
    fm_text = text[3:m.start()].lstrip("\n").rstrip()
    body_text = text[m.end():]
    return fm_text, body_text


def _safe_load_fm(fm_text: str) -> dict | None:
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _coerce_email_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return []


def _coerce_company_slug(value) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        m = re.match(r"\[\[([^\]]+)\]\]", value.strip())
        return (m.group(1) if m else value).strip() or None
    return None


def _proposed_keys_block(keys: identity.IdentityKeys) -> dict:
    """Stable shape for the identity_keys frontmatter block."""
    block: dict = {}
    if keys.linkedin:
        block["linkedin"] = keys.linkedin
    if keys.emails:
        block["emails"] = sorted(keys.emails)
    if keys.github:
        block["github"] = keys.github
    if keys.twitter:
        block["twitter"] = keys.twitter
    if keys.alt_names:
        block["alt_names"] = sorted(keys.alt_names)
    return block


def parse_person_note(path: Path) -> ParsedNote | None:
    """Read a Person note and compute proposed identity.

    Returns None if the file isn't parseable as a Person note (missing
    frontmatter, wrong type, broken YAML).
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    split = _split_frontmatter(raw_text)
    if split is None:
        return None
    fm_text, body_text = split
    fm = _safe_load_fm(fm_text)
    if fm is None:
        return None
    if (fm.get("type") or "").strip() != "person":
        return None

    name = str(fm.get("name") or path.stem or "").strip()
    keys = identity.compute_keys(
        name=name,
        email=fm.get("email"),
        emails=_coerce_email_list(fm.get("emails")),
        linkedin_url=fm.get("linkedin"),
        github=fm.get("github"),
        twitter=fm.get("twitter"),
    )
    existing_id = (str(fm["id"]).strip() if fm.get("id") else None)
    proposed_id = existing_id or identity.mint_id(
        keys,
        name_fallback=name,
        company_slug=_coerce_company_slug(fm.get("company")),
    )

    proposed_block = _proposed_keys_block(keys)
    skip_reason: str | None = None
    if keys.is_empty():
        # Nothing identifying — we still mint a -tmp ID (so the note has
        # a stable handle for the ledger) but flag it for the report.
        skip_reason = "no_identity_keys"

    return ParsedNote(
        path=path,
        raw_text=raw_text,
        fm_text=fm_text,
        fm_text_lines=fm_text.split("\n"),
        body_text=body_text,
        frontmatter=fm,
        has_id=bool(existing_id),
        has_identity_keys=bool(fm.get("identity_keys")),
        existing_id=existing_id,
        keys=keys,
        proposed_id=proposed_id,
        proposed_keys_block=proposed_block,
        skip_reason=skip_reason,
    )


def _yaml_block_lines(block: dict, indent: int = 2) -> list[str]:
    """Serialize a single mapping as indented YAML lines, no doc fences.

    Used for the body of `identity_keys:`. Sorted lists for determinism.
    """
    dumped = yaml.safe_dump(block, sort_keys=False, allow_unicode=True,
                            default_flow_style=False)
    return [" " * indent + line for line in dumped.rstrip().split("\n")]


def render_with_identity(parsed: ParsedNote) -> str:
    """Return the note's full text with `id:` + `identity_keys:` inserted.

    Idempotent: if the note already has both fields, returns the input
    unchanged (but may rewrite to canonical form if `--reformat` is added
    later — currently a no-op).
    """
    if parsed.has_id and parsed.has_identity_keys:
        return parsed.raw_text

    lines = list(parsed.fm_text_lines)

    # Strip any partial state first — re-applying the backfill should
    # converge, not pile up duplicate blocks.
    lines = _strip_existing_identity_lines(lines)

    insert_idx = _find_insertion_point(lines)

    new_lines = [f"id: {parsed.proposed_id}"]
    block_lines = _yaml_block_lines(parsed.proposed_keys_block, indent=2)
    if block_lines:
        new_lines.append("identity_keys:")
        new_lines.extend(block_lines)
        new_lines.append("identity_version: 1")
    # If the keys block would be empty, we still write id (so the note
    # has a stable handle) but skip the empty mapping — emitting
    # `identity_keys: {}` would look strange in the vault.

    lines[insert_idx:insert_idx] = new_lines
    new_fm = "\n".join(lines).rstrip() + "\n"
    return f"---\n{new_fm}---\n{parsed.body_text}"


def _find_insertion_point(lines: list[str]) -> int:
    """Return the index immediately AFTER the `type:` line, or after `name:`
    if no type line, or 0 otherwise. Chosen so the identity block sits at
    the top of frontmatter where a human reader expects it.
    """
    for i, ln in enumerate(lines):
        if re.match(r"^type\s*:", ln):
            return i + 1
    for i, ln in enumerate(lines):
        if re.match(r"^name\s*:", ln):
            return i + 1
    return 0


def _strip_existing_identity_lines(lines: list[str]) -> list[str]:
    """Drop any pre-existing `id:`, `identity_keys:` (and its indented
    body), and `identity_version:` lines. Called before re-inserting so
    the script is idempotent.
    """
    out: list[str] = []
    skipping_block = False
    for ln in lines:
        if skipping_block:
            # Indented continuation of identity_keys block?
            if ln.startswith(" ") or ln.startswith("\t"):
                continue
            skipping_block = False
            # Fall through to standard handling for this line.
        if re.match(r"^id\s*:", ln):
            continue
        if re.match(r"^identity_version\s*:", ln):
            continue
        if re.match(r"^identity_keys\s*:", ln):
            skipping_block = True
            continue
        out.append(ln)
    return out


# ---------------------------------------------------------------------------
# Conflict detection (Union-Find over identity-key intersection)
# ---------------------------------------------------------------------------


@dataclass
class ConflictCluster:
    """A set of 2+ notes that mutually match via identity intersection."""
    note_paths: list[Path]
    shared_keys: dict[str, list[str]]   # class -> values intersected

    def to_serializable(self) -> dict:
        return {
            "note_paths": [str(p) for p in sorted(self.note_paths)],
            "shared_keys": {k: sorted(v) for k, v in self.shared_keys.items()},
            "resolved": False,
        }


def _union_find(n: int):
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    return find, union


def detect_conflicts(parsed_notes: list[ParsedNote]) -> list[ConflictCluster]:
    """Pairwise key intersection; cluster by transitive equivalence.

    A pair (A, B) is "linked" if their IdentityKeys intersect on any
    strong key class (linkedin/email/github/twitter — alt_names is NOT
    a match class). Union-Find collapses transitive links so a 3-note
    cycle (A↔B, B↔C) surfaces as a single cluster.
    """
    n = len(parsed_notes)
    find, union = _union_find(n)
    # Collect each pair's shared-key detail for the report.
    pair_detail: dict[tuple[int, int], dict[str, list[str]]] = {}
    for i in range(n):
        for j in range(i + 1, n):
            classes = identity.keys_intersect(
                parsed_notes[i].keys, parsed_notes[j].keys
            )
            if classes:
                union(i, j)
                pair_detail[(i, j)] = identity.keys_intersect_detail(
                    parsed_notes[i].keys, parsed_notes[j].keys,
                )
    clusters_by_root: dict[int, list[int]] = {}
    for i in range(n):
        clusters_by_root.setdefault(find(i), []).append(i)

    out: list[ConflictCluster] = []
    for members in clusters_by_root.values():
        if len(members) < 2:
            continue
        merged: dict[str, set[str]] = {}
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = sorted((members[i], members[j]))
                detail = pair_detail.get((a, b)) or {}
                for cls, vals in detail.items():
                    merged.setdefault(cls, set()).update(vals)
        out.append(ConflictCluster(
            note_paths=[parsed_notes[m].path for m in members],
            shared_keys={k: sorted(v) for k, v in merged.items()},
        ))
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class BackfillPlan:
    parsed_notes: list[ParsedNote]
    unparseable_paths: list[Path] = field(default_factory=list)
    conflicts: list[ConflictCluster] = field(default_factory=list)

    @property
    def to_create_id(self) -> list[ParsedNote]:
        return [n for n in self.parsed_notes if not n.has_id]

    @property
    def to_create_keys(self) -> list[ParsedNote]:
        return [n for n in self.parsed_notes if not n.has_identity_keys]

    @property
    def already_complete(self) -> list[ParsedNote]:
        return [n for n in self.parsed_notes
                if n.has_id and n.has_identity_keys]

    @property
    def tmp_id_notes(self) -> list[ParsedNote]:
        return [n for n in self.parsed_notes
                if identity.id_is_temporary(n.proposed_id)]


def build_plan(people_dir: Path) -> BackfillPlan:
    parsed: list[ParsedNote] = []
    unparseable: list[Path] = []
    for note in sorted(people_dir.rglob("*.md")):
        rel = note.relative_to(people_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if ".conflicted" in note.name or note.name.endswith(".conflict.md"):
            continue
        p = parse_person_note(note)
        if p is None:
            # Not a person note OR unparseable. Skip silently for non-person
            # notes (sidecars, READMEs); track unparseable separately so
            # the operator can investigate broken frontmatter.
            try:
                first_chunk = note.read_text(encoding="utf-8", errors="replace")[:5]
            except OSError:
                first_chunk = ""
            if first_chunk.startswith("---"):
                unparseable.append(note)
            continue
        parsed.append(p)
    conflicts = detect_conflicts(parsed)
    return BackfillPlan(parsed_notes=parsed, unparseable_paths=unparseable,
                        conflicts=conflicts)


def write_conflicts_file(plan: BackfillPlan, path: Path) -> None:
    if not plan.conflicts:
        if path.exists():
            # Leave stale resolved-or-empty file alone; operator deletes it
            # manually as part of the workflow. (Auto-deleting risks data
            # loss if the operator wrote resolution notes in the file.)
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "version": 1,
        "instructions": [
            "Each cluster below is 2+ Person notes whose identity_keys",
            "intersect. The backfill --apply step refuses to run until",
            "every cluster is resolved or this file is deleted.",
            "",
            "For each cluster:",
            "  - SAME PERSON: pick a canonical note, copy unique keys",
            "    from the secondaries into it, delete the secondaries.",
            "  - DIFFERENT PEOPLE sharing a key (rare): identify which",
            "    note legitimately owns the shared key and remove it",
            "    from the others.",
            "After resolving, EITHER delete this file OR set",
            "`resolved: true` on the cluster.",
        ],
        "conflicts": [c.to_serializable() for c in plan.conflicts],
    }
    path.write_text(
        yaml.safe_dump(body, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def read_unresolved_conflicts(path: Path) -> list[dict]:
    """Return clusters in the file that aren't marked resolved.

    Tolerates absent file (returns []) and malformed file (raises).
    """
    if not path.exists():
        return []
    try:
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RuntimeError(f"migration-conflicts.yml is unparseable: {e}") from e
    if not isinstance(body, dict):
        return []
    clusters = body.get("conflicts") or []
    return [c for c in clusters if not bool(c.get("resolved"))]


def apply_plan(plan: BackfillPlan, *, force: bool = False) -> dict:
    """Write `id:` + `identity_keys:` blocks into each Person note.

    Returns a result dict; never raises (caller decides exit code).

    `force=True` skips the conflicts-resolved check — intended for tests
    and for emergency operator override after manual triage.
    """
    if plan.conflicts and not force:
        return {
            "ok": False,
            "reason": "unresolved identity-graph conflicts in plan",
            "conflicts": len(plan.conflicts),
            "applied": 0,
        }

    applied_paths: list[str] = []
    skipped_paths: list[str] = []
    for parsed in plan.parsed_notes:
        if parsed.has_id and parsed.has_identity_keys:
            skipped_paths.append(str(parsed.path))
            continue
        new_text = render_with_identity(parsed)
        if new_text == parsed.raw_text:
            skipped_paths.append(str(parsed.path))
            continue
        parsed.path.write_text(new_text, encoding="utf-8")
        applied_paths.append(str(parsed.path))

    return {
        "ok": True,
        "applied": len(applied_paths),
        "skipped": len(skipped_paths),
        "applied_paths": applied_paths,
        "skipped_paths": skipped_paths,
    }


def validate_vault(people_dir: Path) -> dict:
    """Post-condition: every Person note has id + identity_keys AND no
    two notes share a strong key (i.e. identity graph is partitioned).
    """
    plan = build_plan(people_dir)
    missing_id = [str(n.path) for n in plan.parsed_notes if not n.has_id]
    missing_keys_block = [str(n.path) for n in plan.parsed_notes
                          if not n.has_identity_keys and not n.keys.is_empty()]
    tmp_ids = [str(n.path) for n in plan.tmp_id_notes if n.has_id]
    return {
        "ok": (not missing_id and not missing_keys_block and not plan.conflicts),
        "person_note_count": len(plan.parsed_notes),
        "missing_id": missing_id,
        "missing_identity_keys": missing_keys_block,
        "tmp_id_notes": tmp_ids,
        "conflicts": [c.to_serializable() for c in plan.conflicts],
        "unparseable_paths": [str(p) for p in plan.unparseable_paths],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_dry_run(plan: BackfillPlan) -> None:
    print(f"Person notes scanned: {len(plan.parsed_notes)}")
    if plan.unparseable_paths:
        print(f"⚠️  Unparseable notes ({len(plan.unparseable_paths)}):")
        for p in plan.unparseable_paths:
            print(f"    {p}")
    print(f"Already complete (id + identity_keys): {len(plan.already_complete)}")
    print(f"Need id minted:                        {len(plan.to_create_id)}")
    print(f"Need identity_keys block:              {len(plan.to_create_keys)}")
    tmp = plan.tmp_id_notes
    if tmp:
        print(f"⚠️  Would mint TEMPORARY (-tmp) id for {len(tmp)} note(s) "
              "(no LinkedIn/email present — send-gate will block):")
        for n in tmp:
            print(f"    {n.proposed_id:48s} {n.path}")
    if plan.conflicts:
        print(f"\n❌ {len(plan.conflicts)} identity-graph conflict cluster(s):")
        for i, c in enumerate(plan.conflicts, 1):
            classes = ",".join(sorted(c.shared_keys.keys()))
            print(f"\n  Cluster {i} — shared via [{classes}]:")
            for k, vs in c.shared_keys.items():
                for v in vs:
                    print(f"    {k:10s} = {v}")
            for p in c.note_paths:
                print(f"    -> {p}")
    else:
        print("\n✅ No identity-graph conflicts.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="Report proposed changes + conflicts; no writes")
    mode.add_argument("--apply", action="store_true",
                      help="Write id + identity_keys blocks into Person notes")
    mode.add_argument("--validate", action="store_true",
                      help="Assert every note has id + identity_keys; no writes")
    p.add_argument("--vault-path", default=None,
                   help="Override config.yml — point at a synthetic people_dir (testing)")
    p.add_argument("--force", action="store_true",
                   help="With --apply: ignore conflicts file (operator override; logged)")
    p.add_argument("--json", action="store_true")

    args = p.parse_args()
    cfg = {} if args.vault_path else _load_config()
    people_dir = _resolve_people_dir(cfg, args.vault_path)
    if people_dir is None:
        print(json.dumps({"ok": False, "reason": "people_dir not resolvable"})
              if args.json else "ERROR: people_dir not resolvable",
              file=sys.stderr)
        sys.exit(2)

    plan = build_plan(people_dir)

    if args.dry_run:
        write_conflicts_file(plan, _conflicts_file())
        if args.json:
            out = {
                "ok": True,
                "people_dir": str(people_dir),
                "person_note_count": len(plan.parsed_notes),
                "already_complete": len(plan.already_complete),
                "to_create_id": len(plan.to_create_id),
                "to_create_keys": len(plan.to_create_keys),
                "tmp_id_notes": [
                    {"path": str(n.path), "proposed_id": n.proposed_id}
                    for n in plan.tmp_id_notes
                ],
                "conflicts": [c.to_serializable() for c in plan.conflicts],
                "unparseable_paths": [str(p) for p in plan.unparseable_paths],
                "conflicts_file": (str(_conflicts_file()) if plan.conflicts else None),
            }
            print(json.dumps(out, indent=2))
        else:
            _print_dry_run(plan)
            if plan.conflicts:
                print(f"\nConflicts written to: {_conflicts_file()}")
                print("Resolve them and re-run --dry-run before --apply.")
        sys.exit(1 if plan.conflicts else 0)

    if args.apply:
        # Block on unresolved entries in the conflicts file UNLESS --force.
        if not args.force:
            try:
                unresolved = read_unresolved_conflicts(_conflicts_file())
            except RuntimeError as e:
                print(json.dumps({"ok": False, "reason": str(e)})
                      if args.json else f"ERROR: {e}", file=sys.stderr)
                sys.exit(2)
            if unresolved:
                msg = (f"{len(unresolved)} unresolved cluster(s) in "
                       f"{_conflicts_file()}; resolve or delete the file first")
                print(json.dumps({"ok": False, "reason": msg})
                      if args.json else f"ERROR: {msg}", file=sys.stderr)
                sys.exit(2)
        # Also block if the in-memory plan still shows live conflicts (the
        # file may have been deleted but the underlying vault state didn't
        # change). --force bypasses.
        result = apply_plan(plan, force=args.force)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result["ok"]:
                print(f"✅ Applied to {result['applied']} note(s); "
                      f"skipped {result['skipped']} already-complete.")
            else:
                print(f"❌ {result['reason']}", file=sys.stderr)
        sys.exit(0 if result["ok"] else 1)

    if args.validate:
        result = validate_vault(people_dir)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result["ok"]:
                print(f"✅ Identity backfill complete "
                      f"({result['person_note_count']} Person notes; "
                      f"{len(result['tmp_id_notes'])} -tmp).")
            else:
                print("❌ Identity backfill incomplete:")
                if result["missing_id"]:
                    print(f"  {len(result['missing_id'])} note(s) missing id")
                if result["missing_identity_keys"]:
                    print(f"  {len(result['missing_identity_keys'])} note(s) missing identity_keys block")
                if result["conflicts"]:
                    print(f"  {len(result['conflicts'])} unresolved conflict cluster(s)")
                if result["unparseable_paths"]:
                    print(f"  {len(result['unparseable_paths'])} unparseable note(s)")
        sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
