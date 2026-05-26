#!/usr/bin/env python3
"""
feeder.py — TWSE daily data feeder for twse-dashboard
Runs via GitHub Actions at 16:30 TPE on weekdays.
Writes docs/data.json and docs/analysis.json.
"""

import json
import logging
import logging.handlers
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

# ── Config ────────────────────────────────────────────────────────────────────
TZ = ZoneInfo("Asia/Taipei")

TICKERS = [
    ("2330", "TSMC",              "台積電",      "SEMI"),
    ("2317", "Hon Hai",           "鴻海",        "ELEC"),
    ("2454", "MediaTek",          "聯發科",      "SEMI"),
    ("2382", "Quanta",            "廣達",        "ELEC"),
    ("2303", "UMC",               "聯電",        "SEMI"),
    ("6505", "Formosa Petro",     "台塑化",      "PETRO"),
    ("2002", "China Steel",       "中鋼",        "STEEL"),
    ("1301", "Formosa Plastics",  "台塑",        "PETRO"),
    ("2881", "Fubon FHC",         "富邦金",      "FIN"),
    ("2882", "Cathay FHC",        "國泰金",      "FIN"),
    ("0050", "Taiwan 50 ETF",     "元大台灣50",  "ETF"),
    ("0056", "Hi-Div ETF",        "元大高股息",  "ETF"),
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "twse-dashboard-feeder/1.0 (github.com/freshshine1/twse-dashboard)"
})
REQUEST_DELAY = 1.0   # seconds between TWSE calls — be polite

# ── Logging ───────────────────────────────────────────────────────────────────
def setup_logging():
    logger = logging.getLogger("feeder")
    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.RotatingFileHandler(
        "feeder.log", maxBytes=100_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    # also echo to stdout so GitHub Actions log captures it
    stdout_h = logging.StreamHandler(sys.stdout)
    stdout_h.setLevel(logging.INFO)
    stdout_h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(stdout_h)
    return logger

log = setup_logging()

# ── Helpers ───────────────────────────────────────────────────────────────────
def safe_float(val, default=None):
    """Parse a string that may contain commas or dashes."""
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
    """GET with retry/backoff. Returns parsed JSON or None."""
    for attempt in range(1, retries + 1):
        try:
            time.sleep(REQUEST_DELAY)
            r = SESSION.get(url, timeout=20)
            r.raise_for_status()
            data = r.json()
            # TWSE uses {"stat": "No Data"} or {"stat": "OK"}
            stat = data.get("stat", "OK") if isinstance(data, dict) else "OK"
            if stat not in ("OK", ""):
                log.warning("%s — stat=%s (attempt %d)", label or url, stat, attempt)
                if attempt < retries:
                    time.sleep(backoff * attempt)
                    continue
                return None
            return data
        except Exception as exc:
            log.warning("%s — attempt %d failed: %s", label or url, attempt, exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
    log.error("%s — all retries exhausted", label or url)
    return None

# ── 1. TAIEX ─────────────────────────────────────────────────────────────────
def fetch_taiex():
    """Returns (taiex, taiex_chg, taiex_chg_pct) or (None,None,None)."""
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

# ── 3. Institutional flow ─────────────────────────────────────────────────────
def fetch_institutional_today():
    """Returns dict with foreign_net_m, dealer_net_m, trust_net_m, three_inst_total_m."""
    url = "https://www.twse.com.tw/fund/BFI82U?response=json&dayDate=&type=day"
    data = twse_get(url, "三大法人")
    result = {"foreign_net_m": 0.0, "dealer_net_m": 0.0, "trust_net_m": 0.0}
    if not data:
        return result
    rows = data.get("data", [])
    # columns: 單位名稱, 買進金額, 賣出金額, 買賣超金額
    for row in rows:
        name = row[0].strip()
        net  = safe_float(row[3], 0.0) / 1_000_000  # NT$ → millions
        if "外資及陸資" in name and "不含" not in name:
            result["foreign_net_m"] = round(net, 2)
        elif "自營商" in name and "避險" not in name and "自行" not in name:
            result["dealer_net_m"] = round(net, 2)
        elif "投信" in name:
            result["trust_net_m"] = round(net, 2)
    result["three_inst_total_m"] = round(
        result["foreign_net_m"] + result["dealer_net_m"] + result["trust_net_m"], 2
    )
    return result

def pressure_label(foreign_net_m):
    if   foreign_net_m >  20000: return "Strong Buy"
    elif foreign_net_m >   5000: return "Buy"
    elif foreign_net_m <    -20000: return "Strong Sell"
    elif foreign_net_m <      0: return "Net Sell"
    else:                         return "Neutral"

# ── 2. Historical OHLCV ───────────────────────────────────────────────────────
def fetch_history(ticker, months=3):
    """
    Fetch OHLCV for `months` months back.
    Returns list of dicts sorted oldest→newest:
      {date, open, high, low, close, volume}
    """
    now = datetime.now(TZ)
    all_rows = []
    for m in range(months - 1, -1, -1):
        target = (now.replace(day=1) - timedelta(days=1)) if m == 0 else now
        # walk back m months
        dt = now
        for _ in range(m):
            dt = (dt.replace(day=1) - timedelta(days=1)).replace(day=1)
        dt = dt.replace(day=1)

        date_str = dt.strftime("%Y%m01")
        url = (
            f"https://www.twse.com.tw/exchangeReport/STOCK_DAY"
            f"?response=json&date={date_str}&stockNo={ticker}"
        )
        data = twse_get(url, f"{ticker} history {date_str}")
        if not data:
            continue
        rows = data.get("data", [])
        for row in rows:
            # 日期: "113/04/01" → ROC year
            try:
                parts = row[0].split("/")
                western_year = int(parts[0]) + 1911
                date_obj = datetime(western_year, int(parts[1]), int(parts[2]))
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

    # deduplicate and sort
    seen = set()
    unique = []
    for r in sorted(all_rows, key=lambda x: x["date"]):
        if r["date"] not in seen:
            seen.add(r["date"])
            unique.append(r)
    return unique

def fetch_history_12m(ticker):
    return fetch_history(ticker, months=12)

# ── 5. Technical indicators ───────────────────────────────────────────────────
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

    # vol_ratio
    vols = [r["volume"] for r in history if r["volume"] is not None]
    vol_today = vols[-1] if vols else None
    avg5v = sum(vols[-5:]) / 5 if len(vols) >= 5 else None
    vol_ratio = round(vol_today / avg5v, 2) if (vol_today and avg5v) else None

    # 52-week hi/lo (12 months)
    all_highs = [r["high"] for r in history if r["high"] is not None]
    all_lows  = [r["low"]  for r in history if r["low"]  is not None]
    high_52w  = max(all_highs) if all_highs else None
    low_52w   = min(all_lows)  if all_lows  else None
    pct_from_52w_high = (
        round((price - high_52w) / high_52w * 100, 2)
        if (price and high_52w) else None
    )

    # trend
    trend = "MIXED-"
    if price and ma5 and ma20 and ma60:
        if price > ma5 > ma20 > ma60:
            trend = "BULL"
        elif price < ma5 < ma20 < ma60:
            trend = "BEAR"
        elif price > ma20:
            trend = "MIXED+"

    return {
        "ma5": ma5, "ma20": ma20, "ma60": ma60,
        "vol_ratio": vol_ratio,
        "high_52w": high_52w, "low_52w": low_52w,
        "pct_from_52w_high": pct_from_52w_high,
        "trend": trend,
    }

# ── 1b. Daily snapshot (all tickers) ─────────────────────────────────────────
def fetch_snapshot():
    """Returns dict keyed by stockNo → {close, chg, chg_pct, volume, ...}"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        time.sleep(REQUEST_DELAY)
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        rows = r.json()  # list of dicts
    except Exception as exc:
        log.error("Snapshot fetch failed: %s", exc)
        return None

    if isinstance(rows, dict) and rows.get("stat") == "No Data":
        log.info("Snapshot: No Data (holiday or off-hours)")
        return None

    snap = {}
    for row in rows:
        code = row.get("Code", "").strip()
        if not code:
            continue
        close   = safe_float(row.get("ClosingPrice"))
        prev    = safe_float(row.get("LastBestBidPrice"))  # fallback
        change  = safe_float(row.get("Change"))
        # chg_pct
        if close is not None and change is not None:
            base = close - change
            chg_pct = round(change / base * 100, 2) if base else None
        else:
            chg_pct = None
        snap[code] = {
            "close":   close,
            "chg":     change,
            "chg_pct": chg_pct,
            "volume":  safe_float(row.get("TradeVolume")),
            "name_zh": row.get("Name", "").strip(),
        }
    log.info("Snapshot: %d tickers loaded", len(snap))
    return snap

# ── 6. 5-day cumulative foreign ───────────────────────────────────────────────
def fetch_foreign_5d_cumul():
    """
    Fetch institutional flow for the last 5 trading days and sum foreign net.
    dayDate param must be western YYYYMMDD — TWSE converts internally.
    """
    total = 0.0
    days_collected = 0
    candidate = datetime.now(TZ).date()
    attempts = 0

    while days_collected < 5 and attempts < 20:
        attempts += 1

        # skip weekends
        if candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
            continue

        # western date string — TWSE BFI82U accepts YYYYMMDD in western year
        date_str = candidate.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={date_str}&type=day"
        data = twse_get(url, f"三大法人 {date_str}", retries=2, backoff=3)
        candidate -= timedelta(days=1)  # always step back regardless of result

        if not data:
            continue

        rows = data.get("data", [])
        matched = False
        for row in rows:
            name = row[0].strip()
            if "外資及陸資" in name and "不含" not in name:
                net = safe_float(row[3], 0.0) / 1_000_000
                total += net
                days_collected += 1
                matched = True
                log.info("三大法人 %s foreign_net_m=%.1f (day %d/5)", date_str, net, days_collected)
                break

        if not matched:
            log.debug("三大法人 %s — no foreign row found, skipping day", date_str)

    if days_collected < 5:
        log.warning("三大法人 5d cumul: only collected %d days", days_collected)

    return round(total, 2)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=== feeder start %s ===", now_iso())

    # 1. Daily snapshot
    snapshot = fetch_snapshot()
    if snapshot is None:
        log.info("No market data today — exiting without overwriting data.json")
        sys.exit(0)

    # 2. TAIEX
    taiex, taiex_chg, taiex_chg_pct = fetch_taiex()

    # 3. Institutional (today)
    inst = fetch_institutional_today()

    # 4. 5-day cumulative foreign
    foreign_5d = fetch_foreign_5d_cumul()

    market = {
        "taiex":            taiex,
        "taiex_chg":        taiex_chg,
        "taiex_chg_pct":    taiex_chg_pct,
        "foreign_net_m":    inst["foreign_net_m"],
        "dealer_net_m":     inst["dealer_net_m"],
        "trust_net_m":      inst["trust_net_m"],
        "three_inst_total_m": inst["three_inst_total_m"],
        "foreign_5d_cumul_m": foreign_5d,
        "pressure":         pressure_label(inst["foreign_net_m"]),
    }

    # 5. Per-ticker
    watchlist = []
    for code, name_en, name_zh, sector in TICKERS:
        try:
            snap = snapshot.get(code, {})
            close   = snap.get("close")
            chg     = snap.get("chg")
            chg_pct = snap.get("chg_pct")
            volume  = snap.get("volume")

            # 12-month history for 52w; 3-month inside compute_technicals uses last 60 rows
            history = fetch_history_12m(code)
            techs   = compute_technicals(history, close)

            watchlist.append({
                "code":      code,
                "name_en":   name_en,
                "name_zh":   name_zh,
                "sector":    sector,
                "close":     close,
                "chg":       chg,
                "chg_pct":   chg_pct,
                "volume":    volume,
                **techs,
            })
            log.info("OK %s %s close=%s trend=%s", code, name_en, close, techs.get("trend"))
        except Exception as exc:
            log.error("SKIP %s: %s", code, exc)

    # 6. Write data.json
    data_out = {
        "updated":   now_iso(),
        "market":    market,
        "watchlist": watchlist,
        "portfolio": [],
    }
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)
    log.info("docs/data.json written (%d tickers)", len(watchlist))

    # 7. Write analysis.json (Claude summary skipped — no credits yet)
    analysis_out = {
        "updated": now_iso(),
        "summary": "Feeder ran successfully. Claude summary will appear once API credits are added.",
        "callouts": [],
        "sources":  ["TWSE API", "三大法人 BFI82U"],
    }
    with open("docs/analysis.json", "w", encoding="utf-8") as f:
        json.dump(analysis_out, f, ensure_ascii=False, indent=2)
    log.info("docs/analysis.json written")

    log.info("=== feeder done %s ===", now_iso())

if __name__ == "__main__":
    main()
