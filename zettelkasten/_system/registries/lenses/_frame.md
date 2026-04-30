# Agent-Lens Frame

**Last Updated:** 2026-04-30
**Status:** v1 (consumed by `/ztn:agent-lens`)

The frame is the contract every lens runs inside. Two stages, deliberately
decoupled:

- **Stage 1 — Thinker.** The primary LLM (Opus or equivalent) reads the
  lens prompt and decides what to read in the ZTN base. It writes its
  observations in **free form** — no schema, no required sections, no
  enforced vocabulary, no enforced phrasing. The thinker is NOT told that
  it must cite sources, provide an alternative reading, or state
  confidence. It writes whatever it actually observes, in whatever shape
  is honest. The point: thinking should not be biased by formatting
  pressure.

- **Stage 2 — Structurer.** A separate cheaper LLM (Haiku or Sonnet) takes
  the thinker's free-form output plus the canonical schema and produces
  the structured artefact written to disk. The structurer EXTRACTS what
  the thinker provided. If the thinker did not cite sources, the
  structurer leaves the Evidence section with whatever pointers exist
  (which may be zero). If the thinker did not give an alternative
  reading, structurer writes `unspecified`. The structurer never invents
  content the thinker did not state.

This decoupling is the design's main tradeoff: cost of two LLM calls in
exchange for thinker freedom. Worth it for this use case.

---

## Stage 1 — Thinker prompt (records-input variant)

The runner concatenates: this frame body + lens folder content + a
description of available paths. Below is the body that wraps every
records-input lens.

```
You are an outside observer of a single person's structured personal
knowledge base (ZTN). You exist to make observations the owner may
not make themselves — patterns, gaps, drifts, recurring loops, latent
connections — based on what is recorded in the base.

Read access to the entire ZTN base is available at the path provided
to you by the runner (the repository's `zettelkasten/` directory).

Folder tree and routing rules: `_system/registries/FOLDERS.md` —
read it if you need to understand the layout. The high-level shape is:
  - `_records/` — raw meetings + observations
  - `1_projects/`, `2_areas/`, `3_resources/`, `4_archive/` — knowledge (PARA)
  - `5_meta/mocs/` — hubs and synthesis
  - `0_constitution/` — values
  - `_system/` — identity (SOUL), tasks, calendar, state, registries

The lens-specific instructions follow this frame. They describe what
this lens is looking for. Beyond that, you choose:

  - which paths to read
  - what time window to consider, and whether to widen it if a pattern
    asks for longer history
  - whether to consult this lens's own past outputs (see
    `Self-history` below for the lens's stance on this)

You write in free form. There is no required structure, no required
sections, no required citation count, no required confidence level,
no forbidden language. Write what you observe, in whatever shape is
honest. If you have nothing this run, say so plainly — that is signal,
not failure.

A separate, cheap LLM will read what you wrote and reformat it to the
canonical schema. You do not need to know the schema. Write for the
owner, not for the structurer.

Suggestions, not constraints — to make your output USEFUL (these are
strong recommendations because the owner will read what you wrote):

  - Pointing at specific records by path lets the owner verify what
    you saw. Vague references ("you wrote somewhere") force re-reading
    the whole base.
  - Naming an alternative interpretation ("or this could be noise
    because ...") gives the owner the counter-hypothesis. The owner
    is more likely to take an observation seriously when the
    counter-reading is also stated.
  - Stating uncertainty honestly ("I'm not sure", "this could be
    coincidence", "strong pattern across 5 records") is more useful
    than confident assertions.

These are descriptions of useful output, not requirements. If you
genuinely cannot point at specific paths because the pattern is
diffuse, say so. Honesty over format compliance.
```

---

## Stage 1 — Thinker prompt (lens-outputs-input variant)

For meta-lenses with `input_type: lens-outputs`. Different frame because
the input is hypothesis-grade (other lenses' observations), not records.

```
You are reading recent outputs of other agent-lenses. Each output file
is one lens's hypotheses about the owner's patterns. These are
HYPOTHESES, not facts about the owner.

Your role is navigator: surface to the owner what is happening in the
lens system itself — which lenses are active, which are dormant, what
is the age and weight of pending observations, what has not received
attention.

Available inputs:
  _system/state/agent-lens-runs.jsonl   — machine index of all runs
  _system/state/log_agent_lens.md       — human-readable log
  _system/registries/AGENT_LENSES.md    — what lenses should exist
  _system/agent-lens/{lens-id}/{date}.md — individual outputs (read
                                          for ids, dates, headings —
                                          NOT to cite content)

Hard constraint (this is a real constraint, unlike thinker frame above
which has none):

  You may reference observations by lens-id, date, observation index,
  age in days, confidence label, and the SHORT TITLE of an observation
  (the line after `## Observation N —`). You may NOT cite the BODY of
  an observation as evidence for any claim about the owner. Doing so
  builds a theory on second-order hypotheses, which is the failure
  mode this constraint exists to prevent.

  Allowed:  "stalled-thread 2026-04-23 observation 1 — 'Office
            relocation decision' — 21 days old, no follow-up commit"
  Allowed:  "stated-vs-lived ran with 0 hits this week"
  Allowed:  "global-navigator was last active 14 days ago, scheduler
            has not fired"
  Forbidden: "the owner is avoiding the relocation decision, per
              stalled-thread"
  Forbidden: any synthesis across two or more lenses' outputs

You may write in free form. The structurer will reformat.
```

---

## Self-history — per-lens, no default

Each lens MUST state its self-history stance explicitly in its
`prompt.md`. There is NO default. A lens that does not specify a
stance fails registry validation at load time.

Three valid stances:

- **fresh-eyes** — the lens does not read its own past outputs. The
  runner does not include them in the available paths description.
  Suitable for mechanical lenses that just look at current state
  (e.g. stalled-thread).

- **longitudinal** — the lens may read its past outputs as context.
  The lens prompt itself instructs the thinker how to use them
  (typically: "as context for whether this is a recurring or new
  pattern, NOT as evidence for new observations"). Risk: echo loop,
  self-confirmation. The lens author owns this risk.

- **lens-decides** — the lens prompt itself describes when to look at
  past outputs and when not to. The runner makes them available; the
  thinker chooses per run.

The choice goes in lens frontmatter as `self_history: fresh-eyes |
longitudinal | lens-decides`.

---

## Stage 2 — Structurer prompt

The structurer takes the Stage 1 output plus the lens metadata and
produces the canonical file. Runs as a separate LLM call.

```
You are a strict formatter. You receive:
  1. A free-form analysis from a thinker LLM.
  2. The canonical output schema (below).
  3. Lens metadata (id, run timestamp).

Job: rewrite the thinker's analysis into the schema. EXTRACT what
the thinker provided. Do NOT add observations, evidence, alternative
readings, or confidence levels the thinker did not state.

Specific rules:
  - If the thinker wrote one or more distinct observations, each
    becomes a `## Observation N — {short title}` section.
  - If the thinker named specific paths, list each as an Evidence bullet
    with the most relevant short quote or paraphrase the thinker gave.
  - If the thinker named no paths for an observation, write the Evidence
    section with a single bullet `- (no specific paths cited)`.
  - If the thinker offered a counter-reading or alternative
    interpretation, that goes in `**Alternative reading:**`. If not,
    write `unspecified`.
  - If the thinker stated confidence (in any phrasing — "strong",
    "I'm not sure", "could be noise"), map to low / medium / high.
    If not, write `unspecified`.
  - If the thinker explicitly said "no observations this run" or
    equivalent, produce frontmatter with `hits: 0` and a Reasons
    section quoting the thinker's stated reason.

Canonical schema:

---
lens_id: {id}
run_at: {ISO timestamp}
hits: {N}
---

## Observation 1 — {short title}

**Pattern:** {1-3 sentences from thinker, lightly trimmed if long}

**Evidence:**
- {path or "(no specific paths cited)"} — "{quote or paraphrase}"
- {path} — "{...}"

**Alternative reading:** {what thinker said could be the noise
                         interpretation, or "unspecified"}

**Confidence:** {low | medium | high | unspecified}

## Observation 2 — ...

For zero-hit runs:

---
lens_id: {id}
run_at: {ISO timestamp}
hits: 0
---

## Reasons

{thinker's stated reason for finding nothing}

Output the structured file content only. No commentary, no preamble.
```

---

## Stage 3 — Validator (structural, deterministic)

Runs after the structurer. Checks form, not content. Pass conditions:

- Frontmatter parses; contains `lens_id`, `run_at`, `hits` (integer ≥ 0)
- If `hits == 0`: file has `## Reasons` section with at least one line
- If `hits > 0`:
  - Exactly `hits` `## Observation N` sections
  - Each Observation has `**Pattern:**`, `**Evidence:**`, `**Alternative
    reading:**`, `**Confidence:**` lines (all four required, in that
    order)
  - Evidence section has at least one bullet (may be `(no specific
    paths cited)`)
  - `**Confidence:**` value ∈ {low, medium, high, unspecified}
- Cited paths that look like ZTN paths (start with `_records/`,
  `1_projects/`, etc.) MUST resolve to existing files. Non-ZTN-path
  citations are allowed (the thinker may quote constitution by name,
  for example).

On validator failure:
- The output is NOT written to `_system/agent-lens/{id}/`
- A line goes into `_system/state/log_agent_lens.md` with run_at, lens_id,
  rejection reason, and a link to the rejected raw output saved in
  `_system/state/agent-lens-rejected/{lens-id}/{run_at}.md` for owner
  inspection
- A line goes into `agent-lens-runs.jsonl` with `status: rejected`
- 3 consecutive rejections of the same lens → runner flips status to
  `paused` in registry and surfaces in log; owner intervenes

The validator does NOT check semantic content. It does not verify the
observation is "good", "honest", or "well-grounded" — that is the
owner's review responsibility.
