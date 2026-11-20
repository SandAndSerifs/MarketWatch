"""Simulated order execution. Deterministic and auditable.

There is no code path in this package that can reach a real brokerage. Fills are
computed from the latest verified quote with conservative assumptions:

* Market buys pay the ask (sells hit the bid) plus `slippage_bps`. Without a
  two-sided quote, a half-spread of `assumed_half_spread_bps` is charged.
* Limit orders fill only if marketable, at the better of limit and quote.
* Orders are rejected (not filled) when the quote is missing/stale, the spread is
  abnormally wide, or a configured random-rejection stress test fires.
* Orders larger than the displayed size are partially filled; the remainder
  stays working and is re-attempted on later ticks at the then-current price.
* Sell-side regulatory fees: SEC Section 31 ($20.60 per $1M notional, effective
  2026-04-04) and FINRA TAF ($0.000195/share, max $9.79 per trade, 2026 schedule).
  Commission defaults to $0 (typical for retail US brokers). All configurable.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ExecutionConfig:
    slippage_bps: float = 2.0
    assumed_half_spread_bps: float = 3.0
    latency_ms: int = 300
    max_spread_bps: float = 100.0
    lot_size_for_displayed: int = 100  # quote sizes are treated as round lots of 100 shares
    commission_per_order: float = 0.0
    sec_fee_per_million: float = 20.60
    finra_taf_per_share: float = 0.000195
    finra_taf_max: float = 9.79
    random_reject_prob: float = 0.0
    seed: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "ExecutionConfig":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QuoteView:
    price: float | None
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    ts: datetime | None
    fresh: bool
    fresh_reason: str = "ok"


@dataclass
class FillResult:
    status: str  # filled | partial | rejected | not_marketable
    qty: float = 0.0
    price: float | None = None
    fees: float = 0.0
    reference_price: float | None = None
    reason: str = ""
    model: dict[str, Any] = field(default_factory=dict)


def _ceil_cent(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100


def regulatory_fees(side: str, qty: float, price: float, cfg: ExecutionConfig) -> float:
    fees = cfg.commission_per_order
    if side == "sell":
        fees += _ceil_cent(qty * price * cfg.sec_fee_per_million / 1_000_000)
        fees += _ceil_cent(min(qty * cfg.finra_taf_per_share, cfg.finra_taf_max))
    return round(fees, 2)


class ExecutionSimulator:
    def __init__(self, cfg: ExecutionConfig | None = None) -> None:
        self.cfg = cfg or ExecutionConfig()
        self._rng = random.Random(self.cfg.seed)

    def simulate(self, side: str, qty: float, order_type: str, q: QuoteView, limit_price: float | None = None) -> FillResult:
        cfg = self.cfg
        if side not in ("buy", "sell"):
            return FillResult("rejected", reason=f"invalid side {side}")
        if qty <= 0:
            return FillResult("rejected", reason="quantity must be positive")
        if not q.fresh or q.price is None:
            return FillResult("rejected", reason=f"No fresh quote: {q.fresh_reason}")
        two_sided = bool(q.bid and q.ask and q.ask >= q.bid > 0)
        mid = (q.bid + q.ask) / 2 if two_sided else q.price  # type: ignore[operator]
        spread_bps = (q.ask - q.bid) / mid * 10_000 if two_sided else None  # type: ignore[operator]
        if spread_bps is not None and spread_bps > cfg.max_spread_bps:
            return FillResult("rejected", reason=f"Spread {spread_bps:.0f} bps exceeds {cfg.max_spread_bps:.0f} bps")
        if cfg.random_reject_prob > 0 and self._rng.random() < cfg.random_reject_prob:
            return FillResult("rejected", reason="Simulated venue rejection (stress test)")
        slip = cfg.slippage_bps / 10_000
        if side == "buy":
            base = q.ask if two_sided else q.price * (1 + cfg.assumed_half_spread_bps / 10_000)
            px = base * (1 + slip)
            displayed = q.ask_size
        else:
            base = q.bid if two_sided else q.price * (1 - cfg.assumed_half_spread_bps / 10_000)
            px = base * (1 - slip)
            displayed = q.bid_size
        if order_type == "limit":
            if limit_price is None:
                return FillResult("rejected", reason="limit order without limit price")
            if side == "buy" and base > limit_price:  # type: ignore[operator]
                return FillResult("not_marketable", reason=f"Ask {base:.2f} above limit {limit_price:.2f}")
            if side == "sell" and base < limit_price:  # type: ignore[operator]
                return FillResult("not_marketable", reason=f"Bid {base:.2f} below limit {limit_price:.2f}")
            px = min(px, limit_price) if side == "buy" else max(px, limit_price)
        fill_qty = qty
        status = "filled"
        if displayed:
            capacity = displayed * cfg.lot_size_for_displayed
            if qty > capacity:
                fill_qty = math.floor(capacity * 1000) / 1000
                status = "partial"
        px = round(px, 4)
        fees = regulatory_fees(side, fill_qty, px, cfg)
        return FillResult(status, fill_qty, px, fees, round(mid, 4), "",
                          {"two_sided_quote": two_sided, "spread_bps": round(spread_bps, 2) if spread_bps else None,
                           "slippage_bps": cfg.slippage_bps,
                           "assumed_half_spread_bps": None if two_sided else cfg.assumed_half_spread_bps,
                           "latency_ms": cfg.latency_ms, "quote_ts": q.ts.isoformat() if q.ts else None})

    def fill_at_reference(self, side: str, qty: float, reference: float) -> tuple[float, float]:
        """Backtest fill: reference (e.g. next open or stop level) +/- half-spread and slippage."""
        adj = (self.cfg.assumed_half_spread_bps + self.cfg.slippage_bps) / 10_000
        px = reference * (1 + adj) if side == "buy" else reference * (1 - adj)
        px = round(px, 4)
        return px, regulatory_fees(side, qty, px, self.cfg)
