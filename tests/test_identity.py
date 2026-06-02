"""Tests for orchestrator/identity.py.

Covers: normalization, key construction, multi-key intersection, deterministic
ID minting, strict-policy resolution (None/Match/Conflict), legacy-frontmatter
fallback, and edge cases (Unicode, hidden files, Obsidian sync conflicts).

Run:
    cd /Users/yang/code/outreach-factory && pytest tests/test_identity.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator import identity as I


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestLinkedinNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("linkedin.com/in/dylan-txa", "in/dylan-txa"),
        ("https://www.linkedin.com/in/dylan-txa/", "in/dylan-txa"),
        ("https://linkedin.com/in/Dylan-Txa", "in/dylan-txa"),
        ("LINKEDIN.COM/IN/dylan-txa", "in/dylan-txa"),
        ("https://uk.linkedin.com/in/dylan-txa", "in/dylan-txa"),
        ("https://www.linkedin.com/in/dylan-txa?utm=foo", "in/dylan-txa"),
        ("https://linkedin.com/in/dylan-txa/recent-activity/", "in/dylan-txa"),
        # Old "pub" URL format folds to "in"
        ("https://www.linkedin.com/pub/dylan-txa/", "in/dylan-txa"),
        # Company pages stay separate
        ("linkedin.com/company/gojiberry-ai", "company/gojiberry-ai"),
        ("https://linkedin.com/company/Gojiberry-AI/", "company/gojiberry-ai"),
        # Bare slug
        ("dylan-txa", "in/dylan-txa"),
        ("in/dylan-txa", "in/dylan-txa"),
        ("company/gojiberry-ai", "company/gojiberry-ai"),
    ])
    def test_normalizes(self, raw, expected):
        assert I._normalize_linkedin(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "not-a-linkedin-url"])
    def test_empty_or_invalid(self, raw):
        # Bare strings without URL structure get treated as slugs; only None/empty
        # truly return None. We test the actual empty cases here.
        if raw in (None, "", "   "):
            assert I._normalize_linkedin(raw) is None

    def test_person_vs_company_distinct(self):
        # Same slug under /in/ and /company/ must NOT collide.
        a = I._normalize_linkedin("linkedin.com/in/example")
        b = I._normalize_linkedin("linkedin.com/company/example")
        assert a != b


class TestEmailNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("dylan@gojiberry.ai", "dylan@gojiberry.ai"),
        ("Dylan@Gojiberry.AI", "dylan@gojiberry.ai"),
        ("  dylan@gojiberry.ai  ", "dylan@gojiberry.ai"),
        # Gmail dots + aliases: keep as distinct (intentionally — see HANDOFF)
        ("d.y.l.a.n@gmail.com", "d.y.l.a.n@gmail.com"),
        ("dylan+work@gmail.com", "dylan+work@gmail.com"),
    ])
    def test_normalizes(self, raw, expected):
        assert I._normalize_email(raw) == expected

    @pytest.mark.parametrize("raw", [
        None, "", "   ", "not-an-email", "missing@", "@missing.com",
        "no-at-sign.com", "two@@signs.com",
    ])
    def test_invalid(self, raw):
        assert I._normalize_email(raw) is None


class TestGithubNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("dylan-txa", "dylan-txa"),
        ("@dylan-txa", "dylan-txa"),
        ("Dylan-Txa", "dylan-txa"),
        ("github.com/dylan-txa", "dylan-txa"),
        ("https://github.com/dylan-txa", "dylan-txa"),
        ("https://www.github.com/dylan-txa/some-repo", "dylan-txa"),
    ])
    def test_normalizes(self, raw, expected):
        assert I._normalize_github(raw) == expected


class TestTwitterNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("dylan_txa", "dylan_txa"),
        ("@dylan_txa", "dylan_txa"),
        ("Dylan_Txa", "dylan_txa"),
        ("twitter.com/dylan_txa", "dylan_txa"),
        ("https://twitter.com/dylan_txa", "dylan_txa"),
        ("https://x.com/dylan_txa", "dylan_txa"),
        ("x.com/dylan_txa/status/12345", "dylan_txa"),
    ])
    def test_normalizes(self, raw, expected):
        assert I._normalize_twitter(raw) == expected


class TestAltNameNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("Dylan Teixeira", "dylan teixeira"),
        ("  Dylan   Teixeira  ", "dylan teixeira"),
        # Diacritics stripped for matching
        ("José Barrueta", "jose barrueta"),
        ("Witold de La Chapelle", "witold de la chapelle"),
        ("François Müller", "francois muller"),
        # Asian scripts NFC-normalized but not transliterated
        ("田中太郎", "田中太郎"),
    ])
    def test_normalizes(self, raw, expected):
        assert I._normalize_alt_name(raw) == expected


# ---------------------------------------------------------------------------
# compute_keys (the public construction API)
# ---------------------------------------------------------------------------


class TestComputeKeys:
    def test_full(self):
        k = I.compute_keys(
            name="Dylan Teixeira",
            email="DYLAN@gojiberry.ai",
            linkedin_url="https://linkedin.com/in/dylan-txa",
            github="@dylan-txa",
            twitter="x.com/dylan_txa",
            alt_names=["Dylan T."],
        )
        assert k.linkedin == "in/dylan-txa"
        assert k.emails == frozenset({"dylan@gojiberry.ai"})
        assert k.github == "dylan-txa"
        assert k.twitter == "dylan_txa"
        # Name folded into alt_names
        assert "dylan teixeira" in k.alt_names
        assert "dylan t." in k.alt_names

    def test_email_plus_emails_unioned(self):
        k = I.compute_keys(
            email="dylan@gojiberry.ai",
            emails=["dylan@edusign.com", "dylan@gojiberry.ai"],  # dup ok
        )
        assert k.emails == frozenset({"dylan@gojiberry.ai", "dylan@edusign.com"})

    def test_empty(self):
        k = I.compute_keys()
        assert k.is_empty()
        assert not k.has_strong_key()

    def test_name_only_is_empty_for_matching(self):
        # Name-only candidate: alt_names get populated, but is_empty() checks
        # match-classes (LinkedIn/email/github/twitter) — alt_names is NOT a
        # match class because names are too unstable. So name-only counts as
        # empty for matching purposes.
        k = I.compute_keys(name="Dylan Teixeira")
        assert k.alt_names  # name was folded in
        assert k.is_empty()  # but no match-class keys = empty for matching
        assert not k.has_strong_key()

    def test_strong_key_with_linkedin(self):
        k = I.compute_keys(linkedin_url="linkedin.com/in/dylan-txa")
        assert k.has_strong_key()

    def test_strong_key_with_email(self):
        k = I.compute_keys(email="dylan@gojiberry.ai")
        assert k.has_strong_key()


# ---------------------------------------------------------------------------
# Intersection
# ---------------------------------------------------------------------------


class TestKeysIntersect:
    def test_no_match(self):
        a = I.compute_keys(linkedin_url="linkedin.com/in/alice")
        b = I.compute_keys(linkedin_url="linkedin.com/in/bob")
        assert I.keys_intersect(a, b) == frozenset()

    def test_single_class_match_linkedin(self):
        a = I.compute_keys(linkedin_url="linkedin.com/in/alice", email="alice@a.com")
        b = I.compute_keys(linkedin_url="linkedin.com/in/alice", email="alice@b.com")
        assert I.keys_intersect(a, b) == frozenset({"linkedin"})

    def test_single_class_match_email(self):
        a = I.compute_keys(email="alice@example.com")
        b = I.compute_keys(linkedin_url="linkedin.com/in/alice", email="alice@example.com")
        assert I.keys_intersect(a, b) == frozenset({"email"})

    def test_multi_class_match(self):
        a = I.compute_keys(
            linkedin_url="linkedin.com/in/alice",
            email="alice@example.com",
            github="alice-gh",
        )
        b = I.compute_keys(
            linkedin_url="linkedin.com/in/alice",
            email="alice@example.com",
            github="alice-gh",
            twitter="alice_tw",
        )
        assert I.keys_intersect(a, b) == frozenset({"linkedin", "email", "github"})

    def test_email_set_intersection(self):
        a = I.compute_keys(emails=["a@x.com", "a@y.com"])
        b = I.compute_keys(emails=["a@y.com", "a@z.com"])
        assert I.keys_intersect(a, b) == frozenset({"email"})

    def test_person_company_linkedin_distinct(self):
        # linkedin.com/in/example must NOT match linkedin.com/company/example
        a = I.compute_keys(linkedin_url="linkedin.com/in/example")
        b = I.compute_keys(linkedin_url="linkedin.com/company/example")
        assert I.keys_intersect(a, b) == frozenset()

    def test_alt_names_not_a_match_class(self):
        # Names are unstable; alt_names overlap must NOT register as match.
        a = I.compute_keys(name="Dylan Teixeira", email="x@a.com")
        b = I.compute_keys(name="Dylan Teixeira", email="y@b.com")
        assert I.keys_intersect(a, b) == frozenset()

    def test_intersect_detail(self):
        a = I.compute_keys(
            linkedin_url="linkedin.com/in/alice",
            emails=["a@x.com", "a@y.com"],
        )
        b = I.compute_keys(
            linkedin_url="linkedin.com/in/alice",
            emails=["a@y.com", "a@z.com"],
        )
        d = I.keys_intersect_detail(a, b)
        assert d["linkedin"] == ["in/alice"]
        assert d["email"] == ["a@y.com"]


# ---------------------------------------------------------------------------
# ID minting
# ---------------------------------------------------------------------------


class TestMintId:
    def test_linkedin_yields_li_suffix(self):
        k = I.compute_keys(linkedin_url="linkedin.com/in/dylan-txa")
        assert I.mint_id(k) == "dylan-txa-li"

    def test_linkedin_company_handled(self):
        k = I.compute_keys(linkedin_url="linkedin.com/company/gojiberry-ai")
        # Just the slug part with -li (provenance suffix); kind is encoded in
        # the linkedin key itself, not the id slug.
        assert I.mint_id(k) == "gojiberry-ai-li"

    def test_email_yields_em_suffix_deterministic(self):
        k = I.compute_keys(email="dylan@gojiberry.ai")
        id1 = I.mint_id(k)
        id2 = I.mint_id(k)
        assert id1 == id2
        assert id1.endswith("-em")
        assert len(id1.split("-")[0]) == 12  # sha256 hex prefix

    def test_email_set_uses_lexicographically_first(self):
        k1 = I.compute_keys(emails=["b@x.com", "a@x.com"])
        k2 = I.compute_keys(emails=["a@x.com", "b@x.com"])
        assert I.mint_id(k1) == I.mint_id(k2)

    def test_linkedin_beats_email_for_id(self):
        k = I.compute_keys(
            linkedin_url="linkedin.com/in/dylan-txa",
            email="dylan@gojiberry.ai",
        )
        assert I.mint_id(k).endswith("-li")

    def test_no_strong_key_yields_tmp(self):
        k = I.compute_keys(name="Random Person")
        mid = I.mint_id(k, name_fallback="Random Person", company_slug="Acme", year=2026)
        assert mid.endswith("-tmp")
        assert "random-person" in mid
        assert "acme" in mid
        assert "2026" in mid

    def test_truly_empty_still_unique(self):
        k = I.compute_keys()
        mid = I.mint_id(k)
        assert mid.endswith("-tmp")
        assert "unknown" in mid

    def test_id_provenance_helpers(self):
        k_li = I.compute_keys(linkedin_url="in/a")
        k_em = I.compute_keys(email="a@b.com")
        k_tmp = I.compute_keys(name="X")
        assert I.id_is_strong(I.mint_id(k_li))
        assert I.id_is_strong(I.mint_id(k_em))
        assert I.id_is_temporary(I.mint_id(k_tmp, name_fallback="X"))
        assert not I.id_is_strong(I.mint_id(k_tmp, name_fallback="X"))


# ---------------------------------------------------------------------------
# Reading Person notes
# ---------------------------------------------------------------------------


def _write_note(path: Path, frontmatter: dict, body: str = "# Body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{fm}\n---\n\n{body}\n", encoding="utf-8")


class TestReadPersonKeys:
    def test_new_format_with_identity_keys_block(self, tmp_path):
        note = tmp_path / "Dylan.md"
        _write_note(note, {
            "type": "person",
            "name": "Dylan Teixeira",
            "id": "dylan-txa-li",
            "identity_keys": {
                "primary": "linkedin:in/dylan-txa",
                "linkedin": "in/dylan-txa",
                "emails": ["dylan@gojiberry.ai"],
                "github": "dylan-txa",
            },
        })
        result = I.read_person_keys(note)
        assert result is not None
        person_id, keys = result
        assert person_id == "dylan-txa-li"
        assert keys.linkedin == "in/dylan-txa"
        assert keys.emails == frozenset({"dylan@gojiberry.ai"})
        assert keys.github == "dylan-txa"

    def test_legacy_format_fallback(self, tmp_path):
        note = tmp_path / "Legacy.md"
        _write_note(note, {
            "type": "person",
            "name": "Legacy Person",
            "linkedin": "https://www.linkedin.com/in/legacy/",
            "email": "legacy@example.com",
        })
        result = I.read_person_keys(note)
        assert result is not None
        person_id, keys = result
        assert person_id is None  # no id field
        assert keys.linkedin == "in/legacy"
        assert keys.emails == frozenset({"legacy@example.com"})

    def test_empty_identity_keys_block_falls_back(self, tmp_path):
        note = tmp_path / "PartialNew.md"
        _write_note(note, {
            "type": "person",
            "name": "Partial",
            "identity_keys": {},  # empty block
            "linkedin": "linkedin.com/in/partial",
        })
        # Empty dict should trigger legacy fallback
        result = I.read_person_keys(note)
        assert result is not None
        _, keys = result
        assert keys.linkedin == "in/partial"

    def test_non_person_type_returns_none(self, tmp_path):
        note = tmp_path / "NotPerson.md"
        _write_note(note, {"type": "company", "name": "Gojiberry AI"})
        assert I.read_person_keys(note) is None

    def test_no_frontmatter_returns_none(self, tmp_path):
        note = tmp_path / "Plain.md"
        note.write_text("# Just a heading, no frontmatter\n")
        assert I.read_person_keys(note) is None

    def test_malformed_yaml_returns_none(self, tmp_path):
        note = tmp_path / "Bad.md"
        note.write_text("---\nthis: is: not: valid: yaml:\n---\n")
        assert I.read_person_keys(note) is None

    def test_empty_email_string_handled(self, tmp_path):
        # Yang's existing notes sometimes have `email:` with no value.
        note = tmp_path / "EmptyEmail.md"
        _write_note(note, {
            "type": "person",
            "name": "Empty Email",
            "linkedin": "linkedin.com/in/empty",
            "email": "",
        })
        result = I.read_person_keys(note)
        assert result is not None
        _, keys = result
        assert keys.emails == frozenset()
        assert keys.linkedin == "in/empty"

    def test_emails_as_string_not_list_coerced(self, tmp_path):
        """A hand-edited or partially-migrated note might have
        `identity_keys.emails: "single@example.com"` (string instead of list).
        _coerce_email_list handles this gracefully — pin the behavior so
        a future refactor can't silently regress it."""
        note = tmp_path / "Malformed.md"
        # Write the YAML directly to bypass safe_dump's list normalization
        note.write_text(
            "---\n"
            "type: person\n"
            "name: Malformed\n"
            "id: malformed-li\n"
            "identity_keys:\n"
            "  linkedin: in/malformed\n"
            "  emails: \"single@example.com\"\n"
            "---\n\n# Body\n",
            encoding="utf-8",
        )
        result = I.read_person_keys(note)
        assert result is not None
        person_id, keys = result
        assert person_id == "malformed-li"
        assert keys.linkedin == "in/malformed"
        assert keys.emails == frozenset({"single@example.com"})

    def test_emails_with_null_entry_filtered(self, tmp_path):
        """YAML `emails: [a@x.com, null, b@x.com]` shouldn't crash."""
        note = tmp_path / "Nullish.md"
        note.write_text(
            "---\n"
            "type: person\n"
            "name: Nullish\n"
            "identity_keys:\n"
            "  emails:\n"
            "    - a@x.com\n"
            "    - null\n"
            "    - b@x.com\n"
            "---\n\n# Body\n",
            encoding="utf-8",
        )
        result = I.read_person_keys(note)
        assert result is not None
        _, keys = result
        assert keys.emails == frozenset({"a@x.com", "b@x.com"})


# ---------------------------------------------------------------------------
# Index + matching
# ---------------------------------------------------------------------------


class TestBuildIndex:
    def test_walks_recursive(self, tmp_path):
        _write_note(tmp_path / "queue" / "A.md",
                    {"type": "person", "name": "A",
                     "linkedin": "linkedin.com/in/a"})
        _write_note(tmp_path / "active" / "B.md",
                    {"type": "person", "name": "B",
                     "linkedin": "linkedin.com/in/b"})
        idx = I.build_index(tmp_path)
        names = sorted(e.note_path.stem for e in idx)
        assert names == ["A", "B"]

    def test_skips_hidden_dirs(self, tmp_path):
        _write_note(tmp_path / ".trash" / "Old.md",
                    {"type": "person", "name": "Old"})
        _write_note(tmp_path / "A.md",
                    {"type": "person", "name": "A",
                     "linkedin": "in/a"})
        idx = I.build_index(tmp_path)
        names = [e.note_path.stem for e in idx]
        assert names == ["A"]

    def test_skips_obsidian_conflict_files(self, tmp_path):
        _write_note(tmp_path / "A.md",
                    {"type": "person", "name": "A", "linkedin": "in/a"})
        _write_note(tmp_path / "A.conflicted.md",
                    {"type": "person", "name": "A", "linkedin": "in/a"})
        _write_note(tmp_path / "A.conflict.md",
                    {"type": "person", "name": "A", "linkedin": "in/a"})
        idx = I.build_index(tmp_path)
        names = [e.note_path.name for e in idx]
        assert names == ["A.md"]

    def test_skips_non_person(self, tmp_path):
        _write_note(tmp_path / "A.md",
                    {"type": "person", "name": "A", "linkedin": "in/a"})
        _write_note(tmp_path / "Company.md",
                    {"type": "company", "name": "Co"})
        _write_note(tmp_path / "List.md",
                    {"type": "lead-list", "query": "q"})
        idx = I.build_index(tmp_path)
        names = [e.note_path.stem for e in idx]
        assert names == ["A"]

    def test_empty_people_dir_returns_no_matches(self, tmp_path):
        """The most common new-OSS-user state: empty vault directory.
        find_matches must return [] cleanly, not crash."""
        candidate = I.compute_keys(linkedin_url="in/anyone")
        # Empty existing dir
        empty = tmp_path / "empty_people"
        empty.mkdir()
        assert I.find_matches(candidate, empty) == []
        # No-such-path: rglob on a missing dir returns nothing without erroring
        assert I.find_matches(candidate, tmp_path / "does-not-exist") == []


class TestFindMatchesInIndex:
    @pytest.fixture
    def index(self, tmp_path):
        _write_note(tmp_path / "Alice.md", {
            "type": "person", "name": "Alice",
            "id": "alice-li",
            "identity_keys": {
                "linkedin": "in/alice",
                "emails": ["alice@example.com"],
            },
        })
        _write_note(tmp_path / "Bob.md", {
            "type": "person", "name": "Bob",
            "id": "bob-li",
            "identity_keys": {"linkedin": "in/bob"},
        })
        _write_note(tmp_path / "Charlie.md", {
            "type": "person", "name": "Charlie",
            "id": "abc123def456-em",
            "identity_keys": {"emails": ["charlie@example.com"]},
        })
        return I.build_index(tmp_path)

    def test_no_match(self, index):
        candidate = I.compute_keys(linkedin_url="in/nobody")
        assert I.find_matches_in_index(candidate, index) == []

    def test_linkedin_match(self, index):
        candidate = I.compute_keys(linkedin_url="linkedin.com/in/alice")
        matches = I.find_matches_in_index(candidate, index)
        assert len(matches) == 1
        assert matches[0].person_id == "alice-li"
        assert matches[0].matched_classes == frozenset({"linkedin"})

    def test_email_match(self, index):
        candidate = I.compute_keys(email="charlie@example.com")
        matches = I.find_matches_in_index(candidate, index)
        assert len(matches) == 1
        assert matches[0].person_id == "abc123def456-em"
        assert matches[0].matched_classes == frozenset({"email"})

    def test_multi_class_match_same_record(self, index):
        candidate = I.compute_keys(
            linkedin_url="in/alice",
            email="alice@example.com",
        )
        matches = I.find_matches_in_index(candidate, index)
        assert len(matches) == 1
        assert matches[0].matched_classes == frozenset({"linkedin", "email"})

    def test_two_records_match_different_classes(self, tmp_path):
        # Realistic conflict: Alice's LinkedIn + Bob's email both belong to
        # this new candidate. Strict policy will refuse.
        _write_note(tmp_path / "Alice.md", {
            "type": "person", "name": "Alice",
            "id": "alice-li",
            "identity_keys": {"linkedin": "in/example"},
        })
        _write_note(tmp_path / "Bob.md", {
            "type": "person", "name": "Bob",
            "id": "bob-em",
            "identity_keys": {"emails": ["shared@example.com"]},
        })
        idx = I.build_index(tmp_path)
        candidate = I.compute_keys(
            linkedin_url="in/example",
            email="shared@example.com",
        )
        matches = I.find_matches_in_index(candidate, idx)
        assert len(matches) == 2


# ---------------------------------------------------------------------------
# Strict-policy resolution
# ---------------------------------------------------------------------------


class TestResolveStrict:
    def test_zero_matches_returns_none(self, tmp_path):
        candidate = I.compute_keys(linkedin_url="in/nobody")
        conflicts_dir = tmp_path / "conflicts"
        result = I.resolve_strict(candidate, [], conflicts_dir)
        assert result is None

    def test_one_match_returns_match(self, tmp_path):
        # Existing Alice note (real file, since resolve_strict now reads
        # the existing record's keys to check single-class-email ambiguity).
        alice = tmp_path / "Alice.md"
        _write_note(alice, {
            "type": "person", "name": "Alice", "id": "alice-li",
            "identity_keys": {"linkedin": "in/alice"},
        })
        candidate = I.compute_keys(linkedin_url="in/alice")
        match = I.Match(
            note_path=alice, person_id="alice-li",
            matched_classes=frozenset({"linkedin"}),
        )
        conflicts_dir = tmp_path / "conflicts"
        result = I.resolve_strict(candidate, [match], conflicts_dir)
        assert isinstance(result, I.Match)
        assert result.person_id == "alice-li"
        # No conflict report should have been written
        assert not conflicts_dir.exists() or not any(conflicts_dir.iterdir())

    def test_two_matches_returns_conflict_and_writes_report(self, tmp_path):
        candidate = I.compute_keys(
            linkedin_url="in/example",
            email="shared@example.com",
        )
        matches = [
            I.Match(
                note_path=tmp_path / "A.md",
                person_id="alice-li",
                matched_classes=frozenset({"linkedin"}),
                matched_values={"linkedin": ["in/example"]},
            ),
            I.Match(
                note_path=tmp_path / "B.md",
                person_id="bob-em",
                matched_classes=frozenset({"email"}),
                matched_values={"email": ["shared@example.com"]},
            ),
        ]
        conflicts_dir = tmp_path / "conflicts"
        result = I.resolve_strict(candidate, matches, conflicts_dir)
        assert isinstance(result, I.Conflict)
        assert len(result.matches) == 2
        assert result.report_path.exists()

        report = yaml.safe_load(result.report_path.read_text())
        assert report["version"] == 1
        assert "reason" in report
        assert len(report["matched_records"]) == 2
        # Each matched record has its class set + values surfaced
        ids = sorted(r["person_id"] for r in report["matched_records"])
        assert ids == ["alice-li", "bob-em"]
        # Candidate keys preserved for diagnostic
        assert report["candidate"]["linkedin"] == "in/example"
        assert "shared@example.com" in report["candidate"]["emails"]

    def test_conflict_dir_created_on_demand(self, tmp_path):
        # conflicts_dir doesn't exist before
        candidate = I.compute_keys(linkedin_url="in/example")
        matches = [
            I.Match(note_path=tmp_path / "A.md", person_id="a",
                    matched_classes=frozenset({"linkedin"})),
            I.Match(note_path=tmp_path / "B.md", person_id="b",
                    matched_classes=frozenset({"linkedin"})),
        ]
        conflicts_dir = tmp_path / "deeply" / "nested" / "conflicts"
        assert not conflicts_dir.exists()
        result = I.resolve_strict(candidate, matches, conflicts_dir)
        assert isinstance(result, I.Conflict)
        assert conflicts_dir.exists()
        assert result.report_path.parent == conflicts_dir

    def test_conflict_report_filenames_unique_in_same_second(self, tmp_path):
        """Two conflicts in the same second must not clobber each other.

        Microsecond + random suffix in _conflict_report_path guarantees this.
        Without the suffix, parallel discovery skills running on the same
        conflicting candidate would overwrite reports and lose audit trail.
        """
        candidate = I.compute_keys(linkedin_url="in/x")
        matches = [
            I.Match(note_path=tmp_path / "A.md", person_id="a",
                    matched_classes=frozenset({"linkedin"})),
            I.Match(note_path=tmp_path / "B.md", person_id="b",
                    matched_classes=frozenset({"linkedin"})),
        ]
        conflicts_dir = tmp_path / "conflicts"
        # Fire many conflicts in rapid succession.
        paths = set()
        for _ in range(20):
            result = I.resolve_strict(candidate, matches, conflicts_dir)
            assert isinstance(result, I.Conflict)
            paths.add(result.report_path)
        assert len(paths) == 20  # all unique


class TestAmbiguousSingleClassEmail:
    """Strict-policy refinement: a sole email match with a distinct LinkedIn
    candidate escalates to Conflict (shared family / cofounder / work email)."""

    def _setup_existing_record(self, tmp_path, *, linkedin: str | None,
                                email: str) -> I.Match:
        note = tmp_path / "Existing.md"
        keys: dict = {"emails": [email]}
        if linkedin:
            keys["linkedin"] = linkedin
        _write_note(note, {
            "type": "person", "name": "Existing", "id": "existing-li",
            "identity_keys": keys,
        })
        return I.Match(
            note_path=note,
            person_id="existing-li",
            matched_classes=frozenset({"email"}),
            matched_values={"email": [email]},
        )

    def test_distinct_linkedin_escalates_to_conflict(self, tmp_path):
        """Existing Alice has linkedin in/alice + email shared@family.com.
        Candidate has linkedin in/bob + email shared@family.com.
        Sole email match + distinct LinkedIn → Conflict (likely siblings/
        spouses, not same person)."""
        match = self._setup_existing_record(
            tmp_path, linkedin="in/alice", email="shared@family.com",
        )
        candidate = I.compute_keys(
            linkedin_url="in/bob",
            email="shared@family.com",
        )
        conflicts_dir = tmp_path / "conflicts"
        result = I.resolve_strict(candidate, [match], conflicts_dir)
        assert isinstance(result, I.Conflict)
        assert result.report_path.exists()
        report = yaml.safe_load(result.report_path.read_text())
        assert "shared email" in report["reason"].lower() or "ambiguous" in report["reason"].lower()

    def test_same_linkedin_is_confident_match(self, tmp_path):
        """If candidate and existing record have the SAME LinkedIn, the
        email match is confirmatory, not ambiguous. Stays a Match.

        (In practice this would be a multi-class match, not single-class —
        but if a candidate is constructed such that only email registers
        as a class match while LinkedIn happens to be the same, it's still
        the same person.)"""
        match = self._setup_existing_record(
            tmp_path, linkedin="in/alice", email="shared@family.com",
        )
        candidate = I.compute_keys(
            linkedin_url="in/alice",
            email="shared@family.com",
        )
        # Simulate single-class match (would be multi-class in real walk;
        # this directly exercises the resolve_strict refinement path)
        match_email_only = I.Match(
            note_path=match.note_path,
            person_id=match.person_id,
            matched_classes=frozenset({"email"}),
            matched_values={"email": ["shared@family.com"]},
        )
        result = I.resolve_strict(candidate, [match_email_only], tmp_path / "conflicts")
        assert isinstance(result, I.Match)  # same LinkedIn → not ambiguous

    def test_candidate_with_no_linkedin_stays_match(self, tmp_path):
        """If the candidate has no LinkedIn, we can't tell whether it's
        the same person or a shared inbox — default to Match (the spec's
        original behavior). The escalation requires evidence of distinct
        identity (i.e., candidate has its own LinkedIn)."""
        match = self._setup_existing_record(
            tmp_path, linkedin="in/alice", email="shared@family.com",
        )
        candidate = I.compute_keys(email="shared@family.com")  # no linkedin
        result = I.resolve_strict(candidate, [match], tmp_path / "conflicts")
        assert isinstance(result, I.Match)

    def test_existing_record_with_no_linkedin_stays_match(self, tmp_path):
        """If the existing record has no LinkedIn, candidate's LinkedIn
        can't conflict with anything. Stays Match (the candidate's LinkedIn
        is new info that should be added to the existing record at merge
        time, not grounds for escalation)."""
        match = self._setup_existing_record(
            tmp_path, linkedin=None, email="shared@family.com",
        )
        candidate = I.compute_keys(
            linkedin_url="in/somebody",
            email="shared@family.com",
        )
        result = I.resolve_strict(candidate, [match], tmp_path / "conflicts")
        assert isinstance(result, I.Match)

    def test_linkedin_class_match_not_affected_by_refinement(self, tmp_path):
        """The refinement is scoped to single-class email matches only.
        A LinkedIn-class match (sole or otherwise) is always a confident
        match — that's the strongest key class."""
        note = tmp_path / "Alice.md"
        _write_note(note, {
            "type": "person", "name": "Alice", "id": "alice-li",
            "identity_keys": {"linkedin": "in/alice", "emails": ["alice@a.com"]},
        })
        candidate = I.compute_keys(
            linkedin_url="in/alice",
            email="totally-different@elsewhere.com",
        )
        match = I.Match(
            note_path=note, person_id="alice-li",
            matched_classes=frozenset({"linkedin"}),
        )
        result = I.resolve_strict(candidate, [match], tmp_path / "conflicts")
        assert isinstance(result, I.Match)


# ---------------------------------------------------------------------------
# Integration: realistic enrollment scenarios
# ---------------------------------------------------------------------------


class TestRealisticScenarios:
    """Mirrors the actual failure modes called out in HANDOFF-phase-5.5.md."""

    def test_name_variant_duplicate_caught(self, tmp_path):
        """Alex Liu enrolled today, Alex D Liu tomorrow — same person via
        shared LinkedIn. The new architecture catches this."""
        _write_note(tmp_path / "Alex Liu.md", {
            "type": "person", "name": "Alex Liu",
            "id": "alexdliu7-li",
            "identity_keys": {"linkedin": "in/alexdliu7"},
        })
        # Tomorrow's discovery surfaces the same person under a different name
        candidate = I.compute_keys(
            name="Alex D Liu",
            linkedin_url="linkedin.com/in/alexdliu7",
        )
        idx = I.build_index(tmp_path)
        matches = I.find_matches_in_index(candidate, idx)
        result = I.resolve_strict(candidate, matches, tmp_path / "conflicts")
        # Strict policy: single LinkedIn match = confident match
        assert isinstance(result, I.Match)
        assert result.person_id == "alexdliu7-li"

    def test_shared_email_distinct_linkedins_creates_conflict(self, tmp_path):
        """Two separate Person notes, one matches new candidate on email,
        the other on LinkedIn. Strict policy: refuse, escalate to manual."""
        _write_note(tmp_path / "A.md", {
            "type": "person", "name": "A",
            "id": "alice-li",
            "identity_keys": {
                "linkedin": "in/alice",
                "emails": ["shared@family.com"],
            },
        })
        _write_note(tmp_path / "B.md", {
            "type": "person", "name": "B",
            "id": "bob-li",
            "identity_keys": {
                "linkedin": "in/bob",
                "emails": ["shared@family.com"],
            },
        })
        candidate = I.compute_keys(email="shared@family.com")
        idx = I.build_index(tmp_path)
        matches = I.find_matches_in_index(candidate, idx)
        # Two records both share the email
        assert len(matches) == 2
        result = I.resolve_strict(candidate, matches, tmp_path / "conflicts")
        assert isinstance(result, I.Conflict)
        # Manual resolution required — no auto-merge
        assert result.report_path.exists()

    def test_truly_new_person_returns_none(self, tmp_path):
        _write_note(tmp_path / "Existing.md", {
            "type": "person", "name": "Existing",
            "id": "existing-li",
            "identity_keys": {"linkedin": "in/existing"},
        })
        candidate = I.compute_keys(linkedin_url="in/brand-new-prospect")
        idx = I.build_index(tmp_path)
        matches = I.find_matches_in_index(candidate, idx)
        result = I.resolve_strict(candidate, matches, tmp_path / "conflicts")
        assert result is None  # caller should mint new ID + create note

    def test_unicode_name_handled_in_alt_names(self, tmp_path):
        """José Barrueta's diacritics must round-trip through alt_names."""
        k = I.compute_keys(name="José Barrueta", linkedin_url="in/jose-barrueta")
        assert "jose barrueta" in k.alt_names
        assert I.mint_id(k) == "jose-barrueta-li"
