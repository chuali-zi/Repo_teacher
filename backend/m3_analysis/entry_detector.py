from __future__ import annotations

import ast
import re

from backend.contracts.domain import EntryCandidate, FileTreeSnapshot, RepoSurfaceAssignment
from backend.contracts.enums import (
    ConfidenceLevel,
    EntryRole,
    EntryTargetType,
    RepoSurface,
    UnknownTopic,
)
from backend.m3_analysis._helpers import (
    iter_python_nodes,
    make_unknown,
    parse_python_module,
    read_node_text,
    stable_id,
)


def detect_entry_candidates(
    file_tree: FileTreeSnapshot,
    *,
    surface_map: dict[str, RepoSurfaceAssignment] | None = None,
    include_workspace_candidates: bool = False,
) -> list[EntryCandidate]:
    candidates: list[EntryCandidate] = []

    for node in iter_python_nodes(file_tree):
        path = node.relative_path
        basename = path.rsplit("/", 1)[-1]
        assignment = surface_map.get(path) if surface_map else None
        surface = assignment.surface if assignment else None
        if basename in {"__main__.py", "main.py", "app.py", "manage.py"}:
            candidates.append(
                _candidate(
                    path=path,
                    target_type=EntryTargetType.FILE,
                    reason=f"Conventional Python entry file `{basename}`.",
                    confidence=ConfidenceLevel.HIGH
                    if basename in {"__main__.py", "manage.py"}
                    else ConfidenceLevel.MEDIUM,
                    evidence_refs=[stable_id("evidence", "entry-file", path)],
                    surface=surface,
                    score=42.0 + _surface_bonus(surface),
                )
            )

        module = parse_python_module(node)
        if module is None:
            continue
        has_main_guard = False
        framework_name: str | None = None
        for child in ast.walk(module):
            if isinstance(child, ast.If):
                test = child.test
                if (
                    isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"
                    and len(test.ops) == 1
                    and len(test.comparators) == 1
                    and isinstance(test.ops[0], ast.Eq)
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == "__main__"
                ):
                    has_main_guard = True
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id in {"FastAPI", "Flask"}
            ):
                framework_name = child.func.id
        if has_main_guard:
            candidates.append(
                _candidate(
                    path=path,
                    target_type=EntryTargetType.FILE,
                    reason='Contains `if __name__ == "__main__"` runnable block.',
                    confidence=ConfidenceLevel.HIGH,
                    evidence_refs=[stable_id("evidence", "main-guard", path)],
                    surface=surface,
                    score=48.0 + _surface_bonus(surface),
                )
            )
        if framework_name:
            candidates.append(
                _candidate(
                    path=path,
                    target_type=EntryTargetType.FRAMEWORK_OBJECT,
                    reason=f"Defines a `{framework_name}` application object.",
                    confidence=ConfidenceLevel.MEDIUM,
                    evidence_refs=[stable_id("evidence", "framework", path, framework_name)],
                    surface=surface,
                    score=52.0 + _surface_bonus(surface),
                )
            )

    for node in file_tree.nodes:
        if node.node_type != "file":
            continue
        path = node.relative_path.lower()
        text = read_node_text(node) or ""
        assignment = surface_map.get(node.relative_path) if surface_map else None
        surface = assignment.surface if assignment else None
        if path.endswith("pyproject.toml"):
            for match in re.finditer(
                r"^\s*([A-Za-z0-9_.-]+)\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.MULTILINE
            ):
                script_name = match.group(1)
                target = match.group(2)
                if ":" not in target:
                    continue
                candidates.append(
                    _candidate(
                        path=script_name,
                        target_type=EntryTargetType.COMMAND,
                        reason=f"Declared script `{script_name}` in pyproject.toml.",
                        confidence=ConfidenceLevel.MEDIUM,
                        evidence_refs=[
                            stable_id("evidence", "script", node.relative_path, script_name)
                        ],
                        surface=surface,
                        score=38.0 + _surface_bonus(surface),
                    )
                )
        if path.endswith("readme.md"):
            for line in text.splitlines():
                normalized = line.strip()
                if normalized.startswith("python ") or normalized.startswith("uv run "):
                    candidates.append(
                        _candidate(
                            path=normalized,
                            target_type=EntryTargetType.COMMAND,
                            reason="README documents a run command.",
                            confidence=ConfidenceLevel.LOW,
                            evidence_refs=[
                                stable_id(
                                    "evidence", "readme-command", node.relative_path, normalized
                                )
                            ],
                            surface=surface,
                            score=22.0 + _surface_bonus(surface),
                        )
                    )

    deduped: list[EntryCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (str(candidate.target_type), candidate.target_value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    deduped.sort(
        key=lambda item: (
            _entry_role_priority(item.entry_role),
            -(item.score or 0.0),
            item.confidence != ConfidenceLevel.HIGH,
            item.confidence != ConfidenceLevel.MEDIUM,
            item.target_value,
        )
    )
    visible = deduped
    if not include_workspace_candidates:
        product_or_secondary = [
            item for item in deduped if item.entry_role != EntryRole.WORKSPACE_OR_TOOL_ENTRY
        ]
        if product_or_secondary:
            visible = product_or_secondary
    ranked: list[EntryCandidate] = []
    for index, candidate in enumerate(visible[:6], start=1):
        ranked.append(candidate.model_copy(update={"rank": index}))

    if ranked:
        return ranked

    return [
        EntryCandidate(
            entry_id=stable_id("entry", file_tree.repo_id, "unknown"),
            target_type=EntryTargetType.UNKNOWN,
            target_value="unknown",
            reason="No reliable Python entry candidate was found from filenames, runnable blocks, config, or README instructions.",
            confidence=ConfidenceLevel.UNKNOWN,
            rank=1,
            score=0.0,
            surface=None,
            entry_role=EntryRole.UNCERTAIN,
            evidence_refs=[],
            unknown_items=[
                make_unknown(
                    UnknownTopic.ENTRY,
                    "No reliable entry candidate found.",
                    [],
                    "Repository did not expose a clear Python entry file or command.",
                )
            ],
        )
    ]


def _candidate(
    *,
    path: str,
    target_type: EntryTargetType,
    reason: str,
    confidence: ConfidenceLevel,
    evidence_refs: list[str],
    surface: RepoSurface | None,
    score: float,
) -> EntryCandidate:
    return EntryCandidate(
        entry_id=stable_id("entry", path, target_type, reason),
        target_type=target_type,
        target_value=path,
        reason=reason,
        confidence=confidence,
        rank=0,
        score=score,
        surface=surface,
        entry_role=_entry_role_for_surface(surface, confidence),
        evidence_refs=evidence_refs,
        unknown_items=[],
    )


def _entry_role_for_surface(
    surface: RepoSurface | None,
    confidence: ConfidenceLevel,
) -> EntryRole:
    if surface == RepoSurface.PRODUCT:
        return (
            EntryRole.PRIMARY_PRODUCT_ENTRY
            if confidence in {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}
            else EntryRole.SECONDARY_RUNTIME_ENTRY
        )
    if surface in {
        RepoSurface.WORKSPACE_META,
        RepoSurface.TOOLING,
        RepoSurface.DOCS,
        RepoSurface.TEST,
        RepoSurface.BUILD,
    }:
        return EntryRole.WORKSPACE_OR_TOOL_ENTRY
    return (
        EntryRole.SECONDARY_RUNTIME_ENTRY
        if confidence != ConfidenceLevel.UNKNOWN
        else EntryRole.UNCERTAIN
    )


def _surface_bonus(surface: RepoSurface | None) -> float:
    if surface == RepoSurface.PRODUCT:
        return 30.0
    if surface == RepoSurface.ROOT_MISC:
        return 10.0
    if surface in {
        RepoSurface.WORKSPACE_META,
        RepoSurface.TOOLING,
        RepoSurface.DOCS,
        RepoSurface.TEST,
        RepoSurface.BUILD,
    }:
        return -25.0
    return 0.0


def _entry_role_priority(role: EntryRole) -> int:
    if role == EntryRole.PRIMARY_PRODUCT_ENTRY:
        return 0
    if role == EntryRole.SECONDARY_RUNTIME_ENTRY:
        return 1
    if role == EntryRole.WORKSPACE_OR_TOOL_ENTRY:
        return 2
    return 3
