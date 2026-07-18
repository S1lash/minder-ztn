# Privacy & data ownership

Where your data lives, what travels where, what stays local. Read this
before deciding to put anything sensitive into ZTN.

## TL;DR

- **Your records, knowledge, constitution, registries** are text files
  in your git repo. They live on your machine (the working tree),
  plus the local `.git/` history, plus wherever you push the repo —
  typically a private GitHub repo you control. The engine itself
  never pushes; you do (via `/ztn:save` with your confirmation, or
  manually). Nothing else exfiltrates them.
- **Your transcripts** — local files in `_sources/inbox/` after you
  drop them in. **The source you used to record** (Plaud, voice memos,
  etc.) had its own data path before the file got to your inbox; ZTN
  starts where the file lands.
- **Claude Code agent calls** — text content is sent to Anthropic's
  API per their terms. This is how the engine "thinks". You consent
  per-skill-invocation; nothing fires without your action or a
  scheduler you set up.
- **Git pushes** — only when you (or `/ztn:save`, with your
  confirmation) push to a remote. The default remote is `origin` (a
  private repo you control). The engine never auto-pushes to
  `upstream` (the public skeleton).

If you stop running skills and stop pushing, the system is fully
quiescent — markdown files on disk, nothing else.

## Data layers and where they live

| Layer | Location | Travels where |
|---|---|---|
| Voice recordings (raw audio) | Wherever your recorder stores them (Plaud cloud, iCloud, etc.) | Determined by your recorder, not by ZTN. |
| Transcripts (text) | `_sources/inbox/<source>/` and after processing `_sources/processed/<source>/` | Local. Read by `/ztn:process`, sent to Anthropic API as part of the prompt during processing. |
| Records | `_records/meetings/`, `_records/observations/` | Local. Sent to Anthropic API when skills read them (every `/ztn:*` call loads relevant records into context). |
| Knowledge notes | `0_constitution/`, `1_projects/`, `2_areas/`, `3_resources/`, `5_meta/mocs/` | Same — local, sent to Anthropic API when skills read them. |
| Registries | `_system/registries/PEOPLE.md`, `PROJECTS.md`, etc. | Same. |
| Runtime state | `_system/state/` (logs, queues, candidate buffers, batches) | Same. |
| `audience_tags` and `is_sensitive` flags | Frontmatter on each note | Today: advisory. Engine respects them in views and lints. The slot exists; full automation around audience-aware redaction is on the roadmap, not active. |

## What "Anthropic API" means in practice

Every time you run `/ztn:process`, `/ztn:lint`, `/ztn:agent-lens`, or
any other skill, Claude Code:

1. Loads relevant ZTN files into the prompt context (records, system
   state, constitution, transcripts being processed).
2. Sends that prompt to Anthropic's API.
3. Receives the model's response.
4. Writes the response back to your filesystem (new records, updated
   indexes, etc.).

Anthropic's data handling for API calls is governed by their
[commercial terms](https://www.anthropic.com/legal/commercial-terms)
and their data retention policy. By default, prompts and completions
are not used for training. Confirm the current policy before sending
anything you would regret.

The engine does **not**:

- Send data to any other service (OpenAI, Google, etc.)
- Make outbound HTTP calls outside Anthropic's API and your configured
  git remote
- Run telemetry or analytics
- Have any "phone home" mechanism

The pipeline scripts under `zettelkasten/_system/scripts/` are pure
Python on your machine — no network calls.

## Git remotes — what gets pushed where

Your repo can have two remotes:

- **`origin`** — your private repo (the default. Created by
  `gh repo create my-ztn --private`).
- **`upstream`** — the public minder-ztn skeleton (engine source).
  Read-only direction: you pull engine updates *from* upstream, never
  push to it.

`/ztn:save` and `/ztn:sync-data` push to `origin` only. They never
touch `upstream`. If you have private records you don't want on a
remote at all, simply don't push — the system works fully offline.

## Sensitivity flags — what they do today

Every note's frontmatter carries a privacy trio:

- `origin: personal | work | external`
- `audience_tags: [private | public | family | team | ...]`
- `is_sensitive: true | false`

Today these are **advisory metadata**:

- `/ztn:lint` audits for missing or inconsistent values.
- Graph and search presets (`docs/obsidian.md` / `views.md`) include
  filters like "show only `is_sensitive: true`" for self-review.
- Hub views can be filtered by audience.

What they do **not** do today:

- Automatically redact sensitive content from prompts sent to Anthropic.
- Block git push of sensitive notes.
- Encrypt sensitive content at rest.

These are explicit design decisions to keep the slot in the schema
without overstating what the engine guarantees. If you want
encryption-at-rest for sensitive notes, use a tool outside ZTN
(e.g. git-crypt, age, or filesystem-level encryption) — they
compose cleanly with the markdown layout.

## Multi-device

If you sync the repo across devices (laptop, phone, desktop) via git,
your data is wherever you push it:

- Push to `origin` on a private GitHub repo: GitHub holds an
  encrypted-at-rest copy.
- Push to a self-hosted gitea/forgejo: you control the server.
- iCloud / Working Copy / Termius for mobile: the file moves through
  Apple/the SSH layer per their respective policies.

The engine doesn't care which transport you use; it only sees a git
repo on disk.

## What to do if you put something you regret into ZTN

1. **Filesystem level:** delete the file, run `git rm` if committed.
   The git history still has it. Use `git filter-repo` or
   `git rebase -i` + force-push to remove from history (destructive;
   confirm carefully).
2. **In Anthropic's logs:** Anthropic retains API logs per their
   policy (currently 30 days for abuse monitoring, no training use
   on commercial accounts). You cannot delete from their logs; you
   can only stop sending more.
3. **In your records pipeline:** if `/ztn:process` already wrote a
   record citing the regrettable content, edit the record, run
   `/ztn:save`. The engine never auto-rewrites your edits.

## The cognitive-model lens — profiling from your reflections

ZTN ships a `cognitive-model` lens that is **on by default**. Every other Monday
it reads your own reflections (solo voice-notes, journal-style observations) and
proposes principles about how you think and want to be communicated with. It
touches your most private content and writes inferences about you into your repo
(see **Produces** below), so it is worth understanding — but it never changes
your constitution on its own: it only *proposes* to a review buffer you control,
and you promote nothing you do not approve. That gate is why it is safe to ship
active platform-wide.

- **Reads:** your `_records/observations/` (and meetings) — the same content
  every records-lens already sees. It does not reach outside your repo.
- **Produces:** dated lens outputs under `_system/agent-lens/cognitive-model/`
  and proposed candidates in `_system/state/principle-candidates.jsonl` —
  inferences about you, in plain text, in your repo.
- **Never promotes on its own.** A candidate becomes a constitution principle
  only through `/ztn:lint` F.5 + your review. Highly-confident candidates may
  append to the review buffer without a click (tunable in
  `insights-config.yaml`); medium / low always wait for you. Set the class to
  `never_auto` to click every one.
- **Travels with your repo.** Like all your data, these inference files sync to
  `origin` on `/ztn:save` and are sent to the Claude API when a skill reads
  them. `is_sensitive` is advisory only (see above) — it does not redact. If a
  derived inference feels too personal to live in your git history, delete the
  lens output + candidate line and run `/ztn:save`.
- **Turn it off:** set the lens row to `status: draft` in
  `_system/registries/AGENT_LENSES.md`. It stops immediately; existing outputs
  stay until you delete them. Note the opt-out is not durable across updates — a
  later `/ztn:update` re-applies the platform default of `active`, so re-set it
  after updating if you want it permanently off.

The guard against this becoming a profiler that flatters you is the
no-sycophancy rule (in `communication-baseline`, and in your own constitution
where you keep one): the lens is instructed to model how you think, never to
mine for what comforts you.

## The personal-data linter — what stops your data from shipping publicly

If you ever contribute an engine change upstream (or just run the release
tooling locally), `scripts/check_no_personal_data.py` scans everything
that would ship to the public skeleton for your own identifying data. It
does not rely on a hand-maintained list you'd have to remember to update:
it derives its patterns at scan time from your own `PEOPLE.md`,
`PROJECTS.md`, `SOUL.md` Identity section, and every constitution
axiom/principle/rule's title and statement — so a coworker added to
`PEOPLE.md` last week, or a new project in `PROJECTS.md`, is automatically
covered the next time the linter runs. Known-public terms (the engine's
own placeholder examples, product names like `Minder`/`ZTN`) are excluded
so the linter never flags its own depersonalized documentation. This
derivation is local-only — it reads your registries to build regex
patterns and never sends that data anywhere; the scan itself only runs
against files bound for the public skeleton, never your private notes.

## Engine boundaries — what the engine is not allowed to do

Codified in `zettelkasten/_system/docs/ENGINE_DOCTRINE.md` (auto-loaded
into every Claude Code session). The contract:

- Never auto-create a knowledge profile in `3_resources/people/<id>.md`
  without surfacing the threshold-crossing → CLARIFICATION first.
- Never auto-promote a principle candidate to constitution. Owner gates.
- Never overwrite owner edits to SOUL.md / PEOPLE.md / PROJECTS.md /
  hub files. Re-runs add or surface, never rewrite.
- Never close an open thread silently.
- Never delete files from `_sources/`.

These hold across all skills. If you observe a violation, that's a bug.

## Questions

If you're considering putting something specifically sensitive into
ZTN and want to think it through, the right question is **"would I be
OK with this text appearing in a Claude API call?"** — that is the
boundary that matters.

For everything that's not "I would not want this in any API call ever"
— records of work, meetings, decisions, ideas, principles — the
system is designed for it.
