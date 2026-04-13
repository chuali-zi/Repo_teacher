from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / "llm_config.json"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 1


@dataclass(frozen=True)
class LlmConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float


async def stream_llm_response(prompt: str) -> AsyncIterator[str]:
    try:
        from openai import APITimeoutError, AsyncOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 openai 依赖，请先安装后端依赖") from exc

    config = load_llm_config()
    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
    )
    last_error: Exception | None = None

    for _attempt in range(MAX_RETRIES + 1):
        try:
            stream = await client.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
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
