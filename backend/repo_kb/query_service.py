from __future__ import annotations

from typing import Any

from backend.contracts.domain import AnalysisBundle, LlmToolResult, RepositoryKnowledgeBase
from backend.contracts.enums import EntryRole, LearningGoal, RepoSurface
from backend.m3_analysis._helpers import stable_id


def get_repo_surfaces(analysis: AnalysisBundle, *, mode: str = "teaching") -> LlmToolResult:
    kb = _kb(analysis)
    surfaces = [
        {
            "path": item.path,
            "surface": item.surface,
            "reason": item.reason,
            "depth": item.depth,
        }
        for item in kb.surfaces
        if mode == "workspace"
        or item.surface
        not in {
            RepoSurface.WORKSPACE_META,
            RepoSurface.DOCS,
            RepoSurface.TOOLING,
            RepoSurface.TEST,
            RepoSurface.BUILD,
        }
    ]
    return _tool_result(
        "repo.get_surfaces",
        "repo_kb.query_service",
        f"当前模式下可见 {len(surfaces)} 条仓库分区结果。",
        {
            "mode": mode,
            "surfaces": surfaces[:80],
            "teaching_notes": kb.teaching_notes[:8],
        },
        analysis,
    )


def get_entry_candidates(analysis: AnalysisBundle, *, mode: str = "teaching") -> LlmToolResult:
    kb = _kb(analysis)
    grouped = {
        "primary_product_entry": [],
        "secondary_runtime_entry": [],
        "workspace_or_tool_entry": [],
        "uncertain": [],
    }
    for item in kb.candidates:
        if item.candidate_type != "entry":
            continue
        entry_role = str(item.metadata.get("entry_role") or EntryRole.UNCERTAIN)
        if mode != "workspace" and entry_role == EntryRole.WORKSPACE_OR_TOOL_ENTRY:
            continue
        grouped[entry_role].append(
            {
                "candidate_id": item.candidate_id,
                "target_id": item.target_id,
                "title": item.title,
                "summary": item.summary,
                "score": item.score,
                "confidence": item.confidence,
                "surface": item.surface,
                "evidence_refs": item.evidence_refs,
                **item.metadata,
            }
        )
    return _tool_result(
        "repo.get_entry_candidates",
        "repo_kb.query_service",
        "按教学模式过滤后的入口候选与类型分组。",
        {"mode": mode, **grouped},
        analysis,
    )


def get_module_map(analysis: AnalysisBundle, *, mode: str = "teaching") -> LlmToolResult:
    modules = []
    for item in analysis.module_summaries:
        if mode != "workspace" and item.surface not in {
            RepoSurface.PRODUCT,
            RepoSurface.ROOT_MISC,
            None,
        }:
            continue
        modules.append(item.model_dump(mode="json"))
    return _tool_result(
        "repo.get_module_map",
        "repo_kb.query_service",
        f"当前模式下可见 {len(modules)} 个模块候选。",
        {"mode": mode, "module_summaries": modules[:30]},
        analysis,
    )


def get_reading_path(
    analysis: AnalysisBundle, *, goal: str | None = None, mode: str = "teaching"
) -> LlmToolResult:
    steps = [step.model_dump(mode="json") for step in analysis.reading_path]
    if goal:
        try:
            goal_value = LearningGoal(goal)
        except ValueError:
            goal_value = None
        if goal_value == LearningGoal.ENTRY:
            filtered_targets = {
                item.target_value
                for item in analysis.entry_candidates
                if mode == "workspace" or item.entry_role != EntryRole.WORKSPACE_OR_TOOL_ENTRY
            }
            steps = [
                step for step in steps if step["target"] in filtered_targets or step["step_no"] <= 2
            ]
    return _tool_result(
        "repo.get_reading_path",
        "repo_kb.query_service",
        f"返回 {len(steps)} 步阅读路径建议。",
        {"mode": mode, "goal": goal, "reading_path": steps[:8]},
        analysis,
    )


def get_evidence(
    analysis: AnalysisBundle, *, evidence_ids: list[str] | None = None, target: str | None = None
) -> LlmToolResult:
    evidence = analysis.evidence_catalog
    if evidence_ids:
        wanted = set(evidence_ids)
        evidence = [item for item in evidence if item.evidence_id in wanted]
    elif target:
        lowered = target.casefold()
        evidence = [
            item
            for item in evidence
            if (item.source_path and lowered in item.source_path.casefold())
            or (item.note and lowered in item.note.casefold())
        ]
    return _tool_result(
        "repo.get_evidence",
        "repo_kb.query_service",
        f"返回 {len(evidence)} 条相关证据。",
        {
            "evidence_catalog": [
                {
                    **item.model_dump(mode="json"),
                    "content_excerpt": None if item.is_sensitive_source else item.content_excerpt,
                }
                for item in evidence[:30]
            ]
        },
        analysis,
    )


def _kb(analysis: AnalysisBundle) -> RepositoryKnowledgeBase:
    if analysis.knowledge_base is None:
        raise RuntimeError("Repository knowledge base is not available on analysis bundle")
    return analysis.knowledge_base


def _tool_result(
    tool_name: str,
    source_module: str,
    summary: str,
    payload: dict[str, Any],
    analysis: AnalysisBundle,
) -> LlmToolResult:
    return LlmToolResult(
        result_id=stable_id("tool_result", tool_name, summary),
        tool_name=tool_name,
        source_module=source_module,
        summary=summary,
        payload=payload,
        reference_only=True,
        generated_at=analysis.generated_at,
    )
