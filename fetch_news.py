"""
fetch_news.py — PURE PARSER for the News tab (written by NewsIngest.gs).

No network / no Google libraries: the feeder reads the News tab with its existing
get_gsheet_token() + read_sheet_tab() helpers (raw REST via `requests`, same path it
uses for T1/T2) and passes the raw rows here. Keeping this dependency-free means it
can never fail to import on the runner (requirements.txt is only requests + dateutil).

Python stays READ-ONLY on the sheet; NewsIngest.gs is the only writer.
Tiering: each row carries `sender`, so per-source tier is applied downstream — news
biases/vetoes L5 only, never originates a Tier-1 threshold.
"""

from datetime import date, timedelta
from collections import defaultdict

# Columns written by NewsIngest.gs (order matters; header row is already stripped
# by read_sheet_tab, so `rows` here are data rows only).
COLS = ["dedup_key", "news_date", "ingested_at", "sender", "ticker",
        "name", "tag", "headline", "snippet", "gmail_link"]

# Whole-inbox read picks up the odd system mail (account alerts, mailer-daemon).
# Drop obvious non-news senders — a tiny denylist, not a source allowlist.
SENDER_DENYLIST = ("accounts.google.com", "no-reply@google", "mailer-daemon",
                   "postmaster", "googlemail.com>")


def parse_news_rows(rows, days=5):
    """Raw rows (list[list] from read_sheet_tab) -> cleaned dicts, recent-first.

    Filters by resolved news_date window and the sender denylist. Pure/total —
    bad input just yields fewer rows, never raises.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for r in rows or []:
        r = (list(r) + [""] * len(COLS))[:len(COLS)]      # pad/truncate to schema
        rec = dict(zip(COLS, r))
        nd = (rec["news_date"] or "").strip()
        if not nd or nd < cutoff:
            continue
        if any(bad in rec["sender"].lower() for bad in SENDER_DENYLIST):
            continue
        out.append(rec)
    out.sort(key=lambda x: x["news_date"], reverse=True)
    return out


def news_bias_by_ticker(news_recent):
    """Parsed rows -> {code: {bull, bear, watch, headlines[]}} for L5 / per-card display."""
    agg = defaultdict(lambda: {"bull": 0, "bear": 0, "watch": 0, "headlines": []})
    for rec in news_recent:
        code = (rec.get("ticker") or "").strip()
        if not code:
            continue
        tag = rec.get("tag") if rec.get("tag") in ("bull", "bear", "watch") else None
        if tag:
            agg[code][tag] += 1
        if len(agg[code]["headlines"]) < 5:
            agg[code]["headlines"].append({
                "date": rec.get("news_date"),
                "tag": rec.get("tag"),
                "headline": rec.get("headline"),
                "sender": rec.get("sender"),
            })
    return dict(agg)


if __name__ == "__main__":
    # self-test with synthetic rows (no network)
    today = date.today().isoformat()
    sample = [
        ["k1", today, today, "Fisher <x>", "3017", "奇鋐", "bull", "散熱商機爆發", "...", "http://m/1"],
        ["k2", today, today, "no-reply@google.com", "", "", "neutral", "Security alert", "...", "http://m/2"],
    ]
    rows = parse_news_rows(sample, days=5)
    print(f"{len(rows)} rows after filter (Google alert dropped):")
    for r in rows:
        print(" ", r["news_date"], r["ticker"] or "—", r["tag"], r["headline"])
    print("bias:", news_bias_by_ticker(rows))
