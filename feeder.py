#!/usr/bin/env python3
"""
feeder.py — TWSE daily data feeder for twse-dashboard
Runs via GitHub Actions at 16:30 TPE on weekdays.
Writes docs/data.json and docs/tickers.json.
"""

import json
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

# ── Config ────────────────────────────────────────────────────────────────────
TZ = ZoneInfo("Asia/Taipei")

SHEET_ID = "1GuyPvnLtvPY1o7peK4R0tgRAY6nZea20XHEE_-BH9ZY"
SHEET_T1 = "T1 Inventory"
SHEET_T2 = "T2 Watchlist Interest"

FALLBACK_TICKERS = [
    ("2330", "TSMC",             "台積電",     "SEMI"),
    ("2317", "Hon Hai",          "鴻海",       "ELEC"),
    ("2454", "MediaTek",         "聯發科",     "SEMI"),
    ("2382", "Quanta",           "廣達",       "ELEC"),
    ("2303", "UMC",              "聯電",       "SEMI"),
    ("6505", "Formosa Petro",    "台塑化",     "PETRO"),
    ("2002", "China Steel",      "中鋼",       "STEEL"),
    ("1301", "Formosa Plastics", "台塑",       "PETRO"),
    ("2881", "Fubon FHC",        "富邦金",     "FIN"),
    ("2882", "Cathay FHC",       "國泰金",     "FIN"),
    ("0050", "Taiwan 50 ETF",    "元大台灣50", "ETF"),
    ("0056", "Hi-Div ETF",       "元大高股息", "ETF"),
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "twse-dashboard-feeder/1.0 (github.com/freshshine1/twse-dashboard)"
})
REQUEST_DELAY = 1.0

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
    s = str(val).replace(",", "").strip().lstrip("+")  # TPEx prefixes gains with "+"
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
                return None
            return data
        except Exception as exc:
            log.warning("%s — attempt %d failed: %s", label or url, attempt, exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
    log.error("%s — all retries exhausted", label or url)
    return None

# ── Snapshot — TWSE + TPEx ────────────────────────────────────────────────────
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
            close  = safe_float(row.get("ClosingPrice"))
            change = safe_float(row.get("Change"))
            chg_pct = None
            if close is not None and change is not None:
                base = close - change
                chg_pct = round(change / base * 100, 2) if base else None
            snap[code] = {
                "close":    close,
                "chg":      change,
                "chg_pct":  chg_pct,
                "volume":   safe_float(row.get("TradeVolume")),
                "name_zh":  row.get("Name", "").strip(),
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
        log.warning("TPEx snapshot failed after retries — TPEx tickers will have no price/history")
    else:
        for row in tpex_rows:
            code = row.get("SecuritiesCompanyCode", "").strip()
            if not code or code in snap:
                continue
            close  = safe_float(row.get("Close"))
            change = safe_float(row.get("Change"))
            chg_pct = None
            if close is not None and change is not None:
                base = close - change
                chg_pct = round(change / base * 100, 2) if base else None
            snap[code] = {
                "close":    close,
                "chg":      change,
                "chg_pct":  chg_pct,
                "volume":   safe_float(row.get("TradingShares")),
                "name_zh":  row.get("CompanyName", "").strip(),
                "exchange": "TPEx",
            }
            tpex_codes.add(code)
            raw_rows.append({
                "Code": code,
                "Name": row.get("CompanyName", "").strip(),
            })
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

# ── History — exchange-aware ──────────────────────────────────────────────────
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
            log.debug("%s TWSE history %s fetch error: %s", ticker, date_str, exc)
            continue

        stat = data.get("stat", "OK") if isinstance(data, dict) else "OK"
        if stat not in ("OK", ""):
            log.debug("%s TWSE history %s — stat=%s, aborting", ticker, date_str, stat)
            break

        rows = data.get("data", [])
        for row in rows:
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
            log.debug("%s TPEx history %s fetch error: %s", ticker, date_str, exc)
            continue

        stat = data.get("stat", "ok") if isinstance(data, dict) else "ok"
        tables = data.get("tables", []) if isinstance(data, dict) else []
        rows = tables[0].get("data", []) if tables else []

        if stat.lower() != "ok" or not rows:
            log.debug("%s TPEx history %s — no data, aborting", ticker, date_str)
            break

        for row in rows:
            try:
                parts = row[0].strip().split("/")
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

# ── Technical indicators ──────────────────────────────────────────────────────
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

    vols = [r["volume"] for r in history if r["volume"] is not None]
    vol_today = vols[-1] if vols else None
    avg5v = sum(vols[-5:]) / 5 if len(vols) >= 5 else None
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

# ── Institutional flow ────────────────────────────────────────────────────────
def fetch_institutional_today():
    url = "https://www.twse.com.tw/fund/BFI82U?response=json&dayDate=&type=day"
    data = twse_get(url, "三大法人")
    result = {"foreign_net_m": 0.0, "dealer_net_m": 0.0, "trust_net_m": 0.0}
    if not data:
        return result
    for row in data.get("data", []):
        name = row[0].strip()
        net  = safe_float(row[3], 0.0) / 1_000_000
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
    elif foreign_net_m < -20000: return "Strong Sell"
    elif foreign_net_m <      0: return "Net Sell"
    else:                        return "Neutral"

# ── 5-day cumulative foreign ──────────────────────────────────────────────────
def fetch_foreign_5d_cumul():
    total = 0.0
    days_collected = 0
    candidate = datetime.now(TZ).date()
    attempts = 0

    while days_collected < 5 and attempts < 20:
        attempts += 1
        if candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
            continue

        date_str = candidate.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={date_str}&type=day"
        data = twse_get(url, f"三大法人 {date_str}", retries=2, backoff=3)
        candidate -= timedelta(days=1)

        if not data:
            continue

        for row in data.get("data", []):
            name = row[0].strip()
            if "外資及陸資" in name and "不含" not in name:
                net = safe_float(row[3], 0.0) / 1_000_000
                total += net
                days_collected += 1
                log.info("三大法人 %s foreign_net_m=%.1f (day %d/5)", date_str, net, days_collected)
                break

    if days_collected < 5:
        log.warning("三大法人 5d cumul: only collected %d days", days_collected)

    return round(total, 2)

# ── Google Sheets reader ──────────────────────────────────────────────────────
def get_gsheet_token():
    creds_raw = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_raw:
        log.warning("GOOGLE_CREDENTIALS env var not set — skipping Sheet read")
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
        import base64
        import time as _time
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        now = int(_time.time())
        header  = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss":   creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
            "aud":   "https://oauth2.googleapis.com/token",
            "iat":   now,
            "exp":   now + 3600,
        }

        def b64(data):
            return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

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
    token = get_gsheet_token()
    if not token:
        return None

    tickers = []
    seen = set()

    # T1 — DATE | TICKER | NAME_ZH | NAME_EN | QTY | AVG_COST
    for row in read_sheet_tab(token, SHEET_ID, SHEET_T1):
        if len(row) < 2:
            continue
        code = str(row[1]).strip().upper()
        if not code or code in seen:
            continue
        name_zh = row[2].strip() if len(row) > 2 else snapshot.get(code, {}).get("name_zh", "")
        name_en = row[3].strip() if len(row) > 3 else ""
        if not name_en:
            name_en = snapshot.get(code, {}).get("name_zh", code)
        qty      = safe_float(row[4]) if len(row) > 4 else None
        avg_cost = safe_float(row[5]) if len(row) > 5 else None
        tickers.append((code, name_en, name_zh, "T1", qty, avg_cost))
        seen.add(code)
    log.info("Sheet T1: %d tickers", len(tickers))

    # T2 — TICKER | NOTE
    t2_count = 0
    for row in read_sheet_tab(token, SHEET_ID, SHEET_T2):
        if len(row) < 1:
            continue
        code = str(row[0]).strip().upper()
        if not code or code in seen:
            continue
        name_zh = snapshot.get(code, {}).get("name_zh", "")
        tickers.append((code, name_zh or code, name_zh, "T2"))
        seen.add(code)
        t2_count += 1
    log.info("Sheet T2: %d tickers", t2_count)
    log.info("Total from Sheet: %d tickers", len(tickers))

    return tickers if tickers else None

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=== feeder start %s ===", now_iso())

    # 1. Snapshots (TWSE + TPEx) — builds exchange routing sets
    snapshot, raw_rows, twse_codes, tpex_codes = fetch_snapshot()
    if snapshot is None:
        log.info("No market data today — exiting without overwriting data.json")
        sys.exit(0)

    # 2. Write tickers.json
    tickers_list = build_tickers_json(raw_rows)
    with open("docs/tickers.json", "w", encoding="utf-8") as f:
        json.dump({"updated": now_iso(), "tickers": tickers_list}, f, ensure_ascii=False, indent=2)
    log.info("docs/tickers.json written (%d entries)", len(tickers_list))

    # 3. Load tickers from Google Sheet (fallback to hardcoded)
    tickers = load_tickers_from_sheet(snapshot)
    if tickers is None:
        log.warning("Sheet unavailable — using fallback TICKERS")
        tickers = FALLBACK_TICKERS

    # 4. Market data
    taiex, taiex_chg, taiex_chg_pct = fetch_taiex()
    inst = fetch_institutional_today()
    foreign_5d = fetch_foreign_5d_cumul()

    market = {
        "taiex":              taiex,
        "taiex_chg":          taiex_chg,
        "taiex_chg_pct":      taiex_chg_pct,
        "foreign_net_m":      inst["foreign_net_m"],
        "dealer_net_m":       inst["dealer_net_m"],
        "trust_net_m":        inst["trust_net_m"],
        "three_inst_total_m": inst["three_inst_total_m"],
        "foreign_5d_cumul_m": foreign_5d,
        "pressure":           pressure_label(inst["foreign_net_m"]),
    }

    # 5. Per-ticker — exchange-aware history routing
    watchlist = []
    portfolio = []

    for ticker_entry in tickers:
        code     = ticker_entry[0]
        name_en  = ticker_entry[1]
        name_zh  = ticker_entry[2]
        tier     = ticker_entry[3]
        qty      = ticker_entry[4] if len(ticker_entry) > 4 else None
        avg_cost = ticker_entry[5] if len(ticker_entry) > 5 else None

        try:
            snap    = snapshot.get(code, {})
            close   = snap.get("close")
            chg     = snap.get("chg")
            chg_pct = snap.get("chg_pct")
            volume  = snap.get("volume")
            if not name_zh:
                name_zh = snap.get("name_zh", "")

            # Determine exchange from snapshot sets
            if code in tpex_codes:
                exchange = "TPEx"
            elif code in twse_codes:
                exchange = "TWSE"
            else:
                exchange = snap.get("exchange", "TWSE")

            log.info("Fetching history %s [%s]", code, exchange)
            history = fetch_history(code, exchange, months=12)
            techs   = compute_technicals(history, close)

            entry = {
                "ticker":    code,
                "name":      name_en,
                "name_zh":   name_zh,
                "tier":      tier,
                "exchange":  exchange,
                "price":     close,
                "chg":       chg,
                "chg_pct":   chg_pct,
                "vol_today": volume,
                **techs,
                **{"qty": qty, "avg_cost": avg_cost} if tier == "T1" else {},
            }

            if tier == "T1":
                portfolio.append(entry)
            else:
                watchlist.append(entry)

            log.info("OK %s %s [%s/%s] price=%s trend=%s",
                     code, name_zh or name_en, tier, exchange, close, techs.get("trend"))
        except Exception as exc:
            log.error("SKIP %s: %s", code, exc)

    # 6. Analysis placeholder
    analysis = {
        "updated":  now_iso(),
        "summary":  "Feeder ran successfully. Claude summary will appear once API credits are added.",
        "callouts": [],
        "sources":  ["TWSE API", "TPEx API", "三大法人 BFI82U", "Google Sheets"],
    }

    # 7. Write data.json
    data_out = {
        "updated":   now_iso(),
        "market":    market,
        "watchlist": watchlist,
        "portfolio": portfolio,
        "analysis":  analysis,
    }
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)
    log.info("docs/data.json written (%d watchlist, %d portfolio)", len(watchlist), len(portfolio))

    log.info("=== feeder done %s ===", now_iso())

if __name__ == "__main__":
    main()
