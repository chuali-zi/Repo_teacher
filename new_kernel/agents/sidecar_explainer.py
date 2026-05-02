"""Sidecar term explainer for short, non-mutating explanations."""

from __future__ import annotations

from typing import Any

from ..contracts import SidecarExplainData, SidecarExplainRequest
from .base_agent import BaseAgent


class SidecarExplainer(BaseAgent):
    """Explain one term without touching chat, scratchpad, or agent status."""

    def __init__(self, *, llm_client: Any | None = None, prompt_manager: Any | None = None) -> None:
        super().__init__(agent_name="sidecar", llm_client=llm_client, prompt_manager=prompt_manager)

    async def process(
        self,
        request: SidecarExplainRequest | None = None,
        *,
        payload: SidecarExplainRequest | None = None,
        session: Any | None = None,
        term: str | None = None,
        current_repo: str | None = None,
        current_file: str | None = None,
    ) -> SidecarExplainData:
        active_request = request or payload
        if active_request is not None:
            term = active_request.term
            context = active_request.context
            current_repo = current_repo or _context_text(context, "current_repo", "repo")
            current_file = current_file or _context_text(context, "current_file", "path")

        current_repo = current_repo or _session_repo_label(session)
        current_file = current_file or _session_current_file(session)
        clean_term = (term or "").strip()
        if not clean_term:
            raise ValueError("term is required")

        system_prompt = self.get_prompt("system", fallback=_DEFAULT_SYSTEM_PROMPT)
        user_template = self.get_prompt("user_template", fallback=_DEFAULT_USER_TEMPLATE)
        user_prompt = _safe_format(
            user_template,
            term=clean_term,
            current_repo=current_repo or "(unknown repo)",
            current_file=current_file or "(no current file)",
        )
        explanation = await self.call_llm(
            user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=360,
        )
        related_paths = [current_file] if current_file else []
        return SidecarExplainData(
            term=clean_term,
            explanation=_trim_explanation(explanation),
            short_label=clean_term[:24],
            related_paths=related_paths,
        )


def _context_text(context: Any, *keys: str) -> str | None:
    if not isinstance(context, dict):
        return None
    for key in keys:
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _session_repo_label(session: Any) -> str | None:
    repository = getattr(session, "repository", None)
    if repository is None:
        return None
    label = getattr(repository, "display_name", None)
    return str(label).strip() if label else None


def _session_current_file(session: Any) -> str | None:
    current_code = getattr(session, "current_code", None)
    if current_code is None:
        return None
    path = getattr(current_code, "path", None)
    return str(path).strip() if path else None


def _trim_explanation(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return "这个术语需要结合更多上下文解释。"

    pieces: list[str] = []
    start = 0
    for index, char in enumerate(cleaned):
        if char in "。！？!?":
            pieces.append(cleaned[start : index + 1].strip())
            start = index + 1
        if len(pieces) >= 3:
            break
    if pieces:
        return "".join(pieces)
    return cleaned[:240]


def _safe_format(template: str, **values: str) -> str:
    try:
        return template.format(**values)
    except KeyError:
        return _DEFAULT_USER_TEMPLATE.format(**values)


_DEFAULT_SYSTEM_PROMPT = "你是仓库术语解释器。输出 2 到 3 句中文，不修改任何主对话状态。"

_DEFAULT_USER_TEMPLATE = (
    "术语：\n{term}\n\n"
    "当前仓库：\n{current_repo}\n\n"
    "当前文件：\n{current_file}\n\n"
    "请给出简短解释。"
)


__all__ = ["SidecarExplainer"]
