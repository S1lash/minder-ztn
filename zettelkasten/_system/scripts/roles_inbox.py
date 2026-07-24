#!/usr/bin/env python3
"""The inbox door — a role emits into ZTN as a source (CONTRACT §4.2, INV-4/6/11/27).

A role writes into ZTN ONLY via the inbox or a CLARIFICATION (INV-4) — never a
direct record/knowledge/hub write. This module owns the emission-file mechanics
(SRP): where a role emission lands and its shape. The RAILS around it (opt-in,
grounding, budget, injection-firewall) live in `roles_persist._process_inbox_emissions`
(the writer-orchestrator); the CONSUMPTION is `/ztn:process` (the deterministic
decider — propose/dispose, INV-6/11), which classifies + folds the emission like
any source.

`roles` is registered ONCE as a source (SOURCES.md, layout `flat-md`), NOT per role —
every emitting role drops one file per emission DIRECTLY under `_sources/inbox/roles/`,
named `{role-id}--{date}-{hash}.md` (the role-id is in the filename AND the
non-strippable `source: role:{id}` frontmatter). Flat (one file = one item) so
`/ztn:process` folds it in generically with NO process change — the contract's
illustrative `{role-id}/{ts}.md` nesting is ambiguous for the `flat-md`/`dir-per-item`
layout vocabulary (a role-id folder would hold many emissions), so the flat shape is
the robust equivalent that honours «register once, process-generic». The emission is a
HUMAN-PHRASED note (INV: role = colleague, human approach); `source: role:{id}` is
excluded from the role's OWN corpus + triggers (INV-27).

Deterministic, cross-platform (`pathlib`, atomic write, LF). No LLM.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from _common import system_dir

# The single source id under which every role emits (registered once in SOURCES.md).
ROLES_SOURCE_ID = "roles"


def roles_inbox_root(base: Path | None = None) -> Path:
    """`_sources/inbox/roles/` — the whitelisted `flat-md` source `/ztn:process` scans."""
    return system_dir(base).parent / "_sources" / "inbox" / ROLES_SOURCE_ID


def _emission_filename(role_id: str, run_at: str, text: str) -> str:
    """A deterministic, portable, collision-resistant filename:
    `{role-id}--{date}-{hash8}.md`.

    Flat (files directly under `inbox/roles/`) so `/ztn:process` reads it as a
    plain `flat-md` item. Content-hashed so re-emitting the SAME text in the same
    tick is idempotent (overwrites, never piles a duplicate). No colons (Windows-
    safe) — `is_portable_name`-clean."""
    date = str(run_at)[:10] or "undated"
    digest = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:8]
    return f"{role_id}--{date}-{digest}.md"


def _yaml_bool(value: bool) -> str:
    return "true" if value else "false"


def render_emission(
    role_id: str, text: str, evidence: Iterable[str], is_sensitive: bool, run_at: str,
) -> str:
    """Render the emission markdown: `source: role:{id}` frontmatter + human-phrased
    body + a `Grounded in:` provenance line. The `source` is non-strippable metadata
    (INV-11 provenance) a human/downstream MAY discount but that `/ztn:process` judges
    like any source."""
    refs = [str(e).strip() for e in evidence if str(e).strip()]
    grounded = "\n\nGrounded in: " + ", ".join(refs) if refs else ""
    return (
        "---\n"
        f"source: role:{role_id}\n"
        f"emitted_at: {run_at}\n"
        f"is_sensitive: {_yaml_bool(is_sensitive)}\n"
        "---\n\n"
        f"{text.strip()}{grounded}\n"
    )


def emission_path(role_id: str, run_at: str, text: str, base: Path | None = None) -> Path:
    """The deterministic target path for an emission (same content-hash as
    `write_emission` lands). Lets a caller check existence for crash-safe, idempotent
    budget accounting — a re-run whose file already exists must not be re-charged."""
    return roles_inbox_root(base) / _emission_filename(role_id, run_at, text)


def write_emission(
    role_id: str,
    text: str,
    evidence: Iterable[str],
    is_sensitive: bool,
    run_at: str,
    base: Path | None = None,
) -> Path:
    """Atomically drop one emission file under the role's inbox subdir. Returns the
    path written. The caller (the writer-orchestrator) has already checked the rails
    (opt-in, grounding, budget, firewall) — this only lands the file."""
    out_dir = roles_inbox_root(base)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / _emission_filename(role_id, run_at, text)
    body = render_emission(role_id, text, evidence, is_sensitive, run_at)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    tmp.replace(path)
    return path
