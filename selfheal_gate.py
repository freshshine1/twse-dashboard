#!/usr/bin/env python3
"""Self-heal staleness gate for the backup runs of daily.yml.

Prints exactly one line, `run=true` or `run=false`, to stdout (captured into
$GITHUB_OUTPUT). The backup cron runs the full feeder ONLY when this says
`run=true` — i.e. only when the board is actually stale. The PRIMARY cron and
manual workflow_dispatch bypass this gate entirely (handled in daily.yml), so
this script is invoked solely on backup triggers.

Why a gate: the backup exists purely to recover a board that the primary run
failed to refresh (e.g. a transient TWSE blip). If the primary already
succeeded, the backup must be a no-op — it must NOT re-fetch, must NOT commit,
and must NOT touch t86_market_prev. The gate guarantees that.

Holiday safety: if the gate says `run=true` on a non-trading day, feeder.py's
own STOCK_DAY_ALL "No Data" path exits green without overwriting data.json, so a
false-positive here is harmless (a ~30s no-op feeder run), never destructive.

No third-party deps; Taiwan has no DST so a fixed UTC+8 offset is exact.
"""
import datetime
import json
import sys

TPE = datetime.timezone(datetime.timedelta(hours=8))
DATA_PATH = "docs/data.json"
COMPLETE_AFTER = "18:30"  # a snapshot stamped before this didn't ingest that day's T86


def prev_weekday(d):
    """Most recent Mon-Fri date strictly before d."""
    while True:
        d -= datetime.timedelta(days=1)
        if d.weekday() < 5:
            return d


def latest_trading_day(now):
    """The weekday whose ~19:00 board SHOULD exist by `now`.

    Backups run pre-market (early AM), so today's session hasn't closed and the
    latest *completed* trading day is the most recent prior weekday. If somehow
    invoked on a weekday at/after 18:30 (T86 published), today qualifies.
    Public-holiday weekdays are not special-cased: feeder no-ops on them, so the
    worst case is a harmless redundant run.
    """
    if now.weekday() < 5 and now.strftime("%H:%M") >= COMPLETE_AFTER:
        return now.date()
    return prev_weekday(now.date())


def evaluate(now):
    ltd = latest_trading_day(now)
    try:
        with open(DATA_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        upd = str(data.get("updated", ""))
        board_date = datetime.date.fromisoformat(upd[:10])
        board_time = upd[11:16]  # 'HH:MM'
    except Exception as exc:  # missing / malformed -> treat as stale, recover
        return True, "data.json unreadable (%s)" % exc, ltd

    if board_date < ltd:
        return True, "board %s is behind latest trading day %s" % (board_date, ltd), ltd
    if board_date == ltd and board_time < COMPLETE_AFTER:
        return True, "board %s is a pre-%s snapshot (%s)" % (board_date, COMPLETE_AFTER, board_time), ltd
    return False, "board %s %s is current" % (board_date, board_time), ltd


def main():
    now = datetime.datetime.now(TPE)
    stale, reason, ltd = evaluate(now)
    # Decision to stdout (for GITHUB_OUTPUT); rationale to stderr (for the log).
    print("run=%s" % ("true" if stale else "false"))
    sys.stderr.write(
        "[selfheal_gate] now=%s TPE  latest_trading_day=%s  %s  ->  run=%s\n"
        % (now.strftime("%Y-%m-%d %H:%M"), ltd, reason, "true" if stale else "false")
    )


if __name__ == "__main__":
    main()
