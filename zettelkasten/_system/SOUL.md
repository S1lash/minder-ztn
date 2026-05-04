---
id: soul
layer: system
modified: REPLACE_WITH_DATE
---

# SOUL

> Identity + Current Focus + Working Style + Active Goals.
> Maintained manually. Focus shift detection — suggestion in `/ztn:lint`.
>
> **Bootstrap:** `/ztn:bootstrap` interviews you and fills the sections below
> on first run. Edit freely afterwards. The Values auto-zone (between markers)
> is regenerated from `0_constitution/` and must not be hand-edited.

## Identity

- **Name:** {Your full name as you'd like agents to refer to you}
- **Role:** {Current professional role / occupation}
- **Location:** {City, Country}
- **Timezone:** {IANA tz, e.g. Europe/Berlin (UTC+1)}
- **Language:** {Primary language for notes; secondary for code/metadata}
- **Domain:** {Industry / domain expertise — one sentence}
- **Experience:** {Years + summary, optional}

## Values

> Free-form bullets — what you stand for, what trade-offs you make consciously.
> Used to calibrate skill behaviour (see `5_meta/PROCESSING_PRINCIPLES.md`
> Values Profile section).

- {Core value 1 — short statement + reason}
- {Core value 2 — ...}
- {Core value 3 — ...}

## Current Focus

> Derived from TASKS.md streams (density of last 4 weeks) + open threads.
> Split into **Work** and **Personal** to mirror TASKS.md sections.
> Refreshed by `/ztn:bootstrap` and reviewed manually.

### Work

- {Active focus area 1}
- {Active focus area 2}

### Personal

- {Active focus area 1}
- {Active focus area 2}

## Working Style

> How you prefer to operate — used by skills to align outputs with you.

- **Communication:** {Direct / structured / Socratic / ...}
- **Cadence:** {Async-first / sync-heavy / mixed}
- **Capture preference:** {Voice-first / written / mixed}
- **Review cadence:** {Daily / weekly / monthly}

## Active Goals

> Outcome-level goals (3-12 month horizon). Concrete tasks live in TASKS.md.

1. {Goal 1 — outcome statement}
2. {Goal 2 — ...}

## Values (auto-zone)

> Auto-rendered from `0_constitution/` core principles by
> `_system/scripts/render_soul_values.py`. Do NOT hand-edit between the
> markers — drift is detected and reported as CLARIFICATION.

<!-- soul-values:start -->
{populated by render_soul_values.py — empty until first principle lands}
<!-- soul-values:end -->
