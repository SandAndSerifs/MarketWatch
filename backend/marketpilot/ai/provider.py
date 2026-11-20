"""Interchangeable LLM provider layer.

The rest of the app depends only on `LLMProvider.run(...)`. To add another vendor,
implement the same method (system prompt + messages + tool specs + a tool executor)
and register it in `build_ai_provider`.

The AI never touches order placement, sizing or risk approval: its tools are
read-only views of recorded data and market data.
"""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, get_settings

log = logging.getLogger(__name__)

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]


class AINotConfigured(RuntimeError):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class AIResult:
    text: str
    model: str
    stop_reason: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    refused: bool = False


class LLMProvider(ABC):
    name = "abstract"
    model = ""

    @abstractmethod
    async def run(self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec],
                  execute: ToolExecutor, max_turns: int = 10) -> AIResult: ...


class NoAIProvider(LLMProvider):
    name = "none"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def run(self, system, messages, tools, execute, max_turns=10):  # type: ignore[override]
        raise AINotConfigured(self.reason)


class AnthropicProvider(LLMProvider):
    """Claude via the official Anthropic SDK, manual tool loop (host-side tools)."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-opus-5-5", effort: str = "medium") -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2, timeout=180.0)
        self.model = model
        self.effort = effort

    async def run(self, system, messages, tools, execute, max_turns=10):  # type: ignore[override]
        a = self._anthropic
        msgs = list(messages)
        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        calls: list[dict[str, Any]] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        resp = None
        for _ in range(max_turns):
            kwargs: dict[str, Any] = dict(
                model=self.model, max_tokens=16000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=msgs, thinking={"type": "adaptive"}, output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            if tool_defs:
                kwargs["tools"] = tool_defs
            try:
                resp = await self.client.beta.messages.create(**kwargs)
            except a.AuthenticationError as e:
                raise AINotConfigured(f"Anthropic rejected the API key: {e}") from e
            except a.RateLimitError as e:
                return AIResult(f"The AI provider is rate-limiting requests; try again shortly. ({e})", self.model, "rate_limited")
            except a.APIStatusError as e:
                return AIResult(f"AI provider error {e.status_code}: {e.message}", self.model, "error")
            except a.APIConnectionError as e:
                return AIResult(f"Could not reach the AI provider: {e}", self.model, "error")
            u = getattr(resp, "usage", None)
            if u is not None:
                usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
                usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
                usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
            if resp.stop_reason == "refusal":
                return AIResult("The model declined to answer this request.", resp.model, "refusal", calls, usage, True)
            if resp.stop_reason == "pause_turn":
                msgs.append({"role": "assistant", "content": resp.content})
                continue
            if resp.stop_reason != "tool_use":
                break
            msgs.append({"role": "assistant", "content": resp.content})
            uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]

            async def run_one(b: Any) -> dict[str, Any]:
                try:
                    inp = b.input if isinstance(b.input, dict) else json.loads(b.input)
                    out = await execute(b.name, inp)
                    calls.append({"tool": b.name, "input": inp, "ok": True})
                    return {"type": "tool_result", "tool_use_id": b.id,
                            "content": json.dumps(out, default=str)[:60_000]}
                except Exception as e:  # tool failure is reported to the model, not hidden
                    calls.append({"tool": b.name, "ok": False, "error": str(e)[:200]})
                    return {"type": "tool_result", "tool_use_id": b.id, "content": f"Tool error: {e}", "is_error": True}

            results = await asyncio.gather(*(run_one(b) for b in uses))
            msgs.append({"role": "user", "content": list(results)})
        text = "".join(getattr(b, "text", "") for b in (resp.content if resp else []) if getattr(b, "type", "") == "text")
        return AIResult(text.strip() or "(no answer)", getattr(resp, "model", self.model), getattr(resp, "stop_reason", ""),
                        calls, usage)


def build_ai_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    if s.ai_provider == "anthropic":
        if not s.anthropic_api_key:
            return NoAIProvider("AI assistant not configured: set ANTHROPIC_API_KEY in backend/.env")
        return AnthropicProvider(s.anthropic_api_key.get_secret_value(), s.ai_model, s.ai_effort)
    return NoAIProvider("AI_PROVIDER=none")
