---
name: ztn:check-content
description: >
  Review content candidates from ZTN notes by scanning frontmatter dynamically,
  cluster by theme and content_type, handle multi-angle notes, detect convergence,
  generate ready-to-post drafts, and maintain CONTENT_OVERVIEW.md as bird's-eye view.
  Companion mode with motivational nudges to help overcome publishing friction.
disable-model-invocation: false
---

# /ztn:check-content — Content Pipeline Review & Draft Generator

Review notes with `content_potential`, manage the content pipeline,
and generate publication-ready drafts.

**Philosophy:** Lower the barrier from "idea exists" to "post is published."
The user has the insights — this skill removes friction and provides momentum.

**Data model:** Content candidates live in note frontmatter:
- `content_potential: high|medium` — level of public sharing value
- `content_type: expert|reflection|story|insight|observation` — dominant note type (single)
- `content_angle: string | [array]` — one or more hooks for potential posts

There is no separate candidate registry — this skill discovers candidates
dynamically by scanning knowledge notes. Results are cached in
`_system/views/CONTENT_OVERVIEW.md` (read-only, auto-regenerated).

## Arguments

`$ARGUMENTS` supports:
- (no args) — full pipeline review: scan, cluster, suggest top drafts
- `--draft <topic>` — generate a ready-to-post draft for a specific topic
- `--cluster` — re-cluster all candidates by theme
- `--stats` — show pipeline statistics only
- `--type <type>` — filter by content_type (expert|reflection|story|insight|observation)

---

## Step 1: Load Context

Read these files (in parallel):
1. `{{MINDER_ZTN_BASE}}/_system/POSTS.md` — published history (avoid repeats)
2. `{{MINDER_ZTN_BASE}}/5_meta/PROCESSING_PRINCIPLES.md` — values profile for tone calibration

Note the date of last published post. This informs companion mode messaging.

---

## Step 2: Scan All Candidates

Grep knowledge notes for `content_potential:` in frontmatter across:
- `1_projects/`
- `2_areas/`
- `3_resources/`

For each match, read note frontmatter and extract:
- `content_potential`, `content_type`, `content_angle`, `title`, `id`, `tags`, `domains`, `created`

**Handling content_angle:**
- If string → treat as single-element list: `["the angle"]`
- If array → use as-is: `["angle1", "angle2", ...]`
- If missing → read first content section to infer angle, flag as "incomplete markup"

**Multi-angle notes** get indexed multiple times — once per angle. This means a single
note can appear in multiple theme clusters. For example, a `reflection` note with angles
`["Childhood perfectionism → adult control", "Why delegation is hard for tech leads"]`
lands in both "Psychology & Personal Growth" and "Career & Leadership" clusters.

Check against POSTS.md published list — skip already published.

If 0 total candidates:
  - Report: "No content candidates found. Run `/ztn:process` to populate."
  - Skip to Step 6 (report only)

---

## Step 3: Cluster Analysis

### 3.1 Theme clustering (primary axis)

Cluster ALL candidate-angle pairs by theme. Theme is determined by a combination
of `tags`, `domains`, angle text, and note content:

- Career & Leadership
- AI & Technology
- Technical & Architecture
- Psychology & Personal Growth
- Business & Product Ideas
- Organizational & Management
- Life & Lifestyle
- (dynamic — create new clusters as needed based on actual content)

A multi-angle note appears in multiple clusters — this is intentional.

### 3.2 Secondary grouping by content_type

Within each theme cluster, group by `content_type`. This helps identify
the right tone and platform for draft generation:
- `expert` notes → professional/technical angle
- `reflection` notes → personal/vulnerable angle
- `story` notes → narrative arc
- `insight` notes → counter-intuitive hook
- `observation` notes → seed for development

### 3.3 Convergence detection

For each theme cluster:
1. **Count** unique notes and angles (high vs medium)
2. **Convergence check:** Do multiple notes point to the same angle/story?
   - 2+ high-potential notes on a coherent topic = "ready cluster"
   - A single note with 2+ angles also shows "internal convergence" — multiple
     facets of the same topic are already articulated
3. **Rank** clusters by readiness: `convergence × count × avg_potential`
4. **Flag** top 3 ready-to-draft topics

---

## Step 4: Generate Drafts

If `--draft <topic>` specified but no matching cluster found:
  - Search all knowledge notes by topic keyword
  - If matches found: create ad-hoc cluster and proceed
  - If no matches: report "No matching content found for '{topic}'"

For ready clusters (or if `--draft <topic>` specified):

1. **Read ALL source notes** in the cluster (full content, not just frontmatter)

2. **Determine platform** — consider BOTH `content_type` and the specific angle:
   - Same note, different angles → can produce drafts for different platforms
   - `expert` + technical/career/AI angle → LinkedIn (English)
   - `reflection` + psychology/personal angle → Telegram (Russian)
   - `story` → career angle → LinkedIn; personal angle → Telegram; universal → both
   - `insight` → professional angle → LinkedIn; personal angle → Telegram
   - `observation` → Telegram (lightweight, personal channel)
   - When a multi-angle note appears in a cluster: use the SPECIFIC angle
     that placed it in this cluster, not all angles

3. **Generate draft** following Content Strategy from POSTS.md:
   - **LinkedIn:** 1000-1500 chars, professional tone, clear structure,
     end with a question or call-to-reflection, 5-7 hashtags
   - **Telegram:** Storytelling format, can be longer, personal vulnerable tone,
     Russian language, can include incomplete thoughts
   - **Instagram:** Visual-first, short caption, lifestyle angle

4. **Save draft** to `{{MINDER_ZTN_BASE}}/6_posts/drafts/YYYYMMDD-draft-{topic-slug}.md`
   (Create `6_posts/drafts/` directory if it doesn't exist)
   with frontmatter:
   ```yaml
   ---
   draft_for: "{topic}"
   content_type: "{dominant type}"
   platform: linkedin|telegram|instagram|both
   angle_used: "{the specific angle this draft is based on}"
   source_notes:
     - note-id-1
     - note-id-2
   status: draft
   created: YYYY-MM-DD
   ---
   ```

5. **Display draft** to user inline for immediate review/editing

---

## Step 5: Companion Mode

After analysis, provide motivational context:

1. **Progress reminder:** "You've published {N} posts. {N} candidates are waiting."
2. **Lowest-friction pick:** Suggest the single easiest draft to publish next,
   with reasoning: "This one is ready because you have 3 detailed source notes
   and the angle is clear."
3. **Capability proof:** Reference the user's own published posts as evidence
   they can do this: "Your Spring AI post worked well — this AI agents topic
   has even richer source material."
4. **Barrier acknowledgment:** "You mentioned hesitation about sharing.
   Remember: your ZTN has {N}+ notes of original thinking. That's not imposter
   syndrome — that's domain expertise looking for an outlet."
5. **Micro-action:** End with one concrete next step, not a menu:
   "Want me to generate the LinkedIn draft for '{topic}' right now?"

---

## Step 6: Generate CONTENT_OVERVIEW.md

Regenerate `{{MINDER_ZTN_BASE}}/_system/views/CONTENT_OVERVIEW.md` — an auto-generated
bird's-eye view of all content candidates. This file is:
- **Read-only** — never edited manually, always regenerated by this skill
- **A cache** — not source of truth (frontmatter is), but useful for quick reference
- **Human-readable** — designed for the user to scan and see their content landscape

Format:

```markdown
# Content Overview

> Auto-generated by `/ztn:check-content` — do not edit manually.
> Source of truth: `content_potential` / `content_type` / `content_angle` in note frontmatter.

**Generated:** YYYY-MM-DD
**Candidates:** {N} total (high: {N}, medium: {N})
**Published:** {N} posts | **Days since last:** {N}

---

## By Type

| Type | Count | High | Medium |
|------|-------|------|--------|
| expert | {N} | {N} | {N} |
| reflection | {N} | {N} | {N} |
| story | {N} | {N} | {N} |
| insight | {N} | {N} | {N} |
| observation | {N} | {N} | {N} |

---

## Theme Clusters

### {Theme Name} ({N} notes, {N} angles)
{Convergence: ready / building / early}

| Note | Type | Potential | Angle(s) |
|------|------|-----------|----------|
| [[note-id]] | {type} | {high/medium} | {angle or first angle + "(+N more)"} |
...

### {Next Theme}
...

---

## Multi-Angle Notes ({N} notes with 2+ angles)

| Note | Type | Angles | Clusters |
|------|------|--------|----------|
| [[note-id]] | {type} | {N} angles | {cluster1}, {cluster2} |
...

---

## Ready to Draft (convergence detected)

1. **{topic}** [{type}] — {N} notes, "{best angle}"
2. **{topic}** [{type}] — {N} notes, "{best angle}"
3. **{topic}** [{type}] — {N} notes, "{best angle}"
```

---

## Step 7: Output Report

Output to user:

```
## Content Pipeline Report — YYYY-MM-DD

### Pipeline Stats
- Total candidates: {N} (high: {N}, medium: {N})
- By type: expert: {N}, reflection: {N}, story: {N}, insight: {N}, observation: {N}
- Multi-angle notes: {N} (contributing {N} additional angles)
- Ready clusters: {N}
- Drafts generated this session: {N}
- Days since last published post: {N}

### Top 3 Ready-to-Draft Topics
1. **{topic}** [{content_type}] — {N} source notes, {angle}
2. **{topic}** [{content_type}] — {N} source notes, {angle}
3. **{topic}** [{content_type}] — {N} source notes, {angle}

### Incomplete Markup ({N} notes)
{list of notes with content_potential but missing content_type/content_angle}

### Drafts Generated
{list with paths if any}

### CONTENT_OVERVIEW.md
Updated: {path}

### Next Action
{companion mode suggestion}
```

---

## Example Usage

```
/ztn:check-content
/ztn:check-content --draft "agentic commerce research"
/ztn:check-content --stats
/ztn:check-content --cluster
/ztn:check-content --type reflection
```
