"""Login / logout / status for public (remote) mode."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import COOKIE, SESSION_SECONDS, client_ip, is_https

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str = Field(..., min_length=1, max_length=500)


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    sm = request.app.state.sessions
    return {"required": sm.required, "authenticated": (not sm.required) or sm.valid(request.cookies.get(COOKIE))}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    sm = request.app.state.sessions
    if not sm.required:
        return {"ok": True, "required": False}
    ok, reason = sm.check_password(body.password, client_ip(request.headers, request.client.host if request.client else None))
    if reason == "too_many_attempts":
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    if not ok:
        raise HTTPException(401, "Wrong password")
    response.set_cookie(COOKIE, sm.issue(), max_age=SESSION_SECONDS, httponly=True, samesite="strict",
                        secure=is_https(request.headers, request.url.scheme), path="/")
    return {"ok": True}


@router.post("/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
