"""Phase 1 Decomposer: turn a ``RepoOverview`` into an ordered ``SubtopicMeta`` list.

This agent only plans WHAT the next phase should investigate; it does NOT call
tools, write notes, stream answers, or touch the scratchpad. It performs exactly
one LLM call, parses strict JSON, validates against the closed pillar set
``{what, stack, why, arch, flow, polyglot}``, drops unreachable anchors while
keeping the sub-topic, and falls back to canonical defaults when the LLM output
is unusable. Behaviour mirrors AGENTS.md §3.2 / §7.2 verbatim.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Literal

from ..research_scratchpad import SubtopicMeta
from .base_research_agent import BaseResearchAgent


_VALID_IDS = ("what", "stack", "why", "arch", "flow", "polyglot")
_STANDARD_REQUIRED = ("what", "stack", "why", "arch", "flow")
_DEFAULT_TITLES: dict[str, str] = {
    "what": "这个仓库在干什么",
    "stack": "用了哪些技术栈与各自作用",
    "why": "为什么挑这套技术栈",
    "arch": "整体架构（重点）",
    "flow": "主流程怎么跑通",
    "polyglot": "多语言分工与跨语言互调用",
}
_DEFAULT_ANCHORS_STANDARD: dict[str, tuple[str, ...]] = {
    "what": ("README.md",),
    "stack": ("README.md",),
    "why": ("README.md",),
    "arch": (),
    "flow": (),
}


def _arch_default_anchors(reachable: tuple[str, ...]) -> tuple[str, ...]:
    """Pick a mix of directory + file anchors (≤3 of each, ≤6 total).

    Directory anchors give the Investigator the high-level layout to ``list_dir``;
    file anchors invite it to ``read_file_range`` a representative source file.
    The two combined steer Phase 2 toward grounded source reading rather than
    pure directory inference (RECON-E §D1, FIX-04).
    """

    dirs: list[str] = []
    files: list[str] = []
    for path in reachable:
        if not isinstance(path, str) or not path:
            continue
        if path.endswith("/"):
            if len(dirs) < 3:
                dirs.append(path)
        else:
            if len(files) < 3:
                files.append(path)
        if len(dirs) >= 3 and len(files) >= 3:
            break
    mixed = tuple(dirs + files)
    if mixed:
        return mixed
    # Last resort: take whatever's there.
    return tuple(reachable[:6])


class Decomposer(BaseResearchAgent):
    """Plan the sub-topic list for Phase 2; one LLM call, deterministic fallback."""

    def __init__(self, *, llm_client: Any, prompt_manager: Any, agent_name: str = "decompose") -> None:
        super().__init__(agent_name=agent_name, llm_client=llm_client, prompt_manager=prompt_manager)

    async def process(
        self,
        *,
        report_shape: Literal["short", "standard"],
        repo_overview: Any,
    ) -> list[SubtopicMeta]:
        primary = getattr(repo_overview, "primary_language", None) or "unknown"
        language_counts = dict(getattr(repo_overview, "language_counts", {}) or {})
        file_count = int(getattr(repo_overview, "file_count", 0) or 0)
        top_level_paths = list(getattr(repo_overview, "top_level_paths", ()) or ())[:60]
        entry_candidates = list(getattr(repo_overview, "entry_candidates", ()) or ())[:12]
        repo_overview_text = getattr(repo_overview, "text", "") or ""
        reachable = _reachable_paths(top_level_paths, entry_candidates)

        user_prompt = self.get_prompt("user_template").format(
            report_shape=report_shape,
            primary_language=primary,
            language_counts=json.dumps(_top_language_counts(language_counts), ensure_ascii=False),
            file_count=file_count,
            top_level_paths=json.dumps(top_level_paths, ensure_ascii=False),
            entry_candidates=json.dumps(_render_entries(entry_candidates), ensure_ascii=False),
            repo_overview_text=repo_overview_text,
        )
        # AGENTS.md §3.2: JSON-parse failure → default pillars; FIX-02 extends
        # this to LLM HTTP failures (auth/balance/rate-limit/4XX/timeout) so a
        # provider error doesn't surface as ErrorEvent. Mirrors investigator.py.
        try:
            text = await self.call_llm(
                user_prompt,
                system_prompt=self.get_prompt("system"),
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=900,
            )
        except Exception:
            return _fallback_subtopics(report_shape, reachable=reachable)
        payload = self.parse_strict_json(text, fallback={"subtopics": []})
        raw_items = payload.get("subtopics") if isinstance(payload, dict) else None

        validated = _validate_subtopics(
            raw_items,
            report_shape=report_shape,
            reachable=reachable,
            multilingual=_multilingual(language_counts),
        )
        return validated or _fallback_subtopics(report_shape, reachable=reachable)


def _multilingual(language_counts: dict[str, int]) -> bool:
    """``True`` iff the second-largest language has ≥ 25% of the largest's share."""

    values = sorted(language_counts.values(), reverse=True)
    if len(values) < 2 or values[0] == 0:
        return False
    return values[1] / values[0] >= 0.25


def _top_language_counts(language_counts: dict[str, int]) -> dict[str, int]:
    if not language_counts:
        return {}
    ranked = sorted(language_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    return {name: count for name, count in ranked}


def _render_entries(entry_candidates: Iterable[Any]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for candidate in entry_candidates:
        path = getattr(candidate, "path", None)
        if not isinstance(path, str) or not path:
            continue
        item: dict[str, Any] = {"path": path}
        hint = getattr(candidate, "reason", None) or getattr(candidate, "hint", None)
        if isinstance(hint, str) and hint:
            item["hint"] = hint
        rendered.append(item)
    return rendered


def _reachable_paths(top_level_paths: Iterable[str], entry_candidates: Iterable[Any]) -> tuple[str, ...]:
    seen: list[str] = []
    for path in top_level_paths:
        if isinstance(path, str) and path and path not in seen:
            seen.append(path)
    for candidate in entry_candidates:
        path = getattr(candidate, "path", None)
        if isinstance(path, str) and path and path not in seen:
            seen.append(path)
    return tuple(seen)


def _anchor_reachable(anchor: str, reachable: tuple[str, ...]) -> bool:
    if not anchor:
        return False
    return any(anchor == base or anchor in base or base in anchor for base in reachable)


def _validate_subtopics(
    raw_items: Any,
    *,
    report_shape: Literal["short", "standard"],
    reachable: tuple[str, ...],
    multilingual: bool,
) -> list[SubtopicMeta]:
    if not isinstance(raw_items, list) or not raw_items:
        return []

    by_id: dict[str, SubtopicMeta] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        sid = item.get("id")
        if not isinstance(sid, str) or sid not in _VALID_IDS or sid in by_id:
            continue
        raw_title = item.get("title")
        title = (
            raw_title.strip()
            if isinstance(raw_title, str) and raw_title.strip()
            else _DEFAULT_TITLES[sid]
        )
        anchors_raw = item.get("anchors") or ()
        anchors = tuple(
            anchor
            for anchor in (anchors_raw if isinstance(anchors_raw, list) else ())
            if isinstance(anchor, str) and _anchor_reachable(anchor, reachable)
        )
        by_id[sid] = SubtopicMeta(id=sid, title=title, anchors=anchors)

    if not by_id:
        return []
    if report_shape == "short":
        if "what" not in by_id:
            return []
        # Short branch keeps [what] or [what, stack] only; canonical order.
        return [by_id["what"]] + ([by_id["stack"]] if "stack" in by_id else [])

    # Standard branch: fill missing pillars with defaults; allow polyglot iff multilingual.
    result: list[SubtopicMeta] = []
    for sid in _STANDARD_REQUIRED:
        existing = by_id.get(sid)
        if existing is None:
            anchors = _default_anchors_for(sid, reachable)
            result.append(SubtopicMeta(id=sid, title=_DEFAULT_TITLES[sid], anchors=anchors))
            continue
        # RECON-D Option A: when the LLM produced an arch sub-topic but every
        # anchor was unreachable (so anchors_raw was filtered down to ()), inject
        # the dynamic default so Investigator still sees concrete paths.
        if sid == "arch" and not existing.anchors and reachable:
            anchors = _arch_default_anchors(reachable)
            if anchors:
                result.append(SubtopicMeta(id=sid, title=existing.title, anchors=anchors))
                continue
        result.append(existing)
    if "polyglot" in by_id and multilingual:
        result.append(by_id["polyglot"])
    return result


def _default_anchors_for(sid: str, reachable: tuple[str, ...]) -> tuple[str, ...]:
    """Return the default anchor tuple for a missing standard pillar."""

    if sid == "arch":
        return _arch_default_anchors(reachable)
    return _DEFAULT_ANCHORS_STANDARD.get(sid, ())


def _fallback_subtopics(
    report_shape: Literal["short", "standard"],
    *,
    reachable: tuple[str, ...] = (),
) -> list[SubtopicMeta]:
    if report_shape == "short":
        return [SubtopicMeta(id="what", title=_DEFAULT_TITLES["what"], anchors=("README.md",))]
    return [
        SubtopicMeta(
            id=sid, title=_DEFAULT_TITLES[sid], anchors=_default_anchors_for(sid, reachable)
        )
        for sid in _STANDARD_REQUIRED
    ]


__all__ = ["Decomposer"]
