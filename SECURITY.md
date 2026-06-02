# Security policy

## Reporting a vulnerability

Please report security issues privately, not in a public issue or pull request.

Use GitHub's private vulnerability reporting: open the repository's **Security**
tab and click **Report a vulnerability**. That opens a private advisory visible
only to the maintainers. If the form is not available, open a regular issue that
says only "security report, please enable private reporting" with no details,
and a maintainer will follow up.

Please include:

- what the issue is and the impact you expect,
- the steps or a proof of concept to reproduce it,
- the version or commit SHA you tested.

Expect an initial acknowledgement within a few days. This is a small project
maintained in spare time, so please allow reasonable time for a fix before any
public disclosure. Coordinated disclosure is appreciated.

## Scope

This is a self-hosted framework: you run it on your own machine with your own
credentials. The most security-relevant areas are:

- credential storage (encrypted at rest; see [ADR-0080](docs/adr/0080-pillar-j-week-5-6-encrypted-credentials-and-gdpr-forget.md)),
- the append-only ledger and the data it records,
- anything that sends mail or calls an external API on your behalf.

Secrets live in `.env` and `~/.outreach-factory/`, never in the repository. If
you find a committed secret, treat it as a vulnerability and report it as above.

## Supported versions

There are no tagged releases yet. Fixes land on the `main` branch, so run the
latest `main`.
