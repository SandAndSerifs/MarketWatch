"""Built-in, rule-based strategies.

All are long-only and evaluated on *completed* daily bars, except VWAP Reclaim
which uses intraday bars and is flat by the close. Thresholds are deliberately
conventional (taken from widely published definitions) rather than optimised,
to limit overfitting; any change creates a new strategy version.
"""
from __future__ import annotations

import operator
from typing import Any

import numpy as np

from ..analysis import indicators as ind
from .base import ExitInstruction, ParamSpec, SetupProposal, Strategy, StrategyContext, TradeView


def _need(t: dict[str, Any], *keys: str) -> bool:
    return t.get("ok", False) and all(t.get(k) is not None for k in keys)


def _nearest_resistance(t: dict[str, Any], above: float) -> float | None:
    levels = [lv["price"] for lv in t.get("resistance", []) if lv["price"] > above]
    return min(levels) if levels else None


class TrendPullback(Strategy):
    """MarketPilot's proposed initial strategy (see docs/STRATEGY.md)."""

    key = "trend_pullback"
    name = "Trend Pullback"
    version = "1.0.0"
    style = "Trend following / buy-the-dip in established uptrends"
    description = (
        "Buys a short-term pullback inside an established uptrend (price > rising 50-day > 200-day) once the "
        "pullback shows signs of ending (price takes out the prior day's high). Stop below the pullback low, "
        "target 2R, breakeven after +1R, 10-session time stop, exit if the close loses the 50-day average."
    )
    param_specs = (
        ParamSpec("rsi2_max", 15.0, 1, 40, "RSI(2) must be at or below this to qualify as a pullback"),
        ParamSpec("max_dist_ema20_atr", 1.0, 0.2, 3, "Or: close within this many ATRs of the 20-day EMA"),
        ParamSpec("min_adx", 15.0, 0, 40, "Minimum ADX(14) trend strength"),
        ParamSpec("stop_atr_cap", 2.5, 1, 5, "Maximum stop distance in ATRs"),
        ParamSpec("target_r", 2.0, 1, 5, "Profit target as a multiple of initial risk"),
        ParamSpec("time_stop_days", 10, 2, 40, "Exit after this many sessions"),
    )
    knowledge_refs = ("trend-following", "pullbacks-in-trends", "atr-stops", "position-sizing-fixed-fractional")

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        t = ctx.tech
        if not _need(t, "sma50", "sma200", "ema20", "atr14", "rsi2", "adx14"):
            return None
        close, atr = t["close"], t["atr14"]
        if not (t["trend"] == "uptrend" and close > t["sma50"] > t["sma200"]):
            return None
        if t["adx14"] < self.p("min_adx"):
            return None
        near_ema = abs(close - t["ema20"]) <= self.p("max_dist_ema20_atr") * atr
        if not (t["rsi2"] <= self.p("rsi2_max") or (near_ema and t["change_pct"] < 0)):
            return None
        trigger = round(t["high"] + 0.05 * atr, 2)
        structural = t["low5"] - 0.1 * atr
        stop = round(max(structural, trigger - self.p("stop_atr_cap") * atr), 2)
        if stop >= trigger:
            return None
        r = trigger - stop
        target = round(trigger + self.p("target_r") * r, 2)
        evidence = [
            f"Uptrend: close {close:.2f} > 50-day SMA {t['sma50']:.2f} > 200-day SMA {t['sma200']:.2f}",
            f"Trend strength ADX(14) = {t['adx14']:.1f} (min {self.p('min_adx'):.0f})",
            f"Pullback: RSI(2) = {t['rsi2']:.1f}" + (f", close within {abs(close - t['ema20']) / atr:.2f} ATR of 20-day EMA" if near_ema else ""),
            f"Entry only if price trades above {trigger:.2f} (prior high + 0.05 ATR), confirming buyers stepped back in",
        ]
        conflicting = []
        res = _nearest_resistance(t, trigger)
        if res and res < target:
            conflicting.append(f"Resistance near {res:.2f} sits below the 2R target {target:.2f}")
        return SetupProposal(
            ctx.symbol, self.key, self.version,
            thesis=(f"{ctx.symbol} is in an established uptrend and has pulled back. Historically, pullbacks inside "
                    "strong trends resolve in the direction of the trend more often than they reverse it; a move above "
                    "the prior day's high is the confirmation that the dip is being bought."),
            evidence=evidence, entry_type="buy_stop", entry_price=trigger, stop=stop, target=target,
            invalidation=[
                f"Price trades below {stop:.2f} (pullback low minus buffer): the pullback has become a reversal",
                f"A daily close below the 50-day SMA ({t['sma50']:.2f}) breaks the uptrend premise",
                f"No trigger above {trigger:.2f} within 2 sessions: setup expires",
                f"No progress within {self.p('time_stop_days')} sessions: momentum thesis not playing out",
            ],
            time_stop_days=int(self.p("time_stop_days")), conflicting=conflicting,
            metrics={"rsi2": t["rsi2"], "adx14": t["adx14"], "atr14": atr},
        )

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        t = ctx.tech
        if t.get("ok") and t.get("sma50") and t["close"] < t["sma50"]:
            return ExitInstruction(f"Thesis broken: daily close {t['close']:.2f} below 50-day SMA {t['sma50']:.2f}",
                                   "thesis_broken")
        return super().manage(ctx, trade)


class Breakout(Strategy):
    key = "breakout"
    name = "Volatility-Contraction Breakout"
    version = "1.0.0"
    style = "Breakout"
    description = ("Arms a buy-stop just above the prior 20-day high when the stock is in an uptrend, close to "
                   "the high, and Bollinger Band width is contracted (quiet before expansion). Stop 2 ATR, target "
                   "2.5R, trail exit on a close below the prior 10-day low.")
    param_specs = (
        ParamSpec("max_pct_below_high", 3.0, 0.5, 10, "Close must be within this % of the 20-day high"),
        ParamSpec("max_width_pctile", 40.0, 5, 100, "Bollinger width percentile (lower = tighter)"),
        ParamSpec("stop_atr", 2.0, 1, 4, "Stop distance in ATRs"),
        ParamSpec("target_r", 2.5, 1, 6, "Target in R"),
        ParamSpec("time_stop_days", 15, 3, 60, "Time stop"),
    )
    knowledge_refs = ("breakouts", "volatility-contraction", "failed-breakouts")

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        t = ctx.tech
        if not _need(t, "high20_prior", "atr14", "sma50", "bb_width_pctile"):
            return None
        close, atr, hi = t["close"], t["atr14"], t["high20_prior"]
        if close <= t["sma50"] or close > hi:
            return None
        if (hi - close) / hi * 100 > self.p("max_pct_below_high"):
            return None
        if t["bb_width_pctile"] > self.p("max_width_pctile"):
            return None
        trigger = round(hi + 0.05 * atr, 2)
        stop = round(trigger - self.p("stop_atr") * atr, 2)
        target = round(trigger + self.p("target_r") * (trigger - stop), 2)
        conflicting = []
        if t.get("rvol20") is not None and t["rvol20"] < 0.8:
            conflicting.append(f"Volume is light (RVOL {t['rvol20']:.2f}); breakouts on low volume fail more often")
        return SetupProposal(
            ctx.symbol, self.key, self.version,
            thesis=(f"{ctx.symbol} is coiling just under its 20-day high with contracted volatility. A push through the "
                    "high on expanding volume often starts a new leg as trapped sellers cover and breakout buyers enter."),
            evidence=[f"Close {close:.2f} is {(hi - close) / hi * 100:.1f}% below the prior 20-day high {hi:.2f}",
                      f"Bollinger width at the {t['bb_width_pctile']:.0f}th percentile of the last 120 sessions",
                      f"Above the 50-day SMA {t['sma50']:.2f}"],
            entry_type="buy_stop", entry_price=trigger, stop=stop, target=target,
            invalidation=[f"Price back below {stop:.2f} after entry: failed breakout",
                          f"Breakout reverses and closes back under {hi:.2f} on the trigger day: bull trap risk",
                          "A daily close below the prior 10-day low ends the trend leg"],
            time_stop_days=int(self.p("time_stop_days")), conflicting=conflicting,
            metrics={"bb_width_pctile": t["bb_width_pctile"], "rvol20": t.get("rvol20")},
        )

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        t = ctx.tech
        if t.get("ok") and t.get("low10_prior") and t["close"] < t["low10_prior"] and trade.sessions_held >= 2:
            return ExitInstruction(f"Trailing exit: close {t['close']:.2f} below prior 10-day low {t['low10_prior']:.2f}", "trail")
        return super().manage(ctx, trade)


class MeanReversionRSI2(Strategy):
    key = "mean_reversion"
    name = "RSI(2) Mean Reversion"
    version = "1.0.0"
    style = "Mean reversion"
    description = ("Buys sharp short-term oversold readings (RSI(2) very low) in stocks above their 200-day average, "
                   "with a limit order near the prior close. Exits on a close above the 5-day SMA, a 2.5 ATR stop, or "
                   "after 5 sessions. Low reward:risk by design; relies on a high hit rate, which must be verified.")
    param_specs = (
        ParamSpec("rsi2_max", 5.0, 1, 20, "Entry threshold for RSI(2)"),
        ParamSpec("stop_atr", 2.5, 1, 5, "Stop distance in ATRs"),
        ParamSpec("time_stop_days", 5, 2, 15, "Time stop"),
    )
    knowledge_refs = ("mean-reversion", "short-term-reversal-evidence")

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        t = ctx.tech
        if not _need(t, "sma200", "rsi2", "atr14", "sma20"):
            return None
        close, atr = t["close"], t["atr14"]
        if close <= t["sma200"] or t["rsi2"] > self.p("rsi2_max"):
            return None
        entry = round(close, 2)
        stop = round(entry - self.p("stop_atr") * atr, 2)
        target = round(max(t["sma20"], entry + 0.5 * atr), 2)
        return SetupProposal(
            ctx.symbol, self.key, self.version,
            thesis=(f"{ctx.symbol} has sold off hard over a few sessions while its long-term trend is intact. Short-term "
                    "extremes in liquid stocks have tended to partially revert within days (short-term reversal effect)."),
            evidence=[f"RSI(2) = {t['rsi2']:.1f} (threshold {self.p('rsi2_max'):.0f})",
                      f"Long-term uptrend intact: close {close:.2f} > 200-day SMA {t['sma200']:.2f}"],
            entry_type="limit", entry_price=entry, stop=stop, target=target,
            invalidation=[f"Price below {stop:.2f}: the selloff is a trend change, not a dip",
                          "Selling is news-driven (earnings miss, guidance cut, downgrade): reversion edge does not apply",
                          f"No bounce within {self.p('time_stop_days')} sessions"],
            time_stop_days=int(self.p("time_stop_days")),
            conflicting=["Strategy has an intentionally low reward:risk; it depends on a high win rate"],
            metrics={"rsi2": t["rsi2"]},
        )

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        if len(ctx.bars) >= 5:
            sma5 = float(np.mean([b.c for b in ctx.bars[-5:]]))
            if ctx.bars[-1].c > sma5 and trade.sessions_held >= 1:
                return ExitInstruction(f"Reversion complete: close {ctx.bars[-1].c:.2f} above 5-day SMA {sma5:.2f}", "target")
        if trade.max_hold_days and trade.sessions_held >= trade.max_hold_days:
            return ExitInstruction(f"Time stop after {trade.sessions_held} sessions", "time_stop")
        return None


class Momentum(Strategy):
    key = "momentum"
    name = "Relative Momentum"
    version = "1.0.0"
    style = "Momentum"
    description = ("Buys stocks with strong 6-month momentum that are still in a healthy (not overbought) state with "
                   "positive MACD histogram. Entry above the prior high, 2 ATR stop, 3R target, trail with the 20-day EMA.")
    param_specs = (
        ParamSpec("min_roc126", 15.0, 0, 100, "Minimum 126-day rate of change %"),
        ParamSpec("rsi_min", 50.0, 30, 70, "RSI(14) lower bound"),
        ParamSpec("rsi_max", 72.0, 55, 90, "RSI(14) upper bound (avoid chasing)"),
        ParamSpec("stop_atr", 2.0, 1, 4, "Stop in ATRs"),
        ParamSpec("target_r", 3.0, 1, 6, "Target in R"),
        ParamSpec("time_stop_days", 20, 5, 60, "Time stop"),
    )
    knowledge_refs = ("momentum-evidence", "trend-following")

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        t = ctx.tech
        if not _need(t, "roc126", "rsi14", "macd_hist", "sma50", "atr14", "ema20"):
            return None
        if t["roc126"] < self.p("min_roc126") or not (self.p("rsi_min") <= t["rsi14"] <= self.p("rsi_max")):
            return None
        if t["macd_hist"] <= 0 or t["close"] < t["sma50"] or t["close"] < t["ema20"]:
            return None
        atr = t["atr14"]
        trigger = round(t["high"] + 0.05 * atr, 2)
        stop = round(trigger - self.p("stop_atr") * atr, 2)
        target = round(trigger + self.p("target_r") * (trigger - stop), 2)
        conflicting = []
        if t.get("extension_atr_from_sma50") and t["extension_atr_from_sma50"] > 4:
            conflicting.append(f"Extended {t['extension_atr_from_sma50']:.1f} ATR above the 50-day SMA")
        return SetupProposal(
            ctx.symbol, self.key, self.version,
            thesis=(f"{ctx.symbol} has strong intermediate-term momentum. Past winners have tended to keep outperforming "
                    "over the following months (momentum effect), especially when the trend is orderly rather than parabolic."),
            evidence=[f"126-day return {t['roc126']:.1f}% (min {self.p('min_roc126'):.0f}%)",
                      f"RSI(14) {t['rsi14']:.1f} in the healthy {self.p('rsi_min'):.0f}-{self.p('rsi_max'):.0f} band",
                      f"MACD histogram positive ({t['macd_hist']:.3f})", "Price above 20-day EMA and 50-day SMA"],
            entry_type="buy_stop", entry_price=trigger, stop=stop, target=target,
            invalidation=[f"Price below {stop:.2f}", "Daily close below the 20-day EMA after the first 3 sessions",
                          "Momentum crash conditions: broad market in high-volatility selloff"],
            time_stop_days=int(self.p("time_stop_days")), conflicting=conflicting,
            metrics={"roc126": t["roc126"], "rsi14": t["rsi14"]},
        )

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        t = ctx.tech
        if t.get("ok") and t.get("ema20") and t["close"] < t["ema20"] and trade.sessions_held >= 3:
            return ExitInstruction(f"Trailing exit: close {t['close']:.2f} below 20-day EMA {t['ema20']:.2f}", "trail")
        return super().manage(ctx, trade)


class MACrossover(Strategy):
    key = "ma_crossover"
    name = "20/50 Moving-Average Crossover"
    version = "1.0.0"
    style = "Trend following"
    description = "Enters when the 20-day SMA crosses above the 50-day SMA with price above the 200-day; exits on the reverse cross."
    param_specs = (ParamSpec("stop_atr", 2.5, 1, 5, "Stop in ATRs"), ParamSpec("target_r", 3.0, 1, 8, "Target in R"),
                   ParamSpec("time_stop_days", 40, 5, 120, "Time stop"))
    knowledge_refs = ("moving-averages", "trend-following")

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        t = ctx.tech
        if not _need(t, "sma20", "sma50", "sma200", "atr14") or not t.get("sma20_cross_up_sma50"):
            return None
        if t["close"] < t["sma200"]:
            return None
        atr = t["atr14"]
        trigger = round(t["high"] + 0.05 * atr, 2)
        stop = round(trigger - self.p("stop_atr") * atr, 2)
        target = round(trigger + self.p("target_r") * (trigger - stop), 2)
        return SetupProposal(
            ctx.symbol, self.key, self.version,
            thesis=f"The 20-day average crossed above the 50-day for {ctx.symbol}, signalling a possible new intermediate uptrend.",
            evidence=[f"20-day SMA {t['sma20']:.2f} crossed above 50-day SMA {t['sma50']:.2f} on the last bar",
                      f"Price above the 200-day SMA {t['sma200']:.2f}"],
            entry_type="buy_stop", entry_price=trigger, stop=stop, target=target,
            invalidation=[f"Price below {stop:.2f}", "20-day SMA crosses back below the 50-day (whipsaw)"],
            time_stop_days=int(self.p("time_stop_days")),
            conflicting=["Crossovers lag price and whipsaw in sideways markets"],
        )

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        if ctx.tech.get("sma20_cross_down_sma50"):
            return ExitInstruction("Exit signal: 20-day SMA crossed below 50-day SMA", "thesis_broken")
        return super().manage(ctx, trade)


class MACDCross(Strategy):
    key = "macd"
    name = "MACD Signal Cross"
    version = "1.0.0"
    style = "Momentum"
    description = "Enters on a MACD line cross above its signal line while price is above the 200-day SMA; exits on the reverse cross."
    param_specs = (ParamSpec("stop_atr", 2.0, 1, 5, "Stop in ATRs"), ParamSpec("target_r", 2.0, 1, 6, "Target in R"),
                   ParamSpec("time_stop_days", 20, 3, 60, "Time stop"))
    knowledge_refs = ("macd", "momentum-evidence")

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        t = ctx.tech
        if not _need(t, "macd", "macd_signal", "sma200", "atr14") or not t.get("macd_cross_up"):
            return None
        if t["close"] < t["sma200"]:
            return None
        atr = t["atr14"]
        trigger = round(t["high"] + 0.05 * atr, 2)
        stop = round(trigger - self.p("stop_atr") * atr, 2)
        target = round(trigger + self.p("target_r") * (trigger - stop), 2)
        return SetupProposal(
            ctx.symbol, self.key, self.version,
            thesis=f"Short-term momentum in {ctx.symbol} is turning up (MACD bullish cross) within a long-term uptrend.",
            evidence=[f"MACD {t['macd']:.3f} crossed above signal {t['macd_signal']:.3f}",
                      f"Close above 200-day SMA {t['sma200']:.2f}"],
            entry_type="buy_stop", entry_price=trigger, stop=stop, target=target,
            invalidation=[f"Price below {stop:.2f}", "MACD crosses back below its signal line"],
            time_stop_days=int(self.p("time_stop_days")),
        )

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        if ctx.tech.get("macd_cross_down"):
            return ExitInstruction("Exit signal: MACD crossed below its signal line", "thesis_broken")
        return super().manage(ctx, trade)


class RSIRecovery(Strategy):
    key = "rsi"
    name = "RSI(14) Oversold Recovery"
    version = "1.0.0"
    style = "Mean reversion"
    description = "Enters when RSI(14) crosses back above 30 from oversold while price remains above the 200-day SMA."
    param_specs = (ParamSpec("level", 30.0, 10, 45, "Oversold level"), ParamSpec("stop_atr", 2.0, 1, 5, "Stop in ATRs"),
                   ParamSpec("target_r", 2.0, 1, 6, "Target in R"), ParamSpec("time_stop_days", 10, 3, 40, "Time stop"))
    knowledge_refs = ("rsi", "mean-reversion")

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        t = ctx.tech
        if not _need(t, "rsi14", "rsi14_prev", "sma200", "atr14"):
            return None
        lvl = self.p("level")
        if not (t["rsi14_prev"] < lvl <= t["rsi14"]) or t["close"] < t["sma200"]:
            return None
        atr = t["atr14"]
        trigger = round(t["high"] + 0.05 * atr, 2)
        stop = round(min(t["low5"] - 0.1 * atr, trigger - self.p("stop_atr") * atr), 2)
        target = round(trigger + self.p("target_r") * (trigger - stop), 2)
        return SetupProposal(
            ctx.symbol, self.key, self.version,
            thesis=f"{ctx.symbol} is recovering from an oversold reading while the long-term trend is still up.",
            evidence=[f"RSI(14) crossed up through {lvl:.0f} ({t['rsi14_prev']:.1f} -> {t['rsi14']:.1f})",
                      f"Close above 200-day SMA {t['sma200']:.2f}"],
            entry_type="buy_stop", entry_price=trigger, stop=stop, target=target,
            invalidation=[f"Price below {stop:.2f} (new low)", "RSI falls back under the oversold level"],
            time_stop_days=int(self.p("time_stop_days")),
        )


class VWAPReclaim(Strategy):
    key = "vwap_reclaim"
    name = "Intraday VWAP Reclaim"
    version = "1.0.0"
    style = "Intraday"
    description = ("Intraday only: after 10:00 ET, buys when a stock in a daily uptrend reclaims session VWAP on a "
                   "5-minute close. Stop at the session low, 2R target, flat by 15:50 ET. Forward-test only.")
    timeframe = "5Min"
    holding = "intraday"
    backtestable = False
    param_specs = (ParamSpec("target_r", 2.0, 1, 5, "Target in R"), ParamSpec("max_stop_atr", 1.0, 0.2, 3, "Max stop in daily ATRs"))
    knowledge_refs = ("vwap", "intraday-trading-risks")

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        bars, t = ctx.intraday or [], ctx.tech
        if len(bars) < 8 or not _need(t, "sma50", "atr14") or t["close"] < t["sma50"]:
            return None
        from ..data.calendar import et_date, to_et

        day = et_date(bars[-1].t)
        today = [b for b in bars if et_date(b.t) == day]
        if len(today) < 7 or to_et(today[-1].t).hour < 10:
            return None
        vw = ind.session_vwap([b.t for b in today], [b.h for b in today], [b.l for b in today],
                              [b.c for b in today], [b.v for b in today])
        if not (today[-2].c < vw[-2] and today[-1].c > vw[-1]):
            return None
        low = min(b.l for b in today)
        entry = round(today[-1].c, 2)
        stop = round(max(low, entry - self.p("max_stop_atr") * t["atr14"]) - 0.01, 2)
        if stop >= entry:
            return None
        target = round(entry + self.p("target_r") * (entry - stop), 2)
        return SetupProposal(
            ctx.symbol, self.key, self.version,
            thesis=f"{ctx.symbol} reclaimed session VWAP inside a daily uptrend: intraday control shifting back to buyers.",
            evidence=[f"5-min close {today[-1].c:.2f} back above VWAP {vw[-1]:.2f}", "Daily close above 50-day SMA"],
            entry_type="market", entry_price=entry, stop=stop, target=target,
            invalidation=[f"Price below session low {low:.2f}", "Loses VWAP again on a 5-minute close", "15:50 ET: flat by the close"],
            time_stop_days=0, valid_days=0, holding="intraday",
            conflicting=["Intraday volume on the IEX feed is partial; VWAP is IEX-weighted unless on SIP"],
        )

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        from datetime import time as dtime

        from ..data.calendar import to_et

        if to_et(ctx.as_of).time() >= dtime(15, 50):
            return ExitInstruction("Intraday strategy: flat before the close (15:50 ET)", "eod")
        return None


_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}


class CustomRules(Strategy):
    """User-defined rule strategy. Rules compare technical-profile fields with numbers or other fields."""

    key = "custom"
    name = "Custom Rules"
    version = "1.0.0"
    style = "Custom"
    description = "All rules must be true on the last completed daily bar. Entry above the prior high, ATR-based stop, R-multiple target."
    param_specs = (ParamSpec("stop_atr", 2.0, 0.5, 5, "Stop in ATRs"), ParamSpec("target_r", 2.0, 1, 6, "Target in R"),
                   ParamSpec("time_stop_days", 10, 1, 60, "Time stop"))

    def __init__(self, params: dict[str, Any] | None = None, rules: list[dict[str, Any]] | None = None) -> None:
        params = dict(params or {})
        rules = rules if rules is not None else params.pop("rules", [])
        super().__init__(params)
        self.rules = self.validate_rules(rules)
        self.params["rules"] = self.rules
        self._apply_version()

    @classmethod
    def default_params(cls) -> dict[str, Any]:
        return {**super().default_params(), "rules": []}

    @staticmethod
    def validate_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rules:
            if r.get("op") not in _OPS:
                raise ValueError(f"Invalid operator {r.get('op')!r}")
            if not isinstance(r.get("left"), str):
                raise ValueError("Rule 'left' must be a technical field name")
            out.append({"left": r["left"], "op": r["op"], "right": r["right"]})
        if not out:
            raise ValueError("Custom strategy needs at least one rule")
        return out

    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        t = ctx.tech
        if not _need(t, "atr14"):
            return None
        evidence = []
        for r in self.rules:
            lv = t.get(r["left"])
            rv = t.get(r["right"]) if isinstance(r["right"], str) else r["right"]
            if lv is None or rv is None or isinstance(lv, (list, dict)) or not _OPS[r["op"]](lv, rv):
                return None
            evidence.append(f"{r['left']} ({lv}) {r['op']} {r['right']} ({rv})")
        atr = t["atr14"]
        trigger = round(t["high"] + 0.05 * atr, 2)
        stop = round(trigger - self.p("stop_atr") * atr, 2)
        target = round(trigger + self.p("target_r") * (trigger - stop), 2)
        return SetupProposal(ctx.symbol, self.key, self.version, thesis="User-defined rule set matched.",
                             evidence=evidence, entry_type="buy_stop", entry_price=trigger, stop=stop, target=target,
                             invalidation=[f"Price below {stop:.2f}"], time_stop_days=int(self.p("time_stop_days")))

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        return super().manage(ctx, trade)


BUILTINS: dict[str, type[Strategy]] = {
    cls.key: cls for cls in (TrendPullback, Breakout, MeanReversionRSI2, Momentum, MACrossover, MACDCross, RSIRecovery,
                             VWAPReclaim, CustomRules)
}


def create_strategy(key: str, params: dict[str, Any] | None = None) -> Strategy:
    if key not in BUILTINS:
        raise ValueError(f"Unknown strategy {key!r}")
    return BUILTINS[key](params)


def list_strategies() -> list[dict[str, Any]]:
    out = []
    for key, cls in BUILTINS.items():
        if key == "custom":
            inst = CustomRules(rules=[{"left": "close", "op": ">", "right": "sma200"}])
        else:
            inst = cls()
        out.append(inst.describe())
    return out
