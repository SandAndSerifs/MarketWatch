"""Position and cash accounting for hypothetical-money experiments.

Invariants (tested):
  * cash never goes negative (no margin) - an entry that would overdraw is refused;
  * equity = cash + sum(qty * mark price) for open positions;
  * realized P&L of a closed trade = (sum exit proceeds) - (sum entry cost) - all fees.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Experiment, Fill, Order, Position, Trade


class AccountingError(RuntimeError):
    pass


def open_positions(s: Session, experiment_id: int) -> list[Position]:
    return list(s.execute(select(Position).where(Position.experiment_id == experiment_id)).scalars())


def equity(s: Session, exp: Experiment) -> tuple[float, float]:
    """(equity, positions_value) using each position's latest mark (falls back to cost)."""
    pv = sum(p.qty * (p.last_price if p.last_price else p.avg_cost) for p in open_positions(s, exp.id))
    return exp.cash + pv, pv


def apply_entry_fill(s: Session, exp: Experiment, order: Order, qty: float, price: float, fees: float,
                     reference: float, ts: datetime, model: dict[str, Any], *, strategy_key: str,
                     strategy_version: str, stop: float, target: float | None, max_hold_days: int | None,
                     decision_id: int | None) -> Trade:
    cost = qty * price + fees
    if cost > exp.cash + 1e-6:
        raise AccountingError(f"Entry would overdraw cash (cost {cost:.2f} > cash {exp.cash:.2f}); margin is not allowed")
    s.add(Fill(order_id=order.id, ts=ts, qty=qty, price=price, reference_price=reference, fees=fees, model=model))
    exp.cash = round(exp.cash - cost, 6)
    pos = s.execute(select(Position).where(Position.experiment_id == exp.id, Position.symbol == order.symbol)).scalar_one_or_none()
    if pos is None:
        trade = Trade(experiment_id=exp.id, symbol=order.symbol, strategy_key=strategy_key, strategy_version=strategy_version,
                      status="open", qty=qty, entry_ts=ts, entry_price=price, stop_initial=stop, stop_current=stop,
                      target_initial=target, fees=fees, mae=price, mfe=price, max_hold_days=max_hold_days,
                      decision_id=decision_id)
        s.add(trade)
        s.flush()
        pos = Position(experiment_id=exp.id, symbol=order.symbol, qty=qty, avg_cost=price, trade_id=trade.id,
                       last_price=price, last_price_ts=ts)
        s.add(pos)
    else:  # additional partial fill of the same entry
        trade = s.get(Trade, pos.trade_id)
        assert trade is not None
        new_qty = pos.qty + qty
        pos.avg_cost = (pos.avg_cost * pos.qty + price * qty) / new_qty
        pos.qty = new_qty
        trade.qty = new_qty
        trade.entry_price = pos.avg_cost
        trade.fees += fees
    order.trade_id = trade.id
    order.filled_qty = round(order.filled_qty + qty, 6)
    order.avg_fill_price = pos.avg_cost
    order.fees = round(order.fees + fees, 2)
    order.status = "filled" if order.filled_qty >= order.qty - 1e-9 else "partially_filled"
    order.updated_at = ts
    s.flush()
    return trade


def apply_exit_fill(s: Session, exp: Experiment, order: Order, qty: float, price: float, fees: float,
                    reference: float, ts: datetime, model: dict[str, Any], reason: str) -> Trade:
    pos = s.execute(select(Position).where(Position.experiment_id == exp.id, Position.symbol == order.symbol)).scalar_one_or_none()
    if pos is None:
        raise AccountingError(f"No open position in {order.symbol} to sell (short selling is not allowed)")
    qty = min(qty, pos.qty)
    s.add(Fill(order_id=order.id, ts=ts, qty=qty, price=price, reference_price=reference, fees=fees, model=model))
    exp.cash = round(exp.cash + qty * price - fees, 6)
    trade = s.get(Trade, pos.trade_id)
    assert trade is not None
    snap = dict(trade.exit_snapshot or {})
    fills = list(snap.get("fills", []))
    fills.append({"ts": ts.isoformat(), "qty": qty, "price": price, "fees": fees})
    snap["fills"] = fills
    trade.exit_snapshot = snap
    trade.fees = round(trade.fees + fees, 2)
    pos.qty = round(pos.qty - qty, 6)
    order.trade_id = trade.id
    order.filled_qty = round(order.filled_qty + qty, 6)
    order.fees = round(order.fees + fees, 2)
    order.avg_fill_price = price if order.avg_fill_price is None else (
        (order.avg_fill_price * (order.filled_qty - qty) + price * qty) / order.filled_qty)
    order.status = "filled" if order.filled_qty >= order.qty - 1e-9 else "partially_filled"
    order.updated_at = ts
    if pos.qty <= 1e-9:
        exit_qty = sum(f["qty"] for f in fills)
        exit_px = sum(f["qty"] * f["price"] for f in fills) / exit_qty
        trade.exit_price = round(exit_px, 4)
        trade.exit_ts = ts
        trade.exit_reason = reason
        trade.status = "closed"
        trade.gross_pnl = round((exit_px - trade.entry_price) * trade.qty, 2)
        trade.net_pnl = round(trade.gross_pnl - trade.fees, 2)
        risk = trade.entry_price - trade.stop_initial
        trade.r_multiple = round((exit_px - trade.entry_price) / risk, 3) if risk > 0 else None
        s.delete(pos)
    s.flush()
    return trade


def mark_position(pos: Position, trade: Trade, price: float, ts: datetime) -> None:
    pos.last_price, pos.last_price_ts = price, ts
    trade.mae = min(trade.mae or price, price)
    trade.mfe = max(trade.mfe or price, price)
