# Example tenant: ScholarFeed

A complete worked second-tenant built on the outreach-factory core. ScholarFeed
does cold outreach to recently-published CS/AI/ML researchers, offering a free
2-week Pro API key as the call-to-action, and tracks key activation (not just
replies) as the outcome signal.

It exists in `examples/` for two reasons:

1. A reference implementation of a tenant whose pipeline differs from the
   default (it adds an API-key provisioning stage before drafting).
2. The held-out tenant the golden-path harness runs alongside the training
   tenant, so the gates are not overfit to a single use case.

## What's here

| File | Role |
|---|---|
| `skills/find-researchers/SKILL.md` | Discovery skill: finds recently-published researchers via arXiv, filters by ICP, and writes Person notes into the ScholarFeed vault. |
| `assemble_scholarfeed_touch.py` | Verbatim cold-touch assembler. The body is byte-for-byte fixed; only the first sentence and the trial key vary per recipient (an LLM would paraphrase the body, so this does a literal substitution instead). |
| `provision_trial_key.py` | Mints a free Pro trial key via the ScholarFeed admin API, to embed as the CTA. |
| `config.scholarfeed.example.yml` | The per-tenant config. Copy, edit, and select it with `OUTREACH_FACTORY_CONFIG`. |

## How to use it

```bash
# 1. Copy the tenant config and fill in your values.
cp examples/scholarfeed/config.scholarfeed.example.yml \
   ~/.outreach-factory/config.scholarfeed.yml
# edit ~/.outreach-factory/config.scholarfeed.yml

# 2. Make the discovery skill available to Claude Code.
ln -s "$PWD/examples/scholarfeed/skills/find-researchers" \
   ~/.claude/skills/find-researchers

# 3. Select this tenant for any factory invocation via the env override.
export OUTREACH_FACTORY_CONFIG=~/.outreach-factory/config.scholarfeed.yml

# 4. Mint a trial key, then assemble + send a touch (dry-run shown).
python examples/scholarfeed/provision_trial_key.py --email jane@university.example
python examples/scholarfeed/assemble_scholarfeed_touch.py \
    --name "Dr. Jane Researcher" \
    --first-sentence "saw your recent paper on self-evaluating agents, nice work." \
    --key sf_xxxxxxxx --email jane@university.example --dry-run
```

The assembler and the generic `send_queued.py` share the same config loader, so
the touch note it writes flows through the normal gated send path.

## Secrets (.env)

ScholarFeed's scripts read one secret, from the environment first, then a
chmod-600 file. Put it in your `~/.outreach-factory/.env`:

```
# ScholarFeed admin API secret (trial-key minting + pre-send suppression check)
SCHOLARFEED_ADMIN_SECRET=your-admin-secret-here
```

`config.scholarfeed.example.yml` points the generic pre-send suppression check
at this secret via `security.suppression_check_secret_env: SCHOLARFEED_ADMIN_SECRET`.
