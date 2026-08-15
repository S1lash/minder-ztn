#!/usr/bin/env bash
# migration-kind: heal
# 023-owner-persona — the owner becomes a person in their own base.
#
# The base is about the owner's life, and the owner is not in it as an
# identity: no row in the people registry, no profile card. That is not one
# clone's oversight, it is a hole in the model — from this version on the
# engine resolves identity against the registry, and a check that reads
# «absent from the registry, therefore drift» would call the owner of the base
# garbage.
#
# This migration creates both:
#
#   * `## Owner` in `3_resources/people/PEOPLE.md` — its own section, apart
#     from the general table, because tier mechanics (mention counting,
#     promote, demote) do not apply to someone present in nearly everything.
#   * `3_resources/people/{owner}.md` — a profile assembled from named
#     sources: the identity card in SOUL, the active constitution, the focus
#     and working model in SOUL, the people around them, and whatever they
#     wrote about themselves under `_sources/**/describe-me/`.
#
# Assembled, never invented. A source that says nothing produces no section,
# and the section appears on a later run once the source does — so a friend
# whose constitution is still empty gets a smaller profile now and a fuller
# one later, rather than a stub with a name in it.
#
# `heal`, and the test is not «is this important». It is: does an unapplied or
# half-applied state make the engine read the WRONG thing? Here it does not.
# `_common.owner_identity` prefers the declared `## Owner` row and, absent one,
# derives the identifier from `SOUL.md → ## Identity → Name:` — its own
# docstring says the derivation exists «so a base that has not got one yet
# still knows who its owner is». A clone without this migration resolves the
# owner to the same identifier and excludes it from identity checks just the
# same. What is missing is the profile, which nothing reads to decide anything.
# Un-run means a page the owner does not have yet, not an engine pointed
# somewhere wrong.
#
# The kind is also what keeps a repair from being able to block an update: as
# `structural` this aborted every friend's `/ztn:update` on a clone whose
# shared library was not on disk yet — a supported mid-update state with its
# own self-heal path.
#
# Never blocks on a data condition, and never invents one either. It runs only
# on a base that has an owner:
#
#   * SOUL still carries the placeholder name the skeleton ships — the clone
#     has not been bootstrapped. Deriving from it would mint a person out of
#     template prose, invisible to every identity check (nothing writes a
#     registry row for it) and permanent (the real name later produces a
#     SECOND profile and leaves the first standing). Nothing is written.
#   * SOUL has no name line at all — the owner is told, in their own
#     clarification queue, what is missing and what to do about it.
#
# Never fakes success in either case, nor when the engine library is not on
# disk: it writes nothing, says why, and exits non-zero — which for a `heal` is
# recorded `partial`, so the update continues and the next one runs it for
# real. Exiting zero would be recorded `applied` and the work would never
# happen.
#
# Idempotent: the registry section is added only when absent, and each
# generated block in the profile carries the hash of what this migration last
# wrote there — a block that still matches is refreshed from current sources,
# and a block the owner has edited is left exactly as they left it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

python3 "$SCRIPT_DIR/_023_owner_persona.py" --repo-root "$REPO_ROOT"
