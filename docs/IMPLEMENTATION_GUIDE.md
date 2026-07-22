# Watchlist System — Implementation Instruction Set

**Version:** v2 · **Created:** 2026-06-01 · **Last updated:** 2026-06-10

> **Changelog (newest first).** The title no longer carries a single date — read this block, not the
> header, to know what is fresh. Major version (v2) tracks *structural* revisions; append-only notes
> and status flips are minor. Git holds the full per-line history.
>
> - **2026-07-22** — Added **Chapter 19** (two undocumented scoring divergences, session 32):
>   `ENABLE_MARGIN=1` has been live in production since at least 2026-06-16 while every doc
>   called `margin_score` an unshipped stub — a §6 built-≠-documented divergence spanning the
>   entire `signal_log` window (19.1); the L1 float-cap unit is 1000× too small, which has
>   collapsed the T86 component of L1 into a **sign vote** on trust/foreign/dealer for the whole
>   observe window — reproduced 48/48 against live `score.py` (19.2); the same unit bug in
>   `_norm_mag` saturates the §12.2 `driver` string so 投信 wins 18/18 tied rows (19.3);
>   `FLOAT_M` value-audit debt (19.4); how the 7/28 review must read its own L1 bands (19.5);
>   §14.5 roll-time evidence ruling out option (a) (19.6). **Documentation + decisions owed —
>   no code changed, freeze intact.**
> - **2026-07-20** — Added **Chapter 18** (skill in production, 7/17 crash-day T86 gap,
>   hit-rate grader, sessions 29–30): `twse-run-review` skill shipped + first production runs,
>   backlog item 5 DONE — the L3 stale-stub check noted as future in §17.5 shipped in v1 (18.1);
>   record −6.47% crash day 7/17 — market-level T86 fetch returned empty under load, board
>   shipped with zeroed institutional header + degraded L1; self-heals next primary because T86
>   windows are re-fetched per-date every run, no local chip history (18.2); hit-metric decision
>   — fwd_5d sign PRIMARY — and `tools/hitrate_review.py` shipped (18.3). All tooling /
>   incident record — freeze intact.
> - **2026-07-14** — Added **Chapter 17** (run ledger, snapshot persistence & failure anatomy,
>   sessions 26–28): intraday-tab tooltips (17.1); typhoon-closure behavior verified clean (17.2);
>   run ledger `processed/run_log.csv` + `RUN_SLOT` slot plumbing + snapshot persistence with
>   session-date filenames (17.3); pre-dawn Backup-B false-red root cause + green stand-down fix
>   (17.4); `health.l3` "staleness" resolved as feeder_l3's designed stale-stub guard, NOT a bug
>   (17.5); raw Actions log fetch pattern + operational facts (17.6); primary cron 19:13→18:13 TPE
>   and checkout@v5 / setup-python@v6 bumps (17.7). All display/reliability — freeze intact.
> - **2026-07-03** — Added **Chapter 16** (Intraday cross-reference tab, session 22): new
>   display-only 盤中 tab reading live MIS quotes for the board universe via a 5-min cron
>   (`feeder_intraday.py` + `intraday.yml`) pushing to the un-served `data` branch (Pages
>   build-throttle rationale). Live price / 量比 / 掛單 imbalance / 距MA20 cross-referenced
>   against the frozen board; 0050-red regime gate renders ADD-side actions `VOID (下跌盤)`.
>   Ch.10 wall throughout — never scores, never gates. Freeze intact.
> - **2026-07-02** — Added **Chapter 15** (log date integrity, session 21): root-caused the
>   backup-recovery date-cascade — bookkeeping rows stamped by *wall-clock* date meant an
>   after-midnight self-heal logged the prior session under the next day's date, and the
>   date-keyed dedupe then silently **dropped the real next-day rows** (verdict 6/30 lost, signal
>   3131 ADD lost, 6/29 & 7/1 mislabeled, Sat 6/27 dup). Fix: stamp `update_verdict_log` /
>   `update_signal_log` with the **T86 session date** (`_t86_iso`), never wall-clock; one-time
>   CSV repairs reconstructed from per-commit history. Also shipped §14.4's display half: amber
>   per-card 前日價 pill + Summary-tab stale-price banner. Display/bookkeeping only — freeze intact.
> - **2026-06-25** — Added **Chapter 14** (price-snapshot freshness hardening, session 19):
>   root-caused `STOCK_DAY_ALL` lagging a full trading session (Tue prices on a Wed board, reported
>   green — the silent-stale class on the *price* axis that §13.1/§13.3 timestamp checks miss). TAIFEX
>   OI UTF-8 fix (14.1), block-host tooltip base box (14.2), observe-only price-snapshot date logging
>   (14.3), per-holding `price_stale` flag + in-feeder self-check + price-aware 02:43 self-heal gate +
>   `verify_board.py` post-run check (14.4, **extends §13.3 past its timestamp-only blind spot**). Open:
>   the cron/price-source decision (14.5). All display/reliability — no scoring math, freeze intact.
> - **2026-06-18** — Added **Chapter 13** (reliability & legibility, sessions 17–18): stale-board
>   grey overlay (13.1), deepened TWSE snapshot retry 3→5 + exp backoff (13.2), off-`:00` primary +
>   two gated self-heal backup crons (13.3, **supersedes Ch.7 timing**), Market-tab dynamic tooltips
>   (13.4). All display/reliability-only — no scoring math, not observe-boundary-gated.
> - **2026-06-12** — Added **Chapter 12** (decision-quality & legibility upgrades): signal
>   attribution log (12.1, prerequisite for all future tuning), action why-line + distance-to-flip
>   (12.2), data-health strip (12.3), market breadth leg (12.4), Taifex OI display chip (12.5),
>   confluence-degree display (12.6), verdict scoreboard (12.7), recency decay [BOUNDARY-HELD]
>   (12.8). Build-order recap amended. No scoring math changes before 2026-07-28.
> - **2026-06-10** — Added **Chapter 11** (deferred note: per-bucket disposition/處置股 scoring revision;
>   parked until after the P0 radar L3 exclusion + L4 audit). Header reworked to version + dual-date +
>   this changelog. **L4 audited** (§4.1): magnitude confirmed correct; VIX per-component cap added
>   (Option B) to stop VIX dominating the tilt — *apply at the 2026-07-28 observe boundary, not mid-window*.
> - **2026-06-09** — Synced L3/L4/L5 status across the guide: L3 built & running, L4 built-but-unaudited,
>   L5 pipeline-built-but-not-scored; Chapter 7 18:30-run fix marked **DONE**.
> - **2026-06-01** — **v2 structural revision.** Folded in the five 2026-05-31 review decisions
>   (incremental migration over rewrite + keep HTML dashboard; new Radar discovery tab; Radar v1 on
>   clean trend data; 方舟/ARK as Tier-3 manual cross-check; two data-validity fixes — L1-halved and
>   16:30-pre-T86 timing — moved to top of worklist).

### Building the Watch + Radar tabs on top of the existing Inventory setup

**Stack:** GitHub (repo + Actions, scheduled Python) → processed files → GitHub Pages dashboard (`docs/`). Google Sheet stays **read-only** as the source for the curated universe (T1 Inventory + T2 Watchlist) and positions. GOOGLEFINANCE stays on the Inventory tab for live P&L.

> **What changed in this revision (read this first).** Five decisions from the 2026-05-31 review are now folded in:
> 1. **Architecture is an incremental migration, not a rewrite, and the HTML dashboard stays.** We keep the existing `feeder.py` → `docs/data.json` → `index.html` flow as the human-facing surface (it beats writing to a Sheet "Watch" tab), and migrate the *pipeline* toward the layered `/raw → /processed → output` structure as new layers are added. See Chapter 0.
> 2. **New Radar tab = opportunity discovery** (names *not* in T1/T2, surfaced from whole-market chip data we already pull and currently discard). See Chapter 8.
> 3. **Radar v1 ships on clean data.** Gate on the 投信 buy-*trend* (Tier-1, daily); defer the absolute "投信持股 < 5%" level (no clean Tier-1 source). See Chapter 8.3.
> 4. **方舟運算 (ARK) is a Tier-3 manual cross-check**, never a rule. Data entered by screenshot; read-rules live in `config/ark_crosscheck.md`, referenced from the tab. See Chapter 9.
> 5. **Two live data-validity fixes** move to the top of the worklist: the L1-is-halved problem and the 16:30-run-predates-T86 timing problem. See Chapter 1.7 and Chapter 7.

-----

## How to use this document

This is the build playbook. It follows the **same chapter order as the research report** (the five layers), then adds the Radar and ARK chapters. The Research Report stays the evidence base — this guide is the operational "how." Do the chapters **in order**; Chapters 1 and 2 give ~80% of the useful signal.

Three rules that override everything else:

1. **Confluence at the action layer, never the score layer.** The composite score can read anything; a GO/SELL only fires when ≥ 2 independent layers agree. (Single-factor chip signals had a documented sub-30% short-term hit rate.)
2. **Source tiering is law.** Tier 1 = TWSE / TPEx / MOPS (the *only* place a rule or threshold may originate). Tier 2 = regulated institutions (KGI, Yuanta, SinoPac/永豐, Fubon, Cathay, CTBC) for interpretation/calendars. Tier 3 = aggregators **and the 方舟 app** for display/cross-check only. Community (Dcard, PTT) = sentiment-read only. Every data point below is tagged.
3. **Idempotent runs.** GitHub Actions is stateless. Every run pulls fresh, writes a dated raw file, reprocesses, and overwrites the output. Nothing persists between runs except what is committed to the repo. (This is also *why* the architecture must migrate toward committed `/raw` + `/processed` files once layers run at different times — see 0.1b.)

-----

## Chapter 0 — Architecture & Repo Layout

### 0.1 The file-splitting principle (unchanged)

A **monolithic index file** (one file holding raw data + mappings + feeder logic) is fragile — one corruption kills everything. But the fix is **not** many loose files glued by a hand-maintained index (that just moves the risk to the remapping step). The fix is **isolation by folder + stable naming, no central index.** Files are found by predictable path. Corruption in one layer cannot touch another. Adding a source = dropping a file in a known folder.

### 0.1b As-built vs as-designed — the honest reality and the migration plan

**As-built today, the system *is* the monolith 0.1 warns against:** a single `feeder.py` (~1,370 lines) does snapshot fetch, history, technicals, L1/L2 scoring, composite, action, Sheet read, and writes `docs/data.json`, which `index.html` renders. This works and ships value daily for an L1+L2 build.

**Decision: migrate incrementally, do not big-bang rewrite, and keep the dashboard.**

- The **HTML dashboard is the human surface and stays.** It is better than the guide's original "write a Sheet Watch tab" idea.
- The **Google Sheet stays a read-only source** (T1/T2 + positions). Python never writes to it. This satisfies the GOOGLEFINANCE boundary *more* cleanly than a `push_to_sheet.py` would.
- The **pipeline migrates toward `/raw → /processed → output`** as layers are added — not as a rewrite for its own sake.
- **The forcing function is L4.** Chapter 7's schedule runs L4 (US overnight) at ~06:00 and L1/L2 at ~18:30. Two runs at different times must share state, and stateless CI can only do that through **committed intermediate files** — which *is* the `/raw` + `/processed` structure. So the architecture isn't optional polish; it's required the moment L4 lands. Build L4 (and Radar's persistence) as separate scripts writing committed files, and carve `score.py` out of `feeder.py` to read `/processed/` — that one extraction is the seam that matters most.

### 0.2 Repo structure — current, target, and migration

```
CURRENT (as-built)
/twse-dashboard
├── feeder.py                 # monolith: fetch + score + write
├── /docs
│   ├── index.html            # the dashboard (human surface) — KEEP
│   ├── data.json             # the ONLY file the dashboard reads
│   ├── tickers.json
│   └── analysis.json
└── /.github/workflows/...

TARGET (migrate toward, as layers are added)
/twse-dashboard
├── /raw                      # untouched official pulls, one file per source per day
│   ├── t86_all_YYYYMMDD.csv      # WHOLE-MARKET T86 — persist it (feeds Radar)
│   ├── margin_YYYYMMDD.csv
│   ├── price_YYYYMMDD.csv
│   ├── us_overnight_YYYYMMDD.json
│   └── monthly_revenue_YYYYMM.csv
├── /processed                # clean per-LAYER files (the isolation boundary)
│   ├── layer1_chip.csv
│   ├── layer2_technical.csv
│   ├── layer3_fundamental.csv
│   ├── layer4_regime.csv
│   ├── layer5_news.csv
│   ├── radar_candidates.csv      # discovery shortlist (Chapter 8)
│   └── composite_scores.csv
├── /config
│   ├── weights.json
│   ├── thresholds.json
│   ├── broker_behavior.json      # 隔日沖 detection params (behavioral, NOT a name list)
│   └── ark_crosscheck.md         # 方舟 Tier-3 read-rules (Chapter 9)
├── /src
│   ├── fetch_layer1.py ... fetch_layer5.py
│   ├── fetch_radar.py            # whole-market chip screen
│   ├── score.py                  # reads processed/, writes data.json
│   └── (no push_to_sheet — dashboard renders data.json directly)
├── /docs                     # the dashboard, unchanged
└── /.github/workflows/daily.yml
```

**Config-as-Sheet note:** the original guide called for `config/universe.csv`. We deliberately replace that with "read universe + positions live from the Google Sheet at run start." That is a valid implementation of the config layer and keeps the live inventory integration. The only thing that must never happen is Python *writing* the curated lists back to the Sheet.

### 0.3 The GOOGLEFINANCE boundary

GOOGLEFINANCE stays **only** on the Sheet's Inventory tab for live price/P&L (your view). Python is **read-only** on the Sheet and owns everything GOOGLEFINANCE cannot do (T86, concentration, broker branches, scoring, discovery). The dashboard's Portfolio P&L is a separate, computed, read-only view. They never overlap; Python never writes a cell.

### 0.4 Review checkpoints

|Trigger|What to review|Cadence|
|---|---|---|
|Pipeline health (API endpoint changes, broker drift, dead sources)|`/src` fetchers + `broker_behavior.json`|**Monthly**|
|Thresholds (regime-sensitive)|`thresholds.json`|**Quarterly**, ≥ 60 closed trades|
|Layer weights (structural)|`weights.json`|**6-month minimum**, ≥ 60 closed trades/bucket|
|Watchlist GO hit-rate < 45% (rolling 30 trades)|Full L1 audit|**Immediate**|
|Major regime shift (export controls, surprise CBC, TSMC moves index > 3%, TWSE format change)|Whole framework|**Immediate**|

Rule of thumb: **tune thresholds, not weights.**

-----

## Chapter 1 — Chip / Flow Layer (L1, weight 35%) — BUILD FIRST

Highest-edge layer. Already largely built; **fix 1.7 before trusting the observe-only data.**

### 1.1 Review what you already have

- [x] Per-ticker T86 (foreign/trust/dealer) wired, column fix shipped (trust = col 13, not col 7).
- [x] FLOAT normalisation fixed (`FLOAT_K`, thousands of shares).
- [ ] Confirm none of your chip columns are hand-entered.

### 1.2 Data points, sources, endpoints

|Data point|Tier|Source / endpoint|Notes|
|---|---|---|---|
|T86 個股三大法人買賣超|1|`twse.com.tw/.../t86.html` + OpenAPI; `T86?...&selectType=ALL`|~18:00 daily. **外資自營商 already inside 自營商 — don't double count.** ALL pull returns whole market in one call — keep it (feeds Radar).|
|TPEx (上櫃) equivalent|1|`tpex.org.tw/openapi/`|Mirror set; verify field names against a live response.|
|籌碼集中度 inputs (個股券商買賣明細)|1|`bsr.twse.com.tw/bshtm/`|Per-stock per-day; compute concentration yourself. **Still stub.**|
|融資融券|1|`twse.com.tw/.../MI_MARGN.html`|融資餘額, 融券餘額, 券資比. **Still stub.**|
|借券賣出餘額|1|`twt92u.html` / `twt93u.html`|Real short interest.|
|外資持股比率|1|`mi-qfiis.html`|20-day trend > single day. (No clean 投信 equivalent — see 8.3.)|
|董監持股 / 設質|1|MOPS `t56sb01_q1`|設質比 > 30% = red flag.|
|Cross-check / display|3|Goodinfo, HiStock, Wantgoo, **方舟 app**|Display only — never the rule source.|

### 1.3 Interpretation rules → L1 sub-score (unchanged)

Compute on rolling 5-day persistence. 投信 highest signal; 外資 large-caps; 自營商 noisiest (warrant hedging, de-weight). Cleanest: 投信買 + 主力分點買 + 外資 neutral. 季底作帳 caution (discount swing-long on 投信持股 > 12% in last week of Mar/Jun/Sep/Dec — *not yet implemented, needs holding data*).

**L1 sub-formula:**
```
T86_score = 0.50 * sign(5d_投信_net) * min(|5d_投信_net|/float, 0.02)/0.02
          + 0.30 * sign(5d_外資_net) * min(|5d_外資_net|/float, 0.005)/0.005
          + 0.20 * sign(5d_自營商_net) * min(|5d_自營商_net|/float, 0.01)/0.01   # clip [-1,+1]

L1 = 0.50*T86_score + 0.20*concentration_score + 0.20*broker_score + 0.10*margin_score
```
> **Minor fix:** code currently uses *today's* dealer net for the 自營商 term; spec is *5-day*. Align to 5d.

### 1.4 籌碼集中度 (compute, don't fetch) — still stub

```
Concentration_N = (Σ Top-15 buyer net-buys − Σ Top-15 seller net-sells) / Σ N-day total volume × 100%
```
Thresholds: 1d > 20%, 3d > 10%, 5d > 6%, 60d > 5%, 120d > 3%. **1-day > 20% alone had sub-30% short-term hit rate — never fires alone.**

### 1.5 隔日沖 detection — behavioral, not a named list

```
flag_next_day_dump = (top1_branch_buy > 20% of daily volume)
                     AND (top1_branch_buy > 2 × top2_branch_buy)
                     AND (same branch flips to net seller within 1-3 sessions)
```
4% open-gap rule applies if flagged and held. **Still stub.**

### 1.6 Validation gate

- [x] `layer1` (T86 portion) populates daily without manual touch.
- [ ] Spot-check 3 tickers against Goodinfo.
- [ ] 隔日沖 flag fires sensibly (after broker_score wired).

### 1.7 ✅ DONE — L1 internal rescale (was: L1 structurally halved)

> **Status: DONE — Option (A) shipped in `score.py`.** L1 is now rescaled internally by the
> filled sub-weight fraction (mirroring `compute_composite`'s missing-layer rescale), so a
> 投信-only signal reaches the GO-relevant range and today's observe-only L1 is comparable to
> the finished system. The original problem statement is kept below for context.

Currently `L1 = 0.50 * T86_score`, with concentration/broker/margin **hard-zeroed** (not rescaled). Two consequences:

1. **L1 caps near ±0.5 and a 投信-only signal yields L1 ≈ 0.25** — *below* the GO confluence threshold (L1 ≥ 0.4). Almost no GO can fire on the L1 side during the stubbed period.
2. **The observe-only baseline you are collecting now is on a half-strength L1.** When concentration/broker/margin land, L1 roughly doubles, and the 60-day stats won't transfer.

**Fix (pick one, do it before the clock matters):**
- **(A) ✅ Chosen & shipped — rescale L1 internally** by the filled-sub-weight fraction, exactly as `compute_composite` already rescales for missing *layers*. This makes today's L1 comparable to the finished system, so the observe-only data stays valid.
- **(B) Otherwise — restart the 60-day observe-only clock** when L1's sub-components are complete, and label all data before that as "T86-only proxy."

This is the single most important correction in this revision because it affects data being collected *right now*.

-----

## Chapter 2 — Technical / Price Layer (L2, weight 30%) — BUILD SECOND

Confirmation layer. **Done** (KD, MACD, BB, golden cross, MA-stale detection all shipped). L2 sub-weights in code: MA 30%, volume 20%, RSI 15%, KD 15%, MACD 15%, golden-cross +5% bonus.

- Indicator rules and GREEN-light confluence (≥ 3 required) unchanged from prior guide.
- **Note:** Bollinger Bands are computed but not scored (display-only). Optional refinement: add a BB squeeze→breakout contribution later.

-----

## Chapter 3 — Fundamental Anchor (L3, weight 10%) — EXCLUSION FILTER ONLY

**Built & running — daily 08:30 TPE (Mon–Fri)** via `l3_fundamentals.yml` → `feeder_l3.py`, writing `docs/raw/l3_fundamentals_latest.json` (+ dated archive) behind a last-known-good guard (never overwrites `latest` on a zero-flag/empty fetch — writes a dated `stale:true` stub instead). Auto-EXCLUDE: 月營收年增率 < −10% for 2+ months; EPS negative latest quarter; 負債比 > 70%; 設質比 > 30%; on 注意股/處置股 list. For inventory, L3 ≤ −0.6 alone is a valid SELL contributor. Sources: MOPS `t05st10_ifrs`, quarterly reports, `mopsfin.twse.com.tw`. (Monthly revenue lands ~10th, quarterly on report dates; the daily weekday run surfaces new disclosures as they post.)

-----

## Chapter 4 — US / Global Regime Layer (L4, weight 15%) — MARKET-WIDE TILT

One regime number applied uniformly. **Not started — and it forces the architecture split (0.1b).** Sources: Yahoo TW `^SOX`, `TSM`; Anue; MacroMicro premium. Tilt table and regime veto (tilt ≤ −5 suspends new GO) unchanged. Run ~06:00 TPE after US close, writing a **committed** `/raw/us_overnight_*.json` the 18:30 run reads.

### 4.1 L4 audit result (2026-06-10) — magnitude confirmed, VIX capped

L4 was audited live against the 2026-06-09 run. The tilt math is **correct**: it reproduces to the
byte (`feeder_us.py` `compute_tilt`), the producer/reader/veto/label bands all match this chapter,
and the file is **fresh** (the 21:44 run consumed an L4 file built that morning from the prior US
session). The handoff's "L4 un-audited" item is therefore **resolved**.

**One design issue found and fixed (Option B — VIX per-component cap).** The components are
`^SOX ×2.0`, `TSM ×2.0`, `^GSPC ×1.0`, `^VIX ×0.3 (inverted)`, summed as weighted % moves, scaled to
±10. VIX has the smallest *weight* but VIX daily % moves are structurally 4–5× larger than index
moves, so on 2026-06-08 (VIX −12%) it contributed **~46% of the tilt** — behaving like a co-driver,
not the garnish the 0.3 weight implies. Intent for L4 is **"US-tech-overnight effect on TW"** (SOX/TSM
dominant), so VIX is now capped at a max absolute raw contribution of **±2.5** (≈ ±0.94 tilt points).
On normal days (≤ ±8% VIX) the cap doesn't bite; on spikes it prevents VIX from single-handedly moving
the tilt or triggering a false veto. Effect on the 6/08 example: tilt 7.82 → 7.40 (still Strong
Bullish, driven by SOX/TSM). The clip cap (`sum_of_weights × 5`) is unchanged, so the scale is stable.

> **Timing discipline:** this changes the L4 magnitude on spike-VIX days, which feeds the composite.
> Apply at the **next 60-day observe boundary (2026-07-28)**, not mid-window, so the baseline stays
> comparable — same rule as the §1.7 L1 rescale. On normal days it's a no-op, so the cost of waiting
> is near zero.

> **Future — Option C (deferred):** the cap is a blunt fix. The statistically cleaner approach is to
> *normalise VIX to its own scale* (e.g. VIX level vs its recent average, rescaled to index-move
> units) rather than feeding raw % change. More correct, more to maintain — revisit only if VIX
> behaviour proves important after the first hit-rate review. Until then, the ±2.5 cap stands.

-----

## Chapter 5 — News / Event Layer (L5, weight 10%) — BIAS-AND-VETO OVERLAY

Noisiest. **Not started.** Scheduled (calendar: 月營收, earnings, 除權息, 股東會, FOMC, CBC, MSCI review, TSMC 法說) → reduce size within 2 days. Unscheduled (重大訊息, geopolitics) → volatility veto, −10..−20 pts, bar entries 1–3 days. MVP = keyword sentinel on MOPS 重大訊息.

-----

## Chapter 6 — Synthesis, Scoring & the Watch Tab

### 6.1 Composite (unchanged)
```
Composite = 35*L1 + 30*L2 + 10*L3 + 15*L4 + 10*L5      # each L ∈ [-1,+1] → range -100..+100
```
`compute_composite` rescales by filled-weight fraction for missing layers — keep. **Pair this with the L1 internal rescale from 1.7**, or the composite will keep leaning on L2 while L1 is suppressed.

### 6.2 Action table + confluence gate (unchanged)

|Composite|Watchlist|Inventory|Radar (under-radar)|
|---|---|---|---|
|≥ +40 + confluence|GO full|HOLD/ADD|GO small|
|+20..+40|GO half if confluence|HOLD|Monitor|
|−20..+20|NO-GO|HOLD|NO-GO|
|−20..−40|NO-GO|TRIM 50%|Exclude|
|≤ −40|NO-GO|SELL|Exclude|

- **GO** requires composite ≥ +40 AND L1 ≥ +0.4 AND L2 ≥ +0.4.
- **GO-HALF** requires composite ≥ +20 AND L1 ≥ +0.4 AND L2 ≥ +0.4.
- **SELL** requires ≥ 2 of {L1,L2,L3} ≤ −0.4, or L3 ≤ −0.6 alone, or unscheduled major-negative L5.
- Single-layer signals never trigger action.

### 6.3 Bucket weight overrides (`weights.json`)
```json
{
  "inventory":   {"L1":30,"L2":25,"L3":20,"L4":10,"L5":15},
  "watchlist":   {"L1":35,"L2":35,"L3":8, "L4":15,"L5":7},
  "under_radar": {"L1":45,"L2":25,"L3":15,"L4":10,"L5":5}
}
```

### 6.4 The Watch tab
Read-only columns: `Ticker | Bucket | Composite | L1..L5 | Action | Confluence? | Flags | UpdatedAt`. Conditional-format Action.

-----

## Chapter 7 — GitHub Actions schedule (`daily.yml`)

⚠ **FIX: the run must be ≥ 18:30 TPE.** T86 publishes ~18:00; a 16:30 run fetches *today's* T86 as empty, silently walks back, and labels **yesterday's** flows as "今" (today). Either move the run to ≥ 18:30 or relabel the columns. Confirm in the Actions log whether `today_str` returns rows.

|Step|When (TPE, UTC+8)|Script|
|---|---|---|
|Pull US overnight (L4)|~06:00|`fetch_layer4.py` → commit `/raw/us_overnight_*.json`|
|Pull T86/margin/holding (L1) + price (L2) + **whole-market T86 for Radar**|~18:30|`fetch_layer1.py`, `fetch_layer2.py`, `fetch_radar.py`|
|Pull news sentinel (L5)|~18:30|`fetch_layer5.py`|
|Pull revenue (L3)|monthly, after the 10th|`fetch_layer3.py`|
|Score + write data.json|~19:00|`score.py`|

Rate guard: ~1 req/sec, cache aggressively. **Whole-market T86 (`selectType=ALL`) is one call/day — cheap; only history fetches are expensive.** Store Google service-account creds as a GitHub **Secret**.

> **Update (2026-06-18, Ch.13):** the single ~19:00 `:00` schedule above is **superseded** — the
> primary now runs **19:13 TPE** (off `:00` to dodge top-of-hour contention) plus two gated self-heal
> backup crons (23:37 / 02:43 TPE). See §13.3.

-----

## Chapter 8 — Radar / Discovery Tab (the opportunity bucket) — NEW

Radar surfaces **opportunities you have not listed in T1/T2** — low-coverage mid-caps where institutions have started silent accumulation. This is the report's "real edge." Radar is **opportunity-only**; the caution/trim side (升溫) lives on the Inventory tab, not here.

### 8.1 Pipeline (read-only on the Sheet end-to-end)
```
whole-market T86 (already pulled via selectType=ALL — STOP DISCARDING IT)
   → persist to /raw/t86_all_YYYYMMDD.csv
   → exclude T1 + T2 (set difference)
   → apply coverage filter (8.3)
   → rank survivors by L1 accumulation (under_radar weights)
   → write shortlist to /processed/radar_candidates.csv → docs/data.json
   → render in new "Radar 雷達" dashboard tab
```
**Promotion is manual.** If you like a radar name, *you* add it to T2 in the Sheet. Python never writes the curated lists.

> **Code wiring (currently missing):** today `main()` sets `bucket = "inventory" if tier=="T1" else "watchlist"`, and `compute_action` only distinguishes inventory (T1) vs watchlist. Radar candidates must be tagged on a distinct tier (e.g. `T3`) so `bucket="under_radar"` and the `weights.json` override apply, and `compute_action` needs an `under_radar` branch. Without both, radar names get watchlist actions (GO **full**) instead of the under-radar column (GO **small**).

### 8.2 Why this is cheap
The T86 ALL endpoint returns the entire market in **one call per day**; five days is five calls. You are already pulling and discarding it. The expensive part (12-month OHLCV history for full L2) is spent **only on survivors** — radar is L1-dominant by design, so the screen needs no per-ticker history.

### 8.3 Coverage filter — v1 (option 3) and what's deferred

**There are two different 投信 numbers:** *flow* ("did trusts buy today?", clean daily T86) and *level* ("what % do trusts own?", **no clean Tier-1 source** — TWSE publishes this for foreigners via `mi-qfiis`, not for 投信). The report wants the level (< 5% = early). We can't source it cleanly, and Tier-3 aggregators can't supply a *threshold*.

**v1 gates (all clean Tier-1, ship now):**
- Not in T1/T2.
- 投信 buy-**trend**: a *newly-started* net-buy streak (began recently), not long-running. A fresh streak on a still-quiet stock is the behavioral proxy for "low holding, rising" — captures "early" without the level number.
- Daily volume in band: **1,000–10,000 張**.
- Market cap **50–500 億** *(needs a shares-outstanding source; `FLOAT_K` covers only ~30 names today — extend or defer the cap band)*.
- No 隔日沖 branch in top buyers (behavioral detector, 1.5).

**Deferred:** absolute "投信持股 < 5% rising over 20d" — revisit only if a clean Tier-1 source appears, or accept a cumulated-T86 proxy clearly labelled approximate. **Do not let this hold up shipping radar v1** — the accumulation trend carries the edge.

### 8.4 ARK cross-check on radar
When a radar name surfaces, the 方舟 **價值** tag is the manual Tier-3 sanity check ("fundamentally sound / not a value trap"). See Chapter 9. Never a gate.

-----

## Chapter 9 — 方舟運算 (ARK) — Tier-3 Manual Cross-Check — NEW

The 方舟運算 app (developer Galaxy Digital Co.; influencer-led consumer product, popular but **not** an institutional source) is a **Tier-3 cross-check only**. It cannot be ingested (closed app, no API), so:

- **Data entry is manual** — you screenshot it. No automation.
- **Read-rules live in `config/ark_crosscheck.md`** and are referenced from the relevant dashboard tab as help text. As you learn the app, you refine that one file; nothing else changes.
- **Hard wall:** ARK never feeds any score or the confluence gate. It guides *your* eyes only.

**Tag mapping (which of our surfaces each ARK signal cross-checks):**

|ARK signal|Meaning|Our analogue|Cross-checks which tab|
|---|---|---|---|
|價值 (value zone)|undervalued + good fundamentals (long buy)|L3 fundamental anchor|**Radar / opportunity**|
|升溫 (heating zone)|overextended (trim/sell)|L2 overbought (RSI/BIAS/position)|**Inventory / trim** — *not* Radar|
|位階 漏斗 (level funnel)|how high-in-range the price is|L2 position-in-range|both, as context|
|水位 (持股配置建議 %)|portfolio cash-vs-equity level|conceptually L4, expressed as sizing|**Inventory / portfolio sizing**|
|建議調節股數/金額|per-ticker offload suggestion|(the report deliberately omits position sizing)|**Inventory** — human sizing aid|

**Note:** 水位 / 建議調節 fill the position-sizing gap the report explicitly left open ("decision aid, not a strategy"). Use ARK (or your own analogue of it) as the *sizing* companion to our *signal* engine — but keep the two questions separate: our system says GO/TRIM + confluence; ARK says how much. A portfolio-level water level never overrides a per-ticker signal, or vice versa.

-----

## Chapter 10 — Summary Tab (今日) — Dashboard Surface — NEW

The dashboard now opens on a **Summary tab (今日)** — a single pre-market glance that synthesises the existing layers. It is a **display surface only**: it reads `data.json` + the L4/L3 raw files and re-presents them. It computes **no new scores**, writes **nothing**, and never touches the composite or the confluence gate.

**Tab order:** 今日 → Portfolio → Watch → Market → 雷達 → Take → 新聞

### 10.1 Market Pulse (compact)

Mirrors the Market tab without a tab switch.

|Element|Source|Shows|
|---|---|---|
|TAIEX row|`market.taiex*`|level + day change + %|
|Inst flow 2×2|`market.{foreign,trust,dealer,three_inst_total}_net_m` + `_prev`|today M NT$, delta arrow, **% change vs prev day**|
|L4 regime strip|`us_overnight_latest.json`|tilt + label + SOX/TSM/GSPC chips|
|Veto banner|`L4_DATA.regime_veto`|red banner at page top on veto days|

**% change rule (Tier-1 derived, display-only):** same-sign days → `(today − prev)/|prev|×100`, shown only at ≥5% (noise filter); a direction flip (e.g. −1,200M → +5,400M) shows **轉多 / 轉空** rather than a meaningless raw %; the 合計 card has no prev and shows no %.

### 10.2 Market Verdict (今日研判) — reading aid, NOT a score

A one-line lean synthesised from four inputs. **This is the one place the Summary tab "decides" anything, and it is deliberately walled off from the scoring engine** — it is a human glance aid, exactly like ARK in Chapter 9.

|Input|Weight|Bullish|Bearish|
|---|---|---|---|
|外資 flow|1|> +30,000M|< −30,000M|
|投信 flow|2|> +3,000M|< −3,000M|
|TAIEX %|1|> +1%|< −1%|
|L4 tilt|1|≥ +4|≤ −4 (veto = −3 pts)|

Output: score ≥ 4 `今日偏多 ✅` · ≥ 2 `今日小多 🟡` · ≤ −4 `今日偏空 ⚠️` · ≤ −2 `今日小空 🔴` · else `今日中性 ⚪`. A detail line lists contributing signals.

> **Hard wall (same discipline as ARK):** the verdict never feeds the composite or the confluence gate. It is a glance-level lean; the per-ticker GO/SELL decision still comes only from L1–L5 + confluence. Thresholds here are display heuristics, **not** Tier-1 rules — they may be tuned freely without touching `thresholds.json`.

### 10.3 Portfolio Watch (持倉警示)

Scans each T1 holding for crossed alert thresholds; colour-coded cards link to the Portfolio tab.

|Alert|Trigger|Icon|
|---|---|---|
|Big price move|`abs(chg_pct) ≥ 2%`|📈 / 📉|
|Heavy foreign selling|`foreign_net < −100,000` shares|🚨|
|Heavy foreign buying|`foreign_net > +100,000` shares|💹|
|Trust selling streak|`trust_streak ≤ −2` sessions|⚠️|
|Chip score negative|`l1_score ≤ −0.35` (fallback when no other alert)|🔴|

Multiple alerts stack on one card; none firing → "持倉無異常訊號". **The 100K-share foreign threshold is a raw-share proxy** pending float data — when `concentration_score` (BSR) lands, tighten to a float-normalised % matching the §1.3 T86 sub-formula.

### 10.4 What was NOT changed

Composite weights, confluence gate, L1–L5 scoring, the Radar fresh-streak gate (§8.3), and the Sheet read path are all untouched. Only the default tab and the Summary content are new. The verdict and watch thresholds are display heuristics living in `index.html`, **not** in `config/thresholds.json` — they are explicitly outside the Tier-1 rule system.

### 10.5 Known limitations

- Verdict thresholds are approximate (typical TWSE daily-flow magnitudes); revisit after the 60-day observe period.
- Foreign-selling alert is raw shares, not float % — sharpens once BSR concentration lands.
- `trust_streak` exists only for T1/T2 (per-ticker history); Radar candidates never appear in Portfolio Watch.
- No sector-level flow breakdown — BFI82U is market-total only; sector context needs a separate scrape (future work).

-----

## Build order recap (revised)

1. **Chapter 1.7 + Chapter 7 fixes FIRST** — DONE (L1 rescale live in score.py; 18:30+ run fixed).
2. **Chapter 8 — Radar v1** — DONE.
3. **Chapter 9 — ARK file** — DONE.
4. **Pipeline reliability** — snapshot retry + red-fail split (session-7 fix), industry-map
   resilience, self-heal cron. Scores mean nothing if the run silently no-ops.
5. **Chapter 12.1–12.3** — attribution log + why-line + data-health. Start the log NOW so the
   2026-07-28 review has per-layer evidence.
6. **Chapter 1 stubs** — broker_score (隔日沖) resume; concentration per bsr_alternatives.md
   (proxy B display-first) since BSR automation is CAPTCHA-walled.
7. **Chapter 12.4–12.7** — breadth, Taifex chip, confluence dots, verdict scoreboard (display).
8. **Chapter 5 — L5** news sentinel into scoring.
9. **2026-07-28 observe boundary — single batched flip:** VIX cap + ENABLE_CONCENTRATION decision
   + 12.8 recency decay + any bsr_alternatives reweight (Option E). One baseline shift, not four.
10. **First hit-rate review** on the 12.1 log: per-layer attribution, near-miss counterfactuals,
    gate tightening per 12.6. **Chapter 11** (處置股 per-bucket) implements after this.

**Source-tier reminder:** Tier 1 decides; Tier 2 interprets; Tier 3 (incl. 方舟) displays/cross-checks; community = sentiment only. No threshold ever originates below Tier 1.

-----

## Chapter 11 — Disposition (處置股) scoring revision — DEFERRED NOTE (added 2026-06-10)

> **Status: parked. Do not implement yet — pick up after the P0 radar L3 exclusion + L4 audit.**
> This note records a decision still owed; the current code's uniform `處置股 = −0.6` hard-exclude
> stays in force until this is implemented.

### The problem with the current treatment
`feeder_l3.py` assigns `l3_score = −0.6` to **all** 處置股 uniformly, and the radar L3 filter
hard-drops everything `≤ −0.6`. This conflates two genuinely different populations:

- **"Bad" 處置股** — thin-float / rumour-driven / 隔日沖-dominated, flagged as a consequence of
  manipulation. Dangerous; the restriction itself dries up liquidity. Correctly excluded.
- **"Good" 處置股** — a fundamentally sound name flagged because price/volume deviated fast off a
  *legitimate* catalyst (earnings gap, M&A disclosure, sector rotation). The exchange mechanism is
  blunt and fires on deviation regardless of cause; the flag expires quickly.

The blunt rule over-excludes the second population.

### Intended per-bucket logic (to implement later)
- **Watchlist (new entry):** keep the hard exclude either way. The 20-minute call auction makes a
  swing entry unworkable while the flag is active, good or bad. No new entries during restriction.
- **Inventory (already holding):** the flag alone is **not** a SELL trigger. L3 = −0.3 (soft warning),
  hold unless L1/L2 also confirm distribution (the existing confluence gate already enforces this —
  inventory SELL needs ≥2 of {L1,L2,L3} ≤ −0.4, so an administrative flag alone can't force it).
- **Radar (discovery):** differentiate. Hard-exclude if the disposition flag co-occurs with a
  revenue-decline flag; otherwise soften to −0.3, keep in radar with a ⚠️ badge, and block the GO
  action but don't hide the name (worth watching for after the flag expires).

### ⚠ Honest caveat on the proposed differentiator
A draft of the radar rule keyed "good vs bad" partly on `trust_net > 0`. **This does no work for
radar:** every radar candidate has already passed the §8.3 fresh-streak gate, so they are *all*
trust-positive by construction. For radar names the differentiator therefore collapses to the
**revenue-decline co-flag** alone. The trust-sign test is only meaningful in buckets that don't
pre-filter on it (i.e. inventory). State this explicitly when implementing so the rule isn't built on
a condition that's always true.

### Why deferred
This is a scoring-metric revision, not a data-validity fix, so it does not affect the observe-only
clock. Implement after P0 (radar L3 exclusion) and the L4 audit. Requires no new data source — it
reorganises existing L3 flags + the radar filter only.

-----

## Chapter 12 — Decision Quality & Legibility Upgrades — NEW (2026-06-12)

Two goals: make the system's hit-rate **measurable per layer** (so the July review can tune on
data, not feel), and make every on-screen action **inspectable in two seconds** by the human who
decides. Nothing in this chapter changes scoring math before the 2026-07-28 observe boundary.
Each section is tagged:

- **[NOW]** — display/logging only, zero effect on scores or the observe baseline. Ship anytime.
- **[BOUNDARY]** — changes score magnitudes. Code it whenever; **commit only at an observe boundary**
  (next: 2026-07-28), same rule as the VIX cap and `ENABLE_CONCENTRATION`.

### 12.1 [NOW] Signal attribution log — *the prerequisite, build first*

**Problem.** The July review can currently answer only "watchlist GO hit X%." It cannot answer
*why* — which layer carried the winners, which carried the losers. Without that, the quarterly
threshold review in §0.4 is guesswork.

**Build.** The 19:00 run appends one row per fired action **and per near-miss** to a committed
log, `processed/signal_log.csv`:

```
date, ticker, bucket, action, composite, L1, L2, L3, L4, L5,
confluence_n,            # count of layers ≥ +0.4 (or ≤ −0.4 for sells)
near_miss,               # 1 if composite ≥ +30 but gate failed; else 0
gate_fail_reason,        # "" | "L1" | "L2" | "L1+L2" — which leg missed
fwd_5d, fwd_10d, fwd_20d # filled by later runs (see below)
```

- **Near-miss capture matters as much as fires:** "would relaxing L2 to +0.35 have helped or hurt"
  is only answerable if the near-misses were logged with their outcomes.
- **Forward-return backfill:** each 19:00 run scans the log for rows aged exactly 5/10/20 trading
  days with an empty slot and fills it from that day's close (close-to-close, vs the close on
  signal date). Stateless-CI-safe: the log is a committed file; backfill is idempotent
  (only fills empties).
- **Tier note:** this is our own Tier-1-derived bookkeeping; no external source.
- **Review queries it must support (July 28):** hit-rate by bucket; hit-rate by L1 band
  (0.4–0.6 vs > 0.6); near-miss counterfactual ("if L2 gate were 0.35"); flag-correlation
  ("did churn-flagged GOs underperform").

**Acceptance:** log exists, grows daily without manual touch, backfill fills a 5-day-old row
correctly on its first eligible run.

### 12.2 [NOW] Action why-line + distance-to-flip — *the legibility core*

**Problem.** `GO · 48.1` forces the human to reverse-engineer five sub-scores. The dashboard's
job is to compress its reasoning into one scannable line.

**Build.** `score.py` emits three short strings per ticker into `data.json`; `index.html` renders
them under the action cell:

- `driver` — the dominant L1 reason, from the largest-|contribution| sub-component.
  Templates: `投信5日 +{x}% float` · `外資5日 {±x}% float` · `融資背離` · `借券升`.
- `confirm` — the dominant L2 reason: `5/20金叉+量` · `MACD>0軸` · `KD低檔轉折` · `突破20MA`.
- `risk` — highest-severity active flag, else `—`: `churn疑似隔日沖` · `處置股` · `季底作帳` ·
  `L4 veto` · `事件{n}日內`.

**Distance-to-flip.** For non-actions near a boundary, one more string `flip`:

- Watchlist NO-GO with composite ≥ +30: whichever is binding —
  `差: 綜合 +{40−composite}` or `差: L1 +{0.4−L1}` / `差: L2 +{0.4−L2}`.
- Inventory holding within 0.15 of a SELL leg: `SELL距: {layer} −{gap}`.
- Else empty. **Display heuristic, lives in score output + HTML, NOT in `thresholds.json`** —
  same wall as the Chapter 10 verdict.

**Acceptance:** every Watch/Radar row shows driver+confirm; every flagged row shows risk; a
synthetic near-miss shows the correct binding gap.

### 12.3 [NOW] Data-health strip (今日 tab)

One row at the top of 今日, one chip per input, age-colored (green = expected-fresh, amber = one
cycle stale, red = older):

```
T86 ✓ 06-12 · 價量 ✓ 06-12 · L3 ✓ 08:30 · L4 ✓ 07:26 · data.json ✓ 19:02
```

Sources: each layer's raw/processed file timestamp + `data.json` `updated`. Red on any chip also
prints one plain-language line (e.g. `快照來源 06-10 後未更新 — 分數反映舊資料`). This is the
permanent answer to the session-7 silent-stale incident: **the human must never need the Actions
tab to know which day they're looking at.**

### 12.4 [NOW display / BOUNDARY score] Market breadth — the internal regime leg

**Problem.** The regime view is external-only (L4 US overnight) and headline flows. TAIEX is
~30% one stock; the index can be green while most of the market breaks down — the highest-risk
day for a fresh GO.

**Build (display now).** From the whole-market snapshot already pulled (zero extra calls),
compute and show on 今日:

- `breadth_20ma` — % of stocks above their own 20MA *(needs per-ticker 20MA over the full market;
  if full-market history is too heavy, v1 fallback: advance% only, label it)*.
- `adv_dec` — advancing vs declining count.
- Divergence badge: TAIEX +>0.5% while `breadth_20ma < 40%` → `⚠ 指數背離 — 大盤強、廣度弱`.

Verdict wiring (display heuristic, Ch.10 wall): breadth < 40% adds −1 to the verdict tally;
> 60% adds +1.

**[BOUNDARY] later, evidence-gated:** promoting breadth into L4 as a scored component happens
only if the 12.1 log shows GO outcomes correlate with breadth. Until then it guides eyes only.

### 12.5 [NOW] Taifex 三大法人 futures OI — forward-positioning chip

**Source (Tier-1):** 期交所 daily 三大法人 futures open-interest stats (free, no CAPTCHA;
verify the exact endpoint/format against a live response before wiring — taifex.com.tw,
區分各期貨契約/三大法人 section; TX + MTX contracts).

**Read.** L1 says what institutions *did* today; foreign net OI says what they're *positioned
for* tomorrow. Display chip on 今日 next to the L4 strip: `外資期淨OI {±n}口 ({5d trend})`, plus
a divergence note when spot and futures disagree (spot net-buy + OI shorting = hedged, discount;
spot net-buy + OI long-building = conviction). Verdict tally: ±1 on a 5-day OI trend
(threshold a display heuristic). **Not an L4 component** until it earns it via the 12.1 log at a
boundary — same gate as breadth.

### 12.6 [NOW] Confluence degree — show agreement, not just sum

A composite +45 from L1=+0.9/L2=+0.2 and one from L1=+0.5/L2=+0.6 are different trades; the sum
hides it. Display two values next to every composite (already computed, just surfaced):

- `agree_n` — layers ≥ +0.4 (the 12.1 `confluence_n`), rendered as dots: `●●○○○`.
- `min(L1,L2)` — the weakest gate leg.

Reading rule (human, not code): prefer a +42 with `agree_n=3` over a +55 carried by one layer.
**[BOUNDARY] later, evidence-gated:** if the log shows agree_n=3+ signals materially outperform,
*consider* tightening the gate to 3 layers — that is the report's own pre-registered benchmark
("if composite-≥+40 hit-rate < 55% → tighten confluence to ≥ 3").

### 12.7 [NOW] Verdict scoreboard — grade the 今日 lean

The Ch.10 verdict claims a daily lean; anything that claims a lean must be falsifiable. Each
19:00 run appends yesterday's verdict + today's TAIEX direction to `processed/verdict_log.csv`
and 今日 shows a small `研判命中率 (60d): {x}%` chip. If after 60 days it tracks ≤ 50%, demote
the verdict visually (smaller, with caveat) — per Ch.10 it never fed scoring anyway, so this
costs nothing and keeps the dashboard honest.

### 12.8 [BOUNDARY] Recency decay on L1 5-day windows

A 投信 streak that ended three days ago should not score like one that printed today. Weight the
5-day nets by recency before summing: `w = [1.0, 0.9, 0.8, 0.7, 0.6]` (d0 → d−4), then the
existing /float normalisation unchanged. Changes L1 magnitudes → **code now if convenient, flag
off, commit/flip only at 2026-07-28**, bundled with the VIX cap + `ENABLE_CONCENTRATION` flips so
the post-boundary baseline shifts once, not three times. Decay weights live in `thresholds.json`
(they are thresholds, not weights, per §0.4's "tune thresholds, not weights").

### 12.9 What Chapter 12 deliberately does NOT do

No changes to: composite weights, the confluence gate, L1–L5 formulas (before the boundary),
the Sheet read path, source tiering. Breadth/Taifex enter as **display + verdict heuristics**
behind the same wall as ARK (Ch.9) and the verdict (Ch.10); promotion into scored layers is
evidence-gated on the 12.1 log. The honest framing stands: none of this makes the system
predictive — it makes it **measurable and inspectable**, which is the realistic ceiling.

### 12.10 Build order within this chapter

1. **12.1 attribution log** — prerequisite for every future tuning decision; the sooner it
   starts, the more the July review can see. *(One `score.py` change + one committed CSV.)*
2. **12.2 why-line + flip** — biggest legibility win per line of code.
3. **12.3 data-health strip** — closes the silent-stale class permanently.
4. **12.7 verdict scoreboard** — trivial once 12.1's append pattern exists.
5. **12.4 breadth (display)** → **12.5 Taifex chip (display)**.
6. **12.6 confluence dots.**
7. **12.8 recency decay** — code last, **commit at the 2026-07-28 boundary**.

-----

## Chapter 13 — Reliability & Legibility Hardening (sessions 17–18) — NEW (2026-06-18)

Two consecutive stale-board days (6/16, 6/17) plus a backlog of un-documented display work prompted
this chapter. Everything here is **reliability or display only**: no scoring math changes, nothing
touches the composite / confluence gate / observe baseline, so none of it is observe-boundary-gated
(unlike the VIX cap or §12.8). This chapter also discharges the §6 "state any divergence" debt for the
session-17/18 changes, which shipped to the repo ahead of their guide entries.

Tags: **[RELIABILITY]** = CI/fetch robustness · **[DISPLAY]** = dashboard surface, Ch.10 wall applies.

### 13.1 [DISPLAY] Stale-board grey overlay (session 17)

**Problem.** A failed or skipped run can leave `data.json` showing a prior trading day with no visible
signal that the numbers are old — the session-7 silent-stale class, on the *display* side.

**Build.** `boardStale()` in `index.html` flags the board stale on **wall-clock TPE time**, not on
`data.json`'s own timestamp (aging a file against its own stamp can never flag the file itself — the
health-strip blind spot). Stale = `data.json.updated` is before 18:30 TPE for the current trading day,
or a full trading day behind. A stale board renders under a grey overlay. The `.supported` class (cards
where `t.confluence === true`) snaps the day-varying tier back to full colour so confluence reads stay
legible through the overlay.

**Acceptance:** on a stale `data.json` the board greys and a confluence card stays full-colour. *(Fired
correctly across the 6/16–6/17 stale days.)*

### 13.2 [RELIABILITY] Deepened TWSE snapshot retry (session 18)

**Root cause it fixes.** 6/17 run #61 hard-failed at `Run feeder`: TWSE `STOCK_DAY_ALL` returned an
empty/non-JSON body (transient night-refresh blip); the old 3-attempt / ~23s retry exhausted and the
feeder correctly exited **red** rather than overwrite `data.json` with nothing (session-7 guard working
as designed).

**Build.** Snapshot retry deepened **3→5 attempts**, backoff `SNAPSHOT_BACKOFF = [30, 60, 120, 240]`s
(~7.5 min of knocking before failing red, vs ~23s). Rides out a multi-minute TWSE outage inside one run.
Hard-fail-red on final exhaustion is unchanged — fail loudly, never silently green.

> **Open follow-up:** the **TPEx** snapshot block (`feeder.py` ~L279) still uses the old 3-try loop. It
> wasn't the failing path, so it was left out of scope — mirror the deep ladder there when convenient.

### 13.3 [RELIABILITY] Off-`:00` primary + gated self-heal backups (session 18) — supersedes Ch.7 timing

**Root cause.** Scheduled 19:00, runs consistently landed 21:57–23:48 TPE (3–5h late) — magnitude well
beyond top-of-hour jitter, most likely **free-tier scheduled-job deprioritization**. Late landings drop
the fetch into TWSE's flaky night-refresh window. There is **no quiet pre-market slot**: pre-market TPE
(00:00–08:00) = 16:00–24:00 UTC = GitHub's US-busy hours. So the real fix is not on-time landing
(unachievable on free tier) but a **gate + deep retry**.

**Build (`daily.yml` + `selfheal_gate.py`):**
- Primary cron `0 11` → **`13 11`** (19:13 TPE) — off `:00` to dodge top-of-hour contention.
- Two **gated backup crons**: **`37 15`** (23:37 TPE, same evening) + **`43 18`** (02:43 TPE next
  morning) — both drift-safe before the 09:00 open.
- **Gate step** keys on `github.event.schedule`: primary cron + manual `workflow_dispatch` always
  proceed; backup crons run feeder **only if `selfheal_gate.py` reports the board stale**, else no-op in
  ~10s without touching `data.json` / `t86_market_prev`. Setup/install/feeder/commit all carry
  `if: steps.gate.outputs.run == 'true'`.
- `selfheal_gate.py` (repo root, stdlib-only) prints `run=true/false`; stale = board behind the latest
  trading day, or a pre-18:30 snapshot for it. Holiday-safe: a false "run" just makes feeder no-op green
  on `No Data`. 8/8 unit tests at build time.

**Acceptance:** primary lands a complete post-18:30 snapshot; on a failed primary a backup cron fires,
the gate reports stale, and the board self-heals before the open. *(First live test: the 6/18 primary.)*

### 13.4 [DISPLAY] Market-tab dynamic tooltips (session 18)

Hover tooltips on the Market tab with **dynamic current-vs-expected reads** — TAIEX, the four 三大法人
cards, the L4 label, and the SOX/TSM/GSPC/VIX chips each interpret their *current* value against the
§10.2 verdict / L4 tilt thresholds (e.g. the 合計 card ties today's net to the 5-day to flag a
"counter-move, not a trend"). Plus a z-index fix (popups `9999`, above sticky nav and cards; the hovered
host lifts via `:has()`). Thresholds here are **display heuristics** — same Ch.10 wall as the verdict;
they never touch composite / confluence / scores.

### 13.5 What Chapter 13 does NOT change

No changes to: composite weights, the confluence gate, L1–L5 formulas, the observe baseline, the Sheet
read path, or source tiering. §13.1/§13.4 sit behind the Ch.10 display wall; §13.2/§13.3 are CI
robustness. The 2026-07-28 batched flip (VIX cap, `ENABLE_CONCENTRATION`, §12.8 recency decay) is
untouched by this chapter.

-----

## Chapter 14 — Price-Snapshot Freshness Hardening (session 19) — NEW (2026-06-25)

The §13.1 grey overlay and §13.3 self-heal gate both define "stale" on the board's **timestamp** (is
`data.json.updated` from the latest trading day, after 18:30?). Session 19 found a class they both miss:
a board that is timestamp-current but whose **prices are a session behind**. Root cause — the per-stock
price source (`STOCK_DAY_ALL`) lags a full trading session: day-D's close is not on the feed at any cron
slot we run on day D (verified live — at 21:53 TPE the feed still served D-1; D's close only appeared the
next morning). So the primary writes **current T86 chips on prior-session prices**, the timestamp looks
fresh, and every existing check passes green. The §13.x `stale` flag is a *corruption/blank* detector (no
history, or >25% scale mismatch); a one-session lag is a ~1% price gap that sails straight through it.

This is the silent-stale class on the **price** axis — §13.1/§13.3 closed only the *timestamp* axis.

### 14.1 [RELIABILITY] TAIFEX OI — UTF-8 decode (`futures_oi` was silently empty)

`fetch_taifex_oi` force-set `r.encoding = "cp950"`. TAIFEX moved `futContractsDate` to **UTF-8** (page
`<meta charset>` = UTF-8; the anchors 臺股期貨/外資 decode only under UTF-8). The Big5 decode mangled
every anchor, so `_parse_taifex_oi` matched nothing and the 今日 OI chip never filled — **not** a UA block
(the prior suspicion). Fix: `cp950` → `utf-8`; validated live (臺股期貨 外資 net OI parsed). Row shapes
unchanged (15-cell header / 13-cell continuation, `nums[10]`). `daily.yml` already stages the OI raw files
conditionally — no workflow change. *(First production fill: the 6/24 21:33 run.)*

### 14.2 [DISPLAY] Tooltip base box → `.tw-b` block hosts (follow-on to §13.4)

§13.4's tooltip base styling lived only on `.tw .tp` (inline hosts). The block-level hosts (`.tw-b`:
institutional cards, regime-comp chips) got only z-index + hover→display, never the base box or
`position:absolute` — so their popups were unstyled in-flow spans the card clipped (`?` cursor, no popup).
Extended three selectors (`.tw .tp` / `::after` / `.tp-t`) to also match `.tw-b .tp`. CSS-only.

### 14.3 [RELIABILITY] Price-snapshot freshness instrument (observe-only)

`feeder.py` reads the session `Date` (ROC compact, e.g. `1150624`) that both `STOCK_DAY_ALL` (TWSE) and
`tpex_mainboard_daily_close_quotes` (TPEx) carry — both verified to expose it — via `_roc_to_western()`,
and logs `freshness observe: t86=… twse_snap=… tpex_snap=… lag_*=…` at the write point, plus a LAG warning
when a snapshot is **strictly older** than the T86 session (strict `<` leaves the legit "T86 fell back to
yesterday" path alone). Observe-only: no gate, board still publishes. Purpose: log the feed roll-time at
every cron slot so §14.5 has data. (Snap dates threaded through `fetch_snapshot`'s return + `main()` unpack.)

### 14.4 [RELIABILITY] Per-holding `price_stale` flag + self-check + price-aware gate + post-run verify

Four layers, all keyed off the §14.3 dates. The board is genuinely **mixed-date** (TPEx publishes day-D's
close by evening; TWSE lags a session), so freshness is **per-holding by exchange**, never board-wide.

- **`price_stale` / `price_session` per row** (`feeder.py`): `price_session = snap_date_dd` (TWSE) /
  `tpex_snap_date_dd` (TPEx) / `None` (興櫃); `price_stale = price_session < t86_session`. Plus
  `market.price_stale_count` (holdings), `market.price_stale_watch_count`, `market.t86_session`. Display
  field — never feeds composite/confluence (Ch.10 wall). Distinct from the §13.x `stale` (blank/no-data) flag.
- **In-feeder self-check** (`_verify_freshness_flags`): independently re-derives every row's `price_stale`
  and the count before the write; **red-exits** on any inconsistency — a board whose freshness flags
  silently lie is worse than a red exit.
- **Price-aware self-heal gate** (`selfheal_gate.py --price-aware` + `daily.yml`): the 02:43 backup now
  reads the prior board's `price_stale_count` and re-runs when the board is timestamp-current but
  price-stale — a free fresh-price recovery if the feed rolled by 02:43, a harmless re-write if not. The
  23:37 backup stays timestamp-only (feed not yet rolled). **Extends §13.3** past its timestamp-only gate.
  No-ops safely when the metric is absent (`.get(...,0)`), so its commit order is unconstrained.
- **Post-run verify** (`verify_board.py`, new repo-root stdlib script; `daily.yml` step before commit,
  gated `run==true`): fails LOUD if `data.json.updated` isn't from this run (no-op-masquerading-as-green)
  or the freshness metric is missing; emits a `::warning::` when `price_stale_count > 0` so a stale board
  shouts on the Actions summary. Independent of the in-feeder self-check.

14/14 unit tests at build (flagging, self-check catch, gate truth table, verify fail-loud). All four files
verified byte-identical live post-commit. *(First live test: the 6/25 19:13 primary + 02:43 backup.)*

> **Status 2026-07-02:** the human-visible half shipped — `index.html` now renders an amber
> `前日價 M/D` pill (`pxStalePill`, from `price_stale`/`price_session`) on affected cards and a
> Summary-tab banner from `market.price_stale_count` / `price_stale_watch_count`. Amber deliberately
> distinct from the grey `.is-stale` board-wide wash (grey = whole board old; amber = board current,
> price axis honestly one session back).

### 14.5 [OPEN] The `STOCK_DAY_ALL` full-session-lag decision (carried "1b")

§14.3/§14.4 make the lag **visible and self-healing-where-possible**; they do not make day-D prices appear
on day D. The structural fix is still owed — one of: (a) a post-roll D+1 morning cron; (b) a faster
same-day TWSE price source (per-stock `STOCK_DAY` last row, or MIS intraday close) for the curated
universe, keeping `STOCK_DAY_ALL` for the broad scan only; or (c) accept aligned T-1 pricing (prices and
T86 both one session back, consistent). The §14.3 logs (feed `Date` at 19:13 / 23:37 / 02:43) are
accumulating the roll-time needed to choose; the 02:43 price-aware gate may partly self-solve (a) if the
roll is pre-dawn. Decide once a few sessions of roll-time logs are in.

### 14.6 What Chapter 14 does NOT change

No composite weights, confluence gate, L1–L5 formulas, observe baseline, or source tiering. §14.1/14.2 are
fixes; §14.3/14.4 are CI/display reliability behind the Ch.10 wall; §14.4's `price_stale` is display-only
and never scored. The 2026-07-28 batched flip (VIX cap, `ENABLE_CONCENTRATION`, §12.8 recency decay) is
untouched.

-----

## Chapter 15 — Log Date Integrity (session 21) — NEW (2026-07-02)

The self-heal architecture (§13.3) worked exactly as designed this week — the primary failed on
6/29 and 7/1 and the backups recovered both boards before the next open, zero board-days lost —
and in doing so exposed a latent bug in the Ch.12 bookkeeping that only fires on the recovery path.

### 15.1 The incident — wall-clock stamping + date-keyed dedupe = silent row loss

`update_verdict_log` (§12.7) and `update_signal_log` (§12.1) stamped rows with
`datetime.now(TZ).date()`. While the primary ran the same evening as the session, wall-clock date
== session date and nothing was visible. When a backup recovers a board **after midnight**, the
prior session's rows get stamped with the *next day's* date — and because both logs dedupe on
`date` (verdict) / `(date, ticker)` (signal), the mislabeled row **occupies the next day's slot**,
so when the real next-day run appends, its row is treated as a duplicate and **silently dropped**.
The cascade is self-perpetuating: every after-midnight recovery steals a slot and destroys a row.

Confirmed damage (reconstructed from per-commit `data.json` / CSV history, atom feed + raw@sha):
verdict row labeled 6/30 was session **6/29**; the real 6/30 verdict (+3 小多, TAIEX +2.50) was
dropped; row labeled 7/2 was session **7/1**; Sat 6/27 carried a duplicate of 6/26. Signal log:
same relabels, plus two dropped real-6/30 rows — including a **fired `3131 T1 ADD`** — recovered
from commit `dde5e591`'s board via `build_signal_log_row` semantics. Five Sat-6/27 rows (the
price-aware backup *re-scoring* session 6/26 with fresher prices) were deleted rather than merged:
the logs record what the system emitted **at decision time**, not later recomputes.

### 15.2 The fix — stamp by trading session, never wall-clock

Both bookkeeping calls in `feeder.py` now pass `_t86_iso` (the T86 session date, already computed
for the Ch.14 freshness flags) with wall-clock as fallback only if T86 parsing failed:

    _t86_iso or datetime.now(TZ).date().isoformat()

This also makes the dedupe *correct* instead of destructive: a backup re-run of the same session
now collides with the session's existing rows (blocked, as intended) instead of the next day's.
One-time repaired `processed/verdict_log.csv` (9 rows) and `processed/signal_log.csv` (64 rows)
committed alongside; no forward-return cells were touched, so §12.1 backfill refills them
idempotently.

### 15.3 House rule (promoted to `config/agent_ops.md`)

**Any persisted row keyed by date must be stamped with the trading-session date taken from the
data itself (`t86_session` / `_t86_iso`), never wall-clock.** Third occurrence of this bug class
(Sat verdict dup, Sat signal dup, the 6/29→7/2 cascade); it has earned a standing rule.

### 15.4 What Chapter 15 does NOT change

No composite weights, confluence gate, L1–L5 formulas, observe baseline, or source tiering.
Bookkeeping/date semantics only; the verdict/signal logs remain display-and-review-only behind the
Ch.10 wall. The 2026-07-28 batched flip is untouched. Note for the 7/28 review: hit-rate
`graded_n` resets meaningfully only from the repaired log forward — treat pre-repair pairings
with suspicion.

-----

## Chapter 16 — Intraday Cross-Reference Tab (session 22) — NEW (2026-07-03)

A new 盤中 dashboard tab showing **live intraday pressure for the board universe (T1 + T2),
cross-referenced against last night's frozen board**. Same family as the Ch.10 verdict and the
Ch.9 ARK rules: **display-only, never scores, never gates, walled off from the composite.**
Everything here is fully outside the 2026-07-28 freeze.

### 16.1 Data path — MIS via a separate `data` branch

```
docs/data.json (last night's board, main)          ← universe source, always tracks the board
  → feeder_intraday.py (NEW leaf module, repo root; touches nothing else)
  → ONE batched MIS GET  https://mis.twse.com.tw/stock/api/getStockInfo.jsp
      ex_ch = tse_XXXX.tw|otc_XXXX.tw…  (prefix keyed off each row's `exchange` field)
  → intraday.json  → pushed to the `data` branch (intraday.yml, */5 cron 09:00–13:5x TPE)
  → 盤中 tab reads raw.githubusercontent.com/…/data/intraday.json (60 s poll while visible)
```

**Why a separate branch:** GitHub Pages rebuilds the site on every push to the served branch and
throttles ~10 builds/hr; 12 pushes/hr of intraday data would starve the real board's builds. The
`data` branch is never served — the tab reads it raw. The board's daily.yml cadence is untouched.

**Session-20 probe facts baked into the module:** bare GET, no session/headers; `rtcode 0000` =
success; both TSE and OTC resolve in one call; MIS limit ≈ 3 req / 5 s so the whole universe goes
in a single request. Fields: `z` last, `y` prev close, `v` cumulative 張, `a/f` ask price/size ×5,
`b/g` bid price/size ×5 (underscore-delimited).

### 16.2 Parse guards & semantics (all mandatory, all unit-tested offline)

- `z` can be `-` (no trade yet / limit) → `last = None`, no chg%. Book levels can be `-`/empty
  (seen live on otc_6488's top ask) → dropped cell-wise; **never assume 5 clean levels**.
- `book_imbalance = (Σbid − Σask)/(Σbid + Σask)` sizes only, None when the book is empty.
- **量比 unit fix:** the board's `vol_today` is in **shares**; MIS `v` is in **張** — the module
  divides by 1,000. (`rel_vol = cum_v / (vol_today/1000)`, v1 label "vs 昨日全日量"; the
  same-time-yesterday refinement is deferred, not blocking.)
- **Session stamping follows the Ch.15 house rule:** the `session` field comes from the data
  itself (MIS per-item trade date `d`), wall-clock only as fallback.
- **Holiday guard (beyond the original spec):** weekday run + MIS session ≠ today ⇒ market
  holiday ⇒ exit green with a log, no write, no false red. Genuine trading-day failures during
  market hours still **fail loud** (exit 1). Outside 09:00–13:30 TPE / weekends: no-op green.

### 16.3 The tab (`panel-intraday`)

Per row (sorted by |chg%|): live price + chg%, 量比, 掛單 imbalance chip (colored beyond ±15%),
距MA20 (live price vs the frozen board's ma20), the board's action + `flip` string, and a
`✓ 順昨夜籌碼 / ✗ 逆昨夜籌碼` note — rendered only when the move ≥ 0.3% **and** |L1| ≥ 0.1, so
no noise verdicts. Poll runs only while the tab is visible (starts on tab enter, stops on leave).

**Live-regime gate (display logic only):** 0050 (on the board, rides the same MIS call) red
intraday → banner + every GO/ADD action struck through with `VOID (下跌盤)`. Framing is always
"consider reviewing", never an instruction to execute.

**States:** closed market → "已收盤" with the last session's final snapshot; `updated` > 10 min
old during market hours → amber 資料延遲 (cron queue-drift is normal; > 15 min persistent →
check Actions); `data` branch empty → plain-language notice, no error.

### 16.4 Workflow notes (`intraday.yml`) — divergences from the session-21 handoff sketch

1. **`/tmp` carry across the branch switch from day one:** `intraday.json` is untracked on the
   main checkout but tracked on `data` from run 2 onward — a plain `git checkout data` then
   refuses to overwrite it. Verified in a simulated repo; the sketch's anticipated fragility is
   real on every run after the first.
2. **`git checkout -B data FETCH_HEAD`** instead of `git checkout data` — the Actions checkout
   is shallow/single-branch, so the plain form can't see the remote ref reliably.
3. **Commit-if-changed** replaces `git commit … || echo "no change"` — that pattern would also
   swallow real push failures (fail-loud rule).
4. **`timeout-minutes: 8`** — with 5-min ticks and `cancel-in-progress: false`, one hung MIS
   call would otherwise stack the queue.
5. Own concurrency group (`twse-intraday`), deliberately **not** the shared
   `twse-dashboard-write` group: this workflow never pushes to main, so it cannot race
   daily.yml / us_overnight / l3.

### 16.5 What Chapter 16 does NOT change

No composite weights, confluence gate, L1–L5 formulas, observe baseline, or source tiering.
`feeder.py` / `score.py` / `daily.yml` are untouched; the module is a leaf. The 盤中 tab sits
behind the Ch.10 display wall — nothing on it feeds a score, and the VOID tag is a reading aid,
not an action. The 2026-07-28 batched flip is untouched. (Forward note: MIS same-day close is
also the candidate **§14.5** price source for the board itself — that decision remains owed at
the boundary and is *not* made by this chapter.)

## Chapter 17 — Run Ledger, Snapshot Persistence & Failure Anatomy (sessions 26–28) — NEW (2026-07-14)

Reliability, audit-trail, and diagnosis work. **Nothing here touches scoring math; the
2026-07-28 freeze is intact throughout.**

### 17.1 Intraday-tab tooltips (session 26, commit `8d4a7aa`)

Native HTML `title` attributes (hover-only, zero new CSS/JS) on five 盤中 cell types: 量比,
掛單 imbalance, 距MA20, the ✓/✗ 籌碼 chips, and the action/VOID tag. Each tooltip is worded
dynamically from the displayed values. Six anchored splices in `docs/index.html`; mobile
unaffected (no hover), which Fisher confirmed acceptable.

### 17.2 Typhoon closure behavior — verified clean (2026-07-10, 巴威/Bavi)

An ad-hoc full-day market closure is a **clean no-session day** for the pipeline: T86 never
publishes, the primary keeps the board stamped on the last real session (2026-07-09),
`price_stale` stays false (the last close is still the latest valid close), and both backups
stand down. **No code change needed for ad-hoc closures.** Side effect worth knowing: the
closure deferred a 23-name ex-div batch to the next session — large mechanical negative
`chg_pct` marks, not signal (and mostly masked on the board by the §14.5 structural price lag
until TWSE prices roll forward).

### 17.3 Run ledger + snapshot persistence (session 27, Task C item 1)

**Problem class (third occurrence):** files written by feeder but absent from `daily.yml`'s
guarded git-add loop are silently discarded every run (previously verdict_log, taifex OI; now
`docs/raw/snapshot_*.json` — meaning **no snapshot archive existed** going into the 7/28
hit-rate review). House rule: whenever feeder persists a NEW file, grep `daily.yml`'s git-add
in the same review.

Shipped:
- `daily.yml` gate step emits `slot=` per cron branch (`primary` / `backupA` / `backupB`, with
  manual runs split off as `dispatch` via `github.event_name`); the feeder step receives it as
  the `RUN_SLOT` env var. Git-add loop gains `processed/run_log.csv` and
  `docs/raw/snapshot_*.json`.
- `feeder.py` `append_run_log()` (non-fatal) appends `session_date, run_slot, finished_utc,
  rows` to `processed/run_log.csv`. `session_date` comes from `_t86_iso` (Ch.15 house rule —
  data date, wall-clock only as fallback); slot from `RUN_SLOT` (`unknown` when unset, e.g.
  local runs).
- Rider in the same feeder touch: snapshot filenames now stamp the **trading-session date**
  (`_t86_iso`) instead of wall-clock — a post-midnight backup no longer writes the prior
  session's snapshot under the next day's name.

**Ledger semantics:** only board-producing runs write a row. A gate stand-down or a stood-down
Backup B (17.4) writes nothing. Expect a `backupB` row most nights **in addition to** the
primary row — see 17.5's overwrite note.

### 17.4 Pre-dawn Backup-B false red — anatomy and fix (session 27, Task C item 2)

Root cause confirmed from raw Actions logs of three failed runs (07-06, 06-30, 06-25, all
starting ~04:3x TPE after cron drift). The anatomy, identical each time:

1. The primary had **already succeeded** that evening — the board was current.
2. Backup B's `--price-aware` gate fired anyway on ≥1 TWSE holding `price_stale` — the
   **structural** one-session `STOCK_DAY_ALL` lag (§14.5), not a real miss. The gate cannot
   distinguish structural lag from a genuine stale board, so it proceeded.
3. At ~04:33 TPE `STOCK_DAY_ALL` sits in its maintenance window → non-JSON across all 5 retry
   attempts → `SnapshotFetchError` → red exit.
4. Even with the endpoint up, a refetch cannot heal structural lag — the run was unwinnable
   before it started. Textbook false red.

**Fix (shipped):** in `fetch_snapshot()`'s all-retries-exhausted branch, if
`RUN_SLOT == "backupB"` → loud warning + green stand-down via the proven "no market data —
exit without overwriting data.json" path. **Fail-loud is preserved everywhere else**: primary,
Backup A, dispatch, and RUN_SLOT-unset local runs all still raise red.

**Real fix deferred by design:** MIS same-day pricing into the main board (7/28 boundary,
§14.5) removes the structural lag and with it the gate's blindness; the item here only
silences the false alarm.

### 17.5 `health.l3` "staleness" — resolved: NOT a bug (session 28)

The session-26 observation (board built 7/10 21:29 TPE stamping `health.l3 =
2026-07-09T12:31` despite L3 commit `8c9bc06` landing 12:34 TPE that day) is **feeder_l3's
own fail-safe working as designed**:

- `feeder.py` stamps `health.l3` from the `asof` inside `docs/raw/l3_fundamentals_latest.json`.
  Correct.
- `feeder_l3.py` refuses to overwrite `latest` when a fetch returns **0 flagged tickers across
  all sources** (treated as endpoint failure — an empty `latest` would poison the fallback
  chain and self-heal cannot recover it). It writes only a dated stub with `"stale": true` and
  a `stale_reason`, keeping the last known-good `latest` in place.
- Commit `8c9bc06` contained **only** such a stub (7/10 typhoon closure; 0 flagged). `latest`
  was never touched, so `health.l3 = 7/09` was honest reporting of genuinely stale L3 data.
- What misled the diagnosis: the workflow's flat commit message `L3 fundamentals <date>` looks
  identical for fresh runs and stale stubs. **Do not trust L3 commit messages; check the dated
  file's `stale` flag.** Baseline flagged counts run in the hundreds (198/198/152 on 7/08,
  7/09, 7/13), so the 0-flagged heuristic is safe.

**Detection playbook for future occurrences:** (a) `health.l3` date lagging the last trading
day on the data-health strip is the primary signal; (b) the dated stub's `stale_reason` is the
permanent archive evidence; (c) the Actions log carries a "NOT overwriting latest" warning.
The `twse-run-review` skill (backlog) gains a check: if `health.l3` < last trading day, fetch
the dated L3 file and report its `stale`/`stale_reason` as amber.

**Related nightly observation (session 28 sweep):** whenever the pre-dawn `STOCK_DAY_ALL`
endpoint is UP, Backup B's gate still fires on the structural lag and the run completes,
**overwriting the primary's board and snapshot with identical-session data** and appending a
`backupB` ledger row. Harmless (same session), confirmed nightly rather than occasional; goes
away with the 7/28 MIS work. Recorded, not a task.

### 17.6 Operational facts (save rediscovery)

- **Raw Actions log fetch (cookie-authenticated, from a github.com tab):**
  `github.com/<owner>/<repo>/commit/<FULL head_sha>/checks/<jobId>/logs` — a short SHA returns
  HTTP 500. Get `head_sha` + `jobId` from the `api.github.com` runs/jobs endpoints first
  (works fine via an authenticated browser tab; rate-limits hard from the sandbox IP).
- **Chrome MCP content-filter discipline:** returning raw log text from `javascript_tool`
  trips `[BLOCKED]`. Two-phase pattern: store filtered+sanitized lines in a `window._var`
  (strip URLs and `<>="'`, truncate ~140 chars), return only a count, read the array in a
  second call. **Navigation wipes all `window._*` vars.**
- A `raw.githubusercontent` read seconds after a commit can serve the pre-commit file even
  with `?cb=` (CDN edge race) — re-fetch before declaring an md5 mismatch real.
- Backup B's cron (`43 18 UTC`) drifts to ~20:3x–20:5x UTC starts on free-tier queueing —
  the drift is what pushes it INTO the TWSE maintenance window.
- pages-build-and-deployment grey (!) on an intermediate build = superseded by a newer
  commit's build, NOT a failed commit; the final green build serves everything.

### 17.7 Schedule & toolchain maintenance (session 28)

- Primary cron shifted `13 11` → `13 10` UTC (19:13 → **18:13 TPE**). T86 publishes ~18:00
  TPE and queue drift only pushes starts later, so the 13-minute nominal margin is the floor;
  the shift claws back ~1h of the 1–5h drift. Backups unchanged (23:37 / 02:43 TPE).
- `actions/checkout@v4→v5` and `actions/setup-python@v5→v6` across all five workflows
  (Node 20 deprecation warnings on every run).

### 17.8 What Chapter 17 does NOT change

No composite weights, confluence gate, L1–L5 formulas, observe baseline, or source tiering.
The 2026-07-28 batched flip is untouched. The gate-side design question — should
`--price-aware` stand down when the only staleness is the structural TWSE lag — remains
deliberately open pending the MIS decision.

## Chapter 18 — Skill in Production, the 7/17 Crash-Day T86 Gap & the Hit-Rate Grader (sessions 29–30) — NEW (2026-07-20)

### 18.1 `twse-run-review` skill shipped — backlog item 5 DONE (session 29, commit `b82e084`)

`skills/twse-run-review/` (`review_run.py`, 333 lines stdlib read-only + `SKILL.md`) is the
session-open ritual, replacing the manual verification sweep. Correction to §17.5's closing
note: the L3 stale-stub sub-check (fetch the dated L3 file, read `stale`/`stale_reason`)
shipped in v1, not later. One pre-ship fix from live testing: today's L3 stamp is expected
only after **13:00 TPE** on weekdays (run window ~11:44–12:34), killing a morning false-amber.
Canonical copy is the repo; the claude.ai upload is a zip of the folder — any change re-zips
and re-uploads so the two never drift (verified md5-identical at ship). First production run
(7/16 session): 10 green. First Monday-morning run (7/17 session): see 18.2.

### 18.2 2026-07-17 — record crash day, market-level T86 gap (session 30)

**The day.** TAIEX −2,953.71 (−6.47%) to 42,671.27 — largest single-day point drop in its
history — on NT$1.21T record turnover (post-earnings TSMC selloff cascade).

**The gap.** Primary ran 19:59 TPE (drift, nominal 18:13) and the market-level T86 fetch
returned empty — almost certainly endpoint strain under record volume, not our code. Board
shipped with `t86_session: null`, `foreign/trust/dealer/three_inst_total_m = 0.0`, and a
derived `pressure: Neutral` that was therefore meaningless on the heaviest foreign-selling
day of the window. `foreign_5d_cumul_m` (separate endpoint) stayed live and true
(−310,242M). Per-ticker chip windows were partially short — concretely, 3363's L1 collapsed
−0.868 → −0.033 and Friday's signal printed TRIM where the prior day fired SELL. BackupB
stood down Saturday (by design; no row, no commit), so nothing recovered it; the zeroed
header sat on the live dashboard through the weekend.

**Why it self-heals with zero action.** There is **no local chip-history file**: feeder.py
re-fetches the T86 multi-day window live, per-date, on every run. The next primary pulls the
last 5 sessions — including 7/17, published on TWSE's historical endpoint well before then —
so both the header and the L1 5-day windows repair in one run. Nothing to commit, nothing to
trigger (house rule: no manual run pre-18:00 TPE).

**What stays degraded, deliberately.** The shipped 7/17 board is the decision-time record
(Ch.15 principle: logs record what the system emitted, not later recomputes). It is flagged
`DEGRADED` in the hit-rate grader (18.3) and excluded from the headline metric.

**Skill scorecard.** The Monday-morning run flagged 2 RED: `health.t86` (true positive — the
incident above) and `health.data` 3d-old (false positive — the age check is weekend-unaware;
reviewing Friday on Monday morning trips it). **v1.1 fix queued:** make the age check count
trading days, not wall-clock days. One concern per commit; re-zip/re-upload on ship.

### 18.3 Hit-metric decision + `tools/hitrate_review.py` (session 30, commits `6fcf4c3` + `4c6dd19`)

**Decision (Fisher, 2026-07-20): PRIMARY = metric A, sign(fwd_5d) vs action direction.**
Rationale: (1) sample maturity — at review time fwd_5d is graded for nearly the whole window
while fwd_20d matures only for pre-~6/29 fires (5 rows graded at decision time); (2) horizon
match — L1 runs on 1/3/5-day chip windows, so fwd_5d tests exactly what the score claims;
(3) already graded in-log, zero plumbing. fwd_10d/fwd_20d and metric C (fwd_5d excess vs
TAIEX 5d forward, baseline = `verdict_log` compounded, partial coverage from 6/18) are
computed alongside. **C graduates to primary post-boundary** once a TAIEX series is archived
forward — it is the only metric that separates selection from beta, which the crash week
makes obvious (every TRIM “hits” fwd_5d in a −5.92% week regardless of skill).

**The tool.** `tools/hitrate_review.py` — stdlib, read-only, exit 0 always, fetches both
CSVs live (cache-busted) or `--local DIR`. Direction: GO/ADD → +, SELL/TRIM → −; near-miss
counterfactual direction = sign(composite); fwd == 0 counts as a miss. Sections: coverage
(logger shipped mid-window — first row 6/16 vs observe open 5/29; Ch.15 repaired-rows note;
DEGRADED sessions), metric A by action and side, horizons, metric C, |composite| bands,
§12.1 L1 bands (0.4–0.6 vs >0.6), per-layer agree/oppose attribution, near-miss grading by
`gate_fail_reason`, and the §12.1 counterfactual “L2 gate → 0.35” (flips rows with
|L2| ∈ [0.35, 0.4)). One §12.1 review query is **not computable**: flag-correlation
(churn-flagged GOs) — `signal_log` carries no flag column. Placement note: plain `tools/`
over a skill — runs a handful of times around the boundary; no zip maintenance.

**Early reads (small samples, fwd cells still filling — do not act before 7/28):**
GO-side 1/10 vs SELL-side 12/22 on fwd_5d (metric C softens the GO-side: 48.4% excess — most
GO fires immediately preceded the −5.92% week); the L2→0.35 relaxation would have flipped 8
near-misses at 2/7 graded hits — first evidence the 0.4 gate earns its keep.

### 18.4 What Chapter 18 does NOT change

No composite weights, confluence gate, L1–L5 formulas, observe baseline, or source tiering.
The 2026-07-28 batched flip is untouched. New open item added to it in spirit only: skill
v1.1 weekend-aware age check ships independently (display/tooling, freeze-exempt).

-----

## Chapter 19 — Two Undocumented Scoring Divergences (session 32) — NEW (2026-07-22)

Both were found while doing a *routine* 3363 L1 spot-check six days before the observe
boundary. Neither is a crash, an outage, or a failed run — both have been quietly shaping
every score in the observe window, and neither appears in any prior chapter, handoff, or
backlog. **Nothing in this chapter changes code.** It records what the shipped system
actually does, so the 2026-07-28 review does not misread its own evidence.

The unifying failure mode is the one §6 exists to prevent: **built ≠ documented**. §6 asks
for divergence to be stated in the commit message and the handoff; these two escaped because
one shipped as a workflow env var (not a code diff anyone reviewed against the guide) and the
other is arithmetically invisible — wrong units produce plausible-looking scores in the right
range, so nothing ever looked broken.

### 19.1 `ENABLE_MARGIN=1` is live in production, and always has been

`.github/workflows/daily.yml` line 87 sets `ENABLE_MARGIN: "1"`. It is present in **every**
version of `daily.yml` the atom feed still exposes, back to `872fa78b` (2026-06-16). So the
`margin_score` sub-component (融資 read, 10% L1 sub-weight, §1.3) has been folded into L1 as

    l1 = (0.50 × t86_score + 0.10 × margin_score) / 0.60

for the **entire** `signal_log` window (first row 2026-06-16), while Chapter 1, the build-order
recap, `bsr_alternatives.md`, and every handoff have continued to call it an unshipped stub.

**Board evidence (2026-07-21 board, 48 rows):** `margin_score` is non-null on **34 of 34 TWSE
rows** and null on **all 14 TPEx rows** (values: 0.6 × 15, 0.0 × 15, 0.2 × 4).

**Severity is documentation, not contamination.** Because the flag predates the whole log,
the observe baseline is *internally consistent* — there is no mid-window regime break. Nothing
needs unwinding.

**But it carries a real asymmetry worth stating plainly:** MI_MARGN is a **TWSE-only** endpoint,
so `margin_score` is structurally `None` on every TPEx name. TWSE and TPEx names are therefore
scored on **different L1 denominators** — `/0.60` vs `/0.50`. That is the §1.7 rescale working
exactly as designed (fail-safe: unfilled sub-scores are not counted), but it means a TWSE name
and a TPEx name with identical chip flows do **not** produce identical L1. Not necessarily
wrong; definitely not documented until now, and it belongs in the 7/28 read.

**Decision owed (Fisher):** keep `ENABLE_MARGIN` ON and correct the docs, or flip it OFF.
The recommendation on the table is **keep ON** — flipping it off six days before the boundary
would create a *third* baseline regime for no analytical gain. Either way the guide must stop
calling it a stub.

### 19.2 The L1 float-cap unit bug — T86 is a sign vote, not a magnitude

`score.py::compute_l1_score` normalises each 5-day net against a cap derived from free float:

```python
cap = float_m * 1000 * cap_pct        # score.py L125
```

`FLOAT_M` values are in **millions of shares** (`"2330": 25930` = TSMC's 25.93B ✓). The
multiplier must therefore be `1_000_000`, not `1000`. **Every cap is 1000× too small.**

The unit intent is not in doubt — `_float_pct` (L330), in the same file, for the *display*
percentage, does it correctly:

```python
return net / (float_m * 1_000_000) * 100.0    # score.py L330 — correct
```

So one function reads `FLOAT_M` as millions and the other as thousands. The display % has
been right all along; the scoring cap has not.

**Scale of the error (2026-07-21 board):**

| Ticker | `float_m` | foreign 5d cap (shipped) | actual foreign 5d | over cap |
|---|---|---|---|---|
| 0050 | 6,800 | 34,000 sh | −311,940,225 | **9,175×** |
| 2359 | 2,000 | 10,000 sh | −4,453,704 | 445× |
| 6223 | 1,100 | 5,500 sh | −2,093,955 | 381× |
| 2330 | 25,930 | 129,650 sh | −48,522,380 | 374× |
| 5274 | 560 | 2,800 sh | −1,008,975 | 360× |

**Consequence.** Of the 26 float-covered rows on that board, **26/26 have at least one term
clipped at ±1**, and **18/26 have every non-zero term clipped**. When all three clip,
`t86_score` collapses to

    ±0.50 ±0.30 ±0.20

— a ternary vote on the **signs** of the trust / foreign / dealer 5-day nets, with all
magnitude information discarded. A 投信 net-buy of 1% of float and one of 0.001% of float
score identically.

**This is verified, not inferred.** The full 48-row board reproduces **48/48 exact** when the
live `score.py::compute_l1_score` is called directly with each row's `trust_5d` / `foreign_5d`
/ `dealer_5d`, that ticker's `FLOAT_M` value, and its `margin_score`. There is no residual.

**Worked example — 3131 (float_m = 850), the row that exposed it:**

| term | 5d net | shipped cap | ratio | contribution |
|---|---|---|---|---|
| 投信 | +55,000 | 17,000 | 3.24 → **clipped +1** | +0.500 |
| 外資 | −271,950 | 4,250 | −64.0 → **clipped −1** | −0.300 |
| 自營 | −4,070 | 8,500 | −0.479 (only unclipped term) | −0.096 |

`t86_score = 0.104`; `margin_score` is `None` (TPEx), so `l1 = 0.104` — the exact board value.
Note that the **only** term carrying real information is the dealer term, the one the spec
de-weights hardest as noisiest (§1.3, warrant hedging).

### 19.3 The same bug in `_norm_mag` — the §12.2 `driver` line is saturated too

`_norm_mag` (L347) is the ranking helper behind the §12.2 why-line and repeats the identical
`float_m * 1000 * cap_pct`. `_driver_string` sorts candidates by `(magnitude, priority)` — so
when both the 投信 and 外資 magnitudes clip at exactly 1.0, the sort is a **tie** and the
priority rank alone decides it. Trust outranks foreign, so **投信 always wins**.

**Verified on the 2026-07-21 board:** of the 20 float-covered rows where both `trust_5d` and
`foreign_5d` are non-zero, **18 have both terms clipped** — and the driver reads `投信5日` on
exactly those 18. The 2 rows where `外資5日` wins are precisely the 2 where the tie did not occur.

So the dashboard's "dominant L1 reason" is, on saturated rows, not a measurement — it is the
tie-break constant. The *number* rendered next to it (`+0.01% float`) is correct, because
`_fmt_flow` routes through the correct `_float_pct`. **A row can therefore display a driver
label chosen by tie-break alongside a percentage that contradicts it** — e.g. 3131 renders
`投信5日 +0.01% float` while 外資 moved 64× more float that week.

Any fix to L125 must patch L347 in the same commit, or the score and the explanation of the
score will disagree.

### 19.4 `FLOAT_M` value-audit debt — why 19.2 cannot be fixed alone

`FLOAT_M` is ~30 hand-maintained entries in `feeder.py` (L103), in millions of shares. A
wrong cap *unit* has been masking wrong cap *values*: with every cap 1000× too small,
essentially everything clips, so an individual bad `FLOAT_M` entry has had no visible effect.
Correcting the unit removes that mask and each value starts to matter directly.

Known suspect: `"3363": 2100` — 2.1B shares for 上詮, roughly 20× too large for a name of that
size. It is unlikely to be the only one.

**Therefore: do not land the L125/L347 unit fix without auditing `FLOAT_M` in the same
change.** A correct unit applied to wrong float values is *worse* than the current state — the
present bug is at least uniform and self-announcing (everything clips), whereas selectively
wrong floats would produce silently wrong magnitudes that look entirely plausible. This needs
a source decision first (TWSE/TPEx shares-outstanding endpoint vs. hand maintenance), and
`FLOAT_M` covering only ~30 of 48 board names is itself a coverage gap (§8.3 already flags it
for the market-cap band).

### 19.5 How the 2026-07-28 review must read its own L1 evidence

`tools/hitrate_review.py` (§18.3) reports hit-rate by **L1 band (0.4–0.6 vs > 0.6)**, on the
§12.1 premise that the band proxies chip-signal *strength*. Given 19.1 + 19.2, it does not.
For the observe window, an L1 band is:

> a **sign-combination** of the trust / foreign / dealer 5-day nets, plus the margin term on
> TWSE names only, divided by a denominator that differs by exchange.

Concretely, on saturated rows the reachable `t86_score` values are the sums of ±0.50/±0.30/±0.20
— so the bands are enumerating *which institutions agreed*, not *how hard they bought*. That is
still a real and testable signal — arguably a clean one — but it is a different hypothesis than
the one §12.1 wrote down, and the review must not report it as flow magnitude.

**Two concrete instructions for the review:**
1. Read L1 bands as agreement patterns. "L1 > 0.6" ≈ "trust and foreign agreed", not "large flow".
2. Segment by exchange before comparing L1 bands, because of the 19.1 denominator asymmetry.

### 19.6 §14.5 roll-time evidence — option (a) is ruled out

Carried here because it is decision-relevant at the same boundary. On the 2026-07-21 session
the board is honestly **mixed-date** by exchange, exactly as §14.4 designed:

| Section | `price_session` | `price_stale` | Rows |
|---|---|---|---|
| TWSE (portfolio + watchlist) | `20260720` | `True` | 34 |
| TPEx | `20260721` | `False` | 14 |

with `market.price_stale_count = 1` and `price_stale_watch_count = 33`. The header is fresh
(T86 and TAIEX come from endpoints that publish same-day); this is the known structural
`STOCK_DAY_ALL` one-session lag, correctly detected and honestly flagged with the §14.4 amber
前日價 pill. Not a bug and not a failed run.

**What is new:** Backup B ran at **04:18 TPE and still received 7/20 prices.** The TWSE feed
therefore rolls *later* than 04:18 TPE. That empirically **eliminates §14.5 option (a)**
("a post-roll D+1 morning cron") at any slot the free tier can reliably hit — free-tier drift
already pushes 02:43 nominal starts to ~04:1x, and the feed is still behind at that point.
**Option (b) — MIS same-day pricing into the main board — is now the standing recommendation**,
and it carries a second dividend: it removes the structural lag that blinds the `--price-aware`
self-heal gate (§17.4, §17.8), permanently retiring the Backup B false-fire class.

### 19.7 Decisions owed out of this chapter

| # | Decision | Recommendation | Blocks |
|---|---|---|---|
| 1 | `ENABLE_MARGIN` — keep ON or flip OFF | **Keep ON**, fix the docs | — |
| 2 | L1 cap-unit fix (`×1000` → `×1e6`, L125 **and** L347) into the 7/28 batch | **Yes — but only paired with (3)** | (3) |
| 3 | `FLOAT_M` value audit + source decision | Needed before (2) can land safely | — |
| 4 | §14.5 price source | **Option (b), MIS same-day** | — |

Items 2–4 are boundary-gated; item 1 is a documentation correction that can land any time.

### 19.8 What Chapter 19 does NOT change

**No code was changed by this chapter.** No composite weights, confluence gate, L1–L5 formulas,
observe baseline, or source tiering. The 2026-07-28 batched flip is untouched — the cap-unit fix
is *proposed* into it (19.7 item 2), pending the `FLOAT_M` audit, and is not staged. The freeze
holds.
