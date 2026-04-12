from __future__ import annotations

from collections import defaultdict

from backend.contracts.domain import FileNode, LanguageStat
from backend.contracts.enums import FileNodeStatus, FileNodeType

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".scala": "Scala",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".vue": "Vue",
    ".svelte": "Svelte",
}


def detect_languages(nodes: list[FileNode]) -> tuple[str, list[LanguageStat]]:
    file_counts: dict[str, int] = defaultdict(int)
    source_counts: dict[str, int] = defaultdict(int)
    considered_files = 0

    for node in nodes:
        if node.node_type != FileNodeType.FILE:
            continue
        if node.status in {FileNodeStatus.IGNORED, FileNodeStatus.SENSITIVE_SKIPPED}:
            continue
        language = EXTENSION_LANGUAGE_MAP.get((node.extension or "").lower(), "unknown")
        file_counts[language] += 1
        if node.is_source_file:
            source_counts[language] += 1
        considered_files += 1

    if considered_files == 0:
        return "unknown", []

    stats = [
        LanguageStat(
            language=language,
            file_count=file_counts[language],
            source_file_count=source_counts[language],
            ratio=file_counts[language] / considered_files,
        )
        for language in file_counts
    ]
    stats.sort(key=lambda item: (-item.source_file_count, -item.file_count, item.language.lower()))
    primary_language = stats[0].language if stats and stats[0].source_file_count > 0 else "unknown"
    return primary_language, stats
