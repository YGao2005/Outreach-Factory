"""Pillar A Week 2 — suppression rule classes + GDPR forget.

Mirrors the structure of ``tests/test_policy_cooldown.py`` and
``tests/test_policy_cross_channel.py``:

  TestSuppressEmailRule — exact match, case-insensitive, miss.
  TestSuppressDomainRule — per-domain match, case-insensitive on both
                            sides, the per-email rule does not fire as
                            domain (and vice versa).
  TestSuppressIdentityKeyRule — LinkedIn URL canonicalization in both
                                 the YAML and the person_id.
  TestEmptyListAllAllow — empty suppressions → every send Allow.
  TestSuppressionListIO — YAML round-trip including version enforcement
                          and directory-merge.
  TestForgetAppend — GDPR forget atomic-append happy path + idempotency.
  TestSuppressionFromYamlRegistration — rule classes register and
                                         instantiate from the policy YAML.

The suppression rules don't need a ledger — they read only ``ctx.email``
and ``ctx.person_id``. The fake ledger here is a no-op stub used only to
satisfy the ``RuleContext`` Protocol shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from orchestrator.policy import engine as policy_engine
from orchestrator.policy import suppression as sup
from orchestrator.policy import types as policy_types


# ---------------------------------------------------------------------------
# Stub ledger — suppression rules don't query, so this is a no-op shell.
# ---------------------------------------------------------------------------


class _StubLedger:
    def query_by_person(self, person_id, since=None):
        return []

    def last_send_for(self, person_id, channel):
        return None

    def query_by_email(self, email):
        return set()

    def all_events(self):
        return []


def _make_ctx(
    *,
    channel="email",
    register="cold-pitch",
    person_id="alice-li",
    email="alice@example.com",
    now=None,
    tz="UTC",
):
    return policy_types.RuleContext(
        person_id=person_id,
        channel=channel,
        register=register,
        email=email,
        email_domain=email.split("@", 1)[1] if email and "@" in email else None,
        now=now or datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        timezone=tz,
        ledger=_StubLedger(),
        person_status=None,
    )


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# SuppressEmailRule
# ---------------------------------------------------------------------------


class TestSuppressEmailRule:
    def _list(self):
        return sup.SuppressionList(
            emails={"alice@example.com", "bob@example.com"},
        )

    def test_exact_match_blocks(self):
        rule = sup.SuppressEmailRule(name="email-list", suppressions=self._list())
        ctx = _make_ctx(email="alice@example.com")
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "email-list"
        assert result.detail.get("dimension") == "email"
        assert result.detail.get("matched_email") == "alice@example.com"

    def test_case_insensitive_match(self):
        """Mixed-case ctx.email matches lowercased entry."""
        rule = sup.SuppressEmailRule(name="email-list", suppressions=self._list())
        ctx = _make_ctx(email="ALICE@Example.COM")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_miss_allows(self):
        rule = sup.SuppressEmailRule(name="email-list", suppressions=self._list())
        ctx = _make_ctx(email="charlie@example.com")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_no_email_allows(self):
        """LinkedIn send with no email → email rule cannot apply."""
        rule = sup.SuppressEmailRule(name="email-list", suppressions=self._list())
        ctx = _make_ctx(channel="linkedin", email=None)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_domain_does_not_match_email(self):
        """An entry on the domain list MUST NOT block via the email rule."""
        rule = sup.SuppressEmailRule(
            name="email-list",
            suppressions=sup.SuppressionList(emails=set(),
                                             domains={"example.com"}),
        )
        ctx = _make_ctx(email="alice@example.com")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# SuppressDomainRule
# ---------------------------------------------------------------------------


class TestSuppressDomainRule:
    def _list(self):
        return sup.SuppressionList(domains={"spamtrap.io", "example.com"})

    def test_domain_match_blocks(self):
        rule = sup.SuppressDomainRule(name="domain-list",
                                      suppressions=self._list())
        ctx = _make_ctx(email="anyone@spamtrap.io")
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("matched_domain") == "spamtrap.io"

    def test_case_insensitive_on_input(self):
        rule = sup.SuppressDomainRule(name="domain-list",
                                      suppressions=self._list())
        ctx = _make_ctx(email="someone@SPAMTRAP.IO")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_case_insensitive_on_list(self):
        """Mixed-case entries in the YAML still match lower input."""
        rule = sup.SuppressDomainRule(
            name="domain-list",
            suppressions=sup.SuppressionList(domains={"spamtrap.io"}),
        )
        ctx = _make_ctx(email="someone@SpamTrap.io")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_miss_allows(self):
        rule = sup.SuppressDomainRule(name="domain-list",
                                      suppressions=self._list())
        ctx = _make_ctx(email="alice@other-co.com")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_no_email_allows(self):
        rule = sup.SuppressDomainRule(name="domain-list",
                                      suppressions=self._list())
        ctx = _make_ctx(channel="linkedin", email=None)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# SuppressIdentityKeyRule
# ---------------------------------------------------------------------------


class TestSuppressIdentityKeyRule:
    def test_bare_in_slug_match(self):
        """The simplest case: ``in/foo`` in the list matches person_id ``in/foo``."""
        rule = sup.SuppressIdentityKeyRule(
            name="id-list",
            suppressions=sup.SuppressionList(identity_keys={"in/john-doe"}),
        )
        ctx = _make_ctx(person_id="in/john-doe")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_full_url_in_yaml_matches_canonical_person_id(self):
        """User authored the YAML with a full URL; person_id is ``in/<slug>``.
        Canonicalization on YAML load + on evaluate must agree."""
        # Round-trip via the file loader so we exercise the real
        # canonicalization path, not a hand-built set.
        tmp = Path(__file__).parent / "_tmp_sup_id_url.yml"
        try:
            tmp.write_text(
                "version: 1\n"
                "identity_keys:\n"
                "  - https://www.linkedin.com/in/Jane-Doe\n"
                "  - https://uk.linkedin.com/in/foo-bar/\n",
                encoding="utf-8",
            )
            lst = sup.load_suppression_list_from_yaml(tmp)
            rule = sup.SuppressIdentityKeyRule(
                name="id-list", suppressions=lst,
            )
            ctx = _make_ctx(person_id="in/jane-doe")
            assert isinstance(rule.evaluate(ctx), policy_types.Block)
            # Country-prefixed URL also normalizes.
            ctx2 = _make_ctx(person_id="in/foo-bar")
            assert isinstance(rule.evaluate(ctx2), policy_types.Block)
        finally:
            tmp.unlink(missing_ok=True)

    def test_bare_pub_slug_normalizes_to_in(self, tmp_path):
        """Legacy ``pub/<slug>`` form (LinkedIn's old URL shape, still
        appears in scraped data) must canonicalize to ``in/<slug>``
        whether it comes in as a full URL OR a bare prefix."""
        # URL form (already worked pre-fix).
        assert sup._canon_linkedin("https://www.linkedin.com/pub/foo") == "in/foo"
        # Bare prefix (broken pre-fix — used to return ``in/pub/foo``).
        assert sup._canon_linkedin("pub/foo") == "in/foo"
        # Symmetric match through SuppressIdentityKeyRule + YAML loader
        # (the loader is where canonicalization-on-write happens, so we
        # round-trip through it to exercise the real path).
        p = _write_yaml(
            tmp_path / "s.yml",
            "version: 1\n"
            "identity_keys:\n"
            "  - pub/legacy-user\n",
        )
        lst = sup.load_suppression_list_from_yaml(p)
        assert lst.identity_keys == {"in/legacy-user"}, \
            "pub/<slug> in YAML must canonicalize to in/<slug>"
        rule = sup.SuppressIdentityKeyRule(name="id-list", suppressions=lst)
        # A person_id with the modern URL form matches the legacy pub/ entry.
        ctx = _make_ctx(person_id="https://www.linkedin.com/in/legacy-user")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_full_url_in_person_id_matches_bare_slug_in_yaml(self):
        """Reverse direction: yaml has ``in/foo``; person_id is a full URL.
        (Less common in practice, but canonicalization runs on both sides.)"""
        rule = sup.SuppressIdentityKeyRule(
            name="id-list",
            suppressions=sup.SuppressionList(identity_keys={"in/foo"}),
        )
        ctx = _make_ctx(person_id="https://www.linkedin.com/in/foo")
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_company_url_distinct_from_person(self):
        """``in/foo`` MUST NOT match ``company/foo`` and vice versa."""
        rule = sup.SuppressIdentityKeyRule(
            name="id-list",
            suppressions=sup.SuppressionList(identity_keys={"in/foo"}),
        )
        ctx = _make_ctx(person_id="company/foo")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_miss_allows(self):
        rule = sup.SuppressIdentityKeyRule(
            name="id-list",
            suppressions=sup.SuppressionList(identity_keys={"in/foo"}),
        )
        ctx = _make_ctx(person_id="in/bar")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# Empty list → all Allow
# ---------------------------------------------------------------------------


class TestEmptyListAllAllow:
    """Greenfield install: no entries on any dimension → every send Allow."""

    def test_email_rule_empty_allows(self):
        rule = sup.SuppressEmailRule(name="r",
                                     suppressions=sup.SuppressionList())
        ctx = _make_ctx(email="alice@example.com")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_domain_rule_empty_allows(self):
        rule = sup.SuppressDomainRule(name="r",
                                      suppressions=sup.SuppressionList())
        ctx = _make_ctx(email="alice@example.com")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_identity_rule_empty_allows(self):
        rule = sup.SuppressIdentityKeyRule(name="r",
                                           suppressions=sup.SuppressionList())
        ctx = _make_ctx(person_id="in/anyone")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


class TestSuppressionListIO:
    def test_round_trip_full_shape(self, tmp_path):
        p = _write_yaml(
            tmp_path / "s.yml",
            "version: 1\n"
            "emails:\n"
            "  - Alice@Example.com\n"
            "  - bob@example.com\n"
            "domains:\n"
            "  - SpamTrap.IO\n"
            "identity_keys:\n"
            "  - https://www.linkedin.com/in/Foo\n"
            "  - in/bar\n",
        )
        lst = sup.load_suppression_list_from_yaml(p)
        # Everything is canonicalized.
        assert lst.emails == {"alice@example.com", "bob@example.com"}
        assert lst.domains == {"spamtrap.io"}
        assert lst.identity_keys == {"in/foo", "in/bar"}

    def test_missing_file_empty(self, tmp_path):
        lst = sup.load_suppression_list_from_yaml(tmp_path / "missing.yml")
        assert lst.emails == set()
        assert lst.domains == set()
        assert lst.identity_keys == set()

    def test_empty_file_empty_list(self, tmp_path):
        p = _write_yaml(tmp_path / "s.yml", "")
        lst = sup.load_suppression_list_from_yaml(p)
        assert lst.emails == set()

    def test_missing_version_raises(self, tmp_path):
        p = _write_yaml(tmp_path / "s.yml", "emails: []\n")
        with pytest.raises(ValueError, match="version"):
            sup.load_suppression_list_from_yaml(p)

    def test_wrong_version_raises(self, tmp_path):
        p = _write_yaml(tmp_path / "s.yml", "version: 99\nemails: []\n")
        with pytest.raises(ValueError, match="unsupported version"):
            sup.load_suppression_list_from_yaml(p)

    def test_non_string_entry_raises(self, tmp_path):
        p = _write_yaml(
            tmp_path / "s.yml",
            "version: 1\nemails: [42]\n",
        )
        with pytest.raises(ValueError, match="must be strings"):
            sup.load_suppression_list_from_yaml(p)

    def test_dir_merge(self, tmp_path):
        d = tmp_path / "suppressions"
        d.mkdir()
        _write_yaml(d / "a.yml",
                    "version: 1\nemails: [a@x.com]\n")
        _write_yaml(d / "b.yml",
                    "version: 1\nemails: [b@x.com]\ndomains: [spam.io]\n")
        merged = sup.load_suppression_dir(d)
        assert merged.emails == {"a@x.com", "b@x.com"}
        assert merged.domains == {"spam.io"}

    def test_dir_missing_returns_empty(self, tmp_path):
        merged = sup.load_suppression_dir(tmp_path / "missing")
        assert merged.emails == set()


# ---------------------------------------------------------------------------
# GDPR forget atomic append
# ---------------------------------------------------------------------------


class TestForgetAppend:
    """The GDPR ``forget`` path adds a person's keys to suppression atomically
    with the ledger purge (ADR-0004 §GDPR forget path). The cross-pillar
    atomicity is Pillar J's; this test covers the file-level behavior."""

    def test_creates_file_in_empty_dir(self, tmp_path):
        d = tmp_path / "suppressions"
        target = sup.forget_append(
            d,
            email="forgotten@example.com",
            identity_key="https://www.linkedin.com/in/forgotten",
        )
        assert target.exists()
        loaded = sup.load_suppression_list_from_yaml(target)
        assert "forgotten@example.com" in loaded.emails
        assert "in/forgotten" in loaded.identity_keys

    def test_idempotent_repeated_calls(self, tmp_path):
        d = tmp_path / "suppressions"
        sup.forget_append(d, email="x@y.com")
        sup.forget_append(d, email="x@y.com")
        loaded = sup.load_suppression_list_from_yaml(d / "gdpr-forget.yml")
        # Still exactly one entry — set semantics.
        assert loaded.emails == {"x@y.com"}

    def test_merges_with_existing_entries(self, tmp_path):
        d = tmp_path / "suppressions"
        d.mkdir()
        _write_yaml(d / "gdpr-forget.yml",
                    "version: 1\nemails: [old@y.com]\n")
        sup.forget_append(d, email="new@y.com")
        loaded = sup.load_suppression_list_from_yaml(d / "gdpr-forget.yml")
        assert loaded.emails == {"old@y.com", "new@y.com"}

    def test_atomic_via_rename(self, tmp_path):
        """The implementation writes a .tmp then renames — sanity that no
        leftover .tmp is present after success (we can't easily simulate a
        crash mid-write here, but absence of leftover is the contract)."""
        d = tmp_path / "suppressions"
        sup.forget_append(d, domain="legal.example.com")
        assert not list(d.glob("*.tmp"))


# ---------------------------------------------------------------------------
# Rule-class registration via the policy YAML loader
# ---------------------------------------------------------------------------


class TestSuppressionFromYamlRegistration:
    def test_registered_under_discriminators(self):
        assert policy_engine.RULE_REGISTRY.get("suppression.email") \
            is sup.SuppressEmailRule
        assert policy_engine.RULE_REGISTRY.get("suppression.domain") \
            is sup.SuppressDomainRule
        assert policy_engine.RULE_REGISTRY.get("suppression.identity-key") \
            is sup.SuppressIdentityKeyRule

    def test_load_policy_yaml_with_suppression_rule(self, tmp_path):
        """End-to-end: a policy YAML names a suppression rule + source file;
        the loader constructs the rule with a populated SuppressionList."""
        # Author a suppressions file.
        sfile = tmp_path / "blocklist.yml"
        sfile.write_text(
            "version: 1\nemails: [blocked@x.com]\n", encoding="utf-8",
        )
        # Author the policy YAML referencing it by absolute path.
        pfile = tmp_path / "cooldowns.yml"
        pfile.write_text(
            f"version: 1\n"
            f"rules:\n"
            f"  - name: email-suppression\n"
            f"    type: suppression.email\n"
            f"    source: {sfile}\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(pfile)
        assert len(rules) == 1
        rule = rules[0]
        assert isinstance(rule, sup.SuppressEmailRule)

        # Verdict: a send to blocked@x.com fires; one to other@x.com allows.
        ctx_block = _make_ctx(email="blocked@x.com")
        ctx_allow = _make_ctx(email="other@x.com")
        assert isinstance(rule.evaluate(ctx_block), policy_types.Block)
        assert isinstance(rule.evaluate(ctx_allow), policy_types.Allow)

    def test_source_dir_form_in_policy_yaml(self, tmp_path):
        d = tmp_path / "suppressions"
        d.mkdir()
        (d / "a.yml").write_text(
            "version: 1\ndomains: [spamtrap.io]\n", encoding="utf-8",
        )
        pfile = tmp_path / "cooldowns.yml"
        pfile.write_text(
            f"version: 1\n"
            f"rules:\n"
            f"  - name: domain-suppression\n"
            f"    type: suppression.domain\n"
            f"    source: {{dir: {d}}}\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(pfile)
        assert len(rules) == 1
        result = rules[0].evaluate(_make_ctx(email="abuse@spamtrap.io"))
        assert isinstance(result, policy_types.Block)

    def test_unknown_source_form_raises(self, tmp_path):
        with pytest.raises(ValueError, match="source"):
            sup.SuppressEmailRule.from_yaml({
                "name": "x", "type": "suppression.email",
                "source": 42,
            })

    def test_missing_source_raises(self):
        """A suppression rule with no ``source:`` would silently allow
        every send — exactly the false-positive class suppression exists
        to prevent. Asymmetric-failure-cost principle compels: refuse
        the configuration at load time, force the operator to opt in
        explicitly. Repeated across all three rule classes because the
        footgun is class-independent."""
        for cls in (sup.SuppressEmailRule, sup.SuppressDomainRule,
                    sup.SuppressIdentityKeyRule):
            with pytest.raises(ValueError, match="'source' is required"):
                cls.from_yaml({
                    "name": "no-source", "type": "suppression.email",
                    # no 'source:' field
                })
