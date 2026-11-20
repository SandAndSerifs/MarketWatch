"""Periodic performance reports and the weekly strategy review (continuous learning)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.performance import trade_stats
from ..data.calendar import et_date
from ..db import Decision, EquitySnapshot, Experiment, Trade


def _period_key(d: Any, period: str) -> str:
    if period == "daily":
        return d.isoformat()
    if period == "weekly":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return f"{d.year}-{d.month:02d}"


def performance_report(s: Session, experiment_id: int, period: str = "weekly") -> dict[str, Any]:
    exp = s.get(Experiment, experiment_id)
    if exp is None:
        raise KeyError(experiment_id)
    snaps = list(s.execute(select(EquitySnapshot).where(EquitySnapshot.experiment_id == experiment_id)
                           .order_by(EquitySnapshot.ts)).scalars())
    trades = list(s.execute(select(Trade).where(Trade.experiment_id == experiment_id, Trade.status == "closed")).scalars())
    rows: dict[str, dict[str, Any]] = {}
    prev_eq, prev_spy = exp.starting_capital, None
    for sn in snaps:
        k = _period_key(et_date(sn.ts), period)
        r = rows.setdefault(k, {"period": k, "start_equity": prev_eq, "start_spy": prev_spy or sn.benchmark_price})
        r["end_equity"], r["end_spy"] = sn.equity, sn.benchmark_price
        prev_eq, prev_spy = sn.equity, sn.benchmark_price or prev_spy
    by_period: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_period[_period_key(et_date(t.exit_ts), period)].append(t)  # type: ignore[arg-type]
    out = []
    for k in sorted(set(rows) | set(by_period)):
        r = rows.get(k, {"period": k})
        ts = trade_stats([{"net_pnl": t.net_pnl, "r_multiple": t.r_multiple} for t in by_period.get(k, [])])
        ret = ((r["end_equity"] / r["start_equity"] - 1) * 100) if r.get("end_equity") and r.get("start_equity") else None
        spy = ((r["end_spy"] / r["start_spy"] - 1) * 100) if r.get("end_spy") and r.get("start_spy") else None
        out.append({"period": k, "start_equity": r.get("start_equity"), "end_equity": r.get("end_equity"),
                    "return_pct": round(ret, 3) if ret is not None else None,
                    "spy_return_pct": round(spy, 3) if spy is not None else None,
                    "trades_closed": ts["trades"], "win_rate": ts["win_rate"], "net_pnl": ts.get("total_net_pnl"),
                    "expectancy_r": ts["expectancy_r"]})
    return {"experiment": {"id": exp.id, "name": exp.name}, "period": period, "rows": out,
            "note": "Hypothetical results from simulated trading."}


def weekly_strategy_review(s: Session, days: int = 7) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trades = list(s.execute(select(Trade).where(Trade.status == "closed")).scalars())
    groups: dict[tuple[str, str], list[Trade]] = defaultdict(list)
    for t in trades:
        groups[(t.strategy_key, t.strategy_version)].append(t)
    reviews = []
    for (key, ver), ts in sorted(groups.items()):
        recent = [t for t in ts if t.exit_ts and t.exit_ts >= since]
        exit_rules: dict[str, int] = defaultdict(int)
        for t in ts:
            exit_rules[(t.review or {}).get("exit_rule", "unknown")] += 1
        # Objection-outcome analysis: did trades that carried a given objection do worse?
        with_obj: dict[str, list[float]] = defaultdict(list)
        all_r = [t.r_multiple for t in ts if t.r_multiple is not None]
        for t in ts:
            d = s.get(Decision, t.decision_id) if t.decision_id else None
            if not d or t.r_multiple is None:
                continue
            for issue in {o["issue"] for o in d.record["steps"]["5_challenge"]["objections"] if o["severity"] != "info"}:
                with_obj[issue].append(t.r_multiple)
        obj_rows = []
        for issue, rs in with_obj.items():
            others = [r for r in all_r if r not in rs] if len(rs) < len(all_r) else []
            row = {"objection": issue, "trades_with": len(rs), "avg_r_with": round(sum(rs) / len(rs), 3),
                   "avg_r_without": round(sum(others) / len(others), 3) if others else None}
            row["assessment"] = ("insufficient sample (<5 trades each side)" if len(rs) < 5 or len(others) < 5 else
                                 "trades with this objection performed worse - consider making it a filter (test first)"
                                 if row["avg_r_without"] is not None and row["avg_r_with"] < row["avg_r_without"] - 0.3 else
                                 "no clear difference")
            obj_rows.append(row)
        deviations = sum(1 for t in ts if (t.review or {}).get("decision_quality") == "Plan deviation")
        stats = trade_stats([{"net_pnl": t.net_pnl, "r_multiple": t.r_multiple} for t in ts])
        reviews.append({"strategy": key, "version": ver, "all_time": stats,
                        "last_period": trade_stats([{"net_pnl": t.net_pnl, "r_multiple": t.r_multiple} for t in recent]),
                        "exit_rules": dict(exit_rules), "plan_deviations": deviations,
                        "objection_outcomes": sorted(obj_rows, key=lambda r: -r["trades_with"])})
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "period_days": days, "strategies": reviews,
            "policy": ("Findings are hypotheses. Any change becomes a NEW strategy version (draft), must be backtested "
                       "with out-of-sample validation and forward paper-tested before use. Active strategies are never "
                       "modified silently. No claim of profitability is made without measurable evidence.")}
