"""Checklist, knowledge, alerts, brokerage isolation, AI loop, API integration."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from marketpilot.decision.checklist import TIMING_RULES, challenge, classify
from marketpilot.risk.manager import Check, RiskConfig, RiskVerdict
from marketpilot.strategies.base import SetupProposal, StrategyContext


def _ctx(regime_label="risk_on", events=None, resistance=None):
    tech = {"ok": True, "close": 100, "atr_pct": 2.0, "change_pct": 0.5, "rsi14": 55, "avg_dollar_volume20": 5e8,
            "extension_atr_from_sma50": 1.0, "resistance": resistance or []}
    return StrategyContext("AAPL", datetime(2026, 11, 18, 17, tzinfo=timezone.utc), [], tech,
                           {"label": regime_label, "sectors": []}, events=events or [])


def _prop():
    return SetupProposal("AAPL", "trend_pullback", "1.0.0", "thesis", ["e"], "buy_stop", 100.0, 96.0, 108.0, ["below 96"], 10)


def test_challenge_raises_objections_and_falsifiers():
    ch = challenge(_ctx("risk_off", resistance=[{"price": 102.0, "touches": 3}]), _prop(), RiskConfig(), None)
    issues = {o["issue"]: o["severity"] for o in ch["objections"]}
    assert issues["Market headwind"] == "serious" and issues["Overhead resistance"] == "serious"
    assert "below 96" in ch["what_would_prove_it_wrong"]
    ev = [{"kind": "earnings", "symbol": "AAPL", "date": "2026-11-19", "time_et": "amc"}]
    ch2 = challenge(_ctx(events=ev), _prop(), RiskConfig(), None)
    assert ch2["counts"]["blocking"] == 1


def test_classification_timing_vs_structural():
    ch = {"counts": {"blocking": 0, "serious": 0, "caution": 1, "info": 0}}
    timing = RiskVerdict(False, 0, 0, 0, [Check("regular_session", False, "closed")], {})
    assert classify(ch, timing)[0] == "BUY_CANDIDATE"
    structural = RiskVerdict(False, 0, 0, 0, [Check("reward_risk", False, "1.1")], {})
    assert classify(ch, structural)[0] == "NO_TRADE"
    assert classify({"counts": {"blocking": 0, "serious": 2, "caution": 0, "info": 0}}, None)[0] == "WATCH"
    assert "regular_session" in TIMING_RULES


def test_knowledge_library_is_sourced_and_searchable(db):
    from marketpilot.knowledge.store import build_index, load_curated

    docs = load_curated()
    assert len(docs) >= 30
    for d in docs:
        assert d["sources"], d["slug"]
        for src in d["sources"]:
            assert src.get("title") and src.get("year") and src.get("type"), d["slug"]
    with db.session_scope() as s:
        res = build_index(s).search("how big should my position be risk per trade", 3)
        assert res[0]["slug"] == "position-sizing-fixed-fractional"
        assert build_index(s).search("backtest overfitting data snooping", 1)[0]["slug"] == "backtest-overfitting"


def test_alert_dedupe_and_cooldown(db):
    from marketpilot.alerts.service import AlertService

    svc = AlertService()
    now = datetime(2026, 11, 18, 15, tzinfo=timezone.utc)
    with db.session_scope() as s:
        a1 = svc.create(s, kind="signal", title="t", body="b", dedupe_key="k1", now=now, cooldown_minutes=60)
        a2 = svc.create(s, kind="signal", title="t", body="b", dedupe_key="k1", now=now + timedelta(minutes=30), cooldown_minutes=60)
        a3 = svc.create(s, kind="signal", title="t", body="b", dedupe_key="k1", now=now + timedelta(minutes=61), cooldown_minutes=60)
        assert a1 is not None and a2 is None and a3 is not None


def test_robinhood_connector_is_read_only_and_disabled_by_default():
    from marketpilot.brokerage import robinhood

    with pytest.raises(robinhood.BrokerageDisabled):
        robinhood.get_client()
    for bad in ("place_equity_order", "cancel_equity_order", "review_equity_order", "create_alert", "exercise_option"):
        with pytest.raises(robinhood.ForbiddenBrokerageAction):
            robinhood.assert_read_only(bad)
    robinhood.assert_read_only("get_portfolio")
    assert robinhood.status()["mode"] == "read-only"


def test_paper_package_never_imports_brokerage():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "marketpilot"
    for p in list((root / "paper").glob("*.py")) + list((root / "risk").glob("*.py")):
        imports = [ln for ln in p.read_text().splitlines() if ln.strip().startswith(("import ", "from "))]
        assert not any("brokerage" in ln or "robinhood" in ln.lower() for ln in imports), p
    # No order-submission endpoints exist in any provider adapter
    for p in (root / "data" / "providers").glob("*.py"):
        assert "/v2/orders" not in p.read_text()


class _FakeMessages:
    """Mimics the SDK: first a tool_use turn, then a final answer."""

    def __init__(self):
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return SimpleNamespace(stop_reason="tool_use", model=kw["model"], usage=None, content=[
                SimpleNamespace(type="tool_use", id="tu_1", name="search_knowledge", input={"query": "atr"})])
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], usage=None,
                               content=[SimpleNamespace(type="text", text="[Fact] answer")])


@pytest.mark.asyncio
async def test_anthropic_provider_tool_loop_without_network():
    from marketpilot.ai.provider import AnthropicProvider, ToolSpec

    p = AnthropicProvider("sk-test", "claude-opus-5-5")
    fake = _FakeMessages()
    p.client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    seen = []

    async def execute(name, inp):
        seen.append((name, inp))
        return {"ok": True}

    res = await p.run("sys", [{"role": "user", "content": "q"}], [ToolSpec("search_knowledge", "d", {"type": "object"})], execute)
    assert res.text == "[Fact] answer" and seen == [("search_knowledge", {"query": "atr"})]
    second = fake.calls[1]
    assert second["fallbacks"] == "default" and second["thinking"] == {"type": "adaptive"}
    assert second["messages"][-1]["content"][0]["tool_use_id"] == "tu_1"


def test_api_end_to_end_without_provider(db):
    from marketpilot.app import create_app
    from marketpilot.config import get_settings

    app = create_app(get_settings())
    with TestClient(app) as c:
        assert c.get("/api/health").json()["paper_trading_only"] is True
        assert c.get("/api/market/overview").status_code == 503  # never fabricated
        r = c.post("/api/experiments", json={"name": "E1", "strategy_key": "momentum", "strategy_params": {"target_r": 4}})
        assert r.status_code == 200 and "+" in r.json()["strategy_version"]
        eid = r.json()["id"]
        assert c.post(f"/api/experiments/{eid}/start").json()["status"] == "running"
        assert c.put(f"/api/experiments/{eid}/settings", json={"risk": {"max_position_pct": 8}}).status_code == 409
        assert c.post("/api/emergency-stop", json={"flatten": False}).json()["halted_experiments"] == 1
        assert c.post(f"/api/experiments/{eid}/resume").status_code == 409  # kill switch active
        c.post("/api/emergency-stop/clear")
        assert c.post(f"/api/experiments/{eid}/resume").json()["status"] == "running"
        comp = c.post("/api/competitions", json={"name": "Cup", "start_now": False}).json()
        assert len(comp["experiment_ids"]) == 4
        lb = c.get("/api/competitions/Cup").json()
        assert lb["ranking"].startswith("risk-adjusted") and len(lb["rows"]) == 4
        wl = c.get("/api/watchlists").json()[0]
        assert c.post(f"/api/watchlists/{wl['id']}/items", json={"symbol": "TSLA"}).status_code == 200
        assert c.post(f"/api/watchlists/{wl['id']}/items", json={"symbol": "bad sym!"}).status_code == 400
        ev = c.post("/api/events", json={"kind": "macro", "name": "Test CPI", "date": "2026-12-10", "time_et": "08:30",
                                         "source": "BLS"}).json()
        assert ev["verified_at"]
        v = c.post("/api/strategies/versions", json={"strategy_key": "breakout", "params": {"target_r": 3},
                                                     "change_reason": "test wider target"}).json()
        assert c.post(f"/api/strategies/versions/{v['id']}/status", json={"status": "approved"}).status_code == 409
        assert c.post("/api/backtests", json={"strategy_key": "trend_pullback"}).status_code == 503
        assert c.get("/api/knowledge", params={"q": "earnings gap"}).json()["results"]
        st = c.get("/api/settings").json()
        assert st["paper_trading_only"] and st["brokerage"]["enabled"] is False
        assert "sk-" not in json.dumps(st)
