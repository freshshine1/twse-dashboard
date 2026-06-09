"""
feeder_l3.py — L3 Fundamental Anchor (exclusion filter).

Per IMPLEMENTATION_GUIDE Chapter 3, L3 is an EXCLUSION FILTER, not a scorer.
A flag firing pulls L3 toward -0.6 (hard) or -0.3 (soft warning). No flags -> 0.

MVP covers:
  - attention list (注意股)      -> hard exclude, L3 = -0.6
  - disposition list (處置股)    -> hard exclude, L3 = -0.6
  - monthly revenue YoY < -10%   -> soft warning, L3 = -0.3

Run #3 proved bare requests calls get HTML error pages from openapi.twse.com.tw
despite HTTP 200, so r.json() died with "Expecting value". This version sends a
browser User-Agent, tries multiple endpoint variants, and logs the actual body
sample on parse failure so the next run is self-diagnosing.

Output: docs/raw/l3_fundamentals_latest.json (+ dated archive).
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

log = logging.getLogger("feeder_l3")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TPE = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

ENDPOINTS = {
    "attention": [
        "https://openapi.twse.com.tw/v1/announcement/notice",
        "https://www.twse.com.tw/rwd/zh/announcement/notice?response=json",
    ],
    "disposition": [
        "https://openapi.twse.com.tw/v1/announcement/punish",
        "https://www.twse.com.tw/rwd/zh/announcement/punish?response=json",
    ],
    "revenue_twse": [
        "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    ],
    "revenue_tpex": [
        "https://openapi.twse.com.tw/v1/opendata/t187ap05_O",
    ],
}

CODE_KEYS = ("Code", "公司代號", "證券代號", "stock_id")
YOY_KEYS  = ("營業收入-去年同月增減(%)", "營業收入_去年同月增減(%)",
             "營業收入_去年同月增減", "去年同月增減(%)", "去年同月比較增減(%)",
             "去年同期增減%", "去年同期(%)", "去年同月增減百分比")
REVENUE_DECLINE_THRESHOLD = -10.0


def _pick(row, keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "N/A"):
            return v
    return None


def fetch_json_robust(urls, label, retries=2, backoff=3):
    for url in urls:
        for attempt in range(retries):
            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
                ct = r.headers.get("Content-Type", "")
                body = r.text
                if r.status_code != 200:
                    log.warning("  %s %s -> HTTP %d (%s) body[:200]=%r",
                                label, url, r.status_code, ct, body[:200])
                    continue
                try:
                    data = json.loads(body)
                except json.JSONDecodeError as je:
                    log.warning("  %s %s -> HTTP 200 (%s) but body not JSON: %s | body[:200]=%r",
                                label, url, ct, je, body[:200])
                    continue
                if isinstance(data, list):
                    sample_keys = list(data[0].keys()) if data and isinstance(data[0], dict) else []
                    log.info("  %s OK from %s: %d rows; first-row keys: %s",
                             label, url, len(data), sample_keys)
                elif isinstance(data, dict):
                    log.info("  %s OK from %s: dict keys=%s",
                             label, url, list(data.keys())[:8])
                return data
            except Exception as e:
                log.warning("  %s %s attempt %d/%d failed: %s",
                            label, url, attempt + 1, retries, e)
                if attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
        log.warning("  %s gave up on %s; trying next candidate", label, url)
    log.error("  %s: ALL %d endpoint candidates failed", label, len(urls))
    return []


def normalize_rows(data):
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        rows = data.get("data") or data.get("rows") or []
        return [r for r in rows if isinstance(r, dict)]
    return []


def main():
    now = datetime.now(TPE)

    log.info("Fetching attention 注意股 ...")
    att_rows = normalize_rows(fetch_json_robust(ENDPOINTS["attention"], "attention"))
    att_codes = {str(_pick(r, CODE_KEYS)).strip() for r in att_rows if _pick(r, CODE_KEYS)}

    log.info("Fetching disposition 處置股 ...")
    disp_rows = normalize_rows(fetch_json_robust(ENDPOINTS["disposition"], "disposition"))
    disp_codes = {str(_pick(r, CODE_KEYS)).strip() for r in disp_rows if _pick(r, CODE_KEYS)}

    log.info("Fetching revenue TWSE ...")
    rev_twse_rows = normalize_rows(fetch_json_robust(ENDPOINTS["revenue_twse"], "rev_twse"))
    log.info("Fetching revenue TPEx ...")
    rev_tpex_rows = normalize_rows(fetch_json_robust(ENDPOINTS["revenue_tpex"], "rev_tpex"))

    revenue_decline = {}
    for row in (rev_twse_rows + rev_tpex_rows):
        code = _pick(row, CODE_KEYS)
        yoy  = _pick(row, YOY_KEYS)
        if code is None or yoy is None:
            continue
        try:
            yoy_f = float(str(yoy).replace(",", ""))
        except Exception:
            continue
        if yoy_f <= REVENUE_DECLINE_THRESHOLD:
            revenue_decline[str(code).strip()] = round(yoy_f, 2)

    all_codes = att_codes | disp_codes | set(revenue_decline.keys())
    by_ticker = {}
    for code in all_codes:
        flags = []
        if code in att_codes:
            flags.append({"type": "attention", "label": "注意股"})
        if code in disp_codes:
            flags.append({"type": "disposition", "label": "處置股"})
        if code in revenue_decline:
            flags.append({"type": "revenue_yoy",
                          "label": f"營收 YoY {revenue_decline[code]:+.1f}%",
                          "value": revenue_decline[code]})
        hard = any(f["type"] in ("attention", "disposition") for f in flags)
        soft = any(f["type"] == "revenue_yoy" for f in flags)
        l3 = -0.6 if hard else (-0.3 if soft else 0.0)
        by_ticker[code] = {"flags": flags, "l3_score": l3}

    payload = {
        "asof": now.isoformat(timespec="seconds"),
        "source": "TWSE OpenAPI + main-site fallbacks",
        "thresholds": {"revenue_yoy_pct": REVENUE_DECLINE_THRESHOLD},
        "counts": {
            "attention":       len(att_codes),
            "disposition":     len(disp_codes),
            "revenue_decline": len(revenue_decline),
            "flagged_total":   len(by_ticker),
        },
        "by_ticker": by_ticker,
    }

    out_dir = Path("docs/raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    (out_dir / f"l3_fundamentals_{now.strftime('%Y-%m-%d')}.json").write_text(body)
    (out_dir / "l3_fundamentals_latest.json").write_text(body)
    log.info("L3 wrote %d flagged tickers (attention=%d, disposition=%d, rev_decline=%d)",
             len(by_ticker), len(att_codes), len(disp_codes), len(revenue_decline))


if __name__ == "__main__":
    main()
