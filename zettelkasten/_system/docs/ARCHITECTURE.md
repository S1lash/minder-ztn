# ZTN Platform Architecture

> Personal knowledge platform built on Zettelkasten + QMD + OpenClaw.
> Git-centric architecture. Designed for individuals or small groups
> (instance owner + optional collaborators with Plaud-style voice
> recorders).

**Related documents:**
- [CONVENTIONS.md](./CONVENTIONS.md) — documentation style rules для SKILL / system / spec files (binding)
- Constitution design rationale — folded into [CONSTITUTION.md §1](../../0_constitution/CONSTITUTION.md)

> **Note for forks/skeleton clones.** This document references roadmap
> and phase-scoped SDDs that live in the original instance owner's
> deployment journal (a `platform/` folder, not part of the engine).
> Those references are historical context for the architecture; they
> are not load-bearing for running the system.

---

## Table of Contents

1. [Philosophy & Key Decisions](#1-philosophy--key-decisions)
2. [Why Not Minder / GBrain / Khoj](#2-why-not-minder--gbrain--khoj)
3. [System Overview](#3-system-overview)
4. [Per-User Docker Stack](#4-per-user-docker-stack)
5. [Data Flow: Recording → Push Notification](#5-data-flow-recording--push-notification)
6. [ZTN Enhancements](#6-ztn-enhancements)
7. [QMD: Knowledge Search Layer](#7-qmd-knowledge-search-layer)
8. [OpenClaw: ztn-bridge Plugin](#8-openclaw-ztn-bridge-plugin)
9. [Proactive Context Injection](#9-proactive-context-injection)
10. [Multi-Platform MCP Access](#10-multi-platform-mcp-access)
11. [Reliability & Fallbacks](#11-reliability--fallbacks)
12. [Isolation & Security](#12-isolation--security)
13. [Resource Planning](#13-resource-planning)
14. [Risks & Open Questions](#14-risks--open-questions)
15. [Implementation Plan](#15-implementation-plan)

---

## 1. Philosophy & Key Decisions

### Core Principle: Git as Single Source of Truth

The entire knowledge base lives as markdown files in a git repository. There is no
separate database that mirrors or duplicates this data. Git provides versioning,
collaboration, and auditability. Everything else is a **lens** over these files.

### Architecture Layers

```
┌─────────────────────────────────────────────────┐
│  ACTION LAYER: OpenClaw + MCP integrations      │  Creates tasks, events, sends messages
│  (Slack, Calendar, ClickUp, Todoist, Telegram)  │
├─────────────────────────────────────────────────┤
│  SEARCH LAYER: QMD (hybrid search over files)   │  Indexes, searches, serves files
├─────────────────────────────────────────────────┤
│  PROCESSING LAYER: /ztn:process (Claude/Codex)  │  Classifies, atomizes, enriches notes
├─────────────────────────────────────────────────┤
│  STORAGE LAYER: Git repository (markdown files) │  Single source of truth
├─────────────────────────────────────────────────┤
│  CAPTURE LAYER: Plaud → Zapier → GitHub         │  Voice recording → transcript
└─────────────────────────────────────────────────┘
```

Each layer has a single responsibility. No layer duplicates another's work:
- **Capture** produces raw transcripts (no processing)
- **Storage** holds all data (no computation)
- **Processing** enriches data (writes to storage, doesn't store separately)
- **Search** indexes storage (read-only, no data duplication beyond index)
- **Action** executes on search results (no data storage of its own)

### Key Design Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|---|---|---|---|
| Knowledge store | Git + markdown | PostgreSQL (Minder), GBrain Pages | Git = versioning + collaboration + no sync issues |
| Search engine | QMD | GBrain, Khoj, raw grep | QMD indexes files in-place (no data duplication), serves original files, MCP built-in |
| Enrichment | /ztn:process (Claude) | GBrain signal-detector, custom agents | Battle-tested skill, 8 processing principles, 14-question classification |
| Action layer | OpenClaw | Custom agent, Claude Desktop only | Already deployed for 3 users, plugin system, MCP integrations, Telegram channel |
| Memory search | Voyage-3 (built-in) | QMD, Ollama, node-llama-cpp | Best quality, cost negligible (~$0.06/1M tokens), instance operator sponsors users |
| Trigger mechanism | Webhook + cron fallback | Cron only, webhook only | Webhook for speed, cron for reliability |
| Isolation | Docker per user | Process isolation, shared containers | Strongest isolation for personal data, already established pattern |

---

## 2. Why Not Minder / GBrain / Khoj

### Why Not Minder

Minder is a 12-agent cognitive backend with PostgreSQL + Neo4j + Qdrant + Redis + MinIO.
It was designed as a "smart brain" on top of ZTN but introduced:
- **Data duplication**: ZTN in git AND Minder in 3 databases
- **Sync complexity**: Changes in git need to be ingested into Minder
- **Operational overhead**: 5 databases + Java app + blue-green deployment
- **Scope creep**: 12 agents, concept graphs, multi-round processing — overkill for note search

ZTN + /ztn:process already does enrichment. Minder duplicates this with its own pipeline.
The platform works better with Minder removed entirely — not deferred, not optional, removed.

**What Minder did well (preserved in new architecture):**
- Proactive context injection → adopted in ztn-bridge plugin (same pattern from minder-openclaw-plugin)
- Entity extraction → already in /ztn:process
- Task/event tracking → moved to ZTN _system/ files + BATCH_LOG

### Why Not GBrain

GBrain (github.com/garrytan/gbrain) is a Postgres-native knowledge system with:
- 30+ MCP tools, hybrid search, entity extraction, timeline tracking
- Built for Postgres-centric architecture (Pages ingested into pgvector)

**Fundamental incompatibility**: GBrain ingests files into its own database. This creates
a second source of truth alongside git. Every file change requires re-ingestion and sync.
Using GBrain would mean replacing ZTN's git model, not augmenting it.

**GBrain features adopted as ZTN markdown structures:**
- SOUL.md (identity & state) → see Section 6
- Compiled Truth + Timeline dual model → see Section 6
- OPEN_THREADS.md (unresolved items) → see Section 6
- Tiered entity enrichment → see Section 6
- BATCH_LOG for processing audit → see Section 6

### Why Not Khoj

Khoj is a Python-based AI assistant with web UI, multi-user support, and MCP.
Rejected because:
- Data duplication (same problem as GBrain — ingests into own storage)
- Python stack adds operational complexity (different ecosystem from TypeScript/OpenClaw)
- Web UI is nice-to-have but users already have Claude Desktop / ChatGPT / Telegram
- Heavier resource requirements than QMD

### Why QMD

QMD (Query Markdown Documents) is a local-first search engine that indexes markdown
files **in-place** without duplicating data.

**Strengths:**
- Zero data duplication — SQLite index points at existing files
- Serves original files via `get`/`multi_get` tools (transcripts, summaries, notes)
- Hybrid search: BM25 full-text + vector semantic + LLM reranking
- MCP server with HTTP transport (Streamable HTTP for remote access)
- Incremental indexing via SHA-256 content hashing (fast re-index)
- Local models (~2GB) — no API cost for search
- TypeScript/Bun — same ecosystem as OpenClaw

**Weaknesses (acknowledged):**
- Local embedding model (embeddinggemma-300M) — quality on Russian text is unverified
- No write API (by design — correct for our architecture)
- No built-in file watching (solved by sync scripts)
- Single-user design (solved by per-user Docker containers)
- No background enrichment (not needed — /ztn:process handles this)

---

## 3. System Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL SERVICES                              │
│                                                                         │
│  Plaud ──→ Zapier ──→ GitHub repo (per user)                           │
│                          ↑ push (from /ztn:process via Codex)          │
│                          ↑ push (from OpenClaw session_end)            │
│                                                                         │
│  Claude Desktop ──→ QMD MCP (remote HTTPS) ──→ search/get ZTN notes   │
│  ChatGPT        ──→ QMD MCP (remote HTTPS) ──→ search/get ZTN notes   │
│  Claude Code    ──→ QMD MCP (remote HTTPS) ──→ search/get ZTN notes   │
│  Claude Mobile  ──→ QMD MCP (remote HTTPS) ──→ search/get ZTN notes   │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────── VPS (Zomro NL) ──────────────────────────┐
│                                                                         │
│  ┌─── Shared Services (host level) ──────────────────────────────────┐ │
│  │                                                                    │ │
│  │  Nginx: reverse proxy + SSL + per-user auth                       │ │
│  │    https://{user}-ztn.minder.host/mcp → QMD per user             │ │
│  │    https://{user}.minder.host → OpenClaw per user                 │ │
│  │                                                                    │ │
│  │  Trigger Service: GitHub webhook handler                          │ │
│  │    POST /webhook/github/{user} → route to sync or /ztn:process   │ │
│  │                                                                    │ │
│  │  /data/shared/qmd-models/ (~2GB, read-only mount to all QMD)     │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌─── Per-User Docker Stack (×6 users) ──────────────────────────────┐ │
│  │  See Section 4 for details                                        │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Per-User Docker Stack

Each user gets a fully isolated Docker stack with its own network.

```
┌─────────────── Docker Network: {user}-net (isolated) ──────────────────┐
│                                                                         │
│  ┌─── Container: openclaw-{user} ──────────────────────────────────┐   │
│  │                                                                  │   │
│  │  OpenClaw agent (Claude Sonnet 4.5)                             │   │
│  │  Telegram channel (per-user bot)                                │   │
│  │  memory-core: Voyage-3 hybrid search (built-in)                 │   │
│  │                                                                  │   │
│  │  Plugins:                                                        │   │
│  │    ztn-bridge      → connects to QMD via localhost               │   │
│  │    mcp-integrations → Slack, Calendar, ClickUp, Todoist         │   │
│  │    telegram         → Telegram messaging                         │   │
│  │    lobster          → (existing)                                 │   │
│  │                                                                  │   │
│  │  State:                                                          │   │
│  │    /workspace/ztn-state.json (last_processed_batch_id)          │   │
│  │                                                                  │   │
│  │  Port: 18801 + user_offset (loopback)                           │   │
│  │  Memory limit: 2GB                                               │   │
│  │                                                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                           ↕ localhost:{qmd_port}                        │
│  ┌─── Container: qmd-{user} ──────────────────────────────────────┐   │
│  │                                                                  │   │
│  │  QMD HTTP daemon (Bun runtime)                                  │   │
│  │                                                                  │   │
│  │  Collections:                                                    │   │
│  │    ztn:    /data/zettelkasten/   (ZTN knowledge notes)          │   │
│  │    memory: /data/openclaw-memory/ (OpenClaw memory files)       │   │
│  │                                                                  │   │
│  │  Index: /cache/qmd/index.sqlite                                 │   │
│  │  Models: /models/ (read-only bind mount from shared)            │   │
│  │                                                                  │   │
│  │  Port: 8181 + user_offset (loopback, exposed via Nginx)        │   │
│  │  Memory limit: 1GB (models loaded on demand, 5-min idle timeout)│   │
│  │                                                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                           ↕ volume mount                                │
│  ┌─── Volume: {user}-data ─────────────────────────────────────────┐   │
│  │                                                                  │   │
│  │  /data/zettelkasten/        ← git clone of user's ZTN repo     │   │
│  │  /data/openclaw-memory/     ← OpenClaw memory files             │   │
│  │  /cache/qmd/                ← QMD SQLite index                  │   │
│  │                                                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Isolation Guarantees

- **Network isolation**: Each user has a dedicated Docker network (`{user}-net`).
  Containers in different networks cannot communicate.
- **Filesystem isolation**: Each user has a dedicated volume. No cross-user mounts.
- **Process isolation**: Docker provides PID namespace isolation.
- **Shared resources** (read-only only):
  - QMD models: bind-mounted as read-only (`/data/shared/qmd-models/:/models/:ro`)
  - No shared databases, no shared state, no shared indexes.

---

## 5. Data Flow: Recording → Push Notification

### End-to-End Timeline (Optimistic: ~4-8 minutes)

```
 0:00   User records voice on Plaud
          │
 1-3m   Zapier detects new recording (polling interval)
          │
 ~3m    Zapier → git commit → push transcript to GitHub
          │  _sources/inbox/plaud/{ISO-timestamp}/transcript_with_summary.md
          │
 ~3m    GitHub webhook ──→ VPS Trigger Service
          │                  Detects: new file in _sources/inbox/
          │                  Action: trigger Codex/Claude API → /ztn:process
          │
 ~5-7m  /ztn:process runs (Claude/Codex):
          │  1. Classify transcript (14-question LLM classification)
          │  2. Atomize into knowledge notes
          │  3. Resolve people (OntologyIndex — deterministic, no LLM)
          │  4. Create records in _records/meetings/ (kind: meeting) or _records/observations/ (kind: observation)
          │  5. Create knowledge notes in PARA folders
          │  6. Extract tasks → _system/TASKS.md
          │  7. Update _system/state/OPEN_THREADS.md (via /ztn:maintain post-batch)
          │  8. Update _system/views/HUB_INDEX.md, 3_resources/people/PEOPLE.md
          │  9. Write _system/state/batches/{batch_id}.md (markdown report per batch-format spec)
          │ 9a. Write _system/state/batches/{batch_id}.json (JSON manifest via emit_batch_manifest.py — Minder consumer contract per ARCHITECTURE.md §4.5)
          │ 10. Append row to _system/state/BATCH_LOG.md (markdown table)
          │ 11. git commit + push
          │
 ~7m    GitHub webhook (second) ──→ VPS Sync Service
          │  1. git pull (into /data/{user}/zettelkasten/)
          │  2. qmd update (incremental, SHA-256 change detection)
          │  3. qmd embed (only new/changed chunks)
          │  4. Read BATCH_LOG.md table, find new batch rows since last cursor
          │  5. POST system message → OpenClaw gateway API
          │
 ~8m    OpenClaw receives notification:
          │  "[ZTN] New batch: 1 record, 2 tasks, 1 event"
          │  Agent reads _system/state/batches/{batch_id}.md via ztn_get
          │  For each task → creates in ClickUp (via MCP)
          │  For each event → creates in Calendar (via MCP)
          │  Sends summary to user via Telegram
          │
 ~8m    User receives push notification:
          ╔══════════════════════════════════════════╗
          ║  Обработал запись встречи с Петей:       ║
          ║  • 2 задачи → добавлены в ClickUp       ║
          ║  • Встреча в пятницу → в календаре       ║
          ║  • Обновил профиль Пети                  ║
          ╚══════════════════════════════════════════╝
```

### Session End Flow (OpenClaw → ZTN)

```
OpenClaw session ends
  → session_end hook fires in ztn-bridge plugin
  → Plugin extracts session summary from transcript
  → Writes to: /data/{user}/zettelkasten/_sources/inbox/openclaw/{ISO-timestamp}/transcript.md
  → git add + commit + push
  → GitHub receives new file → triggers /ztn:process (same pipeline as Plaud)
  → Session becomes a ZTN source, processed like any other recording
```

---

## 6. ZTN Enhancements

Markdown structures built into ZTN для dogfooding + friend rollout. Детальные
форматы, шаблоны, правила — см. phase-specific SDDs.

### 6.1 Ключевые принципы

- **Markdown-first.** Все форматы — markdown с YAML frontmatter. JSON не используется — markdown лучше для LLM-скиллов + git diff + human review.
- **Backward compatibility.** Новые файлы не ломают существующие. Новые поля frontmatter опциональные.
- **CLARIFICATIONS safety valve (hard rule).** При confidence < threshold скилл пишет вопрос в `_system/state/CLARIFICATIONS.md` вместо auto-decision. Применяется ко всем скиллам (bootstrap, process, maintain, lint).
- **Локальный эталон до VPS.** Knowledge pipeline доводится до эталона на локальной машине (dogfooding 1+ месяц), FREEZE GATE — только потом VPS/QMD/plugin/friends.

### 6.2 Системные файлы

| Файл | Назначение | Заполняет | Поддерживает |
|---|---|---|---|
| `_system/SOUL.md` | Identity + Current Focus + Working Style | bootstrap + вручную | lint (focus drift suggestions) |
| `_system/state/OPEN_THREADS.md` | Незакрытые темы (отличается от TASKS — это ожидания/вопросы, не действия) | bootstrap + maintain | maintain + lint |
| `_system/views/CURRENT_CONTEXT.md` | Live state для thin orientation | bootstrap, maintain after-batch | maintain + lint |
| `_system/views/INDEX.md` | Surface catalog of knowledge + archive + constitution + hubs (faceted by PARA / domains / cross-domain); records and posts intentionally out of scope | bootstrap (Step 5.5), maintain after-batch (Step 7.6), regen_all.py — all via `_system/scripts/render_index.py` | maintain + lint A.6 (heartbeat) |
| `_system/state/log_maintenance.md` | Append-only audit maintain + bootstrap | maintain, bootstrap | lint (reads) |
| `_system/state/log_process.md` | Append-only chronological process log | process | lint, maintain (reads) |
| `_system/state/log_lint.md` | Append-only lint audit trail | lint | — |
| `_system/docs/batch-format.md` | Batch format contract — markdown report + JSON manifest; per-entity privacy trio + concept fields; sections `## Concepts Upserted` + `## Sensitive Entities` | manual | manual bump + migration |
| `_system/state/BATCH_LOG.md` | Markdown table, append-only index of batches | process | — |
| `_system/state/batches/{id}.md` | Full report per batch (frontmatter + structured sections) | process | — |
| `_system/state/lint-context/daily/` | 30-day rolling daily summaries | lint | — |
| `_system/state/lint-context/monthly/` | Append-forever monthly summaries | lint | — |

### 6.3 Модификации существующих файлов

- **`SYSTEM_CONFIG.md`** — source type registry, canonical Resolution-action vocabulary, CLARIFICATIONS format contract, cross-skill exclusion rules
- **`PEOPLE.md`** — колонки `Tier`, `Mentions`, `Last`, `Profile`; bootstrap расставляет tiers с нуля, process инкрементирует mentions (1-per-file), maintain suggests promote, lint auto-generates Tier 1 profile skeletons
- **Knowledge notes** — mandatory append-only секция `## Evidence Trail` (timeline источников эволюции знания). Не mutable, только append

### 6.4 Tiered Entity Enrichment

PEOPLE.md registry с mention counting и tier'ами:
- **Tier 3 (stub):** 1-2 mentions → одна строка в PEOPLE.md с контекстом первого упоминания
- **Tier 2 (basic):** 3-7 mentions → расширенная строка с ролью и проектами
- **Tier 1 (full):** 8+ mentions → отдельный профиль в `3_resources/people/{id}.md`

Profile в `3_resources/people/{id}.md` = Tier 1 автоматически независимо от mention count.

**Кто что делает:**
- `/ztn:bootstrap` — первичная расстановка tiers, count mentions с нуля
- `/ztn:process` — incremental mentions (1-per-file rule), tier только при insert нового person
- `/ztn:maintain` — suggests Tier promote through CLARIFICATIONS, никогда не auto-apply
- `/ztn:lint` — auto Tier 2→1 profile skeleton generation при достижении threshold (reviewed tier — validate requested)

---

## 7. QMD: Knowledge Search Layer

### Configuration

```yaml
# /data/{user}/qmd.yml
collections:
  - name: ztn
    path: /data/zettelkasten
    pattern: "**/*.md"
    ignore:
      - ".git"
      - "_sources/inbox/**"             # Don't index unprocessed inbox files
      - "_system/state/batches/**"            # Machine-readable, not for search
      - "_system/state/lint-context/daily/**" # 30-day rolling — high churn, not useful for long-term search
      # NOTE: _system/state/lint-context/monthly/** IS indexed — rich prose summaries, valuable for semantic recall
    update_commands: |
      cd /data/zettelkasten && git pull --ff-only

  - name: memory
    path: /data/openclaw-memory
    pattern: "**/*.md"
```

### What Gets Indexed (ztn collection)

| Directory | Indexed | Reason |
|---|---|---|
| `_records/meetings/` | Yes | Meeting records — primary search target |
| `_records/observations/` | Yes | Observation records (solo Plaud transcripts) |
| `_sources/processed/` | Yes | Original transcripts — for "give me the file" requests |
| `_sources/inbox/` | No | Unprocessed, will be indexed after /ztn:process |
| `1_projects/` through `5_meta/` | Yes | PARA knowledge notes — core knowledge |
| `_system/SOUL.md` | Yes | Identity context |
| `_system/state/OPEN_THREADS.md` | Yes | Active threads |
| `_system/TASKS.md` | Yes | Tasks |
| `_system/state/BATCH_LOG.md` | No | Machine-readable index (markdown table), not for text search |
| `_system/state/batches/*.md` | No | Human-readable batch reports per batch-format spec |
| `_system/state/batches/*.json` | No | Machine-parseable JSON manifests for the Minder dispatch worker (schema: minder-project/strategy/ARCHITECTURE.md §4.5) |
| `_system/state/lint-context/daily/` | No | 30-day rolling — high churn |
| `_system/state/lint-context/monthly/` | Yes | Rich prose summaries — valuable for semantic recall |

### MCP Tools Exposed

| Tool | Purpose | Use Case |
|---|---|---|
| `query` | Hybrid search (BM25 + vector + rerank) | "Что я обсуждал про инвестиции?" |
| `get` | Retrieve full file by path | "Дай мне транскрипт встречи от 15 апреля" |
| `multi_get` | Batch retrieve by glob pattern | "Все записи за эту неделю" |
| `status` | Index health and stats | Diagnostics |

### Sync Mechanism

QMD does not watch files. Sync is triggered externally:

```bash
#!/bin/bash
# sync-ztn.sh — called by webhook handler or cron
USER=$1
cd /data/users/$USER/zettelkasten
git pull --ff-only
XDG_CACHE_HOME=/data/users/$USER/qmd-cache qmd update
XDG_CACHE_HOME=/data/users/$USER/qmd-cache qmd embed
```

**Triggers:**
- Primary: GitHub webhook (instant on push)
- Fallback: cron every 15 minutes

---

## 8. OpenClaw: ztn-bridge Plugin

Thin plugin (~300 lines TypeScript) connecting OpenClaw to QMD and ZTN git repo.

### Plugin Structure

```
~/.openclaw/extensions/ztn-bridge/
├── index.ts                  ← register(api): tools + hooks
├── src/
│   ├── qmd-client.ts         ← HTTP client for QMD REST/MCP API
│   ├── tools/
│   │   ├── ztn-search.ts     ← Search ZTN knowledge
│   │   ├── ztn-get.ts        ← Get specific file
│   │   ├── ztn-recent.ts     ← Recent notes/records
│   │   └── ztn-save.ts       ← Write file to ZTN inbox
│   ├── hooks/
│   │   ├── orientation.ts    ← before_prompt_build: thin context injection
│   │   └── session-end.ts    ← session_end: save summary to ZTN inbox
│   └── batch-processor.ts    ← Read BATCH_LOG, process new batches
├── package.json
└── openclaw.plugin.json
```

### Tools

| Tool | Parameters | What It Does |
|---|---|---|
| `ztn_search` | `query: string` | Calls QMD `query` on ztn collection. Returns search results with excerpts. |
| `ztn_get` | `path: string` | Calls QMD `get`. Returns full file content. For transcripts, summaries, notes. |
| `ztn_recent` | `days?: number` | Calls QMD `query` filtered to last N days. Returns recent activity. |
| `ztn_save` | `filename: string, content: string` | Writes file to `_sources/inbox/openclaw/{timestamp}/{filename}`. Runs `git add + commit + push`. |

### Hooks

**before_prompt_build** (every user message):
- Reads cached orientation (5-min TTL)
- On cache miss: reads SOUL.md + OPEN_THREADS.md + DAILY_CONTEXT.md from filesystem (no QMD call)
- Injects thin signal — see Section 9

**session_end** (session termination):
- Extracts session summary from transcript
- Calls `ztn_save` to write to inbox
- Triggers git push → eventually processed by /ztn:process

### Batch Processor

Called by webhook notification AND heartbeat poll:

```
1. Read _system/state/BATCH_LOG.md via ztn_get (markdown table per batch-format spec)
2. Compare batch IDs with last_processed_batch_id (from ztn-state.json)
3. For each new batch (chronological order):
   a. Read _system/state/batches/{batch_id}.md via ztn_get (markdown report per batch-format spec)
   b. For each task: check if already in ClickUp → if not, create
   c. For each event: check if already in Calendar → if not, create
   d. Compile summary message
   e. Update last_processed_batch_id
4. Send summary to user via Telegram
```

### Comparison with Minder Plugin

| Aspect | Minder Plugin (3000+ lines) | ztn-bridge (~300 lines) |
|---|---|---|
| Backend | Minder REST API (Java + 5 DBs) | QMD HTTP + git operations |
| Tools | 7 (context, query, browse, get, update, remember, diagnostics) | 4 (search, get, recent, save) |
| Background services | IngestQueue (file-based, polls every 30s), ErrorJournal, IngestDedup | None (batch processing is event-driven) |
| Hooks | 3 (before_prompt_build, after_compaction, session_end) | 2 (before_prompt_build, session_end) |
| Cache | Context cache with TTL, shared between hook and tool | Orientation cache with TTL (filesystem reads only) |
| Complexity | High (async queues, dedup windows, health checks, graceful shutdown) | Low (stateless HTTP calls + git operations) |

---

## 9. Proactive Context Injection

### Pattern (adopted from Minder plugin)

Two layers: **thin orientation always** + **deep search on demand**.

**Layer 1: before_prompt_build (passive, every message)**

Does NOT call QMD. Reads 3 small files from filesystem (cached 5 min):

```xml
<personal_context>
ZTN snapshot: {N} meeting records, {M} people tracked, {K} active hubs.
Focus: {from SOUL.md current focus}.
Open threads: {count} ({first thread title}, ...).
Today: {from DAILY_CONTEXT.md — tasks due, meetings}.
Last batch: {timestamp} ({N} new notes).
(If topic relates to your knowledge — call ztn_search for details.)
</personal_context>
```

Key: the last line tells the agent to call `ztn_search` if the conversation is relevant
to personal knowledge. Agent decides — we don't search on every message.

**Layer 2: ztn_search (active, agent decides)**

Agent calls `ztn_search` when:
- User asks about past conversations, people, decisions
- User asks for a file (transcript, summary)
- Conversation topic overlaps with ZTN content
- User explicitly asks to check notes

Agent does NOT call `ztn_search` when:
- Casual conversation unrelated to personal knowledge
- Tool usage (set timer, send message)
- The orientation signal already has enough context

### Why This Works

The Minder plugin validated this pattern over months of use:
- Cache hit rate was high (most messages don't need fresh context)
- Agents reliably call the search tool when topics shift
- Thin orientation keeps token usage low (<200 tokens per message)
- Deep search only fires when needed (saves latency and cost)

---

## 10. Multi-Platform MCP Access

### Supported Platforms (April 2026)

| Platform | MCP Support | Transport | Tier Required | Per-Chat Toggle |
|---|---|---|---|---|
| Claude Desktop | Yes | Streamable HTTP | Free+ | Yes |
| Claude Mobile | Yes (synced from web) | Streamable HTTP | Free+ | Yes |
| ChatGPT | Yes (Oct 2025) | Streamable HTTP | Plus+ | Yes (Developer Mode) |
| Claude Code | Yes | Streamable HTTP | — | Config-based |
| Cursor | Yes | HTTP | — | Config-based |

### Architecture

```
Internet ──→ Nginx (VPS)
               │
               ├── https://{user}-ztn.minder.host/mcp
               │     → auth: Bearer {per-user-token}
               │     → proxy_pass localhost:{qmd_port}
               │
               └── (existing OpenClaw routes)
```

### Setup Per Friend

1. Create GitHub repo from ZTN template
2. Configure Plaud → Zapier → GitHub
3. Deploy Docker stack (OpenClaw + QMD)
4. Generate auth token for QMD MCP
5. Friend adds MCP connector in their preferred chat:
   - **ChatGPT**: Settings → Developer Mode → Create Connector → URL + token
   - **Claude Desktop**: Settings → Connectors → Add Custom → URL + token
   - **Claude Code**: `~/.claude.json` → mcpServers → url + headers

### Per-Chat Activation

Friends control when ZTN is active. Both ChatGPT and Claude support per-conversation
connector toggle. In a work chat — enable ZTN. In a casual chat — disable.

OpenClaw (via Telegram) always has ZTN active through the ztn-bridge plugin.

---

## 11. Reliability & Fallbacks

### Dual-Trigger Pattern

Every async step has a primary (fast) and fallback (reliable) trigger:

```
STEP 1: /ztn:process trigger
  PRIMARY:  GitHub webhook on inbox/ change → Codex API (instant)
  FALLBACK: Cron every 15 min → Codex/Claude checks inbox → skip if empty

STEP 2: VPS sync + QMD re-index
  PRIMARY:  GitHub webhook on processed/ change → sync script (instant)
  FALLBACK: Cron every 15 min → sync script (idempotent)

STEP 3: OpenClaw notification
  PRIMARY:  Sync script → POST to OpenClaw gateway (instant)
  FALLBACK: OpenClaw heartbeat every 30 min → checks BATCH_LOG
```

### Batch Accumulation Handling

If webhook fails and multiple batches accumulate:

```
1. OpenClaw checks BATCH_LOG.jsonl
2. Filters: all batch_ids > last_processed_batch_id
3. Processes ALL missed batches in chronological order
4. Updates cursor after each batch (not at end — crash-safe)
```

### Idempotency

| Component | Idempotent? | Mechanism |
|---|---|---|
| /ztn:process | Yes | Tracks processed files in PROCESSED.md. Already-processed → skip. |
| QMD update | Yes | SHA-256 content hashing. Unchanged files → skip. |
| QMD embed | Yes | Tracks which documents have embeddings. Already-embedded → skip. |
| Batch processor | Yes | Cursor-based (last_processed_batch_id). Already-processed → skip. |
| Sync script | Yes | git pull --ff-only + incremental QMD update. Safe to run N times. |

### Failure Scenarios

| Failure | Impact | Recovery |
|---|---|---|
| GitHub webhook lost | Up to 15 min delay | Cron fallback picks up |
| Codex/Claude API down | /ztn:process delayed | Cron retries every 15 min |
| VPS sync webhook lost | Up to 30 min delay | OpenClaw heartbeat + cron |
| OpenClaw offline 2 hours | 4 batches missed | On restart: processes all 4 from BATCH_LOG |
| /ztn:process crashes mid-run | Partial processing | File stays in inbox, next run reprocesses |
| QMD daemon crashes | Search unavailable | Docker restart policy: unless-stopped |
| Git push conflict | Processing blocked | Alert; manual resolution needed |

---

## 12. Isolation & Security

### Per-User Isolation

| Layer | Mechanism |
|---|---|
| Network | Docker network per user (`{user}-net`). No cross-user communication. |
| Filesystem | Docker volume per user. No shared writable mounts. |
| Process | Docker PID namespace isolation. |
| Auth (MCP) | Per-user Bearer token in Nginx. One token = one user = one QMD instance. |
| Auth (OpenClaw) | Per-user gateway token + device pairing (existing). |
| Git | Per-user GitHub repo. Separate SSH keys or tokens. |

### Shared Resources (Read-Only Only)

| Resource | Access | Risk |
|---|---|---|
| QMD models (~2GB) | Read-only bind mount | Zero — binary model files, no user data |
| Nginx config | Host-level only | Standard reverse proxy security |
| Trigger Service | Host-level, routes by user | Must validate webhook signatures |

### Data at Rest

- ZTN files: on Docker volume, encrypted at VPS disk level (if VPS supports)
- QMD index: SQLite on Docker volume (contains text chunks + embeddings, NOT original files)
- OpenClaw memory: on Docker volume (existing encryption from OpenClaw)
- Git credentials: per-user SSH keys or tokens in Docker secrets

### Webhook Security

Trigger Service must validate GitHub webhook signatures (HMAC-SHA256)
to prevent spoofed webhooks from triggering /ztn:process for wrong users.

---

## 13. Resource Planning

### VPS Capacity (Current: 8 vCPU / 20 GB RAM / 140 GB NVMe)

**With Minder stack removed:**

| Component | RAM per instance | Instances | Total RAM |
|---|---|---|---|
| Minder stack (removed) | ~7 GB | 0 | **0 GB (freed)** |
| OpenClaw | ~2 GB | 6 | 12 GB |
| QMD daemon (idle) | ~200 MB | 6 | 1.2 GB |
| QMD daemon (active, models loaded) | ~2 GB | 1-2 concurrent | ~4 GB peak |
| Nginx + Trigger Service | ~200 MB | 1 | 0.2 GB |
| OS + overhead | ~1 GB | 1 | 1 GB |
| **Total (steady state)** | | | **~14.4 GB** |
| **Total (peak, 2 users searching)** | | | **~18 GB** |

**QMD model memory note:** Models are loaded on demand and auto-dispose after 5 min
idle. In practice, at most 1-2 users search simultaneously. Steady state RAM is ~14 GB.
Peak (all 6 searching) would exceed 20 GB — but this is extremely unlikely.

**Mitigation if RAM is tight:**
- QMD model inactivity timeout: reduce from 5 min to 2 min
- Use lighter embedding model (fewer parameters)
- Or: upgrade VPS to 32 GB RAM

### Disk Usage

| Data | Per User | 6 Users |
|---|---|---|
| ZTN repo (notes + transcripts) | ~50-200 MB | ~1 GB |
| QMD index (SQLite) | ~20-50 MB | ~300 MB |
| QMD models (shared) | ~2 GB | 2 GB |
| OpenClaw workspace + memory | ~200 MB | 1.2 GB |
| **Total** | | **~5 GB** |

Disk is not a constraint (140 GB NVMe).

---

## 14. Risks & Open Questions

### Critical Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **QMD Russian language quality** | HIGH | embeddinggemma-300M is untested on Russian. MUST verify on a real-content ZTN before rollout. Fallback: set `QMD_EMBED_MODEL` to multilingual model, or fall back to BM25-only search. |
| **Zapier reliability** | MEDIUM | Zapier polling can miss files or delay. Consider direct Plaud → GitHub integration if available. |
| **Codex/Claude API costs for friends** | MEDIUM | /ztn:process runs on Claude/Codex per user. Who pays? Operator may sponsor initially, but N users × frequent recordings = nontrivial API spend. Need to monitor. |

### Open Questions

1. **QMD embedding model for Russian** — need to test. If bad, options:
   a. Replace with multilingual GGUF model via `QMD_EMBED_MODEL`
   b. Use QMD's BM25 search only (disable vector search)
   c. Reconsider GBrain (uses OpenAI embeddings, good Russian support)

2. **Plaud → Zapier → GitHub latency** — Zapier polls (1-3 min delay). Is there
   a faster path? Plaud API direct → GitHub? IFTTT? Custom webhook?

3. **OpenClaw gateway API for system messages** — does OpenClaw's gateway support
   receiving system messages via API? Need to verify endpoint exists. Alternative:
   write to a trigger file that ztn-bridge plugin watches.

4. **Claude/Codex trigger from webhook** — need to verify Codex/Claude API supports
   webhook-triggered runs. Alternative: always use cron schedule (simpler but slower).

5. **ZTN template for new instances** — how much of an existing ZTN structure to
   include? New users don't have 400+ notes. Start with minimal template (SOUL.md,
   basic PARA, empty registries) and let it grow organically.

6. **User onboarding flow** — who sets up GitHub repos, Zapier, Plaud config?
   Operator manually per user? Or a semi-automated script?

### Architectural Concerns (Self-Criticism)

1. **Two webhook chains are fragile** — Recording → Zapier → GitHub → Webhook →
   Codex → GitHub → Webhook → Sync → OpenClaw. Six steps, each can fail. Cron
   fallbacks help, but this is inherently complex. A simpler architecture would have
   fewer moving parts.

2. **Git as message bus** — using git push/pull as a trigger mechanism is unconventional.
   It works, but git wasn't designed for event-driven architectures. Merge conflicts,
   push races, and git lock files are real risks with multiple writers (Codex + OpenClaw
   both push to the same repo).

3. **QMD is young software** — fewer stars, less battle-tested than Elasticsearch or
   pgvector. If QMD has bugs or performance issues at scale, there's less community
   support. Mitigation: the ZTN data is in git (portable), QMD can be replaced.

4. **Operational complexity for the operator** — N users × (Docker stack + GitHub repo +
   Zapier + Codex trigger + QMD + OpenClaw). That's a lot of moving parts to maintain.
   Even if each piece is simple, the total system is complex.

5. **Session-end writes are async** — OpenClaw session_end pushes to git, but
   /ztn:process may not run for 15 min. User might expect instant knowledge capture
   from OpenClaw sessions but it's delayed.

---

## 15. Implementation Plan

Implementation phases, decision gates, and open questions are tracked
per-instance — typically in a `platform/` folder kept by the instance
owner. The engine itself (this repo) ships only the running system; the
plan-of-record for any specific deployment lives in that owner's
working tree, outside the engine.

**Краткая последовательность:**

```
Phase 1: Structure + Bootstrap
Phase 2: /ztn:process (batch output)
Phase 3: /ztn:maintain (after-batch integrator)
Phase 4: /ztn:lint (nightly slop catcher)
Phase 5: Local scheduling + dogfooding   (1-2 месяца elapsed)
  ═══ FREEZE GATE ═══
Phase 6: QMD validation + VPS deploy
Phase 7: ztn-bridge plugin для OpenClaw
Phase 8: Automation Pipeline (Trigger Service)
Phase 9: Friend rollout
```

**Ключевой принцип:** knowledge pipeline (process/maintain/lint) сначала доводится
до эталонного состояния на локальной машине (Phase 1-5), минимум месяц dogfooding,
FREEZE GATE — только потом VPS/QMD/ztn-bridge/friends (Phase 6-9).

Детали каждой фазы с sub-steps, decision gates, open questions — в ROADMAP.md.
SDD для конкретной фазы — в `PHASE-{N}-SDD.md`, пишется когда подходим к фазе.

---

## Appendix: Comparison with Previous Architecture

```
BEFORE (Minder Stack):                    AFTER (ZTN Platform):
═══════════════════════                    ══════════════════════
PostgreSQL  ┐                              Git repo (markdown)
Neo4j       ├─ 5 databases                 QMD (SQLite index)
Qdrant      │                              ─────────────
Redis       │                              2 components
MinIO       ┘

Java Spring Boot app                       /ztn:process (Claude skill)
  12 agents                                ztn-bridge plugin (~300 LoC)
  Multi-round processing                   Trigger Service (~150 LoC)
  Concept graph
  ─────────────
  1 app + 5 DBs                            Complexity: LOW

minder-openclaw-plugin (3000+ LoC)         Data duplication: NONE
  IngestQueue, ErrorJournal                (QMD indexes files in-place)
  IngestDedup, ContextCache
  7 tools, 3 hooks                         Operational overhead: LOW
  ─────────────                            (Docker + cron + webhook)
  Data duplication: YES
  (git AND 3 databases)
  Operational overhead: HIGH
```
