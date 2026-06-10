# Watchlist System — Implementation Instruction Set

**Version:** v2 · **Created:** 2026-06-01 · **Last updated:** 2026-06-10

> **Changelog (newest first).** The title no longer carries a single date — read this block, not the
> header, to know what is fresh. Major version (v2) tracks *structural* revisions; append-only notes
> and status flips are minor. Git holds the full per-line history.
>
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

### 1.7 ⚠ FIX BEFORE TRUSTING OBSERVE-ONLY DATA — L1 is structurally halved

Currently `L1 = 0.50 * T86_score`, with concentration/broker/margin **hard-zeroed** (not rescaled). Two consequences:

1. **L1 caps near ±0.5 and a 投信-only signal yields L1 ≈ 0.25** — *below* the GO confluence threshold (L1 ≥ 0.4). Almost no GO can fire on the L1 side during the stubbed period.
2. **The observe-only baseline you are collecting now is on a half-strength L1.** When concentration/broker/margin land, L1 roughly doubles, and the 60-day stats won't transfer.

**Fix (pick one, do it before the clock matters):**
- **(A) Preferred — rescale L1 internally** by the filled-sub-weight fraction, exactly as `compute_composite` already rescales for missing *layers*. This makes today's L1 comparable to the finished system, so the observe-only data stays valid.
- **(B) Otherwise — restart the 60-day observe-only clock** when L1's sub-components are complete, and label all data before that as "T86-only proxy."

This is the single most important correction in this revision because it affects data being collected *right now*.

-----

## Chapter 2 — Technical / Price Layer (L2, weight 30%) — BUILD SECOND

Confirmation layer. **Done** (KD, MACD, BB, golden cross, MA-stale detection all shipped). L2 sub-weights in code: MA 30%, volume 20%, RSI 15%, KD 15%, MACD 15%, golden-cross +5% bonus.

- Indicator rules and GREEN-light confluence (≥ 3 required) unchanged from prior guide.
- **Note:** Bollinger Bands are computed but not scored (display-only). Optional refinement: add a BB squeeze→breakout contribution later.

-----

## Chapter 3 — Fundamental Anchor (L3, weight 10%) — EXCLUSION FILTER ONLY

Monthly batch. **Not started.** Auto-EXCLUDE: 月營收年增率 < −10% for 2+ months; EPS negative latest quarter; 負債比 > 70%; 設質比 > 30%; on 注意股/處置股 list. For inventory, L3 ≤ −0.6 alone is a valid SELL contributor. Sources: MOPS `t05st10_ifrs`, quarterly reports, `mopsfin.twse.com.tw`. Run after the 10th + on quarterly dates.

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

1. **Chapter 1.7 + Chapter 7 fixes FIRST** — rescale L1 (or restart the clock) and move the run to ≥ 18:30. These correct data being collected *now*.
2. **Chapter 8 — Radar v1** — persist whole-market T86, exclude T1/T2, trend-based coverage filter, new Radar tab.
3. **Chapter 9 — ARK file** — create `config/ark_crosscheck.md`, reference from tab (manual screenshots).
4. **Chapter 1 stubs** — concentration_score (BSR), broker_score (隔日沖), margin_score.
5. **Chapter 3 — L3** monthly filter.
6. **Chapter 4 — L4** regime tilt (forces the `/raw` committed-file split).
7. **Chapter 5 — L5** news sentinel.
8. **Chapter 7** — full multi-time schedule.
9. **Observe-only for 60 days**, log every would-be action, compute real hit-rate by bucket *before* trusting it with size.
10. **Chapter 10 — Summary tab (今日)** — default landing surface: Market Pulse + Verdict + Portfolio Watch + Radar Spotlight. Display-only; no new scores. (Shipped 2026-06-08.)

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
