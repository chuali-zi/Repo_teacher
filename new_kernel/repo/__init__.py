# repo 包：GitHub URL 解析 → git clone → 文件树扫描 → repo overview → 首个教学片段，由 RepoParsePipeline 编排并向上层 sink 推送 ParseLogLine / RepoConnectedData。
from .errors import RepoModuleError
from .git_cloner import CloneResult, GitCloner
from .github_resolver import GithubResolver, RemoteHead, parse_github_input, parse_remote_head
from .overview_builder import OverviewBuilder, OverviewEntryCandidate, RepoOverview
from .parse_pipeline import RepoParsePipeline, RepoParseResult, parse_repository
from .teaching_slice_picker import TeachingSlicePicker
from .tree_scanner import ScannedDirectory, ScannedFile, SkippedPath, TreeScanResult, TreeScanner

__all__ = [
    "CloneResult",
    "GitCloner",
    "GithubResolver",
    "OverviewBuilder",
    "OverviewEntryCandidate",
    "RemoteHead",
    "RepoModuleError",
    "RepoOverview",
    "RepoParsePipeline",
    "RepoParseResult",
    "ScannedDirectory",
    "ScannedFile",
    "SkippedPath",
    "TeachingSlicePicker",
    "TreeScanResult",
    "TreeScanner",
    "parse_github_input",
    "parse_remote_head",
    "parse_repository",
]
