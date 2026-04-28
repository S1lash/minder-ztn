You are running an autonomous nightly tick. There is no human in this
loop. Your contract:

1. Pre-flight sync. Run `/ztn:sync-data`.
   - Up-to-date or no `origin` → continue.
   - Conflict → STOP. Append a one-line note to
     `_system/state/CLARIFICATIONS.md` under `### Scheduler failures`
     with timestamp and cause, then run `/ztn:save --auto --message
     "scheduler: sync conflict, owner action needed"`. Exit.

2. Lint. Run `/ztn:lint`.
   - Standard flow: skill auto-fixes the obvious, surfaces the
     non-obvious to CLARIFICATIONS. Do NOT pause for owner input.
   - Queue size is irrelevant to whether the run continues — owner
     reviews the queue tomorrow via /ztn:resolve-clarifications.
   - If `/ztn:lint` aborts on lock / repo state — append failure note
     to CLARIFICATIONS, then continue to step 3 so the note ships.

3. Save. Run `/ztn:save --auto`.
   - Commits with auto-proposed message (suffix `[scheduled]`) and
     pushes to `origin`. Engine refusal applies. No force-push.

4. Forbidden in this run:
   - `/ztn:process` (its own daytime schedule handles this)
   - `/ztn:maintain` (runs inline inside process; not relevant here)
   - `/ztn:resolve-clarifications` (owner-only)
   - `/ztn:update` (engine sync is owner-only)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force`

Output: single-line status (success / partial / sync-blocked /
save-blocked) plus commit SHA if landed. No prose.
