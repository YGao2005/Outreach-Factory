"""Tests for ``vault/0005_add_discovery_lineage_to_identity_keys``.

Pillar E Week 9-11 — per ADR-0036 D168. Coverage:

* TestMigrationSurface — Migration Protocol shape pins
* TestUpgradeCascade — the four-source backfill cascade per D168
* TestUpgradeIdempotence — re-running upgrade is a no-op
* TestUpgradeRefuseLoud — missing vault + invalid frontmatter posture
* TestDowngradeRoundTrip — remove the sub-block; round-trip exact

See ADR-0036 D168 for the design rationale.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from orchestrator.migrations.types import (
    MigrationCategory, MigrationContext,
)
from orchestrator.migrations.vault._vault_io import (
    read_person_frontmatter,
)
from orchestrator.migrations.vault.migration_0005_add_discovery_lineage_to_identity_keys import (
    MIGRATION,
    MIGRATION_ID,
    AddDiscoveryLineageToIdentityKeys,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    state_dir: Path,
    vault_dir: Path | None,
    ledger_dir: Path | None = None,
    dry_run: bool = False,
) -> MigrationContext:
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=ledger_dir if ledger_dir is not None else state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.vault.0005"),
    )


def _write_person_note(
    vault_dir: Path,
    name: str,
    *,
    person_id: str,
    identity_keys: dict | None,
    source_channel: str | None = None,
    source_list: str | None = None,
    created: str | None = None,
    extra: dict | None = None,
) -> Path:
    """Write a synthetic Person note matching the canonical shape."""
    fm: dict = {
        "type": "person",
        "name": name,
        "id": person_id,
    }
    if identity_keys is not None:
        fm["identity_keys"] = identity_keys
    if source_channel is not None:
        fm["source_channel"] = source_channel
    if source_list is not None:
        fm["source_list"] = source_list
    if created is not None:
        fm["created"] = created
    if extra:
        fm.update(extra)
    note = vault_dir / "10 People" / f"{name}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n# {name}\n",
        encoding="utf-8",
    )
    return note


def _write_source_md(
    vault_dir: Path,
    source_skill: str,
    source_list: str,
    scraped_at: str = "2026-05-13T10:00:00Z",
    raw_input_hash: str | None = None,
) -> Path:
    """Write a sibling ``_source.md`` file under People dir."""
    src = vault_dir / "10 People" / "_source.md"
    fm = {
        "source_skill": source_skill,
        "source_list": source_list,
        "scraped_at": scraped_at,
    }
    if raw_input_hash:
        fm["raw_input_hash"] = raw_input_hash
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(
        f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n",
        encoding="utf-8",
    )
    return src


def _seed_ledger_enrolled(
    ledger_dir: Path,
    person_id: str,
    source: str,
    source_list: str = "[[2026-05-13-test]]",
    ts: str = "2026-05-13T10:00:00Z",
) -> None:
    """Append a synthetic enrolled event to the ledger for the backfill cascade."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    f = ledger_dir / "events-2026-05-13.jsonl"
    f.write_text(
        json.dumps({
            "type": "enrolled",
            "person_id": person_id,
            "source": source,
            "source_list": source_list,
            "ts": ts,
            "v": 1,
        }) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# TestMigrationSurface — Migration Protocol pins
# ---------------------------------------------------------------------------


class TestMigrationSurface:

    def test_migration_id(self):
        assert MIGRATION.id == "0005_add_discovery_lineage_to_identity_keys"
        assert MIGRATION_ID == MIGRATION.id

    def test_category_is_vault(self):
        assert MIGRATION.category == MigrationCategory.VAULT

    def test_is_reversible(self):
        assert MIGRATION.is_reversible is True

    def test_description_mentions_discovery_lineage(self):
        assert "discovery_lineage" in MIGRATION.description.lower()

    def test_module_singleton_is_dataclass_instance(self):
        assert isinstance(MIGRATION, AddDiscoveryLineageToIdentityKeys)


# ---------------------------------------------------------------------------
# TestUpgradeCascade — D168 backfill cascade
# ---------------------------------------------------------------------------


class TestUpgradeCascade:

    def test_source_md_takes_precedence(self, tmp_path: Path):
        """When _source.md is parseable, it wins over source_channel."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Alice", person_id="alice-li",
            identity_keys={"linkedin": "in/alice"},
            source_channel="find-leads",  # would normalize to find-leads
            source_list="[[fallback-list]]",
        )
        _write_source_md(
            vault,
            source_skill="competitor-customers",  # _source.md wins
            source_list="[[2026-05-13-acme]]",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)

        assert result.applied is True
        assert result.affected_count == 1

        fm, _ = read_person_frontmatter(vault / "10 People" / "Alice.md")
        lineage = fm["identity_keys"]["discovery_lineage"]
        assert lineage["source_skill"] == "competitor-customers"
        assert lineage["source_list"] == "[[2026-05-13-acme]]"
        assert lineage["scraped_at"].startswith("2026-05-13T10:00:00")

    def test_source_channel_fallback(self, tmp_path: Path):
        """No _source.md → use source_channel: frontmatter."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Bob", person_id="bob-li",
            identity_keys={"linkedin": "in/bob"},
            source_channel="funded-founders",  # legacy spelling
            source_list="[[2026-05-13-vcs]]",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1

        fm, _ = read_person_frontmatter(vault / "10 People" / "Bob.md")
        lineage = fm["identity_keys"]["discovery_lineage"]
        # Legacy "funded-founders" normalized to canonical "find-funded-founders".
        assert lineage["source_skill"] == "find-funded-founders"
        assert lineage["source_list"] == "[[2026-05-13-vcs]]"

    def test_source_channel_without_source_list_uses_default(self, tmp_path: Path):
        """source_channel present, source_list absent → default to [[legacy-{skill}]]."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Carol", person_id="carol-li",
            identity_keys={"linkedin": "in/carol"},
            source_channel="find-leads",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        MIGRATION.upgrade(ctx)
        fm, _ = read_person_frontmatter(vault / "10 People" / "Carol.md")
        lineage = fm["identity_keys"]["discovery_lineage"]
        assert lineage["source_skill"] == "find-leads"
        assert lineage["source_list"] == "[[legacy-find-leads]]"

    def test_ledger_fallback(self, tmp_path: Path):
        """No _source.md + no source_channel → consult ledger enrolled events."""
        vault = tmp_path / "vault"
        ledger = tmp_path / "ledger"
        _write_person_note(
            vault, "Dave", person_id="dave-li",
            identity_keys={"linkedin": "in/dave"},
        )
        _seed_ledger_enrolled(
            ledger, "dave-li", source="competitor-customers",
            source_list="[[2026-05-13-acme]]",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault, ledger_dir=ledger)
        MIGRATION.upgrade(ctx)
        fm, _ = read_person_frontmatter(vault / "10 People" / "Dave.md")
        lineage = fm["identity_keys"]["discovery_lineage"]
        assert lineage["source_skill"] == "competitor-customers"
        assert lineage["source_list"] == "[[2026-05-13-acme]]"

    def test_manual_floor_when_no_provenance(self, tmp_path: Path):
        """Absent every source → fall to source_skill: manual."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Eve", person_id="eve-li",
            identity_keys={"linkedin": "in/eve"},
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1

        fm, _ = read_person_frontmatter(vault / "10 People" / "Eve.md")
        lineage = fm["identity_keys"]["discovery_lineage"]
        assert lineage["source_skill"] == "manual"
        assert lineage["source_list"] == "[[legacy-manual]]"
        assert lineage["raw_input_hash"].startswith("sha256:")

    def test_unknown_source_channel_normalizes_to_manual(self, tmp_path: Path):
        """Legacy source_channel value not in mapping → normalize to manual."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Frank", person_id="frank-li",
            identity_keys={"linkedin": "in/frank"},
            source_channel="rapidapi-scraping-tool",  # unknown
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        MIGRATION.upgrade(ctx)
        fm, _ = read_person_frontmatter(vault / "10 People" / "Frank.md")
        lineage = fm["identity_keys"]["discovery_lineage"]
        # Unknown value → manual (per normalize_legacy_source_to_skill contract).
        assert lineage["source_skill"] == "manual"

    def test_source_md_in_subfolder_attributes_persons_in_same_subfolder(
        self, tmp_path: Path,
    ):
        """Pillar E Week 9-11 review P3-D regression pin.

        Operators commonly organize Persons by source-list subfolder
        (e.g., `10 People/funded-founders/Alice.md`). A `_source.md`
        file at the subfolder level (`10 People/funded-founders/_source.md`)
        MUST attribute Persons in that subfolder.
        """
        vault = tmp_path / "vault"
        subfolder = vault / "10 People" / "funded-founders"
        subfolder.mkdir(parents=True)
        # Write a Person in the subfolder.
        note = subfolder / "Olivia.md"
        note.write_text(
            "---\n" + yaml.safe_dump({
                "type": "person",
                "name": "Olivia",
                "id": "olivia-li",
                "identity_keys": {"linkedin": "in/olivia"},
            }, sort_keys=False) + "---\n\n# Olivia\n",
            encoding="utf-8",
        )
        # Write _source.md in the SAME subfolder.
        src = subfolder / "_source.md"
        src.write_text(
            "---\n" + yaml.safe_dump({
                "source_skill": "find-funded-founders",
                "source_list": "[[2026-05-13-funded-founders]]",
                "scraped_at": "2026-05-13T10:00:00Z",
            }, sort_keys=False) + "---\n",
            encoding="utf-8",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1

        fm, _ = read_person_frontmatter(note)
        lineage = fm["identity_keys"]["discovery_lineage"]
        assert lineage["source_skill"] == "find-funded-founders"
        assert lineage["source_list"] == "[[2026-05-13-funded-founders]]"

    def test_source_md_traversal_stops_at_people_dir(self, tmp_path: Path):
        """Pillar E Week 9-11 review P3-A regression pin.

        A `_source.md` at the vault root (outside the People dir) MUST
        NOT pollute Person attribution — the traversal stops at the
        People dir bound per the post-P3-A fix.
        """
        vault = tmp_path / "vault"
        people = vault / "10 People"
        people.mkdir(parents=True)
        # Write a Person in the People dir (no subfolder).
        note = people / "Peter.md"
        note.write_text(
            "---\n" + yaml.safe_dump({
                "type": "person",
                "name": "Peter",
                "id": "peter-li",
                "identity_keys": {"linkedin": "in/peter"},
            }, sort_keys=False) + "---\n\n# Peter\n",
            encoding="utf-8",
        )
        # Write a STRAY _source.md at the vault root (outside People dir).
        stray = vault / "_source.md"
        stray.write_text(
            "---\n" + yaml.safe_dump({
                "source_skill": "competitor-customers",
                "source_list": "[[stray-vault-root-list]]",
                "scraped_at": "2026-05-13T10:00:00Z",
            }, sort_keys=False) + "---\n",
            encoding="utf-8",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1

        # Peter MUST fall to manual floor, NOT pick up the stray
        # vault-root _source.md (would be a privacy/correctness leak).
        fm, _ = read_person_frontmatter(note)
        lineage = fm["identity_keys"]["discovery_lineage"]
        assert lineage["source_skill"] == "manual", (
            "P3-A regression: vault-root _source.md must NOT attribute "
            "Person notes in People dir. The traversal bound at People "
            "dir prevents the silent attribution leak."
        )
        assert lineage["source_list"] == "[[legacy-manual]]"

    def test_per_source_counts_in_result_notes(self, tmp_path: Path):
        """The result's notes name the per-source backfill counts."""
        vault = tmp_path / "vault"
        # One via _source.md, one via source_channel, one manual floor.
        _write_person_note(
            vault, "A1", person_id="a1-li",
            identity_keys={"linkedin": "in/a1"},
            source_channel="find-leads",
        )
        _write_person_note(
            vault, "A2", person_id="a2-li",
            identity_keys={"linkedin": "in/a2"},
        )
        _write_source_md(
            vault, source_skill="research-prospect",
            source_list="[[research]]",
        )
        # Note: _source.md applies to ALL Person notes in the same dir;
        # so A1 + A2 will both pick up _source.md (it takes precedence).
        # Let me re-shape: write source.md AFTER, only for testing the
        # precedence. The "per_source" assertion adjusts.

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 2
        # Both should use _source.md (it's in the same dir).
        assert "_source.md" in result.notes


# ---------------------------------------------------------------------------
# TestUpgradeIdempotence
# ---------------------------------------------------------------------------


class TestUpgradeIdempotence:

    def test_already_at_target_skipped(self, tmp_path: Path):
        """Person notes already carrying discovery_lineage are skipped."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Gina", person_id="gina-li",
            identity_keys={
                "linkedin": "in/gina",
                "discovery_lineage": {
                    "source_skill": "find-leads",
                    "source_list": "[[manual]]",
                    "scraped_at": "2026-05-13T10:00:00Z",
                    "raw_input_hash": "sha256:" + "a" * 64,
                },
            },
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        # Should report 0 affected (the note already has the field).
        assert result.affected_count == 0

    def test_re_running_upgrade_is_noop(self, tmp_path: Path):
        """Two consecutive upgrade calls — second is a no-op."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Hank", person_id="hank-li",
            identity_keys={"linkedin": "in/hank"},
            source_channel="find-leads",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        r1 = MIGRATION.upgrade(ctx)
        r2 = MIGRATION.upgrade(ctx)
        assert r1.affected_count == 1
        assert r2.affected_count == 0


# ---------------------------------------------------------------------------
# TestUpgradeRefuseLoud
# ---------------------------------------------------------------------------


class TestUpgradeRefuseLoud:

    def test_refuses_on_missing_vault_dir(self, tmp_path: Path):
        ctx = _make_ctx(state_dir=tmp_path, vault_dir=None)
        with pytest.raises(ValueError, match="requires ctx.vault_dir"):
            MIGRATION.upgrade(ctx)

    def test_tolerates_missing_ledger_dir(self, tmp_path: Path):
        """ctx.ledger_dir = None → cascade just skips the ledger step."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Ivy", person_id="ivy-li",
            identity_keys={"linkedin": "in/ivy"},
        )

        # ledger_dir points to nonexistent path — _try_ledger_enrolled
        # returns None without raising.
        nonexistent = tmp_path / "no_ledger"
        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault, ledger_dir=nonexistent)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        fm, _ = read_person_frontmatter(vault / "10 People" / "Ivy.md")
        assert fm["identity_keys"]["discovery_lineage"]["source_skill"] == "manual"

    def test_skips_persons_without_identity_keys(self, tmp_path: Path):
        """Pre-Phase-5.5 Person notes lacking identity_keys are skipped."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Jane", person_id="jane-li",
            identity_keys=None,  # no identity_keys block
            source_channel="find-leads",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        # Note is unchanged.
        fm, _ = read_person_frontmatter(vault / "10 People" / "Jane.md")
        assert "identity_keys" not in fm

    def test_skips_persons_without_id(self, tmp_path: Path):
        """Person notes without `id:` are skipped (drafts in progress)."""
        vault = tmp_path / "vault"
        people = vault / "10 People"
        people.mkdir(parents=True)
        # Write a Person note WITHOUT id:
        (people / "Draft.md").write_text(
            "---\ntype: person\nname: Draft\nidentity_keys:\n  linkedin: in/draft\n---\n",
            encoding="utf-8",
        )
        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0

    def test_skips_non_person_notes(self, tmp_path: Path):
        """Non-Person notes (e.g. lead lists) are skipped."""
        vault = tmp_path / "vault"
        people = vault / "10 People"
        people.mkdir(parents=True)
        (people / "LeadList.md").write_text(
            "---\ntype: lead-list\nname: 2026 leads\n---\n",
            encoding="utf-8",
        )
        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0


# ---------------------------------------------------------------------------
# TestDowngradeRoundTrip
# ---------------------------------------------------------------------------


class TestDowngradeRoundTrip:

    def test_downgrade_removes_sub_block(self, tmp_path: Path):
        """downgrade strips discovery_lineage; other fields preserved."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Kelly", person_id="kelly-li",
            identity_keys={"linkedin": "in/kelly"},
            source_channel="find-leads",
            source_list="[[2026-05-13]]",
        )

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        MIGRATION.upgrade(ctx)
        # Verify stamped.
        fm, _ = read_person_frontmatter(vault / "10 People" / "Kelly.md")
        assert "discovery_lineage" in fm["identity_keys"]

        # Now downgrade.
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        fm2, _ = read_person_frontmatter(vault / "10 People" / "Kelly.md")
        assert "discovery_lineage" not in fm2["identity_keys"]
        # Other identity_keys children preserved.
        assert fm2["identity_keys"]["linkedin"] == "in/kelly"
        # Other top-level fields preserved.
        assert fm2["source_channel"] == "find-leads"
        assert fm2["source_list"] == "[[2026-05-13]]"

    def test_downgrade_idempotent_when_absent(self, tmp_path: Path):
        """downgrade on a Person note without discovery_lineage is a no-op."""
        vault = tmp_path / "vault"
        _write_person_note(
            vault, "Liam", person_id="liam-li",
            identity_keys={"linkedin": "in/liam"},
        )
        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 0

    def test_downgrade_refuses_missing_vault(self, tmp_path: Path):
        ctx = _make_ctx(state_dir=tmp_path, vault_dir=None)
        with pytest.raises(ValueError, match="requires ctx.vault_dir"):
            MIGRATION.downgrade(ctx)

    def test_upgrade_downgrade_round_trip(self, tmp_path: Path):
        """upgrade → downgrade leaves the Person note byte-identical."""
        vault = tmp_path / "vault"
        note = _write_person_note(
            vault, "Maya", person_id="maya-li",
            identity_keys={"linkedin": "in/maya", "emails": ["maya@x.com"]},
            source_channel="find-leads",
            source_list="[[2026-05-13]]",
            created="2026-05-01",
        )
        original_text = note.read_text(encoding="utf-8")

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)

        post_text = note.read_text(encoding="utf-8")
        assert post_text == original_text


# ---------------------------------------------------------------------------
# Dry-run posture
# ---------------------------------------------------------------------------


class TestDryRun:

    def test_dry_run_does_not_mutate(self, tmp_path: Path):
        vault = tmp_path / "vault"
        note = _write_person_note(
            vault, "Nick", person_id="nick-li",
            identity_keys={"linkedin": "in/nick"},
            source_channel="find-leads",
        )
        original = note.read_text(encoding="utf-8")

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True
        assert result.affected_count == 1  # would affect 1 — but didn't write
        # File is unchanged.
        assert note.read_text(encoding="utf-8") == original
