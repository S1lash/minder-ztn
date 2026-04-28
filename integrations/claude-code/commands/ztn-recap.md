---
name: ztn:recap
description: Summarize current Claude Code session and save as raw source for Zettelkasten processing. Use at end of important sessions.
---

# /ztn:recap — Session Recap to ZTN

Summarize the current conversation and save it as a raw source file for later processing by `/ztn:process`.

## Arguments: $ARGUMENTS

Optional: topic override or extra tags. If empty, auto-detect from conversation.

## Execution

### 1. Analyze Current Session

Review the entire conversation and extract:
- **Main topic** — what was this session about (1-3 words for folder name)
- **Category** — Work / Career / Personal (can be multiple)
- **Key decisions** — what was decided and why
- **Work done** — code written, files created/modified, research completed
- **Insights & ideas** — non-obvious things learned or brainstormed
- **Tasks created** — any follow-ups or TODOs identified
- **People mentioned** — if any people were discussed
- **Projects touched** — which projects were worked on

### 2. Determine Metadata

- **Date**: today's date (YYYY-MM-DD)
- **Folder name**: `{YYYY-MM-DD}_{semantic-topic}` (e.g., `2026-04-01_ztn-skills-setup`)
- **Category tags**: based on content (#Work, #Career, #Personal, #AI, #Coding, etc.)

### 3. Create Raw Source File

**Path:** `{{MINDER_ZTN_BASE}}/_sources/inbox/claude-sessions/{folder_name}/transcript.md`

Create the directory and file.

**Format** (matches other raw_sources):

```markdown
# Claude Session: {Descriptive Title}

**Date**: YYYY-MM-DD
**Category**: {Work|Career|Personal}
**Tags**: #claude-session #tag1 #tag2
**Source**: Claude Code CLI session
**Project**: {working directory or project name}
**Duration**: ~{estimated duration}

---

## Summary

{2-3 sentence overview of the entire session}

## Key Decisions

- {Decision 1}: {rationale}
- {Decision 2}: {rationale}

## Work Done

- {What was accomplished — files, features, research}
- {Concrete outputs with paths if applicable}

## Insights & Ideas

- 💡 {Non-obvious insight or idea that emerged}
- 💡 {Another insight}

## Tasks & Follow-ups

- [ ] {Follow-up task 1}
- [ ] {Follow-up task 2}

## Key Exchanges

{3-5 most important moments from the conversation — paraphrased, not verbatim.
Focus on decisions, problems solved, and creative ideas.
Include enough context for ztn:process to create a rich ZTN note.}
```

### 4. Confirm

After creating the file:
- Show the file path
- Show a brief preview (first 10 lines)
- Remind: "Run `/ztn:process` in ZTN session to convert this into a Zettelkasten note"

## Important Rules

- **Language**: Content in the same language as the session (Russian if session was in Russian)
- **No verbatim dumps**: Summarize and structure, don't copy the entire conversation
- **Focus on value**: Only include what would be useful to find/recall later
- **Be honest about what happened**: Include failures, pivots, and dead ends — they have learning value
- **One file per session**: Even if session covered multiple topics, create ONE recap

## Examples

```
/ztn:recap
/ztn:recap workspace reorganization
/ztn:recap --tags #radar #refactoring
```
