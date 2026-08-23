#!/usr/bin/env bash
# migration-kind: heal
# 026-advisory-baseline-wiring — wire the new `advisory-baseline` hot rule into
# this clone's ~/.claude.
#
# The doc itself arrives with the engine sync: `_system/docs/` is a wholesale
# engine path, so by the time this migration runs the file is already on disk.
# What the sync CANNOT deliver is the user-level wiring — the symlink at
# ~/.claude/rules/advisory-baseline.md and the @-import inside the managed block
# of ~/.claude/CLAUDE.md. Both are owned by install.sh, which lives outside the
# repository's reach on every clone.
#
# Un-run, the result is a doc nothing loads — INCOMPLETE, not wrong: no engine
# path reads the old location, because there is no old location. Hence `heal`:
# a failure here must never block a future engine update.
#
# Rather than re-implementing install.sh's symlink logic (which carries the
# Git-Bash `MSYS=winsymlinks:nativestrict` guard, the backup pass and the awk
# splice for the managed block), this delegates to install.sh itself — it is
# idempotent by contract and re-running it after a pull is its documented use.
# It is invoked ONLY on a clone that already has the sibling presentation
# baseline wired, which proves install.sh was run here before and that
# re-running it is expected rather than a surprise write into ~/.claude.
#
# Idempotent: once the symlink exists, the migration reports and does nothing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZK="$REPO_ROOT/zettelkasten"
INSTALLER="$REPO_ROOT/integrations/claude-code/install.sh"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
RULES="$CLAUDE_HOME/rules"

DOC="$ZK/_system/docs/advisory-baseline.md"
SIBLING="$RULES/communication-baseline.md"
TARGET="$RULES/advisory-baseline.md"

if [[ ! -f "$DOC" ]]; then
    echo "info: advisory-baseline.md not found in this base — skipping (fresh clone or non-ZTN base)"
    exit 0
fi

# Already wired — nothing to do.
if [[ -L "$TARGET" || -f "$TARGET" ]]; then
    echo "026-advisory-baseline-wiring: already wired at $TARGET — no change."
    exit 0
fi

# No sibling => install.sh was never run on this machine. Writing into
# ~/.claude here would be an unannounced first install, so only announce.
if [[ ! -L "$SIBLING" && ! -f "$SIBLING" ]]; then
    cat >&2 <<EOF

[migration 026] New hot rule available: advisory-baseline.

  It is the reasoning counterpart to communication-baseline — the objective an
  assistant works toward, how it treats a third party with its own stake, where
  decision criteria come from, and how chance and irreversibility are weighed.

  This machine has no Claude Code integration installed (no
  ~/.claude/rules/communication-baseline.md), so nothing was changed. To wire
  the rules up:

      bash integrations/claude-code/install.sh

EOF
    exit 0
fi

# Sibling present => install.sh has run here; re-running it is its documented
# post-pull step and is what wires the new rule plus the @-import.
echo "[migration 026] wiring advisory-baseline into $CLAUDE_HOME (re-running install.sh)"
if bash "$INSTALLER" >/dev/null 2>&1; then
    if [[ -L "$TARGET" || -f "$TARGET" ]]; then
        echo "026-advisory-baseline-wiring: wired $TARGET"
        exit 0
    fi
    echo "warning: install.sh completed but $TARGET is still absent" >&2
else
    echo "warning: install.sh returned non-zero while wiring advisory-baseline" >&2
fi

cat >&2 <<EOF

  Could not wire the new rule automatically. Run it by hand:

      bash integrations/claude-code/install.sh

  Until then the advisory baseline is present in your base at
  zettelkasten/_system/docs/advisory-baseline.md but is not loaded into
  sessions.

EOF
# heal: never block the update over unwired user-level state.
exit 0
