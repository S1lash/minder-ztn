---
id: log-maintenance
layer: system
description: Append-only audit trail of /ztn:maintain + /ztn:bootstrap runs. Per-run aggregation.
owned_by:
  - ztn:maintain
  - ztn:bootstrap
read_by:
  - ztn:lint
# One-time migration flags (add as needed):
# migration_completed:
#   {migration_name}: YYYY-MM-DD
---

# Maintenance Log

> Append-only log of maintenance + bootstrap operations.
> Each entry — one skill run (`/ztn:bootstrap`, `/ztn:maintain`).
> Format: timestamp (ISO 8601 UTC) | mode | by: {skill} | batch: {id or —}
>
> **Read-only consumer:** `/ztn:lint` reads this file for activity detection (Scan B.1 thread staleness).

---

<!-- Entries append BELOW this line, newest first -->
