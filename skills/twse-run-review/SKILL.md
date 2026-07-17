---
name: twse-run-review
description: Read-only audit of the twse-dashboard nightly pipeline. Use whenever Fisher asks to "review last night's run", "check the pipeline", "run review", "verify yesterday's board", or at session open before building on the repo. Checks the run ledger, snapshot archive, board health stamps (with L3 stale-stub detection), commit cadence, and backup stand-down sanity for one trading session, printing GREEN/AMBER/RED per check.
---

# twse-run-review

Audits one session of the `freshshine1/twse-dashboard` pipeline. **Read-only** — it
never writes to the repo. Stdlib only, no pip installs.

## How to run

```bash
python3 review_run.py                    # latest session in processed/run_log.csv
python3 review_run.py --date 2026-07-15  # specific session
```

Exit code `1` if any check is RED, else `0`.

## What it checks

1. **Ledger** — `processed/run_log.csv` rows for the session. `primary` + `backupB`
   (double row) is GREEN: the nightly backupB overwrite of identical-session data is
   documented normal until the 2026-07-28 MIS work removes the cause.
2. **Snapshot** — `docs/raw/snapshot_<session>.json` exists and parses. Sessions
   before 2026-07-13 predate snapshot persistence (INFO, not a failure).
3. **Board health** — `docs/data.json` `health.*` stamps:
   - `t86` must equal the session date once the primary has run.
   - `l3` lagging the last trading day triggers the **stale-stub sub-check**: fetch
     `docs/raw/l3_fundamentals_<date>.json`; if `stale: true`, report AMBER with its
     `stale_reason` (designed stand-down — `feeder_l3.py` keeps last-known-good
     `latest` when a fetch returns 0 flagged tickers). Never trust the L3 commit
     message — it reads `L3 fundamentals <date>` whether fresh or stub.
   - `l4` may lag the board build by one day (morning L4 lands after backupB) — GREEN.
   - `analysis` is parked (dark since 2026-05-28) — always INFO.
4. **Commit cadence** — atom feed (`.atom`, never `api.github.com` from the sandbox):
   L3, board (expect 2/session), and L4 commits. Feed holds ~20 entries; older
   sessions get INFO "feed no longer covers".
5. **BackupB sanity** — a stood-down backupB writes **no** ledger row by design
   (absence + no commit = GREEN). A backupB board commit **without** a row is RED
   (`append_run_log` failure).

## Interpreting AMBER

AMBER means "designed stand-down or verify manually", not failure:
- L3 stale-stub day (typhoon closures produce these).
- Weekday with no run at all → possible market closure; confirm before alarming.
- The trading calendar is **inferred** (weekday + ledger presence) — the script has no
  holiday table by design (v1 decision, session 29).

## House rules baked in

- Raw fetches are cache-busted (verification reads only — the dashboard frontend must
  never cache-bust; this script is not the frontend).
- **CDN race:** raw.githubusercontent can serve pre-commit content for ~75s+ after a
  commit. If you just committed something, wait and re-run before trusting a RED.
- Sandbox networking: `raw.githubusercontent.com` and `github.com` (`.atom`) only;
  `api.github.com` rate-limits from the sandbox — this script never touches it.

## Versioning

Canonical copy lives in-repo at `skills/twse-run-review/`. The claude.ai skill is a
zip of this folder uploaded via Customize → Skills. When changing the script: edit the
repo copy first (Fisher drag-drop commits, one concern per commit, byte-verify), then
re-zip and re-upload so the two never drift.
