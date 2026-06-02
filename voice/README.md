# Voice corpus — build path

The voice translator (`orchestrator/voice_retrieve.py`) needs two files in your
configured `voice.corpus_dir`:

```
embeddings.npy   numpy array, one row per corpus email
index.json       list of dicts: { date, subject, to, body, year, ... }
```

These scripts build that pair from a Gmail Takeout `.mbox` export. They are
flag-driven and write to the canonical corpus location
(`~/.outreach-factory/voice-corpus/`) by default, so the typical run needs no
editing. Point `voice.corpus_dir` in `~/.outreach-factory/config.yml` at that
directory (or pass `--out-dir` / `--emb` / `--index` to write elsewhere).

## Pipeline

```
mbox export  →  parse_mbox.py    →  filtered.jsonl     (extract YOUR sent mail)
             →  refine.py        →  cleaned.jsonl      (drop short / quote-only)
             →  curate.py        →  curated.jsonl      (drop AI-flavored)
             →  build_index.py   →  embeddings.npy + index.json
```

Optional fifth step (inject cold-pitch register from your CRM):

```
             →  augment_corpus_from_vault.py  →  curated_v2.jsonl
```

## Setup

1. **Export Gmail Takeout** for `Sent Mail` (or a label that captures your
   outgoing register) and download the `.mbox` file.
2. **Install deps**: `pip install -r ../orchestrator/requirements.txt`
   (`build_index.py` uses `sentence-transformers`).

## Run order

Every script defaults its inputs/outputs to `~/.outreach-factory/voice-corpus/`,
so you only have to supply what is unique to you: the `.mbox` path and your own
sender address(es).

```bash
cd ~/code/outreach-factory/voice

# 1. Keep only mail YOU sent (pass each of your addresses with --sender).
python parse_mbox.py --mbox "/path/to/your/takeout.mbox" --sender you@example.com

# 2-4. Refine -> curate -> embed (defaults read/write the canonical corpus dir).
python refine.py
python curate.py
python build_index.py

# Optional — only if you have a markdown CRM with sent cold-pitch notes:
python augment_corpus_from_vault.py --vault-convos "/path/to/vault/40 Conversations"
python build_index.py --in ~/.outreach-factory/voice-corpus/curated_v2.jsonl
```

Run any script with `--help` to see all flags (alternate paths, model, min-year,
drop threshold). Each prints a summary of counts dropped per filter reason. If
you lose >50% of messages at any one step, tune that step's thresholds for your
inbox shape.

## Why corpus quality matters

The retriever finds the top-5 most-similar emails to the draft and instructs the
agent to mirror their tone. If your corpus skews to one register (e.g. all warm
replies, no cold pitches), the agent drifts to that register regardless of the
draft's intent. Rule of thumb:

| Corpus size | Quality |
|-------------|---------|
| <50 emails  | Too small — fall back to manual editing |
| 50-200      | Workable for one register; uneven across registers |
| 200-500     | Good for 2-3 registers if balanced |
| >500        | Comfortable across all 5 registers |

The `augment_corpus_from_vault.py` step exists to inject cold-pitch examples when
your inbox export is reply-heavy.

## Notes

- **No incremental rebuild.** Each script reads its full input and rewrites the
  full output. Fine for n<10k corpora; rebuild from scratch on each new export.
- **Local, zero-cost embeddings.** `build_index.py` defaults to a CPU-only
  sentence-transformers model. Override with `--model` if you prefer another.
