# ADR-0019: Pillar C Week 6 — Calendar booking dispatcher, Cal.com webhook integration, and asymmetric retroactive backfill

- **Status:** Accepted
- **Date:** 2026-05-22
- **Pillar:** C (Multi-channel coherence — Week 6)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar C Week 1 (ADR-0014) shipped the convention-setting decisions every per-channel week composes against. Weeks 2 / 3 / 5 (ADRs 0015 / 0016 / 0018) shipped the first three per-channel synchronous dispatchers (LinkedIn invite + LinkedIn DM + Twitter DM); Week 4 (ADR-0017) shipped the first two reconcile passes (D + E for LinkedIn recovery), and Week 5 generalized the reconcile helper + added Pass F for Twitter DM recovery. Week 6 is structurally the **fourth per-channel week**, but it ships a fundamentally different shape: **calendar bookings are webhook-driven, not periodic-MCP-scrape**. The asymmetric two-phase commit shape inverts every assumption Weeks 2-5 baked in.

The seven concerns Week 6 resolves:

1. **Calendar bookings are NOT synchronous dispatcher → external API → confirmed sends.** Weeks 2-5 share one shape: the dispatcher calls an external MCP, gets a success/failure response, emits `_confirmed | _failed`. The Calendar booking dispatcher only generates a URL — `https://cal.com/yourhandle/intro?intent_id=cb_<ULID>` — and stamps it on the touch note for the operator to embed in their outbound email / DM. The `calendar_booking_intent` event fires at send time; the matching `calendar_booking_confirmed` fires **later** when the Cal.com webhook arrives (the recipient actually booked a slot). D65 pins the URL-fragment intent-id marker shape; D66 pins the webhook handler architecture.

2. **Cal.com URLs are structured artifacts, not free text.** Weeks 2-5's zero-width-Unicode marker shape (per ADR-0015 D39 / ADR-0016 D43 / ADR-0018 D58) lives inside in-message body text. Cal.com booking URLs have their own query-param semantics — the intent_id rides as `?intent_id=cb_<ULID>` instead of a zero-width Unicode marker. D65 pins this distinction + names the rejected alternative (force the ZW marker into URL fragment) explicitly.

3. **Cal.com retries failed webhooks up to 5 times per their docs.** The handler MUST be idempotent — a re-receipt of the same payload emits at most one `calendar_booking_confirmed`. Idempotence is keyed by `intent_id` (which round-trips through the URL); the handler short-circuits on existing `calendar_booking_confirmed` events for the same intent_id.

4. **Webhook handlers are a security boundary.** Forged payloads that the handler honors would emit fake `calendar_booking_confirmed` events, biasing every downstream consumer (Pillar D reply-correlator, Pillar G observability, Pillar I per-tenant state isolation). D67 pins the refuse-loud HMAC-SHA256 verification posture; the asymmetric-failure-cost calculus inverts toward refuse (missed legitimate webhook is recoverable via CLI replay; forged-honored is ledger-poisoning).

5. **A periodic reconcile Pass G is redundant under webhook-driven semantics.** Cal.com retries up to 5 times over ~24 hours; a separate reconcile pass that queries Cal.com's API and emits late `_confirmed` events would duplicate effort. D68 names the deferral with explicit rationale: ship Pass G as deferred-by-default; Pillar I revisits if multi-tenant operators surface recurring webhook-loss patterns.

6. **Cal.com has shipped multiple breaking payload-shape changes historically.** The intent_id can live at `payload.metadata.intent_id` (2024+ documented), `payload.responses.intent_id` (pre-2024), `payload.bookingFieldsResponses.intent_id` (2025+), or the originating URL preserved at `payload.bookingURL` (some integrations). D71 names the schema-version cascade + the unknown-schema refusal path.

7. **Retroactive backfill has asymmetric semantics.** Unlike Weeks 2-5 — where `sent: true` on a touch means the external API call succeeded — a `sent: true` Calendar booking touch means the operator shared the link, NOT that the recipient booked. The `calendar_booking_confirmed` state is operator-orthogonal: the recipient may or may not have followed through. D69's backfill emits `calendar_booking_intent` unconditionally; the paired `calendar_booking_confirmed` lands only when the touch carries an explicit `calendar_booking_confirmed_at:` field.

A reconcile Pass G is **deferred** per D68's rationale. The webhook surface IS the recovery mechanism; periodic-scrape recovery would double-emit when the webhook eventually arrives + Cal.com's retry budget covers the common-case "I missed one webhook" scenario.

Risks this ADR mitigates by design: **R001 (dispatcher crash between intent and outcome)** — the asymmetric two-phase shape forecloses the dispatcher's gap entirely (there IS no API call at send time); **R011 (cross-channel double-engagement)** — Week 6 dispatcher's `calendar_booking_confirmed` events (when emitted by the webhook) fire the cross-channel rule (ADR-0003) the moment they land; **R-NEW (forged webhook):** D67's refuse-loud HMAC verification forecloses ledger poisoning.

## Decision

### D65. Calendar booking event-type prefix `calendar_booking_*`; cost-event source `calendar_booking`; intent-id marker via URL fragment (NOT zero-width-Unicode)

Pillar C Week 6 dispatcher emits two-phase events with the event-type prefix `calendar_booking_*` (per ADR-0014 D33 — `calendar_booking_intent` / `calendar_booking_confirmed` / `calendar_booking_failed`, with NO `_aborted` type because the abort case is `calendar_booking_cancelled`, a Pillar D conversation-state concern). Every event carries `channel: "calendar"` (distinct from the email / linkedin / twitter channels).

The cost-event source is `source="calendar_booking"` per ADR-0015 D40's split-source convention. The dispatcher emits a single `cost_incurred` event per intent emission with `amount_usd=0.0` (Cal.com is free for individual operators on the personal plan) + `units=1` (per-window cap tick). Operators who configure budget-cap rules against `source=calendar_booking` get per-channel daily/weekly throughput caps.

**The intent-id marker scheme diverges from Weeks 2-5's zero-width-Unicode shape.** Cal.com URLs are structured artifacts with their own query-param semantics; the dispatcher synthesizes `<base>?intent_id=cb_<ULID>` and stamps that URL on the touch note for the operator to embed in their outbound message. The `cb_<ULID>` prefix replaces the email / LinkedIn / Twitter dispatchers' `snd_<ULID>` so:

- Operators inspecting their outbound messages see `cb_` in URLs + know the artifact is a calendar booking link.
- The webhook handler can short-circuit on the prefix when classifying inbound payloads.
- The URL is self-evidently a calendar artifact (vs `intent_id=snd_<ULID>` which would suggest an email artifact).

Cal.com's webhook payload preserves the originating URL's query params in `payload.metadata` (newer) / `payload.responses` (older) / `payload.bookingFieldsResponses` (newest) blocks; the handler reads the intent_id from whichever location the payload's schema-version exposes (per D71).

**The reaffirmation pattern continues.** Every per-channel week's first decision in its ADR is the channel-event-naming + cost-source confirmation per ADR-0015 D42's template. D65 makes the distinction explicit: the prefix `calendar_booking_` (consistent with ADR-0014 D33's catalog), the cost source `calendar_booking` (consistent with the D40 split-source convention), and the marker shape (URL-fragment per Cal.com's URL semantics, not in-body zero-width Unicode).

### D66. Cal.com webhook handler architecture — FastAPI route + CLI replay (BOTH)

The handler ships as a single core function (`process_payload` in `orchestrator/cal_com_webhook.py`) wrapped by two thin shims:

* **FastAPI route** (or equivalent WSGI/ASGI handler): the production surface. Cal.com POSTs the webhook to a public endpoint the orchestrator hosts; the route delegates to `process_payload` with the raw request body + the `X-Cal-Signature-256` header. Pillar I OSS bring-up names the deployment story (hosting the route, configuring the Cal.com webhook URL); Week 6 ships the function the route wraps.

* **CLI replay** (`python -m orchestrator.cal_com_webhook replay --payload-file <path>`): the testing + recovery surface. Operators with late / dead-lettered webhooks (Cal.com's retry budget exhausted) can store the raw payload + replay it through the same parsing core. Defaults to `apply=False` (dry-run) per the safer-ergonomic posture; operators explicitly `--apply` when ready.

Both shims share the same:
- HMAC signature verification (D67)
- JSON parsing + schema-version cascade (D71)
- Idempotence check (re-receipt short-circuit)
- Event emission (`calendar_booking_confirmed` + `cal_com_webhook_rejected`)

Why **both** vs picking one:

* **FastAPI alone** would fail Pillar I OSS bring-up's "single Python install" discipline — operators without a web-server-hosting environment couldn't process webhooks at all.
* **CLI alone** would force operators to manually capture every webhook from Cal.com's dashboard, eroding the operational-velocity benefit of the integration.
* **Both** lets production operators use the route while operators in restricted environments (or doing recovery) use the CLI. The shared core means one bug fix lands in both surfaces.

**A 2nd-surface option not chosen: SQS / Kafka queue consumer.** Pillar H (daemon + dispatcher) is the right home for a queue-driven surface IF the volume justifies it; Week 6's CLI surface covers the operator-deliberate replay use case at zero infra cost.

### D67. Webhook signature verification — REFUSE-LOUD on HMAC mismatch

Cal.com signs webhook payloads with a shared secret + HMAC-SHA256 (header `X-Cal-Signature-256`). The handler MUST verify the signature on every inbound webhook; mismatch → reject with `SignatureMismatchError` (HTTP 401 at the route layer) + log + emit a `cal_com_webhook_rejected` event with `reason: signature_mismatch` + `channel: calendar`.

**Why refuse-loud and not advisory.** The asymmetric-failure-cost calculus:

* **Missed legitimate webhook** (operator's Cal.com integration ships a bad signature, or the operator's shared secret is wrong): the ledger doesn't reflect the booking. The operator notices when the booking shows up in their calendar but Pillar G's funnel dashboard doesn't show it. Recovery: fix the secret + replay the payload via CLI. Recoverable at human-time scale.

* **Forged webhook honored**: fake `calendar_booking_confirmed` event emitted; the cross-channel rule (ADR-0003) fires against a recipient who never actually booked; downstream consumers (Pillar D reply-correlator, Pillar G observability, Pillar I per-tenant state isolation) carry biased state forever. Cleanup requires a manual tombstone + an audit-trail amendment.

The asymmetry — missed-legitimate is recoverable, forged-honored is ledger-poisoning — biases the gate to refuse. The handler MUST use `hmac.compare_digest` for constant-time comparison (no timing-side-channel leak on the prefix that did match).

**Empty-shared-secret edge case.** An unconfigured webhook handler (no `shared_secret` configured yet) refuses every payload. An unconfigured handler is a misconfigured deployment, not a missing feature — operators MUST set the shared secret BEFORE the route goes live; the empty-secret refusal forecloses the silent-vulnerability path where an operator ships the handler without a secret and accepts every payload as valid.

**The `sha256=` header prefix.** Cal.com's header may carry a `sha256=` prefix per common webhook conventions; the handler tolerates either form. This is purely a parse-tolerance concession, not a security loosening — the HMAC bytes are still constant-time compared.

### D68. Pass G ship-or-defer decision — DEFER per webhook-driven recovery shape

**Week 6 does NOT ship a reconcile Pass G** for `calendar_booking_intent` recovery. The Cal.com webhook is the canonical recovery surface; a periodic reconcile pass would duplicate effort.

**Why defer instead of ship.**

* **Cal.com's retry budget covers the common case.** Cal.com retries failed webhooks up to 5 times with exponential backoff (~24 hours of retry window per their docs). 99%+ of "missed webhook" cases self-resolve within Cal.com's retry budget without orchestrator-side intervention.

* **The CLI replay path covers the long-tail case.** When the operator notices a missed webhook beyond Cal.com's retry budget (~24h+), they replay the stored payload via `python -m orchestrator.cal_com_webhook replay --payload-file <path>` per D66. Operator-deliberate recovery; one-time per missing webhook.

* **A periodic reconcile would re-fetch from Cal.com's API.** Cal.com's API has its own auth + rate-limit semantics distinct from the webhook surface; building a reconcile pass that queries the API would add a new MCP / adapter surface for the same recovery outcome the webhook provides natively.

* **A periodic reconcile would double-emit on race conditions.** If the webhook arrives late AND the reconcile pass already emitted a `_confirmed`, the indexer would see two `_confirmed` events for the same intent_id. The idempotence check would catch the duplication, but the diagnostic noise (`calendar_booking_confirmed` events with `_recovered_by: "reconcile"` vs `_emitted_by: "cal_com_webhook"`) would confuse operators trying to audit "which path emitted this event?"

**The future trigger.** If multi-tenant operators (Pillar I) discover recurring webhook-loss patterns (e.g., Cal.com's retry budget runs out before the operator notices, AND the CLI replay friction outweighs the benefit of automatic recovery), Pillar I can ship Pass G in a future per-week-review follow-up. D68 explicitly names this as the deferred path.

**Auxiliary surface for the audit case.** `orchestrator/cal_com_webhook.py::list_orphan_booking_intents` enumerates `calendar_booking_intent` events without paired `_confirmed`. Operators can pull this list manually to audit "which calendar booking links never got booked?" — Pillar I's CLI exposes the ergonomic. This is **not** Pass G; it doesn't emit `_aborted` events (there's no `calendar_booking_aborted` event type per ADR-0014 D33); it's a read-only audit surface operators consult on-demand.

### D69. Asymmetric pair semantics in `ledger/0006_baseline_calendar_booking_history`

Pillar C Weeks 2 / 3 / 5's per-channel backfills (`ledger/0003` / `ledger/0004` / `ledger/0005`) emit BOTH `_intent` AND `_confirmed` for every walked touch. Week 6's `ledger/0006` is asymmetric: emits `calendar_booking_intent` UNCONDITIONALLY but `calendar_booking_confirmed` ONLY when the touch carries `calendar_booking_confirmed_at:`.

**Why asymmetric.**

* **`sent: true` semantics differ across channels.** For LinkedIn invites / DMs / Twitter DMs / email: `sent: true` = the API returned success = the send happened. For calendar bookings: `sent: true` = the operator shared the link = the operator emitted intent. The booking itself (the `_confirmed` state) is orthogonal — the recipient may not have followed through.

* **A symmetric backfill would emit false-confirmed events.** If `ledger/0006` mirrored `ledger/0005` and emitted `calendar_booking_confirmed` for every `sent: true` touch unconditionally, the ledger would carry confirmed events for calendar bookings the recipient never actually made. The cross-channel rule (ADR-0003) would then block downstream sends based on phantom bookings — a correctness regression.

* **The asymmetric shape preserves operator intent.** Pre-Pillar-C operators with retroactive booking-confirmation knowledge stamp `calendar_booking_confirmed_at: <ISO>` on the touch BEFORE running the migration; the backfill emits the paired confirmed. Operators without that retroactive knowledge see intent-only backfill — the correct shape because the orchestrator genuinely doesn't know whether the recipient booked.

**The `calendar_booking_confirmed_at:` field on the touch note.** Operators stamp this field manually (Pillar I CLI may add a discovery helper that queries Cal.com's booking-history API + stamps the field for matching touches). The field is operator-deliberate-on-knowledge; absence is correctly interpreted as "not yet booked or status unknown."

### D70. Downstream pillar impact

Per the ADR-0009 / 0010 / 0011 / 0012 / 0013 / 0014 / 0015 / 0016 / 0017 / 0018 convention (every Pillar B + C ADR explicitly names cross-pillar impact):

* **Pillar D (reply + conversation handling).** Pillar D's reply joiner correlates inbound replies (email reply, LinkedIn DM reply) to their originating `calendar_booking_intent` via the URL fragment intent_id. When the recipient replies to the calendar invite email saying "moved to Wednesday — see new booking link", Pillar D parses the calendar URL out of the body + correlates the new intent_id. Pillar D also consumes Cal.com's `BOOKING_CANCELLED` webhook (a separate event class from `calendar_booking_confirmed` per ADR-0014 D33) to emit `calendar_booking_cancelled` events for win/loss attribution. The reply joiner reads `calendar_booking_id` from the `calendar_booking_confirmed` event to deduplicate inbound cancellation notifications.

* **Pillar E (discovery quality + lineage).** No direct interaction. Pillar E adds `discovery_lineage:` blocks to Person frontmatter; per-touch calendar fields are orthogonal. Pillar E's `discovery_lineage:` may include a `discovered_via_calendar:` field that ties to a Pillar C `calendar_booking_confirmed` event — the cross-pillar query is one join, no Pillar C schema change.

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring operates on touch body content (the cover message wrapping the booking URL). The dispatcher's URL-fragment intent-id marker (D65) lives in the URL — NOT in free text — so Pillar F's voice-scorer doesn't need a marker-stripping step (the LinkedIn / Twitter marker-stripping discipline doesn't apply). Pillar F's future per-touch `calendar_action:` discriminator (if Pillar F adds a "calendar group booking" action class — currently deferred per D69's no-action-discriminator rationale) lands here.

* **Pillar G (observability).** Pillar G's per-channel migration audit-trail dashboard reads `ledger/0006`'s `migration_event` filtered by `channel="calendar"` per ADR-0014 D35; Week 6's diagnostic fields (`calendar_intents_emitted`, `calendar_confirmeds_emitted`, `calendar_pairs_skipped`, `touches_without_person_match`) become per-migration observability rows. Pillar G's per-channel funnel dashboard reads `calendar_booking_intent | _confirmed | _failed` events with `channel: calendar` per D33 — one query per funnel state. The asymmetric backfill shape (intent without confirmed) becomes Pillar G's "link-shared-but-not-booked" funnel-conversion metric — operators see how many calendar invites converted to actual bookings. Pillar G also reads `cal_com_webhook_rejected` events for security observability ("how often does our webhook secret rotation break?").

* **Pillar H (daemon + dispatcher).** Pillar H's per-stage parallelism limits become per-channel + per-action — Calendar booking link generation is essentially free (no API call) so parallelism caps don't bind. The webhook handler's per-request idempotence check (linear ledger scan) becomes Pillar H's optimization target if the calendar-booking ledger grows large enough to make per-request scanning hot; the current shape matches the rest of the framework's walk-the-ledger-once convention.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel state isolation. The D63-style existing-operator-seed block (this ADR's §"Existing-operator seed") aggregates into Pillar I's CLI as `python -m orchestrator.migrations seed --pillar-c --channel calendar_booking`. The Cal.com webhook URL configuration is operator-deliberate per D66 — operators set the webhook URL in their Cal.com dashboard + the shared secret in their orchestrator config. Pillar I's CLI may surface a `python -m orchestrator.cal_com check-webhook` ergonomic for webhook-config validation. The webhook handler's tenant-routing extension (a future `?tenant=acme` query param on the booking URL) is a Pillar I concern + does not require Pillar C schema changes.

* **Pillar J (security + compliance).** GDPR-forget on a Person who has calendar booking touches: the calendar touch notes are deleted (Pillar J's forget tooling per ADR-0010's pattern), and per-Person `calendar_booking_*` events are tombstoned. The `calendar_booking_url` field is potentially-PII (it contains the recipient's Person-derived intent_id; reverse-mapping is operator-side); Pillar J's forget tooling redacts it on tombstone. `calendar_booking_id` (Cal.com's per-booking identifier) is sensitive — Pillar J's forget tooling MUST redact it because Cal.com's API exposes booking details keyed on this id.

### D71. Cal.com webhook payload schema versioning

Cal.com has shipped multiple breaking payload-shape changes since the integration's inception. The handler reads `triggerEvent` + `payload` from the top-level dict; intent_id extraction tries multiple locations in priority order:

1. **`payload.metadata.intent_id`** (Cal.com's documented custom-input metadata block; 2024+ default).
2. **`payload.responses.intent_id`** (Cal.com's older custom-questions surface; pre-2024 deployments).
3. **`payload.bookingFieldsResponses.intent_id`** (Cal.com's newest booking-fields surface; 2025+ deployments).
4. **Originating URL fallback** — the URL is preserved at `payload.bookingURL`, `payload.referrer`, or `payload.location.value` depending on the Cal.com release; the handler regex-extracts `cb_<ULID>` from the URL query string.

**Unknown-schema-shape behavior.** If NONE of the documented locations expose the intent_id, the handler raises `UnknownPayloadSchemaError` + emits a `cal_com_webhook_rejected` event with `reason: no_intent_id`. The operator must investigate the payload + decide whether to extend the handler's `extract_intent_id` function with a new branch + a regression test (the doc-test discipline says: when Cal.com ships a new payload shape, add the branch with a test pinning the field path).

**Why explicit cascade vs config-driven extraction.** Cal.com's documented-extension paths are stable per Cal.com release; a config-driven extractor (e.g., `intent_id_paths: ["metadata.intent_id", "responses.intent_id"]`) would force the operator to maintain a config that mirrors the handler's logic. Hardcoding the cascade in `extract_intent_id` ties the implementation to the schema-version knowledge the handler carries — operators don't have to know the schema-version map.

**Schema-version observability.** The emitted `calendar_booking_confirmed` event carries `schema_version: <tag>` (one of `metadata` / `responses` / `booking_fields_responses` / `originating_url`) so Pillar G can chart Cal.com schema-version drift over time. Operators see when Cal.com's payload shape is migrating from one location to another + can prepare for the deprecation of the older location.

## Alternatives considered

### D65-Alt1: Use zero-width-Unicode marker in the URL fragment

Embed the ZW-marker per ADR-0015 D39 / ADR-0016 D43 / ADR-0018 D58 into the URL fragment (`https://cal.com/yourhandle/intro#<ZW>outreach-intent:<id><ZW>`). **Rejected** because:

* URL fragments (the `#` part) are NOT preserved by Cal.com's webhook payload. The fragment is client-side only — browsers strip it before sending the request to Cal.com's servers, so the orchestrator-side correlator wouldn't see the marker at all.
* URL query params (`?intent_id=...`) ARE preserved by Cal.com's webhook (per Cal.com's documented behavior + per the schema-version surfaces in D71). The query-param shape is the structurally-correct match for the round-trip surface.
* Zero-width Unicode in URLs is non-standard + breaks URL normalizers + breaks operator-readability of the URL in the touch body. URLs are structured artifacts; the query-param scheme fits the structure.

### D65-Alt2: Use `snd_<ULID>` prefix (consistent with email / LinkedIn / Twitter dispatchers)

Keep the dispatcher's `_ledger.new_intent_id()` default `snd_<ULID>` shape; the URL becomes `cal.com/yourhandle/intro?intent_id=snd_<ULID>`. **Rejected** because:

* The `snd_` prefix is meaningful for email + LinkedIn + Twitter (those are "sends" — the dispatcher actually invokes an external API). Calendar bookings don't have a "send" action — the dispatcher just generates a URL. The `cb_` prefix is the structurally-correct match for the calendar booking action class.
* URL inspection (operator scanning their outbound message) is improved by `cb_` — operators can tell at a glance which URLs are calendar-booking links. The cost is a single optional `prefix:` kwarg on `new_intent_id()`; the gain is operator-visible discrimination.
* The webhook handler can short-circuit on the `cb_` prefix when classifying inbound payloads — useful if future tenant-routing or batch-handling logic needs to filter by calendar-booking event-class.

### D65-Alt3: Embed the intent_id in a hidden form field instead of the URL query string

Cal.com's booking form supports custom form fields (`bookingFieldsResponses`). The dispatcher could generate a URL pointing to a Cal.com form pre-populated with a hidden `intent_id` field. **Rejected** because:

* The URL shape becomes operator-incomprehensible: `cal.com/yourhandle/intro?prefill=eyJpbnRlbnRfaWQiOiJjYl9YWFhYIn0=` (base64-encoded prefill JSON) vs `cal.com/yourhandle/intro?intent_id=cb_XXXX`. The query-param shape is the operator-readable, debuggable, and inspectable surface.
* Cal.com's prefill-via-URL shape has shipped breaking changes more often than the query-param shape (per Cal.com's release history); the URL query-param scheme is the lower-volatility surface.
* The prefill-vs-query-param choice is operator-config-deliberate (operators can choose either surface in their Cal.com config); the framework standardizes on the query-param shape for simplicity + uses the prefill shape only if the operator's Cal.com config disables query-param preservation.

### D66-Alt1: FastAPI route only (skip CLI replay)

Ship only the production route. **Rejected** because:

* Pillar I OSS bring-up's "single Python install" discipline rejects mandatory web-server hosting. Operators without a public-facing endpoint can't process webhooks at all without the CLI replay path.
* The CLI replay path is the operator-recovery surface for Cal.com's webhook-retry-budget-exhausted case. Without it, operators with a missed webhook beyond Cal.com's retry budget would have NO orchestrator-side recovery option (other than manually emitting events via the ledger CLI — a much wider operator-surface).
* Test-friendliness: the CLI replay function (which IS `process_payload` wrapped) is the natural unit-test entry point. Skipping it would force every webhook-handler test to spin up a FastAPI test client.

### D66-Alt2: CLI replay only (skip FastAPI route)

Ship only the manual CLI surface; operators capture webhooks from Cal.com's dashboard manually. **Rejected** because:

* Manual webhook capture is operationally hostile. Cal.com webhooks fire on every booking; operators with realistic outreach volumes would spend hours per week capturing + replaying payloads.
* The production route is the natural Cal.com integration shape; shipping only the CLI surface would tell operators "use Cal.com's webhook integration manually" which defeats the integration's value.
* The shared core means the CLI path is essentially free once the production route ships.

### D66-Alt3: Queue-based consumer (SQS / Kafka / Redis Streams)

Cal.com posts to a public webhook endpoint that forwards to a queue; orchestrator workers consume. **Rejected for Week 6; reserved for Pillar H.** The queue surface is the right shape IF the volume / latency / reliability requirements justify the operational overhead (queue infra, dead-letter handling, monitoring). Week 6's solo-operator + small-team OSS-target volume doesn't justify the operational cost. Pillar H (daemon + dispatcher) is the right home for a queue-driven surface when the volume + the SLO require it.

### D67-Alt1: Advisory signature verification (log mismatch, accept anyway)

Verify the signature, log a warning on mismatch, but still emit `calendar_booking_confirmed`. **Rejected** because:

* The asymmetric-failure-cost calculus inverts toward refuse. A forged-honored payload poisons every downstream consumer; the security cost of an advisory-only mode is too high for a webhook handler.
* Advisory verification creates alert fatigue: every misconfigured signature produces a warning that operators learn to ignore. The signal becomes useless.
* The recovery path for legitimate-but-rejected payloads (operator's secret rotated, Cal.com's signing changed) is the CLI replay — operator-deliberate, low-friction. Advisory mode would erode the security boundary without operational benefit.

### D67-Alt2: Per-route shared-secret configuration (skip secret entirely for testing)

Allow the operator to disable HMAC verification entirely via a `verify=False` config flag. **Rejected** because:

* A disable-verification config is a runtime foot-gun. Operators copy-paste configs across environments; a `verify=False` development config silently shipped to production is a security incident waiting.
* The handler's `verify_sig=False` keyword argument exists for TESTS (a fixture passes a known-bad signature to exercise the parsing path); production code paths always leave `verify_sig=True`. The split between test-mode and production-mode lives at the test-fixture level, not the configuration level.
* If an operator legitimately needs to disable verification (e.g., during a debugging session against a staging Cal.com), they can disable Cal.com's signing on the staging side + leave the orchestrator's verification on. The friction is intentional + forecloses the silent-shipping path.

### D67-Alt3: Require a separate per-Cal.com-event-type shared secret

Use one shared secret for BOOKING_CREATED, another for BOOKING_CANCELLED, etc. **Rejected** because:

* Cal.com signs with a single per-webhook-config shared secret across all event types; the per-event-type split would force the operator to maintain multiple secrets matching multiple Cal.com webhook configs.
* The event-type filtering happens AFTER signature verification (the handler verifies, then checks `triggerEvent`). The per-event-type secret would force re-verification per event type, doubling the operational complexity for no security gain (the per-event-type secret doesn't protect against forged BOOKING_CREATED — only against operators who have ONE secret rotated and another stale).
* The shared-secret-rotation story is simpler with one secret per webhook config (the Cal.com dashboard's webhook config has one secret per row).

### D68-Alt1: Ship Pass G as a periodic reconcile pass that queries Cal.com's API

Add `reconcile.run_pass_g` that queries Cal.com's booking-list API + emits `_confirmed` for matched intent_ids. **Rejected** per the rationale above:

* Cal.com's retry budget covers the common case (~24 hours of retries).
* The CLI replay path covers the long-tail case.
* A periodic reconcile adds API surface area, rate-limit concerns, and double-emit race conditions.

The handler's `list_orphan_booking_intents` audit function provides the operator-visible enumeration (D68 §"Auxiliary surface") without the periodic-scrape complexity.

### D68-Alt2: Ship Pass G as a dry-run-only audit pass

Pass G runs read-only, logs "would emit _confirmed for these intent_ids", but doesn't write anything. **Rejected** because:

* The `list_orphan_booking_intents` function covers the audit case at zero infrastructure cost (the function is a one-liner the operator can call via the CLI; no reconcile-orchestration wiring required).
* A dry-run-only Pass G would still need the periodic-execution wiring (cron, daemon, etc.) just to call the audit function — that wiring is what Pass G's "deferred" status defers.
* The auxiliary `list_orphan_booking_intents` surface is the structurally simpler shape for the audit case; Pass G would be over-engineered for the same outcome.

### D68-Alt3: Ship Pass G generalizing `_run_channel_intent_pass`

Reuse the Week 5 generalized helper (per ADR-0018 D62) by passing calendar-specific parameters. **Rejected** because:

* The shared helper assumes the channel has an MCP / API surface to query for marker matches. Cal.com doesn't expose a "search bookings by URL query param" API; the helper's `extract_marker_match` callable has no natural binding for the calendar surface.
* Even if the helper could be extended (e.g., to query Cal.com's booking-list API by date range + post-filter for intent_ids), the result emits `_aborted` events for unmatched intents — which calendar bookings DON'T have (no `calendar_booking_aborted` per ADR-0014 D33). The helper's abort-emission contract mismatches the calendar event-type catalog.
* The natural shape — webhook handles confirmation, operator manually audits orphans — doesn't fit the generalized helper. Forcing the fit would be the wrong abstraction.

### D69-Alt1: Symmetric backfill (emit both _intent and _confirmed for every sent: true touch)

Mirror `ledger/0005`'s shape: every `channel: calendar` + `sent: true` touch backfills to a paired intent + confirmed. **Rejected** because:

* `sent: true` on a calendar touch means "operator shared the link" — NOT "recipient booked". A symmetric backfill would emit `calendar_booking_confirmed` events for bookings that never actually happened.
* The cross-channel rule (ADR-0003) fires on `_confirmed` events; phantom confirmed events would block legitimate cross-channel sends for recipients who never booked.
* Pillar G's funnel observability would over-report bookings — the dashboard would show "100% booking conversion rate" because every shared link counts as a confirmed booking. The asymmetric shape preserves the real conversion-rate signal.

### D69-Alt2: Skip the confirmed backfill entirely (intent-only, even when calendar_booking_confirmed_at: is set)

Always emit intent only; ignore any operator-stamped `calendar_booking_confirmed_at:`. **Rejected** because:

* Operators with retroactive knowledge ("I know this person booked on date X — let me stamp the field + run the migration") would have no path to capture that history in the ledger. The retroactive-confirmed event would never land.
* The asymmetric shape's whole point is to respect operator intent — when the operator knows the recipient booked, the ledger should reflect it. Ignoring the field undermines the operator's signal.
* Pillar D's reply-correlator + Pillar G's funnel observability + Pillar I's per-tenant analytics ALL benefit from accurate retroactive confirmed events. Skipping them would degrade three downstream pillars.

### D69-Alt3: Use a separate vault migration to stamp calendar_booking_confirmed_at: automatically

Walk Cal.com's API for historical bookings; stamp `calendar_booking_confirmed_at:` on matching touch notes automatically. **Rejected for Week 6** because:

* Cal.com API integration is operator-deliberate (requires API token, base URL config, rate-limit handling); shipping it as a vault migration would force every operator through that setup even if they don't have retroactive knowledge to capture.
* The Pillar I OSS bring-up's CLI is the right surface for the optional "discover historical bookings from Cal.com API + stamp touches" ergonomic. Operators who want it can run it then; operators who don't have to.
* The asymmetric-backfill shape (intent unconditionally; confirmed only when explicitly stamped) is the correct framework default; the API-driven stamping is an optional augmentation.

### D70-Alt1: Defer §Downstream pillar impact section to a future ADR

Skip in Week 6; cover in Pillar D's ADR. **Rejected** by the established ADR-0009-onwards convention; every Pillar C ADR ships the section.

### D70-Alt2: Aggregate Week 5 + Week 6 downstream impact sections

Treat the per-week §Downstream impact sections as cumulative. **Rejected** because the per-ADR section gives readers a per-week scope without requiring a multi-ADR read-through.

### D70-Alt3: Skip the Pillar E section (no direct interaction)

Cover only the pillars Calendar bookings interact with directly. **Rejected** by the established convention — every per-Pillar-C ADR documents every downstream pillar so future readers see the explicit "no interaction" rather than ambiguous absence.

### D71-Alt1: Hardcode a single schema-version location (metadata only)

Trust Cal.com's documented stable surface; refuse-loud on any other shape. **Rejected** because:

* Operators with older Cal.com deployments would have NO migration path — the handler would refuse-loud every payload until Cal.com upgraded their integration to the metadata-only surface.
* Cal.com's documented-stable surface has shipped breaking changes historically; "stable" is operator-dependent. The cascade approach handles real-world deployment diversity.

### D71-Alt2: Config-driven extraction paths

Operators configure the extraction path priority in their orchestrator config (e.g., `intent_id_paths: ["metadata.intent_id", "responses.intent_id"]`). **Rejected** because:

* Forces operator-side knowledge of Cal.com's payload-shape evolution. The handler should encode that knowledge; operators consume it.
* Config drift: operators copy-paste configs across deployments; the config-vs-actual-payload mismatch becomes a debugging nightmare.
* The cascade order is operator-irrelevant in the common case; the handler tries each path silently + reports which one matched (via the `schema_version` event field for observability).

### D71-Alt3: Refuse-loud on unknown payload shape (don't fall back to originating URL)

If the documented locations all miss, refuse-loud immediately. Skip the URL-fallback path. **Rejected** because:

* The URL fallback covers the case where Cal.com's customer-defined fields (metadata / responses / bookingFieldsResponses) don't get populated due to operator-side Cal.com config issues — but the URL itself is still preserved in some location of the payload.
* The URL regex match is the same-shape extraction that Pass D / E / F use for LinkedIn / Twitter (scanning text for the marker); it's a well-trodden recovery path.
* The fallback emits a `schema_version: originating_url` tag on the confirmed event so Pillar G can chart "how often does the fallback path fire?" — operator-actionable signal without security loss.

## Existing-operator seed

Operators with pre-existing calendar booking touches (future OSS operators with pre-Pillar-C calendar history; Yang specifically has none as of 2026-05-22) may want to skip the retroactive backfill. Per ADR-0014 D36 + ADR-0015 D41 + ADR-0016 D46 + ADR-0017 D51 + ADR-0018 D63 (the established convention), this ADR provides the §"Existing-operator seed" REPL incantation.

### Skipping `ledger/0006` only

For operators who want their pre-Pillar-C Calendar booking ledger state preserved as-is (no `calendar_booking_*` events emitted retroactively):

```python
from datetime import datetime, timezone
from orchestrator.migrations.state import (
    MigrationState, mark_applied, save_state_atomic,
    load_state, DEFAULT_STATE_DIR,
)
from orchestrator.migrations.types import MigrationCategory

state = load_state(DEFAULT_STATE_DIR)
now = datetime.now(timezone.utc)
mark_applied(
    state, MigrationCategory.LEDGER, "0006_baseline_calendar_booking_history",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `ledger/0006` as applied; `apply()` skips it; the operator's calendar booking history stays exactly as it was pre-Week-6 (touch notes + no `calendar_booking_*` ledger events).

### Recommended posture per operator profile

| Operator profile | Recommended action |
|---|---|
| New OSS operator (zero pre-Pillar-C calendar booking history) | Run `apply()` normally. The migration emits zero events (no calendar touches to walk); the migration_event audit trail records the no-op for continuity. |
| Existing operator who wants historical events preserved as-is | Seed `ledger/0006`. Pre-existing calendar touches (if any) remain unstamped at the ledger level; new touches via the Week 6 dispatcher carry full asymmetric events. |
| Existing operator who wants retroactive emissions but no recipient-actually-booked events | Run `apply()` normally. `ledger/0006` emits `calendar_booking_intent` for every walked touch (no `_confirmed` because no touch has `calendar_booking_confirmed_at:`); the asymmetric shape preserves the "shared but not booked" state. |
| Existing operator who wants full retroactive history (intent + confirmed) | Stamp `calendar_booking_confirmed_at: <ISO>` on every touch where the recipient actually booked; THEN run `apply()`. The backfill emits both events per D69's asymmetric semantics. |
| Yang (current sole operator, as of 2026-05-22) | Recommended: run `apply()` normally. Yang's pre-Pillar-C calendar booking count is zero (the channel didn't have a dispatcher); the migration is a no-op for the current operator. The seed-then-skip is operationally identical for Yang; the `apply()` path keeps the convention uniform across all four channels. |

**Week 6 does NOT ship a vault migration.** Calendar bookings have one outreach action (share a link); the dispatcher writeback fields (`calendar_booking_intent_id`, `calendar_booking_url`, `calendar_booking_invited_at`) populate at runtime + no pre-existing field needs migrating. The `calendar_booking_confirmed_at:` field is operator-deliberate-on-knowledge (per D69) — no migration backfills it.

## Backfill overlap with `ledger/0002`

Calendar touches that are `sent: true` produce events from BOTH migrations after a full apply:

1. `send_intent` + `send_confirmed` from `ledger/0002` (channel-agnostic walker emits a generic pair for every `sent: true` touch).
2. `calendar_booking_intent` from `ledger/0006` (asymmetric per-channel backfill; no paired `_confirmed` unless the touch has `calendar_booking_confirmed_at:`).

The dual representation is by design per ADR-0015 §"Backfill overlap with ledger/0002" (Pillar C Week 2 established the rationale; ADR-0016 / 0018 extended it for LinkedIn DM + Twitter DM; Week 6 extends to calendar bookings). The cross-channel rule's first-match-wins semantics short-circuit correctly — but note the calendar case differs from Weeks 2-5: the `ledger/0002` `send_confirmed` (channel: calendar) is emitted because the operator shared the link, while the per-channel `calendar_booking_confirmed` is emitted ONLY when the recipient actually booked. Downstream consumers (Pillar D win-attribution, Pillar G funnel observability) consume the per-channel `calendar_booking_*` events specifically because they distinguish link-shared vs booking-confirmed states.

## Dry-run interaction

Per ADR-0013 D24-N + the ADR-0014 / 0015 / 0016 / 0017 / 0018 inheritance pattern, dry-run interaction for Week 6's deliverables works as follows:

* **`ledger/0006` apply with `ctx.dry_run=True`** runs the walker + classification logic + intent-id computation WITHOUT writing any events to the ledger. The result reports the would-emit counts; no `calendar_booking_*` events are appended; no `migration_event` is emitted (per ADR-0010 D17 "a dry run mutates nothing"). The pre-existing dry-run limitation (vault/0002 hasn't stamped Person.id yet in the same dry_run batch) applies; the backfill reports 0 affected for cross-category-dependent dry-run.
* **`orchestrator.cal_com_webhook.process_payload` with `apply=False`** runs the verification + parsing + idempotence-check WITHOUT writing any events. The result reports the would-emit `calendar_booking_confirmed` with `_dry_run: True`. Matches the reconcile dry-run convention.
* **`replay_from_file` defaults to `apply=False`** per D66's safer-ergonomic posture. Operators explicitly `apply=True` when ready to commit.
* **`gated_calendar_booking_one` has no dry-run mode** (consistent with `gated_send_one` + `gated_li_invite_one` + `gated_li_dm_one` + `gated_tw_dm_one`); operators who want a dry-run path skip the dispatcher call entirely.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. The ledger is authoritative; Cal.com is the booking-confirmation surface for I/O; the webhook handler is a transport. The `_emitted_by: "cal_com_webhook"` field on confirmed events denormalizes the emission source for observability (distinct from `_recovered_by: "reconcile"` for reconcile-emitted events or `_recovered_by: "backfill"` for migration-emitted events).
- **I2 (two-phase commit on every external side effect):** Every calendar booking goes through `calendar_booking_intent` (at send time) → Cal.com webhook → `calendar_booking_confirmed`. The asymmetric shape differs from email / LinkedIn / Twitter (which emit `_confirmed` synchronously at the dispatcher) — but I2's enforcement is stronger here because the confirmed event is gated by HMAC-verified recipient action (the recipient actually booked), not by an API success response (which could be lying). The webhook handler is the recovery vehicle for crashes between intent-write and webhook-receipt; the CLI replay path is the operator-deliberate recovery.
- **I3 (schema versioning):** No new event-schema versions introduced. The calendar booking event types (`calendar_booking_intent | _confirmed | _failed`) are already in `_INTENT_TYPES` + `_OUTCOME_TYPES` per Week 1's generalization (ADR-0014 D33).
- **I4 (reproducible state):** `ledger/0006`'s intent_ids are deterministic (`bf_cb_<hash>`); re-runs produce identical results. The webhook handler's idempotence-check ensures Cal.com's retry budget (up to 5 retries) doesn't produce duplicate `_confirmed` events.
- **I5 (observable by default):** `migration_event` audit-trail emitted per `ledger/0006` apply with per-diagnostic field counts. The webhook handler emits `cal_com_webhook_rejected` events for every rejection (signature mismatch / invalid JSON / no intent_id) with a structured `reason` field. Pillar G can chart per-channel funnel + per-rejection-cause distributions without text-matching.
- **I6 (tests prove invariants):** `tests/test_send_gate_calendar_booking.py` (direct unit tests for `gated_calendar_booking_one`) + `tests/test_cal_com_webhook.py` (direct unit tests for the webhook handler) + `tests/test_migrations_ledger_0006.py` (direct unit tests for the backfill). `tests/test_multi_channel_coherence.py::TestCalendarBookingChannel` un-skips all 4 rows + adds a 5th source-level pin for end-to-end coherence.
- **I7 (cost is a first-class concern):** The Week 6 dispatcher emits `cost_incurred` events with `source="calendar_booking"` per ADR-0015 D40's split-source convention + ADR-0019 D65. The webhook handler doesn't emit cost events (the inbound webhook is operator-time cost, amortized across the run-frequency budget).
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains an ADR-0019 row. The Week 6 commit's per-week handoff document (`.planning/HANDOFF-pillar-c-week-6.md`) scoped the deliverables.

Does not weaken any invariant. I2's enforcement is strengthened (the asymmetric two-phase shape gates on actual recipient action, not just API success). I5's observability is strengthened (the webhook handler's rejection events surface security incidents + Cal.com schema-version drift).

## Migration / rollout

Week 6 ships one new ledger migration + one new dispatcher function + one new webhook-handler module. No vault migrations (per D69's no-action-discriminator + no-pre-existing-field rationale). No new policy migrations (per ADR-0015 D40's split-source operator-deliberate-activation convention).

**Operator-facing changes:**

1. **`runner.pending()` increments by 1 → 10.** The new `ledger/0006_baseline_calendar_booking_history` joins the apply order after `ledger/0005`. Operators who want to skip it use the §"Existing-operator seed" incantation.

2. **A new dispatcher entry point — `gated_calendar_booking_one` in `skills/send-outreach/scripts/send_queued.py`.** The dispatch-outreach skill gets a new branch for the calendar-booking register. Operators who share booking links via the skill see new ledger events the moment they share their first link.

3. **A new module — `orchestrator/cal_com_webhook.py`** — that hosts the webhook handler core. Operators deploying the FastAPI route per D66 add the route wiring; operators using the CLI replay path per D66 invoke `replay_from_file` directly. Pillar I OSS bring-up surfaces both ergonomics via CLI commands.

4. **A new operator-config requirement: `cal_com_base_url`.** Operators who want to share calendar booking links MUST configure a base URL (per-Person via `calendar_booking_url_base:` frontmatter field, or operator-default via the dispatcher's `cal_com_base_url` kwarg). Without it the dispatcher refuses-loud with `no_cal_com_base_url`.

5. **A new operator-config requirement: `cal_com_webhook_shared_secret`.** Operators deploying the FastAPI route MUST configure the shared secret matching their Cal.com webhook config. Misconfigured (empty) secret causes the handler to refuse-loud per D67.

6. **First-invocation against a stale ledger may emit a recovery wave** per the per-channel convention. Operators see new `calendar_booking_intent` events in their first `apply()` run; the asymmetric backfill emits one intent per `sent: true` calendar touch.

**The Week 6 commit's verification surface:**

```bash
# 1. One new migration (9 → 10 pending).
$ python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print(len(r.pending()))"
10

# 2. New dispatcher + webhook + backfill tests pass.
$ python -m pytest tests/test_send_gate_calendar_booking.py tests/test_cal_com_webhook.py tests/test_migrations_ledger_0006.py -v
# Expected: ~90 passed.

# 3. The previously-skipped Calendar coherence rows un-skip and pass.
$ python -m pytest tests/test_multi_channel_coherence.py::TestCalendarBookingChannel -v
# Expected: 5 passed, 0 skipped.

# 4. The full suite is green with the new tests added.
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: ~1590-1620 passing.

# 5. ADR-0019 exists; README index gains the row; PILLAR-PLAN §6 Pillar C
#    row updated to reflect Week 6 ship.
$ ls docs/adr/0019-pillar-c-calendar-booking-dispatcher.md
$ grep "0019" docs/adr/README.md
$ grep "Week 6" docs/PILLAR-PLAN.md
```

## References

- ADR-0001 (policy engine architecture) — `RuleContext.channel` field; the Week 6 dispatcher constructs context with `channel="calendar"`.
- ADR-0003 (channel as first-class policy predicate) — the `CrossChannelTouchRule` Week 6's `calendar_booking_confirmed` events fire against; the rule's `consider_channels:` matches `calendar` as a first-class value.
- ADR-0006 (cost-event model) — Week 6 emits `cost_incurred` events with `source="calendar_booking"` per D65.
- ADR-0008 (budget rules) — operators configure `budget.window-cap` rules against `source=calendar_booking` for per-channel throughput caps.
- ADR-0009 (migration framework) — `ledger/0006` is the sixth ledger migration; the runner's apply order accommodates it without amendment.
- ADR-0010 (ledger migrations) — D14 append-only invariant (Week 6 emissions are append-only); D17 migration_event emission contract.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — D24-N dry-run interaction (Week 6 deliverables respect dry-run); D32 per-ADR existing-operator seed pattern (this ADR instantiates).
- ADR-0014 (Pillar C foundation) — D33 channel event-type naming convention (D65 reaffirms `calendar_booking_*` prefix + names the asymmetric absence of `_aborted`); D35 per-channel `migration_event` channel field (ledger/0006 stamps `channel="calendar"`); D36 per-ADR seed pattern.
- ADR-0015 (Pillar C Week 2 — LinkedIn invite) — D38 per-channel vault-action discriminator (D69 defers calendar's equivalent); D39 zero-width-Unicode marker (D65 diverges to URL-fragment marker); D40 cost-event source split (D65 reaffirms with `calendar_booking`); D41 per-migration seed pattern; D42 per-week per-channel rollout template (Week 6 is the fourth application).
- ADR-0016 (Pillar C Week 3 — LinkedIn DM) — D43 reaffirms D39's marker shape (D65 diverges); D44 requires-existing-connection gate (no calendar equivalent per D69); D46 per-migration seed pattern.
- ADR-0017 (Pillar C Week 4 — reconcile Pass D + E) — D48 serial-execution convention for multi-pass reconcile (no Pass G means the three-caller shape of `_run_channel_intent_pass` remains D + E + F per D68's defer; D48's serial-discipline rationale does NOT directly justify D68 — D68 is self-justifying per its own webhook-vs-periodic-scrape analysis); D50 marker-not-found abort semantics (not inherited by calendar — no `_aborted` event type per D33); D51 operator-facing rollout (this ADR follows the convention).
- ADR-0018 (Pillar C Week 5 — Twitter DM + Pass F) — D58 Twitter DM marker shape (D65 diverges to URL-fragment); D62 helper generalization (`_run_channel_intent_pass` — Pass G defer per D68 leaves the helper at three callers: D + E + F); D63 per-migration seed pattern (this ADR instantiates).
- `docs/PILLAR-PLAN.md` §2 Pillar C — exit criterion (binding text); §6 Pillar C row updated to reflect Week 6 ship.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D67's refuse-loud HMAC posture + D69's asymmetric backfill semantics.
- `docs/RISK-REGISTER.md` R001 (dispatcher crash between intent and outcome) — risk this ADR mitigates by design via the asymmetric two-phase shape (no synchronous API call at send time means no crash window between intent-write and API-success).
- `docs/RISK-REGISTER.md` R002 (false-confirm from delayed MCP response) — risk this ADR mitigates by gating `_confirmed` on HMAC-verified recipient action (not on API success).
- `docs/RISK-REGISTER.md` R011 (cross-channel double-engagement) — risk this ADR mitigates by design via the cross-channel rule firing against `calendar_booking_confirmed`.
- `docs/SOURCES-OF-TRUTH.md` — Cal.com is a booking-confirmation surface, not an SoT; the ledger is authoritative.
- `.planning/HANDOFF-pillar-c-week-5.md` — the prior week's handoff documenting Week 5's deliverables.
- `.planning/HANDOFF-pillar-c-week-6.md` — the handoff that scoped this commit's deliverables.
- `.planning/HANDOFF-pillar-c-week-7.md` — the next week's handoff scoping per-channel policy migrations.
- `orchestrator/cal_com_webhook.py` — Week 6's NEW module. The webhook handler + CLI replay surface.
- `orchestrator/ledger.py::new_intent_id` — Week 6 extended with `prefix:` kwarg (per D65) so calendar booking intent_ids mint `cb_<ULID>` instead of `snd_<ULID>`.
- `orchestrator/migrations/ledger/migration_0006_baseline_calendar_booking_history.py` — the Week 6 ledger backfill (asymmetric per D69).
- `orchestrator/policy/cross_channel.py` — the rule class Week 6's `calendar_booking_confirmed` events fire against; the rule's `type.endswith("_confirmed")` predicate matches `calendar_booking_confirmed` per ADR-0014 D33.
- `skills/send-outreach/scripts/send_queued.py` — `gated_calendar_booking_one` + `_calendar_booking_vault_writeback` + `_build_calendar_rule_context` + calendar constants (`CALENDAR_BOOKING_INTENT_ID_PREFIX`, `CALENDAR_BOOKING_URL_MAX_CHARS`, `CALENDAR_BOOKING_BLOCK_EXTRAS`).
- `skills/send-outreach/scripts/vault.py` — `PersonInfo.calendar_booking_url_base` + `TouchDraft.calendar_cover_message` + `TouchDraft.has_calendar_block` + the `## Calendar` section regex.
- `tests/test_send_gate_calendar_booking.py` — direct unit tests for `gated_calendar_booking_one` (~24 tests).
- `tests/test_cal_com_webhook.py` — direct unit tests for the webhook handler (~38 tests).
- `tests/test_migrations_ledger_0006.py` — direct unit tests for the backfill (~30 tests).
- `tests/test_multi_channel_coherence.py::TestCalendarBookingChannel` — un-skipped Week 6; 5 tests pinning end-to-end coherence + source-level symbol stability.
- `tests/fixtures/synthetic_pillar_b/vault/10 People/Fiona Forrest.md` — calendar-engaged Person added Week 6.
- `tests/fixtures/synthetic_pillar_b/vault/40 Conversations/2026-04-25 Fiona calendar booking.md` — Calendar booking touch added Week 6 (NO `calendar_booking_confirmed_at:` field — substrate for asymmetric backfill semantics per D69).
- Forward-references (planned):
  - **ADR-0020** (Pillar C Week 7): Per-channel policy migrations — first of Weeks 7-11. Per-channel cooldown rules (e.g., LinkedIn invite weekly cap; Twitter DM daily cap; calendar booking per-Person cap) materialize as `policy/0002_*` through `policy/0006_*` migrations that operators run to activate the channel-specific rate-limit shapes the v1 factory cooldowns.yml ships.
  - **Pillar D**: Reply correlator consumes `calendar_booking_confirmed` per D70; `calendar_booking_cancelled` event class lands here (per ADR-0014 D33 — not in Pillar C).
  - **Pillar H daemon** (Weeks 31-36): the webhook handler's FastAPI route lives here; the daemon-as-web-server pattern is the operational deployment of D66's production surface.
  - **Pillar I OSS bring-up**: ships `python -m orchestrator.cal_com_webhook replay` CLI ergonomic + the operator-facing `python -m orchestrator.cal_com check-webhook` validator + tenant-routing extension per D70's multi-tenant note.
