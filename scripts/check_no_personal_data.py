#!/usr/bin/env python3
"""
Personal-data linter.

Reads `.engine-manifest.yml` to learn which paths are engine + template
(those must contain no personal data identifying the owner of this
specific instance). Greps each path for blacklist patterns and reports.

The blacklist itself ships EMPTY in this script (see `DEFAULT_BLACKLIST`
below) — this script is engine code and reaches every friend's clone.
Three layers feed the final pattern list, in order:

1. `DEFAULT_BLACKLIST` — always empty (see above).
2. `load_owner_blacklist` — this instance's hand-curated residue list,
   read from `<repo-root>/personal-data-blacklist.txt` (git-tracked here,
   never shipped — see below).
3. `build_dynamic_blacklist` — patterns DERIVED at scan time from this
   instance's own data registries: `zettelkasten/3_resources/people/PEOPLE.md`
   (every real person's id + name), `zettelkasten/1_projects/PROJECTS.md`
   (every real project's id + display name), `zettelkasten/_system/SOUL.md`
   (the owner's Identity section — name, employer, location, handle, email),
   and `zettelkasten/0_constitution/{axiom,principle,rule}/*.md` (every
   principle's verbatim title + statement, ≥20 chars). This is what makes
   the linter auto-cover a growing PEOPLE.md/PROJECTS.md without hand-
   maintaining a blacklist line per person — a static list proved
   insufficient in practice (real coworker names, project names, and a
   verbatim axiom quote slipped through it before this layer existed).
   Guarded by `SAFE_TERMS` (synthetic placeholders and public product
   names like `Minder`/`ZTN` are never turned into patterns, even though
   they appear literally in the registries as example rows or project
   names), a common-word stoplist, a minimum length, and a placeholder
   (`{...}`) skip — see `_finalize_pattern` and the source-specific
   extractors below it for the full guard chain. On a fresh clone the
   registries are still template-shaped, so this layer returns close to
   nothing and the linter still runs clean.

The constitution-derived slice of the dynamic layer (verbatim axiom/
principle/rule title + statement patterns) is further scoped by
`SANCTIONED_PRINCIPLE_HOMES`: a small set of paths that legitimately ship
verbatim owner axioms as worked examples (the onboarding starter-pack, the
constitution protocol spec's own example, and the pipeline test fixtures).
`build_dynamic_blacklist_tagged` returns the constitution patterns as a
separate tagged list; `main()` skips that list — and only that list — when
scanning a file under one of those paths. Every other pattern class (people,
projects, identity, static blacklist) still applies there, and the
constitution patterns still apply to every other file. See
`SANCTIONED_PRINCIPLE_HOMES` below for the exact path list and rationale.

This instance's real patterns live in `<repo-root>/personal-data-blacklist.txt`,
a git-tracked-but-never-shipped file read at runtime (see
`load_owner_blacklist`). Friends populate their own from
`personal-data-blacklist.example.txt` (which does ship); the dynamic layer
above works for them too, with zero setup, once their own registries fill in.

Exit code:
  0 — no leaks found
  1 — leaks found (CI fails)

Usage:
  scripts/check_no_personal_data.py            # human report
  scripts/check_no_personal_data.py --quiet    # machine-readable, hits only
  scripts/check_no_personal_data.py --extra-pattern '\bAlice\b'

Manifest must be at repo root: `.engine-manifest.yml`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML required. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# Ships EMPTY — this file is engine code, distributed to every friend's
# clone. Naming the owner's identity, employer, or coworkers here would be
# exactly the leak this linter exists to prevent. This instance's real
# patterns are read at runtime from `<repo-root>/personal-data-blacklist.txt`
# (git-tracked in THIS private repo, never shipped — see `load_owner_blacklist`).
# Friends: copy `personal-data-blacklist.example.txt` to
# `personal-data-blacklist.txt` and add your own identifiers.
DEFAULT_BLACKLIST: list[str] = []

BLACKLIST_FILENAME = "personal-data-blacklist.txt"

# Filename suffixes considered text. Anything else skipped.
TEXT_SUFFIXES = {
    ".md", ".yml", ".yaml", ".sh", ".py", ".txt", ".json", ".toml", ".cfg", ".ini",
}

# Paths that legitimately ship a verbatim owner axiom/principle/rule as a
# worked example — the owner's rule is "abstract principles may ship", so a
# constitution-derived pattern (title/statement text mined from
# `0_constitution/`) is never a leak in these three homes:
#   - the onboarding starter-pack, which literally IS a curated set of
#     example axioms handed to friends;
#   - the constitution protocol spec's own worked example (`CONSTITUTION.md`
#     documents the axiom/principle/rule shape by showing one, verbatim);
#   - the pipeline test fixtures, which need a realistic verbatim statement
#     to exercise `_constitution_candidates` / the dynamic-blacklist tests.
# Only the constitution-derived slice of the dynamic blacklist is skipped
# here (see `build_dynamic_blacklist_tagged`) — people, projects, identity,
# and the static blacklist still apply to every path below, and the
# constitution-derived patterns still apply to every path NOT listed here.
# A trailing `/` matches a directory prefix; no trailing `/` matches exactly
# one file.
SANCTIONED_PRINCIPLE_HOMES = (
    "zettelkasten/5_meta/starter-pack/",
    "zettelkasten/0_constitution/CONSTITUTION.md",
    "zettelkasten/_system/scripts/tests/",
)


def is_sanctioned_principle_home(rel_path: Path) -> bool:
    """True when `rel_path` (relative to repo root) falls under one of the
    `SANCTIONED_PRINCIPLE_HOMES` — see that constant for the guard chain
    this participates in."""
    rel_str = rel_path.as_posix()
    for home in SANCTIONED_PRINCIPLE_HOMES:
        if home.endswith("/"):
            if rel_str.startswith(home):
                return True
        elif rel_str == home:
            return True
    return False


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_manifest(root: Path) -> dict:
    p = root / ".engine-manifest.yml"
    if not p.exists():
        print(f"error: manifest not found at {p}", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f)


def load_owner_blacklist(root: Path) -> list[str]:
    """Read this instance's real patterns from `personal-data-blacklist.txt`.

    That file is git-tracked in THIS private repo (so CI here has it) but is
    never listed in `.engine-manifest.yml`, so it never ships to the public
    skeleton. Absent file (e.g. a friend's fresh clone that hasn't copied
    `personal-data-blacklist.example.txt` yet) is not an error — the linter
    just runs with an empty blacklist and passes.
    """
    p = root / BLACKLIST_FILENAME
    if not p.exists():
        return []
    patterns: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


# -----------------------------------------------------------------------------
# Dynamic blacklist — derived from this instance's own data registries.
# -----------------------------------------------------------------------------
#
# Never turned into a pattern even if a registry row literally contains one:
# synthetic placeholder ids used throughout the engine's own depersonalized
# examples, and public product names that are meant to ship. Case-insensitive;
# a derived value that is entirely composed of these tokens is also dropped
# (see `_is_safe_term`) — otherwise a project literally named "minder" (this
# instance's own project id) would flag every mention of the product itself.
SAFE_TERMS = {
    "ivan-petrov", "petya-ivanov", "anna-smirnova", "maria-sidorova",
    "oleg-volkov", "katya-orlova", "sergey-kozlov", "john-doe",
    "acme-payments", "example.com", "project-alpha", "project-beta",
    "Minder", "minder-ztn", "minder.host", "ZTN", "Zettelkasten",
}
_SAFE_TERMS_LOWER = {t.lower() for t in SAFE_TERMS}

# Table header words / stray fragments that must never stand alone as a
# pattern (defence in depth against a parsing edge case grabbing a header
# cell instead of a data cell).
_COMMON_WORD_STOPLIST = {"status", "active", "personal", "work", "name", "role", "project"}

# Below this length a derived token is more likely a stray initial/fragment
# than a real identifier — drop it rather than risk a noisy pattern.
MIN_PATTERN_LENGTH = 5

_PLACEHOLDER_MARKERS = ("{", "}", "REPLACE_WITH_", "<", ">", "...")

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9][\w.\-]*")


def _looks_like_placeholder(value: str) -> bool:
    """True for unfilled template values — never derive a pattern from these."""
    return any(marker in value for marker in _PLACEHOLDER_MARKERS)


def _is_safe_term(value: str) -> bool:
    """True when `value` matches — or is composed entirely of — SAFE_TERMS."""
    lowered = value.strip().lower()
    if lowered in _SAFE_TERMS_LOWER:
        return True
    tokens = _TOKEN_RE.findall(lowered)
    return bool(tokens) and all(t in _SAFE_TERMS_LOWER for t in tokens)


def _is_word_char(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch == "_")


def _finalize_pattern(value: str) -> str | None:
    """Single choke point every derived candidate passes through.

    Applies the placeholder / length / stoplist / safe-term guards, then
    `re.escape`s the literal and wraps it in `\\b...\\b` boundaries — mirrors
    how `personal-data-blacklist.txt` patterns are written by hand, so the
    dynamic layer composes with `DEFAULT_BLACKLIST` / `load_owner_blacklist`
    as plain interchangeable regex strings.

    A `\\b` boundary is only added on a side whose edge character is a word
    character. Names and ids always qualify on both sides. A constitution
    statement typically ends in sentence punctuation (`.`, `»`) — `\\b`
    there would require the *following* character to be a word character,
    which a sentence-ending period essentially never is (it's followed by
    whitespace or end-of-line), silently making the pattern unmatchable.
    Dropping the boundary on that side only removes an assertion, it never
    changes what literal text the pattern still requires.
    """
    v = value.strip()
    if not v or _looks_like_placeholder(v):
        return None
    if len(v) < MIN_PATTERN_LENGTH:
        return None
    if v.lower() in _COMMON_WORD_STOPLIST:
        return None
    if _is_safe_term(v):
        return None
    prefix = r"\b" if _is_word_char(v[0]) else ""
    suffix = r"\b" if _is_word_char(v[-1]) else ""
    return f"{prefix}{re.escape(v)}{suffix}"


# --- Markdown table parsing (PEOPLE.md, PROJECTS.md) ------------------------


def _split_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def _is_separator_row(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


def parse_markdown_tables(text: str) -> list[dict]:
    """Generic GFM-table parser: `[{'header': [...], 'rows': [[...], ...]}, ...]`.

    Tolerant of a single stray blank line inside a table body (PEOPLE.md's
    batch-append log occasionally leaves one between row runs) but stops at
    two consecutive blank lines or any non-table content line — so it never
    merges two distinct tables (they are always separated by a `##` heading
    or a `---` rule in the files this reads).
    """
    lines = text.splitlines()
    n = len(lines)
    tables: list[dict] = []
    i = 0
    while i < n - 1:
        if lines[i].strip().startswith("|") and _is_separator_row(lines[i + 1]):
            header = _split_table_row(lines[i])
            i += 2
            rows: list[list[str]] = []
            blank_run = 0
            while i < n:
                stripped = lines[i].strip()
                if stripped.startswith("|"):
                    rows.append(_split_table_row(lines[i]))
                    blank_run = 0
                    i += 1
                elif stripped == "":
                    blank_run += 1
                    i += 1
                    if blank_run >= 2:
                        break
                else:
                    break
            tables.append({"header": header, "rows": rows})
            continue
        i += 1
    return tables


_EMPTY_CELL_VALUES = {"", "-", "—"}
_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def _is_empty_cell(value: str) -> bool:
    v = value.strip()
    return v in _EMPTY_CELL_VALUES or v.startswith("_(")


def _id_name_rows_from_tables(text: str) -> list[tuple[str, str]]:
    """Extract (id, name) pairs from every table whose header is
    `ID | Name | ...` (case-insensitive) — the shape PEOPLE.md's `## People` /
    `## Stale People` tables and PROJECTS.md's project tables share.

    Tables with a different header shape are skipped automatically: PEOPLE.md's
    2-column `## Removed` list (header `ID | Reason`, no `Name` column) and
    PROJECTS.md's `Old ID | Status | Now part of` redirect table (first header
    cell is `Old ID`, not `ID`) never match.
    """
    out: list[tuple[str, str]] = []
    for table in parse_markdown_tables(text):
        header = [h.strip().lower() for h in table["header"]]
        if not header or header[0] != "id" or "name" not in header:
            continue
        name_idx = header.index("name")
        for row in table["rows"]:
            if len(row) <= name_idx:
                continue
            rid, name = row[0].strip(), row[name_idx].strip()
            if not _ID_RE.match(rid):
                continue
            if _is_empty_cell(rid) or _is_empty_cell(name):
                continue
            if _looks_like_placeholder(rid) or _looks_like_placeholder(name):
                continue
            out.append((rid, name))
    return out


def _is_specific_display_name(name: str) -> bool:
    """Guard for PROJECTS.md display names: the id is always emitted (specific
    by construction — a kebab identifier), but the free-text name is only
    emitted when it is unlikely to be a generic single word."""
    v = name.strip()
    return bool(v) and (" " in v or "-" in v or len(v) >= 6)


def _people_candidates(root: Path) -> list[str]:
    path = root / "zettelkasten" / "3_resources" / "people" / "PEOPLE.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[str] = []
    for rid, name in _id_name_rows_from_tables(text):
        out.append(rid)
        out.append(name)
    return out


def _project_candidates(root: Path) -> list[str]:
    path = root / "zettelkasten" / "1_projects" / "PROJECTS.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[str] = []
    for rid, name in _id_name_rows_from_tables(text):
        out.append(rid)
        if _is_specific_display_name(name):
            out.append(name)
    return out


# --- SOUL.md Identity section -------------------------------------------------

_IDENTITY_FIELDS = {"name", "role", "location", "handle", "github", "email", "employer"}
_IDENTITY_BULLET_RE = re.compile(r"^-\s+\*\*([^*:]+):\*\*\s*(.+)$")


def _extract_section(text: str, heading: str) -> str | None:
    """Return the body of a `## Heading` section (up to the next `## `), or
    None if the heading is absent."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def _extract_employer_candidates(role_value: str) -> list[str]:
    """Pull employer-like proper nouns out of a free-text Role bullet.

    Structural, not semantic — deliberately does not try to parse arbitrary
    prose (that risks grabbing a generic word and turning it into an
    over-broad pattern). Only two shapes qualify:

    - Text after a literal `@` (the `Role @ Employer` convention), up to the
      next `.`/`,`/`(`.
    - Any parenthetical alias, e.g. `(brand X)` / `(бренд X)`, with the
      lead-in word stripped.

    Both are additionally required to start with an uppercase letter (a
    cheap proper-noun heuristic) — this is what keeps a hypothetical
    `(remote)` or `(part-time)` annotation from becoming a pattern. A Role
    value with neither shape yields nothing rather than guessing from prose.
    """
    out: list[str] = []
    at_match = re.search(r"@\s*([^.,(\n]+)", role_value)
    if at_match:
        candidate = at_match.group(1).strip()
        if candidate and candidate[0].isupper():
            out.append(candidate)
    for paren in re.findall(r"\(([^)]+)\)", role_value):
        cleaned = re.sub(r"^(?:бренд|brand|aka|a\.k\.a\.)\s+", "", paren.strip(), flags=re.IGNORECASE)
        if cleaned and cleaned[0].isupper():
            out.append(cleaned)
    return out


def _identity_candidates(root: Path) -> list[str]:
    path = root / "zettelkasten" / "_system" / "SOUL.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    section = _extract_section(text, "## Identity")
    if section is None:
        return []
    out: list[str] = []
    for line in section.splitlines():
        m = _IDENTITY_BULLET_RE.match(line.strip())
        if not m:
            continue
        field, value = m.group(1).strip().lower(), m.group(2).strip()
        if field not in _IDENTITY_FIELDS or _looks_like_placeholder(value):
            continue
        if field == "role":
            out.extend(_extract_employer_candidates(value))
        else:
            # Name / Location / Handle / Github / Email / Employer: taken
            # verbatim as one value, not split into words — e.g. Location's
            # "City, Country" stays one pattern rather than splitting into a
            # bare country name (a real false-positive risk: a country name
            # alone is generic enough to collide with unrelated text).
            out.append(value)
    return out


# --- Constitution (0_constitution/{axiom,principle,rule}/*.md) --------------

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def _read_frontmatter_fields(path: Path, fields: tuple[str, ...]) -> dict:
    """Minimal standalone frontmatter reader.

    Deliberately does not import `zettelkasten/_system/scripts/_common.py`
    (which has its own `read_frontmatter`) — this script ships standalone to
    every friend's clone under `scripts/`, a different subsystem than the ZTN
    pipeline package under `zettelkasten/_system/scripts/`, and stays
    independently distributable without that cross-package coupling.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in fields if k in data}


def _constitution_candidates(root: Path) -> list[str]:
    base = root / "zettelkasten" / "0_constitution"
    out: list[str] = []
    for kind in ("axiom", "principle", "rule"):
        kind_dir = base / kind
        if not kind_dir.exists():
            continue
        for md_path in sorted(kind_dir.rglob("*.md")):
            fm = _read_frontmatter_fields(md_path, ("title", "statement"))
            for field in ("title", "statement"):
                value = fm.get(field)
                if not isinstance(value, str):
                    continue
                normalized = " ".join(value.split())
                if len(normalized) >= 20 and not _looks_like_placeholder(normalized):
                    out.append(normalized)
    return out


def _dedupe_into_patterns(candidates: list[str], seen: set[str]) -> list[str]:
    """Run `candidates` through `_finalize_pattern`, keeping first-seen order
    and skipping anything already in `seen` (mutated in place — shared across
    the general/constitution split in `build_dynamic_blacklist_tagged` so a
    value that would produce the same pattern from two sources is never
    listed twice)."""
    patterns: list[str] = []
    for value in candidates:
        pattern = _finalize_pattern(value)
        if pattern and pattern not in seen:
            seen.add(pattern)
            patterns.append(pattern)
    return patterns


def build_dynamic_blacklist_tagged(root: Path) -> tuple[list[str], list[str]]:
    """Derive personal-data regex patterns from this instance's own data
    registries, split into `(general_patterns, constitution_patterns)`.

    `general_patterns` come from people, projects, and identity (SOUL.md) —
    these apply everywhere, unconditionally. `constitution_patterns` come
    from verbatim axiom/principle/rule title + statement text — these are
    the ones `main()` skips for files under `SANCTIONED_PRINCIPLE_HOMES`
    (see that constant for why). The two lists are deduped against a shared
    `seen` set, general first, so this split changes nothing about which
    patterns exist versus the pre-split single-list design — only how
    `main()` is able to apply them. See the module docstring for the full
    design and the guard chain in `_finalize_pattern`.

    Pattern sources are read directly by path (not through `expand_paths`),
    so reading them never adds them to the linter's own scan targets — they
    are owner-data paths, already outside `.engine-manifest.yml`'s
    `engine:`/`template:` lists.

    Missing registry files are not an error — each source function returns
    `[]` and derivation continues with whatever is available. On a fresh
    clone the registries are still template-shaped (`{placeholder}` values),
    so every candidate is caught by the placeholder guard and this returns
    two empty (or near-empty) lists — the linter still runs clean.
    """
    general_candidates: list[str] = []
    general_candidates.extend(_people_candidates(root))
    general_candidates.extend(_project_candidates(root))
    general_candidates.extend(_identity_candidates(root))

    seen: set[str] = set()
    general_patterns = _dedupe_into_patterns(general_candidates, seen)
    constitution_patterns = _dedupe_into_patterns(_constitution_candidates(root), seen)
    return general_patterns, constitution_patterns


def build_dynamic_blacklist(root: Path) -> list[str]:
    """Flat, untagged view of `build_dynamic_blacklist_tagged` — general
    patterns followed by constitution-derived patterns, identical to the
    single-list design before the sanctioned-homes split existed. Kept for
    callers (tests, ad-hoc scans) that don't need the per-file exception
    `main()` applies; see `build_dynamic_blacklist_tagged` for that."""
    general_patterns, constitution_patterns = build_dynamic_blacklist_tagged(root)
    return general_patterns + constitution_patterns


def expand_paths(root: Path, raw: list[str]) -> list[Path]:
    """Expand manifest entries into concrete file paths."""
    out: list[Path] = []
    self_path = Path(__file__).resolve()
    blacklist_path = (root / BLACKLIST_FILENAME).resolve()
    for entry in raw or []:
        p = root / entry.rstrip("/")
        if p.is_dir():
            for sub in p.rglob("*"):
                if sub.is_file() and sub.suffix in TEXT_SUFFIXES and sub.resolve() not in (self_path, blacklist_path):
                    out.append(sub)
        elif p.is_file():
            if p.suffix in TEXT_SUFFIXES and p.resolve() not in (self_path, blacklist_path):
                out.append(p)
        else:
            # Path does not exist yet (e.g. integrations/VERSION before creation).
            # Skip silently — release tooling will error if a manifested path
            # is missing at extraction time.
            continue
    return sorted(set(out))


def scan_file(path: Path, patterns: list[re.Pattern[str]]) -> list[tuple[int, str, str]]:
    """Return list of (line_no, pattern, line_text) for each hit."""
    hits: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return hits
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pat in patterns:
            if pat.search(line):
                hits.append((line_no, pat.pattern, line.rstrip()))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true", help="machine-readable, hits only")
    ap.add_argument(
        "--extra-pattern",
        action="append",
        default=[],
        help="add an extra regex to the blacklist (repeatable)",
    )
    args = ap.parse_args()

    root = repo_root()
    manifest = load_manifest(root)

    engine_paths = expand_paths(root, manifest.get("engine", []))
    template_paths = expand_paths(root, manifest.get("template", []))
    targets = sorted(set(engine_paths + template_paths))

    general_dynamic, constitution_dynamic = build_dynamic_blacklist_tagged(root)
    always_raw = (
        DEFAULT_BLACKLIST
        + load_owner_blacklist(root)
        + general_dynamic
        + list(args.extra_pattern)
    )
    always_patterns = [re.compile(p) for p in always_raw]
    constitution_patterns = [re.compile(p) for p in constitution_dynamic]

    total_hits = 0
    files_with_hits = 0
    for path in targets:
        rel = path.relative_to(root)
        # Constitution-derived verbatim patterns are skipped for files under
        # SANCTIONED_PRINCIPLE_HOMES — see that constant. Every other
        # pattern class (people, projects, identity, static blacklist,
        # --extra-pattern) still applies everywhere, including here.
        patterns = (
            always_patterns
            if is_sanctioned_principle_home(rel)
            else always_patterns + constitution_patterns
        )
        hits = scan_file(path, patterns)
        if not hits:
            continue
        files_with_hits += 1
        for line_no, pat, line in hits:
            total_hits += 1
            if args.quiet:
                print(f"{rel}:{line_no}\t{pat}\t{line}")
            else:
                print(f"{rel}:{line_no}  [{pat}]")
                print(f"    {line}")

    if not args.quiet:
        print()
        print(f"scanned {len(targets)} files, {files_with_hits} with leaks, {total_hits} total hits")
        if total_hits == 0:
            print("✓ no personal data leaks found")
        else:
            print("✗ personal data leaks found — fix before extraction")

    return 1 if total_hits > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
