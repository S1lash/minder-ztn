#!/usr/bin/env bash
# migration-kind: heal
# 024-retirement-schema — both retirement tables reach the declared schema.
#
# The identity contract says a retirement declares three things: what kind of
# change it was, which identifier survived it, and when it was decided. On a
# clone that predates the contract, neither registry has columns for them:
#
#   1_projects/PROJECTS.md   `## Consolidated / superseded`, columns
#                            `Old ID | Status | Now part of`, with the kind and
#                            the date crammed into one status string.
#   3_resources/people/PEOPLE.md
#                            `## Removed`, columns `ID | Reason`, with the
#                            kind, the successor and the date dissolved in
#                            prose.
#
# Both become `Old ID | Kind | Successor | Date | Reason`, and the project
# section is renamed `## Retired Identifiers` so the live file and the shipped
# template agree on what it is called.
#
# `heal`, on the same test: does an unapplied state make the engine read the
# WRONG thing? It does not. Both registry parsers read the declared columns
# first and fall back to the prose when they are absent, and
# `registry_section_category` answers to the old heading alongside the new. An
# unmigrated table parses to the same identifiers, the same categories and the
# same successors — checked before and after on real data, and the only
# difference is that the two project rows now DECLARE the kind they previously
# left absent. The engine reads the same answer either way; this migration
# makes the file state it rather than infer it.
#
# One honest nuance, since it is the only place the answer is not trivial: a
# project-side `void` retirement is excluded from the residue check by kind, so
# before this runs such a row can be over-reported. That is a conservative
# false positive in a report the owner dismisses, not a wrong write — and on an
# unmigrated table the kind is genuinely not recorded anywhere, so nothing is
# being lost, only left unsaid.
#
# The kind also matters for a reason beyond correctness: as `structural` this
# aborted the whole update on a clone whose shared library was not on disk yet,
# which is a supported mid-update state. A repair of existing data must never
# be able to block a future engine update.
#
# Parse, never guess: the decomposition reuses the engine's own registry
# parsers, including their guard that a successor is accepted only when it
# names an identifier the registry declares live. A row that cannot be
# decomposed confidently keeps its original text word for word in `Reason`,
# gets EMPTY Kind / Successor / Date cells rather than plausible ones, and is
# surfaced as a CLARIFICATION for the owner to answer through
# `/ztn:resolve-clarifications`. Every row's original text survives either way.
#
# `## Stale People` is not touched — a tier drop is archival, not identity
# retirement.
#
# Idempotent: a table whose header already declares Kind, Successor and Date is
# left alone, so the second run is a no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

python3 "$SCRIPT_DIR/_024_retirement_schema.py" --repo-root "$REPO_ROOT"
