"""Watchlists, scanner, alerts, AI analyst, settings, brokerage status, WebSocket."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from ..ai.analyst import analyst_chat
from ..ai.provider import AINotConfigured, build_ai_provider
from ..alerts.service import alert_to_dict, get_prefs, set_prefs
from ..brokerage import robinhood
from ..db import AiMessage, Alert, AppSetting, Decision, Signal, Watchlist, WatchlistItem, session_scope
from ..paper.execution import ExecutionConfig
from ..risk.manager import HARD_CEILINGS, RiskConfig
from ..services.runtime import Runtime
from ..services.scanner import DEFAULT_SCANNER, scanner_settings, signal_to_dict
from ..services.views import decision_to_dict
from .deps import not_found, rt

router = APIRouter(prefix="/api", tags=["misc"])


# --------------------------------------------------------------- watchlists
def _wl(w: Watchlist) -> dict[str, Any]:
    return {"id": w.id, "name": w.name, "items": [{"id": i.id, "symbol": i.symbol, "note": i.note,
                                                   "added_at": i.added_at.isoformat()} for i in w.items]}


@router.get("/watchlists")
def watchlists() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [_wl(w) for w in s.execute(select(Watchlist).order_by(Watchlist.id)).scalars()]


@router.post("/watchlists")
def create_watchlist(body: dict[str, Any]) -> dict[str, Any]:
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    with session_scope() as s:
        if s.execute(select(Watchlist).where(Watchlist.name == name)).first():
            raise HTTPException(409, "exists")
        w = Watchlist(name=name)
        s.add(w)
        s.flush()
        return _wl(w)


@router.delete("/watchlists/{wid}")
def delete_watchlist(wid: int) -> dict[str, Any]:
    with session_scope() as s:
        w = s.get(Watchlist, wid)
        if w is None:
            raise not_found("watchlist", wid)
        s.delete(w)
        return {"deleted": wid}


@router.post("/watchlists/{wid}/items")
def add_item(wid: int, body: dict[str, Any], r: Runtime = Depends(rt)) -> dict[str, Any]:
    sym = (body.get("symbol") or "").upper().strip()
    if not sym or len(sym) > 12 or not all(c.isalnum() or c in ".-" for c in sym):
        raise HTTPException(400, "invalid symbol")
    with session_scope() as s:
        w = s.get(Watchlist, wid)
        if w is None:
            raise not_found("watchlist", wid)
        if any(i.symbol == sym for i in w.items):
            raise HTTPException(409, "already in watchlist")
        w.items.append(WatchlistItem(symbol=sym, note=body.get("note")))
        s.flush()
        r.md.watch([sym])
        return _wl(w)


@router.delete("/watchlists/{wid}/items/{symbol}")
def remove_item(wid: int, symbol: str) -> dict[str, Any]:
    with session_scope() as s:
        w = s.get(Watchlist, wid)
        if w is None:
            raise not_found("watchlist", wid)
        for i in list(w.items):
            if i.symbol == symbol.upper():
                w.items.remove(i)
        return _wl(w)


# ------------------------------------------------------------------ scanner
@router.post("/scanner/run")
async def run_scan(r: Runtime = Depends(rt)) -> dict[str, Any]:
    return await r.scanner.full_scan()


@router.get("/scanner/signals")
def signals(category: str | None = None, symbol: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(Signal).order_by(Signal.id.desc())
        if category:
            q = q.where(Signal.category == category)
        if symbol:
            q = q.where(Signal.symbol == symbol.upper())
        return [signal_to_dict(x) for x in s.execute(q.limit(min(limit, 500))).scalars()]


@router.get("/signals/{sid}")
def signal_detail(sid: int) -> dict[str, Any]:
    with session_scope() as s:
        sig = s.get(Signal, sid)
        if sig is None:
            raise not_found("signal", sid)
        d = s.get(Decision, sig.decision_id) if sig.decision_id else None
        return {"signal": signal_to_dict(sig), "decision": decision_to_dict(d) if d else None}


@router.get("/scanner/settings")
def get_scanner_settings() -> dict[str, Any]:
    with session_scope() as s:
        return scanner_settings(s)


@router.put("/scanner/settings")
def put_scanner_settings(body: dict[str, Any]) -> dict[str, Any]:
    from ..strategies.library import BUILTINS

    with session_scope() as s:
        cur = scanner_settings(s)
        new = {**cur, **{k: v for k, v in body.items() if k in DEFAULT_SCANNER}}
        bad = [k for k in new["strategies"] if k not in BUILTINS or k == "custom"]
        if bad:
            raise HTTPException(400, f"unknown strategies {bad}")
        new["extra_symbols"] = sorted({x.upper() for x in new["extra_symbols"]})
        s.merge(AppSetting(key="scanner", value=new))
        return new


# ------------------------------------------------------------------- alerts
@router.get("/alerts")
def alerts(unread: bool = False, kind: str | None = None, limit: int = 200) -> dict[str, Any]:
    with session_scope() as s:
        q = select(Alert).order_by(Alert.id.desc())
        if unread:
            q = q.where(Alert.read.is_(False))
        if kind:
            q = q.where(Alert.kind == kind)
        rows = [alert_to_dict(a) for a in s.execute(q.limit(min(limit, 500))).scalars()]
        n_unread = len(s.execute(select(Alert.id).where(Alert.read.is_(False))).all())
        return {"alerts": rows, "unread": n_unread}


@router.post("/alerts/{aid}/read")
def mark_read(aid: int) -> dict[str, Any]:
    with session_scope() as s:
        a = s.get(Alert, aid)
        if a is None:
            raise not_found("alert", aid)
        a.read = True
        return {"id": aid, "read": True}


@router.post("/alerts/read-all")
def mark_all_read() -> dict[str, Any]:
    with session_scope() as s:
        s.execute(update(Alert).where(Alert.read.is_(False)).values(read=True))
        return {"ok": True}


@router.get("/alerts/prefs")
def alert_prefs() -> dict[str, Any]:
    with session_scope() as s:
        return get_prefs(s)


@router.put("/alerts/prefs")
def put_alert_prefs(body: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        return set_prefs(s, body)


# ---------------------------------------------------------------------- AI
class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = None


@router.post("/ai/chat")
async def chat(body: ChatIn, r: Runtime = Depends(rt)) -> dict[str, Any]:
    provider = build_ai_provider(r.settings)
    cid = body.conversation_id or uuid.uuid4().hex
    try:
        res = await analyst_chat(r, provider, cid, body.message)
    except AINotConfigured as e:
        raise HTTPException(503, str(e)) from e
    return {"conversation_id": cid, **res}


@router.get("/ai/conversations/{cid}")
def conversation(cid: str) -> list[dict[str, Any]]:
    with session_scope() as s:
        return [{"role": m.role, "content": m.content, "ts": m.ts.isoformat(), "meta": m.meta}
                for m in s.execute(select(AiMessage).where(AiMessage.conversation_id == cid).order_by(AiMessage.id)).scalars()]


# ----------------------------------------------------------------- settings
@router.get("/settings")
def settings_view(r: Runtime = Depends(rt)) -> dict[str, Any]:
    st = r.settings
    return {
        "paper_trading_only": True,
        "market_data": {"provider": st.market_data_provider, "alpaca_keys_configured": st.has_alpaca(),
                        "alpaca_feed": st.alpaca_feed, "massive_key_configured": st.has_massive(),
                        "massive_realtime": st.massive_realtime, "quality": r.md.provider.quality().to_dict(),
                        "stale_quote_seconds": st.stale_quote_seconds},
        "earnings": {"finnhub_key_configured": bool(st.finnhub_api_key)},
        "ai": {"provider": st.ai_provider, "configured": bool(st.anthropic_api_key), "model": st.ai_model, "effort": st.ai_effort},
        "notifications": {"email_configured": bool(st.smtp_host and st.alert_email_to),
                          "webhook_configured": bool(st.alert_webhook_url)},
        "brokerage": robinhood.status(),
        "database": "postgresql" if st.database_url.startswith("postgresql") else "sqlite",
        "risk_defaults": RiskConfig().to_dict(), "risk_hard_ceilings": HARD_CEILINGS,
        "execution_defaults": ExecutionConfig().to_dict(),
        "how_to_configure": "Edit backend/.env (see backend/.env.example) and restart the backend.",
    }


@router.get("/brokerage/status")
def brokerage_status() -> dict[str, Any]:
    return robinhood.status()


@router.get("/brokerage/portfolio")
async def brokerage_portfolio() -> dict[str, Any]:
    try:
        client = robinhood.get_client()
        return {"read_only": True, "portfolio": await client.call("get_portfolio"),
                "positions": await client.call("get_equity_positions")}
    except robinhood.BrokerageDisabled as e:
        raise HTTPException(503, str(e)) from e


# ---------------------------------------------------------------- websocket
@router.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    runtime: Runtime = websocket.app.state.runtime
    q = runtime.md.hub.subscribe()
    await websocket.send_json({"type": "hello", "data": runtime.status()})

    async def reader() -> None:
        while True:
            msg = await websocket.receive_json()
            syms = msg.get("subscribe") if isinstance(msg, dict) else None
            if isinstance(syms, list):
                runtime.md.watch([str(x).upper()[:12] for x in syms[:50]])

    rtask = asyncio.create_task(reader())
    try:
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=25)
                await websocket.send_json(item)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
            if rtask.done():
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        rtask.cancel()
        runtime.md.hub.unsubscribe(q)
