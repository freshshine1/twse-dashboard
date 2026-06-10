# agent_ops.md — additions (paste-ready)

## Edit 1 — REPLACE the existing §5 with this expanded version

## 5. Diagnostics & verification — one batched sweep, never a sequence
- Independent reads (Actions log, live `data.json`, `docs/raw/*.json`, source files) go in **one**
  parallel sweep, not turn-by-turn. Use `browser_batch` (browser) or a single `bash` with all the
  `curl`s + one Python parse (sandbox) whenever ≥2 reads are predictable.
- **Verification template:** when asked to "check the repo," fetch everything needed in one call and
  print a compact pass/fail table — don't fetch-explain-fetch-explain across turns. One sweep per
  verification. (Session-3 lesson: the final batched check cost a fraction of the earlier piecemeal
  ones for the same information.)

## Edit 2 — INSERT this as a new §7, BEFORE the current "## 7. Known environment facts" (which becomes §8)
# (The project file currently ends at §7 Known environment facts — just bump that one to §8.)

## 7. Context discipline — don't re-pay for what's already known
- **The handoff is the context anchor.** Once a framing or root-cause is written into the handoff
  (e.g. the two-clock producer/consumer design, the L3 empty-file bug), treat it as established —
  read it once at session start, then skip straight to the work. Do not re-derive or re-explain it
  mid-session or next session.
- **Don't re-fetch a file you already pulled this session** unless something has changed it (a commit,
  a scheduled run, or a repair you just told Fisher to do). Re-fetching after a repair is correct;
  re-fetching to re-confirm something unchanged is waste.
- **Match the asked-for output length.** "Quick answer" = the answer only, no recap. Default answers
  should carry new reasoning, not re-state context Fisher already has. The handoff and rundown tables
  earn their length; the prose around them usually doesn't.
- **Verification sessions should be near-silent:** a few fetches and a one-line pass/fail each, prose
  only when something fails.
