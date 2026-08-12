#!/usr/bin/env python3
"""The run line — its schema, its atomic append, and reading the last one.

`<base>/_system/roles/{id}/log.jsonl`, one line per EXECUTED run:

    {"ts":"2026-07-28T07:00:11Z","role":"notion-sync","outcome":"ok",
     "writes":2,"reverted":[],"reported_only":[],"ms":41200,"note":null}

A role that was not due writes nothing. Logging a not-due skip would make
`last_run` the most recent tick and freeze every cadence longer than the
tick interval — verbatim the failure the cadence module exists to prevent.

One `outcome` field, four real outcomes: `ok` (did work), `idle` (the role's
own check found nothing to do), `degraded` (it ran and delivered, but part of
its job could not be done), `error`. There is deliberately no separate `gate`
field: whether the role found work is knowledge only the model has, so the
role reports it in its structured return, the tick reads it, and the tick
folds it into `outcome`.

`degraded` exists because the honest failure of a standing role is not a
crash. A role whose external service runs out of quota mid-run still produces
most of its output and still returns successfully — it simply marks what it
could not verify. Logged as `ok`, that reads as a good night, and a quota that
runs out every night degrades the role's work silently and indefinitely. It is
its own value rather than an `error` because the run DID deliver: calling it a
failure would train the owner to ignore the word, and the tick's error paths
(revert, hold-back) do not apply to a run that behaved.

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

OUTCOMES = ("ok", "idle", "degraded", "error")

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
    """Append one run line to this role's log, creating the role dir if new.

    `outcome` is checked against `OUTCOMES` here, and this is the only place
    it can be. The vocabulary is closed because things downstream match its
    values exactly — the repeated-outcome probe compares two lines for the
    same word, the cadence reader distinguishes a run that happened from one
    that did not. A value outside the set would land in the log, read as a
    run, and match none of them: the role would look alive while every check
    over it silently found nothing. Better to refuse the line and let the tick
    report a broken write than to store one nothing can interpret.
    """
    if outcome not in OUTCOMES:
        raise ValueError(
            f"outcome {outcome!r} is not one of {OUTCOMES} — the vocabulary is "
            "closed because the probes over this log match its values exactly"
        )
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
