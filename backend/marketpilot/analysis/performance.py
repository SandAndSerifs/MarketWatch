"""Performance statistics shared by paper trading, competitions and backtests.

Statistics are computed from realised data only. Small samples are flagged
rather than hidden: with fewer than ~30 trades, win rate and profit factor have
very wide confidence intervals and should not be read as evidence of an edge.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime
from typing import Any

import numpy as np

from ..data.calendar import et_date

MIN_TRADES_FOR_INFERENCE = 30


def daily_equity(points: list[tuple[datetime, float]]) -> list[tuple[str, float]]:
    """Last equity value per US/Eastern calendar date."""
    by_day: "OrderedDict[str, float]" = OrderedDict()
    for ts, eq in sorted(points, key=lambda p: p[0]):
        by_day[et_date(ts).isoformat()] = eq
    return list(by_day.items())


def drawdown_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"max_drawdown_pct": 0.0, "current_drawdown_pct": 0.0, "max_dd_duration_periods": 0}
    arr = np.asarray(values, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = (arr / peak - 1) * 100
    dur = mx = 0
    for v in dd:
        dur = dur + 1 if v < 0 else 0
        mx = max(mx, dur)
    return {"max_drawdown_pct": round(float(dd.min()), 3), "current_drawdown_pct": round(float(dd[-1]), 3),
            "max_dd_duration_periods": int(mx)}


MIN_DAYS_FOR_RATIOS = 20


def return_stats(daily_values: list[float], periods_per_year: int = 252) -> dict[str, float | None]:
    # Annualised ratios from a handful of daily returns are noise; require ~a month of data.
    if len(daily_values) < MIN_DAYS_FOR_RATIOS + 1:
        return {"sharpe": None, "sortino": None, "volatility_ann_pct": None}
    arr = np.asarray(daily_values, dtype=float)
    rets = arr[1:] / arr[:-1] - 1
    sd = rets.std(ddof=1)
    downside = rets[rets < 0]
    dsd = math.sqrt((downside**2).mean()) if len(downside) else 0.0
    mean = rets.mean()
    return {
        "sharpe": round(float(mean / sd * math.sqrt(periods_per_year)), 3) if sd > 0 else None,
        "sortino": round(float(mean / dsd * math.sqrt(periods_per_year)), 3) if dsd > 0 else None,
        "volatility_ann_pct": round(float(sd * math.sqrt(periods_per_year) * 100), 3),
    }


def trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """trades: dicts with net_pnl, r_multiple (optional), entry_ts/exit_ts (optional ISO)."""
    closed = [t for t in trades if t.get("net_pnl") is not None]
    n = len(closed)
    if n == 0:
        return {"trades": 0, "win_rate": None, "profit_factor": None, "expectancy": None, "expectancy_r": None,
                "avg_win": None, "avg_loss": None, "largest_win": None, "largest_loss": None,
                "sample_warning": "No closed trades yet."}
    pnl = np.array([t["net_pnl"] for t in closed], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    rs = [t["r_multiple"] for t in closed if t.get("r_multiple") is not None]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    holds = []
    for t in closed:
        if t.get("entry_ts") and t.get("exit_ts"):
            holds.append((datetime.fromisoformat(t["exit_ts"]) - datetime.fromisoformat(t["entry_ts"])).total_seconds() / 86400)
    # streaks
    longest_loss = cur = 0
    for v in pnl:
        cur = cur + 1 if v <= 0 else 0
        longest_loss = max(longest_loss, cur)
    win_rate = len(wins) / n * 100
    # Wilson 95% interval for the win rate: makes small-sample uncertainty explicit.
    z, p = 1.96, len(wins) / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return {
        "trades": n,
        "wins": int(len(wins)), "losses": int(len(losses)),
        "win_rate": round(win_rate, 2),
        "win_rate_ci95": [round((centre - half) * 100, 1), round((centre + half) * 100, 1)],
        "profit_factor": round(float(gross_win / gross_loss), 3) if gross_loss > 0 else None,
        "profit_factor_note": None if gross_loss > 0 else "undefined: no losing trades yet",
        "expectancy": round(float(pnl.mean()), 2),
        "expectancy_r": round(float(np.mean(rs)), 3) if rs else None,
        "avg_win": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else None,
        "avg_win_r": round(float(np.mean([r for r in rs if r > 0])), 3) if any(r > 0 for r in rs) else None,
        "avg_loss_r": round(float(np.mean([r for r in rs if r <= 0])), 3) if any(r <= 0 for r in rs) else None,
        "largest_win": round(float(wins.max()), 2) if len(wins) else None,
        "largest_loss": round(float(losses.min()), 2) if len(losses) else None,
        "total_net_pnl": round(float(pnl.sum()), 2),
        "avg_hold_days": round(float(np.mean(holds)), 2) if holds else None,
        "longest_losing_streak": int(longest_loss),
        "sample_warning": None if n >= MIN_TRADES_FOR_INFERENCE else
        f"Only {n} closed trades: statistics are not yet meaningful (need ~{MIN_TRADES_FOR_INFERENCE}+).",
    }


def summarize(equity_points: list[tuple[datetime, float]], starting_capital: float, trades: list[dict[str, Any]],
              benchmark_points: list[tuple[datetime, float]] | None = None) -> dict[str, Any]:
    daily = daily_equity(equity_points)
    values = [v for _, v in daily]
    final = values[-1] if values else starting_capital
    out: dict[str, Any] = {
        "starting_capital": starting_capital, "final_equity": round(final, 2),
        "total_return_pct": round((final / starting_capital - 1) * 100, 3) if starting_capital else None,
        "days": len(daily),
    }
    out.update(drawdown_stats([starting_capital] + values))
    out.update(return_stats([starting_capital] + values))
    if len(daily) > 60:
        years = len(daily) / 252
        out["cagr_pct"] = round(((final / starting_capital) ** (1 / years) - 1) * 100, 3)
        out["calmar"] = round(out["cagr_pct"] / abs(out["max_drawdown_pct"]), 3) if out["max_drawdown_pct"] < 0 else None
    out["trade_stats"] = trade_stats(trades)
    if benchmark_points:
        b = daily_equity(benchmark_points)
        if len(b) >= 2 and b[0][1] > 0:
            bret = (b[-1][1] / b[0][1] - 1) * 100
            out["benchmark"] = {"symbol": "SPY", "return_pct": round(bret, 3),
                                "excess_return_pct": round((out["total_return_pct"] or 0) - bret, 3),
                                "max_drawdown_pct": drawdown_stats([v for _, v in b])["max_drawdown_pct"],
                                "period": f"{b[0][0]}..{b[-1][0]}"}
    return out


def risk_adjusted_score(stats: dict[str, Any]) -> dict[str, Any]:
    """Leaderboard score that does not reward raw risk-taking.

    score = Sharpe * sample_confidence, minus a penalty when max drawdown exceeds 10%.
    sample_confidence = min(1, trades / 30). Strategies with no closed trades score 0.
    """
    ts = stats.get("trade_stats") or {}
    n = ts.get("trades", 0) or 0
    sharpe = stats.get("sharpe") or 0.0
    conf = min(1.0, n / MIN_TRADES_FOR_INFERENCE)
    dd = abs(stats.get("max_drawdown_pct") or 0.0)
    penalty = max(0.0, (dd - 10.0) / 10.0)
    score = (sharpe * conf - penalty) if n else 0.0
    return {"score": round(score, 3), "sample_confidence": round(conf, 2), "drawdown_penalty": round(penalty, 3),
            "method": "Sharpe x min(1, trades/30) - max(0, (|maxDD|-10%)/10%)"}
