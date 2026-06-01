# ARK (方舟運算) — Tier-3 Cross-Check Rulebook

> **Status: skeleton — fill in as you learn the app.** This file is the *rulebook* for cross-checking against the 方舟運算 app, not a data feed. App data is entered **manually via screenshots**. Nothing in this file ever feeds a score or the confluence gate — it guides your eyes only.

## Hard boundary (do not delete)
- **Tier 3.** 方舟 is a popular consumer app (Galaxy Digital Co., influencer-led), not an institutional source.
- It **cross-checks and displays**; it **never originates a threshold or rule**. Any number that gates an action must come from Tier 1 (TWSE/TPEx/MOPS).
- Data is **manual** (screenshots). No scraping, no API.

## Signal map (confirmed)
| ARK signal | What it means | Our analogue | Cross-checks |
|---|---|---|---|
| 價值 (value zone) | undervalued + good fundamentals → long buy | L3 fundamental anchor | **Radar / opportunity** |
| 升溫 (heating zone) | overextended → trim/sell | L2 overbought (RSI/BIAS/position) | **Inventory / trim** (not Radar) |
| 位階 漏斗 (level funnel) | how high-in-range the price is (green=low/cheap, red=high/hot) | L2 position-in-range | both, as context |
| 水位 (持股配置建議 %) | portfolio cash-vs-equity level (e.g. 66.1%) | conceptually L4, expressed as sizing | **Inventory / portfolio sizing** |
| 建議調節股數/金額 | per-ticker offload suggestion | (report omits sizing) | **Inventory** sizing aid |

## How to use it
- **Radar candidate surfaces from our chip data →** check 方舟 for a 價值 tag (supports it) and absence of 升溫 (not already hot). Agreement = confidence; divergence = investigate, don't act.
- **Holding flags our L2 as overbought / distribution →** check 方舟 升溫 + 水位. Agreement = stronger trim case.
- **Sizing:** our system answers GO/TRIM + confluence; 方舟 水位 answers *how much*. Keep the two questions separate — a portfolio-level water level never overrides a per-ticker signal.

## Read-rules still to confirm (TODO — fill from the app)
- [ ] 位階 — absolute or relative-to-history?
- [ ] 升溫 — what triggers it? (price run %? volume? distance from MA?)
- [ ] 價值 — what defines the value zone? (valuation multiple? vs sector? own history?)
- [ ] 水位 — what do the five gauges weight? (全球散戶 / 外資情緒 / 位階增溫 / 社交反指 / 量能爆衝)
- [ ] Update cadence — confirmed hourly; note refresh countdown when screenshotting.

## When 方舟 and our system disagree
Record it, don't act on the app. A divergence is a research prompt, not a signal. If a pattern of divergence emerges, it tells us where our Tier-1 analogue needs tuning — not that the app is right.
