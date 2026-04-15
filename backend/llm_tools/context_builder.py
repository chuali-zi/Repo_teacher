from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.contracts.domain import (
    AnalysisBundle,
    ConversationState,
    FileNode,
    FileTreeSnapshot,
    LlmToolContext,
    LlmToolDefinition,
    LlmToolResult,
    RepositoryContext,
    TeachingSkeleton,
    TopicRef,
)
from backend.contracts.enums import FileNodeStatus, FileNodeType
from backend.m3_analysis._helpers import stable_id
from backend.security.safety import resolve_repo_relative_path

REFERENCE_POLICY = (
    "这些工具输出是只读参考，不是回答边界。LLM 可以基于工具结果、会话教学状态、"
    "用户问题和通用编程知识作答；当工具证据不足时必须明确标注“根据推断”、"
    "“可能”或“目前不确定”。静态分析里的入口、流程、分层和职责都应视为候选结论。"
)

_SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,})"
)
_MAX_EXCERPT_BYTES = 240_000


def tool_definitions() -> list[LlmToolDefinition]:
    return [
        LlmToolDefinition(
            tool_name="m1.get_repository_context",
            source_module="m1_repo_access",
            description="读取当前仓库来源、展示名、访问状态和只读安全策略摘要。",
            output_contract="Repository metadata without root_path or credentials.",
            safety_notes=["不暴露 root_path。", "不修改仓库。"],
        ),
        LlmToolDefinition(
            tool_name="m2.get_file_tree_summary",
            source_module="m2_file_tree",
            description="读取文件树统计、主语言、规模等级、顶层目录和敏感文件标记。",
            output_contract="Compact FileTreeSnapshot summary.",
            safety_notes=["敏感文件只暴露相对路径和跳过说明。"],
        ),
        LlmToolDefinition(
            tool_name="m2.list_relevant_files",
            source_module="m2_file_tree",
            description="列出可读源码文件和关键非源码文件，供 LLM 决定是否需要继续定位。",
            input_schema={"limit": "int, default 80"},
            output_contract="List of relative paths with file metadata.",
            safety_notes=["仅列路径和大小，不读正文。"],
        ),
        LlmToolDefinition(
            tool_name="m3.get_project_profile",
            source_module="m3_analysis.project_profiler",
            description="读取项目类型候选、主语言和项目画像置信度。",
            output_contract="ProjectProfileResult.",
        ),
        LlmToolDefinition(
            tool_name="m3.get_entry_candidates",
            source_module="m3_analysis.entry_detector",
            description="读取入口候选、排序、理由、置信度和相关未知项。",
            output_contract="EntryCandidate list.",
        ),
        LlmToolDefinition(
            tool_name="m3.get_dependency_map",
            source_module="m3_analysis.import_analyzer",
            description="读取 import 来源分类，区分内部、标准库、第三方和未知依赖。",
            output_contract="Grouped ImportClassification list.",
        ),
        LlmToolDefinition(
            tool_name="m3.get_module_summaries",
            source_module="m3_analysis.module_identifier",
            description="读取关键模块、候选职责、重要性、上下游关系和主路径角色。",
            output_contract="Ranked ModuleSummary list.",
        ),
        LlmToolDefinition(
            tool_name="m3.get_layer_view",
            source_module="m3_analysis.layer_inferrer",
            description="读取教学式分层候选和不确定说明。",
            output_contract="LayerViewResult.",
        ),
        LlmToolDefinition(
            tool_name="m3.get_flow_summaries",
            source_module="m3_analysis.flow_tracer",
            description="读取候选流程骨架。该结果不是运行时真实调用链。",
            output_contract="FlowSummary list.",
            safety_notes=["必须使用候选措辞。"],
        ),
        LlmToolDefinition(
            tool_name="m3.get_reading_path",
            source_module="m3_analysis.reading_path_builder",
            description="读取建议阅读路径和每一步的学习收益。",
            output_contract="ReadingStep list.",
        ),
        LlmToolDefinition(
            tool_name="m3.get_evidence_catalog",
            source_module="m3_analysis.evidence_collector",
            description="读取证据目录，帮助 LLM 给出证据化解释。",
            input_schema={"limit": "int, default 40", "evidence_ids": "optional list[str]"},
            output_contract="EvidenceRef list.",
            safety_notes=["敏感来源不含正文摘录。"],
        ),
        LlmToolDefinition(
            tool_name="m3.get_unknowns_and_warnings",
            source_module="m3_analysis",
            description="读取未知项和非致命警告，用于提示不确定边界。",
            output_contract="UnknownItem and AnalysisWarning lists.",
        ),
        LlmToolDefinition(
            tool_name="m4.get_initial_report_skeleton",
            source_module="m4_skeleton.skeleton_assembler",
            description="读取按首轮报告顺序组织的教学骨架参考。",
            output_contract="Initial-report projection of TeachingSkeleton.",
        ),
        LlmToolDefinition(
            tool_name="m4.get_topic_slice",
            source_module="m4_skeleton.topic_indexer",
            description="读取本轮学习目标对应的主题引用切片。",
            input_schema={"learning_goal": "LearningGoal"},
            output_contract="TopicRef list.",
        ),
        LlmToolDefinition(
            tool_name="m4.get_next_questions",
            source_module="m4_skeleton.skeleton_assembler",
            description="读取 M4 建议的下一步问题。",
            output_contract="Suggestion list.",
        ),
        LlmToolDefinition(
            tool_name="repo.read_file_excerpt",
            source_module="llm_tools.repository_reader",
            description="安全读取一个非敏感文件的指定行范围摘录。",
            input_schema={
                "relative_path": "str",
                "start_line": "int, default 1",
                "max_lines": "int, default 80, max 160",
            },
            output_contract="Redacted file excerpt with line range.",
            safety_notes=["拒绝越界路径。", "拒绝敏感、忽略或不可读文件。", "密钥形态会被脱敏。"],
        ),
        LlmToolDefinition(
            tool_name="repo.search_text",
            source_module="llm_tools.repository_reader",
            description="在可读非敏感文本文件中搜索关键词，返回匹配行摘录。",
            input_schema={"query": "str", "max_matches": "int, default 20, max 50"},
            output_contract="List of path, line_no and redacted line excerpt.",
            safety_notes=["不搜索敏感或已忽略文件。", "密钥形态会被脱敏。"],
        ),
        LlmToolDefinition(
            tool_name="teaching.get_state_snapshot",
            source_module="m5_session.teaching_state",
            description="读取教学计划、学生状态和教师工作日志摘要，维持教学连续性。",
            output_contract="Compact teaching state snapshot.",
            deterministic=False,
        ),
    ]


def build_llm_tool_context(
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    analysis: AnalysisBundle,
    teaching_skeleton: TeachingSkeleton,
    conversation: ConversationState,
    topic_slice: list[TopicRef],
) -> LlmToolContext:
    results = [
        _repository_context_result(repository),
        _file_tree_summary_result(file_tree),
        _relevant_files_result(file_tree),
        _project_profile_result(analysis),
        _entry_candidates_result(analysis),
        _dependency_map_result(analysis),
        _module_summaries_result(analysis),
        _layer_view_result(analysis),
        _flow_summaries_result(analysis),
        _reading_path_result(analysis),
        _evidence_catalog_result(analysis),
        _unknowns_and_warnings_result(analysis),
        _initial_report_skeleton_result(teaching_skeleton),
        _topic_slice_result(topic_slice, teaching_skeleton),
        _next_questions_result(teaching_skeleton),
        _starter_excerpts_result(repository, file_tree, analysis),
        _teaching_state_snapshot_result(conversation),
    ]
    return LlmToolContext(
        policy=REFERENCE_POLICY,
        tools=tool_definitions(),
        tool_results=[item for item in results if item is not None],
    )


def read_file_excerpt(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    *,
    relative_path: str,
    start_line: int = 1,
    max_lines: int = 80,
) -> LlmToolResult:
    normalized = _normalize_relative_path(relative_path)
    node = _find_readable_file_node(file_tree, normalized)
    if node is None:
        return _tool_result(
            "repo.read_file_excerpt",
            "llm_tools.repository_reader",
            f"{normalized} 不可作为 LLM 工具读取。",
            {
                "relative_path": normalized,
                "available": False,
                "reason": "file_not_found_or_not_readable",
            },
        )
    if node.size_bytes and node.size_bytes > _MAX_EXCERPT_BYTES:
        return _tool_result(
            "repo.read_file_excerpt",
            "llm_tools.repository_reader",
            f"{normalized} 文件较大，未自动读取正文。",
            {
                "relative_path": normalized,
                "available": False,
                "reason": "file_too_large",
                "size_bytes": node.size_bytes,
            },
        )

    repo_root = Path(repository.root_path).expanduser().resolve(strict=True)
    file_path = resolve_repo_relative_path(repo_root, normalized)
    lines = _safe_read_lines(file_path)
    if lines is None:
        return _tool_result(
            "repo.read_file_excerpt",
            "llm_tools.repository_reader",
            f"{normalized} 读取失败。",
            {
                "relative_path": normalized,
                "available": False,
                "reason": "decode_or_read_failed",
            },
        )

    safe_start = max(start_line, 1)
    safe_max = min(max(max_lines, 1), 160)
    selected = lines[safe_start - 1 : safe_start - 1 + safe_max]
    excerpt = "".join(selected)
    return _tool_result(
        "repo.read_file_excerpt",
        "llm_tools.repository_reader",
        f"读取 {normalized} 第 {safe_start} 行起的 {len(selected)} 行摘录。",
        {
            "relative_path": normalized,
            "available": True,
            "start_line": safe_start,
            "line_count": len(selected),
            "total_lines": len(lines),
            "excerpt": _redact(excerpt),
        },
    )


def search_text(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    *,
    query: str,
    max_matches: int = 20,
) -> LlmToolResult:
    stripped_query = query.strip()
    if not stripped_query:
        return _tool_result(
            "repo.search_text",
            "llm_tools.repository_reader",
            "搜索词为空，未执行搜索。",
            {"query": query, "matches": []},
        )

    repo_root = Path(repository.root_path).expanduser().resolve(strict=True)
    matches: list[dict[str, Any]] = []
    lowered_query = stripped_query.casefold()
    limit = min(max(max_matches, 1), 50)

    for node in _readable_text_nodes(file_tree):
        if len(matches) >= limit:
            break
        if node.size_bytes and node.size_bytes > _MAX_EXCERPT_BYTES:
            continue
        file_path = resolve_repo_relative_path(repo_root, node.relative_path)
        lines = _safe_read_lines(file_path)
        if lines is None:
            continue
        for line_no, line in enumerate(lines, start=1):
            if lowered_query not in line.casefold():
                continue
            matches.append(
                {
                    "relative_path": node.relative_path,
                    "line_no": line_no,
                    "line": _redact(line.strip())[:260],
                }
            )
            if len(matches) >= limit:
                break

    return _tool_result(
        "repo.search_text",
        "llm_tools.repository_reader",
        f"搜索 {stripped_query!r} 得到 {len(matches)} 条匹配。",
        {"query": stripped_query, "matches": matches},
    )


def _repository_context_result(repository: RepositoryContext) -> LlmToolResult:
    return _tool_result(
        "m1.get_repository_context",
        "m1_repo_access",
        "当前仓库访问上下文与只读策略摘要。",
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
                "max_source_files_full_analysis": (
                    repository.read_policy.max_source_files_full_analysis
                ),
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
        "文件树扫描、过滤、语言和规模摘要。",
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


def _relevant_files_result(file_tree: FileTreeSnapshot, limit: int = 80) -> LlmToolResult:
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
        f"列出 {min(len(nodes), limit)} 个可读源码或说明文件。",
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


def _project_profile_result(analysis: AnalysisBundle) -> LlmToolResult:
    return _tool_result(
        "m3.get_project_profile",
        "m3_analysis.project_profiler",
        "项目画像和项目类型候选。",
        analysis.project_profile.model_dump(mode="json"),
        generated_at=analysis.generated_at,
    )


def _entry_candidates_result(analysis: AnalysisBundle) -> LlmToolResult:
    return _tool_result(
        "m3.get_entry_candidates",
        "m3_analysis.entry_detector",
        f"发现 {len(analysis.entry_candidates)} 个入口候选。",
        {"entry_candidates": _dump_models(analysis.entry_candidates[:12])},
        generated_at=analysis.generated_at,
    )


def _dependency_map_result(analysis: AnalysisBundle) -> LlmToolResult:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in analysis.import_classifications:
        grouped.setdefault(str(item.source_type), []).append(item.model_dump(mode="json"))
    return _tool_result(
        "m3.get_dependency_map",
        "m3_analysis.import_analyzer",
        f"依赖分类共 {len(analysis.import_classifications)} 项。",
        {
            key: values[:30]
            for key, values in sorted(grouped.items(), key=lambda pair: pair[0])
        },
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
        f"关键模块摘要共 {len(analysis.module_summaries)} 项。",
        {"module_summaries": _dump_models(modules[:30])},
        generated_at=analysis.generated_at,
    )


def _layer_view_result(analysis: AnalysisBundle) -> LlmToolResult:
    return _tool_result(
        "m3.get_layer_view",
        "m3_analysis.layer_inferrer",
        f"分层视图状态: {analysis.layer_view.status}。",
        analysis.layer_view.model_dump(mode="json"),
        generated_at=analysis.generated_at,
    )


def _flow_summaries_result(analysis: AnalysisBundle) -> LlmToolResult:
    return _tool_result(
        "m3.get_flow_summaries",
        "m3_analysis.flow_tracer",
        f"候选流程骨架共 {len(analysis.flow_summaries)} 条。",
        {"flow_summaries": _dump_models(analysis.flow_summaries[:10])},
        generated_at=analysis.generated_at,
    )


def _reading_path_result(analysis: AnalysisBundle) -> LlmToolResult:
    return _tool_result(
        "m3.get_reading_path",
        "m3_analysis.reading_path_builder",
        f"建议阅读路径共 {len(analysis.reading_path)} 步。",
        {"reading_path": _dump_models(analysis.reading_path[:8])},
        generated_at=analysis.generated_at,
    )


def _evidence_catalog_result(analysis: AnalysisBundle, limit: int = 40) -> LlmToolResult:
    evidence = analysis.evidence_catalog[:limit]
    return _tool_result(
        "m3.get_evidence_catalog",
        "m3_analysis.evidence_collector",
        f"提供 {len(evidence)} 条证据索引供引用。",
        {
            "evidence_catalog": [
                {
                    **item.model_dump(mode="json"),
                    "content_excerpt": None
                    if item.is_sensitive_source
                    else _redact(item.content_excerpt or ""),
                }
                for item in evidence
            ],
            "total_evidence_count": len(analysis.evidence_catalog),
        },
        generated_at=analysis.generated_at,
    )


def _unknowns_and_warnings_result(analysis: AnalysisBundle) -> LlmToolResult:
    return _tool_result(
        "m3.get_unknowns_and_warnings",
        "m3_analysis",
        f"未知项 {len(analysis.unknown_items)} 个，警告 {len(analysis.warnings)} 个。",
        {
            "unknown_items": _dump_models(analysis.unknown_items[:30]),
            "warnings": _dump_models(analysis.warnings[:30]),
        },
        generated_at=analysis.generated_at,
    )


def _initial_report_skeleton_result(skeleton: TeachingSkeleton) -> LlmToolResult:
    payload = {
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
    }
    return _tool_result(
        "m4.get_initial_report_skeleton",
        "m4_skeleton.skeleton_assembler",
        "首轮报告可用的教学骨架参考，不限制 LLM 的解释方式。",
        payload,
        generated_at=skeleton.generated_at,
    )


def _topic_slice_result(
    topic_slice: list[TopicRef],
    skeleton: TeachingSkeleton,
) -> LlmToolResult:
    return _tool_result(
        "m4.get_topic_slice",
        "m4_skeleton.topic_indexer",
        f"本轮主题切片包含 {len(topic_slice)} 个主题引用。",
        {
            "topic_slice": _dump_models(topic_slice),
            "topic_index_counts": {
                "structure": len(skeleton.topic_index.structure_refs),
                "entry": len(skeleton.topic_index.entry_refs),
                "flow": len(skeleton.topic_index.flow_refs),
                "layer": len(skeleton.topic_index.layer_refs),
                "dependency": len(skeleton.topic_index.dependency_refs),
                "module": len(skeleton.topic_index.module_refs),
                "reading_path": len(skeleton.topic_index.reading_path_refs),
                "unknown": len(skeleton.topic_index.unknown_refs),
            },
        },
        generated_at=skeleton.generated_at,
    )


def _next_questions_result(skeleton: TeachingSkeleton) -> LlmToolResult:
    return _tool_result(
        "m4.get_next_questions",
        "m4_skeleton.skeleton_assembler",
        "M4 推荐下一步问题。",
        {"suggested_next_questions": _dump_models(skeleton.suggested_next_questions[:5])},
        generated_at=skeleton.generated_at,
    )


def _starter_excerpts_result(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    analysis: AnalysisBundle,
) -> LlmToolResult | None:
    paths: list[str] = []
    for candidate in ("README.md", "README.rst", "README.txt", "readme.md"):
        if _find_readable_file_node(file_tree, candidate):
            paths.append(candidate)
            break
    for entry in analysis.entry_candidates[:2]:
        if entry.target_value != "unknown":
            paths.append(entry.target_value)

    excerpts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        normalized = _normalize_relative_path(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        result = read_file_excerpt(
            repository,
            file_tree,
            relative_path=normalized,
            start_line=1,
            max_lines=60,
        )
        if result.payload.get("available"):
            excerpts.append(result.payload)
    if not excerpts:
        return None
    return _tool_result(
        "repo.read_file_excerpt",
        "llm_tools.repository_reader",
        f"预读取 {len(excerpts)} 个入口/说明文件摘录。",
        {"files": excerpts},
    )


def _teaching_state_snapshot_result(conversation: ConversationState) -> LlmToolResult:
    plan = conversation.teaching_plan_state
    student_state = conversation.student_learning_state
    teacher_log = conversation.teacher_working_log
    return _tool_result(
        "teaching.get_state_snapshot",
        "m5_session.teaching_state",
        "当前教学计划、学生状态和教师工作日志摘要。",
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


def _normalize_relative_path(relative_path: str) -> str:
    return relative_path.replace("\\", "/").strip().strip("/")


def _find_readable_file_node(file_tree: FileTreeSnapshot, relative_path: str) -> FileNode | None:
    normalized = _normalize_relative_path(relative_path)
    for node in file_tree.nodes:
        if node.relative_path != normalized or node.node_type != FileNodeType.FILE:
            continue
        if node.status != FileNodeStatus.NORMAL:
            return None
        return node
    return None


def _readable_text_nodes(file_tree: FileTreeSnapshot) -> list[FileNode]:
    return [
        node
        for node in file_tree.nodes
        if node.node_type == FileNodeType.FILE
        and node.status == FileNodeStatus.NORMAL
        and (node.is_source_file or _is_repo_doc(node.relative_path))
    ]


def _safe_read_lines(file_path: Path) -> list[str] | None:
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(_MAX_EXCERPT_BYTES + 1)
    except OSError:
        return None
    if "\0" in text:
        return None
    return text.splitlines(keepends=True)


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
