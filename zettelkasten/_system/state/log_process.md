---
id: log-process
layer: system
description: Append-only chronological log of /ztn:process runs. Newest-first.
owned_by:
  - ztn:process
read_by:
  - ztn:lint
  - ztn:maintain
# One-time migration flags (add as needed):
# migration_completed:
#   {migration_name}: YYYY-MM-DD
---

# Operations Log

> Append-only chronological log of `/ztn:process` runs.
> Each entry — one batch invocation.

---

<!-- Entries append BELOW this line, newest first -->
