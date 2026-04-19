from __future__ import annotations

from pathlib import PurePosixPath

from backend.contracts.domain import FileTreeSnapshot, RelevantSourceFile
from backend.contracts.enums import FileNodeStatus, FileNodeType

KEY_CONFIG_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "manage.py",
}
KEY_DOC_EXTENSIONS = {".md", ".rst", ".txt"}
KEY_DOC_NAMES = {"README.md", "README.rst", "README.txt"}
TEST_PARTS = {"test", "tests", "__tests__", "testing", "fixtures"}
VENDOR_PARTS = {"vendor", "vendors", "third_party", "site-packages", "node_modules"}
BUILD_PARTS = {"build", "dist", ".next", ".nuxt", "coverage"}


def select_relevant_source_files(file_tree: FileTreeSnapshot) -> list[RelevantSourceFile]:
    selections: list[RelevantSourceFile] = []
    for node in sorted(file_tree.nodes, key=lambda item: item.relative_path):
        if node.node_type != FileNodeType.FILE:
            continue
        path = node.relative_path
        source_kind = _source_kind(path, node.extension)
        group_key = _group_key(path)
        selected = False
        include_reason: str | None = None
        skip_reason: str | None = None

        if node.status in {FileNodeStatus.SENSITIVE_SKIPPED, FileNodeStatus.UNREADABLE}:
            skip_reason = "sensitive_or_unreadable"
        elif _is_test_path(path):
            skip_reason = "test_or_fixture"
        elif _is_vendor_path(path):
            skip_reason = "vendor_or_dependency"
        elif _is_build_or_generated(path):
            skip_reason = "build_or_generated"
        elif node.status == FileNodeStatus.IGNORED:
            skip_reason = "ignored_by_policy"
        elif source_kind == "source":
            selected = True
            include_reason = "business_source_file"
        elif source_kind == "config":
            selected = True
            include_reason = "key_runtime_config"
        elif source_kind == "doc":
            selected = True
            include_reason = "key_repo_document"
        else:
            skip_reason = "not_relevant_for_initial_research"

        selections.append(
            RelevantSourceFile(
                relative_path=path,
                selected=selected,
                source_kind=source_kind,
                group_key=group_key,
                include_reason=include_reason,
                skip_reason=skip_reason,
                size_bytes=node.size_bytes,
                is_python_source=node.is_python_source,
            )
        )
    return selections


def _group_key(relative_path: str) -> str:
    parts = PurePosixPath(relative_path).parts
    if len(parts) <= 1:
        return "(root)"
    return parts[0]


def _source_kind(relative_path: str, extension: str | None) -> str:
    name = PurePosixPath(relative_path).name
    lowered_path = relative_path.casefold()
    if name in KEY_CONFIG_FILES:
        return "config"
    if name in KEY_DOC_NAMES or (
        extension in KEY_DOC_EXTENSIONS and lowered_path.startswith("docs/")
    ):
        return "doc"
    if extension == ".toml" and name.endswith(".toml"):
        return "config"
    if extension in {".yaml", ".yml", ".json", ".ini"} and len(PurePosixPath(relative_path).parts) == 1:
        return "config"
    return "source"


def _is_test_path(relative_path: str) -> bool:
    parts = {part.casefold() for part in PurePosixPath(relative_path).parts}
    name = PurePosixPath(relative_path).name.casefold()
    return (
        bool(parts & TEST_PARTS)
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("_spec.py")
    )


def _is_vendor_path(relative_path: str) -> bool:
    parts = {part.casefold() for part in PurePosixPath(relative_path).parts}
    return bool(parts & VENDOR_PARTS)


def _is_build_or_generated(relative_path: str) -> bool:
    parts = {part.casefold() for part in PurePosixPath(relative_path).parts}
    name = PurePosixPath(relative_path).name.casefold()
    return bool(parts & BUILD_PARTS) or "generated" in name
