"""Pillar A Week 3 — recipient timezone inference from country signal.

Tests for :mod:`orchestrator.policy.tz_inference`. The module maps a free-form
country signal (ISO 3166-1 alpha-2 code, full English country name, or a
``"city, country"`` style location string) to an IANA timezone, with a
fallback of ``America/Los_Angeles`` per ADR-0005 §Fallback (which adopts
PILLAR-PLAN §5's resolution row).

Test organization:
  TestISOCodeMapping — alpha-2 codes for the representative set
                        (US/GB/IN/AU/JP/DE/FR/CA/...) resolve correctly.
  TestCountryNameMapping — full names ("United States", "United Kingdom",
                            "Japan") resolve correctly.
  TestLocationStringExtraction — "San Francisco, USA", "London, UK",
                                   "Tokyo, Japan" — the country fragment
                                   is extracted and resolved.
  TestFallback — missing / None / empty / unrecognized country returns the
                  documented default (America/Los_Angeles).
  TestPropertyEveryReturnIsValidIANA — every value the inference function
                                        returns must be loadable by
                                        zoneinfo.ZoneInfo (no typos in
                                        the source table).
  TestCaseInsensitive — country signal is matched case-insensitively.
  TestStripAndNormalize — whitespace / punctuation around the signal don't
                            prevent matching.

The inference function is documented as accepting ``None`` so callers can
pass through an absent country signal without their own guard.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from orchestrator.policy import tz_inference


class TestISOCodeMapping:
    """Representative set of ISO 3166-1 alpha-2 codes for the countries the
    outreach-factory ICP actually encounters. Not exhaustive — Pillar E
    discovery quality will surface gaps that this test will then catch.
    """

    @pytest.mark.parametrize("code,expected", [
        ("US", "America/Los_Angeles"),
        ("GB", "Europe/London"),
        ("IN", "Asia/Kolkata"),
        ("AU", "Australia/Sydney"),
        ("JP", "Asia/Tokyo"),
        ("DE", "Europe/Berlin"),
        ("FR", "Europe/Paris"),
        ("CA", "America/Toronto"),
        ("SG", "Asia/Singapore"),
        ("BR", "America/Sao_Paulo"),
        ("CN", "Asia/Shanghai"),
        ("KR", "Asia/Seoul"),
        ("NL", "Europe/Amsterdam"),
        ("IE", "Europe/Dublin"),
        ("CH", "Europe/Zurich"),
        ("SE", "Europe/Stockholm"),
        ("ES", "Europe/Madrid"),
        ("IT", "Europe/Rome"),
        ("IL", "Asia/Jerusalem"),
        ("AE", "Asia/Dubai"),
        ("NZ", "Pacific/Auckland"),
    ])
    def test_iso_alpha2_resolves(self, code, expected):
        assert tz_inference.infer_timezone(code) == expected


class TestCountryNameMapping:
    @pytest.mark.parametrize("name,expected", [
        ("United States", "America/Los_Angeles"),
        ("USA", "America/Los_Angeles"),
        ("United Kingdom", "Europe/London"),
        ("UK", "Europe/London"),
        ("Great Britain", "Europe/London"),
        ("Japan", "Asia/Tokyo"),
        ("India", "Asia/Kolkata"),
        ("Australia", "Australia/Sydney"),
        ("Germany", "Europe/Berlin"),
        ("France", "Europe/Paris"),
        ("Canada", "America/Toronto"),
        ("Singapore", "Asia/Singapore"),
        ("Brazil", "America/Sao_Paulo"),
        ("Netherlands", "Europe/Amsterdam"),
    ])
    def test_full_name_resolves(self, name, expected):
        assert tz_inference.infer_timezone(name) == expected


class TestLocationStringExtraction:
    """Person notes often store location as a ``"City, Country"`` string
    (per ``skills/research-prospect/SKILL.md`` §Person file frontmatter).
    The inference function tolerates this shape by extracting the trailing
    country fragment.
    """

    @pytest.mark.parametrize("location,expected", [
        ("San Francisco, USA", "America/Los_Angeles"),
        ("London, UK", "Europe/London"),
        ("Tokyo, Japan", "Asia/Tokyo"),
        ("Bangalore, India", "Asia/Kolkata"),
        ("Sydney, Australia", "Australia/Sydney"),
        ("Berlin, Germany", "Europe/Berlin"),
        ("Paris, France", "Europe/Paris"),
        ("Toronto, Canada", "America/Toronto"),
    ])
    def test_city_country_string_resolves(self, location, expected):
        assert tz_inference.infer_timezone(location) == expected

    def test_only_city_no_country_falls_back(self):
        """Just a city name — no country signal — falls back to default."""
        # "Springfield" matches no country.
        assert tz_inference.infer_timezone("Springfield") == \
            tz_inference.DEFAULT_TIMEZONE


class TestFallback:
    """Per ADR-0005 §Fallback (formally cites PILLAR-PLAN §5): the default
    when the country signal cannot be resolved is ``America/Los_Angeles``.

    This default reflects the operator's expectation, not a recipient
    one (the operator is US-Pacific-based; a recipient with no known
    country is most likely already in the operator's local region or
    close enough that an operator-local window is a reasonable
    approximation). Pillar I (multi-tenant) will let operators override.
    """

    def test_none_falls_back(self):
        assert tz_inference.infer_timezone(None) == tz_inference.DEFAULT_TIMEZONE

    def test_empty_string_falls_back(self):
        assert tz_inference.infer_timezone("") == tz_inference.DEFAULT_TIMEZONE

    def test_whitespace_only_falls_back(self):
        assert tz_inference.infer_timezone("   ") == \
            tz_inference.DEFAULT_TIMEZONE

    def test_unrecognized_country_falls_back(self):
        assert tz_inference.infer_timezone("Atlantis") == \
            tz_inference.DEFAULT_TIMEZONE

    def test_default_timezone_constant_is_americas_los_angeles(self):
        """ADR-0005 cites PILLAR-PLAN §5 for this fallback. The constant
        name is part of the module API — if we ever change the default,
        ADR-0005 must be amended in the same commit."""
        assert tz_inference.DEFAULT_TIMEZONE == "America/Los_Angeles"


class TestPropertyEveryReturnIsValidIANA:
    """Every IANA name in the country table must load via
    ``zoneinfo.ZoneInfo`` on the test system. Without this property a
    typo in the table (``Asia/Sigapore``, ``Pacific/Aukland``) would only
    surface at runtime in the rule's ``_local_now`` call — where it would
    look like a recipient-data bug, not a source-code bug. Catching it in
    a unit test means the fix happens at the right layer.
    """

    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        # Sample from every key in the table (codes + names + location
        # strings derived from the names). The infer function returns a
        # str; we just need to assert the result is loadable.
        country=st.one_of(
            st.sampled_from(list(tz_inference.COUNTRY_CODE_TO_TIMEZONE)),
            st.sampled_from(list(tz_inference.COUNTRY_NAME_TO_TIMEZONE)),
            st.none(),
        ),
    )
    def test_every_inferred_tz_is_loadable(self, country):
        tz_name = tz_inference.infer_timezone(country)
        # Should NOT raise ZoneInfoNotFoundError.
        ZoneInfo(tz_name)

    def test_every_country_code_table_entry_is_valid_iana(self):
        """Direct sweep of the alpha-2 table — every value loads."""
        for code, tz_name in tz_inference.COUNTRY_CODE_TO_TIMEZONE.items():
            try:
                ZoneInfo(tz_name)
            except ZoneInfoNotFoundError:
                pytest.fail(
                    f"COUNTRY_CODE_TO_TIMEZONE[{code!r}] = {tz_name!r} "
                    f"is not a valid IANA timezone on this system",
                )

    def test_every_country_name_table_entry_is_valid_iana(self):
        for name, tz_name in tz_inference.COUNTRY_NAME_TO_TIMEZONE.items():
            try:
                ZoneInfo(tz_name)
            except ZoneInfoNotFoundError:
                pytest.fail(
                    f"COUNTRY_NAME_TO_TIMEZONE[{name!r}] = {tz_name!r} "
                    f"is not a valid IANA timezone on this system",
                )


class TestCaseInsensitive:
    @pytest.mark.parametrize("variant", [
        "US", "us", "Us", "uS",
    ])
    def test_iso_code_case_insensitive(self, variant):
        assert tz_inference.infer_timezone(variant) == "America/Los_Angeles"

    @pytest.mark.parametrize("variant", [
        "United States", "united states", "UNITED STATES", "United states",
    ])
    def test_country_name_case_insensitive(self, variant):
        assert tz_inference.infer_timezone(variant) == "America/Los_Angeles"


class TestStripAndNormalize:
    def test_whitespace_stripped(self):
        assert tz_inference.infer_timezone("  Japan  ") == "Asia/Tokyo"

    def test_trailing_punctuation_in_location(self):
        # "London, UK." with trailing period.
        assert tz_inference.infer_timezone("London, UK.") == "Europe/London"

    def test_multi_comma_location_uses_last_segment(self):
        # Some notes have "London, England, UK" — the country (last) wins.
        assert tz_inference.infer_timezone("London, England, UK") == \
            "Europe/London"
