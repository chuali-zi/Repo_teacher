"""Thin async LLM client wrapper for new_kernel agents.

This module is intentionally small and decoupled:
LLM details are only configured through constructor arguments and
explicit dependency injection.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any, Mapping

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    APITimeoutError,
    RateLimitError as APIRateLimitError,
)


logger = logging.getLogger(__name__)


class LLMClientError(RuntimeError):
    """Base exception type for LLM client failures."""


class LLMAuthenticationError(LLMClientError):
    """Raised when provider key/model auth fails."""


class LLMRateLimitError(LLMClientError):
    """Raised when the provider returns rate-limit responses."""


class LLMTimeoutError(LLMClientError):
    """Raised when the provider request exceeds timeout."""


@dataclass(frozen=True)
class LLMCallResult:
    """Structured result for non-streamed LLM responses."""

    content: str
    model: str
    finish_reason: str | None
    usage: dict[str, Any] | None
    raw: Any | None = None


class LLMClient:
    """Shared async client wrapper around OpenAI chat completions.

    The constructor requires explicit `api_key` and `model_id`; no `.env` or
    global singleton is consulted. A caller may pass a custom `client` instance
    for easier testing.
    """

    def __init__(
        self,
        api_key: str | None,
        model_id: str,
        client: AsyncOpenAI | None = None,
        timeout_seconds: float = 30.0,
        default_temperature: float = 0.2,
    ) -> None:
        if client is None:
            if not api_key:
                raise ValueError("api_key is required when client is not injected")
            client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._client = client
        self._model_id = model_id
        self._default_temperature = default_temperature

    async def call_llm(
        self,
        user_prompt: str = "",
        *,
        system_prompt: str | None = None,
        messages: Sequence[Mapping[str, str]] | None = None,
        model_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        stop: list[str] | None = None,
        timeout_seconds: float | None = None,
        **request_kwargs: Any,
    ) -> str:
        """Call the model once and return plain assistant text."""

        result = await self.call_llm_with_result(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            messages=messages,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stop=stop,
            timeout_seconds=timeout_seconds,
            **request_kwargs,
        )
        return result.content

    async def call_llm_with_result(
        self,
        user_prompt: str = "",
        *,
        system_prompt: str | None = None,
        messages: Sequence[Mapping[str, str]] | None = None,
        model_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        stop: list[str] | None = None,
        timeout_seconds: float | None = None,
        **request_kwargs: Any,
    ) -> LLMCallResult:
        """Call the model and return structured metadata + content."""

        msg_payload = self._normalize_messages(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            messages=messages,
        )
        response = await self._create_completion(
            messages=msg_payload,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stop=stop,
            stream=False,
            timeout_seconds=timeout_seconds,
            request_kwargs=request_kwargs,
        )

        choice = response.choices[0] if response.choices else None
        content = ""
        if choice is not None and choice.message is not None:
            content = choice.message.content or ""
            finish_reason = choice.finish_reason
        else:
            finish_reason = None

        usage = getattr(response, "usage", None)
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        elif isinstance(usage, Mapping):
            usage = dict(usage)
        return LLMCallResult(
            content=content,
            model=getattr(response, "model", self._model_id),
            finish_reason=finish_reason,
            usage=usage,
            raw=response,
        )

    async def stream_llm(
        self,
        user_prompt: str = "",
        *,
        system_prompt: str | None = None,
        messages: Sequence[Mapping[str, str]] | None = None,
        model_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        stop: list[str] | None = None,
        timeout_seconds: float | None = None,
        **request_kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream assistant text chunks from the model."""

        msg_payload = self._normalize_messages(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            messages=messages,
        )
        stream = await self._create_completion(
            messages=msg_payload,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stop=stop,
            stream=True,
            timeout_seconds=timeout_seconds,
            request_kwargs=request_kwargs,
        )

        async for chunk in stream:
            choices = getattr(chunk, "choices", [])
            if not choices:
                continue
            delta = choices[0].delta
            if delta is None:
                continue
            if isinstance(delta, Mapping):
                delta_text = delta.get("content")
            else:
                delta_text = getattr(delta, "content", None)
            if delta_text:
                yield delta_text

    async def _create_completion(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        model_id: str | None,
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
        stop: list[str] | None,
        stream: bool,
        timeout_seconds: float | None,
        request_kwargs: Mapping[str, Any],
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model_id or self._model_id,
            "messages": list(messages),
            "temperature": self._default_temperature if temperature is None else temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if top_p is not None:
            kwargs["top_p"] = top_p
        if stop:
            kwargs["stop"] = stop
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        for key, value in request_kwargs.items():
            if value is not None:
                kwargs[key] = value

        try:
            return await self._client.chat.completions.create(**kwargs)
        except AuthenticationError as exc:
            logger.exception("LLM authentication failed")
            raise LLMAuthenticationError("LLM authentication failed") from exc
        except APIRateLimitError as exc:
            logger.exception("LLM rate limit hit")
            raise LLMRateLimitError("LLM request is rate-limited") from exc
        except APITimeoutError as exc:
            logger.exception("LLM request timeout")
            raise LLMTimeoutError("LLM request timeout") from exc
        except (APIConnectionError, APIStatusError, APIError) as exc:
            logger.exception("LLM API error")
            raise LLMClientError(f"LLM API error: {exc.__class__.__name__}") from exc

    @staticmethod
    def _normalize_messages(
        *,
        user_prompt: str = "",
        system_prompt: str | None = None,
        messages: Sequence[Mapping[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        if messages is not None:
            normalized = []
            for msg in messages:
                if isinstance(msg, Mapping):
                    role = msg.get("role")
                    content = msg.get("content")
                else:
                    role = getattr(msg, "role", None)
                    content = getattr(msg, "content", None)
                if role is None or content is None:
                    raise ValueError("messages items must contain role and content")
                normalized.append({"role": str(role), "content": str(content)})
            return normalized

        normalized = []
        if system_prompt:
            normalized.append({"role": "system", "content": system_prompt})
        normalized.append({"role": "user", "content": user_prompt})
        return normalized

    async def close(self) -> None:
        """Close underlying SDK resources when available."""

        closer = getattr(self._client, "close", None)
        if callable(closer):
            await closer()


def make_client(
    api_key: str | None,
    model_id: str,
    *,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = 30.0,
) -> LLMClient:
    """Build and return a shared async client wrapper.

    Kept as a factory for explicit and uniform construction.
    """

    return LLMClient(
        api_key=api_key,
        model_id=model_id,
        client=client,
        timeout_seconds=timeout_seconds,
    )
