#!/usr/bin/env python3
"""
feeder.py ÃÂ¢ÃÂÃÂ TWSE daily data feeder for twse-dashboard
Runs via GitHub Actions at 19:00 TPE on weekdays (after T86 publishes ~18:00).
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
from pathlib import Path

import requests

# Scoring layer (carved out 2026-06-09; see score.py). Leaf import, no cycle.
from score import (
    compute_margin_score,
    compute_l1_score,
    compute_signal_score,
    signal_label,
    load_weights_override,
    compute_l2_score,
    compute_composite,
    compute_action,
    build_action_strings,
    update_signal_log,
)

# L1 concentration sub-score (BSR), carved into its own module; reads docs/bsr/*.csv.
from feeder_concentration import compute_all as compute_concentration_all

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

# 4a: concentration sub-score (BSR via feeder_concentration). Fail-safe by design --
# compute_concentration_all() over an empty/missing docs/bsr returns {}, so every ticker
# scores None and L1 == T86-only (compute_l1_score rescales by filled sub-weight). OFF by
# default: flipping ENABLE_CONCENTRATION=1 folds concentration into L1 for any ticker with
# a BSR file -- a baseline-shifting change, so enable at an observe boundary, not mid-window.
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
class SnapshotFetchError(RuntimeError):
    """Raised when the TWSE snapshot endpoint fails on a TRADING DAY (503 /
    empty body / parse error) — as distinct from a genuine holiday. Lets
    main() exit RED so the failure alerts, instead of the old silent green
    sys.exit(0) that left a stale data.json looking fine."""


def fetch_snapshot():
    snap = {}
    raw_rows = []
    twse_codes = set()
    tpex_codes = set()

    # TWSE — retry the flaky OpenAPI snapshot, then SPLIT the outcome:
    #   * stat == "No Data"  -> genuine holiday / off-hours -> exit GREEN (return None sentinel)
    #   * 503 / empty body / parse error after retries on a trading day -> raise
    #     SnapshotFetchError -> main() exits RED so the failure ALERTS, instead of
    #     the old behaviour where any fetch error silently exited green and left
    #     a stale data.json in place (root cause of the 2026-06-11 stale dashboard).
    twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    rows = None
    last_exc = None
    for attempt in range(1, 4):
        try:
            time.sleep(REQUEST_DELAY)
            r = SESSION.get(twse_url, timeout=30)
            r.raise_for_status()
            parsed = r.json()
        except Exception as exc:
            last_exc = exc
            log.warning("TWSE snapshot attempt %d/3 failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)
            continue
        # Genuine holiday answer — do NOT retry, do NOT fail red.
        if isinstance(parsed, dict) and parsed.get("stat") == "No Data":
            log.info("TWSE Snapshot: No Data (genuine holiday / off-hours) — exiting green.")
            return None, [], set(), set()
        # Good payload.
        if isinstance(parsed, list) and parsed:
            rows = parsed
            break
        # 200 but empty list / unexpected shape -> endpoint not ready, retry.
        last_exc = ValueError("empty or unexpected payload (%s)" % type(parsed).__name__)
        log.warning("TWSE snapshot attempt %d/3: empty/unexpected payload, retrying", attempt)
        if attempt < 3:
            time.sleep(5 * attempt)

    if rows is None:
        # All attempts failed to yield usable data. UPSTREAM error, not a holiday.
        # Weekday -> fail RED (alert); weekend (manual dispatch / cron misfire) ->
        # treat as off-hours and exit green.
        if datetime.now(TZ).weekday() >= 5:
            log.warning("TWSE snapshot unavailable on a weekend — treating as off-hours (green).")
            return None, [], set(), set()
        raise SnapshotFetchError(
            "TWSE STOCK_DAY_ALL unusable after 3 attempts on a trading day "
            "(last error: %s)" % last_exc
        )

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
    dealer_sum = 0.0
    dealer_seen = False
    for row in rows:
        if not row or len(row) < 4:
            continue
        name = str(row[0]).strip()
        net = safe_float(row[3], 0.0) / 1_000_000
        # Match by Unicode codepoints (avoids mojibake literal mismatch with live API).
        if "合計" in name:
            continue
        # Dealer: BFI82U's day report splits the dealer into 自營商(自行買賣) +
        # 自營商(避險) — there is NO single combined 自營商 row, so SUM both. Guard
        # with "外資 not in name": the 外資自營商 row also contains the substring
        # 自營商 and would otherwise mis-bind dealer to a foreign line (= the +0M bug).
        if "自營商" in name and "外資" not in name:
            dealer_sum += net
            dealer_seen = True
        elif "外資" in name and "陸資" in name:
            r["foreign"] = round(net, 2)
        elif "投信" in name:
            r["trust"] = round(net, 2)
    if dealer_seen:
        r["dealer"] = round(dealer_sum, 2)
    return r
def fetch_institutional_today():
    url = "https://www.twse.com.tw/fund/BFI82U?response=json&dayDate=&type=day"
    data = twse_get(url, "BFI82U today")
    rows = data.get("data", []) if data else []
    r = _parse_bfi82u(rows)
    r["three_inst_total_m"] = round(r["foreign"] + r["dealer"] + r["trust"], 2)

    # PREV-DATE FIX: base 'prev' on the date TWSE actually returned in today's
    # response, not _date.today(). An empty dayDate makes TWSE serve the latest
    # available trading day, which can be EARLIER than today when our run lands
    # before publish or while the market is still open. Without this, prev fetches
    # the same date as today (visible in dashboard as prev == today). We also
    # verify the prev response's own date differs, in case TWSE serves the same
    # cached day on consecutive calls.
    today_str = (data or {}).get("date", "")
    try:
        prev_start = datetime.strptime(today_str, "%Y%m%d").date() - timedelta(days=1)
    except Exception:
        prev_start = _date.today() - timedelta(days=1)

    prev = prev_start
    for _ in range(7):
        if prev.weekday() < 5:
            prev_str = prev.strftime("%Y%m%d")
            prev_data = twse_get(
                f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={prev_str}&type=day",
                f"BFI82U prev {prev_str}", retries=2, backoff=3
            )
            if prev_data and prev_data.get("data"):
                returned = prev_data.get("date", "")
                if today_str and returned == today_str:
                    log.warning("BFI82U prev %s returned today's date %s — walking back", prev_str, returned)
                else:
                    pr = _parse_bfi82u(prev_data["data"])
                    r["foreign_net_m_prev"] = pr["foreign"]
                    r["dealer_net_m_prev"] = pr["dealer"]
                    r["trust_net_m_prev"] = pr["trust"]
                    break
        prev -= timedelta(days=1)

    r["data_date"] = today_str   # 12.3: real T86 session date (YYYYMMDD or "")
    return r

def pressure_label(v):
    if v is None: return "N/A"
    if v > 20000: return "Strong Buy"
    if v > 5000: return "Buy"
    if v < -20000: return "Strong Sell"
    if v < 0: return "Net Sell"
    return "Neutral"

def fetch_foreign_5d_cumul():
    """5-day cumulative foreign net buy/sell. Previously this function matched the
    Chinese row label with a mojibake'd string literal that the live TWSE response
    never matched, so the function silently returned 0.0 every run (visible in the
    dashboard as 5d:+0M). We now reuse _parse_bfi82u which matches by clean Unicode
    codepoints, so the 5d aggregate populates from the same parser as today's row."""
    total = 0.0
    days_collected = 0
    candidate = _date.today()
    attempts = 0
    seen_dates = set()
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
        if not data or not data.get("data"):
            continue
        # De-duplicate by TWSE's resolved date — an empty/pre-publish day causes TWSE
        # to silently serve the most recent past day, which would otherwise be counted
        # twice toward the 5-day sum.
        resolved = data.get("date", date_str)
        if resolved in seen_dates:
            continue
        seen_dates.add(resolved)
        pr = _parse_bfi82u(data["data"])
        net = pr.get("foreign", 0.0)
        if net == 0.0:
            continue
        total += net
        days_collected += 1
        log.info("BFI82U %s foreign=%.1fM (day %d/5)", resolved, net, days_collected)
    if days_collected < 5:
        log.warning("BFI82U 5d cumul: only %d days collected", days_collected)
    return round(total, 2)

# ---- T86 per-ticker institutional flow ----
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
    market_t86_today = {}   # P2: whole-market snapshot for Radar (most recent available)
    latest_dt = None         # first date that returns real T86 data (newest first = most recent)
    t86_by_date = {}
    for dt in fetch_dates:
        url = f"https://www.twse.com.tw/fund/T86?response=json&date={dt}&selectType=ALL"
        raw = twse_get(url, f"T86 {dt}", retries=2, backoff=3)
        if not raw or not raw.get("data"):
            continue
        if latest_dt is None:
            latest_dt = dt   # most-recent date with actual data (radar fallback)
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
            # P2: populate market_t86_today from the most-recent date with data
            # (latest_dt). Falls back to yesterday if today's T86 is still processing.
            if dt == latest_dt:
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

    # TPEx institutional -- POST to tpex.org.tw/www/zh-tw/insti/dailyTrade
    # Discovered 2026-06-08: the old openapi/v1/tpex_institutional_trading_daily
    # endpoint silently redirects to the TPEx homepage (HTML, not JSON).
    # Working endpoint: POST with ROC-calendar date + type=Daily.
    # Response: tables[0].data rows, 24 cols:
    #   [0]=code [4]=foreign_net [13]=trust_net [22]=dealer_net [23]=inst_net
    # Verified: 927 rows total, no pagination, column math checks out.
    tpex_by_date = {}
    for dt in fetch_dates:
        roc_year = int(dt[:4]) - 1911
        month    = int(dt[4:6])
        day      = int(dt[6:])
        roc_date = f"{roc_year}/{month}/{day}"
        try:
            time.sleep(REQUEST_DELAY)
            resp = SESSION.post(
                "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",
                data={"date": roc_date, "type": "Daily"},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log.debug("TPEx inst POST %s failed: %s", dt, exc)
            continue
        if payload.get("stat") != "ok":
            log.debug("TPEx inst %s stat=%s", dt, payload.get("stat"))
            continue
        tables = payload.get("tables", [])
        if not tables or not tables[0].get("data"):
            log.debug("TPEx inst %s: empty tables", dt)
            continue
        rows = tables[0]["data"]
        day_map = {}
        for row in rows:
            if len(row) < 24:
                continue
            code = str(row[0]).strip()
            if code not in tpex_codes:
                continue
            day_map[code] = {
                "foreign_net": _parse_int(row[4]),   # foreign net
                "trust_net":   _parse_int(row[13]),  # trust net
                "dealer_net":  _parse_int(row[22]),  # dealer total net
                "inst_net":    _parse_int(row[23]),  # three-inst total
            }
        tpex_by_date[dt] = day_map
        log.info("T86 TPEx %s: %d tickers (ROC %s)", dt, len(day_map), roc_date)

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

# ── Industry map (上市 TWSE numeric codes + 上櫃 TPEx names) ──────────────────────────
TWSE_INDUSTRY = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙",
    "10": "鋼鐵", "11": "橡膠", "12": "汽車", "14": "建材營造",
    "15": "航運", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨",
    "19": "綜合", "20": "其他", "21": "化學", "22": "生技醫療",
    "23": "油電燃氣", "24": "半導體", "25": "電腦及週邊", "26": "光電",
    "27": "通信網路", "28": "電子零組件", "29": "電子通路", "30": "資訊服務",
    "31": "其他電子", "32": "文化創意", "33": "農業科技", "34": "電子商務",
    "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
    "80": "管理股票",
}

def _norm_industry(raw):
    """TWSE gives a numeric 產業別 code; TPEx usually gives a name. Normalise to a name."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    code = s.zfill(2) if s.isdigit() else s
    return TWSE_INDUSTRY.get(code, s)   # numeric -> name; already-a-name passes through

def fetch_industry_map():
    """
    {ticker_code: industry_name} from TWSE 上市 + TPEx 上櫃 basic-info OpenAPI.
    Industry is static-ish; one cheap call each per run. Returns {} on total failure
    so the caller can apply a last-known-good guard (same pattern as L3).
    """
    out = {}
    try:                                  # TWSE 上市公司基本資料 (產業別 = numeric code)
        time.sleep(REQUEST_DELAY)
        r = SESSION.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", timeout=30)
        r.raise_for_status()
        for row in r.json():
            code = (row.get("公司代號") or "").strip()
            if code:
                out[code] = _norm_industry(row.get("產業別"))
        log.info("Industry map TWSE: %d codes", len(out))
    except Exception as exc:
        log.error("Industry map TWSE failed: %s", exc)
    _tpex_n = 0
    try:                                  # TPEx 上櫃股票基本資料 (產業別 usually a name)
        time.sleep(REQUEST_DELAY)
        r = SESSION.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", timeout=30)
        r.raise_for_status()
        for row in r.json():
            code = (row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
            if code and code not in out:
                out[code] = _norm_industry(row.get("產業別"))
                _tpex_n += 1
        log.info("Industry map TPEx: +%d codes", _tpex_n)
    except Exception as exc:
        log.warning("Industry map TPEx failed: %s", exc)
    return out

# ── Radar / discovery screen (P2) ──────────────────────────────────────────────────
def screen_radar_candidates(market_t86_today, universe_codes, snapshot, float_m_map, prev_trust_map=None, industry_map=None, top_n=40):
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

        # §8.3 fresh-streak gate: buying today but NOT yesterday = day 1 of a new streak.
        # prev_trust_map.get(code, 0) defaults to 0 (neutral) when no history
        # or on first run (no file) -> 0 <= 0 is True -> falls back to trust_net > 0 only.
        if trust_net <= 0:
            skipped_no_trust += 1
            continue
        prev_trust = (prev_trust_map or {}).get(code, 0)
        if prev_trust > 0:
            skipped_no_trust += 1   # long-running streak, not fresh
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
            "industry":    (industry_map or {}).get(code, ""),
            "l1_score":    round(trust_norm * 0.5, 3),  # trust-only, weight 0.5 of T86
            "radar_note":  f"投信首日淨買 {round(trust_net/1000):,} 張",
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
            # MI_MARGN returns Chinese field names (confirmed from swagger 2026-06-08)
            code = str(row.get("股票代號", "") or row.get("Code", "") or row.get("StockNo", "")).strip()
            if not code:
                continue
            today = pick(row, "融資今日餘額", "MarginPurchaseTodayBalance")
            prev  = pick(row, "融資前日餘額", "MarginPurchaseYesterdayBalance")
            if today is None or prev is None:
                continue
            out[code] = {"margin_today": today, "margin_prev": prev}
        log.info("MI_MARGN: %d tickers with margin balances", len(out))
    except Exception as exc:
        log.debug("margin fetch failed: %s", exc)
        return {}
    return out


def load_l4_regime():
    """Read the L4 file written by feeder_us.py (08:00 TPE). Market-wide, applied
    uniformly to every ticker. Fail-safe: returns all-None when the file is absent."""
    try:
        with open("docs/raw/us_overnight_latest.json", encoding="utf-8") as f:
            d = json.load(f)
        log.info("L4 loaded: tilt=%s veto=%s label=%s", d.get("tilt_raw"),
                 d.get("regime_veto"), d.get("label"))
        return {"l4": d.get("L4"), "veto": bool(d.get("regime_veto")),
                "asof": d.get("asof")}
    except Exception as exc:
        log.info("L4 file not available (%s) -> L4 unfilled", exc)
        return {"l4": None, "veto": False, "asof": None}


def load_l3_fundamentals():
    """Read the L3 file written by feeder_l3.py (08:30 TPE). Returns
    (by_ticker, available, asof). When available, an unflagged ticker scores
    L3 = 0 (neutral, filled); when the file is absent L3 stays None (unfilled).
    `asof` is the file's own timestamp (for the 12.3 data-health strip)."""
    try:
        with open("docs/raw/l3_fundamentals_latest.json", encoding="utf-8") as f:
            d = json.load(f)
        bt = d.get("by_ticker", {})
        log.info("L3 loaded: %d flagged tickers", len(bt))
        return bt, True, d.get("asof")
    except Exception as exc:
        log.info("L3 file not available (%s) -> L3 unfilled", exc)
        return {}, False, None

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
def _fetch_snapshot_or_exit():
    """Translate the holiday/fetch-error split into process exit codes:
    a SnapshotFetchError (trading-day upstream failure) exits RED (1) so the
    GitHub job fails and alerts; a holiday returns the None sentinel and main()
    exits GREEN (0) without overwriting data.json."""
    try:
        return fetch_snapshot()
    except SnapshotFetchError as exc:
        log.error("ABORT (red exit 1): %s. data.json left untouched; failing the "
                  "run so it alerts instead of going silently stale.", exc)
        sys.exit(1)


def main():
    log.info("=== feeder start %s ===", now_iso())

    # 1. Snapshots (TWSE + TPEx)
    snapshot, raw_rows, twse_codes, tpex_codes = _fetch_snapshot_or_exit()
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

    # P0: load previous-day whole-market trust snapshot for Radar fresh-streak gate (§8.3)
    _prev_trust_path = Path("docs/raw/t86_market_prev.json")
    prev_trust_map: dict = {}
    if _prev_trust_path.exists():
        try:
            prev_trust_map = json.loads(_prev_trust_path.read_text(encoding="utf-8"))
            log.info("P0: loaded prev_trust_map: %d tickers", len(prev_trust_map))
        except Exception as _pte:
            log.warning("P0: failed to load t86_market_prev.json: %s", _pte)

    # P2: industry map for the Radar 產業 column (TWSE codes + TPEx names).
    # Last-known-good guard: an empty fetch keeps the prior docs/industry.json (same
    # discipline as the L3 latest-file guard) so a bad endpoint day can't blank the column.
    industry_map = fetch_industry_map()
    _ind_path = Path("docs/industry.json")
    if industry_map:
        try:
            _ind_path.parent.mkdir(parents=True, exist_ok=True)
            _ind_path.write_text(json.dumps(industry_map, ensure_ascii=False), encoding="utf-8")
            log.info("Wrote docs/industry.json: %d codes", len(industry_map))
        except Exception as _iwe:
            log.warning("industry.json write failed: %s", _iwe)
    else:
        log.warning("Industry map empty — keeping prior docs/industry.json (last-known-good)")
        if _ind_path.exists():
            try:
                industry_map = json.loads(_ind_path.read_text(encoding="utf-8"))
            except Exception:
                industry_map = {}

    # P0/P2: Radar screen — discover under-radar mid-caps with FRESH trust accumulation
    # Fresh = trust_net > 0 today AND trust_net_prev <= 0 (day 1 of new streak, §8.3).
    # Falls back to trust_net > 0 on first run (no prev file yet).
    universe_codes = {t[0] for t in tickers}
    radar = screen_radar_candidates(
        market_t86_today, universe_codes, snapshot, FLOAT_M,
        prev_trust_map=prev_trust_map, industry_map=industry_map,
    )

    # 4a: pre-compute concentration once over the curated universe (one parse pass of
    # docs/bsr/*.csv, per agent_ops batch rule). Fail-safe: empty/missing dir -> {}.
    conc_all = {}
    if ENABLE_CONCENTRATION:
        conc_all = compute_concentration_all("docs/bsr", tickers=all_unique_codes)
        log.info("Concentration: scored %d/%d curated tickers from docs/bsr",
                 len(conc_all), len(all_unique_codes))

    # 6. Per-ticker loop
    # history_cache avoids re-fetching OHLCV for tickers that appear in both T1 and T2
    watchlist  = []
    portfolio  = []
    # radar was populated by screen_radar_candidates above — NOT reinitialised here
    history_cache = {}

    # Chapter 6 synthesis inputs — loaded once, applied per ticker below.
    load_weights_override()                    # may replace WEIGHTS in place
    l4_regime = load_l4_regime()               # market-wide L4 + veto flag
    l3_by_ticker, l3_available, l3_asof = load_l3_fundamentals()

    # P0 FIX (2026-06-10): apply the L3 EXCLUSION filter to radar discovery candidates.
    # Radar is assembled before L3 loads and never enters the main scoring loop, so
    # disposition / severe-decline names would otherwise leak into the discovery list.
    if l3_available:
        # Display change (2026-06-11, per Fisher): DO NOT drop disposition / severe names
        # from radar. Keep them in the top list so 處置股 stay visible with a red 處置 badge
        # (read-with-caution) instead of silently vanishing. Annotate l3_score + l3_flags so
        # the Radar tab can render the badge. This REVERSES the 2026-06-10 P0 hard-exclude,
        # by request. Display-only: scoring / action / confluence logic is untouched (the
        # deferred Ch.11 per-bucket disposition revision is still owed and not done here).
        _disp = 0
        for rc in radar:
            _l3row = l3_by_ticker.get(rc["ticker"], {})
            rc["l3_score"] = _l3row.get("l3_score", 0.0)
            rc["l3_flags"] = _l3row.get("flags", [])
            if any(f.get("type") == "disposition" for f in rc["l3_flags"]):
                _disp += 1
        log.info("Radar L3 annotate: %d candidates kept (%d flagged 處置, badged not dropped)",
                 len(radar), _disp)

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
            # 4a: concentration sub-score from the pre-computed BSR map (conc_all).
            # Absent file -> no entry -> score None -> compute_l1_score rescales L1.
            conc_entry = conc_all.get(code)
            conc_score = conc_entry.get("score") if conc_entry else None
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

            # Chapter 6 synthesis: L2 numeric, L3 from fundamentals file, L4 regime.
            l2 = compute_l2_score(techs)
            if l3_available:
                _l3row  = l3_by_ticker.get(code, {})
                l3      = _l3row.get("l3_score", 0.0)     # unflagged ticker = neutral 0
                l3flags = _l3row.get("flags", [])
            else:
                l3, l3flags = None, []                    # file missing -> unfilled
            l4   = l4_regime["l4"]
            veto = l4_regime["veto"]
            composite = compute_composite(l1, l2, l3, l4, None, tier)   # L5 not folded yet
            action, confluence = compute_action(composite, l1, l2, l3, tier, veto)

            # Chapter 12.2: why-line + distance-to-flip (display only; never feeds
            # the composite or the gate). Built from already-computed values.
            act_strings = build_action_strings(
                tier=tier, action=action, composite=composite,
                l1=l1, l2=l2, l3=l3,
                trust_5d=(t86_entry.get("trust_5d") if t86_entry else None),
                foreign_5d=(t86_entry.get("foreign_5d") if t86_entry else None),
                float_m=float_m,
                concentration_score=conc_score, margin_score=margin_score,
                techs=techs, l3_flags=(l3flags if l3_available else []),
                regime_veto=veto,
            )

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
                "concentration_score":  conc_score,
                "conc_window":    (conc_entry or {}).get("score_window"),
                "conc_present":   (conc_entry or {}).get("present", False),
                "conc_direction": (conc_entry or {}).get("direction", 0),
                "conc_asof":      (conc_entry or {}).get("asof"),
                "margin_score":   margin_score,
                "l2_score":       l2,
                "l3_score":       l3,
                "l3_flags":       l3flags,
                "l4_score":       l4,
                "composite":      composite,
                "action":         action,
                "confluence":     confluence,
                "regime_veto":    veto,
                "signal_score":   sig,
                "signal_label":   signal_label(sig),
                "driver":         act_strings["driver"],
                "confirm":        act_strings["confirm"],
                "risk":           act_strings["risk"],
                "flip":           act_strings["flip"],
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

    # 7b. L5 news (read-only from the News sheet on Account B; fail-safe).
    # Read via the SAME helpers used for T1/T2 (token + REST), then parse with the
    # dependency-free fetch_news module. Surfaced for display + per-ticker bias;
    # NOT folded into the composite score yet (that is the deliberate L5 step).
    news_recent, news_by_ticker, news_by_sector = [], {}, {}
    news_sheet_id = os.environ.get("NEWS_SHEET_ID")
    if news_sheet_id:
        try:
            import fetch_news as _news
            tok = get_gsheet_token()
            news_rows_raw = read_sheet_tab(tok, news_sheet_id, "News") if tok else []
            news_recent    = _news.parse_news_rows(news_rows_raw, days=5)
            news_by_ticker = _news.news_bias_by_ticker(news_recent)
            news_by_sector = _news.sector_rollup(news_recent)
        except Exception as exc:
            log.warning("news read/parse failed, continuing without L5 news: %s", exc)
    else:
        log.info("NEWS_SHEET_ID not set — L5 news skipped")

    for entry in watchlist + portfolio + radar:
        nb = news_by_ticker.get(entry.get("ticker"))
        if nb:
            entry["news"] = {
                "bull":   nb["bull"],
                "bear":   nb["bear"],
                "watch":  nb["watch"],
                "latest": nb["headlines"][0] if nb["headlines"] else None,
            }
    log.info("L5 news: %d recent rows, %d tickers with news", len(news_recent), len(news_by_ticker))

    # 8. Write data.json
    # Chapter 12.3 data-health strip source: one timestamp per input so the
    # human never needs the Actions tab to know which day they're looking at.
    _t86_dd = inst_market.get("data_date") or ""
    _t86_iso = (f"{_t86_dd[:4]}-{_t86_dd[4:6]}-{_t86_dd[6:8]}"
                if len(_t86_dd) == 8 else None)
    health = {
        "t86":      _t86_iso,                 # real T86 session date (BFI82U)
        "price":    now_iso(),                # snapshot/技術 computed this run
        "l3":       l3_asof,                  # L3 file's own asof
        "l4":       l4_regime.get("asof"),    # L4 file's own asof
        "analysis": analysis.get("updated"),  # 早報/SinoPac summary
        "data":     now_iso(),                # this data.json
    }
    data_out = {
        "updated":   now_iso(),
        "market":    market,
        "health":    health,
        "watchlist": watchlist,
        "portfolio": portfolio,
        "radar":     radar,      # P2: under-radar Radar tab
        "news":      {"recent": news_recent[:60], "by_ticker": news_by_ticker, "by_sector": news_by_sector},
        "analysis":  analysis,
    }
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)
    log.info(
        "docs/data.json written ÃÂ¢ÃÂÃÂ portfolio:%d watchlist:%d",
        len(portfolio), len(watchlist)
    )

    # Chapter 12.1: append today's fired actions + near-misses to the signal
    # attribution log and backfill forward returns. Display/bookkeeping only --
    # it never feeds a score or the confluence gate. Non-fatal on error.
    update_signal_log(
        portfolio + watchlist,
        history_cache,
        datetime.now(TZ).date().isoformat(),
    )

    # P0: persist today's market trust snapshot for next run's fresh-streak gate (§8.3)
    try:
        compact = {
            c: r["trust_net"] for c, r in market_t86_today.items()
            if r.get("trust_net") is not None
        }
        Path("docs/raw").mkdir(parents=True, exist_ok=True)
        Path("docs/raw/t86_market_prev.json").write_text(
            json.dumps(compact, ensure_ascii=False), encoding="utf-8"
        )
        log.info("P0: saved t86_market_prev.json: %d tickers", len(compact))
    except Exception as _mte:
        log.warning("P0: failed to save t86_market_prev.json (non-fatal): %s", _mte)

    # Daily snapshot archive - minimal per-ticker view of what the dashboard
    # recommended today, for back-testing the hit-rate review. Without these
    # archives, the observe-only validation clock has no data to grade against.
    # Path is dated; one snapshot per trading day (overwrite if same day re-runs).
    try:
        snap_fields = ("ticker", "name_zh", "tier", "exchange", "price",
                       "composite", "action", "confluence", "regime_veto",
                       "l1_score", "l2_score", "l3_score", "l4_score", "l3_flags",
                       "foreign_5d", "trust_5d", "foreign_streak", "trust_streak",
                       "signal_score", "signal_label")
        def _slim(e):
            return {k: e.get(k) for k in snap_fields}
        snap = {
            "updated":   now_iso(),
            "market":    data_out.get("market", {}),
            "entries":   [_slim(e) for e in (portfolio + watchlist)],
        }
        os.makedirs("docs/raw", exist_ok=True)
        snap_path = f"docs/raw/snapshot_{_date.today().isoformat()}.json"
        with open(snap_path, "w", encoding="utf-8") as fp:
            json.dump(snap, fp, ensure_ascii=False, indent=2)
        log.info("snapshot written %s (%d entries)", snap_path, len(snap["entries"]))
    except Exception as exc:
        log.warning("snapshot write failed (non-fatal): %s", exc)

    log.info("=== feeder done %s ===", now_iso())

if __name__ == "__main__":
    main()
