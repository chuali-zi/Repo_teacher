"""Phase 3 Composer: stream the long-form onboarding report and parse trailing suggestions.

This agent performs exactly one streaming LLM call. It assembles the user-visible
markdown body chunk-by-chunk and, after the model emits the ``<<SUGGESTIONS>>``
marker described in AGENTS.md §3.4 / ``compose.yaml``, parses 1-3 short Chinese
"接下来你可以…" suggestions out of whatever the model wrote after the marker.
The orchestrator never sees the marker line nor the suggestion lines: this file
holds back the trailing ``len("<<SUGGESTIONS>>")`` chars of the buffer so a
marker split across chunk boundaries is detected before being forwarded. No
tools, no scratchpad I/O — the caller passes
``ResearchScratchpad.build_compose_context()`` as a dict.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from .base_research_agent import BaseResearchAgent


_MARKER = "<<SUGGESTIONS>>"
_REPO_OVERVIEW_LIMIT = 4096
_PLACEHOLDER_MARKDOWN = "(本次未产出导读，请稍后重试)"
_MAX_SUGGESTIONS = 3
_BULLET_PREFIXES: tuple[str, ...] = (
    "- ",
    "* ",
    "• ",
    "1.",
    "2.",
    "3.",
    "4.",
    "5.",
    "1)",
    "2)",
    "3)",
)


@dataclass(frozen=True)
class ComposeOutput:
    """Streaming Composer's terminal payload.

    ``markdown`` is the visible body with trailing whitespace stripped; the
    ``<<SUGGESTIONS>>`` marker line and everything after it are excluded.
    ``suggestions`` is 0..3 short Chinese strings parsed from after the marker.
    """

    markdown: str
    suggestions: tuple[str, ...]


class Composer(BaseResearchAgent):
    """Phase 3 streaming agent — one LLM call, marker-aware splitter, suggestion parser."""

    def __init__(
        self,
        *,
        llm_client: Any,
        prompt_manager: Any,
        agent_name: str = "compose",
    ) -> None:
        super().__init__(
            agent_name=agent_name,
            llm_client=llm_client,
            prompt_manager=prompt_manager,
        )
        self._last_output: ComposeOutput | None = None

    @property
    def last_output(self) -> ComposeOutput | None:
        return self._last_output

    async def process(self, *args: Any, **kwargs: Any) -> ComposeOutput:
        """Adapter for ``BaseAgent.process``: drains ``stream(...)`` and returns the result."""

        async for _ in self.stream(*args, **kwargs):
            pass
        if self._last_output is None:
            # Defensive: ``stream`` must always set ``_last_output`` before returning.
            self._last_output = ComposeOutput(
                markdown=_PLACEHOLDER_MARKDOWN, suggestions=()
            )
        return self._last_output

    async def stream(
        self,
        *,
        report_shape: Literal["short", "standard"],
        repo_overview_text: str,
        scratchpad_context: dict,
    ) -> AsyncIterator[str]:
        """Yield visible markdown chunks; stash full ``ComposeOutput`` in ``self.last_output``."""

        user_prompt = self.get_prompt("user_template").format(
            report_shape=report_shape,
            repo_overview_text=_clip_overview(repo_overview_text),
            subtopics_meta=_render_subtopics_meta(scratchpad_context),
            notes_dump=_render_notes_dump(scratchpad_context),
            raw_first_round_dump=_render_raw_first_round(scratchpad_context),
        )

        buffer = ""
        emitted_count = 0
        marker_pos = -1
        any_chunk = False

        stream = self.stream_llm(
            user_prompt,
            system_prompt=self.get_prompt("system"),
            temperature=0.7,
            # AGENTS.md §7.2 targets 3500-5000 中文字符. DeepSeek-chat tokenizes
            # Chinese roughly 1 char ≈ 1 token, so 4000 was just at the edge and
            # the report would be cut off mid-paragraph (FIX-07). 8000 leaves
            # plenty of headroom for the body + the trailing <<SUGGESTIONS>>
            # block + Markdown overhead, and stays inside DeepSeek-chat's
            # 8192 output cap.
            max_tokens=8000,
        )
        async for chunk in stream:
            if not chunk:
                continue
            any_chunk = True
            buffer += chunk

            if marker_pos == -1:
                idx = buffer.find(_MARKER)
                if idx != -1:
                    marker_pos = idx
                    # Flush whatever precedes the marker (rstripped) that we haven't
                    # emitted yet. The trailing whitespace right before the marker is
                    # purely structural — strip it so chunks_concat == markdown body.
                    visible_so_far = buffer[:marker_pos].rstrip()
                    if len(visible_so_far) > emitted_count:
                        to_emit = visible_so_far[emitted_count:]
                        emitted_count = len(visible_so_far)
                        yield to_emit
                else:
                    # Hold back the trailing ``len(_MARKER)`` chars: they could be
                    # the start of a marker that completes in the next chunk.
                    if len(buffer) > len(_MARKER):
                        safe_prefix = buffer[: len(buffer) - len(_MARKER)]
                    else:
                        safe_prefix = ""
                    if len(safe_prefix) > emitted_count:
                        to_emit = safe_prefix[emitted_count:]
                        emitted_count = len(safe_prefix)
                        yield to_emit
            # else: marker already detected, drop everything that follows.

        # End-of-stream cleanup.
        if not any_chunk:
            # Empty model output: emit a single placeholder chunk and record state.
            self._last_output = ComposeOutput(
                markdown=_PLACEHOLDER_MARKDOWN, suggestions=()
            )
            yield _PLACEHOLDER_MARKDOWN
            return

        if marker_pos == -1:
            # No marker ever showed up; flush the held-back tail.
            tail = buffer[emitted_count:]
            if tail:
                yield tail
            visible_md = buffer
            suggestions: tuple[str, ...] = ()
        else:
            visible_md = buffer[:marker_pos]
            after_marker = buffer[marker_pos + len(_MARKER) :]
            suggestions = _parse_suggestions(after_marker)

        self._last_output = ComposeOutput(
            markdown=visible_md.rstrip(),
            suggestions=suggestions,
        )


def _clip_overview(text: str) -> str:
    """Trim the repo overview body to ~4KB; the rest is dropped silently."""

    if not text:
        return ""
    if len(text.encode("utf-8")) <= _REPO_OVERVIEW_LIMIT:
        return text
    encoded = text.encode("utf-8")[:_REPO_OVERVIEW_LIMIT]
    return encoded.decode("utf-8", errors="ignore")


def _render_subtopics_meta(context: dict) -> str:
    """Render ``subtopics`` as ``- {id} ({title})[ skip-marker]`` lines."""

    lines: list[str] = []
    for sub in context.get("subtopics") or ():
        sid = sub.get("id", "")
        title = sub.get("title", "")
        skip_reason = sub.get("skip_reason")
        skip_marker = " [仓库里没有典型对应代码]" if skip_reason else ""
        lines.append(f"- {sid} ({title}){skip_marker}")
    return "\n".join(lines) if lines else "(no subtopics)"


def _render_notes_dump(context: dict) -> str:
    """Render notes as ``## {id} {title}\\n{text}`` blocks; skip empty buckets."""

    sections: list[str] = []
    notes_by_id = context.get("notes_by_id") or {}
    for sub in context.get("subtopics") or ():
        sid = sub.get("id", "")
        title = sub.get("title", "")
        notes = notes_by_id.get(sid) or []
        if not notes:
            continue
        body_parts = [f"## {sid} {title}"]
        for note in notes:
            text = (note or {}).get("text") or ""
            text = text.strip()
            if text:
                body_parts.append(text)
        if len(body_parts) > 1:
            sections.append("\n\n".join(body_parts))
    return "\n\n".join(sections) if sections else "(暂无笔记)"


def _render_raw_first_round(context: dict) -> str:
    """Render first-round raw observations as fenced ``text`` blocks per sub-topic."""

    sections: list[str] = []
    raws = context.get("raw_first_round_by_id") or {}
    for sub in context.get("subtopics") or ():
        sid = sub.get("id", "")
        title = sub.get("title", "")
        raw = raws.get(sid)
        if not raw:
            continue
        sections.append(f"## {sid} {title} 首轮素材\n```text\n{raw}\n```")
    return "\n\n".join(sections) if sections else "(暂无首轮素材)"


def _parse_suggestions(after_marker: str) -> tuple[str, ...]:
    """Pull 1..3 short suggestion strings from the post-marker tail."""

    out: list[str] = []
    for raw_line in after_marker.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for prefix in _BULLET_PREFIXES:
            if line.startswith(prefix):
                line = line[len(prefix) :].strip()
                break
        if line:
            out.append(line)
        if len(out) >= _MAX_SUGGESTIONS:
            break
    return tuple(out)


__all__ = ["ComposeOutput", "Composer"]
