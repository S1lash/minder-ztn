# What's new

User-readable release notes. For the engineering log, see git history.

## 0.20.0 — Lens output upgraded for Obsidian + in-vault graph reset

### In-vault Reset Graph button

`minder-ztn.md` now ships a `## ⚙️ Maintenance` section with a
DataviewJS button: «🔄 Reset graph view to defaults». One click
restores `graph.json` (color groups, forces, default filter) from
the engine snapshot at `.obsidian/graph-defaults.json`, with an
auto-backup of your current state. No CLI needed for the common
recovery case after Obsidian wipes color groups during filter
tweaks. Requires Dataview JS Queries enabled (already part of the
Dataview setup checklist).

The CLI path stays available for power users:
`./integrations/obsidian/seed.sh --reset-graph`.

### Lens output upgraded for Obsidian


Lens output files now carry a human-readable `title:` and reference
cited files via `[[wikilinks]]` instead of paths in backticks. Two
practical effects:

- **Lens nodes in the graph have real names.** Instead of seeing
  `2026-05-04` as a node label, you see «🔭 stalled-thread —
  2026-05-04» (with Front Matter Title plugin enabled). Files become
  scannable in the file tree, Quick Switcher, and graph view.
- **Lens nodes connect to the records they observe.** Each Evidence
  bullet is now `[[basename]]` so Obsidian draws an edge between the
  lens output and the record / hub / principle it cites. The
  `🔭 Lens observations` graph preset becomes meaningful — you see
  «what the AI noticed about which records», not a cluster of
  disconnected dates.

**To opt in:**

1. Run `/ztn:update` (or `scripts/sync_engine.sh`) — pulls the new
   `_frame.md` Stage 2 schema.
2. The next `/ztn:agent-lens` run emits the new format automatically.
   No action needed for friends without prior lens output.

**For pre-existing lens output:** if you happen to have lens files
from before this version (rare — most friends adopt lenses fresh),
they remain valid in their original form per the grandfathering
clause in `_frame.md` Stage 3. The validator never rewrites files
already on disk. New emissions from this version forward use the new
format.

**For maintainers:** `_frame.md` Stage 2 prompt schema and Stage 3
validator updated in lockstep. Wikilink basename resolution replaces
ZTN-path resolution. Legacy outputs grandfathered.

---

## 0.19.0 — Obsidian vault integration

The first proper UI for ZTN. Until now you read your records as files
and your registries as markdown tables; now there's a vault config
that opens cleanly in Obsidian, a dashboard, graph presets, hotkeys,
bookmarks, and visual cues per note type.

**What you get after `/ztn:update` + re-running `install.sh`:**

- **`minder-ztn.md` dashboard** at the vault root. Live blocks (powered by
  Dataview) for recent meetings, observations, active projects, people,
  open tasks. Static links to Current Context, Open Threads,
  Clarifications, SOUL.
- **Bookmarks pane** (left sidebar, `Cmd+Shift+B`) — pre-pinned
  navigation: Now, Identity, Registries, Browse, Obsidian docs.
- **Graph view tuned for ZTN** — colour-coded by PARA layer (people
  orange, meetings green, observations teal, constitution purple, hubs
  gold, projects blue, archive grey). Engine internals and flat
  aggregator nodes (INDEX, registries) hidden by default.
- **6 graph presets** documented in `integrations/obsidian/views.md` —
  copy-paste filters for People web, Decision lineage, Project
  landscape, Hub network, Knowledge distillation, Sensitive zone.
- **Hotkeys** — `Cmd+Shift+G` graph, `Cmd+Shift+L` local graph,
  `Cmd+Shift+B` bookmarks, `Cmd+Shift+O` outline, `Cmd+Shift+K` tag
  pane, `Cmd+Shift+Y` insert template.
- **Visual cues** — coloured left border on the editor pane plus
  emoji prefix in tab headers and file explorer per note type
  (👤 person, 🤝 meeting, 👁 observation, ⚖️ axiom, 🧭 principle,
  📏 rule, 🌟 hub, 🚀 project).
- **Engine paths hidden** — `_system/state/`, `_system/scripts/`,
  `_system/docs/`, `_sources/processed/`, `*.template.md`,
  `integrations/`, `__pycache__/`, README files. Two layers: a CSS
  snippet hides them from the file tree, `userIgnoreFilters` hides
  them from search and graph.
- **Comprehensive guide** at `integrations/obsidian/guide.md` —
  hotkeys reference, daily/weekly/monthly recipes, frontmatter rules,
  reset-to-defaults procedure.

**To opt in:**

1. Run `/ztn:update` (or `scripts/sync_engine.sh`)
2. Run `./integrations/claude-code/install.sh` — it now seeds
   `<vault>/.obsidian/` and `<vault>/minder-ztn.md` if they don't exist.
3. Open Obsidian → "Open folder as vault" → select `zettelkasten/`
4. Install three community plugins (instructions print on first run):
   - **Dataview** by Michael Brenan — powers HOME's live blocks
   - **Tasks** by Clare Macrae — global task view across the vault
   - **Front Matter Title** by snezhig — shows `title:` from
     frontmatter instead of snake-case file IDs in graph, file tree,
     tab headers, Quick Switcher

**To opt out:** delete `<vault>/.obsidian/` and `<vault>/minder-ztn.md`. The
ZTN engine itself doesn't depend on Obsidian — skills work the same
whether you have the vault open or not.

**Backward compatibility:** purely additive. All earlier skills,
manifests, and engine internals unchanged.

**For maintainers:** new engine paths under `integrations/obsidian/`
ship via `release_engine.py`. The seeder is idempotent and never
overwrites a friend's live `.obsidian/` (only `--force` does, with
auto-backup). See `integrations/obsidian/README.md`.

---

## How to read this changelog

Each release has:

- **What you get** — concrete features after running `/ztn:update`
- **To opt in / out** — what you actively need to do
- **Backward compatibility** — whether anything broke
- **For maintainers** — engine-level notes (skip if you're a user)

Versions before 0.19.0 are not documented here in user-readable form;
see git log + integration commit messages for the engineering history.
