"""Thin async LLM client wrapper for new_kernel agents.

This module is intentionally small and decoupled:
LLM details are only configured through constructor arguments and
explicit dependency injection.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Sequence
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Mapping, Protocol

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


class LLMConfigurationError(LLMClientError, ValueError):
    """Raised when required client configuration is missing or invalid."""


class LLMAuthenticationError(LLMClientError):
    """Raised when provider key/model auth fails."""


class LLMRateLimitError(LLMClientError):
    """Raised when the provider returns rate-limit responses."""


class LLMTimeoutError(LLMClientError):
    """Raised when the provider request exceeds timeout."""


class ChatCompletionsProtocol(Protocol):
    """Minimal OpenAI-compatible chat completions surface used by this module."""

    def create(self, **kwargs: Any) -> Awaitable[Any]:
        """Create a chat completion or stream."""


class ChatNamespaceProtocol(Protocol):
    """Namespace exposing chat completion calls."""

    completions: ChatCompletionsProtocol


class AsyncChatClientProtocol(Protocol):
    """Minimal async client protocol accepted by ``LLMClient``."""

    chat: ChatNamespaceProtocol


@dataclass(frozen=True)
class LLMMessage:
    """Text-only chat message accepted by the LLM client."""

    role: str
    content: str

    def __post_init__(self) -> None:
        if not self.role:
            raise ValueError("message role must be a non-empty string")
        if self.content is None:
            raise ValueError("message content is required")

    def to_payload(self) -> dict[str, str]:
        """Return the OpenAI-compatible message payload."""

        return {"role": self.role, "content": self.content}


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
        client: AsyncChatClientProtocol | None = None,
        timeout_seconds: float = 30.0,
        default_temperature: float = 0.2,
        base_url: str | None = None,
    ) -> None:
        if not model_id:
            raise LLMConfigurationError("model_id is required")
        if timeout_seconds <= 0:
            raise LLMConfigurationError("timeout_seconds must be positive")
        if not 0 <= default_temperature <= 2:
            raise LLMConfigurationError("default_temperature must be between 0 and 2")
        if client is None:
            if not api_key:
                raise LLMConfigurationError("api_key is required when client is not injected")
            sdk_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout_seconds}
            if base_url:
                sdk_kwargs["base_url"] = base_url
            client = AsyncOpenAI(**sdk_kwargs)
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
        response_format: Mapping[str, Any] | None = None,
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
            response_format=response_format,
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
        response_format: Mapping[str, Any] | None = None,
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
            response_format=response_format,
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

        return LLMCallResult(
            content=content,
            model=getattr(response, "model", self._model_id),
            finish_reason=finish_reason,
            usage=self._extract_usage(response),
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
        response_format: Mapping[str, Any] | None = None,
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
            response_format=response_format,
            stream=True,
            timeout_seconds=timeout_seconds,
            request_kwargs=request_kwargs,
        )

        async for chunk in stream:
            choices = getattr(chunk, "choices", [])
            if not choices:
                continue
            delta_text = self._extract_delta_text(choices[0])
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
        response_format: Mapping[str, Any] | None,
        stream: bool,
        timeout_seconds: float | None,
        request_kwargs: Mapping[str, Any],
    ) -> Any:
        self._validate_request_options(
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout_seconds=timeout_seconds,
        )
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
        if response_format is not None:
            kwargs["response_format"] = dict(response_format)
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        for key, value in request_kwargs.items():
            if value is not None:
                kwargs[key] = value

        last_exc: Exception | None = None
        for attempt in (0, 1):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except (APIConnectionError, APITimeoutError) as exc:
                last_exc = exc
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                if isinstance(exc, APITimeoutError):
                    logger.exception("LLM request timeout")
                    raise LLMTimeoutError("LLM request timeout") from exc
                logger.exception("LLM API connection error")
                raise LLMClientError(f"LLM API error: {exc.__class__.__name__}") from exc
            except AuthenticationError as exc:
                logger.exception("LLM authentication failed")
                raise LLMAuthenticationError("LLM authentication failed") from exc
            except APIRateLimitError as exc:
                logger.exception("LLM rate limit hit")
                raise LLMRateLimitError("LLM request is rate-limited") from exc
            except (APIStatusError, APIError) as exc:
                logger.exception("LLM API error")
                raise LLMClientError(f"LLM API error: {exc.__class__.__name__}") from exc
        raise LLMClientError("unreachable") from last_exc

    @staticmethod
    def _normalize_messages(
        *,
        user_prompt: str = "",
        system_prompt: str | None = None,
        messages: Sequence[LLMMessage | Mapping[str, Any] | Any] | None = None,
    ) -> list[dict[str, str]]:
        if messages is not None:
            normalized = []
            for msg in messages:
                role, content = LLMClient._message_parts(msg)
                if role is None or content is None:
                    raise ValueError("messages items must contain role and content")
                normalized.append({"role": str(role), "content": str(content)})
            if not normalized:
                raise ValueError("messages must contain at least one item")
            return normalized

        normalized = []
        if system_prompt:
            normalized.append({"role": "system", "content": system_prompt})
        normalized.append({"role": "user", "content": user_prompt})
        return normalized

    @staticmethod
    def _message_parts(message: LLMMessage | Mapping[str, Any] | Any) -> tuple[Any, Any]:
        if isinstance(message, LLMMessage):
            return message.role, message.content
        if isinstance(message, Mapping):
            return message.get("role"), message.get("content")
        return getattr(message, "role", None), getattr(message, "content", None)

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, Any] | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if isinstance(usage, Mapping):
            return dict(usage)
        return None

    @staticmethod
    def _extract_delta_text(choice: Any) -> str | None:
        delta = getattr(choice, "delta", None)
        if delta is None and isinstance(choice, Mapping):
            delta = choice.get("delta")
        if delta is None:
            return None
        if isinstance(delta, Mapping):
            value = delta.get("content")
        else:
            value = getattr(delta, "content", None)
        return value if isinstance(value, str) else None

    @staticmethod
    def _validate_request_options(
        *,
        model_id: str | None,
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
        timeout_seconds: float | None,
    ) -> None:
        if model_id is not None and not model_id:
            raise LLMConfigurationError("model_id must be a non-empty string")
        if temperature is not None and not 0 <= temperature <= 2:
            raise LLMConfigurationError("temperature must be between 0 and 2")
        if max_tokens is not None and max_tokens < 1:
            raise LLMConfigurationError("max_tokens must be positive")
        if top_p is not None and not 0 < top_p <= 1:
            raise LLMConfigurationError("top_p must be in the range (0, 1]")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise LLMConfigurationError("timeout_seconds must be positive")

    async def close(self) -> None:
        """Close underlying SDK resources when available."""

        closer = getattr(self._client, "close", None)
        if callable(closer):
            result = closer()
            if isawaitable(result):
                await result


def make_client(
    api_key: str | None,
    model_id: str,
    *,
    client: AsyncChatClientProtocol | None = None,
    timeout_seconds: float = 30.0,
    default_temperature: float = 0.2,
    base_url: str | None = None,
) -> LLMClient:
    """Build and return a shared async client wrapper.

    Kept as a factory for explicit and uniform construction. ``base_url`` is
    forwarded to ``AsyncOpenAI`` so the client can target an OpenAI-compatible
    endpoint (e.g. DeepSeek). Configuration values must be supplied by the
    caller (composition root); this layer never reads files or env vars.
    """

    return LLMClient(
        api_key=api_key,
        model_id=model_id,
        client=client,
        timeout_seconds=timeout_seconds,
        default_temperature=default_temperature,
        base_url=base_url,
    )


__all__ = [
    "AsyncChatClientProtocol",
    "ChatCompletionsProtocol",
    "ChatNamespaceProtocol",
    "LLMAuthenticationError",
    "LLMCallResult",
    "LLMClient",
    "LLMClientError",
    "LLMConfigurationError",
    "LLMMessage",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "make_client",
]
