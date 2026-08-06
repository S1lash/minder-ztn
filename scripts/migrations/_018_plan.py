#!/usr/bin/env python3
"""Turn a previous-shape role directory into a conversion PLAN the concierge runs.

The hand-off tells the owner what they had. This tells `/ztn:role:add` what it
can carry across without asking, and — just as importantly — what it must not
decide alone. One JSON file per migration, read by `/ztn:role:add --from-previous`.

Why a plan rather than a finished role: the previous shape's prose is written in
a vocabulary that no longer exists (parts, ledger ops, staged acts), and copying
it verbatim would tell a role to do things nothing implements — it would not
fail, it would improvise. Rewriting that prose into the current vocabulary is
exactly what the concierge is for. And `writes:` is the boundary the whole design
rests on: the plan PROPOSES it, with its reasoning, and the owner confirms. A
proposal the owner sees is not a guess.

What is derivable, and how confident:

    certain   — id, name, cadence, status. Same meaning in both shapes.
    proposed  — writes. `emit_inbox: true` means the role put notes in the
                inbox; any role keeps its own state. Both are safe defaults the
                owner confirms. Anything beyond them is theirs to name.
    proposed  — secrets, and ONLY for a role that actually reached outward.
                The store's names belong to the base, not to any one role. The
                store is the SAME file and the SAME encryption in both shapes —
                only the env var holding the key was renamed — so the values
                carry across intact and nothing is re-entered.
    seed      — the body. The old `hooks/tick.md`, handed to the concierge as
                RAW MATERIAL to rewrite, never as text to paste.

Emits `_previous/{id}.plan.json`. Deletes nothing, reads only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG = "config.yml"
# Old and new secret stores are the same path, shape and primitive (Fernet);
# only the environment variable holding the key was renamed. Verified by
# encrypting in the old scheme and decrypting with the current module.
OLD_KEY_ENV = "ZTN_SECRET_MASTER_KEY"
NEW_KEY_ENV = "ZTN_ROLES_KEY"


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def scalar(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def flag(text: str, key: str) -> bool:
    return scalar(text, key).lower() in ("true", "yes", "on")


def listed(text: str, key: str) -> list:
    """Top-level `key:` followed by `- item` lines. Enough for the old shape."""
    out, capturing = [], False
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            capturing = True
            continue
        if capturing:
            stripped = line.strip()
            if line[:1] not in (" ", "\t", "-") and stripped:
                break
            if stripped.startswith("- "):
                out.append(stripped[2:].strip().strip("'\""))
    return out


def cadence_of(cfg: str) -> str:
    """`cadence` + `cadence_anchor` as one current-shape cadence string.

    The grammars agree on the forms that matter — `daily`, `weekly <dow>`,
    `monthly <n>` — so this is a join, not a translation.
    """
    parts = [scalar(cfg, "cadence"), scalar(cfg, "cadence_anchor")]
    return " ".join(p for p in parts if p)


def build(role_dir: Path, store_names: list) -> dict:
    cfg = read(role_dir / CONFIG)
    tick = read(role_dir / "hooks" / "tick.md").strip()
    ask = read(role_dir / "hooks" / "ask.md").strip()
    brief = read(role_dir / "brief.md").strip()

    writes, why = ["state"], ["every role keeps its own memory"]
    if flag(cfg, "emit_inbox"):
        writes.append("inbox")
        why.append("`emit_inbox: true` — it put notes into your inbox")

    return {
        "id": scalar(cfg, "id") or role_dir.name,
        "certain": {
            "name": scalar(cfg, "name") or role_dir.name,
            "cadence": cadence_of(cfg) or "weekly",
            "status": scalar(cfg, "status") or "active",
        },
        "proposed": {
            "writes": writes,
            "writes_reasoning": why,
            # ONLY for a role that actually reached outward. The store's names
            # belong to the base, not to any one role, and handing every role
            # every credential would declare ones it never used — noise at best,
            # and a preflight failure at worst. Which of these a tool-bearing
            # role used lived in the old tools registry, which is opaque here,
            # so these are candidates the owner confirms, never a conclusion.
            "secrets": store_names if listed(cfg, "tools") else [],
            "secrets_note": (
                f"read from the credential store, which is the same file and the "
                f"same encryption in both shapes — only the key's environment "
                f"variable was renamed, {OLD_KEY_ENV} → {NEW_KEY_ENV}. The values "
                f"carry across untouched; nothing has to be re-entered."
            ) if (store_names and listed(cfg, "tools")) else "",
        },
        "seed": {
            "assignment": tick,
            "ask_hook": ask,
            "brief": brief,
            "instruction": (
                "RAW MATERIAL, not text to paste. It is written in a vocabulary "
                "that no longer exists — parts, ledger ops, staged acts. Read what "
                "the owner WANTED and write that in the current shape, in their "
                "register. If a sentence only makes sense under the old machinery, "
                "drop it and say so."
            ),
        },
        "must_ask": _must_ask(cfg, tick),
        "ran_before": any((role_dir / m).is_file()
                          for m in ("state.md", "decisions.jsonl")),
    }


def _must_ask(cfg: str, tick: str) -> list:
    """What the concierge may NOT settle alone. Kept short on purpose.

    A long list turns a two-minute confirmation into an interview and the owner
    stops reading — which is how a `writes:` they never looked at gets accepted.
    """
    asks = []
    if any(w in tick.lower() for w in ("файл", "документ", "file", "document",
                                       "доку", "note", "заметку")):
        asks.append({
            "topic": "a named document",
            "why": ("the assignment mentions maintaining a document. If it keeps "
                    "ONE file, that file goes in `writes:` by name — a whole "
                    "directory of the owner's notes is refused, and rightly"),
        })
    if listed(cfg, "tools"):
        asks.append({
            "topic": "the outside service",
            "why": ("it reached outward. The credential carries across, but the "
                    "endpoint and request shape lived in the old tools registry "
                    "and must be written into the role's own prose now"),
        })
    return asks


def main(argv: list) -> int:
    parked_root = Path(argv[1]).resolve()
    store_names = json.loads(argv[2]) if len(argv) > 2 else []
    if not parked_root.is_dir():
        return 0
    written = 0
    for d in sorted(parked_root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        plan = build(d, store_names)
        (parked_root / f"{plan['id']}.plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written += 1
    print(f"[migration 018] wrote {written} conversion plan(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
