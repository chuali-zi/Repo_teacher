"""Minimal LLM-backed base class for repository teaching agents."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from ..llm.client import LLMClient
from ..prompts.prompt_manager import PromptManager


class BaseAgent(ABC):
    """Thin wrapper around an injected LLM client and local prompt manager."""

    agent_name: str

    def __init__(
        self,
        *,
        agent_name: str,
        llm_client: LLMClient | Any | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        if not agent_name:
            raise ValueError("agent_name must be non-empty")
        self.agent_name = agent_name
        self._llm_client = llm_client
        self._prompt_manager = prompt_manager or PromptManager()

    async def call_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **request_kwargs: Any,
    ) -> str:
        """Call the injected client once and return assistant text."""

        client = self._require_llm_client()
        method = getattr(client, "call_llm", None)
        if method is None:
            raise RuntimeError("llm_client must expose call_llm(...)")

        result = method(
            user_prompt,
            system_prompt=system_prompt,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
            **request_kwargs,
        )
        if inspect.isawaitable(result):
            result = await result
        content = getattr(result, "content", result)
        return "" if content is None else str(content)

    async def stream_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **request_kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream assistant text chunks, falling back to a single call if needed."""

        client = self._require_llm_client()
        method = getattr(client, "stream_llm", None)
        if method is None:
            text = await self.call_llm(
                user_prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                **request_kwargs,
            )
            if text:
                yield text
            return

        stream = method(
            user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **request_kwargs,
        )
        if inspect.isawaitable(stream):
            stream = await stream

        if hasattr(stream, "__aiter__"):
            async for chunk in stream:
                if chunk:
                    yield str(chunk)
            return

        for chunk in stream or ():
            if chunk:
                yield str(chunk)

    def get_prompt(self, section: str, field: str | None = None, fallback: str = "") -> str:
        """Read a prompt template for this agent from the injected PromptManager."""

        return self._prompt_manager.get(self.agent_name, section, field, fallback)

    def _require_llm_client(self) -> Any:
        if self._llm_client is None:
            raise RuntimeError("llm_client is required for agent execution")
        return self._llm_client

    @abstractmethod
    async def process(self, *args: Any, **kwargs: Any) -> Any:
        """Run the concrete agent."""


__all__ = ["BaseAgent"]
