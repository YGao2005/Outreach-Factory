# Pillar D Week 12 — Synthetic 100-message inbox corpus

The corpus in `corpus.yml` is the **binding exit-criterion test substrate** for Pillar D per PILLAR-PLAN §2:

> *"100-message synthetic inbox classifier benchmark with documented rule precision/recall; suppression updates idempotent; attribution funnel reproducible."*

Loaded by the `synthetic_pillar_d_classifier_corpus_state_dir` fixture in `tests/conftest.py`; consumed by `tests/test_multi_channel_coherence.py::TestPillarDExitCriterion::test_100_message_synthetic_inbox_classifier_benchmark`.

## Distribution (per ADR-0031 D136)

| Category        | Count | Notes                                                                                          |
|-----------------|------:|------------------------------------------------------------------------------------------------|
| `unsubscribe`   |    30 | LEGAL-LIABILITY path. Every message MUST match a factory unsubscribe-pattern (rule-classifiable, never LLM). |
| `ooo`           |    15 | Long-tail. Operator-tunable. Includes 2 adversarial scenarios (ooo + interest signal interleaved). |
| `wrong_person`  |    15 | Long-tail. Includes 2 adversarial scenarios (wrong_person + named-redirect). |
| `interest`      |    15 | HIGHEST-AMBIGUITY long-tail per ADR-0027 D110 (evaluated LAST). |
| `rejection`     |    15 | Long-tail. Includes 1 adversarial scenario (rejection + interest signal interleaved — rejection wins per priority). |
| `uncategorized` |    10 | NONE of the factory patterns fire on these. The LLM fallback's expected coverage surface per ADR-0029 D124. |
| **Total**       | **100** | |

## Channel distribution (per ADR-0031 D136)

| Channel     | Count | Reply event type                                            |
|-------------|------:|-------------------------------------------------------------|
| email       |    60 | `reply_received` (Phase 5.5 Pass B)                         |
| linkedin    |    25 | 15 `li_dm_reply_received` + 10 `li_invite_reply_received` (Pillar D Week 3 Pass H/I) |
| twitter     |    15 | `tw_dm_reply_received` (Pillar D Week 3 Pass J)             |

Cal.com replies (`calendar_booking_reply_received`) are DEFERRED to Pillar I per ADR-0027 D113 — the corpus does NOT include calendar reply events. Calendar bookings are tested via `calendar_booking_confirmed` events for closed_won outcome attribution (separate scenario substrate, not the 100-message corpus itself).

## Required scenarios (per ADR-0031 D136)

1. **Pattern coverage** — every factory pattern in `config-template/{category}-patterns.example.yml` has at least one representative phrase in the corpus.
2. **Adversarial precedence** — replies with mixed signals MUST resolve to the higher-priority category per `DISPATCH_PRIORITY`:
   * `unsubscribe` always wins (legal-liability per ADR-0025 D97).
   * `ooo > wrong_person > rejection > interest` per ADR-0027 D110.
3. **Multi-touch attribution** — at least 10 prospects have 2-3 confirmed touches BEFORE their reply event; the conversation_outcome MUST attribute to the most-recent same-channel touch per ADR-0030 D131.
4. **Cross-channel attribution** — at least 5 prospects have touches on both email AND linkedin; the outcome MUST attribute to the touch on the SAME channel as the reply.
5. **TTL-driven dormancy** — at least 5 prospects have replies dated 45+ days before "now" in a non-terminal state (replied / classified / active); Pass N's TTL driver MUST transition them to dormant.
6. **Closed_won surface** — at least 3 prospects have category=interest AND a `calendar_booking_confirmed` event 3 days after the reply; Pass O MUST emit `closed_won` outcomes for them.

## Schema

```yaml
version: 1
messages:
  - id: m_001                          # unique message id (corpus-scope)
    person_id: p_unsub_001              # unique person id (corpus-scope)
    channel: email                       # email | linkedin | twitter
    reply_event_type: reply_received     # event type to seed
    expected_category: unsubscribe       # ground-truth label
    expected_method: rule                # rule | llm — rule for everything the factory patterns match; llm for uncategorized
    subject: "Re: hi from us"            # reply subject (optional for non-email channels)
    body: "please unsubscribe me"        # reply body
    snippet: ""                          # reply snippet (optional)
    matches_pattern: "(?i)\\bunsubscribe\\b"  # the pattern that should fire (docs-only; not validated)
    adversarial: false                   # flag for adversarial scenarios
    multi_touch_count: 1                 # number of confirmed touches before the reply (default 1)
    cross_channel_extra: null            # null | "linkedin" | "email" — seed an extra touch on the other channel
    days_ago: 7                          # how many days before "now" the reply occurred (default ~7)
    closed_won_booking: false            # if true + category=interest, seed a calendar_booking_confirmed 3 days after reply
    llm_predicted_category: null         # for uncategorized rows: the category the fake LLM should return
    notes: "Pattern 1 — direct unsubscribe verb"
```

## Determinism

* The corpus order is the test's iteration order (id is sequential).
* The conftest builder uses a deterministic clock anchored at the test's `now` parameter (timestamps are computed relative to `now`).
* No random number generation.

## Maintenance

* When a factory pattern changes, audit this corpus for matching rows.
* When the dispatch priority changes, audit the adversarial rows.
* When a new long-tail category lands (Pillar I or later), extend the distribution + the per-category count assertion in ADR-0031 D137.
