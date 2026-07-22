#!/usr/bin/env python3
"""twse-run-review v1.1 — read-only pipeline audit for freshshine1/twse-dashboard.

Usage:
    python3 review_run.py                 # audit latest session found in run_log.csv
    python3 review_run.py --date 2026-07-15

Checks (each prints GREEN / AMBER / RED / INFO):
  1. Run ledger rows for the session (primary + backupB expected; double row is normal)
  2. Snapshot presence: docs/raw/snapshot_<session>.json
  3. Board health stamps in docs/data.json (t86 / price / data / l3 / l4 / analysis)
     - l3 lag triggers the stale-stub sub-check: fetch dated L3 file, report
       stale_reason as AMBER (designed stand-down, not a failure)
  4. Commit cadence via the atom feed (L3 / primary / backupB / L4 commits)
  5. Backup stand-down sanity (commit without ledger row = RED; neither = stand-down)

Stdlib only. Read-only — never writes to the repo. Exit code: 1 if any RED, else 0.

House rules honored:
  - Cache-busted raw fetches (verification reads only).
  - CDN race: raw can serve pre-commit content ~75s+ after a commit. If results look
    stale seconds after a commit, wait and re-run before alarming.
  - Trading calendar is inferred (weekday + ledger presence). A weekday with no run is
    AMBER "possible market closure — verify manually", never auto-RED.
  - v1.1: board-build age is counted in TRADING days, not wall-clock days. Weekends are
    not staleness — reviewing Friday's board on Monday morning is 0 trading days old,
    not 3. Ledger session dates are the observed calendar; a weekday gap the ledger does
    not confirm may be a holiday, so it can never escalate past AMBER.
"""

import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, date, timedelta, timezone

REPO = "freshshine1/twse-dashboard"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
ATOM = f"https://github.com/{REPO}/commits/main.atom"
TPE = timezone(timedelta(hours=8))
SNAPSHOT_EPOCH = date(2026, 7, 13)  # snapshot persistence shipped session 27

GREEN, AMBER, RED, INFO = "GREEN", "AMBER", "RED", "INFO"
_results = []


def report(level, check, detail):
    _results.append(level)
    pad = {"GREEN": "\u2705 GREEN", "AMBER": "\U0001f7e1 AMBER",
           "RED": "\U0001f534 RED  ", "INFO": "\u2139\ufe0f  INFO "}[level]
    print(f"[{pad}] {check}: {detail}")


def fetch(path_or_url, cache_bust=True):
    """Fetch text. Raw-repo paths get a cache-bust param (verification read)."""
    url = path_or_url if path_or_url.startswith("http") else f"{RAW}/{path_or_url}"
    if cache_bust:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}cb={int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "twse-run-review/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def parse_date(s):
    """Best-effort date from ISO date or datetime string."""
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return date.fromisoformat(m.group(1)) if m else None


def load_run_log():
    text = fetch("processed/run_log.csv")
    if text is None:
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows


def load_atom_entries():
    text = fetch(ATOM, cache_bust=False)
    entries = []
    for block in re.findall(r"<entry>(.*?)</entry>", text, re.S):
        sha = re.search(r"Commit/([0-9a-f]{40})", block)
        title = re.search(r"<title>(.*?)</title>", block, re.S)
        updated = re.search(r"<updated>(.*?)</updated>", block)
        entries.append({
            "sha": sha.group(1)[:7] if sha else "?",
            "title": title.group(1).strip() if title else "",
            "updated": updated.group(1) if updated else "",
        })
    return entries


def prev_weekday(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def trading_day_gap(build_d, today, session_dates):
    """Trading sessions missed between the last board build and today (v1.1).

    Wall-clock day-counting made Monday mornings false-RED: Friday's board is the
    freshest board that can exist over a weekend, but read 3 calendar days old
    (session 30, reviewing the 2026-07-17 session on Monday 2026-07-20).

    Counts weekdays strictly between `build_d` and `today`. Today itself never
    counts — its board is not due until the 18:13 TPE primary, so a board from the
    previous session is correct all morning.

    The calendar is the OBSERVED one. `session_dates` (run_log session dates) is
    positive evidence a date traded, since only board-producing runs write a ledger
    row. A gap weekday the ledger CONFIRMS is a real missed board; one it does not
    confirm may be a holiday or an ad-hoc closure (§17.2 typhoon), so it can never
    escalate past AMBER — same stance as the ledger check, and the script still has
    no holiday table by design.

    Returns (confirmed, unconfirmed) lists of date objects.
    """
    gap = []
    d = build_d + timedelta(days=1)
    while d < today:
        if d.weekday() < 5:
            gap.append(d)
        d += timedelta(days=1)
    confirmed = [g for g in gap if g.isoformat() in session_dates]
    unconfirmed = [g for g in gap if g.isoformat() not in session_dates]
    return confirmed, unconfirmed


def main():
    ap = argparse.ArgumentParser(description="Audit one pipeline session (read-only).")
    ap.add_argument("--date", help="Session date YYYY-MM-DD (default: latest in run_log)")
    args = ap.parse_args()

    now_tpe = datetime.now(TPE)
    print(f"twse-run-review v1.1 \u2014 now {now_tpe:%Y-%m-%d %H:%M} TPE")

    # ---- Load shared inputs (batched up front) ----
    run_log = load_run_log()
    if run_log is None:
        report(RED, "run_log", "processed/run_log.csv missing from repo")
        return finish()

    # Observed trading calendar: every board-producing run writes a ledger row,
    # so these dates are positive evidence a session traded (v1.1 age check).
    session_dates = {r["session_date"] for r in run_log if r.get("session_date")}

    if args.date:
        session = date.fromisoformat(args.date)
    else:
        dates = sorted({r["session_date"] for r in run_log if r.get("session_date")})
        if not dates:
            report(RED, "run_log", "ledger is empty")
            return finish()
        session = date.fromisoformat(dates[-1])
    s = session.isoformat()
    print(f"Target session: {s} ({session:%A})\n")

    if session.weekday() >= 5:
        report(AMBER, "calendar", f"{s} is a weekend \u2014 no run expected; "
                                  "checks below will mostly be vacuous")

    data = json.loads(fetch("docs/data.json") or "{}")
    health = data.get("health", {})
    atom = load_atom_entries()

    # ---- Check 1: ledger rows ----
    rows = [r for r in run_log if r.get("session_date") == s]
    slots = [r.get("run_slot", "?") for r in rows]
    backupb_due = now_tpe > datetime(session.year, session.month, session.day,
                                     tzinfo=TPE) + timedelta(days=1, hours=8)
    if "primary" in slots and "backupB" in slots:
        report(GREEN, "ledger", f"rows for {s}: {slots} \u2014 primary + nightly "
                                "backupB overwrite (documented, normal until 7/28 MIS)")
    elif "primary" in slots:
        if backupb_due:
            report(GREEN, "ledger", f"rows: {slots} \u2014 backupB absent; see "
                                    "stand-down check below")
        else:
            report(GREEN, "ledger", f"rows: {slots} \u2014 backupB not due yet "
                                    "(runs ~02:43 TPE next day + drift)")
    elif rows:
        report(AMBER, "ledger", f"rows exist but no primary: {slots} \u2014 check "
                                "whether primary failed red or was superseded")
    else:
        if session.weekday() < 5:
            report(AMBER, "ledger", f"no rows for weekday {s} \u2014 possible market "
                                    "closure (typhoon/holiday); verify manually")
        else:
            report(INFO, "ledger", f"no rows for {s} (weekend \u2014 expected)")

    for r in rows:
        if r.get("run_slot") not in ("primary", "backupB", "backupA"):
            report(AMBER, "ledger", f"unexpected slot '{r.get('run_slot')}' in row {r}")
    if len(slots) != len(set(slots)):
        report(AMBER, "ledger", f"duplicate slot rows for {s}: {slots}")

    # ---- Check 2: snapshot presence ----
    if session < SNAPSHOT_EPOCH:
        report(INFO, "snapshot", f"{s} predates snapshot persistence (2026-07-13); "
                                 "no archive expected")
    else:
        snap = fetch(f"docs/raw/snapshot_{s}.json")
        if snap is None:
            if rows:
                report(RED, "snapshot", f"docs/raw/snapshot_{s}.json MISSING despite "
                                        "ledger rows \u2014 git-add path broken?")
            else:
                report(AMBER, "snapshot", f"snapshot_{s}.json absent (no run either "
                                          "\u2014 consistent with closure)")
        else:
            try:
                upd = json.loads(snap).get("updated", "?")
                report(GREEN, "snapshot", f"snapshot_{s}.json present, updated {upd} "
                                          "(backupB overwrite timestamp is normal)")
            except json.JSONDecodeError:
                report(RED, "snapshot", f"snapshot_{s}.json present but not valid JSON")

    # ---- Check 3: board health stamps ----
    t86 = parse_date(health.get("t86"))
    data_d = parse_date(health.get("data"))
    l3_d = parse_date(health.get("l3"))
    l4_d = parse_date(health.get("l4"))
    an_d = parse_date(health.get("analysis"))

    if t86 == session:
        report(GREEN, "health.t86", f"{health.get('t86')} == target session")
    elif t86 and t86 > session:
        report(INFO, "health.t86", f"{health.get('t86')} \u2014 board has moved past "
                                   "the target session (auditing an older run)")
    elif rows:
        report(RED, "health.t86", f"{health.get('t86')} < {s} despite ledger rows "
                                  "\u2014 board did not update")
    else:
        report(AMBER, "health.t86", f"{health.get('t86')} \u2014 no board for {s} "
                                    "(consistent with no-run/closure)")

    if data_d:
        cal_age = (now_tpe.date() - data_d).days
        confirmed, unconfirmed = trading_day_gap(
            data_d, now_tpe.date(), session_dates)
        td_age = len(confirmed) + len(unconfirmed)
        if len(confirmed) >= 2:
            lvl = RED
        elif confirmed or unconfirmed:
            lvl = AMBER
        else:
            lvl = GREEN
        detail = (f"last board build {health.get('data')} "
                  f"({td_age} trading-day gap; {cal_age}d wall-clock)")
        if confirmed:
            detail += (" \u2014 ledger confirms session(s) "
                       + ", ".join(c.isoformat() for c in confirmed)
                       + " with no fresher board")
        elif unconfirmed:
            detail += (" \u2014 weekday gap "
                       + ", ".join(u.isoformat() for u in unconfirmed)
                       + " absent from ledger (possible closure \u2014 verify)")
        report(lvl, "health.data", detail)

    # L3 with stale-stub sub-check. Expectation is run-window-aware: L3 lands
    # ~11:44-12:34 TPE (cron drift), so before 13:00 TPE today's stamp isn't due yet.
    today = now_tpe.date()
    if today.weekday() < 5 and now_tpe.hour >= 13:
        last_td = today
    else:
        last_td = prev_weekday(today)
    if l3_d and l3_d >= last_td:
        report(GREEN, "health.l3", f"{health.get('l3')} \u2014 fresh")
    elif l3_d:
        stub_date = last_td.isoformat()
        stub_raw = fetch(f"docs/raw/l3_fundamentals_{stub_date}.json")
        if stub_raw:
            try:
                stub = json.loads(stub_raw)
            except json.JSONDecodeError:
                stub = {}
            if stub.get("stale"):
                report(AMBER, "health.l3", f"stamp {health.get('l3')} lags; dated file "
                       f"{stub_date} is a designed stale-stub \u2014 reason: "
                       f"{stub.get('stale_reason', '(none recorded)')}")
            else:
                report(RED, "health.l3", f"stamp {health.get('l3')} lags but dated file "
                       f"{stub_date} is NOT a stale-stub \u2014 latest.json not "
                       "refreshed or board built before L3; inspect Actions log")
        else:
            report(AMBER, "health.l3", f"stamp {health.get('l3')} lags and no dated L3 "
                   f"file for {stub_date} \u2014 L3 run absent (weekend/closure/"
                   "workflow failure); verify manually")
    else:
        report(RED, "health.l3", "no l3 stamp in health block")

    # L4: allowed to lag one build (L4 commit can land after the last board build)
    if l4_d and data_d:
        lag = (data_d - l4_d).days
        lvl = GREEN if lag <= 1 else (AMBER if lag == 2 else RED)
        report(lvl, "health.l4", f"{health.get('l4')} \u2014 lag vs board build: {lag}d "
                                 "(\u22641d normal: morning L4 lands after backupB)")

    if an_d:
        report(INFO, "health.analysis", f"{health.get('analysis')} \u2014 L5 parked "
                                        "(dark since 2026-05-28, decision owed)")

    # ---- Check 4: commit cadence (atom feed, ~20 most recent entries) ----
    def find(pattern):
        return [e for e in atom if re.search(pattern, e["title"])]

    l3_commits = find(rf"L3 fundamentals {s}")
    board_commits = find(rf"daily data update {s}")
    l4_commits = find(rf"L4 us_overnight {s}")
    oldest = atom[-1]["updated"] if atom else ""
    feed_covers = parse_date(oldest) and parse_date(oldest) <= session

    if not feed_covers:
        report(INFO, "cadence", f"atom feed no longer covers {s} (oldest entry "
                                f"{oldest}) \u2014 cadence check skipped")
    else:
        if l3_commits:
            report(GREEN, "cadence.l3", f"L3 commit {l3_commits[0]['sha']} at "
                                        f"{l3_commits[0]['updated']}")
        elif session.weekday() < 5:
            report(AMBER, "cadence.l3", f"no 'L3 fundamentals {s}' commit \u2014 "
                                        "weekend/closure or L3 workflow miss")
        if board_commits:
            times = ", ".join(f"{e['sha']}@{e['updated']}" for e in board_commits)
            n = len(board_commits)
            report(GREEN, "cadence.board", f"{n} board commit(s): {times} "
                   "(2/session = primary + backupB, normal)")
        elif rows:
            report(RED, "cadence.board", f"ledger rows exist but no board commits "
                                         f"titled {s} in feed \u2014 investigate")
        else:
            report(AMBER, "cadence.board", f"no board commits for {s} \u2014 "
                                           "consistent with closure; verify")
        if l4_commits:
            report(GREEN, "cadence.l4", f"L4 commit {l4_commits[0]['sha']} at "
                   f"{l4_commits[0]['updated']} (feeds next TPE morning's board)")
        else:
            report(INFO, "cadence.l4", f"no L4 commit titled {s} in feed (runs "
                                       "~22:59 UTC; may be pending or scrolled off)")

    # ---- Check 5: backup stand-down sanity ----
    bB_rows = [r for r in rows if r.get("run_slot") == "backupB"]
    # backupB board commit lands ~18:43+ UTC on the session's UTC date
    bB_commits = [e for e in board_commits
                  if e["updated"] >= f"{s}T17:00:00"] if feed_covers else []
    if bB_commits and not bB_rows:
        report(RED, "backupB", "board commit in backupB window but NO ledger row "
                               "\u2014 append_run_log failed?")
    elif bB_rows:
        report(GREEN, "backupB", f"ran and logged (finished {bB_rows[0].get('finished_utc')})")
    elif backupb_due:
        report(GREEN, "backupB", "no row + no commit \u2014 stood down (writes no row "
                                 "by design)")
    else:
        report(INFO, "backupB", "not due yet")

    return finish()


def finish():
    reds = _results.count(RED)
    ambers = _results.count(AMBER)
    print(f"\nSummary: {_results.count(GREEN)} green, {ambers} amber, {reds} red")
    if reds:
        print("VERDICT: RED \u2014 needs attention")
        return 1
    if ambers:
        print("VERDICT: AMBER \u2014 designed stand-downs or items to verify manually")
    else:
        print("VERDICT: ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
