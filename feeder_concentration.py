"""
feeder_concentration.py — 籌碼集中度 (chip concentration) sub-score for L1.

Reads per-stock-per-day broker-branch (券商分點) CSVs dropped into docs/bsr/ and
computes a SIGNED concentration score for the 1 / 5 / 60-day windows.

Design notes (read before changing):
  * Source-of-truth in each file: ticker (證券/股票代碼 line) + market (title line).
    The DATE is NOT in the file — it is read from the filename (…_YYYYMMDD.csv).
  * Two BSR formats are handled:
      TWSE  title '券商買賣股票成交價量資訊'  — TWO records per line, unquoted.
      TPEx  title '券商買賣證券成交價量資訊'  — ONE record per line, quoted.
  * One module serves BOTH the on-demand and the daily-collected modes. It simply
    computes from whatever files exist in docs/bsr/. On-demand = you only drop a
    file for a gate-adjacent candidate (so most tickers have no file → score None →
    L1 rescales per IMPLEMENTATION_GUIDE §1.7). Daily-collected = the 5d/60d windows
    fill in as files accumulate. No code difference between the two.

  * SIGNED vs CMoney magnitude — DIVERGENCE FROM §1.4, stated on purpose:
    CMoney's published number is the *magnitude* (B − S)/vol and its thresholds
    (1d>20%, 5d>6%, 60d>5%) gate "is concentration present?". But L1 needs a
    *directional* score (+ = accumulation, − = distribution). 2330 on 6/11 is the
    textbook case: magnitude is huge (~49%) but it's the SELL side concentrating
    (foreign houses + 凱基台北 dumping), which must score NEGATIVE, not positive.
    So we report BOTH:
        magnitude  = (B − S)/vol         (CMoney number, vs thresholds)
        net_imbal  = (B + S)/vol         (signed: + buyers dominate, − sellers)
        score      = clip(net_imbal / SCALE[window], −1, +1)
    SCALE is a tunable in CONC_SCALE below — calibrate during the observe window;
    the defaults are first-guess, NOT fitted. Flagged again in the handoff.
"""

import csv
import functools
import glob
import json
import os
import re
from collections import defaultdict

# --- tunables (move to config/thresholds.json once calibrated) ------------------
# net-imbalance fraction that maps to a full ±1 score, per window. First-guess only.
CONC_SCALE = {"1d": 0.15, "5d": 0.08, "60d": 0.05}
# CMoney presence thresholds (magnitude), for the "concentration present?" flag only.
CONC_THRESHOLD = {"1d": 0.20, "5d": 0.06, "60d": 0.05}
WINDOWS = {"1d": 1, "5d": 5, "60d": 60}
TOP_N = 15  # top-N buyers / sellers per CMoney definition

_FNAME_DATE = re.compile(r"(\d{8})")          # YYYYMMDD in filename
_LEAD_CODE = re.compile(r"^([0-9A-Za-z]{1,6})")  # leading broker-branch code


def _decode(path):
    raw = open(path, "rb").read()
    for enc in ("big5", "cp950", "utf-8", "big5hkscs"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("big5", errors="replace")


def _branch_code(broker_field):
    """Stable per-分點 key = leading ASCII code (e.g. '1020','9A00','9268')."""
    s = broker_field.replace("\u3000", "").strip()
    m = _LEAD_CODE.match(s)
    return m.group(1) if m else s


@functools.lru_cache(maxsize=None)
def parse_bsr(path):
    """
    Returns (ticker, market, {branch_code: [buy_shares, sell_shares]}, total_vol)
    or None if the file can't be understood. Auto-detects TWSE vs TPEx by content
    (title line is authoritative; filename token is not trusted for format).
    """
    text = _decode(path)
    lines = text.splitlines()
    if len(lines) < 4:
        return None

    title = lines[0]
    is_twse = "股票" in title          # 券商買賣股票…  → TWSE (2 records/line)
    is_tpex = "證券" in title          # 券商買賣證券…  → TPEx (1 record/line)

    # ticker from the code line (authoritative)
    ticker = None
    for ln in lines[1:4]:
        m = re.search(r'(\d{4,6})', ln.replace('="', '').replace('"', ''))
        if m and ("代碼" in ln or "代號" in ln):
            ticker = m.group(1)
            break

    buy = defaultdict(int)
    sell = defaultdict(int)

    def _add(block):
        # block = [序號, 券商, 價格, 買進股數, 賣出股數]
        if len(block) < 5:
            return
        seq = block[0].strip().strip('"')
        if not seq.isdigit():
            return
        code = _branch_code(block[1].strip().strip('"'))
        try:
            b = int(block[3].strip().strip('"') or 0)
            s = int(block[4].strip().strip('"') or 0)
        except ValueError:
            return
        buy[code] += b
        sell[code] += s

    for ln in lines[3:]:
        parts = ln.split(",")
        if is_twse:
            _add([p for p in parts[0:5]])
            _add([p for p in parts[6:11]])
        else:  # TPEx (or unknown → single block)
            _add([p for p in parts[0:5]])

    if not buy:
        return None
    total = sum(buy.values())
    market = "twse" if is_twse else "tpex" if is_tpex else "?"
    branches = {c: [buy[c], sell[c]] for c in buy}
    return ticker, market, branches, total


def _window_conc(day_files):
    """
    Aggregate branch buy/sell across the given day files (a window), then compute
    top-15 concentration. Returns dict or None.
    """
    buy = defaultdict(int)
    sell = defaultdict(int)
    total = 0
    used = 0
    for f in day_files:
        parsed = parse_bsr(f)
        if not parsed:
            continue
        _t, _m, branches, tot = parsed
        for c, (b, s) in branches.items():
            buy[c] += b
            sell[c] += s
        total += tot
        used += 1
    if used == 0 or total == 0:
        return None
    net = {c: buy[c] - sell[c] for c in buy}
    top_buy = sorted(net.values(), reverse=True)[:TOP_N]
    top_sell = sorted(net.values())[:TOP_N]
    B = sum(v for v in top_buy if v > 0)
    S = sum(v for v in top_sell if v < 0)   # negative
    magnitude = (B - S) / total             # CMoney number (≥0)
    net_imbal = (B + S) / total             # signed: + buyers, − sellers
    return {
        "magnitude": round(magnitude, 4),
        "net_imbal": round(net_imbal, 4),
        "days_used": used,
        "total_vol": total,
    }


def _files_for(bsr_dir, ticker, market):
    """All dated files for one ticker/market, newest first, with their dates."""
    out = []
    for path in glob.glob(os.path.join(bsr_dir, "*.csv")):
        parsed = parse_bsr(path)
        if not parsed:
            continue
        t, m, _b, _tot = parsed
        if t != ticker or (m != market and market != "?"):
            continue
        md = _FNAME_DATE.search(os.path.basename(path))
        if not md:
            continue  # date MUST be in filename
        out.append((md.group(1), path))
    out.sort(reverse=True)  # newest date first
    return out


def concentration_for(bsr_dir, ticker, market):
    """
    Full concentration result for one ticker, across all available windows.
    Returns None if no usable files (→ caller treats score as unavailable, NOT 0).
    """
    dated = _files_for(bsr_dir, ticker, market)
    if not dated:
        return None
    paths = [p for _d, p in dated]
    result = {"ticker": ticker, "market": market, "asof": dated[0][0],
              "files_available": len(paths), "windows": {}, "score": None,
              "score_window": None, "present": False, "direction": 0}

    for wname, wlen in WINDOWS.items():
        w = _window_conc(paths[:wlen])
        if not w:
            continue
        scale = CONC_SCALE[wname]
        wscore = max(-1.0, min(1.0, w["net_imbal"] / scale))
        present = w["magnitude"] >= CONC_THRESHOLD[wname]
        # a window is only "adequately filled" if we have enough real days for it
        adequate = w["days_used"] >= max(1, round(0.6 * wlen))
        result["windows"][wname] = {**w, "score": round(wscore, 3),
                                    "present": present, "adequate": adequate}

    # Headline = the LONGEST adequately-filled window (most reliable per CMoney),
    # falling back to shorter. With on-demand single drops this is honestly "1d".
    for wname in ("60d", "5d", "1d"):
        w = result["windows"].get(wname)
        if w and w["adequate"]:
            result["score"] = w["score"]
            result["present"] = w["present"]
            result["score_window"] = wname
            result["direction"] = 1 if w["score"] > 0 else -1 if w["score"] < 0 else 0
            break
    return result


def compute_all(bsr_dir="docs/bsr", tickers=None):
    """
    Compute concentration for every ticker that has at least one file in bsr_dir
    (or only the given tickers). Returns {ticker: result}. Missing tickers are
    simply absent (last-known-good: never fabricate a 0 score).
    """
    seen = {}
    for path in glob.glob(os.path.join(bsr_dir, "*.csv")):
        parsed = parse_bsr(path)
        if not parsed:
            continue
        t, m, _b, _tot = parsed
        if t:
            seen[t] = m
    out = {}
    for t, m in seen.items():
        if tickers and t not in tickers:
            continue
        r = concentration_for(bsr_dir, t, m)
        if r:
            out[t] = r
    return out


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "docs/bsr"
    res = compute_all(d)
    print(json.dumps(res, ensure_ascii=False, indent=2))
