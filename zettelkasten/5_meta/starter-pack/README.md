# Constitution starter pack

Optional generic axioms `/ztn:bootstrap --with-starter-axioms` can drop
into your `0_constitution/axiom/{domain}/` as starting points. Engine
ships these as drafts — `confidence: starter`, `status: draft` — so
they're visible in your constitution but never auto-load into
`constitution-core` until you mark them `confidence: proven` and
`status: active`.

These are starting points, not prescriptions. Most users:

- keep 1-3 that resonate, edit the wording into their own voice;
- delete the rest;
- write 5-10 of their own over the first month using
  `/ztn:capture-candidate` while working with Claude.

If you don't want any starter content, run `/ztn:bootstrap` without the
flag — your `0_constitution/` stays empty and grows from your own
captured candidates.

## Files

| File | Domain | One-liner |
|---|---|---|
| `axioms/name-the-tradeoff.md` | ethics | Surface trade-offs explicitly before implementing |
| `axioms/own-your-mistakes.md` | ethics | When something breaks, own it; don't defer or rationalize |
| `axioms/internal-honesty.md` | identity | Don't push externally what you're not honest about internally |
| `axioms/quality-as-respect.md` | identity | Quality is respect for self and for whoever lives with the result |
| `axioms/first-time-hard.md` | work | First implementation of anything reusable should be done well |
| `axioms/long-term-consequences.md` | work | Optimize for the people who'll live with this in 12-24 months |
