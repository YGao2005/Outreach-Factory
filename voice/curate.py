"""Score each cleaned email for AI-tells, drop high-scorers → curated.jsonl.

Heuristic scorer based on the /humanizer skill's 29 pattern categories.
Goal: remove emails like the 2025-04-27 "Coffee Chat Request" that read as
AI-flavored even though the operator wrote them (e.g., from a phase when they
leaned on LLM drafts).

Scoring: each pattern hit adds points. Email score = total / 10 (capped at 10).
Drop threshold tuned to retain ~60-70% of corpus.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

# Canonical corpus location (override in/out/summary via flags).
DEFAULT_CORPUS_DIR = Path("~/.outreach-factory/voice-corpus").expanduser()

DROP_THRESHOLD = 4.0

AI_VOCAB = {
    "actually", "additionally", "align", "crucial", "delve", "delving",
    "emphasizing", "enduring", "enhance", "enhanced", "fostering", "garner",
    "highlight", "highlighting", "interplay", "intricate", "intricacies",
    "pivotal", "showcase", "showcases", "tapestry", "testament", "underscore",
    "underscores", "underscoring", "vibrant", "robust", "leverage", "leveraging",
    "navigate", "navigating", "embark", "ensure", "ensuring", "elevate",
    "elevating", "unlock", "unlocking", "transformative", "groundbreaking",
    "seamless", "seamlessly", "myriad", "plethora", "endeavor", "endeavors",
}

SYCOPHANTIC = [
    r"\bhope this (email |message )?(finds you well|reaches you well)\b",
    r"\bgreat question\b",
    r"\bexcellent (point|question)\b",
    r"\byou(?:'re| are)? absolutely (right|correct)\b",
    r"\bi'?d love to (learn|hear|understand)\b",
    r"\bi was particularly impressed\b",
    r"\bgenuinely impressed\b",
    r"\btruly inspiring\b",
    r"\bresonates with me\b",
    r"\breally resonated\b",
    r"\byour philosophy\b",
    r"\bi admire your\b",
    r"\bi hope this helps\b",
    r"\bplease let me know if you\b",
    r"\bi (came|stumbled) across\b",
]

CIRCLE_BACK = [
    r"\bcircle back\b",
    r"\btouch base\b",
    r"\bcircling back\b",
    r"\bjust wanted to check in\b",
    r"\bhope you('?ve)? been well\b",
    r"\bwanted to reach out\b",
]

NEG_PARALLEL = [
    r"\bit'?s not (just|merely) about .{1,50}(it'?s|but)\b",
    r"\bnot (just|only) X.{0,80}(but|it'?s) Y\b",  # generic shape
    r"\bnot only .{1,40} but also\b",
]

PERSUASIVE_AUTHORITY = [
    r"\bthe real question is\b",
    r"\bat its core\b",
    r"\bin reality\b",
    r"\bwhat really matters\b",
    r"\bfundamentally\b",
    r"\bthe deeper issue\b",
    r"\bthe heart of the matter\b",
]

FILLER = [
    r"\bin order to\b",
    r"\bdue to the fact\b",
    r"\bat this point in time\b",
    r"\bit is (important|worth) (to note|noting) that\b",
    r"\bit could potentially possibly\b",
]

GENERIC_CONCLUSIONS = [
    r"\bthe future looks bright\b",
    r"\bexciting times (lie ahead|ahead)\b",
    r"\bstep in the right direction\b",
]

SIGNPOSTING = [
    r"\blet'?s (dive|explore|break this down)\b",
    r"\bhere'?s what you need to know\b",
    r"\bwithout further ado\b",
]


def count_pattern_hits(text: str, patterns: list[str]) -> int:
    n = 0
    for p in patterns:
        n += len(re.findall(p, text, re.IGNORECASE))
    return n


def count_ai_vocab(text: str) -> int:
    words = re.findall(r"\b[A-Za-z]+\b", text.lower())
    return sum(1 for w in words if w in AI_VOCAB)


def em_dash_density(text: str) -> float:
    # Count both unicode em-dash and " — " ASCII approximation
    dashes = text.count("—") + len(re.findall(r" -- ", text))
    words = max(1, len(text.split()))
    return dashes / words


def rule_of_three_hits(text: str) -> int:
    # Crude heuristic: "X, Y, and Z" with three things → potential rule-of-three
    return len(re.findall(r"\b\w+, \w+,? and \w+\b", text))


def score_email(body: str) -> tuple[float, dict]:
    breakdown = {
        "ai_vocab": count_ai_vocab(body),
        "sycophantic": count_pattern_hits(body, SYCOPHANTIC),
        "circle_back": count_pattern_hits(body, CIRCLE_BACK),
        "neg_parallel": count_pattern_hits(body, NEG_PARALLEL),
        "persuasive_authority": count_pattern_hits(body, PERSUASIVE_AUTHORITY),
        "filler": count_pattern_hits(body, FILLER),
        "generic_conclusions": count_pattern_hits(body, GENERIC_CONCLUSIONS),
        "signposting": count_pattern_hits(body, SIGNPOSTING),
        "em_dash_density": em_dash_density(body),
        "rule_of_three": rule_of_three_hits(body),
    }
    # Weighted score
    score = (
        0.6 * breakdown["ai_vocab"]
        + 1.5 * breakdown["sycophantic"]
        + 1.0 * breakdown["circle_back"]
        + 1.5 * breakdown["neg_parallel"]
        + 1.0 * breakdown["persuasive_authority"]
        + 0.5 * breakdown["filler"]
        + 1.5 * breakdown["generic_conclusions"]
        + 1.0 * breakdown["signposting"]
        + 30.0 * breakdown["em_dash_density"]
        + 0.3 * breakdown["rule_of_three"]
    )
    return min(score, 10.0), breakdown


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Score each cleaned email for AI-tells; drop high-scorers into curated.jsonl.")
    ap.add_argument("--in", dest="in_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "cleaned.jsonl", help="Input cleaned.jsonl.")
    ap.add_argument("--out", dest="out_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "curated.jsonl", help="Output curated.jsonl.")
    ap.add_argument("--summary", dest="summary_path", type=Path,
                    default=DEFAULT_CORPUS_DIR / "curated_summary.json", help="Output summary json.")
    args = ap.parse_args()
    in_path = args.in_path.expanduser()
    out_path = args.out_path.expanduser()
    summary_path = args.summary_path.expanduser()

    records = [json.loads(l) for l in in_path.open()]

    scored = []
    for r in records:
        score, breakdown = score_email(r["body_no_urls"])
        scored.append({**r, "ai_tell_score": score, "ai_tell_breakdown": breakdown})

    scored.sort(key=lambda x: x["ai_tell_score"])

    kept = [r for r in scored if r["ai_tell_score"] <= DROP_THRESHOLD]
    dropped = [r for r in scored if r["ai_tell_score"] > DROP_THRESHOLD]

    with out_path.open("w") as f:
        for r in kept:
            r_out = {k: v for k, v in r.items() if k != "ai_tell_breakdown"}
            f.write(json.dumps(r_out, ensure_ascii=False) + "\n")

    by_year = Counter(r["year"] for r in kept)
    score_buckets = Counter()
    for r in scored:
        s = r["ai_tell_score"]
        if s < 1:
            score_buckets["0-1"] += 1
        elif s < 2:
            score_buckets["1-2"] += 1
        elif s < 4:
            score_buckets["2-4"] += 1
        elif s < 6:
            score_buckets["4-6"] += 1
        else:
            score_buckets["6+"] += 1

    examples_dropped = []
    for r in dropped[:5]:
        examples_dropped.append({
            "date": r["date"][:10],
            "subject": r["subject"][:80],
            "score": round(r["ai_tell_score"], 2),
            "breakdown": r["ai_tell_breakdown"],
            "body_snippet": r["body_no_urls"][:200],
        })

    examples_kept_top = []
    for r in sorted(kept, key=lambda x: -x["ai_tell_score"])[:5]:
        examples_kept_top.append({
            "date": r["date"][:10],
            "subject": r["subject"][:80],
            "score": round(r["ai_tell_score"], 2),
            "body_snippet": r["body_no_urls"][:200],
        })

    summary = {
        "input_count": len(records),
        "kept": len(kept),
        "dropped": len(dropped),
        "drop_threshold": DROP_THRESHOLD,
        "kept_by_year": dict(sorted(by_year.items())),
        "score_distribution": dict(score_buckets),
        "examples_dropped_highest_score": examples_dropped,
        "examples_kept_near_threshold": examples_kept_top,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("examples_dropped_highest_score", "examples_kept_near_threshold")}, indent=2))
    print("\n--- 3 highest-scoring dropped (most AI-flavored) ---")
    for ex in examples_dropped[:3]:
        print(f"  {ex['date']} score={ex['score']} {ex['subject']}")
        print(f"    {ex['body_snippet'][:160]}\n")
    print("--- 3 highest-scoring KEPT (near threshold) ---")
    for ex in examples_kept_top[:3]:
        print(f"  {ex['date']} score={ex['score']} {ex['subject']}")
        print(f"    {ex['body_snippet'][:160]}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
