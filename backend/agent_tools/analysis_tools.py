from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from backend.agent_tools.base import ToolContext, ToolSpec
from backend.agent_tools.repository_tools import read_file_excerpt
from backend.contracts.domain import (
    AnalysisBundle,
    ConversationState,
    FileTreeSnapshot,
    LlmToolResult,
    RepositoryContext,
    TeachingSkeleton,
    TopicRef,
)
from backend.contracts.enums import (
    FileNodeStatus,
    FileNodeType,
    LearningGoal,
)
from backend.m3_analysis._helpers import stable_id
from backend.repo_kb.query_service import (
    get_entry_candidates as kb_get_entry_candidates,
    get_evidence as kb_get_evidence,
    get_module_map as kb_get_module_map,
    get_reading_path as kb_get_reading_path,
    get_repo_surfaces as kb_get_repo_surfaces,
)

_SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,})"
)
_TOPIC_ATTRS_BY_GOAL: dict[LearningGoal, tuple[str, ...]] = {
    LearningGoal.OVERVIEW: (
        "structure_refs",
        "entry_refs",
        "flow_refs",
        "module_refs",
        "reading_path_refs",
    ),
    LearningGoal.STRUCTURE: ("structure_refs", "reading_path_refs", "module_refs"),
    LearningGoal.ENTRY: ("entry_refs", "reading_path_refs", "module_refs"),
    LearningGoal.FLOW: ("flow_refs", "entry_refs", "module_refs"),
    LearningGoal.MODULE: ("module_refs", "structure_refs", "reading_path_refs"),
    LearningGoal.DEPENDENCY: ("dependency_refs", "module_refs", "structure_refs"),
    LearningGoal.LAYER: ("layer_refs", "module_refs", "structure_refs"),
    LearningGoal.SUMMARY: ("unknown_refs", "reading_path_refs", "structure_refs"),
}


def build_analysis_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            tool_name="get_repo_surfaces",
            source_module="repo_kb.query_service",
            description="Return the repository surface map grouped for teaching or workspace reading.",
            parameters=_mode_only_parameters(),
            output_contract="High-level surface assignments and teaching notes.",
            aliases=("repo.get_surfaces",),
            preferred_seed=True,
            seed_priority=10,
            handler=lambda arguments, ctx: _kb_tool(
                "get_repo_surfaces",
                ctx,
                lambda analysis: kb_get_repo_surfaces(
                    analysis,
                    mode=str(arguments.get("mode") or "teaching"),
                ),
            ),
        ),
        ToolSpec(
            tool_name="get_entry_candidates",
            source_module="repo_kb.query_service",
            description="Return grouped entry candidates filtered for teaching or workspace mode.",
            parameters=_mode_only_parameters(),
            output_contract="Grouped entry candidates with confidence and evidence refs.",
            preferred_seed=True,
            seed_priority=20,
            handler=lambda arguments, ctx: _kb_tool(
                "get_entry_candidates",
                ctx,
                lambda analysis: kb_get_entry_candidates(
                    analysis,
                    mode=str(arguments.get("mode") or "teaching"),
                ),
            ),
        ),
        ToolSpec(
            tool_name="get_module_map",
            source_module="repo_kb.query_service",
            description="Return the mode-aware module map for the current repository.",
            parameters=_mode_only_parameters(),
            output_contract="Ranked module summaries suitable for teaching navigation.",
            preferred_seed=True,
            seed_priority=30,
            handler=lambda arguments, ctx: _kb_tool(
                "get_module_map",
                ctx,
                lambda analysis: kb_get_module_map(
                    analysis,
                    mode=str(arguments.get("mode") or "teaching"),
                ),
            ),
        ),
        ToolSpec(
            tool_name="get_reading_path",
            source_module="repo_kb.query_service",
            description="Return a focused reading path for the current goal.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "mode": {"type": "string", "enum": ["teaching", "workspace"], "default": "teaching"},
                },
                "required": [],
            },
            output_contract="Reading path preview with step target, reason, and learning gain.",
            preferred_seed=True,
            seed_priority=40,
            handler=lambda arguments, ctx: _kb_tool(
                "get_reading_path",
                ctx,
                lambda analysis: kb_get_reading_path(
                    analysis,
                    goal=str(arguments.get("goal") or "") or None,
                    mode=str(arguments.get("mode") or "teaching"),
                ),
            ),
        ),
        ToolSpec(
            tool_name="get_evidence",
            source_module="repo_kb.query_service",
            description="Return focused evidence items by target string or evidence ids.",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": [],
            },
            output_contract="Filtered evidence catalog entries.",
            seed_priority=50,
            handler=lambda arguments, ctx: _kb_tool(
                "get_evidence",
                ctx,
                lambda analysis: kb_get_evidence(
                    analysis,
                    target=str(arguments.get("target") or "") or None,
                    evidence_ids=arguments.get("evidence_ids"),
                ),
            ),
        ),
        ToolSpec(
            tool_name="m1.get_repository_context",
            source_module="m1_repo_access",
            description="Return repository metadata and the active read-only policy snapshot.",
            parameters=_empty_parameters(),
            output_contract="Compact repository metadata without leaking root_path.",
            preferred_seed=True,
            seed_priority=5,
            handler=lambda arguments, ctx: _repository_context_result(ctx.repository),
        ),
        ToolSpec(
            tool_name="m2.get_file_tree_summary",
            source_module="m2_file_tree",
            description="Return a compact summary of the scanned file tree.",
            parameters=_empty_parameters(),
            output_contract="Top-level directories/files, languages, size, and degradation notices.",
            preferred_seed=True,
            seed_priority=15,
            handler=lambda arguments, ctx: _file_tree_summary_result(ctx.file_tree),
        ),
        ToolSpec(
            tool_name="m2.list_relevant_files",
            source_module="m2_file_tree",
            description="List relevant source and repository-doc files for targeted reading.",
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 80}},
                "required": [],
            },
            output_contract="Relevant file paths with basic file metadata.",
            seed_priority=35,
            handler=lambda arguments, ctx: _relevant_files_result(
                ctx.file_tree,
                limit=int(arguments.get("limit", 80) or 80),
            ),
        ),
        ToolSpec(
            tool_name="m3.get_project_profile",
            source_module="m3_analysis.project_profiler",
            description="Return project profile candidates and the primary language.",
            parameters=_empty_parameters(),
            output_contract="Project profile result.",
            seed_priority=25,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_project_profile",
                ctx,
                lambda analysis: _tool_result(
                    "m3.get_project_profile",
                    "m3_analysis.project_profiler",
                    "Project profile and project-type candidates.",
                    analysis.project_profile.model_dump(mode="json"),
                    generated_at=analysis.generated_at,
                ),
            ),
        ),
        ToolSpec(
            tool_name="m3.get_entry_candidates",
            source_module="m3_analysis.entry_detector",
            description="Return raw M3 entry candidates.",
            parameters=_empty_parameters(),
            output_contract="Ranked entry candidates.",
            seed_priority=45,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_entry_candidates",
                ctx,
                lambda analysis: _tool_result(
                    "m3.get_entry_candidates",
                    "m3_analysis.entry_detector",
                    f"Found {len(analysis.entry_candidates)} raw entry candidates.",
                    {"entry_candidates": _dump_models(analysis.entry_candidates[:12])},
                    generated_at=analysis.generated_at,
                ),
            ),
        ),
        ToolSpec(
            tool_name="m3.get_dependency_map",
            source_module="m3_analysis.import_analyzer",
            description="Return grouped dependency classifications from static analysis.",
            parameters=_empty_parameters(),
            output_contract="Dependency groups bucketed by import source type.",
            seed_priority=65,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_dependency_map",
                ctx,
                _dependency_map_result,
            ),
        ),
        ToolSpec(
            tool_name="m3.get_module_summaries",
            source_module="m3_analysis.module_identifier",
            description="Return ranked module summaries from static analysis.",
            parameters=_empty_parameters(),
            output_contract="Module summaries sorted by importance and path.",
            seed_priority=55,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_module_summaries",
                ctx,
                _module_summaries_result,
            ),
        ),
        ToolSpec(
            tool_name="m3.get_layer_view",
            source_module="m3_analysis.layer_inferrer",
            description="Return the teaching-oriented layer view.",
            parameters=_empty_parameters(),
            output_contract="Layer view result with uncertainty note.",
            seed_priority=75,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_layer_view",
                ctx,
                lambda analysis: _tool_result(
                    "m3.get_layer_view",
                    "m3_analysis.layer_inferrer",
                    f"Layer view status: {analysis.layer_view.status}.",
                    analysis.layer_view.model_dump(mode="json"),
                    generated_at=analysis.generated_at,
                ),
            ),
        ),
        ToolSpec(
            tool_name="m3.get_flow_summaries",
            source_module="m3_analysis.flow_tracer",
            description="Return candidate flow skeletons from static analysis.",
            parameters=_empty_parameters(),
            output_contract="Flow summaries with uncertainty wording.",
            seed_priority=70,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_flow_summaries",
                ctx,
                lambda analysis: _tool_result(
                    "m3.get_flow_summaries",
                    "m3_analysis.flow_tracer",
                    f"Found {len(analysis.flow_summaries)} candidate flow summaries.",
                    {"flow_summaries": _dump_models(analysis.flow_summaries[:10])},
                    generated_at=analysis.generated_at,
                ),
            ),
        ),
        ToolSpec(
            tool_name="m3.get_reading_path",
            source_module="m3_analysis.reading_path_builder",
            description="Return the raw reading path from M3 static analysis.",
            parameters=_empty_parameters(),
            output_contract="Reading step list from the static-analysis pass.",
            seed_priority=42,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_reading_path",
                ctx,
                lambda analysis: _tool_result(
                    "m3.get_reading_path",
                    "m3_analysis.reading_path_builder",
                    f"Reading path contains {len(analysis.reading_path)} steps.",
                    {"reading_path": _dump_models(analysis.reading_path[:8])},
                    generated_at=analysis.generated_at,
                ),
            ),
        ),
        ToolSpec(
            tool_name="m3.get_evidence_catalog",
            source_module="m3_analysis.evidence_collector",
            description="Return a capped evidence catalog for citation and follow-up checks.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 40},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": [],
            },
            output_contract="Evidence catalog entries with sensitive excerpts stripped.",
            seed_priority=60,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_evidence_catalog",
                ctx,
                lambda analysis: _evidence_catalog_result(
                    analysis,
                    limit=int(arguments.get("limit", 40) or 40),
                    evidence_ids=arguments.get("evidence_ids"),
                ),
            ),
        ),
        ToolSpec(
            tool_name="m3.get_unknowns_and_warnings",
            source_module="m3_analysis",
            description="Return current unknown items and non-fatal warnings.",
            parameters=_empty_parameters(),
            output_contract="Unknown items and warnings lists.",
            seed_priority=85,
            handler=lambda arguments, ctx: _analysis_projection(
                "m3.get_unknowns_and_warnings",
                ctx,
                lambda analysis: _tool_result(
                    "m3.get_unknowns_and_warnings",
                    "m3_analysis",
                    f"Unknown items: {len(analysis.unknown_items)}, warnings: {len(analysis.warnings)}.",
                    {
                        "unknown_items": _dump_models(analysis.unknown_items[:30]),
                        "warnings": _dump_models(analysis.warnings[:30]),
                    },
                    generated_at=analysis.generated_at,
                ),
            ),
        ),
        ToolSpec(
            tool_name="m4.get_initial_report_skeleton",
            source_module="m4_skeleton.skeleton_assembler",
            description="Return the initial teaching/report skeleton assembled from static analysis.",
            parameters=_empty_parameters(),
            output_contract="Initial report skeleton projection.",
            preferred_seed=True,
            seed_priority=12,
            handler=lambda arguments, ctx: _skeleton_projection(
                "m4.get_initial_report_skeleton",
                ctx,
                lambda skeleton: _initial_report_skeleton_result(skeleton),
            ),
        ),
        ToolSpec(
            tool_name="m4.get_topic_slice",
            source_module="m4_skeleton.topic_indexer",
            description="Return topic refs for the requested learning goal.",
            parameters={
                "type": "object",
                "properties": {"learning_goal": {"type": "string"}},
                "required": [],
            },
            output_contract="Topic refs grouped for the current teaching goal.",
            preferred_seed=True,
            seed_priority=18,
            handler=lambda arguments, ctx: _topic_slice_tool(arguments, ctx),
        ),
        ToolSpec(
            tool_name="m4.get_next_questions",
            source_module="m4_skeleton.skeleton_assembler",
            description="Return the next teaching questions suggested by M4.",
            parameters=_empty_parameters(),
            output_contract="Next-step suggestions from the teaching skeleton.",
            preferred_seed=True,
            seed_priority=22,
            handler=lambda arguments, ctx: _skeleton_projection(
                "m4.get_next_questions",
                ctx,
                lambda skeleton: _tool_result(
                    "m4.get_next_questions",
                    "m4_skeleton.skeleton_assembler",
                    "Suggested next questions from the teaching skeleton.",
                    {"suggested_next_questions": _dump_models(skeleton.suggested_next_questions[:5])},
                    generated_at=skeleton.generated_at,
                ),
            ),
        ),
        ToolSpec(
            tool_name="teaching.get_state_snapshot",
            source_module="m5_session.teaching_state",
            description="Return the current teaching plan, student state, and working log summary.",
            parameters=_empty_parameters(),
            output_contract="Compact current teaching state snapshot.",
            deterministic=False,
            preferred_seed=True,
            seed_priority=8,
            handler=lambda arguments, ctx: _teaching_state_snapshot_result(ctx.conversation),
        ),
    ]


def _mode_only_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["teaching", "workspace"], "default": "teaching"}
        },
        "required": [],
    }


def _empty_parameters() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": []}


def _kb_tool(
    tool_name: str,
    ctx: ToolContext,
    factory,
) -> LlmToolResult:
    if ctx.analysis is None:
        return _missing_context_result(tool_name, "analysis_not_available")
    return factory(ctx.analysis)


def _analysis_projection(
    tool_name: str,
    ctx: ToolContext,
    factory,
) -> LlmToolResult:
    if ctx.analysis is None:
        return _missing_context_result(tool_name, "analysis_not_available")
    return factory(ctx.analysis)


def _skeleton_projection(
    tool_name: str,
    ctx: ToolContext,
    factory,
) -> LlmToolResult:
    if ctx.teaching_skeleton is None:
        return _missing_context_result(tool_name, "teaching_skeleton_not_available")
    return factory(ctx.teaching_skeleton)


def _topic_slice_tool(arguments: dict[str, Any], ctx: ToolContext) -> LlmToolResult:
    if ctx.teaching_skeleton is None:
        return _missing_context_result("m4.get_topic_slice", "teaching_skeleton_not_available")
    goal_value = str(
        arguments.get("learning_goal")
        or (ctx.conversation.current_learning_goal if ctx.conversation else LearningGoal.OVERVIEW)
    )
    try:
        goal = LearningGoal(goal_value)
    except ValueError:
        goal = LearningGoal.OVERVIEW
    refs = _topic_slice_for_goal(ctx.teaching_skeleton, goal)
    return _tool_result(
        "m4.get_topic_slice",
        "m4_skeleton.topic_indexer",
        f"Selected {len(refs)} topic refs for goal {goal}.",
        {
            "learning_goal": goal,
            "topic_slice": _dump_models(refs),
            "topic_index_counts": {
                "structure": len(ctx.teaching_skeleton.topic_index.structure_refs),
                "entry": len(ctx.teaching_skeleton.topic_index.entry_refs),
                "flow": len(ctx.teaching_skeleton.topic_index.flow_refs),
                "layer": len(ctx.teaching_skeleton.topic_index.layer_refs),
                "dependency": len(ctx.teaching_skeleton.topic_index.dependency_refs),
                "module": len(ctx.teaching_skeleton.topic_index.module_refs),
                "reading_path": len(ctx.teaching_skeleton.topic_index.reading_path_refs),
                "unknown": len(ctx.teaching_skeleton.topic_index.unknown_refs),
            },
        },
        generated_at=ctx.teaching_skeleton.generated_at,
    )


def _repository_context_result(repository: RepositoryContext) -> LlmToolResult:
    return _tool_result(
        "m1.get_repository_context",
        "m1_repo_access",
        "Repository access context and read-only policy summary.",
        {
            "repo_id": repository.repo_id,
            "display_name": repository.display_name,
            "source_type": repository.source_type,
            "is_temp_dir": repository.is_temp_dir,
            "owner": repository.owner,
            "name": repository.name,
            "access_verified": repository.access_verified,
            "primary_language": repository.primary_language,
            "repo_size_level": repository.repo_size_level,
            "source_code_file_count": repository.source_code_file_count,
            "read_policy": {
                "read_only": repository.read_policy.read_only,
                "allow_exec": repository.read_policy.allow_exec,
                "allow_dependency_install": repository.read_policy.allow_dependency_install,
                "allow_private_github": repository.read_policy.allow_private_github,
                "max_source_files_full_analysis": repository.read_policy.max_source_files_full_analysis,
            },
        },
    )


def _file_tree_summary_result(file_tree: FileTreeSnapshot) -> LlmToolResult:
    top_level_dirs = [
        node.relative_path
        for node in file_tree.nodes
        if node.depth == 1 and node.node_type == FileNodeType.DIRECTORY
    ][:30]
    top_level_files = [
        node.relative_path
        for node in file_tree.nodes
        if node.depth == 1 and node.node_type == FileNodeType.FILE
    ][:30]
    return _tool_result(
        "m2.get_file_tree_summary",
        "m2_file_tree",
        "Scanned file-tree summary with top-level paths and degradation notices.",
        {
            "snapshot_id": file_tree.snapshot_id,
            "primary_language": file_tree.primary_language,
            "repo_size_level": file_tree.repo_size_level,
            "source_code_file_count": file_tree.source_code_file_count,
            "language_stats": _dump_models(file_tree.language_stats[:8]),
            "top_level_directories": top_level_dirs,
            "top_level_files": top_level_files,
            "ignored_rule_count": len(file_tree.ignored_rules),
            "sensitive_matches": [
                {
                    "relative_path": item.relative_path,
                    "matched_pattern": item.matched_pattern,
                    "content_read": item.content_read,
                    "user_notice": item.user_notice,
                }
                for item in file_tree.sensitive_matches[:20]
            ],
            "degraded_scan_scope": (
                file_tree.degraded_scan_scope.model_dump(mode="json")
                if file_tree.degraded_scan_scope
                else None
            ),
        },
        generated_at=file_tree.generated_at,
    )


def _relevant_files_result(file_tree: FileTreeSnapshot, *, limit: int = 80) -> LlmToolResult:
    nodes = [
        node
        for node in file_tree.nodes
        if node.node_type == FileNodeType.FILE
        and node.status == FileNodeStatus.NORMAL
        and (node.is_source_file or _is_repo_doc(node.relative_path))
    ]
    nodes.sort(key=lambda item: (not _is_repo_doc(item.relative_path), item.depth, item.relative_path))
    return _tool_result(
        "m2.list_relevant_files",
        "m2_file_tree",
        f"Listed {min(len(nodes), limit)} relevant source or repository-doc files.",
        {
            "files": [
                {
                    "relative_path": node.relative_path,
                    "extension": node.extension,
                    "is_source_file": node.is_source_file,
                    "is_python_source": node.is_python_source,
                    "size_bytes": node.size_bytes,
                    "depth": node.depth,
                }
                for node in nodes[:limit]
            ],
            "total_relevant_file_count": len(nodes),
        },
        generated_at=file_tree.generated_at,
    )


def _dependency_map_result(analysis: AnalysisBundle) -> LlmToolResult:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in analysis.import_classifications:
        grouped.setdefault(str(item.source_type), []).append(item.model_dump(mode="json"))
    return _tool_result(
        "m3.get_dependency_map",
        "m3_analysis.import_analyzer",
        f"Dependency classifications: {len(analysis.import_classifications)} items.",
        {key: values[:30] for key, values in sorted(grouped.items(), key=lambda pair: pair[0])},
        generated_at=analysis.generated_at,
    )


def _module_summaries_result(analysis: AnalysisBundle) -> LlmToolResult:
    modules = sorted(
        analysis.module_summaries,
        key=lambda item: (item.importance_rank is None, item.importance_rank or 999, item.path),
    )
    return _tool_result(
        "m3.get_module_summaries",
        "m3_analysis.module_identifier",
        f"Ranked {len(analysis.module_summaries)} module summaries.",
        {"module_summaries": _dump_models(modules[:30])},
        generated_at=analysis.generated_at,
    )


def _evidence_catalog_result(
    analysis: AnalysisBundle,
    *,
    limit: int = 40,
    evidence_ids: list[str] | None = None,
) -> LlmToolResult:
    evidence = analysis.evidence_catalog
    if evidence_ids:
        wanted = set(evidence_ids)
        evidence = [item for item in evidence if item.evidence_id in wanted]
    evidence = evidence[:limit]
    return _tool_result(
        "m3.get_evidence_catalog",
        "m3_analysis.evidence_collector",
        f"Provided {len(evidence)} evidence entries for reference.",
        {
            "evidence_catalog": [
                {
                    **item.model_dump(mode="json"),
                    "content_excerpt": None if item.is_sensitive_source else _redact(item.content_excerpt or ""),
                }
                for item in evidence
            ],
            "total_evidence_count": len(analysis.evidence_catalog),
        },
        generated_at=analysis.generated_at,
    )


def _initial_report_skeleton_result(skeleton: TeachingSkeleton) -> LlmToolResult:
    return _tool_result(
        "m4.get_initial_report_skeleton",
        "m4_skeleton.skeleton_assembler",
        "Initial report skeleton assembled from deterministic analysis artifacts.",
        {
            "overview": skeleton.overview.model_dump(mode="json"),
            "focus_points": _dump_models(skeleton.focus_points),
            "repo_mapping": _dump_models(skeleton.repo_mapping),
            "language_and_type": skeleton.language_and_type.model_dump(mode="json"),
            "key_directories": _dump_models(skeleton.key_directories),
            "entry_section": skeleton.entry_section.model_dump(mode="json"),
            "recommended_first_step": skeleton.recommended_first_step.model_dump(mode="json"),
            "reading_path_preview": _dump_models(skeleton.reading_path_preview),
            "unknown_section": _dump_models(skeleton.unknown_section),
            "suggested_next_questions": _dump_models(skeleton.suggested_next_questions),
        },
        generated_at=skeleton.generated_at,
    )


def _teaching_state_snapshot_result(conversation: ConversationState | None) -> LlmToolResult:
    if conversation is None:
        return _missing_context_result("teaching.get_state_snapshot", "conversation_not_available")
    plan = conversation.teaching_plan_state
    student_state = conversation.student_learning_state
    teacher_log = conversation.teacher_working_log
    return _tool_result(
        "teaching.get_state_snapshot",
        "m5_session.teaching_state",
        "Current teaching plan, student state, and teacher working log summary.",
        {
            "teaching_plan": {
                "plan_id": plan.plan_id,
                "current_step_id": plan.current_step_id,
                "steps": [
                    {
                        "step_id": step.step_id,
                        "title": step.title,
                        "goal": step.goal,
                        "status": step.status,
                        "target_scope": step.target_scope,
                    }
                    for step in plan.steps[:8]
                ],
            }
            if plan
            else None,
            "student_learning_state": {
                "state_id": student_state.state_id,
                "topics": [
                    {
                        "topic": item.topic,
                        "coverage_level": item.coverage_level,
                        "recommended_intervention": item.recommended_intervention,
                    }
                    for item in student_state.topics[:10]
                ],
            }
            if student_state
            else None,
            "teacher_working_log": {
                "current_teaching_objective": teacher_log.current_teaching_objective,
                "planned_transition": teacher_log.planned_transition,
                "student_risk_notes": teacher_log.student_risk_notes[:5],
                "recent_decisions": teacher_log.recent_decisions[-4:],
            }
            if teacher_log
            else None,
            "current_teaching_decision": (
                conversation.current_teaching_decision.model_dump(mode="json")
                if conversation.current_teaching_decision
                else None
            ),
        },
    )


def build_starter_excerpts_result(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    analysis: AnalysisBundle,
    *,
    max_files: int = 2,
    max_lines: int = 60,
) -> LlmToolResult | None:
    paths: list[str] = []
    for candidate in ("README.md", "README.rst", "README.txt", "readme.md"):
        if any(
            node.relative_path == candidate
            and node.node_type == FileNodeType.FILE
            and node.status == FileNodeStatus.NORMAL
            for node in file_tree.nodes
        ):
            paths.append(candidate)
            break
    for entry in analysis.entry_candidates[:2]:
        if entry.target_value != "unknown":
            paths.append(entry.target_value)

    excerpts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        normalized = path.replace("\\", "/").strip("/")
        if normalized in seen:
            continue
        if len(excerpts) >= max_files:
            break
        seen.add(normalized)
        result = read_file_excerpt(
            repository,
            file_tree,
            relative_path=normalized,
            start_line=1,
            max_lines=max_lines,
        )
        if result.payload.get("available"):
            excerpts.append(result.payload)
    if not excerpts:
        return None
    return _tool_result(
        "read_file_excerpt",
        "agent_tools.repository_tools",
        f"Prepared {len(excerpts)} starter excerpts from entry or README files.",
        {"files": excerpts},
    )


def _topic_slice_for_goal(skeleton: TeachingSkeleton, goal: LearningGoal) -> list[TopicRef]:
    refs: list[TopicRef] = []
    for attr in _TOPIC_ATTRS_BY_GOAL.get(goal, ()):
        refs.extend(getattr(skeleton.topic_index, attr))
    deduped: list[TopicRef] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.ref_id in seen:
            continue
        deduped.append(ref)
        seen.add(ref.ref_id)
    return deduped[:10]


def _missing_context_result(tool_name: str, reason: str) -> LlmToolResult:
    return _tool_result(
        tool_name,
        "agent_tools.analysis_tools",
        f"{tool_name} is unavailable because {reason}.",
        {"available": False, "reason": reason},
    )


def _tool_result(
    tool_name: str,
    source_module: str,
    summary: str,
    payload: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> LlmToolResult:
    return LlmToolResult(
        result_id=stable_id("tool_result", tool_name, summary),
        tool_name=tool_name,
        source_module=source_module,
        summary=summary,
        payload=payload,
        reference_only=True,
        generated_at=generated_at or datetime.now(UTC),
    )


def _dump_models(items: list[Any]) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        for item in items
    ]


def _is_repo_doc(relative_path: str) -> bool:
    lowered = relative_path.lower()
    return lowered.startswith("readme") or lowered in {
        "pyproject.toml",
        "package.json",
        "requirements.txt",
        "setup.py",
    }


def _redact(value: str) -> str:
    return _SECRET_RE.sub("[redacted_secret]", value)
