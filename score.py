"""
score.py -- scoring layer carved out of feeder.py (behavior-preserving).

Pure scoring: L1 chip sub-scores, L2 technical score, composite, confluence
gate, action table, and the bucket-weight config loader. Leaf module: imports
only stdlib, references nothing from feeder.py, so feeder.py imports FROM here
with no circular dependency. Logic is byte-identical to the pre-carve feeder.

Source-tier / confluence discipline is unchanged -- see IMPLEMENTATION_GUIDE
Chapter 1 (L1), Chapter 2 (L2), Chapter 6 (synthesis + confluence gate).
"""
import csv
import json
import logging
import os
from datetime import datetime

# Child of the "feeder" logger configured in feeder.setup_logging(); it
# propagates to the same handlers, so log output is unchanged.
log = logging.getLogger("feeder.score")


# --- L1 chip sub-scores & signal score --------------------------------------
def _sgn(x):
    if not x: return 0
    return 1 if x > 0 else -1


def compute_margin_score(margin_today, margin_prev, price_chg_pct, inst_net):
    """4c: retail-sentiment read in [-1, +1] from 融資餘額 change vs price and 法人 flow.

    Report logic: 法人 buy + 融資 flat/down = silent (clean) accumulation [+];
    融資 up on an up-day while 法人 sell = retail chasing / distribution risk [-].
    Magnitudes/thresholds here are interpretation of the report's qualitative rules
    (tunable later via thresholds.json), not Tier-1-originated rules.
    """
    if margin_today is None or margin_prev is None or margin_prev <= 0:
        return None
    m_chg = (margin_today - margin_prev) / margin_prev
    inst = inst_net or 0
    pc = price_chg_pct or 0
    score = 0.0
    if inst > 0 and m_chg <= 0.0:
        score = 0.6      # institutions accumulating without retail chasing
    elif inst < 0 and pc > 0 and m_chg > 0.02:
        score = -0.8     # margin rising on up-day while institutions sell = distribution
    elif pc > 0 and m_chg > 0.05:
        score = -0.4     # retail chasing on margin
    elif inst > 0 and m_chg > 0:
        score = 0.2      # both rising = mild confirmation
    return round(max(-1.0, min(1.0, score)), 3)


def compute_concentration(buyer_nets, seller_nets, total_volume):
    """4a: chip concentration % for one window.

    concentration = (sum(top-15 buyer nets) - sum(top-15 seller nets)) / total_volume * 100
    Signed: positive = net specific-party accumulation, negative = distribution.
    `buyer_nets` / `seller_nets` are per-branch net share counts (already split by side);
    `total_volume` is the window's total traded shares. Returns None if no volume.
    """
    if not total_volume or total_volume <= 0:
        return None
    top_buy = sum(sorted([n for n in buyer_nets if n > 0], reverse=True)[:15])
    top_sell = sum(sorted([abs(n) for n in seller_nets if n < 0], reverse=True)[:15])
    return round((top_buy - top_sell) / total_volume * 100.0, 3)


def compute_concentration_score(c5, c60):
    """Map signed 5-day and 60-day concentration % to an L1 sub-score in [-1, +1].

    Thresholds are DISPLAY references from the report (5d > 6%, 60d > 5%), used here
    only to normalise magnitude -- they are not standalone action rules (1-day chip
    alone had a documented sub-30% hit rate). Returns None if neither window has data.
    """
    parts = []
    if c5 is not None:
        parts.append(max(-1.0, min(1.0, c5 / 6.0)))
    if c60 is not None:
        parts.append(max(-1.0, min(1.0, c60 / 5.0)))
    if not parts:
        return None
    return round(sum(parts) / len(parts), 3)


def compute_l1_score(t86_entry, float_m, concentration=None, margin=None):
    if not t86_entry:
        return None
    def norm(net, cap_pct):
        if net is None: return 0.0
        if float_m and float_m > 0:
            cap = float_m * 1000 * cap_pct
            return max(-1.0, min(1.0, net / cap)) if cap else 0.0
        return max(-1.0, min(1.0, net / 10000))

    f5  = t86_entry.get("foreign_5d") or 0.0
    tr5 = t86_entry.get("trust_5d")  or 0.0
    d5  = t86_entry.get("dealer_5d")  or 0.0        # real 5d sum (P1a fix)

    t86_score = (
        0.50 * _sgn(tr5) * abs(norm(tr5, 0.02))
        + 0.30 * _sgn(f5) * abs(norm(f5, 0.005))
        + 0.20 * _sgn(d5) * abs(norm(d5, 0.01))
    )
    t86_score = max(-1.0, min(1.0, t86_score))

    # L1 sub-weights (target): T86 0.50, concentration 0.20, broker 0.20, margin 0.10.
    # Rescale by the FILLED sub-weight fraction so the score stays comparable while
    # the remaining sub-scores are stubs (same approach the P1a fix used). Any sub-score
    # that is None is simply not filled -> fail-safe: with all None, l1 == t86_score.
    num = 0.50 * t86_score
    den = 0.50
    if concentration is not None:
        num += 0.20 * max(-1.0, min(1.0, concentration))
        den += 0.20
    if margin is not None:
        num += 0.10 * max(-1.0, min(1.0, margin))
        den += 0.10
    l1 = num / den if den else 0.0
    return round(max(-1.0, min(1.0, l1)), 3)

def compute_signal_score(l1, trend):
    score = 0
    if trend == "BULL":   score += 2
    elif trend == "MIXED+": score += 1
    elif trend == "BEAR":   score -= 2
    elif trend == "MIXED-": score -= 1
    if l1 is not None:
        if l1 >= 0.5:    score += 2
        elif l1 >= 0.15: score += 1
        elif l1 <= -0.5:  score -= 2
        elif l1 <= -0.15: score -= 1
    return max(-4, min(4, score))

def signal_label(score):
    if score >= 3:   return "Strong Bull"
    elif score >= 1: return "Bull"
    elif score == 0: return "Neutral"
    elif score >= -2: return "Bear"
    else:            return "Strong Bear"

# ============================================================================
# Chapter 6 synthesis: L2 numeric score, composite, action table.
# Each layer score is in [-1,+1]; composite is the filled-weight-rescaled
# weighted sum * 100, so range is -100..+100 regardless of which layers exist.
# ============================================================================

# Bucket weight overrides (IMPLEMENTATION_GUIDE 6.3). Inventory leans more on
# fundamentals (L3) and news (L5); watchlist leans on chip+technical entry timing.
# These are the BUILT-IN DEFAULTS; load_weights_override() lets a config file
# replace them per bucket without code changes.
WEIGHTS = {
    "T1": {"L1": 30, "L2": 25, "L3": 20, "L4": 10, "L5": 15},   # inventory
    "T2": {"L1": 35, "L2": 35, "L3": 8,  "L4": 15, "L5": 7},    # watchlist
}
_WEIGHTS_DEFAULT = {"L1": 35, "L2": 30, "L3": 10, "L4": 15, "L5": 10}
# Friendly-name -> internal tier-key mapping for config/weights.json overrides.
_BUCKET_ALIAS = {"inventory": "T1", "watchlist": "T2", "under_radar": "radar"}


def load_weights_override(path="config/weights.json"):
    """If config/weights.json exists, apply its bucket overrides on top of the
    built-in WEIGHTS dict. Mutates WEIGHTS in place so the rest of the feeder
    (compute_composite) picks up the new values without further wiring.

    File format: {"inventory": {"L1":30,...}, "watchlist": {...}, ...}. Keys
    starting with _ are treated as comments and ignored. Unknown buckets and
    unknown layer names are logged and skipped (fail-safe; the run continues
    with built-in defaults for whatever wasn't overridden)."""
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        log.info("weights override %s not present -> using built-in WEIGHTS", path)
        return
    except Exception as exc:
        log.warning("weights override %s failed to load (%s) -> using built-in", path, exc)
        return
    applied = []
    for bucket_name, layer_weights in cfg.items():
        if bucket_name.startswith("_") or not isinstance(layer_weights, dict):
            continue
        tier_key = _BUCKET_ALIAS.get(bucket_name)
        if tier_key is None:
            log.warning("weights override: unknown bucket '%s' (ignored)", bucket_name)
            continue
        merged = dict(WEIGHTS.get(tier_key, _WEIGHTS_DEFAULT))
        for layer, w in layer_weights.items():
            if layer not in ("L1", "L2", "L3", "L4", "L5"):
                log.warning("weights override [%s]: unknown layer '%s' (ignored)",
                            bucket_name, layer)
                continue
            try:
                merged[layer] = float(w)
            except Exception:
                log.warning("weights override [%s.%s]: non-numeric value %r (ignored)",
                            bucket_name, layer, w)
        WEIGHTS[tier_key] = merged
        applied.append(bucket_name)
    if applied:
        log.info("weights override applied: %s", applied)


def compute_l2_score(techs):
    """Technical layer score in [-1,+1] from trend structure + RSI + volume.
    Returns None when price history is stale/missing (so it doesn't fill a
    composite slot with a fake 0)."""
    if not techs or techs.get("trend") in (None, "STALE"):
        return None
    trend = techs.get("trend")
    base = {"BULL": 0.6, "MIXED+": 0.25, "MIXED-": -0.25, "BEAR": -0.6}.get(trend, 0.0)
    adj = 0.0
    rsi = techs.get("rsi14")
    if rsi is not None:
        if   rsi >= 80: adj -= 0.20      # blow-off overbought
        elif rsi >= 70: adj -= 0.10      # overbought
        elif rsi <= 20: adj -= 0.10      # don't reward a falling knife
        elif 45 <= rsi <= 65: adj += 0.10  # healthy momentum band
    vr = techs.get("vol_ratio")
    if vr is not None and vr >= 1.5 and base > 0:
        adj += 0.10                      # volume confirms an up-move
    return round(max(-1.0, min(1.0, base + adj)), 3)


def compute_composite(l1, l2, l3, l4, l5, bucket):
    """Filled-weight-rescaled weighted sum * 100. Layers that are None are
    excluded from both numerator and denominator, so a missing layer doesn't
    drag the score toward zero."""
    w = WEIGHTS.get(bucket, _WEIGHTS_DEFAULT)
    pairs = [(w["L1"], l1), (w["L2"], l2), (w["L3"], l3), (w["L4"], l4), (w["L5"], l5)]
    num = sum(wi * li for wi, li in pairs if li is not None)
    den = sum(wi for wi, li in pairs if li is not None)
    if den == 0:
        return None
    return round(num / den * 100, 1)


def _confluence(l1, l2):
    return (l1 is not None and l1 >= 0.4) and (l2 is not None and l2 >= 0.4)


def _sell_trigger(l1, l2, l3):
    """SELL when >=2 of {L1,L2,L3} <= -0.4, or L3 <= -0.6 alone (hard exclude)."""
    if l3 is not None and l3 <= -0.6:
        return True
    neg = sum(1 for x in (l1, l2, l3) if x is not None and x <= -0.4)
    return neg >= 2


def compute_action(composite, l1, l2, l3, bucket, veto=False):
    """Action table (IMPLEMENTATION_GUIDE 6.2). GO requires confluence AND no
    regime veto. Returns (action, confluence_bool)."""
    if composite is None:
        return ("MONITOR", False)
    conf = _confluence(l1, l2)
    sell = _sell_trigger(l1, l2, l3)
    if bucket == "T1":                        # inventory
        if sell or composite <= -40: return ("SELL", conf)
        if composite <= -20:         return ("TRIM", conf)
        if composite >= 40:          return ("ADD" if conf else "HOLD", conf)
        return ("HOLD", conf)
    # watchlist (T2)
    if sell:                                  return ("NO-GO", conf)
    if composite >= 40 and conf and not veto: return ("GO", conf)
    if composite >= 20 and conf and not veto: return ("GO half", conf)
    return ("NO-GO", conf)


# --- Chapter 12.2: action why-line + distance-to-flip -----------------------
# Compress the reasoning behind each on-screen action into a few scannable
# strings so the human doesn't have to reverse-engineer five sub-scores:
#   driver  -- the dominant L1 reason (largest-magnitude chip sub-signal)
#   confirm -- the dominant L2 reason (trend structure + volume)
#   risk    -- the highest-severity active flag, else "-"
#   flip    -- for near-boundary non-actions, the binding gap to the next state
# DISPLAY HEURISTIC ONLY: these live in score output + HTML, never in
# thresholds.json, and never feed the composite or the confluence gate (same
# wall as the Ch.10 verdict / Ch.9 ARK). See IMPLEMENTATION_GUIDE Chapter 12.2.
#
# Honesty notes (verified against the live feeder, 2026-06-13):
#  * The scored `techs` dict carries only trend / rsi14 / vol_ratio / MAs --
#    there is NO macd/kd/golden_cross field, so `confirm` is built from MA
#    structure + volume and deliberately does NOT claim "MACD>0軸 / KD低檔轉折"
#    (those would be fabricated). Add them here only once they're scored.
#  * churn (隔日沖), 季底作帳, and scheduled-event countdown are not computed
#    yet -> not surfaced in `risk`. Hooks are marked TODO below.

_GO_COMPOSITE = 40.0   # display mirror of compute_action's GO threshold
_GATE = 0.4            # display mirror of the confluence gate


def _float_pct(net, float_m):
    """Signed net shares as % of free float (float_m in MILLIONS of shares),
    or None. Independent of L1's internal cap -- this is a plain display %."""
    if net is None or not float_m or float_m <= 0:
        return None
    return net / (float_m * 1_000_000) * 100.0


def _fmt_flow(net, float_m):
    """'+1.40% float' when float is known, else '+3,000張' (lots = shares/1000)."""
    pct = _float_pct(net, float_m)
    if pct is not None:
        return f"{pct:+.2f}% float"
    lots = (net or 0) / 1000.0
    return f"{lots:+,.0f}張"


def _norm_mag(net, float_m, cap_pct):
    """Magnitude in [0,1] mirroring compute_l1_score.norm, for ranking drivers."""
    if net is None:
        return 0.0
    if float_m and float_m > 0:
        cap = float_m * 1000 * cap_pct
        return min(1.0, abs(net) / cap) if cap else 0.0
    return min(1.0, abs(net) / 10000)


def _driver_string(trust_5d, foreign_5d, float_m,
                   concentration_score, margin_score):
    """Pick the dominant L1 sub-signal and format it. Ranking mirrors the L1
    sub-weighting (trust highest-signal, then foreign, then concentration,
    then margin); ties break in that order. '' when nothing meaningful."""
    cands = []  # (magnitude, priority, label)
    if trust_5d:
        cands.append((_norm_mag(trust_5d, float_m, 0.02), 4,
                      f"投信5日 {_fmt_flow(trust_5d, float_m)}"))
    if foreign_5d:
        cands.append((_norm_mag(foreign_5d, float_m, 0.005), 3,
                      f"外資5日 {_fmt_flow(foreign_5d, float_m)}"))
    if concentration_score:
        d = "升" if concentration_score > 0 else "降"
        cands.append((abs(concentration_score), 2, f"集中度{d}"))
    if margin_score is not None and margin_score:
        if margin_score < 0:
            cands.append((abs(margin_score), 1, "融資背離"))
        elif margin_score >= 0.6:
            cands.append((abs(margin_score), 1, "融資未追高"))
    if not cands:
        return ""
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return cands[0][2]


def _confirm_string(techs):
    """Dominant L2 reason from MA structure + volume (no macd/kd available)."""
    if not techs:
        return ""
    trend = techs.get("trend")
    vr = techs.get("vol_ratio")
    vol_tag = " +量" if (vr is not None and vr >= 1.5) else ""
    if trend == "BULL":
        return "均線多頭排列" + vol_tag
    if trend == "MIXED+":
        return "站上20MA" + vol_tag
    if trend == "BEAR":
        return "均線空頭排列"
    if trend == "MIXED-":
        return "20MA之下"
    return ""  # None / STALE -> no claim


def _risk_string(l3_flags, regime_veto):
    """Highest-severity active flag, else '-'. Order: 處置股 > L4 veto > 營收旗標."""
    flags = l3_flags or []
    if any(f.get("type") == "disposition" for f in flags):
        return "處置股"
    # TODO(when scored): churn 疑似隔日沖 (broker_score), 季底作帳 (holding data),
    #                    事件{n}日內 (L5 calendar) slot in above L4 veto.
    if regime_veto:
        return "L4 veto"
    rev = [f for f in flags if f.get("type") == "revenue_yoy" and f.get("label")]
    if rev:
        worst = min(rev, key=lambda f: (f.get("value")
                                        if f.get("value") is not None else 0))
        return worst["label"]
    return "—"


def _flip_string(tier, action, composite, l1, l2, l3):
    """Distance-to-flip for near-boundary NON-actions, else ''.
    Watchlist NO-GO (composite>=30): the binding gate leg (worst of L1/L2) or
    the composite gap. Inventory HOLD/TRIM: closest leg approaching a SELL leg."""
    if tier == "T2" and action == "NO-GO" and composite is not None \
            and composite >= 30:
        legs = []
        if l1 is None or l1 < _GATE:
            legs.append(("L1", _GATE - (l1 or 0.0)))
        if l2 is None or l2 < _GATE:
            legs.append(("L2", _GATE - (l2 or 0.0)))
        if legs:                                   # gate is binding (AND-gate)
            name, gap = max(legs, key=lambda x: x[1])   # worst leg = true blocker
            return f"差 {name} +{gap:.2f}"
        if composite < _GO_COMPOSITE:
            return f"差 綜合 +{_GO_COMPOSITE - composite:.0f}"
        return ""
    if tier == "T1" and action in ("HOLD", "TRIM"):
        near = [(nm, val + _GATE) for nm, val in (("L1", l1), ("L2", l2), ("L3", l3))
                if val is not None and -_GATE < val <= -0.25]
        if near:
            name, gap = min(near, key=lambda x: x[1])   # closest to a SELL leg
            return f"SELL距 {name} −{gap:.2f}"
    return ""


def build_action_strings(*, tier, action, composite, l1, l2, l3,
                         trust_5d, foreign_5d, float_m,
                         concentration_score, margin_score,
                         techs, l3_flags, regime_veto):
    """Assemble the four 12.2 display strings for one ticker. Pure; safe to
    feed straight into the entry dict / data.json."""
    return {
        "driver":  _driver_string(trust_5d, foreign_5d, float_m,
                                  concentration_score, margin_score),
        "confirm": _confirm_string(techs),
        "risk":    _risk_string(l3_flags, regime_veto),
        "flip":    _flip_string(tier, action, composite, l1, l2, l3),
    }


# --- Chapter 12.1: signal attribution log -----------------------------------
# Append-only decision-quality log: one row per fired action and per near-miss,
# carrying the full L1-L5 vector, confluence degree, and forward 5/10/20-day
# returns backfilled idempotently on later runs. This is display/bookkeeping
# only -- it never feeds a score or the confluence gate. It exists so the
# 2026-07-28 hit-rate review can attribute outcomes per layer instead of by
# feel. See IMPLEMENTATION_GUIDE Chapter 12.1.

_SIGNAL_LOG_FIELDS = [
    "date", "ticker", "bucket", "action", "composite",
    "l1", "l2", "l3", "l4", "l5",
    "confluence_n", "near_miss", "gate_fail_reason",
    "signal_close", "fwd_5d", "fwd_10d", "fwd_20d",
]
_TIER_TO_BUCKET = {"T1": "inventory", "T2": "watchlist", "T3": "under_radar"}
_FIRED_ACTIONS = {"GO", "GO half", "SELL", "TRIM", "ADD"}
_FWD_WINDOWS = [(5, "fwd_5d"), (10, "fwd_10d"), (20, "fwd_20d")]


def _agree_count(scores, sells):
    """Layers agreeing with the action direction: >= +0.4 for buys, <= -0.4 for
    sells. None layers (unfilled, e.g. L5) don't count. Mirrors 12.6 agree_n."""
    out = 0
    for s in scores:
        if s is None:
            continue
        if (s <= -0.4) if sells else (s >= 0.4):
            out += 1
    return out


def build_agreement(l1, l2, l3, l4, l5, *, sells):
    """Chapter 12.6: confluence-degree display. Returns agree_n (layers agreeing
    with the action direction, == confluence_n from the 12.1 log) and min_gate
    (the weaker of the two gate legs L1/L2). Display-only -- never feeds the
    composite or the confluence gate."""
    agree_n = _agree_count([l1, l2, l3, l4, l5], sells)
    legs = [x for x in (l1, l2) if x is not None]
    min_gate = min(legs) if legs else None
    return {"agree_n": agree_n, "min_gate": min_gate}


def build_signal_log_row(entry, run_date):
    """Return a log row dict for `entry` if it fired an action or is a near-miss,
    else None. Pure (no I/O). `entry` is a scored T1/T2 dict from feeder.main()."""
    action    = entry.get("action")
    composite = entry.get("composite")
    tier      = entry.get("tier")
    l1 = entry.get("l1_score"); l2 = entry.get("l2_score")
    l3 = entry.get("l3_score"); l4 = entry.get("l4_score")
    l5 = None  # not folded into the composite yet (Chapter 5)

    fired = action in _FIRED_ACTIONS
    near_miss = (
        composite is not None and composite >= 30 and not fired
        and tier in ("T1", "T2")
    )
    if not (fired or near_miss):
        return None

    sells = action in ("SELL", "TRIM") or (composite is not None and composite < 0)
    agree_n = _agree_count([l1, l2, l3, l4, l5], sells)

    reason = ""
    if near_miss:
        miss = []
        if l1 is None or l1 < 0.4: miss.append("L1")
        if l2 is None or l2 < 0.4: miss.append("L2")
        reason = "+".join(miss)

    return {
        "date": run_date,
        "ticker": entry.get("ticker"),
        "bucket": _TIER_TO_BUCKET.get(tier, tier),
        "action": action,
        "composite": composite,
        "l1": l1, "l2": l2, "l3": l3, "l4": l4, "l5": l5,
        "confluence_n": agree_n,
        "near_miss": 1 if near_miss else 0,
        "gate_fail_reason": reason,
        "signal_close": entry.get("price"),
        "fwd_5d": "", "fwd_10d": "", "fwd_20d": "",
    }


def _as_date(d):
    """Normalise a history 'date' (datetime / date / str) to a date, or None."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if hasattr(d, "year") and not isinstance(d, str):  # already a date
        return d
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(d), fmt).date()
        except ValueError:
            continue
    return None


def _read_signal_log(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _empty_fwd_count(rows):
    return sum(1 for r in rows for _, c in _FWD_WINDOWS if r.get(c) in ("", None))


def _backfill_forward_returns(rows, history_cache):
    """Idempotently fill empty fwd_5d/10d/20d using each ticker's dated closes.
    Windows are counted in TRADING sessions present in history, so a cell only
    fills once that many real sessions have elapsed past the signal date."""
    for row in rows:
        if all(row.get(c) not in ("", None) for _, c in _FWD_WINDOWS):
            continue
        hist = history_cache.get(row.get("ticker"))
        sig_close = row.get("signal_close")
        if not hist or sig_close in ("", None):
            continue
        try:
            sig_close = float(sig_close)
            sig_d = datetime.strptime(row["date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if sig_close <= 0:
            continue
        future = [h for h in hist
                  if h.get("close") and _as_date(h.get("date"))
                  and _as_date(h["date"]) > sig_d]
        future.sort(key=lambda h: _as_date(h["date"]))
        for n, col in _FWD_WINDOWS:
            if row.get(col) in ("", None) and len(future) >= n:
                row[col] = round((future[n - 1]["close"] / sig_close - 1.0) * 100, 2)
    return rows


def update_signal_log(entries, history_cache, run_date,
                      path="processed/signal_log.csv"):
    """Append today's fires + near-misses (dedup on date+ticker), backfill
    forward returns, and rewrite the CSV. Stateless-CI-safe: the file is the
    only state, so the workflow must commit it. Returns (n_appended,
    n_backfilled). Never raises into the caller -- bookkeeping must not break
    the pipeline."""
    try:
        rows = _read_signal_log(path)
        seen = {(r.get("date"), r.get("ticker")) for r in rows}

        appended = 0
        for entry in entries:
            new = build_signal_log_row(entry, run_date)
            if new is None or (new["date"], new["ticker"]) in seen:
                continue
            rows.append(new)
            seen.add((new["date"], new["ticker"]))
            appended += 1

        before = _empty_fwd_count(rows)
        _backfill_forward_returns(rows, history_cache)
        filled = before - _empty_fwd_count(rows)

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_SIGNAL_LOG_FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in _SIGNAL_LOG_FIELDS})

        log.info("signal_log: +%d new, %d fwd-returns backfilled (%d rows total)",
                 appended, filled, len(rows))
        return appended, filled
    except Exception as exc:  # never let bookkeeping break the run
        log.warning("signal_log update failed (non-fatal): %s", exc)
        return 0, 0


# ---- Chapter 12.7: 今日研判 verdict scoreboard (display/bookkeeping only) ----
# Mirrors the LIVE index.html verdict heuristic. NOTE this diverges from the guide
# Ch.10.2 table (which lists 外資 weight-1 / 投信 weight-2 single bands); the shipped
# JS uses graded +/-1 / +/-2 bands for BOTH, so we mirror the JS -- it is what the
# human actually sees. The verdict never feeds the composite or the confluence gate
# (same wall as ARK Ch.9 / the Ch.10 verdict itself).
_VERDICT_LOG_FIELDS = ["date", "verdict_score", "verdict_label",
                       "verdict_dir", "taiex_chg_pct", "taiex_dir"]


def compute_verdict(market, l4_tilt_raw=None, l4_veto=False):
    """Reproduce the on-screen 今日研判 lean from the same inputs index.html uses:
    外資/投信 net (M NT$), TAIEX day %, L4 raw tilt / veto. Returns
    {score, label, dir, parts} or None when both flows are missing (matches the JS
    render guard). `dir` is +1 bull / -1 bear / 0 neutral, keyed off the same bands
    as the label. Pure, display-only -- never a score input.
    L4 caveat: this uses the L4 file present at the 19:00 run; if the human views
    pre-market after a fresher overnight L4 lands, the displayed L4 leg can differ
    on veto/boundary days (at most the +/-1 or -3 L4 contribution)."""
    fv = market.get("foreign_net_m")
    tv = market.get("trust_net_m")
    if fv is None and tv is None:
        return None
    score = 0
    parts = []
    if fv is not None:
        fv = float(fv)
        if   fv >  30000: score += 2; parts.append("外資大買")
        elif fv >      0: score += 1; parts.append("外資買超")
        elif fv < -30000: score -= 2; parts.append("外資大賣")
        elif fv <      0: score -= 1; parts.append("外資賣超")
    if tv is not None:
        tv = float(tv)
        if   tv >  3000: score += 2; parts.append("投信大買")
        elif tv >     0: score += 1; parts.append("投信買超")
        elif tv < -3000: score -= 2; parts.append("投信大賣")
        elif tv <     0: score -= 1; parts.append("投信賣超")
    tp = market.get("taiex_chg_pct")
    if tp is not None:
        try:
            tp = float(tp)
            if   tp >  1: score += 1; parts.append("TAIEX +%.1f%%" % tp)
            elif tp < -1: score -= 1; parts.append("TAIEX %.1f%%" % tp)
        except (TypeError, ValueError):
            pass
    if l4_veto:
        score -= 3; parts.append("L4 VETO")
    elif l4_tilt_raw is not None:
        if   l4_tilt_raw >=  4: score += 1; parts.append("L4 多")
        elif l4_tilt_raw <= -4: score -= 1; parts.append("L4 空")

    # Chapter 12.4 breadth leg (v1 advance-ratio). Reads market["breadth"]
    # (computed once in feeder -> logged verdict == displayed verdict). Display
    # heuristic only; same wall as the rest of the verdict.
    _bd = (market.get("breadth") or {}).get("advance_pct")
    if _bd is not None:
        if   _bd < 40: score -= 1; parts.append("廣度弱<40%")
        elif _bd > 60: score += 1; parts.append("廣度強>60%")

    if   score >=  4: label, d = "今日偏多 ✅", 1
    elif score >=  2: label, d = "今日小多 🟡", 1
    elif score <= -4: label, d = "今日偏空 ⚠️", -1
    elif score <= -2: label, d = "今日小空 🔴", -1
    else:             label, d = "今日中性 ⚪", 0
    return {"score": score, "label": label, "dir": d, "parts": parts}


def _read_verdict_log(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def compute_verdict_hitrate(rows, window=60):
    """Grade each row's verdict_dir against the NEXT row's taiex_dir (the verdict is
    a forward lean for the next session). Neutral verdicts (dir 0) make no
    directional claim and are excluded. Returns {hit_pct, graded_n} over the most
    recent `window` graded pairs, or None if nothing is gradeable yet."""
    pairs = []
    for i in range(len(rows) - 1):
        try:
            vd = int(rows[i].get("verdict_dir"))
            od = int(rows[i + 1].get("taiex_dir"))
        except (TypeError, ValueError):
            continue
        if vd == 0 or od == 0:
            continue
        pairs.append(1 if vd == od else 0)
    pairs = pairs[-window:]
    if not pairs:
        return None
    return {"hit_pct": round(100.0 * sum(pairs) / len(pairs), 1),
            "graded_n": len(pairs)}


def update_verdict_log(verdict, taiex_chg_pct, run_date,
                       path="processed/verdict_log.csv"):
    """Append today's verdict + TAIEX direction (dedup on date), rewrite the CSV,
    and return the rolling hit-rate dict (or None). Stateless-CI-safe: the file is
    the only state, so the workflow must commit it. Never raises into the caller --
    bookkeeping must not break the pipeline. Display-only; never a score input."""
    try:
        rows = _read_verdict_log(path)
        seen = {r.get("date") for r in rows}
        if verdict is not None and run_date not in seen:
            try:
                tp = float(taiex_chg_pct)
                tdir = 1 if tp > 0 else (-1 if tp < 0 else 0)
            except (TypeError, ValueError):
                tp, tdir = "", 0
            rows.append({
                "date":          run_date,
                "verdict_score": verdict["score"],
                "verdict_label": verdict["label"],
                "verdict_dir":   verdict["dir"],
                "taiex_chg_pct": tp,
                "taiex_dir":     tdir,
            })
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=_VERDICT_LOG_FIELDS)
                w.writeheader()
                for r in rows:
                    w.writerow({k: r.get(k, "") for k in _VERDICT_LOG_FIELDS})
            log.info("verdict_log: +1 row (%s dir=%+d), %d rows total",
                     run_date, verdict["dir"], len(rows))
        else:
            log.info("verdict_log: no append (have_verdict=%s dup=%s)",
                     verdict is not None, run_date in seen)
        return compute_verdict_hitrate(rows)
    except Exception as exc:  # never let bookkeeping break the run
        log.warning("verdict_log update failed (non-fatal): %s", exc)
        return None
