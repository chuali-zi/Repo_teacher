from __future__ import annotations

import os
from collections.abc import AsyncIterator

from openai import APITimeoutError, AsyncOpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 1


async def stream_llm_response(prompt: str) -> AsyncIterator[str]:
    client = AsyncOpenAI(
        api_key=_api_key(),
        base_url=os.getenv("M6_LLM_BASE_URL", DEFAULT_BASE_URL),
    )
    model = os.getenv("M6_LLM_MODEL", DEFAULT_MODEL)
    timeout_seconds = float(os.getenv("M6_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    last_error: Exception | None = None

    for _attempt in range(MAX_RETRIES + 1):
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                stream=True,
                timeout=timeout_seconds,
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


def _api_key() -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 LLM API Key，请设置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY")
    return api_key
