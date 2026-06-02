"""Regression barrier for the zero-setup `outreach-factory demo` walkthrough.

The demo is the storefront's "wow" surface (P1-2). These tests pin three
properties that, if they regress, silently break the first impression:

  1. `main(["demo"])` exits 0 and prints all four pipeline stages for the
     bundled fake prospect.
  2. The demo runs on the standard library alone (no third-party import in the
     `demo` code path), so a bare clone can run it without `pip install`.
  3. Every byte the demo prints, and every committed demo file, is free of em
     and en dashes (the project's absolute no-dash rule, and the dashes are the
     #1 AI tell the whole product exists to avoid).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator import cli

EM_DASH = "—"
EN_DASH = "–"
DEMO_DIR = Path(__file__).resolve().parent.parent / "examples" / "demo"


def _run_demo(capsys) -> tuple[int, str]:
    rc = cli.main(["demo"])
    return rc, capsys.readouterr().out


def test_demo_exits_zero_and_prints_four_stages(capsys):
    rc, out = _run_demo(capsys)
    assert rc == 0
    for marker in (
        "THE OUTREACH FACTORY DEMO",
        "[1 of 4]",
        "[2 of 4]",
        "[3 of 4]",
        "[4 of 4]",
    ):
        assert marker in out, f"missing stage marker: {marker!r}"


def test_demo_shows_prospect_voice_and_live_pointer(capsys):
    _, out = _run_demo(capsys)
    # The fake prospect and the demo sender's wedge both surface.
    assert "Riley Okafor" in out
    assert "riley@okafor.example" in out
    assert "Carillon" in out
    # The CLI honestly points at the live, agent-generated path.
    assert "/draft-outreach --demo" in out
    # And it does not pretend to send.
    assert "nothing is sent" in out.lower()


def test_demo_output_is_dash_free(capsys):
    _, out = _run_demo(capsys)
    assert EM_DASH not in out, "demo output contains an em dash"
    assert EN_DASH not in out, "demo output contains an en dash"


def test_demo_path_imports_no_third_party(monkeypatch, capsys):
    """The demo must run on a bare clone. Simulate the absence of the repo's
    third-party deps by making any of them raise on import; the demo path must
    still succeed because it uses only the standard library."""
    import builtins

    real_import = builtins.__import__
    banned = {"yaml", "numpy", "sentence_transformers", "torch"}

    def _guarded_import(name, *args, **kwargs):
        root = name.split(".")[0]
        if root in banned:
            raise ImportError(f"{root} blocked for the bare-clone demo test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    rc, out = _run_demo(capsys)
    assert rc == 0
    assert "FINAL DRAFT" in out


def test_demo_corpus_parses_to_six_exemplars():
    corpus = cli._parse_demo_corpus((DEMO_DIR / "voice-corpus.md").read_text(encoding="utf-8"))
    assert len(corpus) == 6
    cold = [e for e in corpus if e["register"] == "cold-pitch"]
    assert len(cold) == 3
    # Every exemplar parsed an id, a register, and a non-empty body.
    for ex in corpus:
        assert ex["id"]
        assert ex["register"]
        assert ex["body"].strip()


def test_demo_prospect_frontmatter_parses():
    fm, body = cli._split_frontmatter(
        (DEMO_DIR / "vault" / "Riley Okafor.md").read_text(encoding="utf-8")
    )
    assert fm["name"] == "Riley Okafor"
    assert fm["register"] == "cold-pitch"
    assert fm["email"] == "riley@okafor.example"
    assert body.strip(), "prospect note body should not be empty"


@pytest.mark.parametrize(
    "rel",
    [
        "README.md",
        "voice-corpus.md",
        "scaffold.md",
        "sample-draft.md",
        "vault/Riley Okafor.md",
    ],
)
def test_demo_files_are_dash_free(rel):
    text = (DEMO_DIR / rel).read_text(encoding="utf-8")
    assert EM_DASH not in text, f"{rel} contains an em dash"
    assert EN_DASH not in text, f"{rel} contains an en dash"
