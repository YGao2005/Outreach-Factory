"""RAG voice translator — retrieval only (subscription-friendly).

Loads embeddings of the user's curated email corpus and retrieves top-K
most-similar exemplars for a given draft. Outputs JSON for a Claude Code agent
to consume and do the rewrite using its OWN subscription-billed LLM call.

Config-driven: reads `~/.outreach-factory/config.yml` (override with
$OUTREACH_FACTORY_CONFIG env var) to locate the corpus directory and embedding
files. The corpus directory must contain:
  - embeddings.npy   (numpy array of corpus embeddings)
  - index.json       (list of dicts with date, subject, to, body, year)

Why this exists separately from voice_translate.py:
  - voice_translate.py (deprecated 2026-05-14) called the Anthropic API
    directly via ANTHROPIC_API_KEY = per-token billing outside the subscription.
  - voice_retrieve.py is local-only, $0, no API. The rewrite happens INSIDE the
    Claude Code agent that calls this script, billed against the subscription.

Usage:
    python3 voice_retrieve.py --file draft.txt          # output JSON to stdout
    python3 voice_retrieve.py --file draft.txt --k 7    # adjust top-K
    python3 voice_retrieve.py "draft text"              # direct arg
    cat draft.txt | python3 voice_retrieve.py           # stdin

Output schema (JSON to stdout):
    {
      "draft": "the input draft",
      "exemplars": [
        {"date": "...", "subject": "...", "to": [...], "body": "...", "score": 0.79, ...},
        ...
      ],
      "hard_rules": ["NO em-dashes...", ...],
      "embed_model": "BAAI/bge-small-en-v1.5",
      "recent_bias": true,
      "corpus_size": int
    }
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import yaml
from sentence_transformers import SentenceTransformer

# ============================================================
# Constants — universal, do NOT parameterize
# ============================================================
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
TOP_K = 5
RECENT_BIAS = True

HARD_RULES = [
    "NO em-dashes (—) inside sentences. Replace with commas, periods, or parentheses.",
    "Preserve the draft's greeting AND signoff EXACTLY. 'Hi Sarah,' stays (or relax to 'Hey Sarah,' if the most recent exemplar uses 'Hey'). 'Cheers,\\nName' must include 'Cheers,\\nName' — do NOT drop the closing word.",
    "Ban these AI-tell phrases entirely: 'hope this email finds you well', 'circle back', 'touch base', 'resonates with me', 'particularly impressed', 'genuinely impressed', 'truly inspiring', \"I'd love to learn from your perspective\", 'thoughtful framework', 'really resonated', 'I came across', 'I admire your', 'Would love to share a quick update'.",
    "Ban these lexical AI-tells (intensifiers and hedges) when used as filler: 'basically', 'literally', 'actually' (as filler not contrast), 'approximately', 'pretty' (as hedge), 'kind of', 'sort of', 'honestly', 'essentially', 'fundamentally', 'really' (as intensifier), 'just' (as softener), 'directly adjacent', 'notoriously'.",
    "NO superlatives without specifics ('incredible', 'amazing', 'truly', 'really exciting' unless backed by something concrete).",
    "NO 'I'd love to learn more from people closer to the problem' — overused.",
    "Keep sentences short and direct. Mix short (under 10 words) with medium (15-25). No sentence over 30 words unless it's a list or specific question.",
    "State, don't perform. 'I appreciated the call' beats 'I really appreciated the wonderful insights from our call.'",
    "For cold-pitch register: include a vulnerability signal ('I don't know yet whether the angle survives', 'still figuring out', 'early on this', 'honestly been a challenge'). LLMs do not volunteer these — they are load-bearing for cold-pitch readability.",
    "For cold-pitch register: closing should be conversational, not formal. 'If you've got the time, would help a lot. If not, no stress.' style, not 'Looking forward to hearing your thoughts.'",
]


# ============================================================
# Config loading
# ============================================================
def _config_path() -> Path:
    return Path(os.environ.get("OUTREACH_FACTORY_CONFIG", "~/.outreach-factory/config.yml")).expanduser()


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        sys.stderr.write(
            f"ERROR: config not found at {path}\n"
            f"Copy config-template/config.example.yml to ~/.outreach-factory/config.yml and fill in your values.\n"
        )
        sys.exit(1)
    return yaml.safe_load(path.read_text())


def corpus_paths(config: dict) -> tuple[Path, Path]:
    corpus_dir = Path(config["voice"]["corpus_dir"]).expanduser()
    emb_path = corpus_dir / "embeddings.npy"
    idx_path = corpus_dir / "index.json"
    if not emb_path.exists():
        sys.stderr.write(f"ERROR: embeddings not found at {emb_path}\n")
        sys.exit(1)
    if not idx_path.exists():
        sys.stderr.write(f"ERROR: index not found at {idx_path}\n")
        sys.exit(1)
    return emb_path, idx_path


# ============================================================
# Retrieval
# ============================================================
def retrieve(query: str, emb_path: Path, idx_path: Path, k: int = TOP_K) -> list[dict]:
    emb = np.load(emb_path)
    index = json.loads(idx_path.read_text())

    model = SentenceTransformer(EMBED_MODEL)
    q_emb = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0].astype(np.float32)
    sims = emb @ q_emb

    if RECENT_BIAS:
        years = np.array([e["year"] for e in index], dtype=np.float32)
        max_year = years.max()
        recency = 1.0 - (max_year - years) * 0.03
        sims = sims * recency

    top_idx = np.argsort(-sims)[:k]
    return [{**index[i], "score": float(sims[i])} for i in top_idx]


def main() -> int:
    ap = argparse.ArgumentParser(description="Retrieve voice exemplars for a draft (local, no API).")
    ap.add_argument("draft", nargs="?", help="draft text")
    ap.add_argument("--file", help="read draft from file")
    ap.add_argument("--k", type=int, default=TOP_K, help="number of exemplars to retrieve")
    args = ap.parse_args()

    if args.file:
        draft = Path(args.file).read_text()
    elif args.draft:
        draft = args.draft
    else:
        draft = sys.stdin.read()

    config = load_config()
    emb_path, idx_path = corpus_paths(config)
    exemplars = retrieve(draft, emb_path, idx_path, k=args.k)

    output = {
        "draft": draft,
        "exemplars": exemplars,
        "hard_rules": HARD_RULES,
        "embed_model": EMBED_MODEL,
        "recent_bias": RECENT_BIAS,
        "corpus_size": len(json.loads(idx_path.read_text())),
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
