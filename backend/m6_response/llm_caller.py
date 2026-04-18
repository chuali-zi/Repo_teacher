from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parents[2] / "llm_config.json"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 0


@dataclass(frozen=True)
class LlmConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float


@dataclass
class ToolCallRequest:
    """A single pending tool call extracted from an LLM streaming response."""

    call_id: str
    function_name: str
    arguments_json: str


@dataclass
class StreamResult:
    """Outcome of a single LLM streaming call (content and/or tool calls)."""

    content_chunks: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str | None = None


async def stream_llm_response(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.6,
) -> AsyncIterator[str]:
    """Original one-shot streaming interface (no function calling)."""
    config = load_llm_config()
    try:
        from openai import APITimeoutError, AsyncOpenAI
    except ModuleNotFoundError:
        yield await asyncio.to_thread(_complete_with_stdlib_http, config, messages, temperature)
        return

    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
    )
    last_error: Exception | None = None

    for _attempt in range(MAX_RETRIES + 1):
        try:
            stream = await client.chat.completions.create(
                model=config.model,
                messages=messages,
                temperature=temperature,
                stream=True,
                timeout=config.timeout_seconds,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            return
        except APITimeoutError as exc:
            last_error = TimeoutError("LLM API 调用超时")
            if _attempt >= MAX_RETRIES:
                raise last_error from exc
        except Exception as exc:
            last_error = RuntimeError(f"LLM API 调用失败: {exc}")
            if _attempt >= MAX_RETRIES:
                raise last_error from exc

    if last_error is not None:
        raise last_error


async def stream_llm_response_with_tools(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    temperature: float = 0.6,
    on_content_delta: Any | None = None,
) -> StreamResult:
    """Single streaming call that may produce content, tool_calls, or both.

    *on_content_delta*: optional async callable receiving each text chunk as
    it arrives, so the caller can forward it to the client in real-time.
    """
    config = load_llm_config()
    try:
        from openai import APITimeoutError, AsyncOpenAI
    except ModuleNotFoundError:
        text = await asyncio.to_thread(_complete_with_stdlib_http, config, messages, temperature)
        result = StreamResult(content_chunks=[text], finish_reason="stop")
        if on_content_delta is not None:
            await on_content_delta(text)
        return result

    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    last_error: Exception | None = None

    for _attempt in range(MAX_RETRIES + 1):
        try:
            stream = await client.chat.completions.create(
                model=config.model,
                messages=messages,
                tools=tools,
                temperature=temperature,
                stream=True,
                timeout=config.timeout_seconds,
            )
            result = StreamResult()
            pending_tool_calls: dict[int, ToolCallRequest] = {}

            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                if delta.content:
                    result.content_chunks.append(delta.content)
                    if on_content_delta is not None:
                        await on_content_delta(delta.content)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in pending_tool_calls:
                            pending_tool_calls[idx] = ToolCallRequest(
                                call_id=tc_delta.id or "",
                                function_name=tc_delta.function.name or ""
                                if tc_delta.function
                                else "",
                                arguments_json="",
                            )
                        pending = pending_tool_calls[idx]
                        if tc_delta.id:
                            pending.call_id = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                pending.function_name = tc_delta.function.name
                            if tc_delta.function.arguments:
                                pending.arguments_json += tc_delta.function.arguments

                if choice.finish_reason:
                    result.finish_reason = choice.finish_reason

            result.tool_calls = [pending_tool_calls[idx] for idx in sorted(pending_tool_calls)]
            return result

        except APITimeoutError as exc:
            last_error = TimeoutError("LLM API 调用超时")
            if _attempt >= MAX_RETRIES:
                raise last_error from exc
        except Exception as exc:
            last_error = RuntimeError(f"LLM API 调用失败: {exc}")
            if _attempt >= MAX_RETRIES:
                raise last_error from exc

    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM API 调用失败: 无法到达此处")


def _complete_with_stdlib_http(
    config: LlmConfig,
    messages: list[dict[str, str]],
    temperature: float,
) -> str:
    endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": config.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        raise TimeoutError("LLM API 调用超时") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM API 调用失败: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"LLM API 调用失败: {exc}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("LLM API 响应缺少 message.content") from exc
    text = str(content).strip()
    if not text:
        raise RuntimeError("LLM API 返回了空内容")
    return text


def load_llm_config(config_path: Path = CONFIG_PATH) -> LlmConfig:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"缺少 LLM 配置文件，请创建 {config_path.name}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM 配置文件格式错误: {config_path.name}") from exc

    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError(f"LLM 配置文件缺少 api_key: {config_path.name}")

    base_url = str(payload.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    model = str(payload.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL

    try:
        timeout_seconds = float(payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"LLM 配置文件中的 timeout_seconds 非法: {config_path.name}") from exc

    return LlmConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
    )
