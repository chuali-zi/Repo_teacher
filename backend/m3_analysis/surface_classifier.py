from __future__ import annotations

from backend.contracts.domain import FileNode, FileTreeSnapshot, RepoSurfaceAssignment
from backend.contracts.enums import FileNodeStatus, RepoSurface
from backend.m3_analysis._helpers import stable_id

_WORKSPACE_META_PREFIXES = (".claude/", ".agents/", ".github/")
_DOCS_PREFIXES = ("docs/", "examples/", "tutorials/")
_TOOLING_PREFIXES = ("scripts/", "tools/", "dev/")
_TEST_PREFIXES = ("tests/", "test/", "fixtures/", "__tests__/")
_BUILD_PREFIXES = ("dist/", "build/", "coverage/", ".next/", "out/")
_PRODUCT_PREFIXES = (
    "src/",
    "app/",
    "backend/",
    "frontend/",
    "server/",
    "pkg/",
    "lib/",
    "repo_tutor_tui/",
)


def classify_repo_surfaces(file_tree: FileTreeSnapshot) -> list[RepoSurfaceAssignment]:
    assignments: list[RepoSurfaceAssignment] = []
    seen: set[str] = set()
    for node in file_tree.nodes:
        if node.status == FileNodeStatus.IGNORED:
            continue
        assignment = classify_node_surface(node)
        if assignment.path in seen:
            continue
        seen.add(assignment.path)
        assignments.append(assignment)
    assignments.sort(key=lambda item: (item.depth, item.path))
    return assignments


def classify_node_surface(node: FileNode) -> RepoSurfaceAssignment:
    path = node.relative_path
    lowered = path.lower()

    if _matches_prefix(lowered, _WORKSPACE_META_PREFIXES):
        return _assignment(
            node,
            RepoSurface.WORKSPACE_META,
            "Agent/meta workspace files are not part of the default teaching mainline.",
        )
    if _matches_prefix(lowered, _DOCS_PREFIXES):
        return _assignment(
            node,
            RepoSurface.DOCS,
            "Documentation and examples are visible context, not default runtime mainline.",
        )
    if _matches_prefix(lowered, _TOOLING_PREFIXES):
        return _assignment(
            node,
            RepoSurface.TOOLING,
            "Tooling and scripts support development rather than product runtime.",
        )
    if _matches_prefix(lowered, _TEST_PREFIXES) or _looks_like_test_path(lowered):
        return _assignment(
            node,
            RepoSurface.TEST,
            "Tests and fixtures are excluded from default entry and mainline ranking.",
        )
    if _matches_prefix(lowered, _BUILD_PREFIXES):
        return _assignment(
            node,
            RepoSurface.BUILD,
            "Build output and generated assets are not teaching mainline sources.",
        )
    if _matches_prefix(lowered, _PRODUCT_PREFIXES):
        return _assignment(
            node, RepoSurface.PRODUCT, "Product code surface suitable for default teaching focus."
        )
    if node.depth == 1 and _looks_like_product_root_file(lowered):
        return _assignment(
            node,
            RepoSurface.PRODUCT,
            "Top-level runtime or package file likely belongs to product surface.",
        )
    return _assignment(
        node,
        RepoSurface.ROOT_MISC,
        "Root-level miscellaneous surface; visible but ranked conservatively.",
    )


def build_surface_map(file_tree: FileTreeSnapshot) -> dict[str, RepoSurfaceAssignment]:
    return {item.path: item for item in classify_repo_surfaces(file_tree)}


def _assignment(node: FileNode, surface: RepoSurface, reason: str) -> RepoSurfaceAssignment:
    return RepoSurfaceAssignment(
        assignment_id=stable_id("surface", node.relative_path, surface),
        path=node.relative_path,
        surface=surface,
        reason=reason,
        depth=node.depth,
    )


def _matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in prefixes)


def _looks_like_test_path(path: str) -> bool:
    basename = path.rsplit("/", 1)[-1]
    return basename.startswith("test_") or basename.endswith("_test.py")


def _looks_like_product_root_file(path: str) -> bool:
    return path in {
        "main.py",
        "app.py",
        "manage.py",
        "pyproject.toml",
        "package.json",
        "setup.py",
        "tui.py",
    }
