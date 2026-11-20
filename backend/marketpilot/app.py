"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .config import Settings, get_settings
from .data.providers.base import NotSupported, ProviderError, ProviderNotConfigured
from .db import StrategyVersion, Watchlist, WatchlistItem, init_engine, session_scope
from .events.calendar import seed_macro_events
from .knowledge.store import seed_knowledge
from .services.runtime import Runtime
from .strategies.library import BUILTINS

log = logging.getLogger("marketpilot")


def seed(s: Any) -> None:
    seed_macro_events(s)
    seed_knowledge(s)
    if not s.execute(select(Watchlist)).first():
        w = Watchlist(name="Core")
        for sym in ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM"):
            w.items.append(WatchlistItem(symbol=sym))
        s.add(w)
    for key, cls in BUILTINS.items():
        if key == "custom":
            continue
        if not s.execute(select(StrategyVersion).where(StrategyVersion.strategy_key == key,
                                                       StrategyVersion.version == cls.version)).first():
            s.add(StrategyVersion(strategy_key=key, version=cls.version, params=cls.default_params(), status="testing",
                                  change_reason="Built-in baseline (conventional parameters, not optimised)",
                                  created_by="system"))


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        init_engine(settings.database_url)
        with session_scope() as s:
            seed(s)
        rt = runtime or Runtime(settings)
        app.state.runtime = rt
        await rt.start()
        log.info("MarketPilot started (paper trading only). Data: %s", rt.md.provider.quality().label)
        yield
        await rt.stop()

    app = FastAPI(title="MarketPilot API", version="0.1.0", lifespan=lifespan,
                  description="Market intelligence and PAPER trading. No real-money order execution exists in this codebase.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ProviderNotConfigured)
    async def _nc(_: Request, exc: ProviderNotConfigured) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc), "code": "provider_not_configured"})

    @app.exception_handler(NotSupported)
    async def _ns(_: Request, exc: NotSupported) -> JSONResponse:
        return JSONResponse(status_code=501, content={"detail": str(exc), "code": "not_supported"})

    @app.exception_handler(ProviderError)
    async def _pe(_: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc), "code": "provider_error"})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "paper_trading_only": True}

    @app.get("/api/status")
    def status(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.status()

    from .api import market, misc, research, trading

    for r in (market.router, trading.router, research.router, misc.router):
        app.include_router(r)
    return app
