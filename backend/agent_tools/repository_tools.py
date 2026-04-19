from __future__ import annotations

import json
import re
import shutil
import subprocess
from itertools import islice
from pathlib import Path
from time import monotonic
from typing import Any

from backend.agent_tools.base import ToolSpec
from backend.contracts.domain import FileNode, FileTreeSnapshot, LlmToolResult, RepositoryContext
from backend.contracts.enums import FileNodeStatus, FileNodeType
from backend.m3_analysis._helpers import stable_id
from backend.security.safety import resolve_repo_relative_path

_SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,})"
)
_MAX_EXCERPT_BYTES = 240_000
_SEARCH_TIMEOUT_SECONDS = 3.0
_RG_BATCH_SIZE = 80


def build_repository_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            tool_name="read_file_excerpt",
            source_module="agent_tools.repository_tools",
            description="Safely read a bounded excerpt from a readable repository file.",
            parameters={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "start_line": {"type": "integer", "default": 1},
                    "max_lines": {"type": "integer", "default": 40},
                },
                "required": ["relative_path"],
            },
            output_contract="Redacted file excerpt with line range and availability flags.",
            safety_notes=(
                "rejects sensitive or unreadable files",
                "clips line count and redacts secret-like tokens",
            ),
            aliases=("repo.read_file_excerpt",),
            preferred_seed=True,
            seed_priority=80,
            handler=lambda arguments, ctx: read_file_excerpt(
                ctx.repository,
                ctx.file_tree,
                relative_path=str(arguments.get("relative_path") or ""),
                start_line=int(arguments.get("start_line", 1) or 1),
                max_lines=int(arguments.get("max_lines", 80) or 80),
            ),
        ),
        ToolSpec(
            tool_name="search_text",
            source_module="agent_tools.repository_tools",
            description="Search readable repository files for a keyword or symbol name.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_matches": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
            output_contract="List of redacted path, line number, and excerpt matches.",
            safety_notes=(
                "uses ripgrep when available",
                "filters out sensitive or unreadable files before returning matches",
            ),
            aliases=("repo.search_text",),
            seed_priority=90,
            handler=lambda arguments, ctx: search_text(
                ctx.repository,
                ctx.file_tree,
                query=str(arguments.get("query") or ""),
                max_matches=int(arguments.get("max_matches", 20) or 20),
            ),
        ),
    ]


def read_file_excerpt(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    *,
    relative_path: str,
    start_line: int = 1,
    max_lines: int = 40,
) -> LlmToolResult:
    normalized = _normalize_relative_path(relative_path)
    node = _find_readable_file_node(file_tree, normalized)
    if node is None:
        return _tool_result(
            "read_file_excerpt",
            "agent_tools.repository_tools",
            f"{normalized} is not readable via the LLM tool layer.",
            {
                "relative_path": normalized,
                "available": False,
                "reason": "file_not_found_or_not_readable",
            },
        )
    if node.size_bytes and node.size_bytes > _MAX_EXCERPT_BYTES:
        return _tool_result(
            "read_file_excerpt",
            "agent_tools.repository_tools",
            f"{normalized} is too large to read directly.",
            {
                "relative_path": normalized,
                "available": False,
                "reason": "file_too_large",
                "size_bytes": node.size_bytes,
            },
        )

    repo_root = Path(repository.root_path).expanduser().resolve(strict=True)
    file_path = resolve_repo_relative_path(repo_root, normalized)
    lines = _safe_read_lines(file_path)
    if lines is None:
        return _tool_result(
            "read_file_excerpt",
            "agent_tools.repository_tools",
            f"{normalized} could not be decoded safely.",
            {
                "relative_path": normalized,
                "available": False,
                "reason": "decode_or_read_failed",
            },
        )

    safe_start = max(start_line, 1)
    safe_max = min(max(max_lines, 1), 160)
    selected = lines[safe_start - 1 : safe_start - 1 + safe_max]
    return _tool_result(
        "read_file_excerpt",
        "agent_tools.repository_tools",
        f"Read {len(selected)} lines from {normalized} starting at line {safe_start}.",
        {
            "relative_path": normalized,
            "available": True,
            "start_line": safe_start,
            "line_count": len(selected),
            "total_lines": len(lines),
            "excerpt": _redact("".join(selected)),
        },
    )


def search_text(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    *,
    query: str,
    max_matches: int = 20,
) -> LlmToolResult:
    stripped_query = query.strip()
    if not stripped_query:
        return _tool_result(
            "search_text",
            "agent_tools.repository_tools",
            "The search query is empty; no search was performed.",
            {"query": query, "matches": []},
        )

    repo_root = Path(repository.root_path).expanduser().resolve(strict=True)
    limit = min(max(max_matches, 1), 50)
    readable_nodes = {
        node.relative_path: node
        for node in _readable_text_nodes(file_tree)
        if not node.size_bytes or node.size_bytes <= _MAX_EXCERPT_BYTES
    }
    matches, timed_out = _search_with_ripgrep(
        repo_root=repo_root,
        query=stripped_query,
        readable_nodes=readable_nodes,
        limit=limit,
    )
    if matches is None and not timed_out:
        matches, timed_out = _search_with_python(
            repo_root=repo_root,
            query=stripped_query,
            readable_nodes=readable_nodes,
            limit=limit,
        )

    payload: dict[str, Any] = {"query": stripped_query, "matches": matches or []}
    if timed_out:
        payload.update(
            {
                "degraded": True,
                "reason": "search_timeout",
                "timeout_seconds": _SEARCH_TIMEOUT_SECONDS,
            }
        )
    return _tool_result(
        "search_text",
        "agent_tools.repository_tools",
        f"Found {len(matches or [])} matches for {stripped_query!r}.",
        payload,
    )


def _search_with_ripgrep(
    *,
    repo_root: Path,
    query: str,
    readable_nodes: dict[str, FileNode],
    limit: int,
) -> tuple[list[dict[str, Any]] | None, bool]:
    rg_path = shutil.which("rg")
    if not rg_path:
        return None, False

    matches: list[dict[str, Any]] = []
    deadline = monotonic() + _SEARCH_TIMEOUT_SECONDS
    for batch in _batched(readable_nodes.keys(), _RG_BATCH_SIZE):
        remaining = deadline - monotonic()
        if remaining <= 0:
            return matches, True
        try:
            completed = subprocess.run(
                [rg_path, "--json", "-n", "--no-messages", "-F", "-i", query, *batch],
                cwd=repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            return matches, True
        except OSError:
            return None, False

        if completed.returncode not in {0, 1}:
            return None, False

        for line in completed.stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "match":
                continue
            data = payload.get("data") or {}
            relative_path = _normalize_relative_path(str(data.get("path", {}).get("text") or ""))
            node = readable_nodes.get(relative_path)
            if node is None:
                continue
            matches.append(
                {
                    "relative_path": relative_path,
                    "line_no": int(data.get("line_number") or 1),
                    "line": _redact(str(data.get("lines", {}).get("text") or "").strip())[:260],
                }
            )
            if len(matches) >= limit:
                return matches, False
    return matches, False


def _search_with_python(
    *,
    repo_root: Path,
    query: str,
    readable_nodes: dict[str, FileNode],
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    lowered_query = query.casefold()
    matches: list[dict[str, Any]] = []
    deadline = monotonic() + _SEARCH_TIMEOUT_SECONDS
    for relative_path, node in readable_nodes.items():
        if monotonic() >= deadline:
            return matches, True
        if len(matches) >= limit:
            break
        file_path = resolve_repo_relative_path(repo_root, relative_path)
        lines = _safe_read_lines(file_path)
        if lines is None:
            continue
        for line_no, line in enumerate(lines, start=1):
            if lowered_query not in line.casefold():
                continue
            matches.append(
                {
                    "relative_path": relative_path,
                    "line_no": line_no,
                    "line": _redact(line.strip())[:260],
                }
            )
            if len(matches) >= limit:
                break
    return matches, False


def _batched(items, size: int):
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _tool_result(
    tool_name: str,
    source_module: str,
    summary: str,
    payload: dict[str, Any],
) -> LlmToolResult:
    return LlmToolResult(
        result_id=stable_id("tool_result", tool_name, summary),
        tool_name=tool_name,
        source_module=source_module,
        summary=summary,
        payload=payload,
        reference_only=True,
    )


def _normalize_relative_path(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def _find_readable_file_node(file_tree: FileTreeSnapshot, relative_path: str) -> FileNode | None:
    normalized = _normalize_relative_path(relative_path)
    for node in file_tree.nodes:
        if node.relative_path != normalized or node.node_type != FileNodeType.FILE:
            continue
        if node.status != FileNodeStatus.NORMAL:
            return None
        return node
    return None


def _readable_text_nodes(file_tree: FileTreeSnapshot) -> list[FileNode]:
    return [
        node
        for node in file_tree.nodes
        if node.node_type == FileNodeType.FILE
        and node.status == FileNodeStatus.NORMAL
        and (node.is_source_file or _is_repo_doc(node.relative_path))
    ]


def _safe_read_lines(file_path: Path) -> list[str] | None:
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(_MAX_EXCERPT_BYTES + 1)
    except OSError:
        return None
    if "\0" in text:
        return None
    return text.splitlines(keepends=True)


def _is_repo_doc(relative_path: str) -> bool:
    lowered = relative_path.lower()
    return lowered.startswith("readme") or lowered in {
        "pyproject.toml",
        "package.json",
        "requirements.txt",
        "setup.py",
    }


def _redact(value: str) -> str:
    return _SECRET_RE.sub("[redacted_secret]", value)
