# Changelog

Notable changes to outreach-factory, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There are no tagged
releases yet, so entries are dated by when they landed on the public `main`
branch.

## 2026-06-02

### Added
- Zero-setup demo. `bin/outreach-factory demo` prints a complete, voice-grounded
  cold email for a fake prospect using only the Python standard library, with no
  Gmail, no API, and no model download. Inside Claude Code, `/draft-outreach
  --demo` generates one live. Sample assets live under `examples/demo/`.
- Encrypted-at-rest credentials and GDPR right-to-erasure via crypto-shred (the
  J5/J6 features, [ADR-0080](docs/adr/0080-pillar-j-week-5-6-encrypted-credentials-and-gdpr-forget.md)):
  a passphrase-derived keystore, AES-GCM credential encryption, and a
  `forget_person` erasure that destroys the key instead of rewriting the
  append-only ledger.
- Adopter-focused README: CI badge, a before/after voice comparison, an explicit
  "what works today vs roadmap" split, and a documentation router.

### Changed
- osv-scanner runs report-only (ADR-0078 D390): it surfaces advisories without
  failing the build. Dependency floors bumped to patched versions.

### Fixed
- The CI gate job now installs the test and send-skill dependencies, so the full
  suite actually runs on GitHub. It previously exited early on a missing pytest.

## 2026-06-01

### Added
- Initial public release. The full discover, research, draft, humanize, and send
  pipeline; the orchestrator (state machine, append-only ledger, cross-process
  locks, auto-enrollment); CPU-only voice retrieval; email verification;
  multi-tenant support; OpenTelemetry observability; and the onboarding CLI
  (`bin/outreach-factory init` / `config` / `doctor`).
