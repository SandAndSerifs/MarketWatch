"""OPTIONAL, READ-ONLY Robinhood connector (disabled by default).

Robinhood's officially supported agent integration is its Trading MCP server
(https://agent.robinhood.com/mcp/trading, launched May 2026). It grants read access to
the user's accounts and can place orders in a separate "agentic" account.

MarketPilot's policy:
  * Disabled unless ROBINHOOD_MCP_ENABLED=true.
  * Authentication uses an OAuth access token obtained through Robinhood's own
    authorization flow (ROBINHOOD_MCP_TOKEN). MarketPilot never asks for or stores a
    Robinhood username/password.
  * Only tools on READ_ONLY_TOOLS can be called. Any order/alert/watchlist-mutating tool
    is refused in code before a request is made.
  * Completely independent of paper trading: nothing in `paper/` imports this module.

STATUS: experimental. The JSON-RPC handshake follows the MCP streamable-HTTP spec but has
not been verified against the live Robinhood endpoint from this development environment.
"""
from __future__ import annotations

import itertools
from typing import Any

import httpx

from ..config import get_settings

READ_ONLY_TOOLS = frozenset({
    "get_accounts", "get_portfolio", "get_equity_positions", "get_equity_orders", "get_pnl_trade_history",
    "get_realized_pnl", "get_equity_tax_lots", "get_equity_quotes", "get_watchlists", "get_watchlist_items",
})

FORBIDDEN_SUBSTRINGS = ("place_", "cancel_", "exercise_", "review_", "create_", "update_", "delete_", "add_",
                        "remove_", "follow_", "unfollow_", "mark_", "decline_", "set_")


class BrokerageDisabled(RuntimeError):
    pass


class ForbiddenBrokerageAction(PermissionError):
    pass


def assert_read_only(tool: str) -> None:
    if tool not in READ_ONLY_TOOLS or any(tool.startswith(p) for p in FORBIDDEN_SUBSTRINGS):
        raise ForbiddenBrokerageAction(f"MarketPilot only permits read-only brokerage tools; '{tool}' is blocked.")


class RobinhoodReadOnly:
    def __init__(self, url: str, token: str, client: httpx.AsyncClient | None = None) -> None:
        self.url = url
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
                         "Content-Type": "application/json"}
        self._client = client or httpx.AsyncClient(timeout=30)
        self._ids = itertools.count(1)
        self._session: str | None = None

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        headers = dict(self._headers)
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        r = await self._client.post(self.url, json={"jsonrpc": "2.0", "id": next(self._ids), "method": method,
                                                    "params": params}, headers=headers)
        r.raise_for_status()
        self._session = r.headers.get("Mcp-Session-Id", self._session)
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            import json

            for line in r.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:]).get("result")
            return None
        return r.json().get("result")

    async def initialize(self) -> Any:
        return await self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "MarketPilot", "version": "0.1"}})

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> Any:
        assert_read_only(tool)
        if self._session is None:
            await self.initialize()
        return await self._rpc("tools/call", {"name": tool, "arguments": arguments or {}})


def get_client() -> RobinhoodReadOnly:
    st = get_settings()
    if not st.robinhood_mcp_enabled:
        raise BrokerageDisabled("Robinhood integration is disabled (ROBINHOOD_MCP_ENABLED=false).")
    if not st.robinhood_mcp_token:
        raise BrokerageDisabled("ROBINHOOD_MCP_TOKEN is not set (OAuth access token from Robinhood's agent authorization).")
    return RobinhoodReadOnly(st.robinhood_mcp_url, st.robinhood_mcp_token.get_secret_value())


def status() -> dict[str, Any]:
    st = get_settings()
    return {"enabled": st.robinhood_mcp_enabled, "token_configured": bool(st.robinhood_mcp_token),
            "endpoint": st.robinhood_mcp_url, "mode": "read-only", "allowed_tools": sorted(READ_ONLY_TOOLS),
            "independent_of_paper_trading": True, "verified_live": False}
