from __future__ import annotations

from collections import Counter

from backend.contracts.domain import FileTreeSnapshot, ModuleSummary, RepoSurfaceAssignment
from backend.contracts.enums import ConfidenceLevel, MainPathRole, ModuleKind, RepoSurface
from backend.m3_analysis._helpers import iter_readable_nodes, iter_python_nodes, stable_id

ROLE_HINTS = {
    "route": "HTTP routes or controllers.",
    "controller": "Request handling or controller logic.",
    "service": "Business logic orchestration.",
    "logic": "Core business logic.",
    "model": "Domain models or schemas.",
    "schema": "Schema or validation definitions.",
    "repo": "Repository or persistence access.",
    "db": "Database access or storage integration.",
    "config": "Configuration or application setup.",
    "util": "Shared utility helpers.",
    "test": "Tests or validation coverage.",
}


def identify_modules(
    file_tree: FileTreeSnapshot,
    *,
    surface_map: dict[str, RepoSurfaceAssignment] | None = None,
) -> list[ModuleSummary]:
    python_nodes = iter_python_nodes(file_tree)
    readable_nodes = iter_readable_nodes(file_tree)
    top_level_counts = Counter(
        node.relative_path.split("/", 1)[0] for node in readable_nodes if "/" in node.relative_path
    )
    summaries: list[ModuleSummary] = []

    for top_level, count in top_level_counts.most_common(8):
        surface = _surface_for_path(top_level, surface_map)
        responsibility = None
        lowered = top_level.lower()
        for hint, description in ROLE_HINTS.items():
            if hint in lowered:
                responsibility = description
                break
        if responsibility is None:
            responsibility = "Top-level package or directory containing core implementation files."
        summaries.append(
            ModuleSummary(
                module_id=stable_id("module", top_level),
                path=top_level,
                module_kind=ModuleKind.DIRECTORY,
                surface=surface,
                responsibility=responsibility,
                importance_rank=0,
                likely_layer=None,
                main_path_role=_main_path_role(surface, count),
                upstream_modules=[],
                downstream_modules=[],
                related_entry_ids=[],
                related_flow_ids=[],
                worth_reading_now=surface in {RepoSurface.PRODUCT, RepoSurface.ROOT_MISC, None}
                and count >= 2,
                confidence=ConfidenceLevel.MEDIUM
                if surface in {RepoSurface.PRODUCT, RepoSurface.ROOT_MISC, None}
                else ConfidenceLevel.LOW,
                evidence_refs=[stable_id("evidence", "module-dir", top_level)],
            )
        )

    for node in python_nodes:
        basename = node.relative_path.rsplit("/", 1)[-1]
        if basename in {"main.py", "app.py", "manage.py", "__main__.py"}:
            surface = _surface_for_path(node.relative_path, surface_map)
            summaries.append(
                ModuleSummary(
                    module_id=stable_id("module", node.relative_path),
                    path=node.relative_path,
                    module_kind=ModuleKind.FILE,
                    surface=surface,
                    responsibility="Likely entry-adjacent module worth reading early.",
                    importance_rank=0,
                    likely_layer=None,
                    main_path_role=MainPathRole.MAIN_PATH
                    if surface in {RepoSurface.PRODUCT, RepoSurface.ROOT_MISC, None}
                    else MainPathRole.SUPPORTING,
                    upstream_modules=[],
                    downstream_modules=[],
                    related_entry_ids=[],
                    related_flow_ids=[],
                    worth_reading_now=surface in {RepoSurface.PRODUCT, RepoSurface.ROOT_MISC, None},
                    confidence=ConfidenceLevel.HIGH
                    if surface in {RepoSurface.PRODUCT, RepoSurface.ROOT_MISC, None}
                    else ConfidenceLevel.LOW,
                    evidence_refs=[stable_id("evidence", "module-file", node.relative_path)],
                )
            )

    if not summaries:
        for top_level, count in top_level_counts.most_common(6):
            summaries.append(
                ModuleSummary(
                    module_id=stable_id("module", top_level, "degraded"),
                    path=top_level,
                    module_kind=ModuleKind.DIRECTORY,
                    surface=_surface_for_path(top_level, surface_map),
                    responsibility="Top-level directory identified from repository structure.",
                    importance_rank=0,
                    likely_layer=None,
                    main_path_role=MainPathRole.MAIN_PATH if count >= 1 else MainPathRole.UNKNOWN,
                    upstream_modules=[],
                    downstream_modules=[],
                    related_entry_ids=[],
                    related_flow_ids=[],
                    worth_reading_now=True,
                    confidence=ConfidenceLevel.LOW,
                    evidence_refs=[stable_id("evidence", "module-structure", top_level)],
                )
            )

    deduped: list[ModuleSummary] = []
    seen_paths: set[str] = set()
    for summary in summaries:
        if summary.path in seen_paths:
            continue
        seen_paths.add(summary.path)
        deduped.append(summary)

    deduped.sort(key=lambda item: (_module_priority(item), item.path))
    ranked: list[ModuleSummary] = []
    for index, summary in enumerate(deduped[:10], start=1):
        ranked.append(summary.model_copy(update={"importance_rank": index}))
    return ranked


def _surface_for_path(
    path: str,
    surface_map: dict[str, RepoSurfaceAssignment] | None,
) -> RepoSurface | None:
    if not surface_map:
        return None
    assignment = surface_map.get(path)
    if assignment is not None:
        return assignment.surface
    head = path.split("/", 1)[0]
    assignment = surface_map.get(head)
    return assignment.surface if assignment is not None else None


def _main_path_role(surface: RepoSurface | None, count: int) -> MainPathRole:
    if surface in {RepoSurface.PRODUCT, RepoSurface.ROOT_MISC, None} and count >= 2:
        return MainPathRole.MAIN_PATH
    return MainPathRole.SUPPORTING


def _module_priority(item: ModuleSummary) -> tuple[int, int]:
    surface_priority = (
        0 if item.surface in {RepoSurface.PRODUCT, RepoSurface.ROOT_MISC, None} else 1
    )
    main_path_priority = 0 if item.main_path_role == MainPathRole.MAIN_PATH else 1
    return surface_priority, main_path_priority
