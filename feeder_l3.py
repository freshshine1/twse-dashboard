"""
feeder_l3.py — L3 Fundamental Anchor (exclusion filter).

Per IMPLEMENTATION_GUIDE Chapter 3, L3 is an EXCLUSION FILTER, not a scorer.
A flag firing pulls L3 toward −0.6 (hard) or −0.3 (soft warning). No flags → 0.

MVP (this version) covers:
  - 注意股   (TWSE attention list)              — hard exclude, L3 = −0.6
  - 處置股   (TWSE disposition list)            — hard exclude, L3 = −0.6
  - 月營收年增率 < −10% (current month, YoY)    — soft warning, L3 = −0.3

DEFERRED (future expansion of this same file):
  - EPS negative latest quarter (t05st10_ifrs)
  - 負債比 > 70%, 設質比 > 30%
  - Monthly revenue 2+ consecutive months < −10% (needs historical state)

Sources: TWSE OpenAPI — https://openapi.twse.com.tw/v1/ — public, no auth, JSON.

Schedule: runs daily at 08:30 TPE (Mon–Fri); attention/disposition lists move
frequently. Monthly revenue updates once a month around the 10th, so most days
the only changes here are the attention/disposition lists.

Output (always overwritten, plus a dated archive):
  docs/raw/l3_fundamentals_latest.json
  docs/raw/l3_fundamentals_YYYY-MM-DD.json

The dashboard reads l3_fundamentals_latest.json directly from the frontend
(parallel to L4) and renders per-card flag chips.
"""
import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

log = logging.getLogger("feeder_l3")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TPE  = timezone(timedelta(hours=8))
BASE = "https://openapi.twse.com.tw/v1"

ENDPOINTS = {
    "attention":    f"{BASE}/announcement/notice",     # 注意股
    "disposition":  f"{BASE}/announcement/punish",     # 處置股
    "revenue_twse": f"{BASE}/opendata/t187ap05_L",     # 上市每月營收
    "revenue_tpex": f"{BASE}/opendata/t187ap05_O",     # 上櫃每月營收
}

# Field-name variants seen in TWSE/TPEx OpenAPI: codes can be "Code"/"公司代號";
# YoY column can vary by year. We accept any of these via `_pick`.
CODE_KEYS    = ("Code", "公司代號", "證券代號")
YOY_KEYS     = ("去年同月增減(%)", "去年同月比較增減(%)", "去年同期增減%", "去年同期(%)")
REVENUE_DECLINE_THRESHOLD = -10.0     # YoY% ≤ this triggers the soft warning


def _pick(row, keys):
    """Return the first non-empty value among `keys` from `row`, or None."""
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "N/A"):
            return v
    return None


def fetch_json(url, label, retries=3, backoff=4):
    """GET JSON with retries. Returns [] on persistent failure (caller can
    proceed with a partial L3 — better to ship 2 flags than zero)."""
    for i in range(retries):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("fetch %s attempt %d/%d failed: %s", label, i + 1, retries, e)
            if i < retries - 1:
                time.sleep(backoff * (i + 1))
    return []


def main():
    now = datetime.now(TPE)

    log.info("Fetching 注意股 (attention) …")
    att = fetch_json(ENDPOINTS["attention"], "attention")
    att_codes = {str(_pick(r, CODE_KEYS)).strip()
                 for r in att if isinstance(r, dict) and _pick(r, CODE_KEYS)}

    log.info("Fetching 處置股 (disposition) …")
    disp = fetch_json(ENDPOINTS["disposition"], "disposition")
    disp_codes = {str(_pick(r, CODE_KEYS)).strip()
                  for r in disp if isinstance(r, dict) and _pick(r, CODE_KEYS)}

    log.info("Fetching 月營收 TWSE …")
    rev_twse = fetch_json(ENDPOINTS["revenue_twse"], "rev_twse")
    log.info("Fetching 月營收 TPEx …")
    rev_tpex = fetch_json(ENDPOINTS["revenue_tpex"], "rev_tpex")

    revenue_decline = {}                          # ticker -> YoY %
    for row in (rev_twse + rev_tpex):
        if not isinstance(row, dict):
            continue
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

    # Per-ticker payload: a flag list and the resulting L3 score.
    # Multiple flags don't stack below −0.6 (the guide treats L3 as an exclusion
    # filter, not an additive score — one bad flag is already "exclude").
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
        "source": "TWSE OpenAPI",
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
