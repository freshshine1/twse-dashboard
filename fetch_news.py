"""
fetch_news.py — PURE PARSER for the News tab (written by NewsIngest.gs).

No network / no Google libraries: the feeder reads the News tab with its existing
get_gsheet_token() + read_sheet_tab() helpers (raw REST via `requests`, same path it
uses for T1/T2) and passes the raw rows here. Keeping this dependency-free means it
can never fail to import on the runner (requirements.txt is only requests + dateutil).

Python stays READ-ONLY on the sheet; NewsIngest.gs is the only writer.
Tiering: each row carries `sender`, so per-source tier is applied downstream — news
biases/vetoes L5 only, never originates a Tier-1 threshold.

2026-06-04 changes (no new deps, all stdlib):
  - _normalize_date(): the date filter used a raw string compare (`nd < cutoff`),
    which silently dropped EVERY row if NewsIngest.gs wrote a non-ISO date
    (e.g. "2026/6/4" or "6/4/2026"). We now coerce common formats to ISO before
    comparing, so the window filter is robust to the sheet's date formatting.
  - tag_sectors(): adds a `sectors` list to each row so industry/market-level news
    (the "大盤/產業" rows with no specific ticker) can be grouped by theme on the
    dashboard. Keyword map is Tier-3 display-only — it never feeds a score.
"""

from datetime import date, timedelta
from collections import defaultdict
import re

# Columns written by NewsIngest.gs (order matters; header row is already stripped
# by read_sheet_tab, so `rows` here are data rows only).
COLS = ["dedup_key", "news_date", "ingested_at", "sender", "ticker",
        "name", "tag", "headline", "snippet", "gmail_link"]

# Whole-inbox read picks up the odd system mail (account alerts, mailer-daemon).
# Drop obvious non-news senders — a tiny denylist, not a source allowlist.
SENDER_DENYLIST = ("accounts.google.com", "no-reply@google", "mailer-daemon",
                   "postmaster", "googlemail.com>")

# ── Sector / theme keyword map (Tier-3, display-only grouping) ───────────────────────
# Each sector -> list of substrings to look for in headline + snippet.
# A row may match multiple sectors; order here is the display priority.
SECTOR_KEYWORDS = [
    ("AI",      ["AI", "人工智慧", "算力", "CoWoS", "輝達", "NVIDIA", "Nvidia",
                 "GPU", "伺服器", "資料中心", "大型語言", "LLM"]),
    ("半導體",   ["半導體", "晶圓", "晶片", "台積電", "封測", "先進製程",
                 "矽智財", "IC設計", "晶圓代工"]),
    ("散熱",     ["散熱", "水冷", "均熱", "液冷", "熱導"]),
    ("記憶體",   ["記憶體", "DRAM", "NAND", "HBM", "記憶"]),
    ("網通",     ["網通", "交換器", "光通訊", "CPO", "矽光子", "光模組"]),
    ("被動元件", ["被動元件", "MLCC", "電感", "電阻"]),
    ("面板",     ["面板", "顯示器", "OLED", "驅動IC"]),
    ("電動車",   ["電動車", "車用", "充電", "電池", "EV"]),
    ("金融",     ["金控", "銀行", "壽險", "證券", "升息", "降息", "利率"]),
    ("生技",     ["生技", "醫療", "製藥", "新藥", "疫苗"]),
    ("大盤",     ["台股", "加權", "大盤", "指數", "外資", "三大法人", "成交量"]),
]


def _normalize_date(s):
    """Coerce a date string to ISO 'YYYY-MM-DD'. Returns '' if unparseable.

    Handles: '2026-06-04', '2026/6/4', '2026.6.4', '6/4/2026', '06-04-2026'.
    Pure/total — never raises. Keeps the parser dependency-free.
    """
    s = (s or "").strip()
    if not s:
        return ""
    # Already ISO-ish: 2026-06-04 or 2026-6-4
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # US-ish: 6/4/2026 or 06-04-2026 (month first)
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", s)
    if m:
        mo, d, y = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # Last resort: grab a leading ISO date out of a timestamp like '2026-06-04T09:00'
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return "-".join(m.groups())
    return ""


def tag_sectors(text):
    """Return a list of sector tags whose keywords appear in `text` (case-insensitive
    for ASCII keywords; CJK matched as-is). Display-only — never gates a score."""
    if not text:
        return []
    low = text.lower()
    hits = []
    for sector, kws in SECTOR_KEYWORDS:
        for kw in kws:
            # ASCII keywords are matched case-insensitively; CJK keywords as-is.
            if kw.isascii():
                if kw.lower() in low:
                    hits.append(sector)
                    break
            elif kw in text:
                hits.append(sector)
                break
    return hits


def parse_news_rows(rows, days=5):
    """Raw rows (list[list] from read_sheet_tab) -> cleaned dicts, recent-first.

    Filters by resolved news_date window and the sender denylist. Pure/total —
    bad input just yields fewer rows, never raises. Each output row gains:
      - news_date normalized to ISO
      - `sectors`: list of theme tags (for grouping industry/market news)
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for r in rows or []:
        r = (list(r) + [""] * len(COLS))[:len(COLS)]      # pad/truncate to schema
        rec = dict(zip(COLS, r))
        nd = _normalize_date(rec["news_date"])
        if not nd or nd < cutoff:
            continue
        rec["news_date"] = nd                              # store normalized ISO back
        if any(bad in rec["sender"].lower() for bad in SENDER_DENYLIST):
            continue
        rec["sectors"] = tag_sectors((rec.get("headline") or "") + " " +
                                     (rec.get("snippet") or ""))
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


def sector_rollup(news_recent):
    """Parsed rows -> {sector: [rows...]} for grouping market/industry themes on the
    dashboard. A row appears under each sector it matched. Display-only."""
    agg = defaultdict(list)
    for rec in news_recent:
        for sec in rec.get("sectors", []):
            agg[sec].append(rec)
    return dict(agg)


if __name__ == "__main__":
    # self-test with synthetic rows (no network)
    today = date.today().isoformat()
    slash = date.today().strftime("%Y/%-m/%-d")   # non-ISO format the .gs might emit
    sample = [
        ["k1", today, today, "Fisher <x>", "3017", "奇鋐", "bull", "散熱商機爆發 AI 伺服器需求強", "...", "http://m/1"],
        ["k2", today, today, "no-reply@google.com", "", "", "neutral", "Security alert", "...", "http://m/2"],
        ["k3", slash, today, "SinoPac", "", "", "watch", "台股站上4萬6千點 外資買超", "...", "http://m/3"],
        ["k4", "2020-01-01", "old", "Fisher", "2330", "台積電", "bull", "台積電法說", "...", "http://m/4"],
    ]
    rows = parse_news_rows(sample, days=5)
    print(f"{len(rows)} rows after filter (Google alert + stale dropped, slash-date kept):")
    for r in rows:
        print(" ", r["news_date"], r["ticker"] or "—", r["tag"], r["sectors"], "|", r["headline"])
    print("bias:", news_bias_by_ticker(rows))
    print("sectors:", {k: len(v) for k, v in sector_rollup(rows).items()})
