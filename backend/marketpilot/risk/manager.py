"""Risk Manager: deterministic, independent, veto power.

This module is pure Python with no AI calls. Every entry order passes through
`RiskManager.evaluate_entry`, which returns an itemised verdict. The paper
broker refuses any entry order that does not carry an approved verdict.

Hard rules (not configurable): long-only, no margin, no leverage, no options,
no short selling. Configurable limits are clamped to HARD_CEILINGS so a
mis-typed setting cannot turn into an outsized position.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta
from typing import Any

from ..data import calendar as cal
from ..data.universe import sector_of

HARD_CEILINGS = {
    "max_position_pct": 20.0,
    "max_concurrent_positions": 10,
    "max_daily_loss_pct": 5.0,
    "risk_per_trade_pct": 2.0,
    "max_sector_positions": 5,
}
HARD_FLOORS = {"min_reward_risk": 0.8, "min_price": 1.0, "min_avg_dollar_volume": 1_000_000.0}

FORBIDDEN_KEYS = {"allow_short", "allow_margin", "allow_options", "leverage", "allow_leverage"}


@dataclass
class RiskConfig:
    max_position_pct: float = 5.0  # of STARTING equity, notional
    max_concurrent_positions: int = 5
    max_daily_loss_pct: float = 2.0  # of STARTING equity, realized + unrealized since session start
    risk_per_trade_pct: float = 0.5  # of current equity at the stop
    min_reward_risk: float = 1.5
    max_stop_distance_pct: float = 10.0
    min_price: float = 5.0
    min_avg_dollar_volume: float = 20_000_000.0
    max_spread_bps: float = 25.0
    max_sector_positions: int = 2
    earnings_blackout_days: int = 3  # no new swing entries if earnings within N sessions
    exit_before_earnings: bool = True
    macro_blackout_before_min: int = 60
    macro_blackout_after_min: int = 30
    entry_delay_after_open_min: int = 5
    no_entry_before_close_min: int = 10
    allow_fractional: bool = True
    require_fresh_data: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RiskConfig":
        d = dict(d or {})
        bad = FORBIDDEN_KEYS & set(d)
        if bad:
            raise ValueError(f"These settings are not allowed in MarketPilot: {sorted(bad)} (long-only, cash-only)")
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"Unknown risk settings: {sorted(unknown)}")
        cfg = cls(**d)
        cfg.clamp()
        return cfg

    def clamp(self) -> None:
        for k, ceiling in HARD_CEILINGS.items():
            v = getattr(self, k)
            setattr(self, k, type(v)(min(max(v, 0), ceiling)))
        for k, floor in HARD_FLOORS.items():
            setattr(self, k, max(getattr(self, k), floor))
        self.max_concurrent_positions = max(1, int(self.max_concurrent_positions))
        self.max_sector_positions = max(1, int(self.max_sector_positions))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["hard_rules"] = {"long_only": True, "margin": False, "leverage": False, "options": False, "short_selling": False}
        return d


@dataclass
class PortfolioState:
    starting_capital: float
    cash: float
    equity: float
    day_start_equity: float
    open_symbols: list[str]
    pending_symbols: list[str] = field(default_factory=list)  # entry orders in flight
    halted: bool = False
    halted_reason: str | None = None


@dataclass
class MarketState:
    now: datetime
    price: float | None
    bid: float | None
    ask: float | None
    data_fresh: bool
    data_reason: str
    avg_dollar_volume: float | None
    events: list[dict[str, Any]]  # upcoming events relevant to the symbol (incl. macro)
    kill_switch: bool = False
    earnings_checked: bool = False  # True when an earnings provider returned data covering this symbol


@dataclass
class Check:
    rule: str
    passed: bool
    detail: str
    blocking: bool = True


@dataclass
class RiskVerdict:
    approved: bool
    qty: float
    notional: float
    risk_amount: float
    checks: list[Check]
    sizing: dict[str, Any]

    @property
    def reasons(self) -> list[str]:
        return [c.detail for c in self.checks if not c.passed and c.blocking]

    def to_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "qty": self.qty, "notional": round(self.notional, 2),
                "risk_amount": round(self.risk_amount, 2), "checks": [asdict(c) for c in self.checks],
                "rejections": self.reasons, "sizing": self.sizing}


def earnings_within(events: list[dict[str, Any]], symbol: str, now: datetime, sessions: int) -> dict[str, Any] | None:
    """Return the first earnings event for `symbol` within the next `sessions` trading sessions (incl. today)."""
    today = cal.et_date(now)
    horizon, d, count = today, today, 0
    while count < sessions:
        if cal.is_trading_day(d):
            count += 1
            horizon = d
        d += timedelta(days=1)
    for ev in events:
        if ev.get("kind") == "earnings" and ev.get("symbol") == symbol:
            ev_date = datetime.fromisoformat(ev["date"]).date()
            if today <= ev_date <= horizon:
                return ev
    return None


def macro_blackout(events: list[dict[str, Any]], now: datetime, before_min: int, after_min: int) -> dict[str, Any] | None:
    for ev in events:
        if ev.get("kind") != "macro" or ev.get("importance") != "high" or not ev.get("time_et"):
            continue
        try:
            hh, mm = (int(x) for x in ev["time_et"].split(":"))
        except ValueError:
            continue
        ev_dt = datetime.fromisoformat(ev["date"]).replace(hour=hh, minute=mm, tzinfo=cal.ET)
        if ev_dt - timedelta(minutes=before_min) <= now <= ev_dt + timedelta(minutes=after_min):
            return ev
    return None


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ sizing
    def size_position(self, entry: float, stop: float, portfolio: PortfolioState) -> dict[str, Any]:
        c = self.config
        per_share_risk = entry - stop
        risk_budget = portfolio.equity * c.risk_per_trade_pct / 100
        max_notional = portfolio.starting_capital * c.max_position_pct / 100
        cash_cap = portfolio.cash * 0.995  # leave room for fees/slippage; never borrow
        by_risk = risk_budget / per_share_risk if per_share_risk > 0 else 0.0
        by_cap = max_notional / entry
        by_cash = cash_cap / entry
        raw = max(0.0, min(by_risk, by_cap, by_cash))
        qty = math.floor(raw * 1000) / 1000 if c.allow_fractional else float(math.floor(raw))
        binding = min((("risk_per_trade", by_risk), ("max_position_notional", by_cap), ("available_cash", by_cash)),
                      key=lambda kv: kv[1])[0]
        return {"qty": qty, "per_share_risk": round(per_share_risk, 4), "risk_budget": round(risk_budget, 2),
                "max_notional": round(max_notional, 2), "qty_by_risk": round(by_risk, 3), "qty_by_cap": round(by_cap, 3),
                "qty_by_cash": round(by_cash, 3), "binding_constraint": binding,
                "method": "fixed-fractional risk, capped by notional limit and available cash"}

    # -------------------------------------------------------------- the verdict
    def evaluate_entry(self, symbol: str, entry: float, stop: float, target: float | None, holding: str,
                       portfolio: PortfolioState, market: MarketState) -> RiskVerdict:
        c = self.config
        checks: list[Check] = []

        def add(rule: str, ok: bool, detail: str, blocking: bool = True) -> None:
            checks.append(Check(rule, bool(ok), detail, blocking))

        add("kill_switch", not market.kill_switch, "Emergency STOP is active" if market.kill_switch else "Emergency STOP not active")
        add("experiment_not_halted", not portfolio.halted,
            f"Trading halted: {portfolio.halted_reason}" if portfolio.halted else "Experiment active")
        add("long_only", stop < entry, "Long entry with stop below entry" if stop < entry else "Stop must be below entry (long-only)")
        if c.require_fresh_data:
            add("fresh_data", market.data_fresh, market.data_reason if not market.data_fresh else "Live price is fresh")
        phase = cal.session_phase(market.now)
        add("regular_session", phase in ("opening", "intraday", "power_hour"), f"Session phase is '{phase}'")
        st = cal.session_times(cal.et_date(market.now))
        if st:
            mins_since_open = (market.now - st.open).total_seconds() / 60
            mins_to_close = (st.close - market.now).total_seconds() / 60
            add("not_first_minutes", mins_since_open >= c.entry_delay_after_open_min,
                f"{mins_since_open:.0f} min since open (wait {c.entry_delay_after_open_min})")
            add("not_last_minutes", mins_to_close >= c.no_entry_before_close_min,
                f"{mins_to_close:.0f} min to close (cutoff {c.no_entry_before_close_min})")
        price = market.price or entry
        add("min_price", price >= c.min_price, f"Price {price:.2f} vs minimum {c.min_price:.2f}")
        if market.avg_dollar_volume is not None:
            add("liquidity", market.avg_dollar_volume >= c.min_avg_dollar_volume,
                f"20-day avg dollar volume ${market.avg_dollar_volume/1e6:.1f}M vs min ${c.min_avg_dollar_volume/1e6:.0f}M")
        else:
            add("liquidity", False, "Average dollar volume unknown")
        if market.bid and market.ask and market.ask >= market.bid:
            spread = (market.ask - market.bid) / ((market.ask + market.bid) / 2) * 10_000
            add("spread", spread <= c.max_spread_bps, f"Spread {spread:.1f} bps vs max {c.max_spread_bps:.0f} bps")
        stop_pct = (entry - stop) / entry * 100 if entry > 0 else 999
        add("stop_distance", stop_pct <= c.max_stop_distance_pct, f"Stop distance {stop_pct:.2f}% vs max {c.max_stop_distance_pct:.1f}%")
        if target is not None and entry > stop:
            rr = (target - entry) / (entry - stop)
            add("reward_risk", rr >= c.min_reward_risk, f"Reward:risk {rr:.2f} vs min {c.min_reward_risk:.2f}")
        else:
            add("reward_risk", False, "No profit target defined")
        add("no_duplicate", symbol not in portfolio.open_symbols and symbol not in portfolio.pending_symbols,
            "Already holding or ordering this symbol" if symbol in portfolio.open_symbols + portfolio.pending_symbols
            else "No existing position/order in symbol")
        n_open = len(set(portfolio.open_symbols) | set(portfolio.pending_symbols))
        add("max_positions", n_open < c.max_concurrent_positions, f"{n_open} open/pending vs max {c.max_concurrent_positions}")
        sec = sector_of(symbol)
        if sec:
            same = sum(1 for s in set(portfolio.open_symbols) | set(portfolio.pending_symbols) if sector_of(s) == sec)
            add("sector_concentration", same < c.max_sector_positions, f"{same} positions in sector {sec} vs max {c.max_sector_positions}")
        day_pnl = portfolio.equity - portfolio.day_start_equity
        limit = portfolio.starting_capital * c.max_daily_loss_pct / 100
        add("daily_loss_limit", day_pnl > -limit, f"Today's P&L ${day_pnl:,.2f} vs limit -${limit:,.2f}")
        if holding == "swing":
            ev = earnings_within(market.events, symbol, market.now, c.earnings_blackout_days)
            add("earnings_blackout", ev is None,
                f"Earnings on {ev['date']} ({ev.get('time_et') or 'time n/a'}) within {c.earnings_blackout_days} sessions" if ev
                else f"No known earnings within {c.earnings_blackout_days} sessions")
            if not market.earnings_checked:
                add("earnings_data_verified", False,
                    "Earnings date NOT verified (no earnings data provider configured); gap risk unknown", blocking=False)
        mev = macro_blackout(market.events, market.now, c.macro_blackout_before_min, c.macro_blackout_after_min)
        add("macro_blackout", mev is None,
            f"Inside blackout window for {mev['name']} at {mev['time_et']} ET" if mev else "No high-impact release in blackout window")

        sizing = self.size_position(entry, stop, portfolio) if entry > stop else {"qty": 0.0}
        qty = sizing["qty"]
        notional = qty * entry
        add("position_size", qty > 0 and notional >= 1.0,
            f"Size {qty} shares (${notional:,.2f}); binding constraint: {sizing.get('binding_constraint', 'n/a')}")
        approved = all(ch.passed for ch in checks if ch.blocking)
        return RiskVerdict(approved, qty if approved else 0.0, notional if approved else 0.0,
                           qty * (entry - stop) if approved else 0.0, checks, sizing)

    def daily_loss_breached(self, portfolio: PortfolioState) -> bool:
        limit = portfolio.starting_capital * self.config.max_daily_loss_pct / 100
        return portfolio.equity - portfolio.day_start_equity <= -limit
