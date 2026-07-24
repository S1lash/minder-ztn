#!/usr/bin/env python3
"""Mandate authorization for an outward ACT (CONTRACT §1.2/§6.2, DOCTRINE INV-16).

A role acts on the world ONLY under an owner-granted, live, scoped mandate. This
module is the deterministic gate the writer (`roles_persist` → `roles_act`) consults
before any act: it never trusts the body's claim that an act is allowed — it checks
the act against `RoleConfig.mandate` and refuses (surface, don't guess) when:

  - the role has NO mandate (a read-only role never acts);
  - the mandate is EXPIRED (`until` < today — re-consent required);
  - no `MandateTarget` in `scope` matches the act's `tool` AND `surface` (the mandate
    names the SPECIFIC external target the role may write to — INV-16; a role cannot
    write a surface the owner did not scope).

The matched `MandateTarget` carries the `mode` (`read-modify-write` — the safer,
idempotent shape) and `blast` (`bounded` = the injection-firewall exemption per INV-17)
forward, so the caller enforces rmw + the firewall gate against the OWNER-granted
target, not a body-chosen one. Read-source ⊥ write-target: this gate never binds a
source to a target (INV-16) — it only authorizes the write side.

Pure, deterministic, no LLM, no network. Cross-platform (`date` only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from roles_common import MandateSpec, MandateTarget


@dataclass(frozen=True)
class MandateDecision:
    """The outcome of authorizing one act against a role's mandate.

    `allowed` gates the act. `target` is the matched `MandateTarget` (its `mode` /
    `blast` drive rmw + the firewall exemption) on success, else None. `reason` is the
    honest refusal detail for the run log + a CLARIFICATION (never silent)."""
    allowed: bool
    target: MandateTarget | None = None
    reason: str = ""


def mandate_is_live(mandate: MandateSpec | None, today: date) -> bool:
    """True when the mandate exists and has not expired (`until` absent or ≥ today).

    An absent `until` is an open-ended mandate (owner choice); a set `until` past
    today is expired — the runner refuses acts until the owner re-consents."""
    if mandate is None:
        return False
    if not mandate.until:
        return True
    try:
        return date.fromisoformat(mandate.until) >= today
    except (ValueError, TypeError):
        # A malformed `until` is treated as EXPIRED (fail-closed — never authorize an
        # act on an unparseable expiry; the config loader validates the ISO shape, so
        # this is a defensive belt).
        return False


def authorize_act(
    mandate: MandateSpec | None, tool_id: str, surface: str, today: date,
) -> MandateDecision:
    """Authorize ONE act (a write to `tool_id` on `surface`) against the mandate.

    Deterministic + fail-closed: any missing/expired/out-of-scope condition REFUSES
    with an honest reason (never a silent allow). On success returns the matched
    `MandateTarget` so the caller enforces `mode`/`blast` against the owner-granted
    scope, not a body-supplied one."""
    if mandate is None:
        return MandateDecision(False, None, "role has no act mandate (read-only)")
    if not mandate_is_live(mandate, today):
        return MandateDecision(
            False, None, f"mandate expired ({mandate.until}) — owner re-consent required")
    tool_id = (tool_id or "").strip()
    surface = (surface or "").strip()
    if not tool_id or not surface:
        return MandateDecision(
            False, None, "act names no tool/surface — cannot authorize (surface, don't guess)")
    for target in mandate.scope:
        if target.target == tool_id and target.surface == surface:
            return MandateDecision(True, target, "")
    return MandateDecision(
        False, None,
        f"no mandate target for tool {tool_id!r} on surface {surface!r} — "
        f"the mandate scopes {[(t.target, t.surface) for t in mandate.scope]}")


def act_is_hitl(
    decision: MandateDecision, autonomy: str, ingested_external: bool,
    cage_verified: bool, autonomous_ack: bool = False,
) -> tuple[bool, str]:
    """Whether an authorized act must be owner-confirmed (staged) rather than executed
    in-tick (CONTRACT §6.1/§6.3, INV-15/16/17). Returns (hitl, reason).

    **Owner-accepted autonomy (the launch path).** A role the owner DIALED
    `autonomy: autonomous` executes acts in-tick with NO per-act confirm when the owner has
    set the explicit consent marker `ZTN_ROLES_AUTONOMOUS_ACK=1` (passed here as
    `autonomous_ack`) — with ONE reserved exception: the injection firewall still holds for
    an IRREVERSIBLE (non-`bounded`-blast) act on a tick that ingested external tool content
    (a confused-deputy irreversible act — an email/post whose content could be steered by
    injected external content — is the one thing even an autonomy-consenting owner
    confirms). Everything else runs hands-free: a `bounded` (reversible) act — the role's
    normal board reconcile / status update — always, and an irreversible act on a tick with
    NO external ingestion too. This marker is DISTINCT from `cage_verified`: `cage_verified`
    asserts a verified no-FS sandboxed body (which the harness does NOT have — never claim
    it when untrue); `autonomous_ack` asserts only the owner's informed consent to
    autonomous acting in the un-caged runtime.

    Otherwise HITL when ANY holds (honest disjunction, engine-computed — never a body
    flag):
      - the body cage is not verified AND no autonomous-ack — the emission/act stays
        owner-confirmed in the honor-system harness;
      - the mandate autonomy is `advisory` (the owner chose surface-then-act) — an
        advisory role ALWAYS stages, even if the ack marker is set globally: the
        per-role dial decides, the marker only unlocks `autonomous`-dialed roles;
      - the injection firewall fired AND the act's blast is not `bounded` (a bounded
        rmw to the fixed staging surface is firewall-exempt — INV-17; `open` never is).
        This branch is reached only on the future `cage_verified` path (defense in depth
        with a real sandbox); the `autonomous_ack` launch path above supersedes it.

    An unauthorized decision is not this function's concern (the caller refuses first);
    called only after `authorize_act` allowed the act."""
    target = decision.target
    if target is None:  # defensive — never HITL-decide an unauthorized act
        return True, "act not authorized"
    # Owner's explicit autonomous acceptance — full autonomy on this owner-granted
    # mandate. Distinct from cage_verified (see docstring). The owner's consent relaxes the
    # cage + advisory gates — BUT the injection firewall HOLDS for an IRREVERSIBLE
    # (non-`bounded`-blast) act on a tick that ingested external tool content. That single
    # combination — a confused-deputy irreversible act (an email/post whose content could
    # be steered by injected external content) — is the one case even an autonomy-consenting
    # owner confirms. A `bounded` (reversible) act — the role's normal board reconcile /
    # status update, undoable — runs hands-free even under external ingestion; and an
    # irreversible act on a tick that read NO external tool content also runs hands-free
    # (no injection vector). So the role's direct bounded work always executes; only the
    # genuinely dangerous "irreversible + fresh external content" combination stages.
    if autonomy == "autonomous" and autonomous_ack:
        if ingested_external and target.blast != "bounded":
            return True, ("autonomous consent given, but the injection firewall holds for "
                          "an irreversible (open-blast) act on a tick that read external "
                          "tool content")
        return False, ""
    reasons: list[str] = []
    if not cage_verified:
        reasons.append("body cage unverified (honor-system runtime)")
    if autonomy != "autonomous":
        reasons.append("mandate autonomy is advisory")
    if ingested_external and target.blast != "bounded":
        reasons.append("injection firewall fired and act is not bounded-blast")
    if reasons:
        return True, "; ".join(reasons)
    return False, ""


def autonomy_of(mandate: MandateSpec | None) -> str:
    """The mandate's autonomy dial (`advisory`/`autonomous`), or `advisory` when
    absent (fail-safe — never assume autonomous)."""
    return mandate.autonomy if mandate is not None else "advisory"


def resolve_surface(mandate: MandateSpec | None, tool_id: str) -> tuple[str | None, str]:
    """Derive the write `surface` for an act on `tool_id` from the mandate — never the
    body (the body says «close #1 on the board», the mandate says WHICH board — INV-16).

    Returns (surface, ""). Refuses (None, reason) when the mandate is absent, has NO
    target for the tool, or has MORE THAN ONE (ambiguous — surface, don't guess a
    board). A single matching target → its surface. This keeps the body from ever
    naming an out-of-scope surface: the writer picks only from the owner-granted scope."""
    if mandate is None:
        return None, "role has no act mandate"
    matches = [t for t in mandate.scope if t.target == tool_id]
    if not matches:
        return None, f"mandate scopes no surface for tool {tool_id!r}"
    if len(matches) > 1:
        return None, (f"mandate scopes {len(matches)} surfaces for tool {tool_id!r} — "
                      "ambiguous; the act must name one (surface, don't guess)")
    return matches[0].surface, ""
