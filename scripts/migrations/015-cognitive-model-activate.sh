#!/usr/bin/env bash
# 015-cognitive-model-activate — Announce that the `cognitive-model` lens now
# ships `status: active` platform-wide, and offer to seed the cognitive hub now.
#
# The status flip itself is delivered by the engine sync: AGENT_LENSES.md and
# lenses/cognitive-model/prompt.md are engine paths that sync_engine.sh
# overwrites from upstream BEFORE migrations run, so by the time this migration
# executes the lens is already `active` on the friend's clone. This migration
# therefore does NOT mutate the registry (migrations must never touch owner-data
# / registries) — it only DETECTS the new state and nudges, soft-nag style
# (exits 0 in every case; a non-zero exit would abort sync_engine.sh under
# `set -e` — see 011 / 014).
#
# Why a nudge and not silence: cognitive-model is an autonomous lens that reads
# the owner's private reflections. Enabling it by default is a deliberate
# platform decision, but the owner deserves to be TOLD — and to be able to seed
# the hub immediately instead of waiting for the next biweekly Monday.
# Idempotent: re-running just re-prints the notice; changes nothing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZK="$REPO_ROOT/zettelkasten"
REGISTRY="$ZK/_system/registries/AGENT_LENSES.md"

if [[ ! -f "$REGISTRY" ]]; then
    echo "info: AGENT_LENSES.md not found — skipping (fresh clone or non-ZTN base)"
    exit 0
fi

# Detect the post-sync state. The active row is `| cognitive-model | ... | active |`.
if ! grep -Eq '^\| cognitive-model \|.*\| active \|' "$REGISTRY"; then
    echo "[migration 015] cognitive-model is not active in AGENT_LENSES.md — skipping notice."
    echo "  (expected active after engine sync; if you deliberately set it to draft, this is respected"
    echo "   but note the next /ztn:update re-applies the platform default of active.)"
    exit 0
fi

cat >&2 <<EOF

[migration 015] The 'cognitive-model' lens is now ACTIVE by default.

  What it does: every other Monday it reads your own reflections
  (_records/observations) and proposes patterns of how you think and want to be
  communicated with as principle candidates. It only APPENDS to your review
  buffer (_system/state/principle-candidates.jsonl) — nothing reaches your
  constitution until YOU promote it via /ztn:lint. This is what fills the
  cognitive-model hub (5_meta/mocs/hub-cognitive-model.md).

  To populate the hub NOW instead of waiting for the next biweekly Monday, run:

      /ztn:agent-lens --lens cognitive-model

  (Needs some observation records to mine — a fresh base with no reflections
  yet will produce nothing until you have journal / voice-note material.)

  To opt out: set its status to draft in _system/registries/AGENT_LENSES.md —
  but note the platform default of active is re-applied on the next /ztn:update.
EOF
exit 0
