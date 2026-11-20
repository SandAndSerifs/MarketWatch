"""Strategy interface.

A strategy is the *Market Strategist* role: it proposes setups and defines how an
open position is managed. It never sizes positions or places orders; the Risk
Manager and the simulated broker do that in deterministic code.
"""
from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from ..data.models import Bar, Snapshot


@dataclass
class StrategyContext:
    symbol: str
    as_of: datetime
    bars: list[Bar]  # completed daily bars only (no partial bar for "today")
    tech: dict[str, Any]
    regime: dict[str, Any]
    sector: dict[str, Any] | None = None
    snapshot: Snapshot | None = None
    intraday: list[Bar] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SetupProposal:
    symbol: str
    strategy_key: str
    strategy_version: str
    thesis: str
    evidence: list[str]
    entry_type: str  # buy_stop | limit | market
    entry_price: float
    stop: float
    target: float | None
    invalidation: list[str]
    time_stop_days: int
    valid_days: int = 2  # how many sessions the entry trigger stays armed
    holding: str = "swing"  # swing | intraday
    conflicting: list[str] = field(default_factory=list)  # strategy-specific caveats
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_per_share(self) -> float:
        return self.entry_price - self.stop

    @property
    def reward_risk(self) -> float | None:
        if self.target is None or self.risk_per_share <= 0:
            return None
        return (self.target - self.entry_price) / self.risk_per_share

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["risk_per_share"] = round(self.risk_per_share, 4)
        d["reward_risk"] = round(self.reward_risk, 2) if self.reward_risk is not None else None
        return d


@dataclass
class ExitInstruction:
    reason: str  # human readable, stored on the trade
    rule: str  # machine key: stop | target | time_stop | thesis_broken | trail | earnings | eod
    new_stop: float | None = None  # if set: tighten stop instead of exiting
    exit_now: bool = True


@dataclass
class TradeView:
    """What a strategy may see about an open trade when managing it."""

    symbol: str
    entry_price: float
    entry_ts: datetime
    stop_initial: float
    stop_current: float
    target: float | None
    sessions_held: int
    max_hold_days: int | None
    high_since_entry: float


@dataclass(frozen=True)
class ParamSpec:
    name: str
    default: float | int | bool | str
    min: float | None = None
    max: float | None = None
    description: str = ""


class Strategy(abc.ABC):
    key: str = "base"
    name: str = "Base"
    version: str = "1.0.0"
    style: str = ""
    description: str = ""
    timeframe: str = "1Day"
    holding: str = "swing"
    backtestable: bool = True
    param_specs: tuple[ParamSpec, ...] = ()
    knowledge_refs: tuple[str, ...] = ()

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = self.default_params()
        for k, v in (params or {}).items():
            spec = next((p for p in self.param_specs if p.name == k), None)
            if spec is None:
                raise ValueError(f"Unknown parameter {k!r} for strategy {self.key}")
            if spec.min is not None and float(v) < spec.min:
                raise ValueError(f"{k} below minimum {spec.min}")
            if spec.max is not None and float(v) > spec.max:
                raise ValueError(f"{k} above maximum {spec.max}")
            self.params[k] = type(spec.default)(v) if not isinstance(spec.default, bool) else bool(v)
        self._apply_version()

    def _apply_version(self) -> None:
        """Non-default parameters produce a distinct version id, e.g. '1.0.0+a1b2c3'."""
        import hashlib
        import json

        base = type(self).version
        if self.params != self.default_params():
            digest = hashlib.sha1(json.dumps(self.params, sort_keys=True, default=str).encode()).hexdigest()[:6]
            self.version = f"{base}+{digest}"
        else:
            self.version = base

    @classmethod
    def default_params(cls) -> dict[str, Any]:
        return {p.name: p.default for p in cls.param_specs}

    def p(self, name: str) -> Any:
        return self.params[name]

    @abc.abstractmethod
    def evaluate(self, ctx: StrategyContext) -> SetupProposal | None:
        """Return a long setup, or None if there is no setup (the normal case)."""

    def manage(self, ctx: StrategyContext, trade: TradeView) -> ExitInstruction | None:
        """Default management: breakeven stop after +1R, time stop."""
        r = trade.entry_price - trade.stop_initial
        if r > 0 and trade.high_since_entry >= trade.entry_price + r and trade.stop_current < trade.entry_price:
            return ExitInstruction("Price reached +1R: stop moved to breakeven", "trail",
                                   new_stop=round(trade.entry_price, 4), exit_now=False)
        if trade.max_hold_days and trade.sessions_held >= trade.max_hold_days:
            return ExitInstruction(f"Time stop: held {trade.sessions_held} sessions without reaching target", "time_stop")
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "version": self.version, "style": self.style,
            "description": self.description, "timeframe": self.timeframe, "holding": self.holding,
            "backtestable": self.backtestable, "params": self.params,
            "param_specs": [asdict(p) for p in self.param_specs], "knowledge_refs": list(self.knowledge_refs),
        }
