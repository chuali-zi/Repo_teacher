"""LLM SDK thin client exports.

The package intentionally exposes only a small OpenAI-compatible async client
surface. Configuration is explicit and no environment variables are read here.
"""

from .client import (
    AsyncChatClientProtocol,
    ChatCompletionsProtocol,
    ChatNamespaceProtocol,
    LLMAuthenticationError,
    LLMCallResult,
    LLMClient,
    LLMClientError,
    LLMConfigurationError,
    LLMMessage,
    LLMRateLimitError,
    LLMTimeoutError,
    make_client,
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
