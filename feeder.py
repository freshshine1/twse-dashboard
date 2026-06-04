#!/usr/bin/env python3
"""
feeder.py ÃÂ¢ÃÂÃÂ TWSE daily data feeder for twse-dashboard
Runs via GitHub Actions at 16:30 TPE on weekdays.
Writes docs/data.json and docs/tickers.json.

Fixes vs previous version (ea1b636 ÃÂ¢ÃÂÃÂ this):
BUG1 FIXED: t86 was assigned AFTER the per-ticker loop that referenced it
            ÃÂ¢ÃÂÃÂ NameError crash ÃÂ¢ÃÂÃÂ empty watchlist/portfolio every run.
            Fix: fetch T86 BEFORE the per-ticker loop.
BUG2 FIXED: T86 row indices wrong ÃÂ¢ÃÂÃÂ row[10]/[11] used for trust/dealer.
            Correct layout: trust=[7], dealer_total=[16], inst_total=[17].
BUG3 FIXED: `inst` variable shadowed BFI82U dict in per-ticker loop.
            Renamed T86 lookup var to `t86_entry`.
BUG4 FIXED: Prev-day BFI82U only walked back 1 day, fails on Mondays.
            Now walks back up to 7 calendar days.

Additions:
+ foreign_streak / trust_streak (consecutive buy/sell day count)
+ l1_score (L1 chip composite in [-1,+1], T86 component only for now)
+ signal_score (integer -4..+4 for badge / sort)
+ signal_label (human-readable)
+ trust_net_m_prev in market block

BUG5 FIXED: T1 tickers that are also in T2 now appear in BOTH portfolio AND
            watchlist. The `seen` set no longer blocks T2 from including T1
            tickers. Each tab (T1=portfolio, T2=watchlist) is independent.
BUG6 FIXED: Active ETFs with letter suffixes (e.g. 00981A) are handled as-is
            ÃÂ¢ÃÂÃÂ the code already strips/uppercases the code, matching TWSE
            snapshot keys exactly.

P1a FIXED (2026-06-01): L1 halving -- L1 was capped at +-0.5 because
            concentration/broker/margin sub-scores were hard-zeroed without
            rescaling. Fix: l1 = t86_score (rescaled by filled sub-weight
            fraction 0.50/0.50=1.0). When stubs land the formula becomes
            0.50*t86 + 0.20*conc + 0.20*broker + 0.10*margin.
P1a FIXED (2026-06-01): dealer_5d -- self-çå term used dealer_net*5 (today only).
            Now computes real 5-day dealer sum in fetch_t86_institutional and
            passes dealer_5d through to compute_l1_score and entry dict.
P2 ADDED  (2026-06-01): Radar v1 -- whole-market T86 captured each run.
            screen_radar_candidates() surfaces trust-accumulating mid-caps
            not in T1/T2 (volume 1k-10k Zhang, trust_net>0 today).
            data.json gains a "radar" key for the Radar tab.
"""

import json
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime, timedelta, date as _date
from zoneinfo import ZoneInfo

import requests

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Config ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
TZ = ZoneInfo("Asia/Taipei")

SHEET_ID = "1GuyPvnLtvPY1o7peK4R0tgRAY6nZea20XHEE_-BH9ZY"
SHEET_T1 = "T1 Inventory"
SHEET_T2 = "T2 Watchlist Interest"

FALLBACK_TICKERS = [
    ("2330", "TSMC", "ÃÂ¥ÃÂÃÂ°ÃÂ§ÃÂ©ÃÂÃÂ©ÃÂÃÂ»", "SEMI"),
    ("2317", "Hon Hai", "ÃÂ©ÃÂ´ÃÂ»ÃÂ¦ÃÂµÃÂ·", "ELEC"),
    ("2454", "MediaTek", "ÃÂ¨ÃÂÃÂ¯ÃÂ§ÃÂÃÂ¼ÃÂ§ÃÂ§ÃÂ", "SEMI"),
    ("2382", "Quanta", "ÃÂ¥ÃÂ»ÃÂ£ÃÂ©ÃÂÃÂ", "ELEC"),
    ("2303", "UMC", "ÃÂ¨ÃÂÃÂ¯ÃÂ©ÃÂÃÂ»", "SEMI"),
    ("6505", "Formosa Petro", "ÃÂ¥ÃÂÃÂ°ÃÂ¥ÃÂ¡ÃÂÃÂ¥ÃÂÃÂ", "PETRO"),
    ("2002", "China Steel", "ÃÂ¤ÃÂ¸ÃÂ­ÃÂ©ÃÂÃÂ¼", "STEEL"),
    ("1301", "Formosa Plastics", "ÃÂ¥ÃÂÃÂ°ÃÂ¥ÃÂ¡ÃÂ", "PETRO"),
    ("2881", "Fubon FHC", "ÃÂ¥ÃÂ¯ÃÂÃÂ©ÃÂÃÂ¦ÃÂ©ÃÂÃÂ", "FIN"),
    ("2882", "Cathay FHC", "ÃÂ¥ÃÂÃÂÃÂ¦ÃÂ³ÃÂ°ÃÂ©ÃÂÃÂ", "FIN"),
    ("0050", "Taiwan 50 ETF", "ÃÂ¥ÃÂÃÂÃÂ¥ÃÂ¤ÃÂ§ÃÂ¥ÃÂÃÂ°ÃÂ§ÃÂÃÂ£50", "ETF"),
    ("0056", "Hi-Div ETF", "ÃÂ¥ÃÂÃÂÃÂ¥ÃÂ¤ÃÂ§ÃÂ©ÃÂ«ÃÂÃÂ¨ÃÂÃÂ¡ÃÂ¦ÃÂÃÂ¯", "ETF"),
]

# Approximate free-float shares in millions ÃÂ¢ÃÂÃÂ for L1 normalisation.
# Missing entries use raw-clip fallback (ÃÂÃÂ±10,000 thousand shares).
FLOAT_M = {
    "2330": 25930, "2317": 138000, "2454": 15900, "2382": 13800,
    "2303": 47400, "6505": 25300, "2002": 97300, "1301": 63800,
    "2881": 72600, "2882": 116200, "0050": 6800, "0056": 23000,
    "3711": 79500, "7810": 580, "3017": 3100, "3653": 1400,
    "6669": 1730, "3363": 2100, "3037": 18600, "3533": 770,
    "2359": 2000, "2049": 7900, "2308": 25700, "3131": 850,
    "3324": 2500, "6223": 1100, "3163": 900, "5274": 560,
    "7769": 420, "00981A": 400,
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "twse-dashboard-feeder/1.0 (github.com/freshshine1/twse-dashboard)"
})
REQUEST_DELAY = 1.0

# 4a: concentration is wired but OFF by default until the BSR fetch is verified in CI.
# Flip to "1" in the workflow env only after fetch_concentration() is implemented/tested.
ENABLE_CONCENTRATION = os.getenv("ENABLE_CONCENTRATION") == "1"

# 4c: margin (MI_MARGN, whole-market one call/day, Tier-1, no captcha). Wired but OFF
# by default until the live field names are confirmed in CI. Then set ENABLE_MARGIN=1.
ENABLE_MARGIN = os.getenv("ENABLE_MARGIN") == "1"

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Logging ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
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

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Helpers ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def safe_float(val, default=None):
    if val is None:
        return default
    s = str(val).replace(",", "").strip().lstrip("+")
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
                log.warning("%s ÃÂ¢ÃÂÃÂ stat=%s (attempt %d)", label or url, stat, attempt)
                if attempt < retries:
                    time.sleep(backoff * attempt)
                continue
            return data
        except Exception as exc:
            log.warning("%s ÃÂ¢ÃÂÃÂ attempt %d failed: %s", label or url, attempt, exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
    log.error("%s ÃÂ¢ÃÂÃÂ all retries exhausted", label or url)
    return None

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Snapshot ÃÂ¢ÃÂÃÂ TWSE + TPEx ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def fetch_snapshot():
    snap = {}
    raw_rows = []
    twse_codes = set()
    tpex_codes = set()

    # TWSE
    twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        time.sleep(REQUEST_DELAY)
        r = SESSION.get(twse_url, timeout=30)
        r.raise_for_status()
        rows = r.json()
        if isinstance(rows, dict) and rows.get("stat") == "No Data":
            log.info("TWSE Snapshot: No Data (holiday or off-hours)")
            return None, [], set(), set()
        for row in rows:
            code = row.get("Code", "").strip()
            if not code:
                continue
            close = safe_float(row.get("ClosingPrice"))
            change = safe_float(row.get("Change"))
            chg_pct = None
            if close is not None and change is not None:
                base = close - change
                chg_pct = round(change / base * 100, 2) if base else None
            snap[code] = {
                "close": close,
                "chg": change,
                "chg_pct": chg_pct,
                "volume": safe_float(row.get("TradeVolume")),
                "name_zh": row.get("Name", "").strip(),
                "exchange": "TWSE",
            }
            twse_codes.add(code)
            raw_rows.append(row)
        log.info("TWSE snapshot: %d tickers", len(twse_codes))
    except Exception as exc:
        log.error("TWSE snapshot failed: %s", exc)
        return None, [], set(), set()

    # TPEx
    tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    tpex_rows = None
    for attempt in range(1, 4):
        try:
            time.sleep(REQUEST_DELAY)
            r = SESSION.get(tpex_url, timeout=60)
            r.raise_for_status()
            tpex_rows = r.json()
            log.info("TPEx snapshot fetched on attempt %d", attempt)
            break
        except Exception as exc:
            log.warning("TPEx snapshot attempt %d failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)

    if tpex_rows is None:
        log.warning("TPEx snapshot failed ÃÂ¢ÃÂÃÂ TPEx tickers will have no price/history")
    else:
        for row in tpex_rows:
            code = row.get("SecuritiesCompanyCode", "").strip()
            if not code or code in snap:
                continue
            close = safe_float(row.get("Close"))
            change = safe_float(row.get("Change"))
            chg_pct = None
            if close is not None and change is not None:
                base = close - change
                chg_pct = round(change / base * 100, 2) if base else None
            snap[code] = {
                "close": close,
                "chg": change,
                "chg_pct": chg_pct,
                "volume": safe_float(row.get("TradingShares")),
                "name_zh": row.get("CompanyName", "").strip(),
                "exchange": "TPEx",
            }
            tpex_codes.add(code)
            raw_rows.append({"Code": code, "Name": row.get("CompanyName", "").strip()})
        log.info("TPEx snapshot: %d tickers", len(tpex_codes))

    log.info("Combined snapshot: %d tickers total", len(snap))
    return snap, raw_rows, twse_codes, tpex_codes

def build_tickers_json(raw_rows):
    tickers = []
    seen = set()
    for row in raw_rows:
        code = row.get("Code", "").strip()
        name = row.get("Name", "").strip()
        if code and name and code not in seen:
            tickers.append({"ticker": code, "name_zh": name})
            seen.add(code)
    tickers.sort(key=lambda x: x["ticker"])
    return tickers

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ History ÃÂ¢ÃÂÃÂ exchange-aware ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def fetch_history_twse(ticker, months=12):
    now = datetime.now(TZ)
    all_rows = []
    for m in range(months - 1, -1, -1):
        dt = now
        for _ in range(m):
            dt = (dt.replace(day=1) - timedelta(days=1)).replace(day=1)
        dt = dt.replace(day=1)
        date_str = dt.strftime("%Y%m01")
        url = (
            f"https://www.twse.com.tw/exchangeReport/STOCK_DAY"
            f"?response=json&date={date_str}&stockNo={ticker}"
        )
        time.sleep(REQUEST_DELAY)
        try:
            r = SESSION.get(url, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.debug("%s TWSE history %s error: %s", ticker, date_str, exc)
            continue
        stat = data.get("stat", "OK") if isinstance(data, dict) else "OK"
        if stat not in ("OK", ""):
            log.debug("%s TWSE history %s stat=%s", ticker, date_str, stat)
            break
        for row in data.get("data", []):
            try:
                parts = row[0].split("/")
                western_year = int(parts[0]) + 1911
                date_obj = datetime(western_year, int(parts[1]), int(parts[2]))
                all_rows.append({
                    "date": date_obj,
                    "open": safe_float(row[3]),
                    "high": safe_float(row[4]),
                    "low": safe_float(row[5]),
                    "close": safe_float(row[6]),
                    "volume": safe_float(row[1]),
                })
            except Exception as exc:
                log.debug("%s row parse skip: %s | %s", ticker, exc, row)
    return _dedup_sort(all_rows)

def fetch_history_tpex(ticker, months=12):
    now = datetime.now(TZ)
    all_rows = []
    url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
    for m in range(months - 1, -1, -1):
        dt = now
        for _ in range(m):
            dt = (dt.replace(day=1) - timedelta(days=1)).replace(day=1)
        dt = dt.replace(day=1)
        date_str = f"{dt.year}/{dt.month:02d}/01"
        time.sleep(REQUEST_DELAY)
        try:
            r = SESSION.post(
                url,
                data={"code": ticker, "date": date_str, "response": "json"},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.debug("%s TPEx history %s error: %s", ticker, date_str, exc)
            continue
        stat = data.get("stat", "ok") if isinstance(data, dict) else "ok"
        tables = data.get("tables", []) if isinstance(data, dict) else []
        rows = tables[0].get("data", []) if tables else []
        if stat.lower() != "ok" or not rows:
            log.debug("%s TPEx history %s no data", ticker, date_str)
            break
        for row in rows:
            try:
                parts = row[0].strip().split("/")
                western_year = int(parts[0]) + 1911
                date_obj = datetime(western_year, int(parts[1]), int(parts[2]))
                all_rows.append({
                    "date": date_obj,
                    "open": safe_float(row[3]),
                    "high": safe_float(row[4]),
                    "low": safe_float(row[5]),
                    "close": safe_float(row[6]),
                    "volume": safe_float(row[1]),
                })
            except Exception as exc:
                log.debug("%s TPEx row parse skip: %s | %s", ticker, exc, row)
    return _dedup_sort(all_rows)

def _dedup_sort(rows):
    seen = set()
    unique = []
    for r in sorted(rows, key=lambda x: x["date"]):
        if r["date"] not in seen:
            seen.add(r["date"])
            unique.append(r)
    return unique

def fetch_history(ticker, exchange, months=12):
    if exchange == "TPEx":
        return fetch_history_tpex(ticker, months)
    return fetch_history_twse(ticker, months)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Technical indicators ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def sma(closes, n):
    if len(closes) < n:
        return None
    return round(sum(closes[-n:]) / n, 2)

def compute_technicals(history, snapshot_close):
    closes = [r["close"] for r in history if r["close"] is not None]
    if not closes:
        return {}
    ma5 = sma(closes, 5)
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    price = snapshot_close if snapshot_close is not None else (closes[-1] if closes else None)

    # L2 DATA-MISMATCH GUARD:
    # If today's snapshot close diverges from the most-recent history close by more
    # than 25%, the price and the OHLC history are on different scales/times (stale or
    # truncated history, or a bad snapshot). A daily limit move is <=10%, so >25% is
    # structurally impossible for fresh, same-scale data. In that case the MA / 52w /
    # trend metrics are untrustworthy, so we null them and flag `stale` rather than
    # emit a bogus BULL/BEAR signal (which previously produced e.g. +194% from 52w high).
    last_close = closes[-1] if closes else None
    stale = bool(
        price and last_close and last_close > 0
        and abs(price / last_close - 1.0) > 0.25
    )

    vols = [r["volume"] for r in history if r["volume"] is not None]
    vol_today = vols[-1] if vols else None
    avg5v = sum(vols[-5:]) / 5 if len(vols) >= 5 else None
    vol_ratio = round(vol_today / avg5v, 2) if (vol_today and avg5v) else None

    all_highs = [r["high"] for r in history if r["high"] is not None]
    all_lows = [r["low"] for r in history if r["low"] is not None]
    high_52w = max(all_highs) if all_highs else None
    low_52w = min(all_lows) if all_lows else None
    pct_from_52w_high = (
        round((price - high_52w) / high_52w * 100, 2)
        if (price and high_52w) else None
    )

    trend = "MIXED-"
    if price and ma5 and ma20 and ma60:
        if price > ma5 > ma20 > ma60: trend = "BULL"
        elif price < ma5 < ma20 < ma60: trend = "BEAR"
        elif price > ma20: trend = "MIXED+"

    # RSI-14 (Wilder seed over last 14 deltas)
    rsi14 = None
    if len(closes) >= 15:
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        seed = deltas[-14:]
        avg_gain = sum(max(d, 0) for d in seed) / 14
        avg_loss = sum(abs(min(d, 0)) for d in seed) / 14
        rsi14 = 100.0 if avg_loss == 0 else round(100 - (100 / (1 + avg_gain / avg_loss)), 1)

    if stale:
        # Suppress untrustworthy metrics; keep price + rsi out of the trend logic.
        return {
            "ma5": None, "ma20": None, "ma60": None,
            "vol_ratio": vol_ratio,
            "high_52w": None, "low_52w": None,
            "pct_from_52w_high": None,
            "trend": "STALE",
            "rsi14": None,
            "stale": True,
        }

    return {
        "ma5": ma5, "ma20": ma20, "ma60": ma60,
        "vol_ratio": vol_ratio,
        "high_52w": high_52w, "low_52w": low_52w,
        "pct_from_52w_high": pct_from_52w_high,
        "trend": trend,
        "rsi14": rsi14,
        "stale": False,
    }

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ TAIEX ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
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
        taiex = safe_float(last[4])
        taiex_chg = safe_float(last[5])
        taiex_chg_pct = (
            round(taiex_chg / (taiex - taiex_chg) * 100, 2)
            if taiex and taiex_chg else None
        )
        return taiex, taiex_chg, taiex_chg_pct
    except Exception as exc:
        log.warning("TAIEX parse error: %s", exc)
        return None, None, None

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ BFI82U ÃÂ¢ÃÂÃÂ market-level institutional flow ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def _parse_bfi82u(rows):
    r = {"foreign": 0.0, "dealer": 0.0, "trust": 0.0}
    for row in rows:
        name = row[0].strip()
        net = safe_float(row[3], 0.0) / 1_000_000
        if "ÃÂ¥ÃÂ¤ÃÂÃÂ¨ÃÂ³ÃÂÃÂ¥ÃÂÃÂÃÂ©ÃÂÃÂ¸ÃÂ¨ÃÂ³ÃÂ" in name and "ÃÂ¤ÃÂ¸ÃÂÃÂ¥ÃÂÃÂ«" not in name:
            r["foreign"] = round(net, 2)
        elif "ÃÂ¨ÃÂÃÂªÃÂ§ÃÂÃÂÃÂ¥ÃÂÃÂ" in name and "ÃÂ©ÃÂÃÂ¿ÃÂ©ÃÂÃÂª" not in name and "ÃÂ¨ÃÂÃÂªÃÂ¨ÃÂ¡ÃÂ" not in name:
            r["dealer"] = round(net, 2)
        elif "ÃÂ¦ÃÂÃÂÃÂ¤ÃÂ¿ÃÂ¡" in name:
            r["trust"] = round(net, 2)
    return r

def fetch_institutional_today():
    url = "https://www.twse.com.tw/fund/BFI82U?response=json&dayDate=&type=day"
    data = twse_get(url, "BFI82U today")
    rows = data.get("data", []) if data else []
    r = _parse_bfi82u(rows)
    r["three_inst_total_m"] = round(r["foreign"] + r["dealer"] + r["trust"], 2)

    # BUG4 FIX: walk back up to 7 calendar days for prev-day (handles Mondays)
    prev = _date.today() - timedelta(days=1)
    for _ in range(7):
        if prev.weekday() < 5:
            prev_str = prev.strftime("%Y%m%d")
            prev_data = twse_get(
                f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={prev_str}&type=day",
                f"BFI82U prev {prev_str}", retries=2, backoff=3
            )
            if prev_data and prev_data.get("data"):
                pr = _parse_bfi82u(prev_data["data"])
                r["foreign_net_m_prev"] = pr["foreign"]
                r["dealer_net_m_prev"] = pr["dealer"]
                r["trust_net_m_prev"] = pr["trust"]
                break
        prev -= timedelta(days=1)

    return r

def pressure_label(v):
    if v is None: return "N/A"
    if v > 20000: return "Strong Buy"
    if v > 5000: return "Buy"
    if v < -20000: return "Strong Sell"
    if v < 0: return "Net Sell"
    return "Neutral"

def fetch_foreign_5d_cumul():
    total = 0.0
    days_collected = 0
    candidate = _date.today()
    attempts = 0
    while days_collected < 5 and attempts < 20:
        attempts += 1
        if candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
            continue
        date_str = candidate.strftime("%Y%m%d")
        data = twse_get(
            f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={date_str}&type=day",
            f"BFI82U {date_str}", retries=2, backoff=3
        )
        candidate -= timedelta(days=1)
        if not data:
            continue
        for row in data.get("data", []):
            name = row[0].strip()
            if "ÃÂ¥ÃÂ¤ÃÂÃÂ¨ÃÂ³ÃÂÃÂ¥ÃÂÃÂÃÂ©ÃÂÃÂ¸ÃÂ¨ÃÂ³ÃÂ" in name and "ÃÂ¤ÃÂ¸ÃÂÃÂ¥ÃÂÃÂ«" not in name:
                net = safe_float(row[3], 0.0) / 1_000_000
                total += net
                days_collected += 1
                log.info("BFI82U %s foreign=%.1fM (day %d/5)", date_str, net, days_collected)
                break
    if days_collected < 5:
        log.warning("BFI82U 5d cumul: only %d days collected", days_collected)
    return round(total, 2)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ T86 per-ticker institutional flow ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def _parse_int(s):
    try:
        return int(str(s).replace(",", "").replace(" ", ""))
    except Exception:
        return 0

def _t86_idx(fields, needle, exclude=(), default=None):
    """Resolve a T86 column index by Chinese header-name substring.

    Robust to TWSE column reordering (the index-hardcoding that broke trust twice).
    Returns `default` (the documented positional index) if fields is missing or
    no header matches.
    """
    if fields:
        for i, name in enumerate(fields):
            nm = str(name)
            if needle in nm and not any(x in nm for x in exclude):
                return i
    return default

def _trading_dates_back(n):
    results = []
    d = _date.today()
    while len(results) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            results.append(d.strftime("%Y%m%d"))
    return results  # newest first

def _streak(daily_nets_oldest_first):
    if not daily_nets_oldest_first:
        return 0
    def sgn(x): return 1 if x > 0 else (-1 if x < 0 else 0)
    direction = sgn(daily_nets_oldest_first[-1])
    if direction == 0:
        return 0
    count = 0
    for v in reversed(daily_nets_oldest_first):
        if sgn(v) == direction:
            count += 1
        else:
            break
    return count * direction

def fetch_t86_institutional(twse_codes, tpex_codes):
    """
    Fetch per-stock ÃÂ¤ÃÂ¸ÃÂÃÂ¥ÃÂ¤ÃÂ§ÃÂ¦ÃÂ³ÃÂÃÂ¤ÃÂºÃÂº for today + 4 prior trading days.
    Returns dict: code -> {foreign_net, trust_net, dealer_net, inst_net,
                           foreign_3d, foreign_5d, trust_3d, trust_5d,
                           foreign_streak, trust_streak}

    BUG2 FIX ÃÂ¢ÃÂÃÂ correct T86 column indices:
      row[4]  ÃÂ¥ÃÂ¤ÃÂÃÂ¨ÃÂ³ÃÂÃÂ¦ÃÂ·ÃÂ¨ÃÂ¨ÃÂ²ÃÂ·ÃÂ¨ÃÂ³ÃÂ£ÃÂ¨ÃÂ¶ÃÂ
      row[7]  ÃÂ¦ÃÂÃÂÃÂ¤ÃÂ¿ÃÂ¡ÃÂ¦ÃÂ·ÃÂ¨ÃÂ¨ÃÂ²ÃÂ·ÃÂ¨ÃÂ³ÃÂ£ÃÂ¨ÃÂ¶ÃÂ (was row[10])
      row[16] ÃÂ¨ÃÂÃÂªÃÂ§ÃÂÃÂÃÂ¥ÃÂÃÂÃÂ¦ÃÂ·ÃÂ¨ÃÂ¥ÃÂÃÂÃÂ¨ÃÂ¨ÃÂ (was row[11])
      row[17] ÃÂ¤ÃÂ¸ÃÂÃÂ¥ÃÂ¤ÃÂ§ÃÂ¦ÃÂ³ÃÂÃÂ¤ÃÂºÃÂºÃÂ¥ÃÂÃÂÃÂ¨ÃÂ¨ÃÂ (was row[18])
    """
    today_str = _date.today().strftime("%Y%m%d")
    prior_dates = _trading_dates_back(4)
    fetch_dates = [today_str] + prior_dates  # newest first

    # TWSE T86
    market_t86_today = {}   # P2: whole-market today snapshot for Radar
    t86_by_date = {}
    for dt in fetch_dates:
        url = f"https://www.twse.com.tw/fund/T86?response=json&date={dt}&selectType=ALL"
        raw = twse_get(url, f"T86 {dt}", retries=2, backoff=3)
        if not raw or not raw.get("data"):
            continue
        # Resolve columns by header name (foreign=4 is confirmed-correct positionally;
        # trust/dealer/inst matched by name with documented-index fallback).
        fields = raw.get("fields")
        I_FOR = 4
        I_TRU = _t86_idx(fields, "投信買賣超", default=10)
        I_DEA = _t86_idx(fields, "自營商買賣超", exclude=("自行", "避險", "外資"), default=11)
        I_INS = _t86_idx(fields, "三大法人", default=18)
        need_len = max(I_FOR, I_TRU, I_DEA, I_INS) + 1
        day_map = {}
        for row in raw["data"]:
            if len(row) < need_len:
                continue
            code = row[0].strip()
            # P2: capture whole-market T86 snapshot for Radar (today's date only)
            if dt == fetch_dates[0]:
                market_t86_today[code] = {
                    "foreign_net": _parse_int(row[I_FOR]),
                    "trust_net":   _parse_int(row[I_TRU]),
                    "dealer_net":  _parse_int(row[I_DEA]),
                    "inst_net":    _parse_int(row[I_INS]),
                    "name_zh":     row[1].strip(),
                }
            if code not in twse_codes:
                continue
            day_map[code] = {
                "foreign_net": _parse_int(row[I_FOR]),
                "trust_net":   _parse_int(row[I_TRU]),
                "dealer_net":  _parse_int(row[I_DEA]),
                "inst_net":    _parse_int(row[I_INS]),
            }
        t86_by_date[dt] = day_map
        log.info("T86 TWSE %s: %d tickers", dt, len(day_map))

    # TPEx institutional
    tpex_by_date = {}
    for dt in fetch_dates:
        dt_fmt = f"{dt[:4]}/{dt[4:6]}/{dt[6:]}"
        url = (
            f"https://www.tpex.org.tw/openapi/v1/tpex_institutional_trading_daily"
            f"?date={dt_fmt}&lang=zh-tw"
        )
        raw = twse_get(url, f"TPEx inst {dt}", retries=2, backoff=3)
        if not raw or not isinstance(raw, list):
            continue
        day_map = {}
        for row in raw:
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            if code not in tpex_codes:
                continue
            day_map[code] = {
                "foreign_net": _parse_int(row.get("ForeignInvestorNetBuySell", 0)),
                "trust_net":   _parse_int(row.get("InvestmentTrustNetBuySell", 0)),
                "dealer_net":  _parse_int(row.get("DealerNetBuySell", 0)),
                "inst_net":    _parse_int(row.get("TotalNetBuySell", 0)),
            }
        tpex_by_date[dt] = day_map
        log.info("T86 TPEx %s: %d tickers", dt, len(day_map))

    # Combine into per-ticker summary
    all_codes = twse_codes | tpex_codes
    result = {}

    for code in all_codes:
        days = []
        for dt in fetch_dates:  # newest first
            src = t86_by_date if code in twse_codes else tpex_by_date
            entry = src.get(dt, {}).get(code)
            if entry:
                days.append(entry)

        if not days:
            continue

        today_d = days[0]
        # For streak we need oldestÃÂ¢ÃÂÃÂnewest, so reverse the newest-first list
        foreign_vals = list(reversed([d["foreign_net"] for d in days]))
        trust_vals   = list(reversed([d["trust_net"]   for d in days]))

        result[code] = {
            "foreign_net":    today_d["foreign_net"],
            "trust_net":      today_d["trust_net"],
            "dealer_net":     today_d["dealer_net"],
            "inst_net":       today_d["inst_net"],
            "foreign_3d":     sum(d["foreign_net"] for d in days[:3]) if len(days) >= 3 else None,
            "foreign_5d":     sum(d["foreign_net"] for d in days)     if len(days) >= 5 else None,
            "trust_3d":       sum(d["trust_net"]   for d in days[:3]) if len(days) >= 3 else None,
            "trust_5d":       sum(d["trust_net"]   for d in days)     if len(days) >= 5 else None,
            "dealer_5d":      sum(d["dealer_net"]  for d in days)     if len(days) >= 5 else None,
            "foreign_streak": _streak(foreign_vals),
            "trust_streak":   _streak(trust_vals),
        }

    log.info("T86 combined: %d tickers with data (market_today=%d)", len(result), len(market_t86_today))
    return result, market_t86_today  # P2: return full market snapshot for Radar

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ L1 chip score & signal score ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def _sgn(x):
    if not x: return 0
    return 1 if x > 0 else -1


# ── Radar / discovery screen (P2) ──────────────────────────────────────────────────
def screen_radar_candidates(market_t86_today, universe_codes, snapshot, float_m_map, top_n=40):
    """
    P2 Radar v1: surface under-radar mid-caps with newly-started trust accumulation.
    Coverage filter (all Tier-1 clean sources):
      - Not in T1/T2 universe (exclude already-tracked names)
      - Trust newly-started net-buy (trust_net > 0 = fresh accumulation today)
      - Volume band 1,000-10,000 Zhang (1,000,000-10,000,000 shares in K units: 1000-10000)
      - No 隔日沖 broker detection (deferred until broker_score lands; noted in log)
    Ranks by trust_net descending (strongest accumulation first).
    Returns list of dicts for data.json radar key.
    """
    if not market_t86_today:
        log.info("Radar: no market_t86_today data, skipping screen")
        return []

    candidates = []
    skipped_universe = 0
    skipped_volume = 0
    skipped_no_trust = 0

    for code, row in market_t86_today.items():
        # Exclude T1/T2 already-tracked universe
        if code in universe_codes:
            skipped_universe += 1
            continue

        trust_net = row.get("trust_net", 0) or 0

        # Trust must be net positive today (newly-started accumulation signal)
        if trust_net <= 0:
            skipped_no_trust += 1
            continue

        # Volume band: 1,000-10,000 張 (1 張 = 1,000 shares).
        # Real volume comes from the snapshot (TWSE TradeVolume, in shares);
        # T86 has no volume column, so the old T86-derived band never matched.
        snap = snapshot.get(code, {})
        vol_shares = snap.get("volume") or 0
        volume_zhang = vol_shares / 1000.0
        if not (1000 <= volume_zhang <= 10000):
            skipped_volume += 1
            continue

        close = snap.get("close")
        name_zh = row.get("name_zh") or snap.get("name_zh", code)
        float_m = float_m_map.get(code)

        # Compute a lightweight L1 using trust_net only (no 5d history for radar v1)
        # Normalize: trust_net / (float_m * 1000 * 0.02) capped at 1.0
        if float_m and float_m > 0:
            cap = float_m * 1000 * 0.02
            trust_norm = max(-1.0, min(1.0, trust_net / cap)) if cap else 0.0
        else:
            trust_norm = max(-1.0, min(1.0, trust_net / 10000))

        candidates.append({
            "ticker":      code,
            "name_zh":     name_zh,
            "tier":        "T3",
            "bucket":      "under_radar",
            "price":       close,
            "chg_pct":     snap.get("chg_pct"),
            "volume_k":    round(volume_zhang),
            "trust_net":   trust_net,
            "foreign_net": row.get("foreign_net", 0),
            "dealer_net":  row.get("dealer_net", 0),
            "inst_net":    row.get("inst_net", 0),
            "l1_score":    round(trust_norm * 0.5, 3),  # trust-only, weight 0.5 of T86
            "radar_note":  "投信 net-buy + vol 1k-10k Zhang",
        })

    # Rank by trust_net descending
    candidates.sort(key=lambda x: x["trust_net"], reverse=True)
    result = candidates[:top_n]

    log.info(
        "Radar screen: %d candidates (skipped: universe=%d vol=%d no_trust=%d) -> top %d",
        len(candidates), skipped_universe, skipped_volume, skipped_no_trust, len(result)
    )
    return result


def fetch_margin_all():
    """4c: whole-market margin balances from TWSE OpenAPI (one call/day, Tier-1, no captcha).

    Returns dict: code -> {"margin_today": int, "margin_prev": int} (融資餘額 today/prev).
    *** NEEDS CI VERIFICATION ***  confirm the exact field names against a live response
    and add the right ones to the candidate lists below. Fail-safe: ANY error or missing
    fields -> {} (or that row skipped), so margin stays unfilled and L1 is unchanged.
    """
    out = {}
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
        time.sleep(REQUEST_DELAY)
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            log.warning("MI_MARGN: unexpected payload shape; margin skipped")
            return {}

        def pick(row, *keys):
            for k in keys:
                if k in row and str(row[k]).strip() not in ("", "--"):
                    return _parse_int(row[k])
            return None

        for row in rows:
            code = str(row.get("Code", "") or row.get("StockNo", "")).strip()
            if not code:
                continue
            today = pick(row, "MarginPurchaseTodayBalance", "MarginPurchaseTodayBalanceShares")
            prev  = pick(row, "MarginPurchaseYesterdayBalance", "MarginPurchasePreviousDayBalance")
            if today is None or prev is None:
                continue
            out[code] = {"margin_today": today, "margin_prev": prev}
        log.info("MI_MARGN: %d tickers with margin balances", len(out))
    except Exception as exc:
        log.debug("margin fetch failed: %s", exc)
        return {}
    return out


def compute_margin_score(margin_today, margin_prev, price_chg_pct, inst_net):
    """4c: retail-sentiment read in [-1, +1] from 融資餘額 change vs price and 法人 flow.

    Report logic: 法人 buy + 融資 flat/down = silent (clean) accumulation [+];
    融資 up on an up-day while 法人 sell = retail chasing / distribution risk [-].
    Magnitudes/thresholds here are interpretation of the report's qualitative rules
    (tunable later via thresholds.json), not Tier-1-originated rules.
    """
    if margin_today is None or margin_prev is None or margin_prev <= 0:
        return None
    m_chg = (margin_today - margin_prev) / margin_prev
    inst = inst_net or 0
    pc = price_chg_pct or 0
    score = 0.0
    if inst > 0 and m_chg <= 0.0:
        score = 0.6      # institutions accumulating without retail chasing
    elif inst < 0 and pc > 0 and m_chg > 0.02:
        score = -0.8     # margin rising on up-day while institutions sell = distribution
    elif pc > 0 and m_chg > 0.05:
        score = -0.4     # retail chasing on margin
    elif inst > 0 and m_chg > 0:
        score = 0.2      # both rising = mild confirmation
    return round(max(-1.0, min(1.0, score)), 3)


def fetch_concentration(code, exchange):
    """4a: fetch broker-branch detail from TWSE BSR and return (c5, c60) concentration %.

    *** NEEDS CI VERIFICATION ***  bsr.twse.com.tw is a stateful two-step ASP.NET flow
    (GET bsMenu.aspx for the form/token -> POST stockNo -> GET the generated CSV at a
    tokenized URL). It cannot be exercised from the build sandbox. This is a fail-safe
    scaffold: ANY error returns (None, None), so concentration stays unfilled and L1 is
    unchanged. Implement/verify the scrape against the live endpoint and the Actions log,
    then flip ENABLE_CONCENTRATION. Spend this slow per-stock scrape ONLY on the curated
    universe + radar survivors (per agent_ops) -- never the whole market.
    """
    try:
        # TODO(4a): implement the two-step BSR scrape + per-branch buy/sell aggregation,
        # then call compute_concentration(...) per window. Until then, no-op.
        #   menu = SESSION.get("https://bsr.twse.com.tw/bshtm/bsMenu.aspx", ...)
        #   token = parse(menu)
        #   csv  = SESSION.post(".../bsMenu.aspx", data={... 'stockNo': code, token ...})
        #   buyers, sellers, vol_5d, vol_60d = aggregate(csv)
        #   c5  = compute_concentration(buyers_5d, sellers_5d, vol_5d)
        #   c60 = compute_concentration(buyers_60d, sellers_60d, vol_60d)
        #   return c5, c60
        return None, None
    except Exception as exc:
        log.debug("%s concentration fetch failed: %s", code, exc)
        return None, None


def compute_concentration(buyer_nets, seller_nets, total_volume):
    """4a: chip concentration % for one window.

    concentration = (sum(top-15 buyer nets) - sum(top-15 seller nets)) / total_volume * 100
    Signed: positive = net specific-party accumulation, negative = distribution.
    `buyer_nets` / `seller_nets` are per-branch net share counts (already split by side);
    `total_volume` is the window's total traded shares. Returns None if no volume.
    """
    if not total_volume or total_volume <= 0:
        return None
    top_buy = sum(sorted([n for n in buyer_nets if n > 0], reverse=True)[:15])
    top_sell = sum(sorted([abs(n) for n in seller_nets if n < 0], reverse=True)[:15])
    return round((top_buy - top_sell) / total_volume * 100.0, 3)


def compute_concentration_score(c5, c60):
    """Map signed 5-day and 60-day concentration % to an L1 sub-score in [-1, +1].

    Thresholds are DISPLAY references from the report (5d > 6%, 60d > 5%), used here
    only to normalise magnitude -- they are not standalone action rules (1-day chip
    alone had a documented sub-30% hit rate). Returns None if neither window has data.
    """
    parts = []
    if c5 is not None:
        parts.append(max(-1.0, min(1.0, c5 / 6.0)))
    if c60 is not None:
        parts.append(max(-1.0, min(1.0, c60 / 5.0)))
    if not parts:
        return None
    return round(sum(parts) / len(parts), 3)


def compute_l1_score(t86_entry, float_m, concentration=None, margin=None):
    if not t86_entry:
        return None
    def norm(net, cap_pct):
        if net is None: return 0.0
        if float_m and float_m > 0:
            cap = float_m * 1000 * cap_pct
            return max(-1.0, min(1.0, net / cap)) if cap else 0.0
        return max(-1.0, min(1.0, net / 10000))

    f5  = t86_entry.get("foreign_5d") or 0.0
    tr5 = t86_entry.get("trust_5d")  or 0.0
    d5  = t86_entry.get("dealer_5d")  or 0.0        # real 5d sum (P1a fix)

    t86_score = (
        0.50 * _sgn(tr5) * abs(norm(tr5, 0.02))
        + 0.30 * _sgn(f5) * abs(norm(f5, 0.005))
        + 0.20 * _sgn(d5) * abs(norm(d5, 0.01))
    )
    t86_score = max(-1.0, min(1.0, t86_score))

    # L1 sub-weights (target): T86 0.50, concentration 0.20, broker 0.20, margin 0.10.
    # Rescale by the FILLED sub-weight fraction so the score stays comparable while
    # the remaining sub-scores are stubs (same approach the P1a fix used). Any sub-score
    # that is None is simply not filled -> fail-safe: with all None, l1 == t86_score.
    num = 0.50 * t86_score
    den = 0.50
    if concentration is not None:
        num += 0.20 * max(-1.0, min(1.0, concentration))
        den += 0.20
    if margin is not None:
        num += 0.10 * max(-1.0, min(1.0, margin))
        den += 0.10
    l1 = num / den if den else 0.0
    return round(max(-1.0, min(1.0, l1)), 3)

def compute_signal_score(l1, trend):
    score = 0
    if trend == "BULL":   score += 2
    elif trend == "MIXED+": score += 1
    elif trend == "BEAR":   score -= 2
    elif trend == "MIXED-": score -= 1
    if l1 is not None:
        if l1 >= 0.5:    score += 2
        elif l1 >= 0.15: score += 1
        elif l1 <= -0.5:  score -= 2
        elif l1 <= -0.15: score -= 1
    return max(-4, min(4, score))

def signal_label(score):
    if score >= 3:   return "Strong Bull"
    elif score >= 1: return "Bull"
    elif score == 0: return "Neutral"
    elif score >= -2: return "Bear"
    else:            return "Strong Bear"

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Google Sheets reader ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def get_gsheet_token():
    creds_raw = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_raw:
        log.warning("GOOGLE_CREDENTIALS not set ÃÂ¢ÃÂÃÂ skipping Sheet read")
        return None
    try:
        creds = json.loads(creds_raw)
    except Exception as exc:
        log.error("Failed to parse GOOGLE_CREDENTIALS: %s", exc)
        return None
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests as ga_requests
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        credentials = service_account.Credentials.from_service_account_info(creds, scopes=scopes)
        credentials.refresh(ga_requests.Request())
        return credentials.token
    except ImportError:
        pass
    try:
        import base64, time as _t
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        now = int(_t.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now, "exp": now + 3600,
        }
        def b64(d): return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        signing_input = f"{b64(header)}.{b64(payload)}".encode()
        private_key = serialization.load_pem_private_key(creds["private_key"].encode(), password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        jwt_token = signing_input.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt_token},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as exc:
        log.error("JWT mint failed: %s", exc)
        return None

def read_sheet_tab(token, sheet_id, tab_name):
    import urllib.parse
    range_param = urllib.parse.quote(f"{tab_name}!A:Z")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_param}"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        r.raise_for_status()
        rows = r.json().get("values", [])
        return rows[1:] if len(rows) > 1 else []
    except Exception as exc:
        log.error("Sheet read failed (%s): %s", tab_name, exc)
        return []

def load_tickers_from_sheet(snapshot):
    """
    Load tickers from T1 Inventory and T2 Watchlist Interest.

    BUG5 FIX: A ticker in BOTH T1 and T2 (e.g. 3163 ÃÂ¦ÃÂ³ÃÂ¢ÃÂ¨ÃÂÃÂ¥ÃÂ¥ÃÂ¨ÃÂ) now appears in
    BOTH portfolio AND watchlist. Previously the `seen` set blocked T2 from
    including any T1 ticker. Now T1 and T2 are loaded independently with
    separate seen sets ÃÂ¢ÃÂÃÂ cross-listing is allowed and expected.

    Return value: list of tuples, may contain the same code twice with
    different tiers ("T1" and "T2").
    """
    token = get_gsheet_token()
    if not token:
        return None

    t1_entries = []
    t2_entries = []
    t1_seen = set()

    # T1 Inventory: DATE | TICKER | NAME_ZH | NAME_EN | QTY | AVG_COST
    for row in read_sheet_tab(token, SHEET_ID, SHEET_T1):
        if len(row) < 2:
            continue
        code = str(row[1]).strip().upper()
        if not code or code in t1_seen:
            continue
        name_zh = row[2].strip() if len(row) > 2 else snapshot.get(code, {}).get("name_zh", "")
        name_en = row[3].strip() if len(row) > 3 else ""
        if not name_en:
            name_en = name_zh or code
        qty      = safe_float(row[4]) if len(row) > 4 else None
        avg_cost = safe_float(row[5]) if len(row) > 5 else None
        t1_entries.append((code, name_en, name_zh, "T1", qty, avg_cost))
        t1_seen.add(code)
    log.info("Sheet T1: %d tickers", len(t1_entries))

    # T2 Watchlist Interest: TICKER | COMPANY_ZH | NOTE
    # No dedup against T1 ÃÂ¢ÃÂÃÂ cross-listing is intentional.
    t2_seen = set()
    for row in read_sheet_tab(token, SHEET_ID, SHEET_T2):
        if len(row) < 1:
            continue
        code = str(row[0]).strip().upper()
        if not code or code in t2_seen:
            continue
        name_zh = row[1].strip() if len(row) > 1 else snapshot.get(code, {}).get("name_zh", "")
        t2_entries.append((code, name_zh or code, name_zh, "T2"))
        t2_seen.add(code)
    log.info("Sheet T2: %d tickers", len(t2_entries))

    tickers = t1_entries + t2_entries
    log.info("Total ticker entries (T1+T2, cross-list allowed): %d", len(tickers))
    return tickers if tickers else None

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Main ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def main():
    log.info("=== feeder start %s ===", now_iso())

    # 1. Snapshots (TWSE + TPEx)
    snapshot, raw_rows, twse_codes, tpex_codes = fetch_snapshot()
    if snapshot is None:
        log.info("No market data today ÃÂ¢ÃÂÃÂ exiting without overwriting data.json")
        sys.exit(0)

    # 2. Write tickers.json
    tickers_list = build_tickers_json(raw_rows)
    os.makedirs("docs", exist_ok=True)
    with open("docs/tickers.json", "w", encoding="utf-8") as f:
        json.dump({"updated": now_iso(), "tickers": tickers_list}, f, ensure_ascii=False, indent=2)
    log.info("docs/tickers.json written (%d entries)", len(tickers_list))

    # 3. Load tickers from Google Sheet (fallback to hardcoded)
    tickers = load_tickers_from_sheet(snapshot)
    if tickers is None:
        log.warning("Sheet unavailable ÃÂ¢ÃÂÃÂ using FALLBACK_TICKERS")
        tickers = FALLBACK_TICKERS

    # 4. Market-level institutional data
    inst_market = fetch_institutional_today()
    foreign_5d  = fetch_foreign_5d_cumul()
    taiex, taiex_chg, taiex_chg_pct = fetch_taiex()

    market = {
        "taiex":              taiex,
        "taiex_chg":          taiex_chg,
        "taiex_chg_pct":      taiex_chg_pct,
        "foreign_net_m":      inst_market["foreign"],
        "dealer_net_m":       inst_market["dealer"],
        "trust_net_m":        inst_market["trust"],
        "three_inst_total_m": inst_market["three_inst_total_m"],
        "foreign_5d_cumul_m": foreign_5d,
        "pressure":           pressure_label(inst_market["foreign"]),
        "foreign_net_m_prev": inst_market.get("foreign_net_m_prev"),
        "dealer_net_m_prev":  inst_market.get("dealer_net_m_prev"),
        "trust_net_m_prev":   inst_market.get("trust_net_m_prev"),
    }

    # 5. Per-ticker T86 ÃÂ¢ÃÂÃÂ BEFORE the per-ticker loop (BUG1 FIX)
    # Collect unique codes across T1+T2 for T86 fetch
    all_unique_codes = {t[0] for t in tickers}
    t86_twse = all_unique_codes & twse_codes
    t86_tpex = all_unique_codes & tpex_codes
    log.info("Fetching T86: %d TWSE + %d TPEx tickers", len(t86_twse), len(t86_tpex))
    t86, market_t86_today = fetch_t86_institutional(t86_twse, t86_tpex)  # P2: unpack radar snapshot

    # 4c: whole-market margin balances (one call/day, gated + fail-safe; {} when off/failed)
    margin_map = fetch_margin_all() if ENABLE_MARGIN else {}

    # P2: Radar screen — discover under-radar names with fresh trust accumulation
    universe_codes = {t[0] for t in tickers}
    radar = screen_radar_candidates(market_t86_today, universe_codes, snapshot, FLOAT_M)

    # 6. Per-ticker loop
    # history_cache avoids re-fetching OHLCV for tickers that appear in both T1 and T2
    watchlist  = []
    portfolio  = []
    radar      = []   # P2: populated by screen_radar_candidates before loop
    history_cache = {}

    for ticker_entry in tickers:
        code     = ticker_entry[0]
        name_en  = ticker_entry[1]
        name_zh  = ticker_entry[2]
        tier     = ticker_entry[3]
        qty      = ticker_entry[4] if len(ticker_entry) > 4 else None
        avg_cost = ticker_entry[5] if len(ticker_entry) > 5 else None

        try:
            snap   = snapshot.get(code, {})
            close  = snap.get("close")
            if not name_zh:
                name_zh = snap.get("name_zh", "")

            exchange = (
                "TPEx" if code in tpex_codes
                else ("TWSE" if code in twse_codes else snap.get("exchange", "TWSE"))
            )

            # Use cached history to avoid double-fetching cross-listed tickers
            if code not in history_cache:
                log.info("Fetching history %s [%s]", code, exchange)
                history_cache[code] = fetch_history(code, exchange, months=12)
            history = history_cache[code]
            techs   = compute_technicals(history, close)

            # BUG3 FIX: renamed to t86_entry (no longer shadows inst_market)
            t86_entry = t86.get(code)
            float_m   = FLOAT_M.get(code)
            # 4a: concentration sub-score (gated; no-op + fail-safe until BSR verified).
            conc_score = None
            if ENABLE_CONCENTRATION:
                c5, c60 = fetch_concentration(code, exchange)
                conc_score = compute_concentration_score(c5, c60)
            # 4c: margin sub-score (gated; no-op + fail-safe until MI_MARGN fields verified).
            margin_score = None
            if ENABLE_MARGIN:
                mrow = margin_map.get(code)
                if mrow:
                    inst_net = t86_entry.get("inst_net") if t86_entry else None
                    margin_score = compute_margin_score(
                        mrow["margin_today"], mrow["margin_prev"], snap.get("chg_pct"), inst_net
                    )
            l1  = compute_l1_score(t86_entry, float_m, concentration=conc_score, margin=margin_score)
            sig = compute_signal_score(l1, techs.get("trend"))

            entry = {
                "ticker":    code,
                "name":      name_en,
                "name_zh":   name_zh,
                "tier":      tier,
                "exchange":  exchange,
                "price":     close,
                "chg":       snap.get("chg"),
                "chg_pct":   snap.get("chg_pct"),
                "vol_today": snap.get("volume"),
                **techs,
                "foreign_net":    t86_entry["foreign_net"]         if t86_entry else None,
                "trust_net":      t86_entry["trust_net"]           if t86_entry else None,
                "dealer_net":     t86_entry["dealer_net"]          if t86_entry else None,
                "inst_net":       t86_entry["inst_net"]            if t86_entry else None,
                "foreign_3d":     t86_entry["foreign_3d"]          if t86_entry else None,
                "foreign_5d":     t86_entry["foreign_5d"]          if t86_entry else None,
                "trust_3d":       t86_entry.get("trust_3d")        if t86_entry else None,
                "trust_5d":       t86_entry.get("trust_5d")        if t86_entry else None,
                "dealer_5d":      t86_entry.get("dealer_5d")       if t86_entry else None,
                "foreign_streak": t86_entry.get("foreign_streak")  if t86_entry else None,
                "trust_streak":   t86_entry.get("trust_streak")    if t86_entry else None,
                "l1_score":       l1,
                "signal_score":   sig,
                "signal_label":   signal_label(sig),
            }

            if tier == "T1":
                entry["qty"]      = qty
                entry["avg_cost"] = avg_cost
                portfolio.append(entry)
            else:
                watchlist.append(entry)

            log.info(
                "OK %s %s [%s/%s] price=%s trend=%s l1=%s sig=%+d f_streak=%s",
                code, name_zh or name_en, tier, exchange, close,
                techs.get("trend"), l1, sig or 0,
                t86_entry.get("foreign_streak") if t86_entry else None,
            )
        except Exception as exc:
            log.error("SKIP %s: %s", code, exc)

    # 7. Load analysis.json if present
    analysis = {
        "updated":  now_iso(),
        "summary":  "Feeder ran successfully. Claude summary pending API credits.",
        "callouts": [],
        "sources":  ["TWSE API", "TPEx API", "ÃÂ¤ÃÂ¸ÃÂÃÂ¥ÃÂ¤ÃÂ§ÃÂ¦ÃÂ³ÃÂÃÂ¤ÃÂºÃÂ² BFI82U", "Google Sheets"],
    }
    try:
        with open("docs/analysis.json", "r", encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict) and stored.get("summary"):
            analysis = stored
            log.info("analysis.json loaded (%s)", stored.get("updated", "?"))
    except FileNotFoundError:
        log.info("analysis.json not found ÃÂ¢ÃÂÃÂ using placeholder")
    except Exception as exc:
        log.warning("analysis.json read error: %s", exc)

    # 8. Write data.json
    data_out = {
        "updated":   now_iso(),
        "market":    market,
        "watchlist": watchlist,
        "portfolio": portfolio,
        "radar":     radar,      # P2: under-radar Radar tab
        "analysis":  analysis,
    }
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)
    log.info(
        "docs/data.json written ÃÂ¢ÃÂÃÂ portfolio:%d watchlist:%d",
        len(portfolio), len(watchlist)
    )
    log.info("=== feeder done %s ===", now_iso())

if __name__ == "__main__":
    main()
