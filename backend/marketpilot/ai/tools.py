"""Read-only tools the AI analyst can call. Facts come from here, never from the model's memory."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from ..analysis.technicals import technical_profile
from ..data import calendar as cal
from ..db import BacktestRun, Experiment, Signal, Trade, session_scope
from ..events.calendar import upcoming_events
from ..knowledge.store import retrieve
from ..risk.manager import RiskConfig
from ..services.analysis import reference_portfolio
from ..services.scanner import signal_to_dict
from ..services.views import experiment_summary, trade_detail, trade_to_dict
from ..strategies.library import BUILTINS, create_strategy
from .provider import ToolSpec


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


TOOL_SPECS = [
    ToolSpec("get_market_status", "Current US market session phase, holidays and data-feed quality/health.", _obj({})),
    ToolSpec("get_quotes", "Latest verified quotes/snapshots for up to 20 symbols, with feed label and timestamps.",
             _obj({"symbols": {"type": "array", "items": {"type": "string"}}}, ["symbols"])),
    ToolSpec("get_technicals", "Technical profile (SMA/EMA/RSI/MACD/Bollinger/ATR/ADX/volume/support/resistance) "
             "computed on completed daily bars for one symbol.", _obj({"symbol": {"type": "string"}}, ["symbol"])),
    ToolSpec("get_market_regime", "Broad market regime from SPY and sector ETF relative strength.", _obj({})),
    ToolSpec("get_news", "Recent news headlines for a symbol from the configured provider.", _obj({"symbol": {"type": "string"}}, ["symbol"])),
    ToolSpec("evaluate_setups", "Run every built-in daily strategy's full checklist (thesis, evidence, objections, "
             "risk check) on one symbol right now.", _obj({"symbol": {"type": "string"}}, ["symbol"])),
    ToolSpec("get_signals", "Recent scanner signals, optionally filtered by category (BUY_CANDIDATE, WATCH, "
             "SELL_EXIT_CANDIDATE, HOLD_MANAGE, NO_TRADE) or symbol.",
             _obj({"limit": {"type": "integer"}, "category": {"type": "string"}, "symbol": {"type": "string"}})),
    ToolSpec("get_paper_trades", "Simulated (paper) trades. Filter by experiment_id, status (open/closed), symbol, or since_days.",
             _obj({"experiment_id": {"type": "integer"}, "status": {"type": "string"}, "symbol": {"type": "string"},
                   "since_days": {"type": "integer"}})),
    ToolSpec("get_trade_record", "The ORIGINAL recorded decision record, orders, fills and post-trade review for one trade.",
             _obj({"trade_id": {"type": "integer"}}, ["trade_id"])),
    ToolSpec("get_performance", "Paper-trading experiments with P&L, drawdown, win rate, risk-adjusted score and SPY benchmark.",
             _obj({"experiment_id": {"type": "integer"}})),
    ToolSpec("get_backtests", "Backtest results (train/validation/out-of-sample) for a strategy key.",
             _obj({"strategy_key": {"type": "string"}})),
    ToolSpec("search_knowledge", "Search the curated trading knowledge library; returns excerpts with sources to cite.",
             _obj({"query": {"type": "string"}}, ["query"])),
    ToolSpec("get_events", "Upcoming earnings and economic releases.", _obj({"days": {"type": "integer"}, "symbol": {"type": "string"}})),
    ToolSpec("list_strategies", "Built-in strategy descriptions and parameters.", _obj({})),
]


class AnalystTools:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime

    async def execute(self, name: str, inp: dict[str, Any]) -> Any:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            raise ValueError(f"unknown tool {name}")
        return await fn(**inp)

    async def t_get_market_status(self) -> Any:
        return self.rt.status()

    async def t_get_quotes(self, symbols: list[str]) -> Any:
        snaps = await self.rt.md.get_snapshots([s.upper() for s in symbols[:20]])
        return {"quality": self.rt.md.provider.quality().to_dict(), "snapshots": {k: v.to_dict() for k, v in snaps.items()}}

    async def t_get_technicals(self, symbol: str) -> Any:
        bars = await self.rt.analysis.daily(symbol.upper())
        return technical_profile(bars)

    async def t_get_market_regime(self) -> Any:
        return await self.rt.analysis.regime()

    async def t_get_news(self, symbol: str) -> Any:
        return [n.to_dict() for n in await self.rt.analysis.news(symbol.upper())]

    async def t_evaluate_setups(self, symbol: str) -> Any:
        sym = symbol.upper()
        now = datetime.now(timezone.utc)
        bars = await self.rt.analysis.daily(sym, now)
        regime = await self.rt.analysis.regime()
        out = []
        with session_scope() as s:
            ctx = self.rt.analysis.context(s, sym, bars, regime, now)
            for key, cls in BUILTINS.items():
                if key in ("custom", "vwap_reclaim"):
                    continue
                st = cls()
                p, rec = await self.rt.analysis.evaluate(s, st, ctx, RiskConfig(), reference_portfolio(), now)
                if rec is None:
                    out.append({"strategy": key, "result": "no setup (conditions not met)"})
                else:
                    out.append({"strategy": key, "category": rec["steps"]["7_decision"]["category"],
                                "rationale": rec["steps"]["7_decision"]["rationale"], "thesis": rec["steps"]["3_thesis"]["thesis"],
                                "evidence": rec["steps"]["4_evidence"]["supporting"],
                                "objections": rec["steps"]["5_challenge"]["objections"],
                                "invalidation": rec["steps"]["5_challenge"]["what_would_prove_it_wrong"],
                                "plan": {k: rec["steps"]["6_risk"][k] for k in ("entry_type", "entry", "stop", "target", "reward_risk")}})
        return {"symbol": sym, "technicals_as_of": ctx.tech.get("as_of"), "results": out}

    async def t_get_signals(self, limit: int = 20, category: str | None = None, symbol: str | None = None) -> Any:
        with session_scope() as s:
            q = select(Signal).order_by(Signal.id.desc())
            if category:
                q = q.where(Signal.category == category)
            if symbol:
                q = q.where(Signal.symbol == symbol.upper())
            return [signal_to_dict(x) for x in s.execute(q.limit(min(limit, 50))).scalars()]

    async def t_get_paper_trades(self, experiment_id: int | None = None, status: str | None = None,
                                 symbol: str | None = None, since_days: int | None = None) -> Any:
        with session_scope() as s:
            q = select(Trade).order_by(Trade.id.desc())
            if experiment_id:
                q = q.where(Trade.experiment_id == experiment_id)
            if status:
                q = q.where(Trade.status == status)
            if symbol:
                q = q.where(Trade.symbol == symbol.upper())
            if since_days:
                q = q.where(Trade.entry_ts >= datetime.now(timezone.utc) - timedelta(days=since_days))
            return {"note": "All trades are simulated with hypothetical money.",
                    "trades": [trade_to_dict(t) for t in s.execute(q.limit(100)).scalars()]}

    async def t_get_trade_record(self, trade_id: int) -> Any:
        with session_scope() as s:
            t = s.get(Trade, trade_id)
            if t is None:
                return {"error": f"trade {trade_id} not found"}
            return trade_detail(s, t)

    async def t_get_performance(self, experiment_id: int | None = None) -> Any:
        with session_scope() as s:
            q = select(Experiment).where(Experiment.archived.is_(False))
            if experiment_id:
                q = q.where(Experiment.id == experiment_id)
            exps = [experiment_summary(s, e) for e in s.execute(q).scalars()]
            for e in exps:
                e.pop("armed_setups", None)
            return {"note": "Hypothetical paper-trading results; past performance does not predict future results.",
                    "experiments": exps}

    async def t_get_backtests(self, strategy_key: str | None = None) -> Any:
        with session_scope() as s:
            q = select(BacktestRun).order_by(BacktestRun.id.desc())
            if strategy_key:
                q = q.where(BacktestRun.strategy_key == strategy_key)
            return [{"id": b.id, "strategy": b.strategy_key, "version": b.strategy_version, "period": f"{b.start}..{b.end}",
                     "scenario": b.scenario, "segments": b.segments, "warnings": b.warnings, "data_source": b.data_source}
                    for b in s.execute(q.limit(10)).scalars()]

    async def t_search_knowledge(self, query: str) -> Any:
        with session_scope() as s:
            return retrieve(s, query, 4)

    async def t_get_events(self, days: int = 14, symbol: str | None = None) -> Any:
        with session_scope() as s:
            return upcoming_events(s, [symbol.upper()] if symbol else None, cal.et_date(datetime.now(timezone.utc)), min(days, 60))

    async def t_list_strategies(self) -> Any:
        return [create_strategy(k).describe() if k != "custom" else {"key": "custom", "description": BUILTINS[k].description}
                for k in BUILTINS]
