#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hitrate_review.py — read-only hit-rate grader for the 2026-07-28 observe-window review.

Reads processed/signal_log.csv + processed/verdict_log.csv from the live repo
(raw.githubusercontent.com, cache-busted) or from a local directory (--local DIR).
Never writes to the repo. Stdlib only. Exit code always 0 (analysis, not audit).

Metrics (decided session 30):
  PRIMARY  A: sign(fwd_5d) vs action direction        (best coverage, matches L1 horizon)
  secondary : same on fwd_10d / fwd_20d               (fwd_20d barely graded pre-7/28)
  secondary C: fwd_5d vs TAIEX 5d forward (excess)    (partial: TAIEX series = verdict_log,
                                                       starts 2026-06-18)

Direction convention:
  GO / ADD   -> expect fwd > 0
  SELL / TRIM-> expect fwd < 0
  near-miss (NO-GO/HOLD, near_miss=1) counterfactual direction = sign(composite).
  fwd == 0 counts as a miss.

Degraded sessions are excluded from the headline (reported separately):
  2026-07-17 — market-level T86 missing (record-volume crash day); L1 unreliable.

Known history (Ch.15/16): rows for sessions 6/26–7/1 were reconstructed after the
wall-clock mislabel incident (repaired 2026-07-02); forward returns were refilled
idempotently, so they grade normally. Log coverage starts 2026-06-16 although the
observe window opened 2026-05-29 — the logger shipped mid-window (§12.1).
"""

import argparse
import csv
import io
import sys
import time
import urllib.request
from collections import defaultdict

RAW_BASE = "https://raw.githubusercontent.com/freshshine1/twse-dashboard/main"
OBSERVE_START, OBSERVE_END = "2026-05-29", "2026-07-27"
DEGRADED = {
    "2026-07-17": "market T86 missing (record-volume crash); L1 unreliable",
}
REPAIRED_NOTE = "2026-06-26..2026-07-01 rows reconstructed post Ch.15 repair (grade normally)"
FIRED = {"GO": +1, "ADD": +1, "SELL": -1, "TRIM": -1}
L1_BANDS = [(0.0, 0.4, "|L1| < 0.4"), (0.4, 0.6, "0.4–0.6"), (0.6, 99.0, "> 0.6")]
COMP_BANDS = [(0, 20, "|comp| < 20"), (20, 40, "20–40"), (40, 60, "40–60"), (60, 999, "≥ 60")]


def fetch(path, local_dir):
    if local_dir:
        with open("%s/%s" % (local_dir, path.split("/")[-1]), encoding="utf-8-sig") as f:
            return f.read()
    url = "%s/%s?cb=%d" % (RAW_BASE, path, int(time.time()))
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8-sig")


def num(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load(local_dir):
    sig = list(csv.DictReader(io.StringIO(fetch("processed/signal_log.csv", local_dir))))
    ver = list(csv.DictReader(io.StringIO(fetch("processed/verdict_log.csv", local_dir))))
    dropped = 0
    rows = []
    for r in sig:
        if not (r.get("date") and r.get("ticker") and r.get("action")):
            dropped += 1
            continue
        r["_comp"] = num(r.get("composite"))
        for c in ("l1", "l2", "l3", "l4", "l5", "fwd_5d", "fwd_10d", "fwd_20d"):
            r["_" + c] = num(r.get(c))
        r["_fired"] = r["action"] in FIRED
        if r["_fired"]:
            r["_dir"] = FIRED[r["action"]]
        elif r.get("near_miss", "").strip() == "1" and r["_comp"] is not None:
            r["_dir"] = 1 if r["_comp"] > 0 else (-1 if r["_comp"] < 0 else 0)
        else:
            r["_dir"] = 0
        r["_degraded"] = r["date"] in DEGRADED
        rows.append(r)
    return rows, ver, dropped


def hit(r, col):
    """1 hit / 0 miss / None ungradable, on forward-return column col."""
    f = r["_" + col]
    if f is None or r["_dir"] == 0:
        return None
    return 1 if (f > 0) == (r["_dir"] > 0) and f != 0 else 0


def rate(pairs):
    g = [h for h in pairs if h is not None]
    if not g:
        return "     —      (0 graded)"
    return "%5.1f%%  (%d/%d graded)" % (100.0 * sum(g) / len(g), sum(g), len(g))


def taiex_forward(ver, n):
    """date -> compounded TAIEX % over the n sessions AFTER date (None if short)."""
    dates = [v["date"] for v in ver]
    pcts = [num(v["taiex_chg_pct"]) for v in ver]
    out = {}
    for i, d in enumerate(dates):
        win = pcts[i + 1:i + 1 + n]
        if len(win) == n and all(p is not None for p in win):
            acc = 1.0
            for p in win:
                acc *= 1.0 + p / 100.0
            out[d] = (acc - 1.0) * 100.0
    return out


def line(label, pairs, indent=2):
    print("%s%-22s %s" % (" " * indent, label, rate(pairs)))


def main():
    ap = argparse.ArgumentParser(description="TWSE dashboard hit-rate review (read-only)")
    ap.add_argument("--local", metavar="DIR", default=None,
                    help="read signal_log.csv / verdict_log.csv from DIR instead of the live repo")
    ap.add_argument("--include-degraded", action="store_true",
                    help="fold degraded sessions into the headline instead of separating them")
    args = ap.parse_args()

    rows, ver, dropped = load(args.local)
    print("twse-hitrate-review v1.0 — observe window %s → %s" % (OBSERVE_START, OBSERVE_END))
    print("=" * 72)

    # ---- coverage -------------------------------------------------------
    dates = sorted(set(r["date"] for r in rows))
    fired = [r for r in rows if r["_fired"]]
    nears = [r for r in rows if not r["_fired"] and r.get("near_miss", "").strip() == "1"]
    print("\nCOVERAGE")
    print("  signal_log: %d rows over %d sessions (%s → %s); %d unparseable dropped"
          % (len(rows), len(dates), dates[0] if dates else "—", dates[-1] if dates else "—", dropped))
    print("  logger shipped mid-window: no rows before %s (observe opened %s)"
          % (dates[0] if dates else "—", OBSERVE_START))
    print("  fired signals: %d   near-misses: %d   other: %d"
          % (len(fired), len(nears), len(rows) - len(fired) - len(nears)))
    print("  graded fwd_5d: %d   fwd_10d: %d   fwd_20d: %d"
          % tuple(sum(1 for r in rows if r["_" + c] is not None)
                  for c in ("fwd_5d", "fwd_10d", "fwd_20d")))
    for d, why in sorted(DEGRADED.items()):
        n = sum(1 for r in rows if r["date"] == d)
        print("  DEGRADED %s (%d rows): %s" % (d, n, why))
    print("  note: %s" % REPAIRED_NOTE)
    print("  verdict_log: %d sessions (%s → %s) — TAIEX baseline for metric C"
          % (len(ver), ver[0]["date"] if ver else "—", ver[-1]["date"] if ver else "—"))

    head = fired if args.include_degraded else [r for r in fired if not r["_degraded"]]
    dg = [r for r in fired if r["_degraded"]]

    # ---- headline: metric A --------------------------------------------
    print("\nPRIMARY — METRIC A: sign(fwd_5d) vs action direction, fired signals only")
    line("ALL FIRED", [hit(r, "fwd_5d") for r in head])
    for a in ("GO", "ADD", "SELL", "TRIM"):
        sub = [r for r in head if r["action"] == a]
        if sub:
            line(a, [hit(r, "fwd_5d") for r in sub])
    for side, sgn in (("GO-side (GO+ADD)", +1), ("SELL-side (SELL+TRIM)", -1)):
        line(side, [hit(r, "fwd_5d") for r in head if r["_dir"] == sgn])
    if dg and not args.include_degraded:
        line("degraded (%d fired, excl.)" % len(dg), [hit(r, "fwd_5d") for r in dg])

    # ---- horizons -------------------------------------------------------
    print("\nSECONDARY — same grading on longer horizons (fired, non-degraded)")
    for c in ("fwd_10d", "fwd_20d"):
        line(c, [hit(r, c) for r in head])
    print("  (fwd_20d matures only for signals fired ≥20 sessions before the review)")

    # ---- metric C -------------------------------------------------------
    tf5 = taiex_forward(ver, 5)
    print("\nSECONDARY — METRIC C: fwd_5d vs TAIEX 5d forward (excess), fired, non-degraded")
    pairs, skipped = [], 0
    for r in head:
        f = r["_fwd_5d"]
        base = tf5.get(r["date"])
        if f is None or base is None or r["_dir"] == 0:
            skipped += 1
            continue
        excess = f - base
        pairs.append(1 if (excess > 0) == (r["_dir"] > 0) and excess != 0 else 0)
    line("excess-return hits", pairs)
    print("  %d fired rows skipped (no TAIEX baseline / ungraded) — partial coverage by design" % skipped)

    # ---- bands ----------------------------------------------------------
    print("\nBREAKDOWN — by |composite| band (fired, non-degraded, fwd_5d)")
    for lo, hi, lbl in COMP_BANDS:
        sub = [r for r in head if r["_comp"] is not None and lo <= abs(r["_comp"]) < hi]
        if sub:
            line(lbl, [hit(r, "fwd_5d") for r in sub])

    print("\nBREAKDOWN — by |L1| band (fired, non-degraded, fwd_5d; Ch.12 spec bands)")
    miss_l1 = 0
    for lo, hi, lbl in L1_BANDS:
        sub = [r for r in head if r["_l1"] is not None and lo <= abs(r["_l1"]) < hi]
        if sub:
            line(lbl, [hit(r, "fwd_5d") for r in sub])
    miss_l1 = sum(1 for r in head if r["_l1"] is None)
    if miss_l1:
        print("  (%d fired rows lack L1 — §14.5-style gaps, excluded here)" % miss_l1)

    # ---- layer attribution ---------------------------------------------
    print("\nATTRIBUTION — per layer: hit-rate when layer sign agrees vs opposes action (fired, fwd_5d)")
    for c in ("l1", "l2", "l3", "l4", "l5"):
        agree, oppose = [], []
        n_missing = n_zero = 0
        for r in head:
            v = r["_" + c]
            if v is None:
                n_missing += 1
                continue
            if v == 0 or r["_dir"] == 0:
                n_zero += 1
                continue
            (agree if (v > 0) == (r["_dir"] > 0) else oppose).append(hit(r, "fwd_5d"))
        if not agree and not oppose:
            why = "all zero-valued" if n_zero and not n_missing else \
                  "dark/unpopulated (%d rows missing)" % n_missing
            print("  %-4s %s — no directional signal to attribute" % (c.upper(), why))
            continue
        print("  %-4s agrees: %s   opposes: %s" % (c.upper(), rate(agree), rate(oppose)))

    # ---- near-miss counterfactuals -------------------------------------
    print("\nNEAR-MISS COUNTERFACTUALS (direction = sign(composite); fwd_5d)")
    line("ALL near-misses", [hit(r, "fwd_5d") for r in nears])
    for reason in ("L1", "L2", "L1+L2"):
        sub = [r for r in nears if r.get("gate_fail_reason", "").strip() == reason]
        if sub:
            line("gate fail: " + reason, [hit(r, "fwd_5d") for r in sub])
    relax = [r for r in nears
             if r.get("gate_fail_reason", "").strip() == "L2"
             and r["_l2"] is not None and 0.35 <= abs(r["_l2"]) < 0.4]
    print("  Ch.12 counterfactual — L2 gate relaxed to 0.35 would flip %d near-miss(es):" % len(relax))
    if relax:
        line("  flipped rows", [hit(r, "fwd_5d") for r in relax], indent=2)
        for r in relax:
            print("      %s %s comp=%s l2=%s fwd_5d=%s"
                  % (r["date"], r["ticker"], r["composite"], r["l2"], r["fwd_5d"] or "—"))
    print("  (flag-correlation query — churn-flagged GOs — not computable: signal_log carries no flag column)")

    # ---- verdict scoreboard --------------------------------------------
    print("\nMARKET VERDICT (verdict_log): directional calls vs same-session TAIEX")
    pairs = []
    for v in ver:
        vd, td = (v.get("verdict_dir") or "").strip(), (v.get("taiex_dir") or "").strip()
        if vd in ("1", "-1") and td in ("1", "-1"):
            pairs.append(1 if vd == td else 0)
    n_neutral = sum(1 for v in ver if (v.get("verdict_dir") or "").strip() == "0")
    line("directional verdicts", pairs)
    print("  neutral verdicts: %d of %d sessions (ungraded)" % (n_neutral, len(ver)))

    print("\nDone. Read-only; nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
