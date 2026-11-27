"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .auth import COOKIE, SessionManager, path_is_open, validate_settings, via_cloudflare
from .config import Settings, get_settings
from .data.providers.base import NotSupported, ProviderError, ProviderNotConfigured
from .db import AppSetting, StrategyVersion, Watchlist, WatchlistItem, init_engine, session_scope
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


def _server_secret(settings: Settings) -> str:
    if settings.session_secret:
        return settings.session_secret.get_secret_value()
    import secrets

    with session_scope() as s:
        row = s.get(AppSetting, "session_secret")
        if row is None:
            row = AppSetting(key="session_secret", value={"v": secrets.token_hex(32)})
            s.add(row)
        return row.value["v"]


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or get_settings()
    validate_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        init_engine(settings.database_url)
        with session_scope() as s:
            seed(s)
        app.state.sessions = SessionManager(settings, _server_secret(settings))
        rt = runtime or Runtime(settings)
        app.state.runtime = rt
        await rt.start()
        log.info("MarketPilot started (paper trading only). Data: %s", rt.md.provider.quality().label)
        yield
        await rt.stop()

    app = FastAPI(title="MarketPilot API", version="0.1.0", lifespan=lifespan,
                  description="Market intelligence and PAPER trading. No real-money order execution exists in this codebase.")
    @app.middleware("http")
    async def _errors_as_json(request: Request, call_next):  # type: ignore[no-untyped-def]
        # Registered before CORS so it runs *inside* it: unexpected errors still carry CORS
        # headers and reach the UI as a readable message instead of an opaque CORS failure.
        try:
            return await call_next(request)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("unhandled error on %s", request.url.path)
            return JSONResponse(status_code=500, content={"detail": f"Internal error: {type(exc).__name__}: {exc}"[:500],
                                                          "code": "internal_error"})

    @app.middleware("http")
    async def _auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not settings.public_mode and via_cloudflare(request.headers):
            return JSONResponse(status_code=403, content={
                "detail": "Remote access is disabled. Start MarketPilot in public mode (scripts/start-public) "
                          "with APP_PASSWORD set.", "code": "remote_disabled"})
        if settings.public_mode and request.method != "OPTIONS" and not path_is_open(request.url.path):
            sessions = getattr(request.app.state, "sessions", None)
            if sessions is None or not sessions.valid(request.cookies.get(COOKIE)):
                return JSONResponse(status_code=401, content={"detail": "Sign in required", "code": "auth_required"})
        return await call_next(request)

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

    from .api import auth as auth_api
    from .api import market, misc, research, trading

    for r in (auth_api.router, market.router, trading.router, research.router, misc.router):
        app.include_router(r)
    return app
