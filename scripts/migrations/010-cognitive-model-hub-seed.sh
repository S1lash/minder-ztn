#!/usr/bin/env bash
# 010-cognitive-model-hub-seed — seed the cognitive-model hub for existing installs.
#
# `5_meta/mocs/hub-cognitive-model.md` is the visible projection of «how you
# think», maintained by render_cognitive_model_hub.py at /ztn:maintain Step 7.9.
# It ships as a TEMPLATE (`hub-cognitive-model.template.md`), so a FRESH clone of
# the skeleton already has the file — but `sync_engine.sh` skips template paths,
# so a friend who installed BEFORE this feature never receives it on /ztn:update.
# Without the file, Step 7.9 skips silently forever and the friend never gets the
# hub. This migration writes a minimal valid hub (frontmatter + owner «portrait»
# zone + EMPTY managed-zone markers) when absent; the friend's next /ztn:maintain
# fills the ten-axis table from THEIR own `cognitive_axes`-tagged principles.
#
# It writes only the empty marker skeleton — the renderer owns the table content,
# so there is nothing here to drift from the axis SoT.
#
# Scope: creates ONE owner-data file only when missing. It never overwrites an
# existing hub (idempotent) and touches no other user-data path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HUB="$REPO_ROOT/zettelkasten/5_meta/mocs/hub-cognitive-model.md"

if [[ -f "$HUB" ]]; then
    echo "info: hub-cognitive-model.md already present — no-op"
    echo "010-cognitive-model-hub-seed: done"
    exit 0
fi

mkdir -p "$(dirname "$HUB")"
cat > "$HUB" <<'EOF'
---
id: hub-cognitive-model
title: 'Hub: Cognitive Model — how you think, as Minder models it'
aliases:
- Cognitive Model
- Your Mind as Minder sees it
created: 2026-01-01
modified: '2026-01-01'
hub_created: 2026-01-01
layer: hub
hub_kind: domain
chronological_map_mode: curated
domains:
- ai-interaction
- learning
- meta
- identity
status: active
priority: normal
tags:
- hub
- domain/ai-interaction
- topic/cognitive-model
concepts: []
origin: personal
audience_tags: []
is_sensitive: false
---

# Hub: Cognitive Model — how you think, as Minder models it

> An accumulating showcase of how the system models the way you think and want
> to be communicated with — one row per axis, each with a status and the principle that
> evidences it. Not a source of truth: each pattern's truth lives in its
> principle (`0_constitution/`); this hub only links it. It updates on
> `/ztn:maintain`; do not hand-edit the table between the markers. The portrait
> below is yours.

## Your portrait

<!-- owner-editable: 2-3 sentences in your own words on how you think. The engine never touches this section. -->
_(Fill in 2-3 sentences whenever you like. The engine never writes here — this is your text.)_

<!-- AUTO-GENERATED: cognitive-model-hub — DO NOT EDIT BETWEEN MARKERS (maintained by render_cognitive_model_hub.py) -->
<!-- END AUTO-GENERATED: cognitive-model-hub -->
EOF

echo "seeded $HUB (run /ztn:maintain to fill the ten-axis table)"
echo "010-cognitive-model-hub-seed: done"
