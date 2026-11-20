"""AI Market Analyst and grounded Trade Review Q&A."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ..db import AiMessage, Trade, session_scope
from ..knowledge.store import retrieve
from ..services.views import trade_detail
from .provider import AINotConfigured, LLMProvider
from .tools import TOOL_SPECS, AnalystTools

ANALYST_SYSTEM = """You are the AI Market Analyst inside MarketPilot, a personal market-intelligence and PAPER-trading application.

Ground rules:
- Use the tools for every market fact (prices, indicators, news, trades, performance, events). Never state a price, \
level, date or statistic that did not come from a tool result in this conversation. If a tool fails or data is \
unavailable, say so plainly instead of guessing.
- Label your statements: [Fact] for tool-verified data (mention the data feed/timestamp when relevant), \
[Interpretation] for your reading of the facts, [Estimate] for quantitative guesses, [Uncertain] for predictions.
- Never promise outcomes or invent probabilities of success. Present both the bull case and what would prove it wrong.
- When you use trading concepts, call search_knowledge and cite the source titles/authors it returns.
- For questions about past paper trades, use get_trade_record and explain from the ORIGINAL recorded rationale; \
clearly separate what was known at decision time from hindsight.
- Live data may be IEX-only or delayed; mention this when it matters (volume, spreads).
- All trading in MarketPilot is simulated with hypothetical money unless the user has separately configured a broker. \
You cannot place, size or approve orders.
- Be concise and structured (short headings or bullets). End analyses with a one-line reminder that this is not financial advice."""

TRADE_QA_SYSTEM = """You explain a single simulated (paper) trade made by MarketPilot's autonomous engine.

The ONLY admissible evidence is the JSON trade record provided below: the decision checklist recorded at the time, \
orders, fills, and the deterministic post-trade review, plus knowledge-library excerpts you retrieve. Do not invent \
reasons, prices or events that are not in the record. If the record does not contain the answer, say so.
Always distinguish (a) what the system knew and decided at the time, from (b) what happened afterwards (hindsight). \
Judge decision quality by whether the recorded process and rules were followed, not by the profit or loss. \
Remind the user that one trade is not evidence about a strategy. Keep answers short and specific; quote numbers from the record."""

KB_TOOL = [t for t in TOOL_SPECS if t.name == "search_knowledge"]


async def analyst_chat(runtime: Any, provider: LLMProvider, conversation_id: str, message: str) -> dict[str, Any]:
    with session_scope() as s:
        history = list(s.execute(select(AiMessage).where(AiMessage.conversation_id == conversation_id)
                                 .order_by(AiMessage.id.desc()).limit(16)).scalars())
        history.reverse()
        msgs: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in history]
        s.add(AiMessage(conversation_id=conversation_id, role="user", content=message))
    msgs.append({"role": "user", "content": message})
    tools = AnalystTools(runtime)
    res = await provider.run(ANALYST_SYSTEM, msgs, TOOL_SPECS, tools.execute, max_turns=12)
    with session_scope() as s:
        s.add(AiMessage(conversation_id=conversation_id, role="assistant", content=res.text,
                        meta={"model": res.model, "tool_calls": res.tool_calls, "usage": res.usage,
                              "stop_reason": res.stop_reason}))
    return {"answer": res.text, "model": res.model, "tool_calls": res.tool_calls, "usage": res.usage,
            "refused": res.refused}


STANDARD_QUESTIONS = {
    "why_buy": "Why did you buy this stock?",
    "trigger": "What triggered the trade?",
    "why_sell": "Why did you sell?",
    "invalidation": "What would have invalidated this trade?",
    "good_decision": "Was this a good decision based on the information available at the time?",
    "lessons": "What can the system learn from this result?",
}


def deterministic_answers(detail: dict[str, Any]) -> dict[str, str]:
    """Answers built purely from the stored record (works with no AI configured)."""
    t = detail["trade"]
    dec = (detail.get("decision") or {}).get("record")
    rev = t.get("review") or {}
    if not dec:
        return {k: "No decision record is attached to this trade." for k in STANDARD_QUESTIONS}
    st = dec["steps"]
    trig = dec.get("trigger", {})
    r6 = st["6_risk"]
    ev = st["4_evidence"]["supporting"]
    obj = st["5_challenge"]["objections"]
    out = {
        "why_buy": f"Strategy {dec['strategy']['name']} v{dec['strategy']['version']}. Thesis (recorded at "
                   f"{dec['evaluated_at']}): {st['3_thesis']['thesis']} Supporting evidence: " + "; ".join(ev) +
                   f". Decision: {st['7_decision']['category']} - {st['7_decision']['rationale']}",
        "trigger": (f"Armed plan: {r6['entry_type'].replace('_', ' ')} at {r6['entry']}. Triggered at "
                    f"{trig.get('triggered_at', 'n/a')} with live price {trig.get('live_price', 'n/a')}; the Risk Manager "
                    f"re-checked and approved {r6['verdict']['qty'] if r6.get('verdict') else 'n/a'} shares. "
                    f"Filled at {t['entry_price']} on {t['entry_ts']}."),
        "why_sell": (f"Exit on {t['exit_ts']} at {t['exit_price']}: {t['exit_reason']} (rule: {rev.get('exit_rule')})."
                     if t["status"] == "closed" else "The trade is still open."),
        "invalidation": "Recorded before entry: " + "; ".join(st["5_challenge"]["what_would_prove_it_wrong"]),
        "good_decision": (f"Process: {rev.get('decision_quality', 'n/a')}. Checks: " +
                          "; ".join(f"{c['rule']}: {'OK' if c['ok'] else 'NO'} ({c['detail']})" for c in rev.get("process_checks", [])) +
                          ". Objections raised at the time: " +
                          ("; ".join(f"[{o['severity']}] {o['issue']}" for o in obj if o['severity'] != 'info') or "none") +
                          ". Outcome does not define decision quality.") if rev else "Trade still open; review is written at exit.",
        "lessons": " ".join(rev.get("lessons", ["Trade still open."])) + " " + rev.get("caveat", ""),
    }
    return out


async def trade_question(provider: LLMProvider | None, trade_id: int, question: str) -> dict[str, Any]:
    with session_scope() as s:
        t = s.get(Trade, trade_id)
        if t is None:
            raise KeyError(trade_id)
        detail = trade_detail(s, t)
        kb = retrieve(s, f"{detail['trade']['strategy_key']} {question}", 3)
    canned = deterministic_answers(detail)
    key = next((k for k, q in STANDARD_QUESTIONS.items() if q.lower() == question.strip().lower()), None)
    if provider is None:
        return {"answer": canned.get(key, "AI is not configured; standard questions are answered from the record."),
                "source": "record", "grounding": "deterministic"}
    record_json = json.dumps(detail, default=str)[:90_000]
    system = TRADE_QA_SYSTEM + "\n\nTRADE RECORD (JSON):\n" + record_json + "\n\nKNOWLEDGE EXCERPTS:\n" + json.dumps(kb)[:12_000]

    async def exec_kb(name: str, inp: dict[str, Any]) -> Any:
        with session_scope() as s2:
            return retrieve(s2, inp.get("query", ""), 4)

    try:
        res = await provider.run(system, [{"role": "user", "content": question}], KB_TOOL, exec_kb, max_turns=4)
    except AINotConfigured as e:
        return {"answer": canned.get(key, str(e)), "source": "record", "grounding": "deterministic", "ai_error": str(e)}
    return {"answer": res.text, "source": "ai", "model": res.model, "grounding": "trade record + knowledge library",
            "record_answer": canned.get(key)}



