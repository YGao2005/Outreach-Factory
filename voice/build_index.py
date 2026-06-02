"""Embed cleaned.jsonl with sentence-transformers → embeddings.npy + index.json.

One-time build. Re-run when corpus changes.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

# Canonical corpus location (override the input + outputs via flags).
DEFAULT_CORPUS_DIR = Path("~/.outreach-factory/voice-corpus").expanduser()
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Embed the curated corpus into embeddings.npy + index.json.")
    ap.add_argument("--in", dest="in_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "curated.jsonl",
                    help="Input curated jsonl (curated.jsonl, or curated_v2.jsonl after augment).")
    ap.add_argument("--emb", dest="emb_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "embeddings.npy", help="Output embeddings.npy.")
    ap.add_argument("--index", dest="index_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "index.json", help="Output index.json.")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"sentence-transformers model (default: {DEFAULT_MODEL}).")
    args = ap.parse_args()
    in_path = args.in_path.expanduser()
    emb_path = args.emb_path.expanduser()
    index_path = args.index_path.expanduser()
    model_name = args.model

    records = [json.loads(l) for l in in_path.open()]
    print(f"loaded {len(records)} cleaned emails")

    model = SentenceTransformer(model_name)
    texts = [r["body_no_urls"] for r in records]

    print(f"embedding {len(texts)} texts with {model_name}")
    emb = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)

    np.save(emb_path, emb)
    print(f"wrote {emb_path} shape={emb.shape}")

    index = [
        {
            "i": i,
            "message_id": r.get("message_id", ""),
            "date": r["date"],
            "year": r["year"],
            "subject": r["subject"],
            "to": r["to"],
            "clean_word_count": r["clean_word_count"],
            "body": r["body_no_urls"],
        }
        for i, r in enumerate(records)
    ]
    index_path.write_text(json.dumps(index, ensure_ascii=False))
    print(f"wrote {index_path} ({len(index)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
