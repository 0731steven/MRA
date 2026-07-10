"""Unified DeepSeek client built on the OpenAI Python SDK.

All production LLM calls use the same endpoint/model/reasoning configuration.
The small mock path exists only for offline tests and never uses a second model.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any


DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_REASONING_EFFORT = os.environ.get("DEEPSEEK_REASONING_EFFORT", "high")


class ChatMessage:
    __slots__ = ("role", "content")

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


class LLMClient:
    """Async facade over the synchronous ``openai.OpenAI`` DeepSeek client."""

    def __init__(self, step: int | None = None, name: str | None = None) -> None:
        self.step = step
        self.name = name
        self.model = DEEPSEEK_MODEL
        # Backward-compatible test switch; production .env does not set this.
        self.mock = os.environ.get("DEEPSEEK_MOCK", "false").lower() == "true"
        self.provider = "mock" if self.mock else "deepseek"

    def _client(self):
        from openai import OpenAI

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置，请在 backend/.env 中设置")
        return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

    async def complete_response(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 32768,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        """Return the raw OpenAI-SDK response; always uses non-streaming mode."""
        if self.mock:
            raise RuntimeError("Raw responses are unavailable in DeepSeek mock mode")

        def _call():
            client = self._client()
            params: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "reasoning_effort": DEEPSEEK_REASONING_EFFORT,
                "extra_body": {"thinking": {"type": "enabled"}},
                "max_tokens": max_tokens,
            }
            if tools:
                params["tools"] = tools
            if tool_choice:
                params["tool_choice"] = tool_choice
            # Allow safe OpenAI-compatible options without overriding the fixed
            # model, endpoint, reasoning mode or non-streaming contract.
            for key in ("temperature", "top_p", "stop", "response_format"):
                if key in kwargs:
                    params[key] = kwargs[key]
            return client.chat.completions.create(**params)

        return await asyncio.to_thread(_call)

    async def chat(
        self,
        messages: list[ChatMessage],
        system: str | None = None,
        max_tokens: int = 32768,
        **kwargs: Any,
    ) -> str:
        if self.mock:
            return self._mock_response(messages)
        payload: list[dict[str, Any]] = []
        if system:
            payload.append({"role": "system", "content": system})
        payload.extend({"role": m.role, "content": m.content} for m in messages if m.role != "system")
        response = await self.complete_response(payload, max_tokens=max_tokens, **kwargs)
        content = response.choices[0].message.content if response.choices else ""
        return content or ""

    async def chat_json(
        self,
        messages: list[ChatMessage],
        system: str | None = None,
        max_tokens: int = 32768,
        **kwargs: Any,
    ) -> Any:
        text = (await self.chat(messages, system, max_tokens, **kwargs)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    def _mock_response(self, messages: list[ChatMessage]) -> str:
        last = messages[-1].content if messages else ""
        return json.dumps({"mock": True, "echo": last[:80]}, ensure_ascii=False)
