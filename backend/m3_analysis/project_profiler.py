from __future__ import annotations

from backend.contracts.domain import FileTreeSnapshot, ProjectProfileResult, ProjectTypeCandidate
from backend.contracts.enums import ConfidenceLevel, ProjectType
from backend.m3_analysis._helpers import (
    confidence_from_count,
    iter_readable_nodes,
    read_node_text,
    stable_id,
)


def profile_project(file_tree: FileTreeSnapshot) -> ProjectProfileResult:
    scores: dict[ProjectType, list[str]] = {
        ProjectType.CLI: [],
        ProjectType.WEB_APP: [],
        ProjectType.LIBRARY: [],
        ProjectType.PACKAGE: [],
        ProjectType.SCRIPT_COLLECTION: [],
    }

    for node in iter_readable_nodes(file_tree):
        path = node.relative_path.lower()
        text = (read_node_text(node) or "")[:4000].lower()
        if path.endswith("manage.py") or "fastapi" in text or "flask" in text or "django" in text:
            scores[ProjectType.WEB_APP].append(node.relative_path)
        if "argparse" in text or "click" in text or path.endswith("__main__.py"):
            scores[ProjectType.CLI].append(node.relative_path)
        if path.endswith("pyproject.toml") or path.endswith("setup.py"):
            scores[ProjectType.PACKAGE].append(node.relative_path)
            if "[project]" in text or "packages" in text or "tool.poetry" in text:
                scores[ProjectType.LIBRARY].append(node.relative_path)
        if path.endswith("readme.md") and any(term in text for term in ["library", "package", "api", "web", "cli"]):
            if "cli" in text:
                scores[ProjectType.CLI].append(node.relative_path)
            if "web" in text or "api" in text:
                scores[ProjectType.WEB_APP].append(node.relative_path)
            if "library" in text or "package" in text:
                scores[ProjectType.LIBRARY].append(node.relative_path)

    python_files = [node for node in file_tree.nodes if node.is_python_source]
    if python_files and len(python_files) >= 3 and len(scores[ProjectType.WEB_APP]) == 0 and len(scores[ProjectType.CLI]) == 0:
        scores[ProjectType.SCRIPT_COLLECTION].append("python-source-cluster")

    ranked = sorted(scores.items(), key=lambda item: (-len(item[1]), item[0].value))
    candidates: list[ProjectTypeCandidate] = []
    for project_type, reasons in ranked:
        if not reasons:
            continue
        candidates.append(
            ProjectTypeCandidate(
                type=project_type,
                reason=f"Matched {len(reasons)} repository signals: {', '.join(reasons[:3])}",
                confidence=confidence_from_count(len(reasons)),
                evidence_refs=[stable_id("evidence", "profile", project_type.value, ref) for ref in reasons[:3]],
            )
        )

    if not candidates:
        candidates = [
            ProjectTypeCandidate(
                type=ProjectType.UNKNOWN,
                reason="Repository structure does not provide enough reliable project-type signals.",
                confidence=ConfidenceLevel.UNKNOWN,
                evidence_refs=[],
            )
        ]

    return ProjectProfileResult(
        project_types=candidates[:3],
        primary_language=file_tree.primary_language,
        summary_text=f"Primary language is {file_tree.primary_language} with {file_tree.source_code_file_count} source files.",
        confidence=candidates[0].confidence,
        evidence_refs=candidates[0].evidence_refs,
    )
