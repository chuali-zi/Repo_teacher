from backend.contracts.domain import FileNode, ScanScope
from backend.contracts.enums import FileNodeStatus, FileNodeType, RepoSizeLevel, ScanScopeType


def classify_repo_size(
    nodes: list[FileNode],
    max_source_files_full_analysis: int = 3000,
) -> tuple[RepoSizeLevel, int, ScanScope | None]:
    source_code_file_count = sum(
        1
        for node in nodes
        if node.node_type == FileNodeType.FILE
        and node.is_source_file
        and node.status not in {FileNodeStatus.IGNORED, FileNodeStatus.SENSITIVE_SKIPPED}
    )

    if source_code_file_count < 500:
        return RepoSizeLevel.SMALL, source_code_file_count, None
    if source_code_file_count <= max_source_files_full_analysis:
        return RepoSizeLevel.MEDIUM, source_code_file_count, None

    included_paths = sorted(
        node.relative_path
        for node in nodes
        if node.status == FileNodeStatus.NORMAL and node.depth == 1
    )
    degraded_scope = ScanScope(
        scope_type=ScanScopeType.TOP_LEVEL_ONLY,
        included_paths=included_paths,
        excluded_reason=f"源码文件数为 {source_code_file_count}，超过全量分析上限 {max_source_files_full_analysis}",
        user_notice="仓库较大，优先输出结构总览和阅读起点",
    )
    return RepoSizeLevel.LARGE, source_code_file_count, degraded_scope
