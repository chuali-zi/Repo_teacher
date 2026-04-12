from __future__ import annotations

from collections import Counter

from backend.contracts.domain import FileTreeSnapshot, ModuleSummary
from backend.contracts.enums import ConfidenceLevel, MainPathRole, ModuleKind
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


def identify_modules(file_tree: FileTreeSnapshot) -> list[ModuleSummary]:
    python_nodes = iter_python_nodes(file_tree)
    readable_nodes = iter_readable_nodes(file_tree)
    top_level_counts = Counter(node.relative_path.split("/", 1)[0] for node in readable_nodes if "/" in node.relative_path)
    summaries: list[ModuleSummary] = []

    for top_level, count in top_level_counts.most_common(8):
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
                responsibility=responsibility,
                importance_rank=0,
                likely_layer=None,
                main_path_role=MainPathRole.MAIN_PATH if count >= 2 else MainPathRole.SUPPORTING,
                upstream_modules=[],
                downstream_modules=[],
                related_entry_ids=[],
                related_flow_ids=[],
                worth_reading_now=count >= 2,
                confidence=ConfidenceLevel.MEDIUM,
                evidence_refs=[stable_id("evidence", "module-dir", top_level)],
            )
        )

    for node in python_nodes:
        basename = node.relative_path.rsplit("/", 1)[-1]
        if basename in {"main.py", "app.py", "manage.py", "__main__.py"}:
            summaries.append(
                ModuleSummary(
                    module_id=stable_id("module", node.relative_path),
                    path=node.relative_path,
                    module_kind=ModuleKind.FILE,
                    responsibility="Likely entry-adjacent module worth reading early.",
                    importance_rank=0,
                    likely_layer=None,
                    main_path_role=MainPathRole.MAIN_PATH,
                    upstream_modules=[],
                    downstream_modules=[],
                    related_entry_ids=[],
                    related_flow_ids=[],
                    worth_reading_now=True,
                    confidence=ConfidenceLevel.HIGH,
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

    deduped.sort(key=lambda item: (item.main_path_role != MainPathRole.MAIN_PATH, item.path))
    ranked: list[ModuleSummary] = []
    for index, summary in enumerate(deduped[:10], start=1):
        ranked.append(summary.model_copy(update={"importance_rank": index}))
    return ranked
