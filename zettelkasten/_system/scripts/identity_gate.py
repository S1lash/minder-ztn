#!/usr/bin/env python3
"""Identity gate — run the per-identity residue scan and record that it ran.

Identity Contract Obligation 4 makes the proof of an identity change «a run of
the residue scan filtered to the identity being changed, and its exit code
recorded with the resolution». Recorded BY WHOM is the whole question. A model
that writes `residue_after: 0` into its own payload has recorded a claim; the
claim and the fact are indistinguishable afterwards, and the only thing that
would catch a wrong one is the next nightly recomputation — which happens after
the change has already been closed.

This script closes that gap and nothing else. It runs `identity_audit.py` as a
subprocess with the exact arguments it records, then appends one line to an
append-only log naming what was run, what it exited with, and the commit it ran
against. Lint's retirement-provenance scan then matches an archived resolution
against a line here rather than against a number that appeared in a payload.

**It is not a second scanner and holds no opinion of its own.** Every judgement
belongs to the audit; this passes the audit's exit code straight through, so a
caller can gate on this exactly as it would gate on the audit. The reason it is
a separate file rather than a `--record` flag is that the audit is read-only by
design and by documentation, and the one thing this does is write.

The log is `_system/state/identity-gate.jsonl` — append-only, owner-internal,
and immutable to the identity scan by the same rule that covers every other log
under `_system/state/`.

Exit status: the audit's, unchanged.
  0  no residue for this identity
  1  the identifier is unknown to every registry, or the scan could not run
  2  residue present

Usage:
    python3 identity_gate.py --identity old-project
    python3 identity_gate.py --identity old-project --root <base> --no-record
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import configure_std_streams, repo_root

GATE_LOG = ("_system", "state", "identity-gate.jsonl")


def _head(root: Path) -> str | None:
    """The commit the scan ran against, or None when there is no git here.

    Recorded because an exit code is only meaningful against a tree state: the
    same identity is clean and dirty at different commits, and a line that does
    not say which is not evidence of anything.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8",
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def run_gate(root: Path, identity: str) -> tuple[int, dict]:
    """`(exit_code, record)` — the audit's verdict for one identity.

    The command recorded is the command run, not a reconstruction of it: the
    subprocess exists so that the two cannot drift apart.
    """
    script = Path(__file__).resolve().parent / "identity_audit.py"
    argv = [
        sys.executable, str(script), "--root", str(root),
        "--identity", identity, "--report", "--json", "--fail-on-residue",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True, encoding="utf-8",
    )
    result: dict = {}
    if proc.stdout.strip():
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            result = {}
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "identity": identity,
        "command": " ".join(["identity_audit.py"] + argv[2:]),
        "exit_code": proc.returncode,
        "head": _head(root),
        "residue_count": result.get("residue_count"),
        "surface_residue_count": result.get("surface_residue_count"),
        "identity_known": result.get("identity_known"),
        "clean": result.get("clean"),
        # `clean` alone cannot tell a scanned identity from one no scan covers
        # — both are `true` with zero residue. The scope is what makes the
        # recorded line mean something a year later.
        "identity_scope": result.get("identity_scope"),
    }
    if proc.returncode not in (0, 2):
        # Recorded rather than swallowed: «the scan could not run» is a
        # different state from «the scan found nothing», and a resolution
        # closed on the first one is closed on nothing at all.
        record["error"] = (proc.stderr or "").strip()[:400]
    return proc.returncode, record


def append_record(root: Path, record: dict) -> Path:
    path = root.joinpath(*GATE_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    # Newline written explicitly and the file opened in binary: a text-mode
    # append turns "\n" into CRLF on Git Bash, and half the lines of a shared
    # log would then differ by platform.
    with path.open("ab") as fh:
        fh.write(line.encode("utf-8"))
    return path


def main(argv: list[str] | None = None) -> int:
    configure_std_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", required=True, metavar="ENTITY-ID")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--no-record", action="store_true",
        help="run the scan and print the verdict without appending to the log",
    )
    args = parser.parse_args(argv)

    root = args.root or repo_root()
    if not root.exists():
        print(f"ERROR: root does not exist: {root}", file=sys.stderr)
        return 1

    code, record = run_gate(root, args.identity)
    if not args.no_record:
        append_record(root, record)
    print(json.dumps(record, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
