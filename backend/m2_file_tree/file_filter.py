from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from backend.contracts.domain import FileNode, IgnoreRule, SensitiveFileRef
from backend.contracts.enums import FileNodeStatus, FileNodeType, IgnoreRuleSource
from backend.security.safety import (
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_SENSITIVE_PATTERNS,
    match_repo_pattern,
)


@dataclass(frozen=True)
class ParsedRule:
    rule_id: str
    pattern: str
    source: IgnoreRuleSource
    action: FileNodeStatus
    base_dir: str = ""
    negated: bool = False


@dataclass(frozen=True)
class IgnoreMatch:
    matched_rule_ids: list[str]
    rules: list[ParsedRule]


def apply_file_filters(
    nodes: list[FileNode],
    *,
    ignore_patterns: list[str] | None = None,
    sensitive_patterns: list[str] | None = None,
) -> tuple[list[FileNode], list[IgnoreRule], list[SensitiveFileRef]]:
    repo_root = _infer_repo_root(nodes)
    rules = _build_rules(
        nodes,
        repo_root,
        ignore_patterns=ignore_patterns,
        sensitive_patterns=sensitive_patterns,
    )
    active_rules: dict[str, IgnoreRule] = {}
    sensitive_matches: list[SensitiveFileRef] = []
    filtered_nodes: list[FileNode] = []

    for node in sorted(nodes, key=lambda item: (item.depth, item.relative_path)):
        matched_rule_ids: list[str] = []
        status = node.status

        sensitive_rule = _match_authoritative_rule(
            node,
            rules,
            action=FileNodeStatus.SENSITIVE_SKIPPED,
        )
        if sensitive_rule is not None:
            matched_rule_ids.append(sensitive_rule.rule_id)
            active_rules[sensitive_rule.rule_id] = _to_ignore_rule(sensitive_rule)
            status = FileNodeStatus.SENSITIVE_SKIPPED
            if node.node_type == FileNodeType.FILE:
                sensitive_matches.append(
                    SensitiveFileRef(
                        relative_path=node.relative_path,
                        matched_pattern=sensitive_rule.pattern,
                        content_read=False,
                        user_notice="检测到敏感文件，系统只记录其存在，不会读取正文内容",
                    )
                )
        else:
            ignore_match = _match_ignore_rule(node, rules)
            if ignore_match is not None:
                matched_rule_ids.extend(ignore_match.matched_rule_ids)
                for rule in ignore_match.rules:
                    active_rules[rule.rule_id] = _to_ignore_rule(rule)
                status = FileNodeStatus.IGNORED

        filtered_nodes.append(
            node.model_copy(update={"status": status, "matched_rule_ids": matched_rule_ids})
        )

    ignored_rules = sorted(active_rules.values(), key=lambda item: item.rule_id)
    sensitive_matches.sort(key=lambda item: item.relative_path)
    filtered_nodes.sort(key=lambda item: (item.depth, item.relative_path))
    return filtered_nodes, ignored_rules, sensitive_matches


def _infer_repo_root(nodes: list[FileNode]) -> Path | None:
    depth_one_nodes = [Path(node.real_path).parent for node in nodes if node.depth == 1]
    if depth_one_nodes:
        return depth_one_nodes[0]
    if nodes:
        node_path = Path(nodes[0].real_path)
        return node_path.parent if nodes[0].node_type == FileNodeType.FILE else node_path
    return None


def _build_rules(
    nodes: list[FileNode],
    repo_root: Path | None,
    *,
    ignore_patterns: list[str] | None,
    sensitive_patterns: list[str] | None,
) -> list[ParsedRule]:
    active_ignore_patterns = tuple(ignore_patterns or DEFAULT_IGNORE_PATTERNS)
    active_sensitive_patterns = tuple(sensitive_patterns or DEFAULT_SENSITIVE_PATTERNS)
    rules: list[ParsedRule] = []
    rules.extend(
        ParsedRule(
            rule_id=f"built_in:{index}",
            pattern=pattern,
            source=IgnoreRuleSource.BUILT_IN,
            action=FileNodeStatus.IGNORED,
        )
        for index, pattern in enumerate(active_ignore_patterns, start=1)
    )
    rules.extend(
        ParsedRule(
            rule_id=f"security:{index}",
            pattern=pattern,
            source=IgnoreRuleSource.SECURITY_POLICY,
            action=FileNodeStatus.SENSITIVE_SKIPPED,
        )
        for index, pattern in enumerate(active_sensitive_patterns, start=1)
    )
    if repo_root is None:
        return rules

    gitignore_rules: list[ParsedRule] = []
    gitignore_nodes = [node for node in nodes if PurePosixPath(node.relative_path).name == ".gitignore"]
    for node in sorted(gitignore_nodes, key=lambda item: (item.depth, item.relative_path)):
        gitignore_rules.extend(_parse_gitignore(repo_root, node.relative_path))
    return [*rules, *gitignore_rules]


def _parse_gitignore(repo_root: Path, relative_path: str) -> list[ParsedRule]:
    gitignore_path = repo_root / PurePosixPath(relative_path)
    base_dir = PurePosixPath(relative_path).parent.as_posix()
    if base_dir == ".":
        base_dir = ""

    parsed_rules: list[ParsedRule] = []
    try:
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return parsed_rules

    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        negated = stripped.startswith("!") and len(stripped) > 1
        pattern = stripped[1:] if negated else stripped
        if pattern.startswith("\\") and len(pattern) > 1:
            pattern = pattern[1:]
        parsed_rules.append(
            ParsedRule(
                rule_id=f"gitignore:{relative_path}:{line_number}",
                pattern=pattern,
                source=IgnoreRuleSource.GITIGNORE,
                action=FileNodeStatus.IGNORED,
                base_dir=base_dir,
                negated=negated,
            )
        )
    return parsed_rules


def _match_authoritative_rule(
    node: FileNode,
    rules: list[ParsedRule],
    *,
    action: FileNodeStatus,
) -> ParsedRule | None:
    for rule in rules:
        if rule.action != action or rule.source == IgnoreRuleSource.GITIGNORE:
            continue
        if _matches_rule(node, rule):
            return rule
    return None


def _match_ignore_rule(node: FileNode, rules: list[ParsedRule]) -> IgnoreMatch | None:
    fixed_rules = [
        rule
        for rule in rules
        if rule.source != IgnoreRuleSource.GITIGNORE and rule.action == FileNodeStatus.IGNORED
    ]
    for rule in fixed_rules:
        if _matches_rule(node, rule):
            return IgnoreMatch(matched_rule_ids=[rule.rule_id], rules=[rule])

    selected_rules: list[ParsedRule] = []
    ignored = False
    for rule in rules:
        if rule.source != IgnoreRuleSource.GITIGNORE:
            continue
        if not _matches_rule(node, rule):
            continue
        if rule.source == IgnoreRuleSource.GITIGNORE and rule.negated:
            ignored = False
            selected_rules = []
            continue
        ignored = True
        selected_rules = [rule]

    if not ignored:
        return None
    return IgnoreMatch(matched_rule_ids=[rule.rule_id for rule in selected_rules], rules=selected_rules)


def _matches_rule(node: FileNode, rule: ParsedRule) -> bool:
    target = node.relative_path
    if not target:
        return False

    if rule.base_dir:
        prefix = f"{rule.base_dir}/"
        if target != rule.base_dir and not target.startswith(prefix):
            return False
        target = target[len(prefix) :] if target.startswith(prefix) else ""

    return _match_pattern(target, node.node_type == FileNodeType.DIRECTORY, rule.pattern)


def _match_pattern(relative_path: str, is_directory: bool, pattern: str) -> bool:
    return match_repo_pattern(relative_path, is_directory=is_directory, pattern=pattern)


def _to_ignore_rule(rule: ParsedRule) -> IgnoreRule:
    return IgnoreRule(
        rule_id=rule.rule_id,
        pattern=rule.pattern,
        source=rule.source,
        action=rule.action,
    )
