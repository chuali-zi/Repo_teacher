from __future__ import annotations

import ast
import re

from backend.contracts.domain import EntryCandidate, FileTreeSnapshot
from backend.contracts.enums import ConfidenceLevel, EntryTargetType, UnknownTopic
from backend.m3_analysis._helpers import (
    iter_python_nodes,
    make_unknown,
    parse_python_module,
    read_node_text,
    stable_id,
)


def detect_entry_candidates(file_tree: FileTreeSnapshot) -> list[EntryCandidate]:
    candidates: list[EntryCandidate] = []

    for node in iter_python_nodes(file_tree):
        path = node.relative_path
        basename = path.rsplit("/", 1)[-1]
        if basename in {"__main__.py", "main.py", "app.py", "manage.py"}:
            candidates.append(
                EntryCandidate(
                    entry_id=stable_id("entry", path, "name"),
                    target_type=EntryTargetType.FILE,
                    target_value=path,
                    reason=f"Conventional Python entry file `{basename}`.",
                    confidence=ConfidenceLevel.HIGH if basename in {"__main__.py", "manage.py"} else ConfidenceLevel.MEDIUM,
                    rank=0,
                    evidence_refs=[stable_id("evidence", "entry-file", path)],
                    unknown_items=[],
                )
            )

        module = parse_python_module(node)
        if module is None:
            continue
        has_main_guard = False
        framework_name: str | None = None
        for child in ast.walk(module):
            if isinstance(child, ast.If):
                test = child.test
                if (
                    isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"
                    and len(test.ops) == 1
                    and len(test.comparators) == 1
                    and isinstance(test.ops[0], ast.Eq)
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == "__main__"
                ):
                    has_main_guard = True
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in {"FastAPI", "Flask"}:
                framework_name = child.func.id
        if has_main_guard:
            candidates.append(
                EntryCandidate(
                    entry_id=stable_id("entry", path, "guard"),
                    target_type=EntryTargetType.FILE,
                    target_value=path,
                    reason="Contains `if __name__ == \"__main__\"` runnable block.",
                    confidence=ConfidenceLevel.HIGH,
                    rank=0,
                    evidence_refs=[stable_id("evidence", "main-guard", path)],
                    unknown_items=[],
                )
            )
        if framework_name:
            candidates.append(
                EntryCandidate(
                    entry_id=stable_id("entry", path, framework_name),
                    target_type=EntryTargetType.FRAMEWORK_OBJECT,
                    target_value=path,
                    reason=f"Defines a `{framework_name}` application object.",
                    confidence=ConfidenceLevel.MEDIUM,
                    rank=0,
                    evidence_refs=[stable_id("evidence", "framework", path, framework_name)],
                    unknown_items=[],
                )
            )

    for node in file_tree.nodes:
        if node.node_type != "file":
            continue
        path = node.relative_path.lower()
        text = read_node_text(node) or ""
        if path.endswith("pyproject.toml"):
            for match in re.finditer(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.MULTILINE):
                script_name = match.group(1)
                target = match.group(2)
                if ":" not in target:
                    continue
                candidates.append(
                    EntryCandidate(
                        entry_id=stable_id("entry", node.relative_path, script_name),
                        target_type=EntryTargetType.COMMAND,
                        target_value=script_name,
                        reason=f"Declared script `{script_name}` in pyproject.toml.",
                        confidence=ConfidenceLevel.MEDIUM,
                        rank=0,
                        evidence_refs=[stable_id("evidence", "script", node.relative_path, script_name)],
                        unknown_items=[],
                    )
                )
        if path.endswith("readme.md"):
            for line in text.splitlines():
                normalized = line.strip()
                if normalized.startswith("python ") or normalized.startswith("uv run "):
                    candidates.append(
                        EntryCandidate(
                            entry_id=stable_id("entry", node.relative_path, normalized),
                            target_type=EntryTargetType.COMMAND,
                            target_value=normalized,
                            reason="README documents a run command.",
                            confidence=ConfidenceLevel.LOW,
                            rank=0,
                            evidence_refs=[stable_id("evidence", "readme-command", node.relative_path, normalized)],
                            unknown_items=[],
                        )
                    )

    deduped: list[EntryCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (str(candidate.target_type), candidate.target_value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    deduped.sort(key=lambda item: (item.confidence != ConfidenceLevel.HIGH, item.confidence != ConfidenceLevel.MEDIUM, item.target_value))
    ranked: list[EntryCandidate] = []
    for index, candidate in enumerate(deduped[:6], start=1):
        ranked.append(candidate.model_copy(update={"rank": index}))

    if ranked:
        return ranked

    return [
        EntryCandidate(
            entry_id=stable_id("entry", file_tree.repo_id, "unknown"),
            target_type=EntryTargetType.UNKNOWN,
            target_value="unknown",
            reason="No reliable Python entry candidate was found from filenames, runnable blocks, config, or README instructions.",
            confidence=ConfidenceLevel.UNKNOWN,
            rank=1,
            evidence_refs=[],
            unknown_items=[
                make_unknown(
                    UnknownTopic.ENTRY,
                    "No reliable entry candidate found.",
                    [],
                    "Repository did not expose a clear Python entry file or command.",
                )
            ],
        )
    ]
