#!/usr/bin/env bash
# migration-kind: heal
# 027-starter-axiom-hot-audit — tell the owner if a starter axiom has been
# acting as one of their standing principles without being adopted.
#
# 0.64.1 fixed the shipped starter pack: one of the six carried `claude-code`
# in `applies_to` alongside `core: true`, so adopting the pack put an unedited
# `status: draft` axiom into `constitution-core.md` — the view loaded in every
# session — which the pack's own README says must never happen.
#
# The engine fix reaches new adoptions only. A copy already sitting in
# `0_constitution/axiom/` stopped being engine surface the moment it was
# copied, and migrations MUST NOT touch the owner's constitution. So this one
# detects and reports: one CLARIFICATION per affected axiom, stating the two
# ways out, leaving the decision where it belongs. Same posture as 025, which
# routes its findings to the same queue.
#
# `heal`: nothing here reads a wrong place — un-run means the owner is not yet
# told, which is incomplete, not incorrect. A notice must never be able to
# block a future engine update.
#
# Idempotent: `append_clarifications` skips an anchor already present in the
# open queue or the resolved archive, so re-running never re-asks a question
# the owner has answered.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "warning: python3 not found — skipping starter-axiom audit" >&2
    exit 0
fi

# Never let a reporting migration take the update down with it.
if ! python3 "$SCRIPT_DIR/_027_starter_axiom_audit.py"; then
    echo "warning: 027 starter-axiom audit did not complete" >&2
    echo "  Check by hand: any file under 0_constitution/axiom/ with" >&2
    echo "  confidence: starter, status: draft, and claude-code in applies_to" >&2
    echo "  is loading into every session unedited." >&2
fi

exit 0
