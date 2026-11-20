"""Read models shared by the REST API and the AI tools."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.performance import risk_adjusted_score, summarize
from ..db import Decision, EquitySnapshot, Experiment, Fill, Order, PendingSetup, Trade
from ..paper.accounting import equity, open_positions
from ..risk.manager import RiskConfig


def trade_to_dict(t: Trade) -> dict[str, Any]:
    return {"id": t.id, "experiment_id": t.experiment_id, "symbol": t.symbol, "strategy_key": t.strategy_key,
            "strategy_version": t.strategy_version, "status": t.status, "qty": t.qty,
            "entry_ts": t.entry_ts.isoformat(), "entry_price": t.entry_price, "stop_initial": t.stop_initial,
            "stop_current": t.stop_current, "target_initial": t.target_initial,
            "exit_ts": t.exit_ts.isoformat() if t.exit_ts else None, "exit_price": t.exit_price,
            "exit_reason": t.exit_reason, "fees": t.fees, "gross_pnl": t.gross_pnl, "net_pnl": t.net_pnl,
            "r_multiple": t.r_multiple, "mae": t.mae, "mfe": t.mfe, "max_hold_days": t.max_hold_days,
            "decision_id": t.decision_id, "review": t.review}


def decision_to_dict(d: Decision) -> dict[str, Any]:
    return {"id": d.id, "ts": d.ts.isoformat(), "experiment_id": d.experiment_id, "symbol": d.symbol,
            "strategy_key": d.strategy_key, "strategy_version": d.strategy_version, "category": d.category,
            "approved": d.approved, "context": d.context, "record": d.record}


def order_to_dict(o: Order) -> dict[str, Any]:
    return {"id": o.id, "client_order_id": o.client_order_id, "symbol": o.symbol, "side": o.side,
            "order_type": o.order_type, "qty": o.qty, "limit_price": o.limit_price, "purpose": o.purpose,
            "status": o.status, "filled_qty": o.filled_qty, "avg_fill_price": o.avg_fill_price, "fees": o.fees,
            "reject_reason": o.reject_reason, "created_at": o.created_at.isoformat(), "trade_id": o.trade_id,
            "decision_id": o.decision_id}


def trade_detail(s: Session, t: Trade) -> dict[str, Any]:
    d = s.get(Decision, t.decision_id) if t.decision_id else None
    orders = list(s.execute(select(Order).where(Order.trade_id == t.id).order_by(Order.id)).scalars())
    fills = []
    for o in orders:
        for f in s.execute(select(Fill).where(Fill.order_id == o.id).order_by(Fill.id)).scalars():
            fills.append({"order": o.client_order_id, "side": o.side, "ts": f.ts.isoformat(), "qty": f.qty, "price": f.price,
                          "reference_price": f.reference_price, "fees": f.fees, "model": f.model})
    setup = None
    if d and d.record.get("trigger", {}).get("setup_decision_id"):
        sd = s.get(Decision, d.record["trigger"]["setup_decision_id"])
        setup = decision_to_dict(sd) if sd else None
    exp = s.get(Experiment, t.experiment_id)
    return {"trade": trade_to_dict(t), "decision": decision_to_dict(d) if d else None, "setup_decision": setup,
            "orders": [order_to_dict(o) for o in orders], "fills": fills,
            "experiment": {"id": exp.id, "name": exp.name} if exp else None,
            "execution_costs": {"fees": t.fees,
                                "slippage_vs_reference": round(sum((f["price"] - f["reference_price"]) * f["qty"] *
                                                                   (1 if f["side"] == "buy" else -1) for f in fills), 2)}}


def experiment_summary(s: Session, exp: Experiment, with_curve: bool = False) -> dict[str, Any]:
    eq, pv = equity(s, exp)
    trades = list(s.execute(select(Trade).where(Trade.experiment_id == exp.id)).scalars())
    closed = [t for t in trades if t.status == "closed"]
    snaps = list(s.execute(select(EquitySnapshot).where(EquitySnapshot.experiment_id == exp.id)
                           .order_by(EquitySnapshot.ts)).scalars())
    pts = [(sn.ts, sn.equity) for sn in snaps]
    if exp.started_at:
        pts = [(exp.started_at, exp.starting_capital)] + pts
    pts.append((datetime.now(timezone.utc), eq))
    bench = [(sn.ts, sn.benchmark_price) for sn in snaps if sn.benchmark_price]
    stats = summarize(pts, exp.starting_capital,
                      [{"net_pnl": t.net_pnl, "r_multiple": t.r_multiple, "entry_ts": t.entry_ts.isoformat(),
                        "exit_ts": t.exit_ts.isoformat() if t.exit_ts else None} for t in closed], bench or None)
    realized = sum(t.net_pnl or 0 for t in closed)
    positions = []
    for p in open_positions(s, exp.id):
        tr = s.get(Trade, p.trade_id)
        mark = p.last_price or p.avg_cost
        positions.append({"symbol": p.symbol, "qty": p.qty, "avg_cost": p.avg_cost, "last_price": p.last_price,
                          "last_price_ts": p.last_price_ts.isoformat() if p.last_price_ts else None,
                          "market_value": round(p.qty * mark, 2), "unrealized_pnl": round((mark - p.avg_cost) * p.qty, 2),
                          "stop": tr.stop_current if tr else None, "target": tr.target_initial if tr else None,
                          "trade_id": p.trade_id})
    armed = s.execute(select(PendingSetup).where(PendingSetup.experiment_id == exp.id, PendingSetup.status == "armed")).scalars().all()
    out = {
        "id": exp.id, "name": exp.name, "strategy_key": exp.strategy_key, "strategy_version": exp.strategy_version,
        "strategy_params": exp.strategy_params, "risk_config": exp.risk_config,
        "risk_effective": RiskConfig.from_dict((exp.risk_config or {}).get("risk")).to_dict(), "status": exp.status,
        "halted_reason": exp.halted_reason, "competition_group": exp.competition_group,
        "starting_capital": exp.starting_capital, "cash": round(exp.cash, 2), "equity": round(eq, 2),
        "positions_value": round(pv, 2), "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(sum(p["unrealized_pnl"] for p in positions), 2),
        "day_pnl": round(eq - (exp.day_start_equity or eq), 2),
        "created_at": exp.created_at.isoformat(), "started_at": exp.started_at.isoformat() if exp.started_at else None,
        "universe_size": len(exp.universe or []), "positions": positions,
        "armed_setups": [{"id": a.id, "symbol": a.symbol, "trigger": a.trigger_price, "stop": a.stop, "target": a.target,
                          "expires_at": a.expires_at.isoformat(), "decision_id": a.decision_id} for a in armed],
        "stats": stats, "score": risk_adjusted_score(stats), "open_trades": len(trades) - len(closed),
        "closed_trades": len(closed), "archived": exp.archived,
    }
    if with_curve:
        out["equity_curve"] = [{"ts": sn.ts.isoformat(), "equity": sn.equity, "benchmark_price": sn.benchmark_price}
                               for sn in snaps]
    return out
