#!/usr/bin/env python3
"""The run line — its schema, its atomic append, and reading the last one.

`<base>/_system/roles/{id}/log.jsonl`, one line per EXECUTED run:

    {"ts":"2026-07-28T07:00:11Z","role":"notion-sync","outcome":"ok",
     "writes":2,"reverted":[],"reported_only":[],"ms":41200,"note":null}

A role that was not due writes nothing. Logging a not-due skip would make
`last_run` the most recent tick and freeze every cadence longer than the
tick interval — verbatim the failure the cadence module exists to prevent.

One `outcome` field with three values, three real outcomes: `ok` (did work),
`idle` (the role's own check found nothing to do), `error`. There is
deliberately no separate `gate` field: whether the role found work is
knowledge only the model has, so the role reports it in its structured
return, the tick reads it, and the tick folds it into `outcome`.

`ts` is injected and stored in UTC — never read from the clock in here, and
never stored local, because the cadence arithmetic converts it back to the
owner's zone and needs a known origin.

The file is written UTF-8 with `ensure_ascii=False` and LF endings pinned.
A Cyrillic `note` raising `UnicodeEncodeError` would leave the run unlogged,
`last_run` at `None`, and the role re-running every tick forever; CRLF
translation on Windows would do the same to the byte-level contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# `ts` wire format. Both the writer and the reader below own it, so nothing
# else has to know how a run timestamp is spelled.
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

OUTCOMES = ("ok", "idle", "error")

# The keys a line must carry before it counts as a run line. A JSON object
# that happens to be well-formed but is not a run line is skipped like any
# other corruption.
REQUIRED_FIELDS = ("ts", "outcome")


def format_ts(ts: datetime) -> str:
    """Render an injected timestamp as UTC ISO-8601 with a `Z`."""
    if ts.tzinfo is None or ts.utcoffset() is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime(TS_FORMAT)


def parse_ts(value: str) -> datetime | None:
    """Read a `ts` back into an aware UTC datetime, or `None` if unusable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def append_run(
    cfg,
    *,
    ts: datetime,
    outcome: str,
    writes: int,
    reverted: list,
    reported_only: list,
    ms: int,
    note: str | None,
) -> None:
    """Append one run line to this role's log, creating the role dir if new."""
    entry = {
        "ts": format_ts(ts),
        "role": cfg.id,
        "outcome": outcome,
        "writes": int(writes),
        "reverted": list(reverted),
        "reported_only": list(reported_only),
        "ms": int(ms),
        "note": note,
    }
    path: Path = cfg.log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def last_run(cfg) -> dict | None:
    """The most recent parseable run line, or `None`.

    Scans backwards and skips anything unparseable. A corrupt trailing line
    must never make a role undue forever, so corruption costs the tick one
    line of history and nothing more.
    """
    path: Path = cfg.log_path
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in reversed(text.splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and all(key in entry for key in REQUIRED_FIELDS):
            return entry
    return None
