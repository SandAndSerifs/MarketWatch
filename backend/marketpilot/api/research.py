"""Strategy Lab, backtests, scenarios, versions, knowledge library, events, reports."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..backtest.service import SCENARIOS, backtest_to_dict, run_optimization, start_backtest
from ..data.universe import DEFAULT_UNIVERSE
from ..db import BacktestRun, KnowledgeDoc, MarketEvent, StrategyVersion, audit, session_scope
from ..events.calendar import event_to_dict, refresh_earnings_finnhub, upcoming_events
from ..knowledge.store import build_index, doc_to_dict
from ..services.reports import performance_report, weekly_strategy_review
from ..services.runtime import Runtime
from ..strategies.library import BUILTINS, create_strategy, list_strategies
from .deps import not_found, rt

router = APIRouter(prefix="/api", tags=["research"])


@router.get("/strategies")
def strategies() -> list[dict[str, Any]]:
    return list_strategies()


@router.get("/strategies/versions")
def versions(strategy_key: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(StrategyVersion).order_by(StrategyVersion.id.desc())
        if strategy_key:
            q = q.where(StrategyVersion.strategy_key == strategy_key)
        return [{"id": v.id, "strategy_key": v.strategy_key, "version": v.version, "params": v.params, "status": v.status,
                 "parent_version": v.parent_version, "change_reason": v.change_reason, "created_by": v.created_by,
                 "created_at": v.created_at.isoformat(), "evidence": v.evidence} for v in s.execute(q).scalars()]


class VersionIn(BaseModel):
    strategy_key: str
    params: dict[str, Any]
    change_reason: str = Field(..., min_length=3)
    created_by: str = "user"


@router.post("/strategies/versions")
def create_version(body: VersionIn) -> dict[str, Any]:
    try:
        strat = create_strategy(body.strategy_key, body.params)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    with session_scope() as s:
        existing = s.execute(select(StrategyVersion).where(StrategyVersion.strategy_key == strat.key,
                                                           StrategyVersion.version == strat.version)).scalar_one_or_none()
        if existing:
            return {"id": existing.id, "version": existing.version, "status": existing.status, "existing": True}
        v = StrategyVersion(strategy_key=strat.key, version=strat.version, params=strat.params, status="draft",
                            parent_version=type(strat).version, change_reason=body.change_reason,
                            created_by=body.created_by if body.created_by in ("user", "ai-proposal") else "user")
        s.add(v)
        s.flush()
        audit(s, body.created_by, "strategy_version_created", None, key=strat.key, version=strat.version)
        return {"id": v.id, "version": v.version, "status": v.status}


@router.post("/strategies/versions/{vid}/status")
def set_version_status(vid: int, body: dict[str, Any]) -> dict[str, Any]:
    status = body.get("status")
    if status not in ("draft", "testing", "approved", "retired"):
        raise HTTPException(400, "invalid status")
    with session_scope() as s:
        v = s.get(StrategyVersion, vid)
        if v is None:
            raise not_found("version", vid)
        if status == "approved":
            bts = s.execute(select(BacktestRun).where(BacktestRun.strategy_key == v.strategy_key,
                                                      BacktestRun.strategy_version == v.version,
                                                      BacktestRun.status == "complete")).scalars().all()
            if not any(b.segments.get("test") for b in bts):
                raise HTTPException(409, "Approval requires a completed backtest with an out-of-sample test segment "
                                         "for this exact version (forward paper results are also recommended).")
            v.evidence = {**(v.evidence or {}), "backtests": [b.id for b in bts]}
        v.status = status
        audit(s, "user", "strategy_version_status", None, version_id=vid, status=status)
        return {"id": vid, "status": status}


class BacktestIn(BaseModel):
    strategy_key: str = "trend_pullback"
    params: dict[str, Any] = Field(default_factory=dict)
    universe: list[str] | None = None
    start: date = date(2019, 1, 2)
    end: date = date(2025, 12, 31)
    risk: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    starting_capital: float = 10_000.0


@router.post("/backtests")
async def run_bt(body: BacktestIn, r: Runtime = Depends(rt)) -> dict[str, Any]:
    if body.strategy_key not in BUILTINS:
        raise HTTPException(400, "unknown strategy")
    if not BUILTINS[body.strategy_key].backtestable:
        raise HTTPException(400, "This strategy is intraday and forward-test only")
    try:
        create_strategy(body.strategy_key, body.params)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not r.md.configured:
        raise HTTPException(503, "Backtests need genuine historical data: configure a market data provider first.")
    run_id = await start_backtest(r.md, body.strategy_key, body.params, body.universe or DEFAULT_UNIVERSE, body.start,
                                  body.end, body.risk, body.execution, body.starting_capital)
    return {"id": run_id, "status": "running"}


@router.get("/backtests")
def list_bt(strategy_key: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(BacktestRun).order_by(BacktestRun.id.desc()).limit(100)
        if strategy_key:
            q = q.where(BacktestRun.strategy_key == strategy_key)
        return [backtest_to_dict(b) for b in s.execute(q).scalars()]


@router.get("/backtests/{bid}")
def get_bt(bid: int) -> dict[str, Any]:
    with session_scope() as s:
        b = s.get(BacktestRun, bid)
        if b is None:
            raise not_found("backtest", bid)
        return backtest_to_dict(b, full=True)


class OptimizeIn(BaseModel):
    strategy_key: str
    grid: dict[str, list[Any]]
    universe: list[str] | None = None
    start: date = date(2019, 1, 2)
    end: date = date(2025, 12, 31)


@router.post("/backtests/optimize")
async def optimize(body: OptimizeIn, r: Runtime = Depends(rt)) -> dict[str, Any]:
    n = 1
    for v in body.grid.values():
        n *= len(v)
    if n > 40:
        raise HTTPException(400, f"Grid has {n} combinations; the limit is 40 to curb overfitting.")
    return await run_optimization(r.md, body.strategy_key, body.grid, body.universe or DEFAULT_UNIVERSE[:40], body.start, body.end)


@router.get("/scenarios")
def scenarios() -> dict[str, Any]:
    return SCENARIOS


class ScenarioIn(BaseModel):
    strategy_key: str = "trend_pullback"
    params: dict[str, Any] = Field(default_factory=dict)
    scenarios: list[str] = Field(default_factory=lambda: list(SCENARIOS))
    universe: list[str] | None = None


@router.post("/scenarios/run")
async def run_scenarios(body: ScenarioIn, r: Runtime = Depends(rt)) -> dict[str, Any]:
    if not r.md.configured:
        raise HTTPException(503, "Configure a market data provider first.")
    ids = {}
    for key in body.scenarios:
        sc = SCENARIOS.get(key)
        if not sc:
            raise HTTPException(400, f"unknown scenario {key}")
        ids[key] = await start_backtest(r.md, body.strategy_key, body.params, body.universe or DEFAULT_UNIVERSE,
                                        date.fromisoformat(sc["start"]), date.fromisoformat(sc["end"]), scenario=key)
    return {"runs": ids}


# --------------------------------------------------------------- knowledge
@router.get("/knowledge")
def knowledge(q: str | None = None, category: str | None = None) -> dict[str, Any]:
    with session_scope() as s:
        if q:
            results = build_index(s).search(q, 20, category)
            return {"results": [{k: v for k, v in d.items() if k != "body"} for d in results]}
        query = select(KnowledgeDoc).order_by(KnowledgeDoc.category, KnowledgeDoc.title)
        if category:
            query = query.where(KnowledgeDoc.category == category)
        docs = [doc_to_dict(d, with_body=False) for d in s.execute(query).scalars()]
        cats = sorted({d["category"] for d in docs})
        return {"results": docs, "categories": cats}


@router.get("/knowledge/{slug}")
def knowledge_doc(slug: str) -> dict[str, Any]:
    with session_scope() as s:
        d = s.execute(select(KnowledgeDoc).where(KnowledgeDoc.slug == slug)).scalar_one_or_none()
        if d is None:
            raise not_found("document", slug)
        return doc_to_dict(d)


class KnowledgeIn(BaseModel):
    title: str = Field(..., min_length=3)
    category: str
    body: str = Field(..., min_length=20)
    sources: list[dict[str, Any]] = Field(..., min_length=1, description="Each source needs title/authors/year/type")
    tags: list[str] = Field(default_factory=list)


@router.post("/knowledge")
def add_knowledge(body: KnowledgeIn) -> dict[str, Any]:
    import re

    slug = "user-" + re.sub(r"[^a-z0-9]+", "-", body.title.lower()).strip("-")[:100]
    with session_scope() as s:
        if s.execute(select(KnowledgeDoc).where(KnowledgeDoc.slug == slug)).first():
            raise HTTPException(409, "A document with this title exists")
        d = KnowledgeDoc(slug=slug, title=body.title, category=body.category, summary=body.body[:400], body=body.body,
                         sources=body.sources, tags=body.tags, updated_at=date.today().isoformat(), origin="user")
        s.add(d)
        s.flush()
        return doc_to_dict(d)


# ------------------------------------------------------------------- events
@router.get("/events")
def events(days: int = 30, symbol: str | None = None) -> list[dict[str, Any]]:
    from datetime import datetime, timezone

    from ..data.calendar import et_date

    with session_scope() as s:
        return upcoming_events(s, [symbol.upper()] if symbol else None, et_date(datetime.now(timezone.utc)), min(days, 120))


class EventIn(BaseModel):
    kind: str = Field(..., pattern="^(earnings|macro)$")
    name: str
    date: date
    time_et: str | None = None
    symbol: str = "*"
    importance: str = Field("high", pattern="^(high|medium|low)$")
    source: str = Field(..., min_length=2)
    source_url: str | None = None


@router.post("/events")
def add_event(body: EventIn) -> dict[str, Any]:
    with session_scope() as s:
        e = MarketEvent(kind=body.kind, name=body.name, date=body.date.isoformat(), time_et=body.time_et,
                        symbol=body.symbol.upper() if body.kind == "earnings" else "*", importance=body.importance,
                        source=body.source, source_url=body.source_url, verified_at=date.today().isoformat(),
                        details={"added_by": "user"})
        s.add(e)
        s.flush()
        return event_to_dict(e)


@router.delete("/events/{eid}")
def delete_event(eid: int) -> dict[str, Any]:
    with session_scope() as s:
        e = s.get(MarketEvent, eid)
        if e is None:
            raise not_found("event", eid)
        s.delete(e)
        return {"deleted": eid}


@router.post("/events/refresh-earnings")
async def refresh_earnings(r: Runtime = Depends(rt)) -> dict[str, Any]:
    if not r.settings.finnhub_api_key:
        raise HTTPException(503, "Set FINNHUB_API_KEY (free tier available) to load earnings dates.")
    with session_scope() as s:
        return await refresh_earnings_finnhub(s, r.settings.finnhub_api_key.get_secret_value(),
                                              sorted(set(DEFAULT_UNIVERSE) | set(r.scanner.universe())))


# ------------------------------------------------------------------- reports
@router.get("/reports/performance/{experiment_id}")
def perf_report(experiment_id: int, period: str = "weekly") -> dict[str, Any]:
    if period not in ("daily", "weekly", "monthly"):
        raise HTTPException(400, "period must be daily, weekly or monthly")
    with session_scope() as s:
        try:
            return performance_report(s, experiment_id, period)
        except KeyError:
            raise not_found("experiment", experiment_id) from None


@router.get("/reports/strategy-review")
def strategy_review(days: int = 7) -> dict[str, Any]:
    with session_scope() as s:
        return weekly_strategy_review(s, days)
