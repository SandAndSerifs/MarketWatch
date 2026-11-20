"""Paper trading: experiments, controls, trades, trade review, competition, emergency stop."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..ai.analyst import STANDARD_QUESTIONS, deterministic_answers, trade_question
from ..ai.provider import NoAIProvider, build_ai_provider
from ..data.providers.base import ProviderError
from ..data.universe import DEFAULT_UNIVERSE
from ..db import AppSetting, Decision, Experiment, Order, PendingSetup, Trade, audit, session_scope, utcnow
from ..paper.accounting import open_positions
from ..paper.execution import ExecutionConfig
from ..risk.manager import RiskConfig
from ..services.runtime import Runtime
from ..services.views import decision_to_dict, experiment_summary, order_to_dict, trade_detail, trade_to_dict
from ..strategies.library import BUILTINS, create_strategy
from .deps import not_found, rt

router = APIRouter(prefix="/api", tags=["paper-trading"])


class ExperimentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    strategy_key: str = "trend_pullback"
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    starting_capital: float = Field(10_000.0, ge=1_000, le=10_000_000)
    risk: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    universe: list[str] | None = None
    competition_group: str | None = None
    notes: str | None = None


def _create_experiment(s: Any, body: ExperimentIn) -> Experiment:
    if body.strategy_key not in BUILTINS:
        raise HTTPException(400, f"Unknown strategy {body.strategy_key}")
    try:
        strat = create_strategy(body.strategy_key, body.strategy_params)
        risk = RiskConfig.from_dict(body.risk)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    exe = ExecutionConfig.from_dict(body.execution)
    universe = sorted({u.upper().strip() for u in (body.universe or DEFAULT_UNIVERSE) if u.strip()})
    from ..backtest.service import _register_version

    _register_version(body.strategy_key, body.strategy_params)
    exp = Experiment(name=body.name, strategy_key=strat.key, strategy_version=strat.version, strategy_params=strat.params,
                     risk_config={"risk": {k: v for k, v in risk.to_dict().items() if k != "hard_rules"},
                                  "execution": exe.to_dict()},
                     universe=universe, starting_capital=body.starting_capital, cash=body.starting_capital,
                     status="stopped", competition_group=body.competition_group, notes=body.notes)
    s.add(exp)
    s.flush()
    audit(s, "user", "experiment_created", exp.id, strategy=strat.key, version=strat.version, capital=body.starting_capital)
    return exp


@router.get("/experiments")
def list_experiments(include_archived: bool = False) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(Experiment).order_by(Experiment.id.desc())
        if not include_archived:
            q = q.where(Experiment.archived.is_(False))
        return [experiment_summary(s, e) for e in s.execute(q).scalars()]


@router.post("/experiments")
def create_experiment(body: ExperimentIn) -> dict[str, Any]:
    with session_scope() as s:
        exp = _create_experiment(s, body)
        return experiment_summary(s, exp)


@router.get("/experiments/{exp_id}")
def get_experiment(exp_id: int) -> dict[str, Any]:
    with session_scope() as s:
        exp = s.get(Experiment, exp_id)
        if exp is None:
            raise not_found("experiment", exp_id)
        return experiment_summary(s, exp, with_curve=True)


@router.post("/experiments/{exp_id}/{action}")
async def control(exp_id: int, action: str, r: Runtime = Depends(rt)) -> dict[str, Any]:
    with session_scope() as s:
        exp = s.get(Experiment, exp_id)
        if exp is None:
            raise not_found("experiment", exp_id)
        kill = s.get(AppSetting, "kill_switch")
        if action in ("start", "resume") and kill and kill.value.get("active"):
            raise HTTPException(409, "Emergency STOP is active. Clear it first (Settings or Paper Trader page).")
        if action == "start":
            if exp.status not in ("stopped",):
                raise HTTPException(409, f"Cannot start from status {exp.status}")
            exp.status = "running"
            exp.started_at = exp.started_at or utcnow()
        elif action == "pause":
            if exp.status != "running":
                raise HTTPException(409, f"Cannot pause from status {exp.status}")
            exp.status = "paused"
        elif action == "resume":
            if exp.status not in ("paused", "halted"):
                raise HTTPException(409, f"Cannot resume from status {exp.status}")
            exp.status, exp.halted_reason = "running", None
        elif action == "stop":
            exp.status = "stopped"
            for ps in s.execute(select(PendingSetup).where(PendingSetup.experiment_id == exp_id, PendingSetup.status == "armed")).scalars():
                ps.status = "cancelled"
            for o in s.execute(select(Order).where(Order.experiment_id == exp_id, Order.side == "buy",
                                                   Order.status.in_(("new", "partially_filled")))).scalars():
                o.status = "cancelled"
        elif action == "archive":
            if open_positions(s, exp_id):
                raise HTTPException(409, "Close open positions before archiving")
            exp.status, exp.archived = "stopped", True
        elif action == "reset":
            if open_positions(s, exp_id):
                raise HTTPException(409, "Close open positions before resetting")
            exp.status, exp.archived = "stopped", True
            body = ExperimentIn(name=f"{exp.name} (reset {datetime.now(timezone.utc).date()})", strategy_key=exp.strategy_key,
                                strategy_params={k: v for k, v in exp.strategy_params.items()},
                                starting_capital=exp.starting_capital, risk=exp.risk_config.get("risk", {}),
                                execution=exp.risk_config.get("execution", {}), universe=exp.universe,
                                competition_group=exp.competition_group)
            new = _create_experiment(s, body)
            audit(s, "user", "experiment_reset", exp_id, new_experiment_id=new.id)
            return {"archived": exp_id, "new_experiment": experiment_summary(s, new)}
        elif action == "generate-setups":
            pass
        else:
            raise HTTPException(400, f"Unknown action {action}")
        audit(s, "user", f"experiment_{action}", exp_id)
        status = exp.status
    if action in ("start", "generate-setups") and r.md.configured:
        try:
            res = await r.engine.generate_setups(exp_id)
            return {"status": status, "setups": res}
        except ProviderError as e:
            return {"status": status, "setups_error": str(e)}
    return {"status": status}


@router.put("/experiments/{exp_id}/settings")
def update_settings(exp_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Changing a strategy/risk configuration is only allowed while stopped and creates an audit entry.
    Strategy parameter changes produce a new strategy version id."""
    with session_scope() as s:
        exp = s.get(Experiment, exp_id)
        if exp is None:
            raise not_found("experiment", exp_id)
        if exp.status != "stopped":
            raise HTTPException(409, "Stop the experiment before changing its configuration (no silent changes).")
        try:
            if "risk" in body:
                risk = RiskConfig.from_dict(body["risk"])
                exp.risk_config = {**exp.risk_config, "risk": {k: v for k, v in risk.to_dict().items() if k != "hard_rules"}}
            if "execution" in body:
                exp.risk_config = {**exp.risk_config, "execution": ExecutionConfig.from_dict(body["execution"]).to_dict()}
            if "strategy_params" in body:
                strat = create_strategy(exp.strategy_key, body["strategy_params"])
                exp.strategy_params, exp.strategy_version = strat.params, strat.version
            if "universe" in body:
                exp.universe = sorted({u.upper() for u in body["universe"]})
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        audit(s, "user", "experiment_settings_changed", exp_id, changes=list(body))
        return experiment_summary(s, exp)


@router.get("/experiments/{exp_id}/decisions")
def experiment_decisions(exp_id: int, limit: int = 100) -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = s.execute(select(Decision).where(Decision.experiment_id == exp_id).order_by(Decision.id.desc()).limit(limit)).scalars()
        return [{k: v for k, v in decision_to_dict(d).items() if k != "record"} |
                {"summary": d.record["steps"]["7_decision"]["rationale"],
                 "rejections": d.record["roles"]["risk_manager"]["rejections"]} for d in rows]


@router.get("/experiments/{exp_id}/orders")
def experiment_orders(exp_id: int, limit: int = 200) -> list[dict[str, Any]]:
    with session_scope() as s:
        return [order_to_dict(o) for o in s.execute(select(Order).where(Order.experiment_id == exp_id)
                                                   .order_by(Order.id.desc()).limit(limit)).scalars()]


@router.post("/emergency-stop")
async def emergency_stop(body: dict[str, Any] | None = None, r: Runtime = Depends(rt)) -> dict[str, Any]:
    return await r.engine.emergency_stop(bool((body or {}).get("flatten", False)))


@router.post("/emergency-stop/clear")
def clear_emergency(r: Runtime = Depends(rt)) -> dict[str, Any]:
    r.engine.clear_emergency_stop()
    return {"cleared": True, "note": "Experiments stay halted until you resume them individually."}


# ------------------------------------------------------------------ trades
@router.get("/trades")
def list_trades(experiment_id: int | None = None, status: str | None = None, symbol: str | None = None,
                limit: int = 300) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(Trade).order_by(Trade.id.desc())
        if experiment_id:
            q = q.where(Trade.experiment_id == experiment_id)
        if status:
            q = q.where(Trade.status == status)
        if symbol:
            q = q.where(Trade.symbol == symbol.upper())
        names = {e.id: e.name for e in s.execute(select(Experiment)).scalars()}
        return [trade_to_dict(t) | {"experiment_name": names.get(t.experiment_id)} for t in s.execute(q.limit(limit)).scalars()]


@router.get("/trades/{trade_id}")
async def get_trade(trade_id: int, r: Runtime = Depends(rt)) -> dict[str, Any]:
    with session_scope() as s:
        t = s.get(Trade, trade_id)
        if t is None:
            raise not_found("trade", trade_id)
        detail = trade_detail(s, t)
        entry_ts, exit_ts, sym = t.entry_ts, t.exit_ts, t.symbol
    detail["standard_answers"] = deterministic_answers(detail)
    detail["standard_questions"] = STANDARD_QUESTIONS
    try:
        end = (exit_ts or datetime.now(timezone.utc)) + timedelta(days=20)
        start = entry_ts - timedelta(days=120)
        bars = await r.md._call(r.md.provider.get_bars([sym], "1Day", start, min(end, datetime.now(timezone.utc))))
        detail["chart_bars"] = [b.to_dict() for b in bars.get(sym, [])]
    except ProviderError as e:
        detail["chart_bars"], detail["chart_error"] = [], str(e)
    return detail


class Question(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)


@router.post("/trades/{trade_id}/ask")
async def ask_trade(trade_id: int, body: Question, r: Runtime = Depends(rt)) -> dict[str, Any]:
    provider = build_ai_provider(r.settings)
    try:
        return await trade_question(None if isinstance(provider, NoAIProvider) else provider, trade_id, body.question)
    except KeyError:
        raise not_found("trade", trade_id) from None


@router.post("/trades/{trade_id}/close")
async def close_trade(trade_id: int, r: Runtime = Depends(rt)) -> dict[str, Any]:
    """Manually close a paper position at the current simulated market price."""
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        t = s.get(Trade, trade_id)
        if t is None or t.status != "open":
            raise HTTPException(409, "Trade is not open")
        exp = s.get(Experiment, t.experiment_id)
        pos = next((p for p in open_positions(s, t.experiment_id) if p.symbol == t.symbol), None)
        if pos is None or exp is None:
            raise HTTPException(409, "No open position")
        fresh, reason = r.md.quote_freshness(t.symbol, now)
        if not fresh:
            try:
                await r.md.get_snapshots([t.symbol])
            except ProviderError:
                pass
            fresh, reason = r.md.quote_freshness(t.symbol, now)
        if not fresh:
            raise HTTPException(409, f"Cannot simulate a fill without a fresh price: {reason}")
        await r.engine._exit(s, exp, pos, t, "Manual close by user", "manual", now)
        audit(s, "user", "manual_close", exp.id, trade_id=trade_id)
        return trade_to_dict(t)


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: int) -> dict[str, Any]:
    with session_scope() as s:
        d = s.get(Decision, decision_id)
        if d is None:
            raise not_found("decision", decision_id)
        return decision_to_dict(d)


# ------------------------------------------------------------- competition
class CompetitionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    strategies: list[dict[str, Any]] = Field(default_factory=lambda: [
        {"strategy_key": "momentum"}, {"strategy_key": "breakout"}, {"strategy_key": "mean_reversion"},
        {"strategy_key": "trend_pullback"}])
    starting_capital: float = 10_000.0
    risk: dict[str, Any] = Field(default_factory=dict)
    universe: list[str] | None = None
    start_now: bool = True


@router.post("/competitions")
async def create_competition(body: CompetitionIn, r: Runtime = Depends(rt)) -> dict[str, Any]:
    ids = []
    with session_scope() as s:
        if s.execute(select(Experiment).where(Experiment.competition_group == body.name)).first():
            raise HTTPException(409, "A competition with this name exists")
        for i, st in enumerate(body.strategies):
            label = chr(ord("A") + i)
            exp = _create_experiment(s, ExperimentIn(
                name=f"{body.name} - Agent {label}: {BUILTINS[st['strategy_key']].name}", strategy_key=st["strategy_key"],
                strategy_params=st.get("params", {}), starting_capital=body.starting_capital, risk=body.risk,
                universe=body.universe, competition_group=body.name))
            if body.start_now:
                exp.status, exp.started_at = "running", utcnow()
            ids.append(exp.id)
    if body.start_now and r.md.configured:
        asyncio.create_task(_gen_all(r, ids))
    return {"competition": body.name, "experiment_ids": ids}


async def _gen_all(r: Runtime, ids: list[int]) -> None:
    for i in ids:
        try:
            await r.engine.generate_setups(i)
        except Exception:
            pass


@router.get("/competitions")
def list_competitions() -> list[dict[str, Any]]:
    with session_scope() as s:
        groups = sorted({g for (g,) in s.execute(select(Experiment.competition_group).where(
            Experiment.competition_group.is_not(None))).all()})
        return [leaderboard(g) for g in groups]


@router.get("/competitions/{name}")
def leaderboard(name: str) -> dict[str, Any]:
    with session_scope() as s:
        exps = list(s.execute(select(Experiment).where(Experiment.competition_group == name)).scalars())
        if not exps:
            raise not_found("competition", name)
        rows = []
        for e in exps:
            sm = experiment_summary(s, e, with_curve=True)
            ts = sm["stats"]["trade_stats"]
            rows.append({"experiment_id": e.id, "name": e.name, "strategy_key": e.strategy_key,
                         "strategy_version": e.strategy_version, "status": e.status, "archived": e.archived,
                         "equity": sm["equity"], "total_return_pct": sm["stats"]["total_return_pct"],
                         "max_drawdown_pct": sm["stats"]["max_drawdown_pct"], "sharpe": sm["stats"].get("sharpe"),
                         "sortino": sm["stats"].get("sortino"), "win_rate": ts.get("win_rate"), "trades": ts.get("trades"),
                         "profit_factor": ts.get("profit_factor"), "score": sm["score"], "sample_warning": ts.get("sample_warning"),
                         "equity_curve": sm.get("equity_curve", []), "started_at": sm["started_at"],
                         "benchmark": sm["stats"].get("benchmark")})
        rows.sort(key=lambda x: -x["score"]["score"])
        return {"name": name, "rows": rows, "ranking": "risk-adjusted score (not raw return)",
                "identical_rules": "Same starting capital, risk limits and universe unless changed at creation."}
