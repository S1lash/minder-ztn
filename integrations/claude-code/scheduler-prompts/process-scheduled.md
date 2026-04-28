You are running an autonomous scheduled tick. There is no human in this
loop. Your contract:

1. Pre-flight sync. Run `/ztn:sync-data`.
   - Up-to-date or no `origin` → continue.
   - Conflict / non-fast-forward → STOP. Append a one-line note to
     `_system/state/CLARIFICATIONS.md` under a `### Scheduler failures`
     section with timestamp and short cause, then run `/ztn:save --auto
     --message "scheduler: sync conflict, owner action needed"` so the
     note itself ships to remote. Exit.

2. Process. Run `/ztn:process`.
   - Anything ambiguous, low-confidence, or boundary-case — let the
     skill route it to CLARIFICATIONS as designed. Do NOT pause for
     owner input. CLARIFICATIONS growing is the expected steady state.
   - `/ztn:process` finishes maintain inline; do not invoke
     `/ztn:maintain` separately.
   - If `/ztn:process` aborts on lock / repo state — append failure
     note to CLARIFICATIONS as in step 1, then continue to step 3 so
     the note still gets committed.

3. Save. Run `/ztn:save --auto`.
   - This commits with the auto-proposed message (suffix `[scheduled]`)
     and pushes to `origin`. No prompts.
   - Engine paths are refused as always; if any are dirty, that's an
     owner-only situation and the scheduler must surface it via
     CLARIFICATIONS, not bypass via `--include-engine`.
   - If push rejects (someone pushed first) — commit stays local; the
     next scheduled tick pre-syncs and resolves. Do NOT force-push.

4. Forbidden in this run:
   - `/ztn:lint` (has its own nightly schedule)
   - `/ztn:resolve-clarifications` (owner-only)
   - `/ztn:update` (engine sync is owner-only)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force` of any kind

Output: a single-line status (success / partial / sync-blocked /
save-blocked) plus the commit SHA if a commit landed. No prose.
