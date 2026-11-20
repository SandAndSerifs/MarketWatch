from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from ..services.runtime import Runtime


def rt(request: Request) -> Runtime:
    return request.app.state.runtime


def not_found(what: str, ident: Any) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} {ident} not found")
