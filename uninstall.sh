#!/usr/bin/env bash
# uninstall.sh — remove outreach-factory skill symlinks from ~/.claude/skills/
#
# Does NOT touch ~/.outreach-factory/config.yml or any backups created by install.sh.

set -euo pipefail

REPO_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_SKILLS="$HOME/.claude/skills"

echo "outreach-factory uninstall"
echo "  removing symlinks from $CLAUDE_SKILLS"
echo ""

for skill_dir in "$REPO_HOME"/skills/*/; do
    skill_name=$(basename "$skill_dir")
    target="$CLAUDE_SKILLS/$skill_name"

    if [[ -L "$target" ]]; then
        link_target="$(readlink "$target")"
        if [[ "$link_target" == "$skill_dir"* ]]; then
            rm "$target"
            echo "  ✓  removed symlink $target"
        else
            echo "  -  $target is a symlink to $link_target (not us), leaving alone"
        fi
    else
        echo "  -  $target is not a symlink, leaving alone"
    fi
done

echo ""
echo "Uninstall complete."
echo ""
echo "Backups created by install.sh (named *.backup-*) are still in $CLAUDE_SKILLS."
echo "Move them back manually if you want to restore a previous skill version."
echo "Your config at ~/.outreach-factory/config.yml is untouched."
