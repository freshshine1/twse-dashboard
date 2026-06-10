"""
feeder_us.py — L4 US/Global Overnight Regime layer.

Runs at 08:00 TPE (00:00 UTC) Mon–Fri, ~3–4 hours after the US close, ~1 hour
before TW market open. Pulls free Yahoo Finance quotes and computes a single
"regime tilt" number for the upcoming TW session.

Components (weighted contributions to tilt, in pct-of-day-move terms):
  ^SOX   2.0× — Philadelphia Semiconductor, the dominant signal for TW tech
  TSM    2.0× — TSMC ADR; proxy for the index-leader's overnight move
  ^GSPC  1.0× — S&P 500; broad US mood
  ^VIX   0.3× INVERTED — rising VIX = risk-off; capped contribution

Output: tilt_raw ∈ [-10, +10], L4 = tilt/10 ∈ [-1, +1]. Per IMPLEMENTATION_GUIDE
Chapter 4, tilt ≤ −5 triggers regime_veto (no new GO signals downstream).

Writes two files:
  docs/raw/us_overnight_YYYY-MM-DD.json  — archive (one per session)
  docs/raw/us_overnight_latest.json      — always-current; dashboard reads this

Dependency-light: only `requests` + stdlib. No auth, no Google APIs.
"""
import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

log = logging.getLogger("feeder_us")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TPE  = timezone(timedelta(hours=8))
YHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1d&range=5d"

# (symbol, weight, label_for_payload, invert_sign, contrib_cap)
# contrib_cap = max absolute raw contribution this component may add to the tilt
# (None = uncapped). VIX is capped because its daily % moves are 4-5x larger than
# index % moves, so even at weight 0.3 it could otherwise dominate the tilt (on
# 2026-06-08 a -12% VIX day contributed ~46% of the tilt — see Chapter 4 audit note).
# The cap keeps VIX a mood *garnish* (max ~0.94 tilt pts) so SOX/TSM stay the drivers,
# matching the intent that L4 tracks US-tech-overnight, not broad risk mood.
# Future: revisit as Option C (normalise VIX to its own scale) per the guide note.
COMPONENTS = [
    ("^SOX",  2.0, "SOX",  False, None),
    ("TSM",   2.0, "TSM",  False, None),
    ("^GSPC", 1.0, "GSPC", False, None),
    ("^VIX",  0.3, "VIX",  True,  2.5),
]


def fetch_quote(symbol, retries=3, backoff=4):
    """Return {close, chg_pct, symbol} for `symbol`, computed from the last two
    non-null daily closes. Returns None on failure (caller decides to abort)."""
    url = YHOO.format(symbol)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            # Diagnostic: capture HTTP details before raising. Yahoo Finance has
            # been known to 401/429 cloud IPs (incl. GitHub-hosted runners). If
            # this consistently fails, we'll switch to Stooq as a fallback source.
            if r.status_code != 200:
                log.warning("  %s HTTP %d body[:200]=%r", symbol, r.status_code, r.text[:200])
            r.raise_for_status()
            d = r.json()
            result = d["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                raise ValueError(f"{symbol} returned <2 closes")
            chg_pct = (closes[-1] / closes[-2] - 1.0) * 100.0
            return {"close": round(closes[-1], 2),
                    "chg_pct": round(chg_pct, 2),
                    "symbol": symbol}
        except Exception as e:
            log.warning("fetch %s attempt %d/%d failed: %s", symbol, attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    return None


def compute_tilt(comps):
    """Weighted sum of pct moves (VIX inverted), with an optional per-component
    contribution cap (Option B, 2026-06-10). Clipped to ±(sum_of_weights × 5),
    then scaled to ±10. Returns (tilt, n_contributors)."""
    raw = 0.0
    n = 0
    for symbol, weight, label, invert, contrib_cap in COMPONENTS:
        c = comps.get(label)
        if c is None:
            log.warning("%s missing — skipping in tilt", label)
            continue
        contrib = c["chg_pct"] * weight
        if invert:
            contrib = -contrib
        if contrib_cap is not None:
            contrib = max(-contrib_cap, min(contrib_cap, contrib))
        raw += contrib
        n += 1
    # A "full" ±5% day on every component caps at ±(sum_of_weights × 5).
    # NB: cap is over ALL weights (the design max), not just fetched ones.
    cap = sum(w for _, w, _, _, _ in COMPONENTS) * 5.0
    raw = max(-cap, min(cap, raw))
    # Scale to ±10. cap = sum_of_weights × 5 (currently 26.5); kept as a formula
    # so it stays correct if weights are ever retuned.
    tilt = raw * 10.0 / cap
    return round(tilt, 2), n


def label_for_tilt(tilt):
    if tilt >=  5: return "Strong Bullish"
    if tilt >=  2: return "Bullish"
    if tilt >  -2: return "Neutral"
    if tilt >  -5: return "Bearish"
    return "Strong Bearish (veto)"


def main():
    now_tpe = datetime.now(TPE)
    # The US session that closed overnight is "yesterday" in TPE terms — coarse but fine
    # for labelling; the actual close time depends on EDT/EST and isn't load-bearing here.
    us_session_date = (now_tpe - timedelta(days=1)).strftime("%Y-%m-%d")

    comps = {}
    for symbol, _, label, _, _ in COMPONENTS:
        log.info("Fetching %s …", symbol)
        q = fetch_quote(symbol)
        if q:
            comps[label] = q
            log.info("  %s close=%.2f chg=%+.2f%%", label, q["close"], q["chg_pct"])

    if len(comps) < 2:
        log.error("Only %d components fetched — refusing to write partial L4", len(comps))
        sys.exit(1)

    tilt, n = compute_tilt(comps)
    veto = tilt <= -5
    L4   = round(max(-1.0, min(1.0, tilt / 10.0)), 3)

    payload = {
        "asof":             now_tpe.isoformat(timespec="seconds"),
        "us_session_date":  us_session_date,
        "components":       comps,
        "tilt_raw":         tilt,
        "regime_veto":      veto,
        "L4":               L4,
        "label":            label_for_tilt(tilt),
        "contributors":     n,
    }

    out_dir = Path("docs/raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    dated_path  = out_dir / f"us_overnight_{now_tpe.strftime('%Y-%m-%d')}.json"
    latest_path = out_dir / "us_overnight_latest.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    dated_path.write_text(body)
    latest_path.write_text(body)
    log.info("Wrote %s + %s | tilt=%.2f label=%s veto=%s L4=%+.3f",
             dated_path, latest_path, tilt, payload["label"], veto, L4)


if __name__ == "__main__":
    main()
