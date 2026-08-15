#!/usr/bin/env python3
"""Migration 023 — the owner becomes a person in their own base.

The base is about the owner's life and the owner is not in it as an identity:
no row in the people registry, no profile card. That is not one clone's
oversight, it is a hole in the model — every identity check that reads «absent
from the registry, therefore drift» calls the owner of the base garbage.

This creates both, on a clone that predates the contract:

  1. `## Owner` in `3_resources/people/PEOPLE.md` — its own section, apart from
     the general table, because tier mechanics (mention counting, promote,
     demote) do not apply to someone present in nearly everything.
  2. `3_resources/people/{owner}.md` — a profile ASSEMBLED FROM NAMED SOURCES.

Assembled, never invented. Every section says which file it came from, and a
source that says nothing produces no section — it appears on a later run, once
the source does. That is the same rule the rest of the engine lives by, and it
is why a friend whose constitution is still empty gets a smaller profile now
and a fuller one later rather than a stub with a name in it.

Idempotency is per section and hash-guarded: a generated block that still
hashes to what this migration wrote is refreshed, and one that does not is the
owner's edit and is left exactly as they left it.

It runs only on a base that has an owner. A clone whose SOUL still carries the
placeholder name this engine ships has not been bootstrapped, and there is no
one yet to make a person of: the migration writes nothing, says so, and exits
non-zero so it is retried rather than recorded as done.

What it deliberately does NOT do: add the owner to the `people:` array of any
record. They are present by default almost everywhere; auto-population would
inflate every count and carry no signal. Their *absence* is the thing that
means something.

Usage: python3 _023_owner_persona.py --repo-root <path>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _identity_migration_lib import (  # noqa: E402
    append_clarifications,
    clarification_anchor,
    configure_std_streams,
    report_no_library,
    import_common,
    is_placeholder,
    is_separator_row,
    read_text,
    resolve_base,
    table_cells,
    upsert_block,
    write_text,
)

NS = "owner-profile"
MIGRATION = "migration-023"

# How many of the owner's people to name on the card. The registry is the full
# list; a profile that reprints 116 rows is a second registry, not a profile.
PEOPLE_SHOWN = 15

OWNER_SECTION = """\
## Owner

The person this base belongs to. Kept in its own section, separate from the \
general table, because tier mechanics — mention counting, promote, demote — \
do not apply to them: they are present in nearly everything, so a count \
carries no signal.

- **Identifier** — derived from `_system/SOUL.md → ## Identity → Name:` by the \
same `firstname-lastname` rule as every other row. It is the id used in \
`speaker:` on observation records.
- **Always a valid identity.** Identity checks treat the owner identifier as \
registered by definition — it is never reported as an identifier missing from \
the registry.
- **Registered, never auto-populated.** The owner is NOT added to the `people:` \
array of records and notes automatically. They are present by default almost \
everywhere; auto-population would inflate every count and carry no signal. \
Their *absence* from a record is what is significant.
- **Profile** — `3_resources/people/<id>.md`, same shape as any other profile \
(`5_meta/templates/person-template.md`), assembled from `SOUL.md`, the active \
constitution and the registry.

| ID | Name | Role | Profile |
|---|---|---|---|
| OWNER_ID | OWNER_NAME | OWNER_ROLE | [[OWNER_ID]] |
"""


# -----------------------------------------------------------------------------
# Sources
# -----------------------------------------------------------------------------

_SECTION_RE_CACHE: dict[str, re.Pattern[str]] = {}


def soul_section(soul: str, heading: str, level: int = 2) -> str:
    """The body of one `##` section of SOUL.md, verbatim, without its heading.

    Bounded by the next heading of the same or a shallower level, so a section
    with `###` subsections keeps them.
    """
    key = f"{level}:{heading}"
    pattern = _SECTION_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(
            r"^#{%d}\s+%s\s*$(.*?)(?=^#{1,%d}\s|\Z)" % (
                level, re.escape(heading), level,
            ),
            re.MULTILINE | re.DOTALL,
        )
        _SECTION_RE_CACHE[key] = pattern
    m = pattern.search(soul)
    return m.group(1).strip("\n") if m else ""


def soul_identity_field(identity_block: str, field: str) -> str:
    """One `- **Field:** value` line from SOUL's identity block.

    A field the owner has not filled in yet reads as absent, not as its own
    instruction text: a partially bootstrapped SOUL otherwise puts
    `{Current professional role / occupation}` in the registry's Role column,
    where nothing would ever notice it again.
    """
    value = raw_identity_field(identity_block, field)
    return "" if is_placeholder(value) else value


def raw_identity_field(identity_block: str, field: str) -> str:
    """The same line, exactly as it stands — placeholder and all.

    The guard in `main` needs to tell «the owner has not answered this yet»
    apart from «there is no such line», and only the unfiltered value carries
    that difference.
    """
    m = re.search(
        r"^\s*[-*]\s*\*\*%s:\*\*\s*(.+?)\s*$" % re.escape(field),
        identity_block, re.MULTILINE,
    )
    return m.group(1).strip() if m else ""


def bullet_leads(section: str) -> list[str]:
    """The bolded lead of each top-level bullet, in order.

    A compact index of a long section rather than a copy of it. The full text
    stays in its one home; duplicating it here would give the same fact two
    homes that diverge the first time either is edited.
    """
    out: list[str] = []
    for line in section.splitlines():
        if not re.match(r"^[-*]\s", line):
            continue  # indented sub-bullets and prose are not leads
        m = re.match(r"^[-*]\s+\*\*(.+?)\*\*", line)
        if m:
            out.append(m.group(1).strip().rstrip(":—- "))
    return out


def constitution_index(common, base: Path) -> list[str]:
    """`- \\`{id}\\` — {title}` for every ACTIVE principle, axioms first.

    An index of the tree, not a copy of it. A malformed or half-set-up
    constitution degrades to what parsed rather than to an exception — a
    migration that dies on one bad frontmatter file leaves the owner with no
    profile at all.
    """
    root = base / "0_constitution"
    if not root.is_dir():
        return []
    try:
        principles = common.iter_principles(root)
    except Exception:  # noqa: BLE001 — any parse failure degrades to «no index»
        return []
    order = {"axiom": 0, "principle": 1, "rule": 2}
    rows = []
    for p in principles:
        fm = p.frontmatter
        if str(fm.get("status", "active")).strip().lower() != "active":
            continue
        rows.append((
            order.get(str(fm.get("type", "")).strip(), 9),
            str(fm.get("id", "")),
            str(fm.get("title", "")).strip(),
        ))
    rows.sort()
    return [f"- `{pid}` — {title}" for _, pid, title in rows if pid]


def people_around(base: Path, owner_id: str) -> tuple[list[str], int]:
    """`(rendered rows, tier-1 total)` — the most-mentioned Tier-1 people.

    Selection is a stated rule, not a judgement: Tier 1, ordered by the
    registry's own mention count, the top `PEOPLE_SHOWN`. The registry stays
    the full list and the section says so.
    """
    path = base / "3_resources" / "people" / "PEOPLE.md"
    text = read_text(path, default="")
    if not text:
        return [], 0
    headers: list[str] | None = None
    people: list[tuple[int, str, str, str, str]] = []
    in_people = False
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            h = line.lstrip("#").strip().lower()
            in_people = h.startswith("people") and "registry" not in h
            headers = None
            continue
        if not in_people:
            continue
        cells = table_cells(line)
        if cells is None or is_separator_row(cells):
            continue
        if headers is None:
            headers = [c.lower() for c in cells]
            continue
        row = dict(zip(headers, cells))
        pid = (row.get("id") or "").strip("*_` ").strip()
        if not pid or pid == owner_id:
            continue
        if (row.get("tier") or "").strip() != "1":
            continue
        try:
            mentions = int((row.get("mentions") or "0").strip() or 0)
        except ValueError:
            mentions = 0
        people.append((
            -mentions, pid, (row.get("name") or "").strip(),
            (row.get("role") or "").strip(), (row.get("org") or "").strip(),
        ))
    people.sort()
    rendered = []
    for _neg, pid, name, role, org in people[:PEOPLE_SHOWN]:
        where = " @ ".join(x for x in (role, org) if x and x != "-")
        rendered.append(f"- [[{pid}]] — {name}" + (f", {where}" if where else ""))
    return rendered, len(people)


def describe_me_sources(base: Path) -> list[str]:
    """Pointers to everything the owner wrote about themselves.

    Pointers, not content. This is a migration: it can list what exists, and
    it cannot read a corpus and say what it means. A pointer the owner follows
    is honest; a summary a script invented is not.
    """
    out: list[str] = []
    for parent in ("inbox", "processed"):
        root = base / "_sources" / parent / "describe-me"
        if not root.is_dir():
            continue
        for md in sorted(root.rglob("*.md")):
            if md.name.lower().endswith("template.md"):
                continue
            out.append(f"- `{md.relative_to(base).as_posix()}`")
    return out


# -----------------------------------------------------------------------------
# Profile assembly
# -----------------------------------------------------------------------------

def _first_sentence(text: str) -> str:
    head, sep, _tail = text.strip().partition(". ")
    return head if sep else text.strip()


def soul_pointer(soul: str) -> str:
    """The pointer that replaces every copy.

    It names the SOUL sections that actually exist on this base, by heading, so
    the reader lands somewhere real — and says plainly why the text is not
    reproduced here. A profile block is written by a migration; a migration
    that recorded `applied` never runs again; so a copy could never be
    refreshed and nothing in the system would ever notice it had gone stale.
    `## Working Style` is absent from the list because it has its own section
    below, carrying its own pointer.
    """
    parts = [
        "Location, language, team, domain and experience are in "
        "`_system/SOUL.md → ## Identity`"
    ]
    if soul_section(soul, "Current Focus"):
        parts.append("what the owner is working on now is `## Current Focus`")
    return (
        "_" + "; ".join(parts) + ". Those sections are the source of truth and "
        "are not reproduced here: a copy in this profile could never be "
        "refreshed, and nothing would notice it had gone stale._"
    )


def build_sections(common, base: Path, owner_id: str) -> list[tuple[str, str]]:
    """`[(key, content)]` — one entry per section whose sources said something.

    Nothing here is a copy. Every section is either a field this profile owns
    in its own right (name and role, which the registry row carries too) or
    synthesis that exists in this form nowhere else — the principle index, the
    circle of people, the self-description pointers. Everything else is a
    pointer at the file that owns it.
    """
    soul_path = base / "_system" / "SOUL.md"
    soul = read_text(soul_path, default="")
    identity = soul_section(soul, "Identity")
    style = soul_section(soul, "Working Style")

    sections: list[tuple[str, str]] = []

    name = soul_identity_field(identity, "Name")
    role = soul_identity_field(identity, "Role")
    if name or role:
        # Name and role are the profile's own fields — every person card in
        # this base carries them, and so does the registry row. The rest of
        # SOUL is pointed at, never restated.
        fields = []
        if name:
            fields.append(f"- **Name:** {name}")
        if role:
            fields.append(f"- **Role:** {_first_sentence(role)}")
        sections.append((
            "identity",
            "## Identity\n\n" + "\n".join(fields) + "\n\n" + soul_pointer(soul),
        ))

    index = constitution_index(common, base)
    if index:
        sections.append((
            "constitution",
            "## Values and principles\n\n"
            "_Index of the active constitution at `0_constitution/`, which "
            "holds the statement, the evidence trail and the history of each "
            "one. Regenerated views live in `_system/views/`._\n\n"
            + "\n".join(index),
        ))

    leads = bullet_leads(style)
    if leads:
        sections.append((
            "working-style",
            "## Working style\n\n"
            "_Index of `_system/SOUL.md → ## Working Style`, which holds the "
            "full text. Listed here so the profile names what the owner's "
            "working model covers; it does not restate it._\n\n"
            + "\n".join(f"- {lead}" for lead in leads),
        ))

    rows, total = people_around(base, owner_id)
    if rows:
        shown = min(len(rows), PEOPLE_SHOWN)
        sections.append((
            "people",
            "## People around\n\n"
            f"_The {shown} most-mentioned of {total} Tier-1 people in "
            "`3_resources/people/PEOPLE.md`, ordered by that registry's own "
            "mention count. The registry is the full list._\n\n"
            + "\n".join(rows),
        ))

    described = describe_me_sources(base)
    if described:
        sections.append((
            "self-description",
            "## Self-description sources\n\n"
            "_What the owner wrote about themselves, under "
            "`_sources/**/describe-me/`. Listed as pointers: the files are the "
            "content, and a script summarising them would be inventing._\n\n"
            + "\n".join(described),
        ))

    return sections


def initial_profile(owner_id: str, name: str, today: str) -> str:
    """The card a profile starts as — frontmatter and title, nothing claimed.

    Written once, on the run that creates the file. Every later run touches
    only the generated sections, so the frontmatter is the owner's from the
    moment it exists.

    No role line: the `## Identity` block below owns that field, and stating it
    twice in one file is the same duplication as copying it out of SOUL, only
    at closer range.
    """
    title = name or owner_id
    return (
        "---\n"
        f"id: {owner_id}\n"
        f"title: {title}\n"
        f"name: {title}\n"
        f"created: '{today}'\n"
        "layer: person\n"
        "role: owner\n"
        "origin: personal\n"
        "audience_tags: []\n"
        "is_sensitive: false\n"
        "tags:\n"
        f"- person/{owner_id}\n"
        "- role/owner\n"
        "---\n\n"
        f"# {title}\n\n"
        "_The owner of this base. Sections below are assembled by the engine "
        "from named sources; anything you write outside them, and any edit you "
        "make inside them, is kept._\n"
    )


# -----------------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------------

_OWNER_HEADING_RE = re.compile(r"^#{1,6}\s*owner\b", re.IGNORECASE | re.MULTILINE)
_PEOPLE_HEADING_RE = re.compile(r"^##\s+People\s*$", re.MULTILINE)


def _cell(value: str, *, first_sentence: bool = False) -> str:
    """A SOUL line rendered safely into a one-line table cell.

    A raw `|` would split the cell and shift every column after it, so it is
    escaped. `first_sentence` keeps the Role cell to the current title: the
    SOUL line often continues into a former one, which is history and belongs
    in the profile's Identity section, not in the registry's Role column.
    """
    text = (value or "").strip()
    if first_sentence:
        text = _first_sentence(text)
    return text.replace("|", "\\|")


def ensure_owner_section(base: Path, owner_id: str, name: str, role: str) -> str:
    """Add `## Owner` to the people registry. Returns the outcome."""
    path = base / "3_resources" / "people" / "PEOPLE.md"
    if not path.is_file():
        return "no-registry"
    text = read_text(path)
    if _OWNER_HEADING_RE.search(text):
        return "present"
    # Placeholder substitution rather than `.format`, because the section text
    # legitimately contains braces of its own.
    section = (
        OWNER_SECTION
        .replace("OWNER_NAME", _cell(name) or owner_id)
        .replace("OWNER_ROLE", _cell(role, first_sentence=True) or "—")
        .replace("OWNER_ID", owner_id)
    )
    m = _PEOPLE_HEADING_RE.search(text)
    if m:
        text = text[:m.start()] + section + "\n---\n\n" + text[m.start():]
    else:
        text = text.rstrip("\n") + "\n\n---\n\n" + section
    write_text(path, text)
    return "added"


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

UNRESOLVED_BLOCK = """\
### {today} — owner identity could not be resolved

**Type:** owner-identity-missing
**Subject:** owner
**Source:** engine migration 023 (owner persona)
**Action taken:** none — no owner row and no owner profile were created
**Uncertainty:** The owner's identifier is derived from `_system/SOUL.md → \
## Identity → Name:`, and that line is missing or empty on this base. Without \
it the engine cannot name the owner, so every identity check has to treat the \
owner's identifier as an unregistered one.
**To resolve:** Add a `- **Name:** <your name>` line under `## Identity` in \
`_system/SOUL.md`, then run `/ztn:update` again — this migration retries and \
will create the registry row and the profile.
"""

# Not done, so do not fake success. A zero exit is recorded `applied` and this
# migration never runs again — which on a clone that is merely waiting for its
# owner to arrive would mean waiting forever. A non-zero exit from a `heal` is
# recorded `partial`, the update continues, and the next one retries. Same
# reasoning as `NO_LIBRARY_RC`, and the same value.
NOT_READY_RC = 1


def main(argv: list[str] | None = None) -> int:
    # Owner text is not ASCII; std streams must not use the platform default.
    configure_std_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args(argv)

    base = resolve_base(args.repo_root)
    if base is None:
        print("023: no zettelkasten base on this clone — nothing to do")
        return 0

    common = import_common(base)
    if common is None:
        return report_no_library("023", base)
    today = common.today_iso()

    soul = read_text(base / "_system" / "SOUL.md", default="")
    identity_block = soul_section(soul, "Identity")

    if is_placeholder(raw_identity_field(identity_block, "Name")):
        # The base has not been bootstrapped: the Name line still holds the
        # instruction the skeleton shipped. Deriving an identifier from it
        # mints a person out of template prose — one that no identity check
        # can see, because nothing wrote a registry row for it, and that this
        # migration would never replace, because when the real name arrives it
        # produces a second profile and leaves the first standing.
        print(
            "023: `_system/SOUL.md → ## Identity → Name:` still holds the "
            "placeholder this engine ships — the base has not been "
            "bootstrapped yet"
        )
        print(
            "023: nothing was written. Run `/ztn:bootstrap`; this migration "
            "runs by itself on the next update, once the owner has a name."
        )
        return NOT_READY_RC

    owner_id = common.owner_identity(base)
    if not owner_id:
        # A migration never blocks an update on a data condition. The owner is
        # told, in their own queue, what is missing and what to do about it.
        written, _ = append_clarifications(
            base, MIGRATION, f"migration 023 — owner persona ({today})",
            [(
                clarification_anchor(MIGRATION, "owner-unresolved"),
                UNRESOLVED_BLOCK.format(today=today),
            )],
        )
        print(
            "023: owner identifier not resolvable from SOUL.md — "
            + ("surfaced as a CLARIFICATION" if written else "already surfaced")
        )
        return NOT_READY_RC

    name = soul_identity_field(identity_block, "Name")
    role = soul_identity_field(identity_block, "Role")

    registry_outcome = ensure_owner_section(base, owner_id, name, role)

    profile_path = base / "3_resources" / "people" / f"{owner_id}.md"
    created = not profile_path.exists()
    document = (
        initial_profile(owner_id, name, today) if created
        else read_text(profile_path)
    )

    outcomes: dict[str, list[str]] = {}
    for key, content in build_sections(common, base, owner_id):
        document, outcome = upsert_block(document, NS, key, content)
        outcomes.setdefault(outcome, []).append(key)

    write_text(profile_path, document)

    rel = profile_path.relative_to(base).as_posix()
    print(f"023: owner `{owner_id}` — registry section {registry_outcome}")
    print(f"023: profile {rel} {'created' if created else 'updated in place'}")
    for outcome in ("added", "refreshed", "unchanged", "kept"):
        keys = outcomes.get(outcome)
        if keys:
            print(f"023:   sections {outcome}: {', '.join(sorted(keys))}")
    if not outcomes:
        print("023:   no section had a source to build from yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
