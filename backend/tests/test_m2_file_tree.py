from __future__ import annotations

from pathlib import Path

from backend.contracts.domain import RepositoryContext
from backend.contracts.enums import FileNodeStatus, RepoSizeLevel, RepoSourceType
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.security.safety import build_default_read_policy


def make_repository(root_path: Path, *, max_source_files_full_analysis: int = 3000) -> RepositoryContext:
    read_policy = build_default_read_policy()
    read_policy.max_source_files_full_analysis = max_source_files_full_analysis
    return RepositoryContext(
        repo_id="repo_test",
        source_type=RepoSourceType.LOCAL_PATH,
        display_name=root_path.name,
        input_value=str(root_path),
        root_path=str(root_path),
        is_temp_dir=False,
        access_verified=True,
        read_policy=read_policy,
    )


def test_scan_repository_tree_applies_sensitive_and_ignore_rules(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("export const a = 1\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("print('skip')\n", encoding="utf-8")

    snapshot = scan_repository_tree(make_repository(tmp_path))

    status_by_path = {node.relative_path: node.status for node in snapshot.nodes}
    assert status_by_path["app/main.py"] == FileNodeStatus.NORMAL
    assert status_by_path[".env"] == FileNodeStatus.SENSITIVE_SKIPPED
    assert status_by_path["node_modules"] == FileNodeStatus.IGNORED
    assert status_by_path["ignored.py"] == FileNodeStatus.IGNORED
    assert snapshot.sensitive_matches[0].relative_path == ".env"
    assert snapshot.sensitive_matches[0].content_read is False


def test_scan_repository_tree_detects_primary_language(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "src" / "worker.py").write_text("print('worker')\n", encoding="utf-8")
    (tmp_path / "web.js").write_text("console.log('hi')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")

    snapshot = scan_repository_tree(make_repository(tmp_path))

    assert snapshot.primary_language == "Python"
    assert snapshot.source_code_file_count == 3
    assert snapshot.repo_size_level == RepoSizeLevel.SMALL


def test_scan_repository_tree_marks_large_repo_scope(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    for index in range(3001):
        (tmp_path / "src" / f"file_{index}.py").write_text("print('x')\n", encoding="utf-8")

    snapshot = scan_repository_tree(make_repository(tmp_path))

    assert snapshot.repo_size_level == RepoSizeLevel.LARGE
    assert snapshot.degraded_scan_scope is not None
    assert snapshot.degraded_scan_scope.scope_type == "top_level_only"
    assert snapshot.degraded_scan_scope.user_notice == "仓库较大，优先输出结构总览和阅读起点"
