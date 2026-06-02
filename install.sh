#!/usr/bin/env bash
# install.sh — symlink outreach-factory skills into ~/.claude/skills/
#
# Safe to re-run. Backs up any pre-existing skill directories before symlinking.

set -euo pipefail

REPO_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.outreach-factory"
CONFIG_FILE="$CONFIG_DIR/config.yml"
CLAUDE_SKILLS="$HOME/.claude/skills"
SKILL_BACKUPS="$HOME/.claude/skills_backups"
TIMESTAMP="$(date +%Y-%m-%d-%H%M%S)"

echo "outreach-factory install"
echo "  repo: $REPO_HOME"
echo "  config: $CONFIG_FILE"
echo "  skills target: $CLAUDE_SKILLS"
echo ""

# --- Verify config exists ---
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: config not found at $CONFIG_FILE"
    echo ""
    echo "Run:"
    echo "  ./bin/outreach-factory config      # copies the config + .env templates"
    echo "  # Then edit $CONFIG_FILE with your values"
    echo ""
    echo "Aborting."
    exit 1
fi
echo "✓ Config found"

# Detailed validation runs at the end via scripts/doctor.py.

# --- Install skills (symlink) ---
echo ""
echo "Installing skills..."
mkdir -p "$CLAUDE_SKILLS" "$SKILL_BACKUPS"

for skill_dir in "$REPO_HOME"/skills/*/; do
    skill_name=$(basename "$skill_dir")
    target="$CLAUDE_SKILLS/$skill_name"
    backup="$SKILL_BACKUPS/$skill_name.backup-$TIMESTAMP"

    if [[ -L "$target" ]]; then
        echo "  ↻  $skill_name (already symlinked, replacing)"
        rm "$target"
    elif [[ -d "$target" || -f "$target" ]]; then
        echo "  ⚠  $skill_name exists — backing up to $backup"
        mv "$target" "$backup"
    fi

    ln -s "$skill_dir" "$target"
    echo "  ✓  symlinked $target → ${skill_dir%/}"
done

echo ""
echo "Install complete."

# --- Run preflight ---
# Use system python3, NOT voice.python_bin from config (that venv is voice-only;
# doctor needs the python that the email/orchestrator scripts will actually run under).
echo ""
echo "Running preflight (scripts/doctor.py)..."
echo ""
if command -v python3 >/dev/null; then
    python3 "$REPO_HOME/scripts/doctor.py" || true
else
    echo "⚠  python3 not found — skipping doctor.py. Run it manually after installing Python 3.11+:"
    echo "    python3 scripts/doctor.py"
fi

echo ""
echo "Next steps:"
echo "  1. Run onboarding (Gmail OAuth -> vault -> first prospect -> test send):"
echo "       ./bin/outreach-factory init"
echo "     (preview the wiring first with: ./bin/outreach-factory init --dry-run)"
echo "  2. Restart Claude Code (or open a fresh session) to pick up the new skills"
echo "  3. Set up any missing optional features above (see docs/OPTIONAL-FEATURES.md)"
echo "  4. Test: /draft-outreach <prospect> --register cold-pitch"
echo "  5. To uninstall, run: ./uninstall.sh"
