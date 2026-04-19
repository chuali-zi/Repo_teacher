from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from backend.agent_tools.base import ToolContext, ToolSpec
from backend.agent_tools.repository_tools import read_file_excerpt
from backend.contracts.domain import (
    ConversationState,
    FileTreeSnapshot,
    LlmToolResult,
    RepositoryContext,
)
from backend.contracts.enums import FileNodeStatus, FileNodeType

_SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,})"
)
_SOURCE_PATH_RE = re.compile(
    r"(?<![\w./\\-])([A-Za-z0-9_./\\-]+\."
    r"(?:py|js|jsx|ts|tsx|md|toml|json|yaml|yml|css|html|txt|rst))(?![\w./\\-])",
    re.IGNORECASE,
)
_COMMON_START_FILES = (
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "main.py",
    "app.py",
    "__main__.py",
)


def build_analysis_tool_specs() -> list[ToolSpec]:
    return [
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
            seed_priority=10,
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
            preferred_seed=True,
            seed_priority=20,
            handler=lambda arguments, ctx: _relevant_files_result(
                ctx.file_tree,
                limit=int(arguments.get("limit", 80) or 80),
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
            seed_priority=30,
            handler=lambda arguments, ctx: _teaching_state_snapshot_result(ctx.conversation),
        ),
    ]


def build_starter_excerpts_result(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    *,
    user_text: str | None = None,
    max_files: int = 2,
    max_lines: int = 60,
) -> LlmToolResult | None:
    readable_paths = _readable_path_set(file_tree)
    candidate_paths = [
        *_paths_from_user_text(user_text or "", readable_paths),
        *[path for path in _COMMON_START_FILES if path in readable_paths],
    ]

    excerpts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in candidate_paths:
        normalized = path.replace("\\", "/").strip("/")
        if not normalized or normalized in seen:
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
        f"Prepared {len(excerpts)} starter excerpts from user hints or common entry files.",
        {"files": excerpts},
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
    nodes.sort(
        key=lambda item: (
            not _is_repo_doc(item.relative_path),
            item.depth,
            item.relative_path,
        )
    )
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
                    "tags": _path_tags(node.relative_path),
                }
                for node in nodes[:limit]
            ],
            "total_relevant_file_count": len(nodes),
        },
        generated_at=file_tree.generated_at,
    )


def _teaching_state_snapshot_result(conversation: ConversationState | None) -> LlmToolResult:
    if conversation is None:
        return _tool_result(
            "teaching.get_state_snapshot",
            "m5_session.teaching_state",
            "teaching.get_state_snapshot is unavailable because conversation_not_available.",
            {"available": False, "reason": "conversation_not_available"},
        )

    plan = conversation.teaching_plan_state
    student_state = conversation.student_learning_state
    teacher_log = conversation.teacher_working_log
    return _tool_result(
        "teaching.get_state_snapshot",
        "m5_session.teaching_state",
        "Current teaching plan, student state, and teacher working log summary.",
        {
            "current_learning_goal": conversation.current_learning_goal,
            "current_stage": conversation.current_stage,
            "message_count": len(conversation.messages),
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
                    for step in plan.steps[:6]
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
                        "last_explained_at_message_id": item.last_explained_at_message_id,
                        "student_signal": item.student_signal,
                        "supporting_evidence_count": len(item.supporting_evidence),
                    }
                    for item in student_state.topics[:8]
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
            "current_teaching_directive": (
                conversation.current_teaching_directive.model_dump(mode="json")
                if conversation.current_teaching_directive
                else None
            ),
        },
    )


def _readable_path_set(file_tree: FileTreeSnapshot) -> set[str]:
    return {
        node.relative_path.replace("\\", "/").strip("/")
        for node in file_tree.nodes
        if node.node_type == FileNodeType.FILE and node.status == FileNodeStatus.NORMAL
    }


def _paths_from_user_text(user_text: str, readable_paths: set[str]) -> list[str]:
    basename_index: dict[str, list[str]] = {}
    for path in readable_paths:
        basename_index.setdefault(path.rsplit("/", 1)[-1].casefold(), []).append(path)

    paths: list[str] = []
    for match in _SOURCE_PATH_RE.finditer(user_text):
        candidate = match.group(1).replace("\\", "/").strip("`'\".,:;()[]{}<>")
        normalized = candidate.strip("/")
        lowered = normalized.casefold()
        if lowered in {item.casefold() for item in readable_paths}:
            paths.append(_canonical_path(readable_paths, lowered))
            continue
        basename_matches = basename_index.get(normalized.rsplit("/", 1)[-1].casefold(), [])
        if len(basename_matches) == 1:
            paths.append(basename_matches[0])
    return _dedupe_paths(paths)


def _canonical_path(paths: set[str], lowered_path: str) -> str:
    return next(path for path in paths if path.casefold() == lowered_path)


def _dedupe_paths(paths: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = path.replace("\\", "/").strip("/")
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        deduped.append(normalized)
        seen.add(key)
    return deduped


def _path_tags(relative_path: str) -> list[str]:
    lowered = relative_path.lower()
    tags: list[str] = []
    if lowered.startswith("readme"):
        tags.append("doc")
    if lowered.endswith((".toml", ".json", ".yaml", ".yml")):
        tags.append("config")
    if "/test" in lowered or lowered.startswith("test") or lowered.endswith("_test.py"):
        tags.append("test")
    if lowered.endswith(".py"):
        tags.append("python")
    return tags


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


def _empty_parameters() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": []}


def _tool_result(
    tool_name: str,
    source_module: str,
    summary: str,
    payload: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> LlmToolResult:
    return LlmToolResult(
        result_id=_stable_id(tool_name, summary),
        tool_name=tool_name,
        source_module=source_module,
        summary=summary,
        payload=_redact_payload(payload),
        reference_only=True,
        generated_at=generated_at or datetime.now(UTC),
    )


def _stable_id(*parts: str) -> str:
    digest = hashlib.md5("::".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"tool_result_{digest[:16]}"


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str):
        return _SECRET_RE.sub("[redacted_secret]", value)
    return value
