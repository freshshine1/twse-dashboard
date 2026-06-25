#!/usr/bin/env python3
"""Post-feeder board verification (#3b) — the double-check on the freshness layer.

Runs in daily.yml AFTER `Run feeder` and BEFORE `Commit and push`, but only on runs
that actually executed the feeder (gate run==true). It is independent of feeder.py's
own in-process self-check (#3a), so a regression that breaks BOTH the flagger and its
self-check still gets caught here at the workflow boundary.

Fails LOUD (exit 1) — which skips the commit, leaving the last good board live — when:
  1. data.json was NOT refreshed by this run (a silent no-op masquerading as green):
     its `updated` timestamp is older than MAX_AGE_SEC.
  2. the freshness metric is missing entirely (market.price_stale_count / t86_session):
     i.e. the #2 flagger silently stopped emitting.

A board that is genuinely on prior-session prices (price_stale_count > 0) is NOT an
error here — that is an honestly-flagged board and must still publish. It is surfaced
as a GitHub ::warning:: annotation so it shows on the run summary without log-diving.

Stdlib only; no third-party deps (mirrors selfheal_gate.py).
"""
import datetime
import json
import sys

DATA_PATH = "docs/data.json"
MAX_AGE_SEC = 1800  # 30 min: feeder takes ~6 min, so a fresh write is well under this.


def main():
    errs = []
    try:
        with open(DATA_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        print("::error::%s unreadable (%s)" % (DATA_PATH, exc))
        sys.exit(1)

    market = data.get("market", {})
    upd = str(data.get("updated", ""))

    # 1) Was data.json actually refreshed by THIS run?
    try:
        t = datetime.datetime.fromisoformat(upd)
        now = datetime.datetime.now(t.tzinfo) if t.tzinfo else datetime.datetime.now()
        age = (now - t).total_seconds()
        if age > MAX_AGE_SEC:
            errs.append("data.json 'updated' is %.0fs old (>%ds) -- feeder ran but did "
                        "not refresh the board" % (age, MAX_AGE_SEC))
    except Exception as exc:
        errs.append("unparseable updated=%r (%s)" % (upd, exc))

    # 2) Is the freshness metric present at all?
    if "price_stale_count" not in market:
        errs.append("market.price_stale_count missing -- #2 freshness flagger not emitting")
    if "t86_session" not in market:
        errs.append("market.t86_session missing -- #2 freshness flagger not emitting")

    psc = market.get("price_stale_count")
    print("[verify_board] updated=%s  price_stale_count=%s  t86_session=%s"
          % (upd, psc, market.get("t86_session")))

    if psc:
        # Honest-but-stale board: publish, but make it shout on the run summary.
        print("::warning::%s holding(s) on prior-session prices "
              "(STOCK_DAY_ALL lagged a session; board published with price_stale flags)" % psc)

    if errs:
        for e in errs:
            print("::error::" + e)
        sys.exit(1)
    print("[verify_board] OK -- board refreshed and freshness flags present.")


if __name__ == "__main__":
    main()
