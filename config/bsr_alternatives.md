# BSR Alternatives — L1 Without Broker-Branch Data

> **Status: reference document, not yet adopted.** This is the playbook for completing L1 if the
> BSR (`bsr.twse.com.tw`) CAPTCHA barrier is never resolved. Nothing here is wired into scoring
> until explicitly decided. Source-tier discipline applies throughout: everything below is Tier-1
> (TWSE/TPEx/期交所) unless marked otherwise.
>
> **Hard rule:** no CAPTCHA solvers, no paid scraping proxies, no automation against BSR. The
> CAPTCHA is TWSE's explicit "no bots" signal. The only permitted BSR path is a **human** clicking
> the download button (Option D).

---

## What BSR actually provides (so we know what we're replacing)

BSR (個股券商買賣明細) is the per-stock, per-day, per-broker-branch ledger. It feeds two stubbed
L1 sub-components:

| Sub-component | L1 weight | What BSR gives it |
|---|---|---|
| `concentration_score` | 20% | Top-15 buyer/seller net vs total volume (CMoney-style 籌碼集中度) |
| `broker_score` (隔日沖) | 20% | Branch identity: is the #1 buyer a known 隔日沖 desk, >20% of volume, >2× #2? |

The information content of BSR, distilled: **(a)** how *concentrated* the buying is (few hands vs
many), and **(b)** *whose* hands (sticky 主力 vs next-day dumpers). The alternatives recover (a)
approximately and (b) partially.

---

## Option A — Fill the easy stubs first: margin + 借券 (no proxy needed)

These are not BSR substitutes — they're the *already-specced* L1 components that happen to be
CAPTCHA-free. Do these regardless of any BSR decision.

### A1. `margin_score` (融資融券) — 10% of L1, fully specced in Research Report §1.4
- **Endpoint:** `https://www.twse.com.tw/zh/trading/margin/MI_MARGN.html` (CSV/JSON, daily, no CAPTCHA).
  TPEx mirror exists for 上櫃.
- **Fields:** 融資餘額, 融券餘額, 融資使用率, 券資比.
- **Scoring sketch (Tier-1 rules, from the report):**
  - 法人 5d net buy > 0 AND 融資餘額 5d change ≤ 0 → **+1** (silent accumulation — the cleanest template)
  - 融資餘額 ↑ AND price ↑ AND 法人 net sell → **−0.5** (retail chasing into distribution)
  - 融資餘額 ↑ AND price ↓ → **−1** (forced averaging-down)
  - 券資比 > 30% AND price rising → **+0.5** squeeze flag (display badge, not a gate)
- **Effort:** low. One whole-market pull/day, joins on ticker.

### A2. 借券賣出餘額 — real institutional short interest
- **Endpoints:** `twt92u.html` (借券賣出餘額) / `twt93u.html`, daily, no CAPTCHA.
- **Read:** 20d trend. Rising balance + flat price = distribution warning; falling = cover.
  New-issue rule: ignore first 5 trading days after 借券 opens on a name (baseline-0 distortion).
- **Where it goes:** either a new 10% L1 sub-weight, or folded into `margin_score` as a
  combined "leverage/short posture" component. Decide at adoption time, flip only at an
  observe boundary.

---

## Option B — Concentration proxy from T86 (replaces `concentration_score`, approximate)

### Formula
```
ConcProxy_N = Σ_N(三大法人 net buy shares) / Σ_N(total volume shares) × 100%
```
Same shape as the CMoney formula, but the numerator is **institutional net** instead of
**Top-15-branch net**.

### What carries over and what doesn't
- **Carries over:** direction and trend. When real concentration rises because 投信/外資 are
  accumulating, ConcProxy rises with it. The report's "trend > level" rule (rising 5d on rising
  20d = continuation) transfers cleanly.
- **Lost:** non-institutional 主力 (大戶 buying through retail-channel branches) is invisible —
  this is precisely the "under-the-radar" population Radar hunts. Also lost: thresholds. The
  CMoney cutoffs (1d>20%, 60d>5%...) are calibrated to Top-15 branch data and **must not** be
  reused on the proxy. Derive proxy thresholds empirically from your own distribution after
  60+ days of computing it (e.g. flag top-quintile ConcProxy within your universe).
- **Labelling rule:** every surface showing it says `集中度 (proxy)`. It never silently
  substitutes for real concentration in docs or thresholds.json.

### Effort
Near zero — computed from the whole-market T86 you already pull and persist.

---

## Option C — Behavioral 隔日沖 proxy (replaces `broker_score`, partial)

Without branch identity, detect the *footprint* of next-day churn:

```
churn_flag(t) =  volume(t) > 2.5 × avg_volume_20d
             AND |三大法人 net(t)| < 0.1 × volume(t)        # institutions roughly flat
             AND close(t) > open(t)                        # ran up intraday
confirmed(t+1) = churn_flag(t) AND close(t+1) < open(t+1)  # next-day red
```

- **Logic:** a volume explosion that institutions didn't drive, on an up day, is retail/day-trade/
  隔日沖 churn by elimination. Next-day red confirms.
- **Use:** `churn_flag` discounts the GO score same-day (pre-emptive); `confirmed` feeds the
  false-positive log. The 4% open-gap exit rule still applies if holding a flagged name.
- **What's lost vs BSR:** the *pre-emptive identity* signal. Real broker_score flags **before**
  the dump because the branch name is known; the proxy partially infers it from the volume/flow
  shape and fully confirms only after the fact. Expect more false negatives on sophisticated
  隔日沖 desks that size below the volume threshold.
- **Calibration:** start with the 2.5× / 0.1 / red-next-day parameters above, log every fire for
  60 days, then tune against the >60% false-positive recalibration rule in the Research Report.

---

## Option D — Manual low-volume BSR pulls (real data, human-in-the-loop)

BSR's per-stock CSV download works fine for a human in a browser. This is legitimate and matches
the existing drag-and-drop workflow.

### Protocol
1. **Scope:** inventory (T1) + radar survivors only — per agent_ops §8, BSR effort is spent only
   on names that already cleared the T86 screen. Practical cap: **≤ 10–15 names/week**.
2. **Cadence:** weekly (e.g. Saturday), or event-driven when a name flags `churn_flag` or surfaces
   on Radar.
3. **Files:** download CSV per stock → drop into `/raw/bsr/{ticker}_{YYYYMMDD}.csv` via drag-drop.
4. **Processing:** a parser script computes real Top-15 concentration + checks top buyers against
   `broker_behavior.json` watchlist → writes `/processed/bsr_spot.csv`.
5. **Scoring rule:** manual BSR data is a **spot-check overlay**, not a daily score input — it's
   too sparse (weekly, partial universe) to be a fair daily sub-component. It validates/refutes
   the Option B+C proxies: when proxy and real BSR disagree on a name you hold, trust BSR.
6. **Display:** dashboard shows a `BSR ✓ {date}` badge on spot-checked names with the real
   concentration number next to the proxy.

### Effort
~15–30 min/week of human time. The parser is a one-session build.

---

## Option E — Formal reweight (if abandoning concentration/broker entirely)

If proxies + manual pulls aren't worth it, redistribute L1 honestly rather than carrying
permanent stubs:

```
Current spec:  L1 = 0.50·T86 + 0.20·concentration + 0.20·broker + 0.10·margin
Reweighted:    L1 = 0.60·T86 + 0.20·margin/借券 + 0.20·ConcProxy(B) — or —
Minimal:       L1 = 0.70·T86 + 0.30·margin/借券
```

- Flip **only at an observe boundary** (next: 2026-07-28), same rule as the VIX cap.
- Document in IMPLEMENTATION_GUIDE §1 changelog as a deliberate spec change, not a stub.

---

## Effectiveness comparison — honest assessment

Scale: how much of the original BSR-based sub-component's decision value is recovered.
These are judgment estimates, not backtested numbers — treat as priors to verify against your
own hit-rate log.

| Configuration | Concentration value recovered | 隔日沖 value recovered | Notes |
|---|---|---|---|
| **Original BSR** (daily, automated) | 100% | 100% | The benchmark — currently unreachable without violating the CAPTCHA wall |
| **A only** (margin + 借券, no proxies) | ~0% (different signal) | ~0% | Not substitutes — but they add *new* orthogonal signal (retail posture, short interest) the original L1 spec wanted anyway |
| **B alone** (T86 conc proxy) | ~50–60% | 0% | Trend/direction recovered; level thresholds and non-institutional 主力 lost. Blind exactly where Radar hunts |
| **C alone** (behavioral churn) | 0% | ~40–50% | Catches blunt 隔日沖; misses identity-based pre-emption and sized-down desks; confirms partly after the fact |
| **B + C combined** | ~50–60% | ~40–50% | The realistic automated ceiling. Combined they cover the *common case* (institutional accumulation real-or-churned) but stay blind to branch-level 大戶 games |
| **B + C + D** (proxies + weekly manual spot-checks) | ~70–80% on covered names | ~60–70% on covered names | Best practical option. Real data exactly where decisions happen (holdings + radar survivors); proxies cover the rest. Sparse cadence is the residual gap — a Tuesday 隔日沖 trap isn't caught by a Saturday pull |
| **E** (reweight, no replacement) | n/a | n/a | Honest but thinner: L1 becomes a flow-persistence + leverage layer. Confluence gate still protects you; expect somewhat more chip-trap entries that L2 must catch |

### Key takeaways
1. **Single source never substitutes.** No one alternative recovers BSR; the value is in the combination, and even combined it tops out around ~70–80% — and only on the names you spot-check.
2. **The irreducible loss is identity.** Everything except Option D infers from shape; only branch names tell you *who*. That's the piece TWSE deliberately put behind a human gate.
3. **Where the loss bites:** Radar (under-the-radar 大戶 accumulation invisible to T86-only proxies) and same-day 隔日沖 pre-emption. Where it doesn't: inventory SELL decisions (margin/借券/外資持股比率 trends cover distribution well) and the confluence gate itself.
4. **The confluence gate is the safety net.** Even a degraded L1 can't fire a GO alone — L2 must co-sign. The cost of the proxies is missed opportunities and a few more L2-caught traps, not blown-up trades.

---

## Recommended adoption sequence (if going down this route)

1. **A1 + A2 now** (margin + 借券) — specced, free, CAPTCHA-free, no proxy caveats. Flip into L1 at the 2026-07-28 boundary.
2. **B** (ConcProxy) — compute and *display* immediately, score after 60 days of own-distribution threshold calibration.
3. **C** (churn flag) — same: display + log first, score after the false-positive review.
4. **D** (manual pulls) — only if the July hit-rate review shows decisions where branch data would have changed the call. Build the parser then, not before.
5. **E** — fallback if D proves not worth the weekly effort after 2–3 months.

*Referenced from IMPLEMENTATION_GUIDE Ch.1; adopt via changelog entry + boundary-timed commit.*
