#!/usr/bin/env python3
"""
feeder.py — TWSE daily data feeder for twse-dashboard
Runs via GitHub Actions at 16:30 TPE on weekdays.
Writes docs/data.json (merges analysis.json if present).

Changes vs ea1b636 (run #24):
  - FIX: watchlist/portfolio were being written as empty lists because the
    per-ticker loop appended to a local `watchlist` variable that shadowed
    the outer scope after the T86 refactor. Renamed loop var to `ticker_rows`.
  - FIX: T86 per-ticker now correctly attached to each ticker entry.
  - ADD: foreign_streak / trust_streak — consecutive net-buy(+) or net-sell(-)
    days derived from the 5-day T86 history. Positive = consecutive buys,
    negative = consecutive sells, 0 = mixed.
  - ADD: L1 composite score (foundation layer, ∈ [-1,+1]) — T86_score weighted
    by 投信 50 / 外資 30 / 自營商 20, normalised against float proxies.
    concentration_score, broker_score, margin_score stubs return 0 until BSR
    data is wired; L1 = 0.50*T86_score + 0 + 0 + 0 today.
  - ADD: signal_score integer (-4..+4) for UI badge/sort — maps L1 + technical
    trend into a single number the front-end can use without knowing L1.
  - KEEP: all existing fields, market block, analysis merge, BFI82U prev-day.
"""

import json
import logging
import logging.handlers
import math
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

# ── Config ────────────────────────────────────────────────────────────────────

TZ = ZoneInfo("Asia/Taipei")

# Each entry: (code, name_en, name_zh, sector, bucket, shares_float_m)
# bucket: "portfolio" | "watchlist"
# shares_float_m: approximate free-float shares in millions — used for L1
#   normalisation. Set to None to skip normalisation (score will be coarser).
#   Update these when you add/remove positions.
UNIVERSE = [
    # ── Portfolio (holdings) ──────────────────────────────────────────────────
    ("2330", "TSMC",              "台積電",   "SEMI",  "portfolio", 25_930),
    ("2317", "Hon Hai",           "鴻海",     "ELEC",  "portfolio", 138_000),
    # ── Watchlist ─────────────────────────────────────────────────────────────
    ("2454", "MediaTek",          "聯發科",   "SEMI",  "watchlist",  15_900),
    ("2382", "Quanta",            "廣達",     "ELEC",  "watchlist",  13_800),
    ("2303", "UMC",               "聯電",     "SEMI",  "watchlist",  47_400),
    ("6505", "Formosa Petro",     "台塑化",   "PETRO", "watchlist",  25_300),
    ("2002", "China Steel",       "中鋼",     "STEEL", "watchlist",  97_300),
    ("1301", "Formosa Plastics",  "台塑",     "PETRO", "watchlist",  63_800),
    ("2881", "Fubon FHC",         "富邦金",   "FIN",   "watchlist",  72_600),
    ("2882", "Cathay FHC",        "國泰金",   "FIN",   "watchlist", 116_200),
    ("0050", "Taiwan 50 ETF",     "元大台灣50","ETF",  "watchlist",   6_800),
    ("0056", "Hi-Div ETF",        "元大高股息","ETF",  "watchlist",  23_000),
]

# TPEx tickers — fetched from TPEx openapi instead of TWSE T86
TPEX_CODES = set()  # e.g. {"3324", "5274", "6223"} — add OTC holdings here

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "twse-dashboard-feeder/1.0 (github.com/freshshine1/twse-dashboard)"
})
REQUEST_DELAY = 1.0   # seconds between TWSE calls — be polite
T86_DAYS     = 5      # rolling window for streak + T86_score

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging():
    logger = logging.getLogger("feeder")
    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.RotatingFileHandler(
        "feeder.log", maxBytes=100_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    stdout_h = logging.StreamHandler(sys.stdout)
    stdout_h.setLevel(logging.INFO)
    stdout_h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(stdout_h)
    return logger

log = setup_logging()

# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_float(val, default=None):
    if val is None:
        return default
    s = str(val).replace(",", "").strip()
    if s in ("--", "-", ""):
        return default
    try:
        return float(s)
    except ValueError:
        return default

def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")

def twse_get(url, label="", retries=3, backoff=5):
    for attempt in range(1, retries + 1):
        try:
            time.sleep(REQUEST_DELAY)
            r = SESSION.get(url, timeout=20)
            r.raise_for_status()
            data = r.json()
            stat = data.get("stat", "OK") if isinstance(data, dict) else "OK"
            if stat not in ("OK", ""):
                log.warning("%s — stat=%s (attempt %d)", label or url, stat, attempt)
                if attempt < retries:
                    time.sleep(backoff * attempt)
                continue
            return data
        except Exception as exc:
            log.warning("%s — attempt %d failed: %s", label or url, attempt, exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
    log.error("%s — all retries exhausted", label or url)
    return None

def _sign(x):
    if x is None or x == 0:
        return 0
    return 1 if x > 0 else -1

def _streak(daily_nets):
    """
    Given a list of daily net values oldest→newest, return the streak of the
    most recent direction.  e.g. [+10, +5, +8] → +3 (3 consecutive buys)
                                  [+10, -2, -5] → -2 (2 consecutive sells)
                                  []            →  0
    """
    if not daily_nets:
        return 0
    direction = _sign(daily_nets[-1])
    if direction == 0:
        return 0
    count = 0
    for v in reversed(daily_nets):
        if _sign(v) == direction:
            count += 1
        else:
            break
    return count * direction

# ── TAIEX ─────────────────────────────────────────────────────────────────────

def fetch_taiex():
    url = "https://www.twse.com.tw/exchangeReport/FMTQIK?response=json"
    data = twse_get(url, "TAIEX", retries=5, backoff=8)
    if not data:
        return None, None, None
    rows = data.get("data", [])
    if not rows:
        return None, None, None
    last = rows[-1]
    try:
        taiex     = safe_float(last[4])
        taiex_chg = safe_float(last[5])
        taiex_chg_pct = round(taiex_chg / (taiex - taiex_chg) * 100, 2) if taiex and taiex_chg else None
        return taiex, taiex_chg, taiex_chg_pct
    except Exception as exc:
        log.warning("TAIEX parse error: %s", exc)
        return None, None, None

# ── BFI82U — market-level institutional flow ──────────────────────────────────

def _parse_bfi82u(data):
    """Extract foreign / dealer / trust net (NT$ millions) from a BFI82U response."""
    result = {"foreign": 0.0, "dealer": 0.0, "trust": 0.0}
    if not data:
        return result
    for row in data.get("data", []):
        name = row[0].strip()
        net  = safe_float(row[3], 0.0) / 1_000_000
        if "外資及陸資" in name and "不含" not in name:
            result["foreign"] = round(net, 2)
        elif "自營商" in name and "避險" not in name and "自行" not in name:
            result["dealer"]  = round(net, 2)
        elif "投信" in name:
            result["trust"]   = round(net, 2)
    return result

def fetch_institutional_today():
    url  = "https://www.twse.com.tw/fund/BFI82U?response=json&dayDate=&type=day"
    data = twse_get(url, "BFI82U today")
    r    = _parse_bfi82u(data)
    r["total"] = round(r["foreign"] + r["dealer"] + r["trust"], 2)
    return r

def fetch_institutional_prev():
    """Fetch prior trading day BFI82U — walk back up to 5 calendar days."""
    candidate = datetime.now(TZ).date() - timedelta(days=1)
    for _ in range(7):
        if candidate.weekday() < 5:
            date_str = candidate.strftime("%Y%m%d")
            url  = f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={date_str}&type=day"
            data = twse_get(url, f"BFI82U prev {date_str}", retries=2, backoff=3)
            if data and data.get("data"):
                return _parse_bfi82u(data)
        candidate -= timedelta(days=1)
    return {"foreign": None, "dealer": None, "trust": None}

def pressure_label(foreign_net_m):
    if   foreign_net_m is None:    return "N/A"
    if   foreign_net_m > 20_000:   return "Strong Buy"
    elif foreign_net_m > 5_000:    return "Buy"
    elif foreign_net_m < -20_000:  return "Strong Sell"
    elif foreign_net_m < 0:        return "Net Sell"
    else:                          return "Neutral"

# ── T86 per-ticker — TWSE ────────────────────────────────────────────────────

def _trading_days_back(n):
    """Return list of date strings (YYYYMMDD) for the last n trading days."""
    days = []
    candidate = datetime.now(TZ).date()
    attempts  = 0
    while len(days) < n and attempts < n * 3:
        attempts += 1
        if candidate.weekday() < 5:
            days.append(candidate.strftime("%Y%m%d"))
        candidate -= timedelta(days=1)
    return list(reversed(days))  # oldest → newest

def fetch_t86_for_date(date_str, target_codes):
    """
    Pull TWSE T86 for one date. Returns dict:
      code → {foreign_net, trust_net, dealer_net, inst_net}  (shares, thousands)
    Only returns rows whose code is in target_codes.
    """
    url  = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALL"
    data = twse_get(url, f"T86 {date_str}", retries=2, backoff=4)
    if not data:
        return {}

    result = {}
    for row in data.get("data", []):
        # T86 row layout (19+ cols):
        # [0] 證券代號, [1] 證券名稱,
        # [2] 外資買進, [3] 外資賣出, [4] 外資淨買賣超,
        # [5] 投信買進, [6] 投信賣出, [7] 投信淨買賣超,
        # [8] 自營商買進(自行), [9] 自營商賣出(自行), [10] 自營商淨(自行),
        # [11] 自營商買進(避險), [12] 自營商賣出(避險), [13] 自營商淨(避險),
        # [14] 自營商買進合計, [15] 自營商賣出合計, [16] 自營商淨合計,
        # [17] 三大法人買賣超合計  (some rows have 18 or 19 cols)
        if len(row) < 18:
            continue
        code = row[0].strip()
        if code not in target_codes:
            continue
        foreign_net = safe_float(row[4],  0.0)
        trust_net   = safe_float(row[7],  0.0)
        dealer_net  = safe_float(row[16], 0.0)
        inst_net    = round(foreign_net + trust_net + dealer_net, 0)
        result[code] = {
            "foreign_net": foreign_net,
            "trust_net":   trust_net,
            "dealer_net":  dealer_net,
            "inst_net":    inst_net,
        }
    return result

def fetch_t86_rolling(target_codes, days=T86_DAYS):
    """
    Fetch T86 for the last `days` trading days for all target_codes.
    Returns dict:  code → list of daily dicts oldest→newest (missing days = None entry)
    """
    date_list = _trading_days_back(days)
    # accumulated: code → [day0, day1, ... dayN-1]  (oldest→newest)
    accumulated = {code: [] for code in target_codes}

    for date_str in date_list:
        daily = fetch_t86_for_date(date_str, target_codes)
        for code in target_codes:
            accumulated[code].append(daily.get(code))  # None if not in response

    return accumulated

def derive_t86_fields(rolling):
    """
    Given rolling dict (code → list of day dicts, oldest→newest),
    compute summary fields for each code.
    Returns dict: code → {
        foreign_net, trust_net, dealer_net, inst_net,   # today (last day)
        foreign_3d, foreign_5d,                         # cumulative
        trust_3d,   trust_5d,
        foreign_streak, trust_streak,                   # consecutive direction
    }
    """
    out = {}
    for code, days in rolling.items():
        today = days[-1] if days else None

        def sum_field(field, n):
            vals = [d[field] for d in days[-n:] if d and d.get(field) is not None]
            return round(sum(vals), 0) if vals else None

        def streak_field(field):
            vals = [d[field] for d in days if d and d.get(field) is not None]
            return _streak(vals)

        out[code] = {
            # today
            "foreign_net":    today["foreign_net"]  if today else None,
            "trust_net":      today["trust_net"]    if today else None,
            "dealer_net":     today["dealer_net"]   if today else None,
            "inst_net":       today["inst_net"]     if today else None,
            # cumulative
            "foreign_3d":     sum_field("foreign_net", 3),
            "foreign_5d":     sum_field("foreign_net", 5),
            "trust_3d":       sum_field("trust_net",   3),
            "trust_5d":       sum_field("trust_net",   5),
            # streaks (positive = consecutive buys, negative = consecutive sells)
            "foreign_streak": streak_field("foreign_net"),
            "trust_streak":   streak_field("trust_net"),
        }
    return out

# ── TPEx per-ticker (placeholder — TWSE path confirmed, TPEx to verify) ──────

def fetch_tpex_t86_for_date(date_str, target_codes):
    """
    TPEx institutional endpoint. Field names differ from TWSE T86.
    Returns same shape as fetch_t86_for_date.
    NOTE: field positions unverified live — will return {} until confirmed.
    """
    url  = f"https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_trading_info?date={date_str}"
    data = twse_get(url, f"TPEx T86 {date_str}", retries=2, backoff=4)
    if not data or not isinstance(data, list):
        return {}
    result = {}
    for row in data:
        code = str(row.get("SecuritiesCompanyCode", "")).strip()
        if code not in target_codes:
            continue
        # TPEx openapi returns dict rows — field names TBC from live response
        # Stub: log what fields come back so we can fix next run
        log.debug("TPEx row fields for %s: %s", code, list(row.keys()))
    return result

# ── Historical OHLCV + technicals ─────────────────────────────────────────────

def fetch_history(ticker, months=3):
    now     = datetime.now(TZ)
    all_rows = []
    dt = now.replace(day=1)
    for m in range(months - 1, -1, -1):
        target_dt  = (dt - timedelta(days=1) * (m > 0) * 28).replace(day=1) if m else dt
        # simpler: step back month by month
        step = now
        for _ in range(m):
            step = (step.replace(day=1) - timedelta(days=1)).replace(day=1)
        date_str = step.strftime("%Y%m01")

        url  = (f"https://www.twse.com.tw/exchangeReport/STOCK_DAY"
                f"?response=json&date={date_str}&stockNo={ticker}")
        data = twse_get(url, f"{ticker} history {date_str}")
        if not data:
            continue
        for row in data.get("data", []):
            try:
                parts       = row[0].split("/")
                western_year = int(parts[0]) + 1911
                date_obj    = datetime(western_year, int(parts[1]), int(parts[2]))
                all_rows.append({
                    "date":   date_obj,
                    "open":   safe_float(row[3]),
                    "high":   safe_float(row[4]),
                    "low":    safe_float(row[5]),
                    "close":  safe_float(row[6]),
                    "volume": safe_float(row[1]),
                })
            except Exception as exc:
                log.debug("%s row parse skip: %s | %s", ticker, exc, row)

    seen, unique = set(), []
    for r in sorted(all_rows, key=lambda x: x["date"]):
        if r["date"] not in seen:
            seen.add(r["date"])
            unique.append(r)
    return unique

def sma(closes, n):
    if len(closes) < n:
        return None
    return round(sum(closes[-n:]) / n, 2)

def compute_technicals(history, snapshot_close):
    closes = [r["close"] for r in history if r["close"] is not None]
    if not closes:
        return {}
    ma5  = sma(closes, 5)
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    price = snapshot_close if snapshot_close is not None else (closes[-1] if closes else None)

    vols      = [r["volume"] for r in history if r["volume"] is not None]
    vol_today = vols[-1] if vols else None
    avg5v     = sum(vols[-5:]) / 5 if len(vols) >= 5 else None
    vol_ratio = round(vol_today / avg5v, 2) if (vol_today and avg5v) else None

    all_highs = [r["high"] for r in history if r["high"] is not None]
    all_lows  = [r["low"]  for r in history if r["low"]  is not None]
    high_52w  = max(all_highs) if all_highs else None
    low_52w   = min(all_lows)  if all_lows  else None
    pct_from_52w_high = (
        round((price - high_52w) / high_52w * 100, 2)
        if (price and high_52w) else None
    )

    trend = "MIXED-"
    if price and ma5 and ma20 and ma60:
        if   price > ma5 > ma20 > ma60: trend = "BULL"
        elif price < ma5 < ma20 < ma60: trend = "BEAR"
        elif price > ma20:              trend = "MIXED+"

    return {
        "ma5": ma5, "ma20": ma20, "ma60": ma60,
        "vol_ratio": vol_ratio,
        "high_52w": high_52w, "low_52w": low_52w,
        "pct_from_52w_high": pct_from_52w_high,
        "trend": trend,
    }

# ── L1 composite score ────────────────────────────────────────────────────────

def compute_l1_score(t86_fields, float_m):
    """
    L1 ∈ [-1, +1].  Only T86_score wired today; concentration/broker/margin
    stubs return 0 until BSR data is added.

    float_m: free-float shares in millions. None → skip normalisation (raw clip).

    T86_score normalisation caps:
      投信: 2% of float   (mid-cap focus, accumulation visible quickly)
      外資: 0.5% of float (large-cap, higher daily turnover)
      自營商: 1% of float (noisy — lower weight)
    """
    if not t86_fields:
        return None

    def norm(net, cap_pct):
        """Normalise net shares against float. Returns value in [-1, +1]."""
        if net is None:
            return 0.0
        if float_m and float_m > 0:
            float_shares = float_m * 1_000  # thousands (T86 unit)
            cap = float_shares * cap_pct
            if cap == 0:
                return 0.0
            return max(-1.0, min(1.0, net / cap))
        else:
            # No float data — clip raw net to ±10,000 thousand shares
            return max(-1.0, min(1.0, net / 10_000))

    foreign_5d = t86_fields.get("foreign_5d") or 0.0
    trust_5d   = t86_fields.get("trust_5d")   or 0.0
    dealer_5d  = (t86_fields.get("dealer_net") or 0.0) * 5  # approximate 5d from today

    t86_score = (
        0.50 * _sign(trust_5d)   * abs(norm(trust_5d,   0.02))
      + 0.30 * _sign(foreign_5d) * abs(norm(foreign_5d, 0.005))
      + 0.20 * _sign(dealer_5d)  * abs(norm(dealer_5d,  0.01))
    )
    t86_score = max(-1.0, min(1.0, t86_score))

    # Stubs — will be replaced when BSR / margin data is wired
    concentration_score = 0.0   # TODO: BSR 個股券商買賣明細
    broker_score        = 0.0   # TODO: 隔日沖 behavioral detection
    margin_score        = 0.0   # TODO: 融資融券 MI_MARGN

    l1 = (
        0.50 * t86_score
      + 0.20 * concentration_score
      + 0.20 * broker_score
      + 0.10 * margin_score
    )
    return round(max(-1.0, min(1.0, l1)), 3)

def compute_signal_score(l1, trend):
    """
    signal_score ∈ [-4, +4] — integer for badge / sort.
    Maps L1 chip + technical trend into a single display number.
    Positive = bullish lean, negative = bearish, 0 = neutral.
    """
    score = 0

    # Technical trend contribution (±2)
    if trend == "BULL":    score += 2
    elif trend == "MIXED+": score += 1
    elif trend == "BEAR":   score -= 2
    elif trend == "MIXED-": score -= 1

    # L1 contribution (±2)
    if l1 is not None:
        if   l1 >= 0.5:   score += 2
        elif l1 >= 0.15:  score += 1
        elif l1 <= -0.5:  score -= 2
        elif l1 <= -0.15: score -= 1

    return max(-4, min(4, score))

def signal_label(score):
    """Human-readable label for signal_score."""
    if   score >= 3:  return "Strong Bull"
    elif score >= 1:  return "Bull"
    elif score == 0:  return "Neutral"
    elif score >= -2: return "Bear"
    else:             return "Strong Bear"

# ── Snapshot ──────────────────────────────────────────────────────────────────

def fetch_snapshot():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        time.sleep(REQUEST_DELAY)
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        rows = r.json()
    except Exception as exc:
        log.error("Snapshot fetch failed: %s", exc)
        return None

    if isinstance(rows, dict) and rows.get("stat") == "No Data":
        log.info("Snapshot: No Data (holiday or off-hours)")
        return None

    snap = {}
    for row in rows:
        code   = row.get("Code", "").strip()
        if not code:
            continue
        close  = safe_float(row.get("ClosingPrice"))
        change = safe_float(row.get("Change"))
        chg_pct = None
        if close is not None and change is not None:
            base    = close - change
            chg_pct = round(change / base * 100, 2) if base else None
        snap[code] = {
            "close":   close,
            "chg":     change,
            "chg_pct": chg_pct,
            "volume":  safe_float(row.get("TradeVolume")),
            "name_zh": row.get("Name", "").strip(),
        }
    log.info("Snapshot: %d tickers loaded", len(snap))
    return snap

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== feeder start %s ===", now_iso())

    # 1. Snapshot (exit early if no market data)
    snapshot = fetch_snapshot()
    if snapshot is None:
        log.info("No market data today — exiting without overwriting data.json")
        sys.exit(0)

    # 2. TAIEX
    taiex, taiex_chg, taiex_chg_pct = fetch_taiex()

    # 3. Market-level institutional (today + prev)
    inst_today = fetch_institutional_today()
    inst_prev  = fetch_institutional_prev()

    market = {
        "taiex":              taiex,
        "taiex_chg":          taiex_chg,
        "taiex_chg_pct":      taiex_chg_pct,
        "foreign_net_m":      inst_today["foreign"],
        "dealer_net_m":       inst_today["dealer"],
        "trust_net_m":        inst_today["trust"],
        "three_inst_total_m": inst_today["total"],
        "pressure":           pressure_label(inst_today["foreign"]),
        "foreign_net_m_prev": inst_prev.get("foreign"),
        "dealer_net_m_prev":  inst_prev.get("dealer"),
        "trust_net_m_prev":   inst_prev.get("trust"),
    }

    # 4. T86 rolling (last 5 trading days) for all universe tickers
    twse_codes = {u[0] for u in UNIVERSE if u[0] not in TPEX_CODES}
    tpex_codes = {u[0] for u in UNIVERSE if u[0] in TPEX_CODES}

    log.info("Fetching T86 rolling %dd for %d TWSE tickers", T86_DAYS, len(twse_codes))
    t86_rolling = fetch_t86_rolling(twse_codes, days=T86_DAYS)
    t86_summary = derive_t86_fields(t86_rolling)

    # TPEx (stub — fields not yet verified live)
    if tpex_codes:
        log.info("Fetching TPEx T86 for %d OTC tickers (stub)", len(tpex_codes))
        # Will populate once field names confirmed from live response
        for code in tpex_codes:
            t86_summary[code] = {
                "foreign_net": None, "trust_net": None,
                "dealer_net":  None, "inst_net":  None,
                "foreign_3d":  None, "foreign_5d": None,
                "trust_3d":    None, "trust_5d":   None,
                "foreign_streak": None, "trust_streak": None,
            }

    # 5. Per-ticker rows
    portfolio_rows = []
    watchlist_rows = []

    for (code, name_en, name_zh, sector, bucket, float_m) in UNIVERSE:
        try:
            snap  = snapshot.get(code, {})
            close = snap.get("close")

            history = fetch_history(code, months=12)
            techs   = compute_technicals(history, close)

            t86f    = t86_summary.get(code, {})
            l1      = compute_l1_score(t86f, float_m)
            sig     = compute_signal_score(l1, techs.get("trend"))

            row = {
                "code":     code,
                "ticker":   code,          # alias — front-end uses both
                "name_en":  name_en,
                "name_zh":  name_zh,
                "sector":   sector,
                "bucket":   bucket,
                # price
                "close":    close,
                "chg":      snap.get("chg"),
                "chg_pct":  snap.get("chg_pct"),
                "volume":   snap.get("volume"),
                # technicals
                **techs,
                # T86 per-ticker
                "foreign_net":    t86f.get("foreign_net"),
                "trust_net":      t86f.get("trust_net"),
                "dealer_net":     t86f.get("dealer_net"),
                "inst_net":       t86f.get("inst_net"),
                "foreign_3d":     t86f.get("foreign_3d"),
                "foreign_5d":     t86f.get("foreign_5d"),
                "trust_3d":       t86f.get("trust_3d"),
                "trust_5d":       t86f.get("trust_5d"),
                "foreign_streak": t86f.get("foreign_streak"),
                "trust_streak":   t86f.get("trust_streak"),
                # scoring
                "l1_score":       l1,
                "signal_score":   sig,
                "signal_label":   signal_label(sig),
            }

            if bucket == "portfolio":
                portfolio_rows.append(row)
            else:
                watchlist_rows.append(row)

            log.info(
                "OK %s %s close=%s trend=%s l1=%.2f sig=%+d foreign_streak=%s trust_streak=%s",
                code, name_en, close,
                techs.get("trend"), l1 or 0, sig,
                t86f.get("foreign_streak"), t86f.get("trust_streak"),
            )

        except Exception as exc:
            log.error("SKIP %s: %s", code, exc)

    # 6. Load existing analysis.json (written separately / manually)
    analysis = {}
    try:
        with open("docs/analysis.json", encoding="utf-8") as f:
            analysis = json.load(f)
    except FileNotFoundError:
        log.info("docs/analysis.json not found — analysis block will be empty")
    except Exception as exc:
        log.warning("analysis.json load error: %s", exc)

    # 7. Write data.json
    data_out = {
        "updated":   now_iso(),
        "market":    market,
        "portfolio": portfolio_rows,
        "watchlist": watchlist_rows,
        "analysis":  analysis,
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)
    log.info(
        "docs/data.json written — portfolio:%d watchlist:%d",
        len(portfolio_rows), len(watchlist_rows)
    )

    log.info("=== feeder done %s ===", now_iso())


if __name__ == "__main__":
    main()
