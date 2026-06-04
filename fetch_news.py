"""
fetch_news.py — read the News tab (written by NewsIngest.gs) for the L5 news layer.

Reuses the SAME service-account credential the feeder already uses for T1/T2
(GOOGLE_CREDENTIALS). Python stays READ-ONLY on the sheet; the Apps Script is the
only writer. Tiering: each row carries `sender`, so per-source tier (Tier-2 regulated
vs Tier-3 aggregator vs community) is applied downstream — news only biases/vetoes L5,
never originates a Tier-1 threshold.
"""

import os
import json
from datetime import date, timedelta
from collections import defaultdict

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# News lives in its OWN sheet (Sheet B, owned by Account B, shared with the service
# account). This is NOT the portfolio sheet. Set NEWS_SHEET_ID in the workflow env.
SHEET_ID = os.environ.get("NEWS_SHEET_ID", "")
NEWS_TAB = "News"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
# Columns written by NewsIngest.gs (keep in sync):
COLS = ["dedup_key", "news_date", "ingested_at", "sender", "ticker",
        "name", "tag", "headline", "snippet", "gmail_link"]


def _sheets_service():
    # Same GOOGLE_CREDENTIALS secret the feeder already uses for T1/T2.
    creds_json = os.environ["GOOGLE_CREDENTIALS"]
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def fetch_news(days=3, service=None):
    """Return news rows from the last `days` days (by resolved news_date), newest first.

    Returns [] on any failure so a news-source hiccup never breaks the run.
    """
    try:
        if not SHEET_ID:
            print("[news] NEWS_SHEET_ID not set, skipping L5 news")
            return []
        svc = service or _sheets_service()
        resp = (svc.spreadsheets().values()
                .get(spreadsheetId=SHEET_ID, range=f"{NEWS_TAB}!A2:J")
                .execute())
        raw = resp.get("values", [])
    except Exception as exc:                      # missing tab, auth, network, etc.
        print(f"[news] fetch failed, skipping L5 news: {exc}")
        return []

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for r in raw:
        r = (r + [""] * len(COLS))[:len(COLS)]     # pad short rows
        rec = dict(zip(COLS, r))
        if rec["news_date"] and rec["news_date"] >= cutoff:
            out.append(rec)
    out.sort(key=lambda x: x["news_date"], reverse=True)
    return out


def news_bias_by_ticker(days=3, service=None):
    """Aggregate recent news into a per-ticker bias for L5.

    {code: {"bull": n, "bear": n, "watch": n, "headlines": [...]}}.
    L5 scoring/veto is wired separately; this is the clean feed it consumes.
    """
    agg = defaultdict(lambda: {"bull": 0, "bear": 0, "watch": 0, "headlines": []})
    for rec in fetch_news(days=days, service=service):
        code = rec["ticker"].strip()
        if not code:
            continue
        tag = rec["tag"] if rec["tag"] in ("bull", "bear", "watch") else None
        if tag:
            agg[code][tag] += 1
        if len(agg[code]["headlines"]) < 5:
            agg[code]["headlines"].append({"date": rec["news_date"],
                                           "tag": rec["tag"],
                                           "headline": rec["headline"],
                                           "sender": rec["sender"]})
    return dict(agg)


if __name__ == "__main__":
    rows = fetch_news(days=7)
    print(f"{len(rows)} news rows (last 7d)")
    for r in rows[:10]:
        print(f"  {r['news_date']}  {r['ticker'] or '—':>6}  [{r['tag']}]  {r['headline'][:40]}")
