# CLAUDE.md - twse-dashboard

Personal, non-commercial Taiwan stock-market dashboard. A GitHub Actions pipeline
fetches TWSE/TAIFEX data, scores stocks across a 5-layer composite, and serves a live
board at docs/index.html via GitHub Pages. Fisher runs this as a hobby and communicates
tersely: read intent, execute, flag genuine blockers, propose one next action.

## Read first
- docs/IMPLEMENTATION_GUIDE.md (build playbook; read the latest chapter at session start).
- The most recent session handoff, if one is provided.

## Hard rules (do not break)
1. VERIFY LIVE, NOT DOCS. Features described as "shipped" may never have run in
   production. Read the actual current file before building on it.
2. NO scoring / threshold / baseline math changes before the 2026-07-28 observe
   boundary. Display and reliability fixes are fine anytime. Keep display heuristics
   OUT of config/thresholds.json.
3. The confluence gate is load-bearing: GO/ADD fires only when L1 >= 0.4 AND L2 >= 0.4.
   Do not alter the gate or layer formulas outside the boundary batch.
4. FAIL LOUD, never silently green. sys.exit(1) on a trading-day fetch failure is
   intentional - a run that exits 0 without writing data is worse than a red run.
5. daily.yml git-add: a single `git add` over several paths aborts entirely if any one
   is missing. Mandatory outputs are added unconditionally; optional outputs must be
   guarded with `if [ -f "$f" ]`. Any new persisted file MUST be added here or it
   resets to zero on every stateless CI checkout.

## Workflow discipline
- One concern per commit. Run python -m py_compile (and node --check for index.html)
  before committing. Patch with assert-guarded splices (assert the anchor count before
  each replacement) so edits fail loudly if the file drifts.
- Do not manually trigger daily.yml before ~18:00 TPE - T86 data is not published yet.

## Pending verification (as of 2026-06-20)
- The TAIFEX OI fetch fix (browser UA + cp950 + diagnostics in fetch_taifex_oi) and the
  no-history stale-flag fix (compute_technicals empty-history branch) are committed but
  UNVALIDATED. First valid test is the Monday 2026-06-22 run (TAIFEX was holiday-closed).
  After it runs, check: docs/raw/taifex_oi_latest.json exists, market.futures_oi is
  populated, and previously no-history tickers show stale=true.
- Low-priority cleanup: on no-trade days, tickers with price=None still get a composite
  (~65) with no stale flag. Suppress composite / flag stale when price is None - ship
  only AFTER Monday validates the two pending fixes (do not stack changes before then).
