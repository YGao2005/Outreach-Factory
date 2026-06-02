"""Pillar A Week 3 — recipient timezone inference from a country signal.

Sending-window rules (ADR-0005) need the recipient's IANA timezone to
evaluate local-time-of-day and local-weekday windows. The recipient's
``identity_keys.country`` signal (added in this same Week 3 commit) is
the source of truth; this module maps it to a concrete IANA name.

Public API
----------
``infer_timezone(country: str | None) -> str``
    Free-form country signal in, IANA timezone name out. Accepts:

    * ISO 3166-1 alpha-2 code (``"US"``, ``"gb"``).
    * Full English country name (``"Japan"``, ``"United States"``,
      ``"USA"``).
    * ``"City, Country"`` location strings as stored in Person notes
      (``"San Francisco, USA"``, ``"London, UK"``).
    * ``None`` / empty / unrecognized → ``DEFAULT_TIMEZONE``.

``DEFAULT_TIMEZONE``
    The fallback when the country cannot be resolved. Per ADR-0002 §5
    resolution row (carried forward into ADR-0005 §Fallback): the
    operator-local Pacific timezone. Future-Pillar-I (multi-tenant) will
    let operators override this default per-deployment.

``COUNTRY_CODE_TO_TIMEZONE``, ``COUNTRY_NAME_TO_TIMEZONE``
    The two lookup tables. Module-level constants — readable by callers
    (Pillar E discovery quality may want to validate that scraped country
    codes are in the supported set) and by tests (a property test
    enforces every value is a valid IANA name on this system).

Why a source-code table, not a JSON / YAML data file?
-----------------------------------------------------
1. The table is < 100 entries; a Python dict literal is more readable than
   a JSON file with quotes around every key/value.
2. Hot-path lookup is dict-O(1) without parsing on every invocation.
3. The asymmetric-failure-cost principle: a JSON file could go missing /
   parse-fail at runtime; a Python dict cannot. Sending-window rule
   evaluation must not crash on missing data.
4. Pillar B's migration framework can change *consumers* of the table
   when the schema evolves; the table itself doesn't carry user-authored
   data needing versioning.

ADR-0005 records the choice + the country→tz fallback table location.
"""

from __future__ import annotations


DEFAULT_TIMEZONE = "America/Los_Angeles"


# ISO 3166-1 alpha-2 codes → IANA timezone.
#
# Each entry names a single representative zone for the country. Countries
# spanning multiple zones (US, RU, AU, BR, CA, CN, ID) pick the zone where
# the highest concentration of the ICP audience lives — i.e. the zone the
# operator most likely intended when they wrote "country: US". A future
# Pillar E enhancement can refine this with a state/province signal when
# available; until then "country" alone is the coarsest reasonable
# granularity.
#
# The set covers the ~50 most common ICP countries; coverage gaps surface
# as the fallback path (DEFAULT_TIMEZONE). The property test
# ``test_every_country_code_table_entry_is_valid_iana`` enforces zero
# typos in this table.
COUNTRY_CODE_TO_TIMEZONE: dict[str, str] = {
    # Americas
    "US": "America/Los_Angeles",      # operator-local default for US
    "CA": "America/Toronto",          # Eastern is the highest-population CA zone
    "MX": "America/Mexico_City",
    "BR": "America/Sao_Paulo",
    "AR": "America/Argentina/Buenos_Aires",
    "CL": "America/Santiago",
    "CO": "America/Bogota",
    "PE": "America/Lima",
    # Europe
    "GB": "Europe/London",
    "IE": "Europe/Dublin",
    "FR": "Europe/Paris",
    "DE": "Europe/Berlin",
    "NL": "Europe/Amsterdam",
    "BE": "Europe/Brussels",
    "ES": "Europe/Madrid",
    "PT": "Europe/Lisbon",
    "IT": "Europe/Rome",
    "CH": "Europe/Zurich",
    "AT": "Europe/Vienna",
    "SE": "Europe/Stockholm",
    "NO": "Europe/Oslo",
    "DK": "Europe/Copenhagen",
    "FI": "Europe/Helsinki",
    "PL": "Europe/Warsaw",
    "CZ": "Europe/Prague",
    "GR": "Europe/Athens",
    "RO": "Europe/Bucharest",
    "UA": "Europe/Kyiv",
    "RU": "Europe/Moscow",
    "TR": "Europe/Istanbul",
    "IS": "Atlantic/Reykjavik",
    "EE": "Europe/Tallinn",
    # Middle East
    "IL": "Asia/Jerusalem",
    "AE": "Asia/Dubai",
    "SA": "Asia/Riyadh",
    "QA": "Asia/Qatar",
    # Asia
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "TW": "Asia/Taipei",
    "SG": "Asia/Singapore",
    "MY": "Asia/Kuala_Lumpur",
    "TH": "Asia/Bangkok",
    "VN": "Asia/Ho_Chi_Minh",
    "PH": "Asia/Manila",
    "ID": "Asia/Jakarta",
    "IN": "Asia/Kolkata",
    "PK": "Asia/Karachi",
    "BD": "Asia/Dhaka",
    # Oceania
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
    # Africa
    "ZA": "Africa/Johannesburg",
    "EG": "Africa/Cairo",
    "NG": "Africa/Lagos",
    "KE": "Africa/Nairobi",
    "MA": "Africa/Casablanca",
}


# Full English country names and common aliases → IANA timezone.
#
# Authoring discipline: every entry's *value* must equal the same key's
# alpha-2 value in COUNTRY_CODE_TO_TIMEZONE (verified by the test
# ``test_country_name_aliases_are_consistent_with_codes``). The aliases
# (``"USA"``, ``"UK"``, ``"Great Britain"``) exist because Person notes
# scraped from LinkedIn use them inconsistently.
COUNTRY_NAME_TO_TIMEZONE: dict[str, str] = {
    # Americas
    "united states": "America/Los_Angeles",
    "usa": "America/Los_Angeles",
    "u.s.": "America/Los_Angeles",
    "u.s.a.": "America/Los_Angeles",
    "america": "America/Los_Angeles",
    "canada": "America/Toronto",
    "mexico": "America/Mexico_City",
    "brazil": "America/Sao_Paulo",
    "argentina": "America/Argentina/Buenos_Aires",
    "chile": "America/Santiago",
    "colombia": "America/Bogota",
    "peru": "America/Lima",
    # Europe
    "united kingdom": "Europe/London",
    "uk": "Europe/London",
    "u.k.": "Europe/London",
    "great britain": "Europe/London",
    "britain": "Europe/London",
    "england": "Europe/London",
    "scotland": "Europe/London",
    "wales": "Europe/London",
    "northern ireland": "Europe/London",
    "ireland": "Europe/Dublin",
    "france": "Europe/Paris",
    "germany": "Europe/Berlin",
    "netherlands": "Europe/Amsterdam",
    "holland": "Europe/Amsterdam",
    "belgium": "Europe/Brussels",
    "spain": "Europe/Madrid",
    "portugal": "Europe/Lisbon",
    "italy": "Europe/Rome",
    "switzerland": "Europe/Zurich",
    "austria": "Europe/Vienna",
    "sweden": "Europe/Stockholm",
    "norway": "Europe/Oslo",
    "denmark": "Europe/Copenhagen",
    "finland": "Europe/Helsinki",
    "poland": "Europe/Warsaw",
    "czech republic": "Europe/Prague",
    "czechia": "Europe/Prague",
    "greece": "Europe/Athens",
    "romania": "Europe/Bucharest",
    "ukraine": "Europe/Kyiv",
    "russia": "Europe/Moscow",
    "turkey": "Europe/Istanbul",
    "türkiye": "Europe/Istanbul",
    "iceland": "Atlantic/Reykjavik",
    "estonia": "Europe/Tallinn",
    # Middle East
    "israel": "Asia/Jerusalem",
    "united arab emirates": "Asia/Dubai",
    "uae": "Asia/Dubai",
    "u.a.e.": "Asia/Dubai",
    "saudi arabia": "Asia/Riyadh",
    "qatar": "Asia/Qatar",
    # Asia
    "japan": "Asia/Tokyo",
    "south korea": "Asia/Seoul",
    "korea": "Asia/Seoul",
    "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "taiwan": "Asia/Taipei",
    "singapore": "Asia/Singapore",
    "malaysia": "Asia/Kuala_Lumpur",
    "thailand": "Asia/Bangkok",
    "vietnam": "Asia/Ho_Chi_Minh",
    "philippines": "Asia/Manila",
    "indonesia": "Asia/Jakarta",
    "india": "Asia/Kolkata",
    "pakistan": "Asia/Karachi",
    "bangladesh": "Asia/Dhaka",
    # Oceania
    "australia": "Australia/Sydney",
    "new zealand": "Pacific/Auckland",
    # Africa
    "south africa": "Africa/Johannesburg",
    "egypt": "Africa/Cairo",
    "nigeria": "Africa/Lagos",
    "kenya": "Africa/Nairobi",
    "morocco": "Africa/Casablanca",
}


def infer_timezone(country: str | None) -> str:
    """Return the IANA timezone for a country signal, or ``DEFAULT_TIMEZONE``.

    The country signal can be:

    * An ISO 3166-1 alpha-2 code (``"US"``, ``"gb"``). Case-insensitive.
    * A full English name or common alias (``"United States"``, ``"USA"``,
      ``"UK"``). Case-insensitive.
    * A ``"City, Country"`` location string from a Person note's
      ``location:`` frontmatter field (``"San Francisco, USA"``). The
      function tries the whole string first, then falls back to the
      last comma-separated segment.

    Returns ``DEFAULT_TIMEZONE`` (``"America/Los_Angeles"``) when:

    * ``country`` is ``None``, empty, or whitespace.
    * ``country`` is a non-empty string that doesn't match any entry.

    The fallback is deliberately *one* well-defined timezone, not a raise
    — see ADR-0005 §Decision. Sending-window rules need a usable IANA
    name; refusing to infer would just push the burden onto every caller
    (every send-gate construction site) and make the fallback non-uniform.
    """
    if not country:
        return DEFAULT_TIMEZONE
    if not isinstance(country, str):
        return DEFAULT_TIMEZONE
    cleaned = country.strip().rstrip(".").strip()
    if not cleaned:
        return DEFAULT_TIMEZONE

    # Try the whole string first (alpha-2 or full name).
    direct = _lookup(cleaned)
    if direct is not None:
        return direct

    # "City, Country" / "City, Region, Country" — try the trailing segment.
    if "," in cleaned:
        segments = [s.strip().rstrip(".").strip() for s in cleaned.split(",")]
        # Last non-empty segment is the country candidate.
        for seg in reversed(segments):
            if not seg:
                continue
            via_segment = _lookup(seg)
            if via_segment is not None:
                return via_segment
            # If the LAST segment doesn't match, don't keep walking back —
            # earlier segments are city/region, not country. Only fall
            # through to the default.
            break

    return DEFAULT_TIMEZONE


def _lookup(value: str) -> str | None:
    """Resolve a single, already-trimmed token against both tables.

    Returns the IANA name on hit, ``None`` on miss. Two-letter tokens go to
    the alpha-2 table first (avoiding the alias ``"us"`` collision with
    a hypothetical country named ``"Us"``); longer tokens go to the name
    table first.
    """
    if not value:
        return None
    upper = value.upper()
    lower = value.lower()
    # Alpha-2 codes are exactly 2 characters.
    if len(value) == 2:
        hit = COUNTRY_CODE_TO_TIMEZONE.get(upper)
        if hit is not None:
            return hit
    # Country name table (lowercased keys).
    hit = COUNTRY_NAME_TO_TIMEZONE.get(lower)
    if hit is not None:
        return hit
    # Fall back to alpha-2 even for non-2-char inputs — e.g. if a 3-char
    # string accidentally matches a code (shouldn't happen since the
    # table is alpha-2-only, but defensive).
    if len(value) == 2:
        return None
    return COUNTRY_CODE_TO_TIMEZONE.get(upper)
