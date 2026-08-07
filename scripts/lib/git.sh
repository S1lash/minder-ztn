#!/usr/bin/env bash
# Git plumbing primitives — the one owner of "how this engine talks to git".
#
# Source it, do not execute it:
#
#     . "$(dirname "$0")/../lib/git.sh"     # from scripts/scheduler/*
#     . "$(dirname "$0")/lib/git.sh"        # from scripts/*
#
# Why this file exists. Three git behaviours are easy to get wrong, silent when
# wrong, and were each re-derived at several call sites — so a fix landed in one
# and not the others:
#
#   1. Branch detection. `git rev-parse --abbrev-ref HEAD` does NOT fail on a
#      detached HEAD: it exits 0 and prints the literal string `HEAD`. A caller
#      with an `|| echo DETACHED` fallback therefore never sees the fallback,
#      and downstream code treats `HEAD` as a branch name — building the ref
#      `origin/HEAD`, or pushing to a remote branch literally called `HEAD`.
#   2. Non-ASCII paths. With git's default `core.quotePath=true`, porcelain
#      output octal-escapes every non-ASCII byte (`"\320\222\321\201…"`). A
#      caller that only strips the wrapping quotes hands that literal string to
#      `git add`, which fails with "pathspec did not match" — losing a whole
#      commit over a Cyrillic filename.
#   3. MSYS path conversion. On Windows Git Bash, an argument shaped like
#      `<ref>:<path>` is rewritten by the MSYS runtime into `<ref>\<path>` with
#      the colon turned into `;`, so `git cat-file -e upstream/main:.gitignore`
#      fails as an invalid object name. `MSYS_NO_PATHCONV=1` on that single
#      invocation is the fix; it is inert everywhere else.
#
# bash 3.2 compatible (macOS system shell). No arrays returned, no `local -n`,
# no `declare -A`, no `${x^^}` — every function writes LF-separated lines to
# stdout and the caller reads them with `while IFS= read -r`.
#
# Every variable is `local`. This file is SOURCED into scripts that have their
# own variables; a helper that leaked `path` or `branch` into the caller's scope
# would be a bug that only shows up under a name collision, which is the worst
# kind to find.

# ---------------------------------------------------------------------------
# Branch identity
# ---------------------------------------------------------------------------

# git_current_branch [-C <dir>]
#
# Print the current branch name and return 0; print nothing and return 1 when
# HEAD is detached. `symbolic-ref` is the primitive that actually distinguishes
# the two — never `rev-parse --abbrev-ref`.
#
# Callers decide what detached means for them. Nobody ever receives the string
# "HEAD" as if it were a branch.
git_current_branch() {
  git "$@" symbolic-ref --short -q HEAD 2>/dev/null
}

# git_current_branch_or <fallback> [-C <dir>]
#
# Same, but prints <fallback> on a detached HEAD and always returns 0. For
# call sites that persist a branch label and need a sentinel rather than an
# empty string. Use the sentinel `DETACHED`; the engine treats it as
# "no delivery branch" wherever it appears.
git_current_branch_or() {
  local fallback branch
  fallback="$1"
  shift
  branch="$(git_current_branch "$@")"
  if [ -n "$branch" ]; then
    printf '%s\n' "$branch"
  else
    printf '%s\n' "$fallback"
  fi
  return 0
}

# git_is_branch_name <value>
#
# True when <value> names a real delivery branch — i.e. it is non-empty and is
# not one of the sentinels or the literal `HEAD` that a pre-fix `pin-main.sh`
# may have persisted into `.scheduler-state/start-branch`. The `HEAD` arm is
# defence against stale state written before this library existed; it is not
# the fix for the bug, which is `git_current_branch` above.
git_is_branch_name() {
  case "${1:-}" in
    "" | DETACHED | HEAD) return 1 ;;
    *) return 0 ;;
  esac
}

# ---------------------------------------------------------------------------
# Path listing — always quotepath-safe, always file-granular
# ---------------------------------------------------------------------------

# _git_extract_paths  (stdin: porcelain v1 lines; stdout: one path per line)
#
# Strips the two-column status prefix, resolves a rename entry to its
# destination, and removes the wrapping quotes git adds for a path containing
# spaces. Non-ASCII needs no decoding here because every caller below runs with
# `core.quotepath=false`.
_git_extract_paths() {
  local line path
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    path="${line:3}"
    path="${path##* -> }"
    path="${path#\"}"
    path="${path%\"}"
    printf '%s\n' "$path"
  done
}

# git_status_paths [-C <dir>]
#
# One repo-relative path per line for every dirty path in the working tree.
#
# `-uall` is load-bearing alongside `core.quotepath=false`: without it git
# collapses a wholly-new directory into a single entry ending in `/`, and every
# downstream filter then classifies a directory instead of the files inside it.
git_status_paths() {
  git -c core.quotepath=false "$@" status --porcelain -uall | _git_extract_paths
}

# git_staged_paths [-C <dir>]
#
# One repo-relative path per line for everything currently in the index.
git_staged_paths() {
  git -c core.quotepath=false "$@" diff --cached --name-only
}

# ---------------------------------------------------------------------------
# Ref access — MSYS-safe
# ---------------------------------------------------------------------------

# git_ref_has_path <ref> <path> [-C <dir>]
#
# True when <path> exists in <ref>. The `<ref>:<path>` argument shape is the
# one MSYS rewrites, so this is the only sanctioned way to ask the question.
git_ref_has_path() {
  local ref path rc
  ref="$1"
  path="$2"
  shift 2
  MSYS_NO_PATHCONV=1 git "$@" cat-file -e "$ref:$path" 2>/dev/null
  rc=$?
  return $rc
}

# git_ref_read_path <ref> <path> [-C <dir>]
#
# Print the blob at <path> in <ref> on stdout. Same MSYS constraint as above.
git_ref_read_path() {
  local ref path rc
  ref="$1"
  path="$2"
  shift 2
  MSYS_NO_PATHCONV=1 git "$@" show "$ref:$path" 2>/dev/null
  rc=$?
  return $rc
}
