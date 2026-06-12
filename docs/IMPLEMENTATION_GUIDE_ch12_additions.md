# IMPLEMENTATION_GUIDE additions — Chapter 12 (paste-ready)

> Three edits, all in `docs/IMPLEMENTATION_GUIDE.md`. Apply as ONE commit:
> `docs: add Ch.12 decision-quality & legibility upgrades (attribution log, why-line, breadth, agreement)`

---

## Edit 1 — INSERT at the top of the changelog block (newest first)

```
> - **2026-06-12** — Added **Chapter 12** (decision-quality & legibility upgrades): signal
>   attribution log (12.1, prerequisite for all future tuning), action why-line + distance-to-flip
>   (12.2), data-health strip (12.3), market breadth leg (12.4), Taifex OI display chip (12.5),
>   confluence-degree display (12.6), verdict scoreboard (12.7), recency decay [BOUNDARY-HELD]
>   (12.8). Build-order recap amended. No scoring math changes before 2026-07-28.
```

---

## Edit 2 — APPEND as a new chapter after Chapter 11

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

## Edit 3 — REPLACE the "Build order recap (revised)" list with

```
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
```

-----
*End of paste-ready additions.*
