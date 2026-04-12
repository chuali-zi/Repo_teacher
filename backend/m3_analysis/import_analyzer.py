from __future__ import annotations

import ast
import sys

from backend.contracts.domain import FileTreeSnapshot, ImportClassification
from backend.contracts.enums import ConfidenceLevel, ImportSourceType
from backend.m3_analysis._helpers import (
    build_internal_module_index,
    extract_declared_dependencies,
    iter_python_nodes,
    parse_python_module,
    stable_id,
)


def classify_imports(file_tree: FileTreeSnapshot) -> list[ImportClassification]:
    internal_modules = build_internal_module_index(file_tree)
    declared_dependencies, _ = extract_declared_dependencies(file_tree)
    stdlib_modules = set(getattr(sys, "stdlib_module_names", set()))
    imports_by_name: dict[str, dict[str, object]] = {}

    candidate_nodes = iter_python_nodes(file_tree)
    if file_tree.source_code_file_count > 3000:
        candidate_nodes = [
            node
            for node in candidate_nodes
            if node.relative_path.rsplit("/", 1)[-1] in {"__main__.py", "main.py", "app.py", "manage.py"}
        ]

    for node in candidate_nodes:
        module = parse_python_module(node)
        if module is None:
            continue
        for child in ast.walk(module):
            import_name: str | None = None
            if isinstance(child, ast.Import):
                for alias in child.names:
                    import_name = alias.name.split(".", 1)[0]
                    info = imports_by_name.setdefault(import_name, {"used_by_files": set(), "declared_in": set()})
                    info["used_by_files"].add(node.relative_path)
            elif isinstance(child, ast.ImportFrom) and child.module:
                import_name = child.module.split(".", 1)[0]
                info = imports_by_name.setdefault(import_name, {"used_by_files": set(), "declared_in": set()})
                info["used_by_files"].add(node.relative_path)

    results: list[ImportClassification] = []
    for import_name, info in sorted(imports_by_name.items()):
        if import_name in internal_modules:
            source_type = ImportSourceType.INTERNAL
            basis = "Matched Python module inside repository tree."
            confidence = ConfidenceLevel.HIGH
        elif import_name in stdlib_modules:
            source_type = ImportSourceType.STDLIB
            basis = "Matched Python standard library module list."
            confidence = ConfidenceLevel.HIGH
        elif import_name.lower() in declared_dependencies:
            source_type = ImportSourceType.THIRD_PARTY
            basis = "Matched dependency declaration file."
            confidence = ConfidenceLevel.MEDIUM
        else:
            source_type = ImportSourceType.UNKNOWN
            basis = "Did not match internal modules, stdlib list, or declared dependencies."
            confidence = ConfidenceLevel.LOW

        results.append(
            ImportClassification(
                import_id=stable_id("import", import_name),
                import_name=import_name,
                source_type=source_type,
                used_by_files=sorted(info["used_by_files"]),
                declared_in=sorted(info["declared_in"]),
                basis=basis,
                worth_expanding_now=source_type in {ImportSourceType.INTERNAL, ImportSourceType.THIRD_PARTY},
                confidence=confidence,
                evidence_refs=[stable_id("evidence", "import", import_name)],
            )
        )

    return results
