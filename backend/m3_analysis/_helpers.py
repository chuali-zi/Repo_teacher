from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from backend.contracts.domain import AnalysisWarning, EvidenceRef, FileNode, FileTreeSnapshot, UnknownItem
from backend.contracts.enums import ConfidenceLevel, EvidenceType, FileNodeStatus, UnknownTopic, WarningType


def stable_id(prefix: str, *parts: object) -> str:
    raw = "::".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def iter_readable_nodes(file_tree: FileTreeSnapshot) -> list[FileNode]:
    return [
        node
        for node in file_tree.nodes
        if node.node_type == "file" and node.status == FileNodeStatus.NORMAL
    ]


def iter_python_nodes(file_tree: FileTreeSnapshot) -> list[FileNode]:
    return [node for node in iter_readable_nodes(file_tree) if node.is_python_source]


def read_node_text(node: FileNode) -> str | None:
    try:
        return Path(node.real_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return Path(node.real_path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return None
    except OSError:
        return None


def parse_python_module(node: FileNode) -> ast.AST | None:
    text = read_node_text(node)
    if text is None:
        return None
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def python_module_name(relative_path: str) -> str | None:
    if not relative_path.endswith(".py"):
        return None
    stripped = relative_path[:-3]
    parts = [part for part in stripped.split("/") if part]
    if not parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def build_internal_module_index(file_tree: FileTreeSnapshot) -> set[str]:
    modules: set[str] = set()
    for node in iter_python_nodes(file_tree):
        module_name = python_module_name(node.relative_path)
        if module_name:
            parts = module_name.split(".")
            for end in range(1, len(parts) + 1):
                modules.add(".".join(parts[:end]))
    return modules


def extract_declared_dependencies(file_tree: FileTreeSnapshot) -> tuple[set[str], list[EvidenceRef]]:
    dependencies: set[str] = set()
    evidence: list[EvidenceRef] = []
    for node in iter_readable_nodes(file_tree):
        path = node.relative_path
        text = read_node_text(node)
        if text is None:
            continue
        lowered = path.lower()
        if lowered.endswith("requirements.txt") or lowered.endswith("requirements-dev.txt"):
            for line_no, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                name = re.split(r"[<>=!~\[]", stripped, maxsplit=1)[0].strip().replace("-", "_")
                if not name:
                    continue
                dependencies.add(name.lower())
                evidence.append(
                    EvidenceRef(
                        evidence_id=stable_id("evidence", path, line_no, name),
                        type=EvidenceType.DEPENDENCY_DECLARATION,
                        source_path=path,
                        source_location=f"line {line_no}",
                        content_excerpt=stripped[:200],
                        is_sensitive_source=False,
                        note=f"Declared dependency {name}",
                    )
                )
        elif lowered.endswith("pyproject.toml") or lowered.endswith("pipfile") or lowered.endswith("setup.py"):
            matches = re.findall(r"[\"']([A-Za-z0-9_.-]+)[<>=!~]?", text)
            for raw_name in matches:
                normalized = raw_name.replace("-", "_").lower()
                if normalized in {"python", "setuptools", "wheel", "poetry", "name", "version"}:
                    continue
                if not re.match(r"^[a-zA-Z][a-zA-Z0-9_.-]*$", raw_name):
                    continue
                dependencies.add(normalized)
            if matches:
                evidence.append(
                    EvidenceRef(
                        evidence_id=stable_id("evidence", path, "deps"),
                        type=EvidenceType.DEPENDENCY_DECLARATION,
                        source_path=path,
                        source_location=None,
                        content_excerpt="dependency declarations present",
                        is_sensitive_source=False,
                        note="Dependency declaration file detected",
                    )
                )
    return dependencies, evidence


def confidence_from_count(count: int) -> ConfidenceLevel:
    if count >= 2:
        return ConfidenceLevel.HIGH
    if count == 1:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def make_unknown(topic: UnknownTopic, description: str, related_paths: list[str], reason: str) -> UnknownItem:
    return UnknownItem(
        unknown_id=stable_id("unknown", str(topic), description, *related_paths),
        topic=topic,
        description=description,
        related_paths=related_paths,
        reason=reason,
        user_visible=True,
    )


def unreadable_or_sensitive_warnings(file_tree: FileTreeSnapshot) -> tuple[list[AnalysisWarning], list[UnknownItem], list[EvidenceRef]]:
    warnings: list[AnalysisWarning] = []
    unknowns: list[UnknownItem] = []
    evidence: list[EvidenceRef] = []

    for ref in file_tree.sensitive_matches:
        warning_id = stable_id("warning", "sensitive", ref.relative_path)
        warnings.append(
            AnalysisWarning(
                warning_id=warning_id,
                type=WarningType.SENSITIVE_FILE_SKIPPED,
                message=f"Sensitive file skipped: {ref.relative_path}",
                user_notice=ref.user_notice,
                related_paths=[ref.relative_path],
            )
        )
        unknowns.append(
            make_unknown(
                UnknownTopic.SECURITY_SKIPPED,
                f"Skipped reading sensitive file {ref.relative_path}",
                [ref.relative_path],
                ref.user_notice,
            )
        )
        evidence.append(
            EvidenceRef(
                evidence_id=stable_id("evidence", "sensitive", ref.relative_path),
                type=EvidenceType.FILE_PATH,
                source_path=ref.relative_path,
                source_location=None,
                content_excerpt=None,
                is_sensitive_source=True,
                note=ref.user_notice,
            )
        )

    for node in file_tree.nodes:
        if node.node_type != "file":
            continue
        if node.status == FileNodeStatus.UNREADABLE:
            warnings.append(
                AnalysisWarning(
                    warning_id=stable_id("warning", "unreadable", node.relative_path),
                    type=WarningType.FILE_UNREADABLE,
                    message=f"Unreadable file skipped: {node.relative_path}",
                    user_notice="Some files could not be read and were skipped during analysis.",
                    related_paths=[node.relative_path],
                )
            )
    return warnings, unknowns, evidence


def dedupe_by_id(items: list[Any], attr: str) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in items:
        item_id = getattr(item, attr)
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result
