# Examples: worked tenants

The framework core (`orchestrator/`, the generic `skills/`, `config-template/`)
is use-case agnostic. This directory holds **complete worked tenants**: real,
end-to-end outreach setups built on the core, kept here as reference
implementations you can read, copy, and adapt.

They are intentionally NOT installed by `install.sh` (which only symlinks the
generic `skills/*/`). You opt into an example explicitly, per its README.

## Available examples

| Example | What it does | Notable |
|---|---|---|
| [`scholarfeed/`](scholarfeed/) | Cold outreach to recently-published CS/AI researchers, offering a free trial API key as the CTA | A second tenant with a DIFFERENT pipeline topology (adds an API-key provisioning stage) and a usage-based outcome signal. The held-out tenant the golden-path harness uses to guard against single-tenant overfit. |

## Using an example as a starting point

The cleanest path for your own outreach is the core onboarding flow
(`./bin/outreach-factory init`, see the top-level [INSTALL.md](../INSTALL.md)).
Reach for an example when you want a concrete, working reference for a piece the
blank template only sketches: a custom discovery skill, a verbatim-template
assembler, a per-tenant config, or a non-standard pipeline stage.
