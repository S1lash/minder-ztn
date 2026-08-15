---
id: readme-1-projects
title: Projects
layer: meta
tags:
- type/structural
created: '2024-12-01'
modified: '2026-08-15'
origin: personal
audience_tags: []
is_sensitive: false
---

# Projects

Active goals with specific deadlines. `PROJECTS.md` is the registry — a row there
IS the registration of a project identifier.

## Structure

Each project has its own subfolder holding its dated notes
(`YYYYMMDD-{type}-{slug}.md`). There is no card file standing for the project
itself: the project's canonical node is its hub, `5_meta/mocs/hub-{id}.md` with
`hub_kind: project`, and that is what links point at.

A note belongs to a project through `projects: [{id}]` in its own frontmatter.
