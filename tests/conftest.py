"""Shared pytest config for outreach-factory tests.

Adds the repo root to sys.path so tests can `from orchestrator import identity`
without installing the repo as a package. The repo's existing scripts run
as `python orchestrator/<script>.py` so they don't need __init__.py; this
shim is just for the test harness.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# orchestrator/ scripts use bare `import identity`, `import state_machine`, etc.
# (they're designed to run via `python orchestrator/<script>.py` with that
# directory as CWD). Add the dir to sys.path so the test harness can import
# them via `from orchestrator import <script>` without ModuleNotFoundError
# on their internal cross-references.
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))


# CRITICAL: alias the bare-import names to the `orchestrator.*` package modules.
# Without this, `from orchestrator import enrollment` would load enrollment.py
# under the package name AND the bare `import identity` inside enrollment.py
# would load a SECOND identity module under the bare name. isinstance()
# checks across the two would silently fail. We force a single canonical
# module identity by registering the package modules under both names.
import importlib   # noqa: E402

# Don't preload modules with optional system deps (verify_email needs
# dnspython and exits on import if absent) — they'll be aliased lazily
# the first time a test imports them via either name.
for _name in ("identity", "state_machine",
              # Pillar E primitives MUST be aliased BEFORE the modules
              # that import them (e.g., enrollment imports
              # discovery_lineage; if enrollment loads first, the bare
              # `import discovery_lineage` inside it creates a second
              # module under the bare name, and the conftest's
              # `if _name in sys.modules: continue` then skips the
              # aliasing — leaving two distinct DiscoveryLineage classes
              # and isinstance() checks fail silently). Per ADR-0038
              # D182 audit category 4.
              "discovery_dedup", "discovery_lineage",
              "email_verification_cache", "tier_assignment",
              "enrollment",
              "backfill_identity", "ledger", "backfill_ledger",
              "reconcile", "policy", "reply_classifier",
              "reply_classifier_llm",
              "auto_unsubscribe", "conversation_state",
              "conversation_outcomes", "funnel"):
    if _name in sys.modules:
        continue
    try:
        _mod = importlib.import_module(f"orchestrator.{_name}")
    except BaseException:
        continue
    sys.modules[_name] = _mod


def pytest_configure(config):
    config.addinivalue_line("markers", "live: tests that hit the live network (DNS, HTTP)")


# ---------------------------------------------------------------------------
# Pillar B Week 5 synthetic-replay fixtures
# ---------------------------------------------------------------------------

import shutil  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
import pytest  # noqa: E402


_PILLAR_B_FIXTURE_ROOT = (
    Path(__file__).resolve().parent / "fixtures" / "synthetic_pillar_b"
)


@dataclass(frozen=True)
class SyntheticState:
    """Resolved paths to one freshly-built synthetic Pillar B state.

    Returned by the ``synthetic_state_dir`` fixture. Wrapping the four
    paths in a dataclass keeps test signatures terse (one parameter
    name instead of four) and lets future fields (e.g. a count
    snapshot, a conflict file marker) land without churning every test.
    """

    state_dir: Path
    vault_dir: Path
    ledger_dir: Path
    policy_dir: Path


@pytest.fixture
def synthetic_state_dir(tmp_path: Path) -> SyntheticState:
    """Build a fresh copy of ``tests/fixtures/synthetic_pillar_b/`` in tmp.

    Provides one isolated playground per test. The static fixture is
    copied into ``tmp_path``; tests are free to mutate the copy
    without affecting the version-controlled source.

    Returns a :class:`SyntheticState` with the four paths a
    ``MigrationRunner`` needs:

    * ``state_dir`` → the migrations state-file lives in
      ``state_dir/migrations.state.json``.
    * ``vault_dir`` → ``state_dir/vault``; contains ``10 People/`` and
      ``40 Conversations/``.
    * ``ledger_dir`` → ``state_dir/ledger`` with one pre-existing
      ``events-2026-04-15.jsonl`` containing one orphan
      ``send_intent``.
    * ``policy_dir`` → ``state_dir/policies`` with one
      ``cooldowns.yml`` at ``version: 1`` (no ``engine_compat``).

    The layout mirrors the production
    ``~/.outreach-factory/{ledger,policies}/`` shape so the runner's
    default sub-dir resolution matches.

    Per ADR-0013 D24 the fixture is a hybrid: the static portion lives
    on disk for reviewer inspection; tests that need volume / stress
    shapes build them programmatically on top of this baseline.
    """
    dest = tmp_path / "state"
    shutil.copytree(_PILLAR_B_FIXTURE_ROOT, dest)
    # README.md sits at the fixture root for human readers; the
    # migration framework doesn't need it. Leave it in place — the
    # walkers skip unknown files (the policy iterator filters by
    # ``*.yml``; vault iterators filter by ``*.md`` + frontmatter
    # type; ledger iterates by ``events-*.jsonl``).
    return SyntheticState(
        state_dir=dest,
        vault_dir=dest / "vault",
        ledger_dir=dest / "ledger",
        policy_dir=dest / "policies",
    )


# ---------------------------------------------------------------------------
# Pillar C Week 12 exit-criterion stress fixture — 50 prospects across four
# channels with deterministic injected-failure substrate.
# ---------------------------------------------------------------------------


_FACTORY_COOLDOWNS_PATH = (
    Path(__file__).resolve().parent.parent
    / "config-template" / "cooldowns.example.yml"
)


# 50-prospect ICP shape per ADR-0014 D37 + the binding exit-criterion
# docstring at tests/test_multi_channel_coherence.py:1689-1694. Each
# index range names the prospect's PRIMARY channel; injected-failure
# substrate is per-channel-symmetric (one intent_only + one pre_intent
# for the four MCP-bearing channels; calendar gets two pre_intent per
# ADR-0019 D68's no-Pass-G + D69's asymmetric semantics).
_PILLAR_C_STRESS_DISTRIBUTION: dict[str, dict[str, int]] = {
    # email: 25 (P00..P24)
    #   P00..P22 → clean dispatch.
    #   P23 → intent_only failure (Pass A recovers to send_confirmed).
    #   P24 → pre_intent failure (no orphan; nothing to recover).
    "email": {
        "start": 0, "count": 25,
        "clean_count": 23,
        "intent_only": 23,  # P23
        "pre_intent": 24,   # P24
    },
    # li_invite: 15 (P25..P39)
    #   P25..P35 → clean dispatch.
    #   P36, P37 → R011-positive (prior email_confirmed in seed; the
    #     cross-channel-email-suppresses-linkedin rule must fire on
    #     dispatch → policy_blocked).
    #   P38 → intent_only failure (Pass D recovers to li_invite_confirmed).
    #   P39 → pre_intent failure.
    "li_invite": {
        "start": 25, "count": 15,
        "clean_count": 11,
        "r011_positive": [36, 37],
        "intent_only": 38,
        "pre_intent": 39,
    },
    # li_dm: 5 (P40..P44)
    #   P40..P42 → clean dispatch (linkedin_connected: true on Person).
    #   P43 → intent_only failure (Pass E recovers to li_dm_confirmed).
    #   P44 → pre_intent failure.
    "li_dm": {
        "start": 40, "count": 5,
        "clean_count": 3,
        "intent_only": 43,
        "pre_intent": 44,
    },
    # tw_dm: 3 (P45..P47)
    #   P45 → clean dispatch.
    #   P46 → intent_only failure (Pass F recovers to tw_dm_confirmed).
    #   P47 → pre_intent failure.
    "tw_dm": {
        "start": 45, "count": 3,
        "clean_count": 1,
        "intent_only": 46,
        "pre_intent": 47,
    },
    # calendar: 2 (P48..P49)
    #   Both → pre_intent failures per ADR-0019 D68 (no Pass G) +
    #   D69 (asymmetric backfill semantics — orphan intent is the
    #   operator-pending state, not a coherence violation).
    #
    # KEY-NAMING DIVERGENCE FROM THE FOUR MCP CHANNELS ABOVE: the
    # MCP channels use ``"intent_only"`` + ``"pre_intent"`` keys
    # (matching the injection sentinel values that
    # ``_build_stress_prospect`` reads). Calendar has NO
    # ``"intent_only"`` slot per D68/D69 — both calendar failures
    # are pre_intent, so the dict uses ``"pre_intent_a"`` +
    # ``"pre_intent_b"`` to keep the two indexes distinct without
    # introducing a list (the per-channel for-loop reads scalar
    # keys; a list would require a different loop shape just for
    # calendar). The fixture-builder's calendar branch at the
    # ``_PILLAR_C_STRESS_DISTRIBUTION["calendar"]`` consumption
    # site (further down) hardcodes ``injection="pre_intent"`` for
    # both indexes — the key names are documentation, not
    # behavior-driving.
    "calendar": {
        "start": 48, "count": 2,
        "clean_count": 0,
        "pre_intent_a": 48,
        "pre_intent_b": 49,
    },
}


@dataclass(frozen=True)
class StressProspect:
    """One prospect in the 50-prospect exit-criterion stress fixture.

    The dataclass captures the minimum information the exit-criterion
    test needs to drive each prospect through the dispatcher (no live
    vault writeback) AND to assert on per-prospect post-conditions.

    The ``injection`` field is one of:

    * ``None`` — clean dispatch (most prospects).
    * ``"intent_only"`` — fake client raises mid-flight after the
      ``<channel>_intent`` ledger event lands; the dispatcher's broad
      ``except Exception`` is bypassed by raising :class:`BaseException`.
      Reconcile's per-channel pass walks the orphan + scans the fake's
      stored marker → emits ``<channel>_confirmed`` with
      ``_recovered_by: "reconcile"``.
    * ``"pre_intent"`` — the harness skips the dispatcher call entirely
      (simulates "process died before the dispatcher touched the
      ledger"). No orphan; reconcile has nothing to recover.

    The ``r011_positive`` flag is True for prospects whose seed ledger
    carries a prior cross-channel ``send_confirmed``; the dispatcher's
    policy gate MUST emit ``policy_blocked`` with the
    ``cross-channel-email-suppresses-linkedin`` rule name (the rule
    activates the moment the LinkedIn dispatcher fires for these
    prospects per ADR-0003 + ADR-0014 D33).
    """

    name: str
    person_id: str
    person_path: Path
    channel: str  # "email" | "li_invite" | "li_dm" | "tw_dm" | "calendar"
    email: str | None
    linkedin: str | None
    twitter_handle: str | None
    calendar_booking_url_base: str | None
    injection: str | None  # None | "intent_only" | "pre_intent"
    r011_positive: bool


@dataclass(frozen=True)
class StressState:
    """Resolved paths + the 50-prospect manifest for the exit-criterion test.

    Mirrors :class:`SyntheticState` (the Pillar B builder fixture) +
    adds the prospect manifest so the test body can iterate per-channel
    without re-scanning the vault.
    """

    state_dir: Path
    vault_dir: Path
    ledger_dir: Path
    policy_dir: Path
    prospects: tuple[StressProspect, ...]

    def by_channel(self, channel: str) -> list[StressProspect]:
        return [p for p in self.prospects if p.channel == channel]

    def by_injection(self, injection: str) -> list[StressProspect]:
        return [p for p in self.prospects if p.injection == injection]

    def r011_positives(self) -> list[StressProspect]:
        return [p for p in self.prospects if p.r011_positive]


def _build_stress_person_note(
    *, name: str, person_id: str, channel: str,
    email: str | None, linkedin: str | None,
    twitter_handle: str | None, calendar_booking_url_base: str | None,
    injection: str | None, r011_positive: bool,
) -> str:
    """Render the markdown text for one Person note in the stress fixture.

    Post-migration shape (schema_version, id, identity_keys present) —
    no vault migrations need to run; the migration framework's
    idempotence handles the case anyway. The ``injected_failure:``
    frontmatter field is documentation: the failure-injection harness
    in the test body reads the in-memory :class:`StressProspect`
    manifest, not the Person frontmatter, but stamping the field keeps
    the on-disk fixture self-documenting.
    """
    lines: list[str] = ["---", "type: person", "schema_version: 1",
                        f"id: {person_id}",
                        "identity_keys:"]
    if email:
        lines.append("  emails:")
        lines.append(f"    - {email}")
    if linkedin:
        # Strip an "in/" prefix if present so identity_keys.linkedin
        # carries the slug form (matches mint_id's `-li` convention).
        slug = linkedin[3:] if linkedin.startswith("in/") else linkedin
        lines.append(f"  linkedin: {slug}")
    if twitter_handle:
        lines.append(f"  twitter: {twitter_handle}")
    lines.append("identity_version: 1")
    lines.append(f"name: {name}")
    if email:
        lines.append(f"email: {email}")
    if linkedin:
        lines.append(f"linkedin: {linkedin}")
    if twitter_handle:
        lines.append(f"twitter_handle: {twitter_handle}")
    if calendar_booking_url_base:
        lines.append(f"calendar_booking_url_base: {calendar_booking_url_base}")
    if channel == "li_dm":
        # ADR-0016 D44: the DM dispatcher refuses-loud on unknown
        # connection state. Stamp linkedin_connected: true so the
        # dispatcher's policy gate proceeds.
        lines.append("linkedin_connected: true")
    lines.append("status: queued")
    lines.append("pipeline_stage: ready")
    if injection:
        lines.append(f"injected_failure: {injection}")
    if r011_positive:
        lines.append("r011_positive: true")
    lines.append("---")
    lines.append(f"# {name}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _stress_prospect_email(idx: int) -> str:
    # Per-prospect distinct domains so the factory's domain-throttle
    # rule (Rule 4 in cooldowns.example.yml — ≥1 send to a domain in
    # 14d → block) doesn't false-fire across the 25 email prospects.
    # Real-world ICP shape: operators target many distinct domains,
    # not a single shared domain.
    return f"p{idx:02d}@p{idx:02d}-test.example"


def _stress_prospect_linkedin(idx: int) -> str:
    return f"in/p{idx:02d}-test"


def _stress_prospect_twitter(idx: int) -> str:
    # Bare handle (no ``@`` prefix) to match the factory's
    # ``twitter_handle:`` convention (e.g. Evan Estefan's
    # ``twitter_handle: evan_estefan`` in the Pillar B fixture). YAML
    # rejects leading-``@`` strings as start-of-token unless quoted,
    # so the bare form is also the simplest on-disk shape.
    return f"p{idx:02d}_test"


def _stress_prospect_cal_base(idx: int) -> str:
    return f"https://cal.com/p{idx:02d}/intro"


def _build_stress_prospect(
    idx: int, *, channel: str, vault_people_dir: Path,
    injection: str | None, r011_positive: bool,
) -> StressProspect:
    name = f"P{idx:02d}"
    # mint_id-style id with `-li` provenance (every Person has linkedin
    # for identity strength regardless of primary channel — keeps the
    # `-tmp` gate from firing in the dispatcher's identity_incomplete
    # check).
    person_id = f"p{idx:02d}-test-li"
    email = _stress_prospect_email(idx) if channel != "tw_dm" else None
    linkedin = _stress_prospect_linkedin(idx)
    twitter_handle = (
        _stress_prospect_twitter(idx) if channel == "tw_dm" else None
    )
    cal_base = (
        _stress_prospect_cal_base(idx) if channel == "calendar" else None
    )
    person_path = vault_people_dir / f"{name}.md"
    person_path.write_text(
        _build_stress_person_note(
            name=name, person_id=person_id, channel=channel,
            email=email, linkedin=linkedin,
            twitter_handle=twitter_handle,
            calendar_booking_url_base=cal_base,
            injection=injection, r011_positive=r011_positive,
        ),
        encoding="utf-8",
    )
    return StressProspect(
        name=name, person_id=person_id, person_path=person_path,
        channel=channel, email=email, linkedin=linkedin,
        twitter_handle=twitter_handle,
        calendar_booking_url_base=cal_base,
        injection=injection, r011_positive=r011_positive,
    )


def _seed_stress_ledger(
    ledger_dir: Path, prospects: tuple[StressProspect, ...],
) -> None:
    """Write the pre-dispatch ledger events: ``enrolled`` for every
    prospect + ``send_intent`` / ``send_confirmed`` pairs for the
    R011-positive prospects' prior email touches.

    R011-positive ledger seeding lands on a date 7 days before the
    test runs (well inside the factory's 14-day cross-channel window
    per ADR-0024 D-N5), with the channel=email tag the cross-channel
    rule queries via ``consider_channels: [email]``.
    """
    import json as _json
    from datetime import timedelta as _td

    now = datetime.now(timezone.utc)
    today_file = ledger_dir / f"events-{now.strftime('%Y-%m-%d')}.jsonl"
    seed_ts = (now - _td(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    lines: list[str] = []
    for p in prospects:
        lines.append(_json.dumps({
            "type": "enrolled",
            "person_id": p.person_id,
            "ts": (now - _td(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "v": 1,
        }))
        if p.r011_positive:
            # Pre-existing email send 7 days ago — the cross-channel
            # rule (cooldowns Rule 5: cross-channel-email-suppresses-
            # linkedin) MUST fire when this prospect's LinkedIn invite
            # is dispatched.
            iid = f"snd_r011_{p.person_id}"
            lines.append(_json.dumps({
                "type": "send_intent",
                "intent_id": iid,
                "person_id": p.person_id,
                "channel": "email",
                "email": p.email,
                "ts": seed_ts,
                "v": 1,
            }))
            lines.append(_json.dumps({
                "type": "send_confirmed",
                "intent_id": iid,
                "person_id": p.person_id,
                "channel": "email",
                "gmail_message_id": f"msg_r011_{p.person_id}",
                "gmail_thread_id": f"thr_r011_{p.person_id}",
                "email": p.email,
                "ts": seed_ts,
                "v": 1,
            }))
    today_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def synthetic_pillar_c_stress_state_dir(tmp_path: Path) -> StressState:
    """Build a 50-prospect synthetic state for the Pillar C exit-criterion test.

    Programmatic builder (no static fixture directory) — the layout is
    too large to inspect by ``cat`` and the prospect list is
    deterministic per :data:`_PILLAR_C_STRESS_DISTRIBUTION`.

    The fixture is fully migrated (post-Pillar-B + post-Pillar-C
    Weeks 7-11 shape — every Person note carries schema_version, id,
    identity_keys; every prospect has an enrolled event; the policy
    file is the factory ``cooldowns.example.yml`` with Rules 5 + 6
    cross-channel cooldowns active; per-channel caps stay commented
    because the per-channel-rate-limit assertion is covered by the
    per-week tests, not by the exit-criterion test). The migrations
    framework still applies idempotently; the test body may or may
    not call ``runner.apply()`` (default: skip — the fixture IS the
    post-migration state).

    R011-positive substrate: P36 + P37 carry prior ``send_confirmed``
    events at channel=email 7 days before the test runs. The
    cross-channel rule (ADR-0003 + ADR-0014 D33) MUST fire on their
    LinkedIn dispatch attempt, emitting ``policy_blocked`` with the
    ``cross-channel-email-suppresses-linkedin`` rule name. This is
    the positive R011 verification — without the seed the test could
    only verify the negative invariant (the rule doesn't false-fire).

    Injected-failure substrate: 10 of the 50 prospects carry an
    ``injection`` value on the :class:`StressProspect` manifest. The
    test body reads the manifest + configures fake clients accordingly
    (per the harness in
    ``tests/test_multi_channel_coherence.py``).

    Returns a :class:`StressState` shaped like :class:`SyntheticState`
    + a ``prospects`` tuple in stable index order (P00..P49). Tests
    iterate ``.by_channel(...)`` / ``.by_injection(...)`` /
    ``.r011_positives()`` for per-scenario assertions.
    """
    dest = tmp_path / "state"
    vault_dir = dest / "vault"
    people_dir = vault_dir / "10 People"
    conv_dir = vault_dir / "40 Conversations"
    ledger_dir = dest / "ledger"
    policy_dir = dest / "policies"
    for d in (people_dir, conv_dir, ledger_dir, policy_dir):
        d.mkdir(parents=True)

    # Copy factory cooldowns template — Rules 5 + 6 are active per
    # Pillar A Week 2 + ADR-0024 D-N3.
    shutil.copy(
        _FACTORY_COOLDOWNS_PATH, policy_dir / "cooldowns.yml",
    )

    prospects: list[StressProspect] = []

    # Email range (P00..P24) — 25 prospects.
    spec = _PILLAR_C_STRESS_DISTRIBUTION["email"]
    for i in range(spec["start"], spec["start"] + spec["count"]):
        injection: str | None = None
        if i == spec["intent_only"]:
            injection = "intent_only"
        elif i == spec["pre_intent"]:
            injection = "pre_intent"
        prospects.append(_build_stress_prospect(
            i, channel="email", vault_people_dir=people_dir,
            injection=injection, r011_positive=False,
        ))

    # LinkedIn invite range (P25..P39) — 15 prospects.
    spec = _PILLAR_C_STRESS_DISTRIBUTION["li_invite"]
    r011_set = set(spec["r011_positive"])
    for i in range(spec["start"], spec["start"] + spec["count"]):
        injection = None
        if i == spec["intent_only"]:
            injection = "intent_only"
        elif i == spec["pre_intent"]:
            injection = "pre_intent"
        prospects.append(_build_stress_prospect(
            i, channel="li_invite", vault_people_dir=people_dir,
            injection=injection, r011_positive=(i in r011_set),
        ))

    # LinkedIn DM range (P40..P44) — 5 prospects.
    spec = _PILLAR_C_STRESS_DISTRIBUTION["li_dm"]
    for i in range(spec["start"], spec["start"] + spec["count"]):
        injection = None
        if i == spec["intent_only"]:
            injection = "intent_only"
        elif i == spec["pre_intent"]:
            injection = "pre_intent"
        prospects.append(_build_stress_prospect(
            i, channel="li_dm", vault_people_dir=people_dir,
            injection=injection, r011_positive=False,
        ))

    # Twitter DM range (P45..P47) — 3 prospects.
    spec = _PILLAR_C_STRESS_DISTRIBUTION["tw_dm"]
    for i in range(spec["start"], spec["start"] + spec["count"]):
        injection = None
        if i == spec["intent_only"]:
            injection = "intent_only"
        elif i == spec["pre_intent"]:
            injection = "pre_intent"
        prospects.append(_build_stress_prospect(
            i, channel="tw_dm", vault_people_dir=people_dir,
            injection=injection, r011_positive=False,
        ))

    # Calendar booking range (P48..P49) — 2 prospects.
    # Both pre_intent per ADR-0019 D68 (no Pass G) + D69 (asymmetric
    # semantics — orphan intent is operator-pending, not a violation).
    spec = _PILLAR_C_STRESS_DISTRIBUTION["calendar"]
    for i in range(spec["start"], spec["start"] + spec["count"]):
        prospects.append(_build_stress_prospect(
            i, channel="calendar", vault_people_dir=people_dir,
            injection="pre_intent", r011_positive=False,
        ))

    assert len(prospects) == 50, (
        f"stress fixture must build exactly 50 prospects; got {len(prospects)}"
    )

    _seed_stress_ledger(ledger_dir, tuple(prospects))

    return StressState(
        state_dir=dest, vault_dir=vault_dir, ledger_dir=ledger_dir,
        policy_dir=policy_dir, prospects=tuple(prospects),
    )


# ---------------------------------------------------------------------------
# Pillar D Week 12 exit-criterion classifier-corpus fixture — 100-message
# synthetic inbox per ADR-0031 D136.
# ---------------------------------------------------------------------------


_PILLAR_D_FIXTURE_ROOT = (
    Path(__file__).resolve().parent / "fixtures" / "synthetic_pillar_d"
)

# Per-channel touch event type. The conftest builder seeds one
# touch event per (person, channel) BEFORE the reply event so the
# attribution walker can find a same-channel touch.
_PILLAR_D_TOUCH_TYPE_BY_CHANNEL: dict[str, str] = {
    "email": "send_confirmed",
    # Per ADR-0027 D112 — Pass H reads invite acceptances against a
    # prior `li_invite_confirmed` touch; Pass I reads DM replies
    # against a prior `li_dm_confirmed` touch. The corpus uses
    # `li_invite_reply_received` for the 10 uncategorized rows
    # (matched to li_invite_confirmed touches); the other 15
    # linkedin rows are `li_dm_reply_received` (matched to
    # li_dm_confirmed touches). The dict here is keyed by reply
    # event type for unambiguous touch mapping.
}

_PILLAR_D_TOUCH_TYPE_BY_REPLY_TYPE: dict[str, str] = {
    "reply_received":              "send_confirmed",
    "li_invite_reply_received":    "li_invite_confirmed",
    "li_dm_reply_received":        "li_dm_confirmed",
    "tw_dm_reply_received":        "tw_dm_confirmed",
}


@dataclass(frozen=True)
class PillarDCorpusState:
    """Resolved paths + corpus manifest for the Pillar D exit-criterion test.

    Mirrors :class:`StressState` (the Pillar C builder fixture's shape) +
    surfaces the corpus messages + the scenario manifest + the test
    clock anchor `now` so the test body can iterate without
    re-loading the YAML.

    Per ADR-0031 D136 the corpus is a HYBRID: the static YAML in
    `tests/fixtures/synthetic_pillar_d/corpus.yml` is the reviewer-
    inspectable surface; this dataclass surfaces the programmatically
    constructed ledger state that consumes it.
    """

    state_dir: Path
    vault_dir: Path
    ledger_dir: Path
    policy_dir: Path
    classifier_dir: Path
    suppressions_dir: Path
    messages: tuple[dict, ...]
    scenarios: dict
    now: datetime


def _pillar_d_iso(ts: datetime) -> str:
    """Stable ISO-8601 with millisecond precision + UTC anchor.

    Matches the ledger's standard ts shape (`YYYY-MM-DDTHH:MM:SS.fffZ`)
    per ``orchestrator/ledger._now_iso``. The millisecond field is
    rendered from the datetime's microsecond component (truncated to
    milliseconds via integer division by 1000) so per-emission
    millisecond offsets (e.g., ``+timedelta(microseconds=1000 * idx)``)
    survive serialization — the prior shape hardcoded `.000Z` which
    silently dropped the offset, per the Week 12 per-week reviewer's
    P3-B finding.
    """
    utc = ts.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{(utc.microsecond // 1000):03d}Z"
    )


def _seed_pillar_d_touch(
    led, *, person_id: str, channel: str, touch_type: str,
    intent_id: str, ts: datetime, reply_event_type: str | None = None,
) -> None:
    """Append one `*_confirmed` touch event to the ledger.

    Per-channel emission shape derived from the per-week reply tests
    (`tests/test_multi_channel_coherence.py::TestReplyEventsCarryChannel`).
    """
    payload: dict = {
        "type": touch_type,
        "person_id": person_id,
        "channel": channel,
        "intent_id": intent_id,
        "ts": _pillar_d_iso(ts),
    }
    if channel == "email":
        payload["gmail_message_id"] = f"sent_{intent_id}"
        payload["gmail_thread_id"] = f"thr_{person_id}"
        payload["email"] = f"{person_id}@x.test"
    elif channel == "linkedin":
        if touch_type == "li_invite_confirmed":
            payload["invitation_id"] = f"inv_{intent_id}"
        else:
            payload["linkedin_thread_id"] = f"thr_{person_id}_li"
    elif channel == "twitter":
        payload["twitter_thread_id"] = f"thr_{person_id}_tw"
    led.append(payload)


def _seed_pillar_d_reply(
    led, *, msg: dict, ts: datetime, reply_to_intent_id: str | None,
) -> None:
    """Append one reply event derived from a corpus message + scenario ts."""
    rtype = msg["reply_event_type"]
    pid = msg["person_id"]
    ch = msg["channel"]
    payload: dict = {
        "type": rtype,
        "person_id": pid,
        "channel": ch,
        "ts": _pillar_d_iso(ts),
    }
    if rtype == "reply_received":
        payload["gmail_message_id"] = f"gid_{msg['id']}"
        payload["gmail_thread_id"] = f"thr_{pid}"
        payload["from"] = f"{pid}@x.test"
        payload["subject"] = msg.get("subject", "")
        payload["body"] = msg.get("body", "")
    elif rtype == "li_invite_reply_received":
        # Per ADR-0027 D112 — invite acceptance has no body; the
        # `reply_message_id` is the synthesized `li_accept:<invitation_id>`.
        payload["reply_message_id"] = f"li_accept:inv_{msg['id']}"
        if reply_to_intent_id is not None:
            payload["reply_to_intent_id"] = reply_to_intent_id
    elif rtype == "li_dm_reply_received":
        payload["reply_message_id"] = f"li_msg_{msg['id']}"
        payload["linkedin_thread_id"] = f"thr_{pid}_li"
        payload["snippet"] = msg.get("snippet", "")
        if reply_to_intent_id is not None:
            payload["reply_to_intent_id"] = reply_to_intent_id
    elif rtype == "tw_dm_reply_received":
        payload["reply_message_id"] = f"tw_msg_{msg['id']}"
        payload["twitter_thread_id"] = f"thr_{pid}_tw"
        payload["snippet"] = msg.get("snippet", "")
        if reply_to_intent_id is not None:
            payload["reply_to_intent_id"] = reply_to_intent_id
    else:
        raise AssertionError(f"unknown reply_event_type: {rtype}")
    led.append(payload)


def _seed_pillar_d_booking(
    led, *, person_id: str, ts: datetime, intent_id: str,
) -> None:
    """Append one `calendar_booking_confirmed` event for closed_won scenarios.

    Per ADR-0019 D69 — booking events carry channel=calendar.
    """
    led.append({
        "type": "calendar_booking_confirmed",
        "person_id": person_id,
        "channel": "calendar",
        "intent_id": intent_id,
        "booking_url": f"https://cal.com/{person_id}/intro?intent_id={intent_id}",
        "ts": _pillar_d_iso(ts),
    })


def _copy_factory_classifier_patterns(classifier_dir: Path) -> None:
    """Copy every factory pattern file from `config-template/` into the
    fixture's classifier dir.

    Per ADR-0027 D109's `from_yaml_dir` contract — the directory
    contains one file per category, named per :data:`PATTERN_FILE_BY_CATEGORY`.
    The factory ships `.example.yml` files; the operator (and this
    fixture) rename to the runtime name.
    """
    factory_root = Path(__file__).resolve().parent.parent / "config-template"
    pairs = [
        ("unsubscribe-patterns.example.yml", "unsubscribe-patterns.yml"),
        ("ooo-patterns.example.yml",         "ooo-patterns.yml"),
        ("wrong-person-patterns.example.yml","wrong-person-patterns.yml"),
        ("interest-patterns.example.yml",    "interest-patterns.yml"),
        ("rejection-patterns.example.yml",   "rejection-patterns.yml"),
    ]
    for src, dest in pairs:
        shutil.copy(factory_root / src, classifier_dir / dest)


@pytest.fixture
def synthetic_pillar_d_classifier_corpus_state_dir(
    tmp_path: Path,
) -> PillarDCorpusState:
    """Build the Pillar D Week 12 100-message synthetic inbox state.

    Per ADR-0031 D136 — HYBRID fixture per ADR-0013 D24's posture:
    the static corpus lives in `tests/fixtures/synthetic_pillar_d/
    corpus.yml` for reviewer inspection; this fixture builds the
    surrounding ledger + classifier-pattern state programmatically.

    Returns a :class:`PillarDCorpusState` with:

    * `state_dir` / `vault_dir` / `ledger_dir` / `policy_dir` —
      paths mirroring :class:`SyntheticState` for Pass C/N
      consumers.
    * `classifier_dir` — pattern files copied from
      `config-template/` per ADR-0027 D109's `from_yaml_dir`
      contract.
    * `suppressions_dir` — empty dir for Pass M's YAML writes.
    * `messages` — the corpus message tuple in id-order.
    * `scenarios` — the scenarios dict (multi_touch / cross_channel
      / ttl_dormant_days_ago / closed_won).
    * `now` — the deterministic test clock anchor (a fixed
      `datetime` per `corpus_now()` below). TTL evaluations use
      `now - ttl_days`; reply timestamps are `now - days_ago`.

    The fixture is DETERMINISTIC — no random number generation;
    every timestamp derives from `now` + a per-message offset.
    Re-runs against the same fixture state produce byte-identical
    ledger contents (load-bearing for the funnel-reproducibility
    assertion per ADR-0031 D140).
    """
    import yaml as _yaml

    dest = tmp_path / "state"
    vault_dir = dest / "vault"
    (vault_dir / "10 People").mkdir(parents=True)
    (vault_dir / "40 Conversations").mkdir(parents=True)
    ledger_dir = dest / "ledger"
    ledger_dir.mkdir(parents=True)
    policy_dir = dest / "policies"
    policy_dir.mkdir(parents=True)
    classifier_dir = dest / "classifier"
    classifier_dir.mkdir(parents=True)
    suppressions_dir = dest / "suppressions"
    suppressions_dir.mkdir(parents=True)

    _copy_factory_classifier_patterns(classifier_dir)

    corpus_text = (_PILLAR_D_FIXTURE_ROOT / "corpus.yml").read_text(
        encoding="utf-8",
    )
    corpus = _yaml.safe_load(corpus_text)
    messages: list[dict] = list(corpus["messages"])
    scenarios: dict = corpus.get("scenarios") or {}

    # Deterministic clock — anchored at 2026-05-23T12:00:00Z (the
    # commit date of Pillar D Week 12 per the handoff). All
    # timestamps derive from this anchor + per-message offsets so
    # the funnel output is byte-identical across runs.
    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)

    import ledger as _ledger  # local import — avoids circular bootstrap
    led = _ledger.Ledger(ledger_dir)

    multi_touch_map: dict[str, int] = scenarios.get("multi_touch") or {}
    cross_channel_map: dict[str, str] = scenarios.get("cross_channel") or {}
    ttl_dormant_map: dict[str, int] = scenarios.get("ttl_dormant_days_ago") or {}
    closed_won_map: dict[str, int] = scenarios.get("closed_won") or {}

    from datetime import timedelta as _td

    # Build deterministic ledger state per the corpus + scenarios.
    for idx, msg in enumerate(messages):
        pid = msg["person_id"]
        ch = msg["channel"]
        rtype = msg["reply_event_type"]
        touch_type = _PILLAR_D_TOUCH_TYPE_BY_REPLY_TYPE[rtype]

        # Resolve scenario overrides.
        days_ago = ttl_dormant_map.get(pid, msg.get("days_ago", 7))
        touch_count = multi_touch_map.get(pid, msg.get("multi_touch_count", 1))
        extra_channel = cross_channel_map.get(pid)

        # The reply timestamp is `now - days_ago` (with millisecond
        # offset per index to break ts collisions across messages).
        reply_ts = now - _td(days=days_ago) + _td(milliseconds=idx)

        # Same-channel touches BEFORE reply. The most-recent touch
        # is 1 day before the reply; older touches step back 7 days
        # each per touch index.
        last_intent_id: str | None = None
        for tcount in range(touch_count):
            offset_days = 1 + (touch_count - 1 - tcount) * 7
            touch_ts = reply_ts - _td(days=offset_days)
            intent_id = f"snd_{pid}_t{tcount}"
            _seed_pillar_d_touch(
                led, person_id=pid, channel=ch, touch_type=touch_type,
                intent_id=intent_id, ts=touch_ts,
                reply_event_type=rtype,
            )
            last_intent_id = intent_id  # the most-recent touch wins attribution

        # Cross-channel extra touch (DIFFERENT channel from the
        # reply). Lands 14 days before the reply; the reply lands
        # on `ch` so this touch is NEVER the attributed one per
        # ADR-0030 D131's same-channel rule.
        if extra_channel and extra_channel != ch:
            extra_touch_type = {
                "email":    "send_confirmed",
                "linkedin": "li_dm_confirmed",
                "twitter":  "tw_dm_confirmed",
            }[extra_channel]
            extra_intent_id = f"snd_{pid}_xch"
            extra_ts = reply_ts - _td(days=14)
            _seed_pillar_d_touch(
                led, person_id=pid, channel=extra_channel,
                touch_type=extra_touch_type,
                intent_id=extra_intent_id, ts=extra_ts,
            )

        # The reply itself.
        _seed_pillar_d_reply(
            led, msg=msg, ts=reply_ts,
            reply_to_intent_id=last_intent_id,
        )

        # TTL-dormant scenarios — pre-seed the matching reply_
        # classified event at the SAME old ts as the reply. The
        # conversation state machine's TTL evaluation reads the
        # thread's last_activity_ts = max(reply_ts, classified_ts).
        # Without pre-seeding, Pass G's classifier emit (under the
        # default wall-clock _now_iso) lands a fresh ts that becomes
        # the thread's last_activity_ts, defeating the stale-thread
        # premise. Pre-seeding lets Pass G's idempotence skip these
        # rows (per ADR-0026 D104's (reply_message_id, channel)
        # idempotence pair) and preserves the deterministic stale
        # ts the TTL driver needs. The pre-seeded classification
        # carries the corpus's expected_category (always "interest"
        # for the 5 TTL prospects per the corpus design).
        if pid in ttl_dormant_map:
            classified_ts = reply_ts + _td(microseconds=1)
            rtype = msg["reply_event_type"]
            mid = (
                f"gid_{msg['id']}" if rtype == "reply_received"
                else f"li_accept:inv_{msg['id']}" if rtype == "li_invite_reply_received"
                else f"li_msg_{msg['id']}" if rtype == "li_dm_reply_received"
                else f"tw_msg_{msg['id']}"
            )
            classified_payload: dict = {
                "type": "reply_classified",
                "person_id": pid,
                "channel": ch,
                "reply_message_id": mid,
                "reply_to_intent_id": last_intent_id,
                "category": msg["expected_category"],
                "classification_method": "rule",
                "confidence": 1.0,
                "matched_pattern": "<seeded-by-pillar-d-week-12-ttl-fixture>",
                "ts": _pillar_d_iso(classified_ts),
                "_emitted_by": "reply_classifier",
            }
            if ch == "email":
                classified_payload["gmail_thread_id"] = f"thr_{pid}"
            led.append(classified_payload)

        # Closed_won — calendar_booking_confirmed event N days
        # after the reply (only for category=interest prospects
        # per ADR-0030 D131 — Pass O only fires closed_won when
        # the thread reaches `active` state).
        if pid in closed_won_map:
            booking_offset = closed_won_map[pid]
            booking_ts = reply_ts + _td(days=booking_offset)
            booking_intent_id = f"book_{pid}"
            _seed_pillar_d_booking(
                led, person_id=pid, ts=booking_ts,
                intent_id=booking_intent_id,
            )

    return PillarDCorpusState(
        state_dir=dest,
        vault_dir=vault_dir,
        ledger_dir=ledger_dir,
        policy_dir=policy_dir,
        classifier_dir=classifier_dir,
        suppressions_dir=suppressions_dir,
        messages=tuple(messages),
        scenarios=scenarios,
        now=now,
    )
