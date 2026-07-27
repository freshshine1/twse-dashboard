#!/usr/bin/env python3
"""feeder_intraday.py — MIS intraday fetch for the Intraday cross-reference tab (Ch.16).

Display-only LEAF module. It never imports from, or writes to, feeder.py / score.py /
docs/data.json, and nothing here feeds the composite or the confluence gate (Ch.10 wall).

Flow (runs on the `main` checkout inside intraday.yml, every ~5 min during market hours):
  docs/data.json (last night's board)  ->  ticker universe (portfolio + watchlist)
  -> ONE batched MIS getStockInfo.jsp call (tse_/otc_ prefixes by the board's `exchange`)
  -> parse with hard guards (z can be '-', book levels can be '-'/empty)
  -> write intraday.json (workflow pushes it to the un-served `data` branch)

Failure semantics:
  - Outside 09:00-13:30 TPE, or on weekends: exit 0 with a log line, write nothing.
  - MIS says it's not a trading session today (holiday): exit 0 with a log line.
  - Fetch/parse failure DURING market hours on a trading day: exit 1 (fail-loud).

Session stamping follows the house rule: the `session` field comes from the data itself
(MIS per-item trade date `d`), wall-clock only as fallback.

Self-test (offline, no network): python feeder_intraday.py --selftest
"""

import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
BOARD_PATH = "docs/data.json"
OUT_PATH = "intraday.json"

ATTEMPTS = 3
BACKOFF = [5, 15]          # seconds between attempts
TIMEOUT = 10

MARKET_OPEN = (9, 0)
# 14:00, not 13:30: the closing auction settles at 13:30 and MIS serves the
# OFFICIAL close (field z) for a few minutes after. Extending the window to
# 14:00 lets the post-close tick overwrite the last continuous-session price
# with the settled close, so intraday.json carries a real 收盤價 by end of run.
# Continuous trading still ends 13:30; ticks in 13:30-14:00 only refresh the close.
MARKET_CLOSE = (14, 0)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("intraday")


# ------------------------------------------------------------------ helpers

def in_market_hours(now):
    """True on Mon-Fri between 09:00 and 13:30 TPE (inclusive open, exclusive close)."""
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (MARKET_OPEN[0] * 60 + MARKET_OPEN[1]) <= minutes < (MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1])


def _f(val):
    """Float or None. MIS uses '-' (and sometimes '') for no-trade / empty cells."""
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _levels(s):
    """Split an underscore-delimited MIS book string into floats, dropping '-'/empty cells.
    Order is preserved (MIS lists best level first). Never assumes 5 clean levels."""
    if not s:
        return []
    out = []
    for cell in str(s).split("_"):
        v = _f(cell)
        if v is not None:
            out.append(v)
    return out


# ------------------------------------------------------------------ universe

def load_universe(board_path=BOARD_PATH):
    """Read (ticker, exchange, name_zh, prev_vol_shares) from the board.
    Portfolio first, then watchlist; deduped on ticker (first occurrence wins).
    Universe always tracks the board — no separate list to maintain."""
    with open(board_path, encoding="utf-8") as fh:
        board = json.load(fh)
    seen = {}
    for bucket in ("portfolio", "watchlist"):
        for row in board.get(bucket, []):
            tk = str(row.get("ticker", "")).strip()
            if not tk or tk in seen:
                continue
            seen[tk] = {
                "ticker": tk,
                "exchange": row.get("exchange") or "TWSE",
                "name_zh": row.get("name_zh") or row.get("name") or tk,
                "prev_vol_shares": row.get("vol_today"),  # prior session's total, in SHARES
            }
    return list(seen.values())


def build_ex_ch(universe):
    """tse_2330.tw|otc_6488.tw — prefix keyed off the board's own exchange field."""
    parts = []
    for u in universe:
        prefix = "otc_" if u["exchange"] == "TPEx" else "tse_"
        parts.append(f"{prefix}{u['ticker']}.tw")
    return "|".join(parts)


# ------------------------------------------------------------------ fetch

def fetch_mis(ex_ch):
    """One batched MIS GET. Returns msgArray on success, raises RuntimeError on exhaustion."""
    import requests  # imported here so --selftest needs no network deps
    params = {"ex_ch": ex_ch, "json": "1", "delay": "0"}
    last_err = None
    for attempt in range(ATTEMPTS):
        try:
            r = requests.get(MIS_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if data.get("rtcode") == "0000":
                return data.get("msgArray", [])
            last_err = f"rtcode={data.get('rtcode')!r}"
        except Exception as e:  # noqa: BLE001 — retry loop, re-raised on exhaustion
            last_err = repr(e)
        if attempt < ATTEMPTS - 1:
            wait = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            log.warning("MIS attempt %d/%d failed (%s) — retrying in %ds",
                        attempt + 1, ATTEMPTS, last_err, wait)
            time.sleep(wait)
    raise RuntimeError(f"MIS unusable after {ATTEMPTS} attempts: {last_err}")


# ------------------------------------------------------------------ parse

def parse_item(item, meta):
    """One MIS msgArray item + its universe meta -> one intraday row dict.
    Every field is guarded; a missing/no-trade field is None, never a crash."""
    prev = _f(item.get("y"))

    cum_v = _f(item.get("v"))  # cumulative volume, 張 (lots)

    rel_vol = None
    pv = meta.get("prev_vol_shares")
    if cum_v is not None and pv:
        try:
            prev_lots = float(pv) / 1000.0  # board stores SHARES; MIS v is 張
            if prev_lots > 0:
                rel_vol = round(cum_v / prev_lots, 2)
        except (TypeError, ValueError):
            rel_vol = None

    # Zero-price guard (2026-07-07 live finding, 3363 halted/special state):
    # MIS can emit 0.00 price levels; a zero is never a price — drop like '-'.
    ask_prices = [p for p in _levels(item.get("a")) if p > 0]
    ask_sizes = _levels(item.get("f"))
    bid_prices = [p for p in _levels(item.get("b")) if p > 0]
    bid_sizes = _levels(item.get("g"))

    sum_ask = sum(ask_sizes)
    sum_bid = sum(bid_sizes)
    denom = sum_ask + sum_bid
    book_imbalance = round((sum_bid - sum_ask) / denom, 3) if denom > 0 else None

    # Last-price fallback (2026-07-06 live finding): MIS `z` reads '-' between
    # matches even on liquid names (24/26 rows blank at 09:47 on day one).
    # Chain: z (trade) -> pz (last matched) -> book mid -> single-sided best.
    # Display-only; never feeds scoring (Ch.10 wall).
    def _pos(x):
        return x if (x is not None and x > 0) else None

    last, last_src = _pos(_f(item.get("z"))), "z"
    if last is None:
        last, last_src = _pos(_f(item.get("pz"))), "pz"
    if last is None:
        if bid_prices and ask_prices:
            last, last_src = round((bid_prices[0] + ask_prices[0]) / 2, 2), "mid"
        elif bid_prices:
            last, last_src = bid_prices[0], "bid"
        elif ask_prices:
            last, last_src = ask_prices[0], "ask"
        else:
            last_src = None
    chg_pct = round((last / prev - 1) * 100, 2) if (last is not None and prev) else None

    return {
        "ticker": meta["ticker"],
        "name_zh": meta["name_zh"],
        "last": last,
        "last_src": last_src,   # z | pz | mid | bid | ask | None
        "prev": prev,
        "chg_pct": chg_pct,
        "cum_v": cum_v,
        "rel_vol": rel_vol,          # vs 昨日全日量 (v1 label — same-time-yesterday later)
        "book_imbalance": book_imbalance,  # (Σbid − Σask)/(Σbid + Σask); + = bid-heavy
        "best_bid": bid_prices[0] if bid_prices else None,
        "best_ask": ask_prices[0] if ask_prices else None,
    }


def session_from_items(items, fallback_iso):
    """Trading-session date from the data itself (MIS `d`, YYYYMMDD) — house rule.
    Wall-clock fallback only if no item carries a parseable date."""
    for it in items:
        d = str(it.get("d") or "").strip()
        if len(d) == 8 and d.isdigit():
            return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return fallback_iso


# ------------------------------------------------------------------ main

def main():
    now = datetime.now(TZ)
    today_iso = now.date().isoformat()

    if not in_market_hours(now):
        log.info("Outside market hours (%s TPE) — no-op, exit green.", now.strftime("%a %H:%M"))
        return 0

    # After 13:30 TPE the continuous session has closed and MIS is serving the
    # settled auction close; before it, prices are live continuous-session ticks.
    # Stamp this so the dashboard overlay can label the number (收盤 vs 盤中).
    after_close = (now.hour * 60 + now.minute) >= (13 * 60 + 30)

    try:
        universe = load_universe()
    except Exception as e:  # noqa: BLE001
        log.error("Cannot read board universe from %s: %r", BOARD_PATH, e)
        return 1
    if not universe:
        log.error("Board universe is empty — refusing to write.")
        return 1

    ex_ch = build_ex_ch(universe)
    log.info("Fetching MIS for %d tickers (one call).", len(universe))
    try:
        items = fetch_mis(ex_ch)
    except RuntimeError as e:
        log.error("%s — market hours on a weekday, failing LOUD.", e)
        return 1

    session = session_from_items(items, today_iso)
    if session != today_iso:
        # Weekday but MIS says the live session isn't today => market holiday. Benign.
        log.info("MIS session %s != today %s — non-trading day, no write, exit green.",
                 session, today_iso)
        return 0

    by_code = {str(it.get("c", "")).strip(): it for it in items}
    rows, missing = [], []
    for meta in universe:
        item = by_code.get(meta["ticker"])
        if item is None:
            missing.append(meta["ticker"])
            continue
        try:
            rows.append(parse_item(item, meta))
        except Exception as e:  # noqa: BLE001 — one bad item must not kill the batch
            log.warning("Parse failed for %s: %r — skipped.", meta["ticker"], e)
            missing.append(meta["ticker"])
    if missing:
        log.warning("No MIS row for %d tickers: %s", len(missing), ",".join(missing))
    if not rows:
        log.error("Zero rows parsed — refusing to write an empty file, failing LOUD.")
        return 1

    payload = {
        "updated": now.isoformat(timespec="seconds"),
        "session": session,
        "phase": "close" if after_close else "intraday",
        "rows": rows,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    log.info("Wrote %s: %d rows, session %s.", OUT_PATH, len(rows), session)
    return 0


# ------------------------------------------------------------------ selftest

SAMPLE_ITEMS = [
    {   # normal TWSE name, 5 clean levels
        "c": "2330", "d": "20260703", "z": "1085.00", "y": "1080.00", "v": "21033",
        "a": "1085.00_1090.00_1095.00_1100.00_1105.00", "f": "1200_800_650_400_300",
        "b": "1080.00_1075.00_1070.00_1065.00_1060.00", "g": "900_1100_700_500_450",
    },
    {   # no trade yet: z='-' ; book present
        "c": "3131", "d": "20260703", "z": "-", "y": "500.00", "v": "0",
        "a": "501.00_502.00_503.00_504.00_505.00", "f": "10_20_30_40_50",
        "b": "499.00_498.00_497.00_496.00_495.00", "g": "15_25_35_45_55",
    },
    {   # z='-' but pz carries the last matched price; book fully empty
        "c": "9999", "d": "20260703", "z": "-", "pz": "88.80", "y": "88.00", "v": "12",
        "a": "-", "f": "-", "b": "-", "g": "-",
    },
    {   # halted/special state (seen live on 3363 2026-07-07): zero bids, no asks
        "c": "3363", "d": "20260707", "z": "-", "y": "581.00", "v": "0",
        "a": "-", "f": "-", "b": "0.00_0.00_0.00_0.00_0.00", "g": "0_0_0_0_0",
    },
    {   # OTC name with a MISSING top ask level (seen live on otc_6488)
        "c": "6488", "d": "20260703", "z": "620.00", "y": "615.00", "v": "5310",
        "a": "-_621.00_622.00_623.00_624.00", "f": "-_50_60_70_80",
        "b": "619.00_618.00_617.00_616.00_615.00", "g": "40_45_50_55_60",
    },
]

SAMPLE_META = {
    "2330": {"ticker": "2330", "name_zh": "台積電", "prev_vol_shares": 37544470.0},
    "3131": {"ticker": "3131", "name_zh": "弘塑", "prev_vol_shares": None},
    "6488": {"ticker": "6488", "name_zh": "環球晶", "prev_vol_shares": 8000000.0},
}


def selftest():
    r1 = parse_item(SAMPLE_ITEMS[0], SAMPLE_META["2330"])
    assert r1["last"] == 1085.0 and r1["last_src"] == "z" and r1["prev"] == 1080.0, r1
    assert r1["chg_pct"] == 0.46, r1
    assert r1["rel_vol"] == round(21033 / 37544.47, 2), r1
    assert r1["best_bid"] == 1080.0 and r1["best_ask"] == 1085.0, r1
    exp = round((3650 - 3350) / (3650 + 3350), 3)
    assert r1["book_imbalance"] == exp, (r1["book_imbalance"], exp)

    r2 = parse_item(SAMPLE_ITEMS[1], SAMPLE_META["3131"])
    assert r2["last"] == 500.0 and r2["last_src"] == "mid", r2       # z='-' -> book mid
    assert r2["chg_pct"] == 0.0, r2
    assert r2["rel_vol"] is None, r2                                  # prev vol None guarded
    assert r2["best_ask"] == 501.0 and r2["best_bid"] == 499.0, r2

    r3 = parse_item(SAMPLE_ITEMS[4], SAMPLE_META["6488"])
    assert r3["best_ask"] == 621.0, r3                # '-' top level dropped, next level used
    a_sz, b_sz = 50 + 60 + 70 + 80, 40 + 45 + 50 + 55 + 60
    assert r3["book_imbalance"] == round((b_sz - a_sz) / (b_sz + a_sz), 3), r3

    r4 = parse_item(SAMPLE_ITEMS[2], {"ticker": "9999", "name_zh": "測試", "prev_vol_shares": None})
    assert r4["last"] == 88.8 and r4["last_src"] == "pz", r4         # z='-' -> pz
    assert r4["chg_pct"] == 0.91, r4
    assert r4["best_bid"] is None and r4["best_ask"] is None, r4     # empty book guarded

    r5 = parse_item(SAMPLE_ITEMS[3], {"ticker": "3363", "name_zh": "上詮", "prev_vol_shares": None})
    assert r5["last"] is None and r5["last_src"] is None, r5         # zero bids dropped
    assert r5["chg_pct"] is None and r5["best_bid"] is None, r5

    assert session_from_items(SAMPLE_ITEMS, "1999-01-01") == "2026-07-03"
    assert session_from_items([{"d": "-"}], "1999-01-01") == "1999-01-01"

    ex = build_ex_ch([
        {"ticker": "2330", "exchange": "TWSE"},
        {"ticker": "6488", "exchange": "TPEx"},
    ])
    assert ex == "tse_2330.tw|otc_6488.tw", ex

    assert in_market_hours(datetime(2026, 7, 3, 9, 0, tzinfo=TZ)) is True
    assert in_market_hours(datetime(2026, 7, 3, 13, 30, tzinfo=TZ)) is False
    assert in_market_hours(datetime(2026, 7, 4, 10, 0, tzinfo=TZ)) is False  # Saturday

    print("SELFTEST PASS — 5 sample rows, guards, prefixes, session, market-hours all OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    sys.exit(main())
