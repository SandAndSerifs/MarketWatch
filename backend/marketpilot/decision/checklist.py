"""The professional trade decision process (8-step checklist).

Roles:
  * Market Strategist  -> the Strategy that produced the SetupProposal.
  * Devil's Advocate   -> `challenge()`: deterministic objections + falsifiers ("what would prove it wrong").
  * Quantitative Analyst -> `quant_view()`: is there measurable evidence this strategy version has an edge?
  * Risk Manager       -> `RiskManager.evaluate_entry()`: independent veto.

The resulting record is stored verbatim (Decision.record) and is the ONLY source
the AI may use to explain a trade afterwards.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data import calendar as cal
from ..data.models import DataQuality, NewsItem
from ..data.universe import sector_of
from ..db import BacktestRun, Trade
from ..risk.manager import RiskConfig, RiskVerdict, earnings_within
from ..strategies.base import SetupProposal, Strategy, StrategyContext

CATEGORIES = ("BUY_CANDIDATE", "SELL_EXIT_CANDIDATE", "WATCH", "HOLD_MANAGE", "NO_TRADE")

# Risk rules that depend on *when* we look, not on the setup itself. A setup that only
# fails these is valid but must wait; they are re-checked at trigger time.
TIMING_RULES = {"regular_session", "not_first_minutes", "not_last_minutes", "macro_blackout", "fresh_data"}

_NEG_NEWS = re.compile(
    r"\b(downgrad\w*|miss(es|ed)?|cuts? (guidance|outlook)|lower(s|ed)? guidance|probe|investigation|subpoena|"
    r"lawsuit|recall|fraud|bankrupt\w*|delist\w*|SEC charges|halt(ed)?|offering|dilut\w*|resign\w*)\b", re.I)


def challenge(ctx: StrategyContext, p: SetupProposal, risk_cfg: RiskConfig, quality: DataQuality | None,
              news: list[NewsItem] | None = None, held_symbols: list[str] | None = None,
              quant: dict[str, Any] | None = None) -> dict[str, Any]:
    """Argue against the trade. Returns objections with severity and explicit falsifiers."""
    t, reg = ctx.tech, ctx.regime
    obj: list[dict[str, str]] = []

    def add(sev: str, issue: str, detail: str) -> None:
        obj.append({"severity": sev, "issue": issue, "detail": detail})

    label = reg.get("label")
    if label == "risk_off":
        add("serious", "Market headwind", "SPY is below its 50- and 200-day averages. Long setups fail more often when the broad market trends down.")
    elif label == "high_volatility":
        add("serious", "High-volatility regime", f"SPY 20-day realized vol {reg.get('realized_vol20')}%: gaps through stops and false signals are more common.")
    elif label == "neutral":
        add("caution", "Mixed market", "Broad trend is not clearly up; follow-through is less reliable.")
    sec = sector_of(ctx.symbol)
    if sec and reg.get("sectors"):
        row = next((s for s in reg["sectors"] if s["symbol"] == sec), None)
        if row and row["rank"] > len(reg["sectors"]) - 3:
            add("caution", "Weak sector", f"{sec} ranks {row['rank']}/{len(reg['sectors'])} on 20-day relative strength vs SPY.")
    ext = t.get("extension_atr_from_sma50")
    if ext is not None and ext > 3.5:
        add("caution", "Extended", f"Price is {ext:.1f} ATRs above the 50-day SMA; late entries risk a mean-reversion pullback.")
    if t.get("rsi14") and t["rsi14"] > 75:
        add("caution", "Overbought", f"RSI(14) {t['rsi14']:.0f}: momentum may be exhausted short-term.")
    risk = p.risk_per_share
    res = [lv["price"] for lv in t.get("resistance", []) if lv["price"] > p.entry_price]
    if res and risk > 0:
        nearest = min(res)
        if nearest < p.entry_price + risk:
            add("serious", "Overhead resistance", f"Resistance at {nearest:.2f} is less than 1R above entry ({p.entry_price:.2f}); upside may be capped quickly.")
        elif p.target and nearest < p.target:
            add("caution", "Resistance before target", f"Resistance at {nearest:.2f} lies between entry and target {p.target:.2f}.")
    rr = p.reward_risk
    if rr is not None and rr < risk_cfg.min_reward_risk:
        add("serious", "Poor reward:risk", f"Reward:risk {rr:.2f} is below the {risk_cfg.min_reward_risk:.2f} minimum.")
    if t.get("atr_pct") and t["atr_pct"] > 5:
        add("caution", "Volatile stock", f"ATR is {t['atr_pct']:.1f}% of price; normal noise can hit the stop.")
    if t.get("change_pct") is not None and t.get("atr_pct") and abs(t["change_pct"]) > 2 * t["atr_pct"]:
        add("caution", "Outsized last move", f"Last session moved {t['change_pct']:.1f}% (>2 ATR); possible news-driven move or exhaustion.")
    if t.get("avg_dollar_volume20") is not None and t["avg_dollar_volume20"] < risk_cfg.min_avg_dollar_volume:
        add("blocking", "Illiquid", f"Average dollar volume ${t['avg_dollar_volume20']/1e6:.1f}M is below the ${risk_cfg.min_avg_dollar_volume/1e6:.0f}M minimum.")
    if p.holding == "swing":
        ev = earnings_within(ctx.events, ctx.symbol, ctx.as_of, risk_cfg.earnings_blackout_days)
        if ev:
            add("blocking", "Earnings ahead", f"Earnings on {ev['date']} ({ev.get('time_et') or 'time n/a'}): overnight gap risk is not controlled by a stop.")
        elif not any(e.get("kind") == "earnings" and e.get("symbol") == ctx.symbol for e in ctx.events):
            add("caution", "Earnings date unverified", "No earnings date on file for this symbol; an unseen report could gap the stock.")
    for ev in ctx.events:
        if ev.get("kind") == "macro" and ev.get("importance") == "high":
            d = datetime.fromisoformat(ev["date"]).date()
            today = cal.et_date(ctx.as_of)
            if today <= d <= today + timedelta(days=3):
                add("caution", "Macro event", f"{ev['name']} on {ev['date']} {ev.get('time_et') or ''} ET can move the whole market.")
    if news:
        recent = [n for n in news if n.created_at >= ctx.as_of - timedelta(days=3) and _NEG_NEWS.search(n.headline)]
        if recent:
            add("caution", "Negative headlines (keyword heuristic)",
                "Recent headlines contain risk keywords: " + "; ".join(n.headline[:90] for n in recent[:3]))
    if held_symbols and sec:
        same = [s for s in held_symbols if sector_of(s) == sec]
        if same:
            add("caution", "Correlated exposure", f"Already exposed to {sec} via {', '.join(same)}; positions would move together.")
    if quality is not None and quality.feed == "iex":
        add("info", "Partial live feed", "Live prices are IEX-only; quotes and intraday volume do not reflect the full market.")
    if quality is not None and not quality.realtime:
        add("caution", "Delayed data", f"Live data is delayed {quality.delay_minutes} minutes; entries will be filled at stale levels.")
    if quant:
        if quant["status"] == "unproven":
            add("caution", "Unproven strategy", "No out-of-sample backtest evidence on file for this strategy version.")
        elif quant["status"] == "negative":
            add("serious", "Negative evidence", "Out-of-sample results for this strategy version show no edge (profit factor < 0.9).")
        elif quant["status"] == "weak":
            add("caution", "Weak evidence", quant.get("note", "Evidence for an edge is inconclusive."))
    for c in p.conflicting:
        add("caution", "Strategy caveat", c)

    falsifiers = list(p.invalidation)
    if label in ("risk_on", "neutral"):
        falsifiers.append("SPY closes below its 50-day average (market regime deteriorates)")
    return {"objections": obj, "what_would_prove_it_wrong": falsifiers,
            "counts": {s: sum(1 for o in obj if o["severity"] == s) for s in ("blocking", "serious", "caution", "info")}}


def quant_view(s: Session, strategy_key: str, version: str) -> dict[str, Any]:
    """Quantitative Analyst: summarise measurable evidence for this exact strategy version."""
    bt = s.execute(select(BacktestRun).where(BacktestRun.strategy_key == strategy_key,
                                             BacktestRun.strategy_version == version,
                                             BacktestRun.status == "complete",
                                             BacktestRun.scenario.is_(None))
                   .order_by(BacktestRun.id.desc())).scalars().first()
    trades = s.execute(select(Trade).where(Trade.strategy_key == strategy_key, Trade.strategy_version == version,
                                           Trade.status == "closed")).scalars().all()
    forward: dict[str, Any] = {"closed_trades": len(trades)}
    if trades:
        rs = [t.r_multiple for t in trades if t.r_multiple is not None]
        wins = [t for t in trades if (t.net_pnl or 0) > 0]
        forward.update({"win_rate": round(len(wins) / len(trades) * 100, 1),
                        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None})
    out: dict[str, Any] = {"strategy": strategy_key, "version": version, "forward_paper": forward}
    if bt is None:
        out.update(status="unproven", note="No backtest on file for this version.")
        return out
    test = (bt.segments or {}).get("test") or {}
    out["backtest"] = {"run_id": bt.id, "period": f"{bt.start}..{bt.end}", "out_of_sample": test}
    n, pf, exp = test.get("trades", 0), test.get("profit_factor"), test.get("expectancy_r")
    if n < 30:
        out.update(status="weak", note=f"Only {n} out-of-sample trades; too few to distinguish skill from luck.")
    elif pf is not None and pf < 0.9:
        out.update(status="negative", note=f"Out-of-sample profit factor {pf:.2f} over {n} trades.")
    elif pf is not None and pf >= 1.2 and (exp or 0) > 0:
        out.update(status="supported", note=f"Out-of-sample profit factor {pf:.2f}, expectancy {exp:.2f}R over {n} trades. Past results do not guarantee future results.")
    else:
        out.update(status="weak", note=f"Out-of-sample profit factor {pf} over {n} trades: inconclusive.")
    return out


def classify(objections: dict[str, Any], verdict: RiskVerdict | None) -> tuple[str, str, list[str]]:
    counts = objections["counts"]
    timing: list[str] = []
    structural: list[str] = []
    if verdict is not None:
        for ch in verdict.checks:
            if ch.blocking and not ch.passed:
                (timing if ch.rule in TIMING_RULES else structural).append(f"{ch.rule}: {ch.detail}")
    if counts["blocking"]:
        return "NO_TRADE", "Blocking objection(s) raised by the challenge step.", timing
    if structural:
        return "NO_TRADE", "Risk Manager rejected the setup: " + "; ".join(structural), timing
    if counts["serious"] >= 2:
        return "WATCH", f"{counts['serious']} serious objections: monitor only, no entry.", timing
    if timing:
        return "BUY_CANDIDATE", "Setup passes structural checks; entry is conditional on timing gates at trigger.", timing
    return "BUY_CANDIDATE", "Setup passes the challenge step and the Risk Manager.", timing


def build_decision(ctx: StrategyContext, strategy: Strategy, p: SetupProposal, risk_cfg: RiskConfig,
                   verdict: RiskVerdict | None, quality: DataQuality | None, quant: dict[str, Any] | None,
                   news: list[NewsItem] | None = None, held_symbols: list[str] | None = None,
                   price: float | None = None, price_ts: datetime | None = None) -> dict[str, Any]:
    t, reg = ctx.tech, ctx.regime
    ch = challenge(ctx, p, risk_cfg, quality, news, held_symbols, quant)
    category, rationale, timing = classify(ch, verdict)
    sec = sector_of(ctx.symbol)
    sector_row = next((x for x in reg.get("sectors", []) if x["symbol"] == sec), None) if sec else None
    tech_keys = ("close", "change_pct", "sma20", "sma50", "sma200", "ema20", "rsi14", "rsi2", "macd", "macd_signal",
                 "macd_hist", "bb_upper", "bb_lower", "pct_b", "atr14", "atr_pct", "adx14", "rvol20", "roc20", "roc126",
                 "high20_prior", "high252", "pct_from_52w_high", "extension_atr_from_sma50", "trend", "support", "resistance")
    return {
        "schema": 1,
        "symbol": ctx.symbol,
        "evaluated_at": ctx.as_of.isoformat(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "quality": quality.to_dict() if quality else None,
            "verified_price": price, "price_ts": price_ts.isoformat() if price_ts else None,
            "daily_bars_through": t.get("as_of"), "bars_used": t.get("bars"),
        },
        "strategy": {"key": strategy.key, "name": strategy.name, "version": strategy.version, "params": strategy.params,
                     "style": strategy.style, "knowledge_refs": list(strategy.knowledge_refs)},
        "steps": {
            "1_market_conditions": {
                "regime": {k: reg.get(k) for k in ("label", "description", "spy_close", "spy_above_50", "spy_above_200",
                                                     "realized_vol20", "drawdown_from_52w_high_pct")},
                "sector": sector_row, "upcoming_events": ctx.events[:10],
            },
            "2_stock_analysis": {
                "technicals": {k: t.get(k) for k in tech_keys},
                "liquidity": {"avg_dollar_volume20": t.get("avg_dollar_volume20"),
                              "spread_bps": ctx.snapshot.spread_bps if ctx.snapshot else None},
                "news": [n.to_dict() for n in (news or [])[:5]],
            },
            "3_thesis": {"thesis": p.thesis, "strategy_description": strategy.description},
            "4_evidence": {"supporting": p.evidence},
            "5_challenge": {**ch, "ai_critique": None},
            "6_risk": {
                "entry_type": p.entry_type, "entry": p.entry_price, "stop": p.stop, "target": p.target,
                "risk_per_share": round(p.risk_per_share, 4),
                "reward_risk": round(p.reward_risk, 2) if p.reward_risk is not None else None,
                "time_stop_days": p.time_stop_days, "valid_days": p.valid_days, "holding": p.holding,
                "verdict": verdict.to_dict() if verdict else None,
            },
            "7_decision": {"category": category, "rationale": rationale, "timing_gates": timing,
                           "approved_for_paper": category == "BUY_CANDIDATE"},
            "8_post_trade": None,
        },
        "roles": {
            "market_strategist": f"{strategy.name} v{strategy.version}",
            "quant_analyst": quant,
            "risk_manager": {"approved": verdict.approved if verdict else None,
                             "rejections": verdict.reasons if verdict else []},
        },
    }


def summarize(record: dict[str, Any]) -> str:
    """Plain-English one-paragraph summary used in alerts."""
    st = record["steps"]
    r = st["6_risk"]
    dec = st["7_decision"]
    obj = st["5_challenge"]["objections"]
    top = [o for o in obj if o["severity"] in ("blocking", "serious")][:2] or [o for o in obj if o["severity"] == "caution"][:2]
    rr = f"{r['reward_risk']:.1f}" if r.get("reward_risk") is not None else "n/a"
    text = (f"{dec['category'].replace('_', ' ')} {record['symbol']} ({record['strategy']['name']}). "
            f"{st['3_thesis']['thesis']} Plan: {r['entry_type'].replace('_', ' ')} at {r['entry']:.2f}, "
            f"stop {r['stop']:.2f}, target {r['target']:.2f} (R:R {rr}).") if r.get("target") else \
        f"{dec['category']} {record['symbol']}: {st['3_thesis']['thesis']}"
    if top:
        text += " Main risks: " + "; ".join(f"{o['issue']} - {o['detail']}" for o in top)
    return text
