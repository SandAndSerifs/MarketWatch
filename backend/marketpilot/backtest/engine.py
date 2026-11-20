"""Event-driven daily backtester.

Rules that prevent look-ahead and flattering assumptions:
  * Decisions on day d use only bars <= d (precomputed causal indicators read at index d).
  * Entries are buy-stop / limit orders working on day d+1 onwards; a buy-stop fills at
    max(open, trigger) (gap-ups fill at the open), plus half-spread and slippage.
  * Intrabar ambiguity is resolved pessimistically: if the entry bar's range also touches
    the stop, the trade is stopped out that day; if a bar touches both stop and target,
    the stop is assumed to fill first. A gap through the stop fills at the open.
  * Strategy exit rules evaluated on the close of day d execute at the open of d+1.
  * Position sizing and limits reuse the live RiskManager's sizing (5% notional cap,
    0.5% risk, max positions, sector limit, cash only).
  * Sell-side regulatory fees and per-share costs from ExecutionConfig.

Known limitations (recorded as warnings on every run): static universe (survivorship
bias), no historical earnings calendar (earnings blackout not simulated), daily bars
cannot model intraday sequencing exactly.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..analysis.performance import drawdown_stats, return_stats, trade_stats
from ..analysis.technicals import RegimeSeries, TechSeries
from ..data.models import Bar
from ..data.universe import sector_of
from ..decision.checklist import challenge
from ..paper.execution import ExecutionConfig, ExecutionSimulator
from ..risk.manager import PortfolioState, RiskConfig, RiskManager
from ..strategies.base import Strategy, StrategyContext, TradeView
from ..strategies.library import create_strategy


@dataclass
class BTPosition:
    symbol: str
    qty: float
    entry_price: float
    entry_date: date
    stop_initial: float
    stop: float
    target: float | None
    max_hold: int | None
    fees: float
    high: float
    low: float
    entry_reason: str
    exit_next_open: str | None = None
    exit_rule: str | None = None


@dataclass
class BTSetup:
    symbol: str
    entry_type: str
    trigger: float
    stop: float
    target: float | None
    expires_idx: int
    time_stop: int
    thesis: str
    objections: int


@dataclass
class BTResult:
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity: list[tuple[str, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def split_dates(dates: list[date], fractions: tuple[float, float, float] = (0.6, 0.2, 0.2)) -> dict[str, tuple[date, date]]:
    n = len(dates)
    a = int(n * fractions[0])
    b = int(n * (fractions[0] + fractions[1]))
    return {"train": (dates[0], dates[max(a - 1, 0)]), "validation": (dates[a], dates[max(b - 1, a)]),
            "test": (dates[b], dates[-1])}


class Backtester:
    def __init__(self, strategy: Strategy, bars: dict[str, list[Bar]], spy: list[Bar],
                 sectors: dict[str, list[Bar]] | None = None, risk: RiskConfig | None = None,
                 execution: ExecutionConfig | None = None, starting_capital: float = 10_000.0,
                 use_challenge: bool = True) -> None:
        self.strategy = strategy
        self.bars = {k: v for k, v in bars.items() if len(v) >= 60}
        self.series = {k: TechSeries(v) for k, v in self.bars.items()}
        self.idx = {k: {b.t.date(): i for i, b in enumerate(v)} for k, v in self.bars.items()}
        self.regime = RegimeSeries(spy, sectors)
        self.spy = spy
        self.risk = risk or RiskConfig()
        self.sim = ExecutionSimulator(execution or ExecutionConfig())
        self.capital = starting_capital
        self.use_challenge = use_challenge

    def run(self, start: date, end: date) -> BTResult:
        res = BTResult()
        res.warnings += [
            "Static symbol universe: survivorship bias likely flatters results (delisted names are missing).",
            "No point-in-time earnings calendar: earnings blackout and pre-earnings exits are NOT simulated.",
            "Daily bars: intraday order of stop/target hits is unknown; pessimistic assumptions applied.",
        ]
        dates = [b.t.date() for b in self.spy if start <= b.t.date() <= end]
        if len(dates) < 20:
            res.warnings.append("Fewer than 20 trading days in range.")
            return res
        cash = self.capital
        positions: dict[str, BTPosition] = {}
        setups: dict[str, BTSetup] = {}
        rm = RiskManager(self.risk)
        for di, d in enumerate(dates):
            # ---- 1. manage open positions with today's bar
            for sym in list(positions):
                i = self.idx[sym].get(d)
                if i is None:
                    continue
                b = self.bars[sym][i]
                p = positions[sym]
                exit_px, rule, reason = None, None, None
                if p.exit_next_open:
                    exit_px, rule, reason = b.o, p.exit_rule, p.exit_next_open
                elif b.o <= p.stop:
                    exit_px, rule, reason = b.o, "stop", f"Gap below stop {p.stop:.2f}: filled at open {b.o:.2f}"
                elif b.l <= p.stop:
                    exit_px = p.stop
                    rule = "stop" if p.stop <= p.stop_initial + 1e-9 else "trail"
                    reason = f"Stop {p.stop:.2f} hit"
                elif p.target and b.o >= p.target:
                    exit_px, rule, reason = b.o, "target", f"Gap above target: filled at open {b.o:.2f}"
                elif p.target and b.h >= p.target:
                    exit_px, rule, reason = p.target, "target", f"Target {p.target:.2f} reached"
                p.high, p.low = max(p.high, b.h), min(p.low, b.l)
                if exit_px is not None:
                    px, fee = self.sim.fill_at_reference("sell", p.qty, exit_px)
                    cash += p.qty * px - fee
                    res.trades.append(self._close(p, d, px, fee, rule or "manual", reason or ""))
                    del positions[sym]
            # ---- 2. work armed setups on today's bar
            for sym in list(setups):
                st = setups[sym]
                if di > st.expires_idx or sym in positions:
                    del setups[sym]
                    continue
                i = self.idx[sym].get(d)
                if i is None:
                    continue
                b = self.bars[sym][i]
                fill_ref = None
                if st.entry_type == "buy_stop":
                    if b.h >= st.trigger:
                        fill_ref = max(b.o, st.trigger)
                    elif b.l <= st.stop:
                        del setups[sym]  # invalidated before triggering
                        continue
                elif st.entry_type == "limit":
                    if b.o <= st.stop:
                        del setups[sym]  # opened below the stop: never buy below invalidation
                        continue
                    if b.l <= st.trigger:
                        fill_ref = min(b.o, st.trigger)
                if fill_ref is None:
                    continue
                del setups[sym]
                eq = cash + sum(pp.qty * self._close_px(pp.symbol, d, pp.entry_price) for pp in positions.values())
                pf = PortfolioState(self.capital, cash, eq, eq, list(positions))
                if len(positions) >= self.risk.max_concurrent_positions:
                    continue
                sec = sector_of(sym)
                if sec and sum(1 for s in positions if sector_of(s) == sec) >= self.risk.max_sector_positions:
                    continue
                size = rm.size_position(fill_ref, st.stop, pf)
                qty = size["qty"]
                if qty <= 0:
                    continue
                px, fee = self.sim.fill_at_reference("buy", qty, fill_ref)
                if qty * px + fee > cash:
                    qty = math.floor((cash - fee) / px * 1000) / 1000 if self.risk.allow_fractional else math.floor((cash - fee) / px)
                    if qty <= 0:
                        continue
                cash -= qty * px + fee
                p = BTPosition(sym, qty, px, d, st.stop, st.stop, st.target, st.time_stop or None, fee, b.h, b.l, st.thesis)
                # pessimistic same-bar stop: if the bar's low reached the stop, assume it was hit after entry
                if b.l <= st.stop:
                    spx, sfee = self.sim.fill_at_reference("sell", qty, st.stop)
                    cash += qty * spx - sfee
                    res.trades.append(self._close(p, d, spx, sfee, "stop", "Stopped out on entry day (pessimistic intrabar assumption)"))
                else:
                    positions[sym] = p
            # ---- 3. after the close: strategy management and new setups (completed bar d)
            regime = self.regime.at_date(d)
            for sym, p in positions.items():
                i = self.idx[sym].get(d)
                if i is None:
                    continue
                ser = self.series[sym]
                ctx = StrategyContext(sym, datetime.combine(d, datetime.min.time()), self.bars[sym][: i + 1],
                                      ser.profile_at(i, with_levels=False), regime)
                held = sum(1 for dd in dates[: di + 1] if dd > p.entry_date)
                tv = TradeView(sym, p.entry_price, ctx.as_of, p.stop_initial, p.stop, p.target, held, p.max_hold, p.high)
                instr = self.strategy.manage(ctx, tv)
                if instr:
                    if instr.new_stop is not None and not instr.exit_now:
                        p.stop = max(p.stop, instr.new_stop)
                    elif instr.exit_now:
                        p.exit_next_open, p.exit_rule = instr.reason, instr.rule
            for sym, ser in self.series.items():
                if sym in positions or sym in setups:
                    continue
                i = self.idx[sym].get(d)
                if i is None or i < 60:
                    continue
                prof = ser.profile_at(i, with_levels=self.use_challenge)
                ctx = StrategyContext(sym, datetime.combine(d, datetime.min.time()).replace(tzinfo=self.spy[0].t.tzinfo),
                                      self.bars[sym][: i + 1], prof, regime)
                prop = self.strategy.evaluate(ctx)
                if prop is None:
                    continue
                if prop.stop >= prop.entry_price:
                    continue
                rr = prop.reward_risk
                if rr is None or rr < self.risk.min_reward_risk:
                    continue
                if (prop.entry_price - prop.stop) / prop.entry_price * 100 > self.risk.max_stop_distance_pct:
                    continue
                if prof.get("avg_dollar_volume20", 0) < self.risk.min_avg_dollar_volume or prop.entry_price < self.risk.min_price:
                    continue
                n_obj = 0
                if self.use_challenge:
                    ch = challenge(ctx, prop, self.risk, None)
                    if ch["counts"]["blocking"] or ch["counts"]["serious"] >= 2:
                        continue
                    n_obj = ch["counts"]["serious"]
                setups[sym] = BTSetup(sym, prop.entry_type, prop.entry_price, prop.stop, prop.target,
                                      di + max(prop.valid_days, 1), prop.time_stop_days, prop.thesis[:200], n_obj)
            # ---- 4. mark to market
            eq = cash + sum(p.qty * self._close_px(p.symbol, d, p.entry_price) for p in positions.values())
            res.equity.append((d.isoformat(), round(eq, 2)))
        # close remaining at last close (marked, flagged)
        last = dates[-1]
        for p in positions.values():
            px, fee = self.sim.fill_at_reference("sell", p.qty, self._close_px(p.symbol, last, p.entry_price))
            res.trades.append(self._close(p, last, px, fee, "end_of_test", "Closed at end of backtest window"))
        return res

    def _close_px(self, sym: str, d: date, fallback: float) -> float:
        i = self.idx[sym].get(d)
        if i is None:
            prior = [k for k in self.idx[sym] if k <= d]
            if not prior:
                return fallback
            i = self.idx[sym][max(prior)]
        return self.bars[sym][i].c

    @staticmethod
    def _close(p: BTPosition, d: date, px: float, fee: float, rule: str, reason: str) -> dict[str, Any]:
        gross = (px - p.entry_price) * p.qty
        fees = p.fees + fee
        risk = p.entry_price - p.stop_initial
        return {"symbol": p.symbol, "qty": p.qty, "entry_date": p.entry_date.isoformat(), "entry_price": p.entry_price,
                "exit_date": d.isoformat(), "exit_price": round(px, 4), "stop_initial": p.stop_initial,
                "target": p.target, "exit_rule": rule, "exit_reason": reason, "fees": round(fees, 2),
                "net_pnl": round(gross - fees, 2), "r_multiple": round((px - p.entry_price) / risk, 3) if risk > 0 else None,
                "mae_r": round((p.low - p.entry_price) / risk, 2) if risk > 0 else None,
                "mfe_r": round((p.high - p.entry_price) / risk, 2) if risk > 0 else None,
                "entry_ts": p.entry_date.isoformat() + "T00:00:00", "exit_ts": d.isoformat() + "T00:00:00",
                "thesis": p.entry_reason}


def segment_metrics(res: BTResult, seg: tuple[date, date], spy: list[Bar]) -> dict[str, Any]:
    a, b = seg
    eq = [(d, v) for d, v in res.equity if a.isoformat() <= d <= b.isoformat()]
    trades = [t for t in res.trades if a.isoformat() <= t["entry_date"] <= b.isoformat()]
    vals = [v for _, v in eq]
    out: dict[str, Any] = {"start": a.isoformat(), "end": b.isoformat(), "days": len(eq)}
    if vals:
        out["return_pct"] = round((vals[-1] / vals[0] - 1) * 100, 3) if vals[0] else None
        out.update(drawdown_stats(vals))
        out.update(return_stats(vals))
    ts = trade_stats(trades)
    out.update({k: ts.get(k) for k in ("trades", "win_rate", "win_rate_ci95", "profit_factor", "expectancy", "expectancy_r",
                                       "avg_win", "avg_loss", "largest_win", "largest_loss", "avg_hold_days",
                                       "longest_losing_streak", "sample_warning")})
    if out.get("days"):
        out["trades_per_month"] = round(ts["trades"] / (len(eq) / 21), 2) if len(eq) >= 21 else None
    spy_seg = [x for x in spy if a <= x.t.date() <= b]
    if len(spy_seg) > 1:
        out["benchmark_spy_return_pct"] = round((spy_seg[-1].c / spy_seg[0].c - 1) * 100, 3)
        out["benchmark_spy_max_drawdown_pct"] = drawdown_stats([x.c for x in spy_seg])["max_drawdown_pct"]
    # performance by market regime label at entry
    return out


def regime_breakdown(res: BTResult, regime: RegimeSeries) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for t in res.trades:
        lab = regime.at_date(date.fromisoformat(t["entry_date"])).get("label", "unknown")
        groups.setdefault(lab, []).append(t)
    return {k: {kk: trade_stats(v).get(kk) for kk in ("trades", "win_rate", "profit_factor", "expectancy_r")}
            for k, v in groups.items()}


def run_backtest(strategy_key: str, params: dict[str, Any], bars: dict[str, list[Bar]], spy: list[Bar],
                 sectors: dict[str, list[Bar]], start: date, end: date, risk: dict[str, Any] | None = None,
                 execution: dict[str, Any] | None = None, capital: float = 10_000.0,
                 fractions: tuple[float, float, float] = (0.6, 0.2, 0.2)) -> dict[str, Any]:
    strat = create_strategy(strategy_key, params)
    if not strat.backtestable:
        raise ValueError(f"{strategy_key} is not backtestable on daily bars (forward-test only)")
    bt = Backtester(strat, bars, spy, sectors, RiskConfig.from_dict(risk), ExecutionConfig.from_dict(execution), capital)
    res = bt.run(start, end)
    dates = [date.fromisoformat(d) for d, _ in res.equity]
    segments: dict[str, Any] = {}
    if len(dates) >= 60:
        for name, seg in split_dates(dates, fractions).items():
            segments[name] = segment_metrics(res, seg, spy)
        segments["full"] = segment_metrics(res, (dates[0], dates[-1]), spy)
        segments["by_regime"] = regime_breakdown(res, bt.regime)
    else:
        res.warnings.append("Too few days for train/validation/test segmentation.")
    return {"strategy": strat.describe(), "result": res, "segments": segments,
            "assumptions": {"execution": bt.sim.cfg.to_dict(), "risk": bt.risk.to_dict(), "starting_capital": capital,
                            "fills": "next-bar buy-stop/limit; pessimistic intrabar; exits on rule at next open",
                            "price_adjustment": "split and dividend adjusted", "segments": list(fractions)}}


def optimize_on_train(strategy_key: str, grid: dict[str, list[Any]], bars: dict[str, list[Bar]], spy: list[Bar],
                      sectors: dict[str, list[Bar]], start: date, end: date, risk: dict[str, Any] | None = None,
                      max_configs: int = 40, fractions: tuple[float, float, float] = (0.6, 0.2, 0.2)) -> dict[str, Any]:
    """Grid search scored ONLY on the training segment; reports validation, keeps test held out."""
    keys = list(grid)
    combos = list(itertools.product(*[grid[k] for k in keys]))[:max_configs]
    dates = [b.t.date() for b in spy if start <= b.t.date() <= end]
    segs = split_dates(dates, fractions)
    rows = []
    for combo in combos:
        params = dict(zip(keys, combo))
        bt = Backtester(create_strategy(strategy_key, params), bars, spy, sectors, RiskConfig.from_dict(risk),
                        use_challenge=False)
        res = bt.run(segs["train"][0], segs["validation"][1])
        tr = segment_metrics(res, segs["train"], spy)
        va = segment_metrics(res, segs["validation"], spy)
        rows.append({"params": params, "train": tr, "validation": va})

    def score(r: dict[str, Any]) -> float:
        t = r["train"]
        return (t.get("expectancy_r") or -9) * min(1.0, (t.get("trades") or 0) / 30)

    rows.sort(key=score, reverse=True)
    return {"configs_tested": len(rows), "best": rows[0] if rows else None, "all": rows,
            "warning": f"{len(rows)} configurations tested: the best training result is biased upward by selection. "
                       "Judge it on the validation segment, then confirm once on the untouched test segment."}
