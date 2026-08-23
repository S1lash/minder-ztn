"""Find starter axioms that were adopted while they still went hot uninvited.

The starter pack ships drafts you edit into your own voice. Its README is
explicit that they do NOT auto-load into the always-on `constitution-core`
view, and that opting one in MEANS adding `claude-code` to its `applies_to`.
Until 0.64.1 one of the six shipped with `claude-code` already present and
`core: true`, so `/ztn:bootstrap --with-starter-axioms` put an unedited
`status: draft` axiom straight into every session.

The fix to the shipped pack reaches new adoptions. It cannot reach a copy
already sitting in `0_constitution/axiom/` — that file stopped being engine
surface the moment it was copied, and a migration may not touch the owner's
constitution. So this reports instead: one clarification per affected axiom,
with the two ways out stated plainly. The owner decides; nothing is rewritten.

Detection is deliberately narrow — `confidence: starter` AND `status: draft`
AND `claude-code` in `applies_to`. An axiom the owner has actually made theirs
will have moved at least one of those, and is none of our business.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.portable import configure_std_streams  # noqa: E402

from _identity_migration_lib import (  # noqa: E402
    append_clarifications,
    clarification_anchor,
    read_text,
    resolve_base,
)

MIGRATION = "027-starter-axiom-hot-audit"

_FIELD = r"^{key}:[ \t]*(?P<v>.+?)[ \t]*$"


def _field(front: str, key: str) -> str:
    m = re.search(_FIELD.format(key=re.escape(key)), front, re.M)
    return m.group("v").strip() if m else ""


def _frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


def affected(base: Path) -> list[tuple[Path, str]]:
    """Adopted starter axioms still carrying `claude-code`. `(path, title)`."""
    root = base / "0_constitution" / "axiom"
    if not root.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*.md")):
        front = _frontmatter(read_text(path, default=""))
        if not front:
            continue
        if _field(front, "confidence") != "starter":
            continue
        if _field(front, "status") != "draft":
            continue
        applies = _field(front, "applies_to")
        # Only the inline-list form ships; a reformatted file is owner-touched.
        if "claude-code" not in applies:
            continue
        title = _field(front, "title") or path.stem
        out.append((path, title.strip("'\"")))
    return out


def build_items(base: Path, rows: list[tuple[Path, str]]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for path, title in rows:
        rel = path.relative_to(base).as_posix()
        anchor = clarification_anchor(MIGRATION, rel)
        block = (
            f"### Starter axiom loading into every session unedited — `{rel}`\n\n"
            f"**Type:** constitution-hygiene\n\n"
            f"**Situation:** «{title}» came from the starter pack and is still "
            f"marked `confidence: starter`, `status: draft` — a draft you have "
            f"not made yours yet. It also carries `claude-code` in its "
            f"`applies_to` and `core: true`, which is what puts a principle "
            f"into `constitution-core.md`, the view loaded in every session. "
            f"So an unedited draft has been acting as one of your standing "
            f"principles.\n\n"
            f"This was an engine defect, not something you did: the pack "
            f"shipped that value by mistake and its own README always said it "
            f"should not. The pack is fixed; your copy is yours, so only you "
            f"can decide what it should be.\n\n"
            f"**Two ways out, both fine:**\n\n"
            f"1. **Keep it.** If it does describe how you decide, edit the "
            f"wording into your own voice and set `confidence: working`, "
            f"`status: active`. Then it is a real principle of yours and "
            f"belongs in the hot view.\n"
            f"2. **Park it.** Remove `claude-code` from `applies_to` and it "
            f"stops loading, staying visible in your constitution until you "
            f"decide. Delete the file if it does not match how you actually "
            f"decide at all.\n\n"
            f"Either way, run `/ztn:regen-constitution` afterwards so the "
            f"views catch up.\n"
        )
        items.append((anchor, block))
    return items


def main() -> int:
    # An axiom title is owner text and may be non-ASCII; without this, printing
    # it raises UnicodeEncodeError under a Windows code page.
    configure_std_streams()
    repo_root = Path(__file__).resolve().parents[2]
    base = resolve_base(repo_root)
    if base is None:
        print("027: no zettelkasten base found — skipping")
        return 0

    rows = affected(base)
    if not rows:
        print("027: no adopted starter axiom is loading uninvited — clean")
        return 0

    items = build_items(base, rows)
    written, skipped = append_clarifications(
        base, MIGRATION, "migration 027 — starter axioms in the hot view", items,
    )
    print(
        f"027: {len(rows)} adopted starter axiom(s) loading into every session; "
        f"{written} clarification(s) queued, {skipped} already known"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
