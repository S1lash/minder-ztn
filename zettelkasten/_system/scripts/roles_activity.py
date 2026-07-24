#!/usr/bin/env python3
"""Plain-language role-activity digest — «what my roles did, and what they touched in my
external systems» in human words (FIX-SHIP-2 §2: trust IS the product — Doctrine §1).

A non-technical owner has `state.md` (what the role KNOWS) but no readable «what it DID
this week + what it touched outside». That trail exists only as engineer-shaped
`roles-runs.jsonl` / `roles-tool-audit.jsonl` / `pending_acts.json` / CLARIFICATIONS. This
module reads those and renders a plain-language summary per role — deterministic (no LLM),
so `/ztn:role:ask "what did you do"` and a weekly digest speak the same honest words.

It is a READ-ONLY projection: it never writes role state. It is NOT the deterministic
`ROLES.md` registry (which must stay byte-identical) — activity is volatile by nature, so
it renders on demand, never into a committed view.

Sources (all tolerant — a missing/corrupt one degrades to «nothing recorded», never a
crash or a guess):
  - `roles-runs.jsonl`     — per-tick outcomes (ran / empty / rejected / paused)
  - `roles-tool-audit.jsonl` — external reads + acts (create/update/close, hash+summary
                               only — never a raw return or a secret, INV-10/12)
  - `pending_acts.json`    — acts STAGED, awaiting the owner's `--approve-acts`
  - `CLARIFICATIONS.md`    — what needs the owner now (act-confirm / tool-request / …)

Deterministic + cross-platform (`pathlib`, UTC dates). `days`/`today` are parameters so
callers + tests are reproducible.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from _common import repo_root, state_dir
from roles_common import (
    clarifications_path,
    discover_role_ids,
    load_role_config,
    role_dir,
)

DEFAULT_WINDOW_DAYS = 7


def _tool_audit_path(base: Path | None) -> Path:
    return state_dir(base) / "roles-tool-audit.jsonl"


def _runs_path(base: Path | None) -> Path:
    return state_dir(base) / "roles-runs.jsonl"


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _iter_jsonl(path: Path) -> list[dict]:
    """Read a `.jsonl` into a list of dict rows — tolerant (a bad line is skipped, a
    missing file is empty). Never raises."""
    out: list[dict] = []
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _within_window(at: Any, cutoff: date) -> bool:
    """True when the ISO stamp `at` is on/after `cutoff` (date-only compare). A missing /
    unparseable stamp is INCLUDED (fail-open — never silently drop real activity)."""
    if not isinstance(at, str) or not at.strip():
        return True
    try:
        return date.fromisoformat(at.strip()[:10]) >= cutoff
    except ValueError:
        return True


# -----------------------------------------------------------------------------
# Extraction (structured, deterministic)
# -----------------------------------------------------------------------------

@dataclass
class RoleActivity:
    """One role's activity over the window — structured, before plain-language render."""
    role_id: str
    name: str
    runs_total: int = 0
    runs_by_status: dict = field(default_factory=dict)
    tool_reads: dict = field(default_factory=dict)          # tool_id -> count
    acts_executed: list = field(default_factory=list)        # effect strings
    acts_skipped: int = 0
    acts_drift: int = 0
    acts_failed: int = 0
    staged_now: int = 0                                       # awaiting approval
    needs_owner: dict = field(default_factory=dict)          # clar type -> count


def _open_role_clarifications(role_id: str, base: Path | None) -> dict[str, int]:
    """Count OPEN (unresolved) `role-*` CLARIFICATIONS naming this role — «what needs you
    now». Reads CLARIFICATIONS.md structurally: a role-clarif marker line
    `<!-- role-clarif: {type}/{subject} -->` on an item not in a resolved section. Tolerant
    — best-effort count, never a crash."""
    out: dict[str, int] = {}
    path = clarifications_path(base)
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    # Only the OPEN region — stop at a «Resolved» heading if the file separates them.
    open_region = re.split(r"(?im)^#{1,3}\s+resolved\b", text)[0]
    for m in re.finditer(r"<!--\s*role-clarif:\s*([a-z-]+)/(.*?)-->", open_region):
        ctype, subject = m.group(1), m.group(2)
        if role_id in subject or subject.strip().startswith(role_id):
            out[ctype] = out.get(ctype, 0) + 1
    return out


def collect_activity(role_id: str, base: Path | None = None,
                     days: int = DEFAULT_WINDOW_DAYS, today: date | None = None) -> RoleActivity:
    """Collect one role's activity over the last `days`. Read-only, tolerant."""
    day = today or _utc_today()
    from datetime import timedelta
    cutoff = day - timedelta(days=max(0, days))
    try:
        name = load_role_config(role_id, base).name or role_id
    except Exception:  # noqa: BLE001 — a broken config still gets an activity shell
        name = role_id
    act = RoleActivity(role_id=role_id, name=name)

    for run in _iter_jsonl(_runs_path(base)):
        if run.get("role_id") != role_id or not _within_window(run.get("run_at"), cutoff):
            continue
        act.runs_total += 1
        st = str(run.get("status") or "?")
        act.runs_by_status[st] = act.runs_by_status.get(st, 0) + 1

    for row in _iter_jsonl(_tool_audit_path(base)):
        if row.get("role_id") != role_id or not _within_window(row.get("at"), cutoff):
            continue
        if row.get("kind") == "act":
            status = str(row.get("status") or "")
            if status == "executed":
                act.acts_executed.append(str(row.get("summary") or row.get("op") or "acted"))
            elif status == "skipped":
                act.acts_skipped += 1
            elif status == "drift":
                act.acts_drift += 1
            elif status in ("failed", "refused"):
                act.acts_failed += 1
        else:  # a read-tool call
            tid = str(row.get("tool_id") or "a tool")
            act.tool_reads[tid] = act.tool_reads.get(tid, 0) + 1

    # Staged-now (independent of the window — it is the CURRENT pending set).
    pending = role_dir(role_id, base) / "pending_acts.json"
    if pending.is_file():
        try:
            data = json.loads(pending.read_text(encoding="utf-8"))
            act.staged_now = len(data.get("acts") or []) if isinstance(data, dict) else 0
        except (OSError, UnicodeDecodeError, ValueError):
            act.staged_now = 0

    act.needs_owner = _open_role_clarifications(role_id, base)
    return act


# -----------------------------------------------------------------------------
# Plain-language render (deterministic — no LLM, non-technical words)
# -----------------------------------------------------------------------------

_NEEDS_LABEL = {
    "role-act-confirm": "act(s) waiting for your approval",
    "role-tool-request": "request(s) for a new tool",
    "role-cold-start": "first draft(s) waiting for your OK",
    "role-emission-confirm": "note(s) waiting for your confirmation",
    "role-act-drift": "act(s) that hit a conflict",
    "role-act-failed": "act(s) that couldn't complete",
    "role-tool-reauth": "tool(s) needing re-authentication",
    "role-nudge": "thing(s) it flagged for you",
    "role-identity-suggest": "suggestion(s) about its own role",
    "role-budget-exhausted": "work deferred to next period (budget)",
}


def render_plain(act: RoleActivity, days: int = DEFAULT_WINDOW_DAYS) -> str:
    """Render one role's activity as plain, non-technical sentences."""
    who = act.name
    if act.runs_total == 0 and not act.staged_now and not act.needs_owner:
        return f"**{who}** — nothing in the last {days} days. It's watching quietly."

    parts: list[str] = []
    if act.runs_total:
        did = act.runs_by_status.get("ok", 0)
        empty = act.runs_by_status.get("empty", 0)
        s = f"ran {act.runs_total} time{'s' if act.runs_total != 1 else ''}"
        if did:
            s += f" ({did} with updates)"
        elif empty:
            s += " (nothing changed)"
        parts.append(s)

    if act.tool_reads:
        # Soften the machine tool-id for a non-technical reader (github-read → "github
        # read"). The digest stays registry-free (lightweight) — a plain hyphen→space is
        # enough to de-jargon the common ids without mangling a custom name.
        reads = ", ".join(
            f"{t.replace('-', ' ')} ({n})" for t, n in sorted(act.tool_reads.items()))
        parts.append(f"read from {reads}")

    if act.acts_executed:
        shown = "; ".join(act.acts_executed[:6])
        more = f" (+{len(act.acts_executed) - 6} more)" if len(act.acts_executed) > 6 else ""
        parts.append(f"made {len(act.acts_executed)} change(s) on your board — {shown}{more}")
    if act.acts_skipped:
        parts.append(f"left {act.acts_skipped} already-correct item(s) untouched")
    if act.acts_drift:
        parts.append(f"held back {act.acts_drift} change(s) that hit a conflict")
    if act.acts_failed:
        parts.append(f"couldn't complete {act.acts_failed} change(s)")

    body = f"**{who}** " + ("; ".join(parts) if parts else "was active") + "."

    tail: list[str] = []
    if act.staged_now:
        tail.append(f"**{act.staged_now} act(s) staged — run `/ztn:roles --approve-acts "
                    f"{act.role_id}` to apply or discard.**")
    for ctype, n in sorted(act.needs_owner.items()):
        if ctype == "role-act-confirm" and act.staged_now:
            continue  # already surfaced above
        label = _NEEDS_LABEL.get(ctype, ctype)
        tail.append(f"{n} {label}")
    if tail:
        body += "\n  · Needs you: " + "; ".join(tail)
    return body


def render_digest(role_ids: list[str], base: Path | None = None,
                  days: int = DEFAULT_WINDOW_DAYS, today: date | None = None) -> str:
    """A plain-language digest across roles — «what your roles did this week»."""
    if not role_ids:
        return f"You have no roles yet. Create one with `/ztn:role:add`."
    header = f"## What your roles did (last {days} days)\n"
    blocks = [render_plain(collect_activity(rid, base, days, today), days)
              for rid in role_ids]
    return header + "\n\n".join(blocks) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", default=None, help="one role id; omit + --all for every role")
    parser.add_argument("--all", action="store_true", help="every discovered role")
    parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--base", default=None, help="zettelkasten base override")
    args = parser.parse_args(argv)
    base = Path(args.base).resolve() if args.base else repo_root()
    if args.role:
        ids = [args.role]
    elif args.all:
        ids = sorted(discover_role_ids(base))
    else:
        parser.error("pass --role <id> or --all")
        return 2
    sys.stdout.write(render_digest(ids, base, max(0, args.days)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
