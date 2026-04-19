from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.agent_runtime import context_budget
from backend.agent_tools import ToolResultCache
from backend.contracts.domain import ConversationState, MessageRecord, RepositoryContext
from backend.contracts.enums import MessageRole, MessageType, PromptScenario
from backend.llm_tools import build_llm_tool_context, read_file_excerpt, search_text
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m5_session.common import utc_now
from backend.m6_response.tool_executor import execute_tool_call
from backend.security.safety import build_default_read_policy


def _fixture_repo(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def _repository(root: Path, repo_id: str = "repo_tool_test") -> RepositoryContext:
    return RepositoryContext(
        repo_id=repo_id,
        source_type="local_path",
        display_name=root.name,
        input_value=str(root),
        root_path=str(root),
        is_temp_dir=False,
        access_verified=True,
        read_policy=build_default_read_policy(),
    )


def test_initial_report_tool_context_stays_small_and_source_driven() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)

    context = build_llm_tool_context(
        repository=repo,
        file_tree=file_tree,
        conversation=ConversationState(current_repo_id=repo.repo_id),
        scenario=PromptScenario.INITIAL_REPORT,
    )

    result_names = {result.tool_name for result in context.tool_results}
    tool_names = {tool.tool_name for tool in context.tools}
    repo_result = next(
        result for result in context.tool_results if result.tool_name == "m1.get_repository_context"
    )

    assert result_names == {
        "m1.get_repository_context",
        "m2.get_file_tree_summary",
        "m2.list_relevant_files",
        "teaching.get_state_snapshot",
    }
    assert tool_names == {"m2.list_relevant_files", "search_text", "read_file_excerpt"}
    assert "root_path" not in repo_result.payload
    assert "read-only" in context.policy


def test_followup_source_question_gets_small_starter_excerpt() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    conversation = ConversationState(
        current_repo_id=repo.repo_id,
        messages=[
            MessageRecord(
                message_id="msg_user",
                role=MessageRole.USER,
                message_type=MessageType.USER_QUESTION,
                created_at=utc_now(),
                raw_text="Explain app.py and main.py.",
                streaming_complete=True,
            )
        ],
    )

    context = build_llm_tool_context(
        repository=repo,
        file_tree=file_tree,
        conversation=conversation,
        scenario=PromptScenario.FOLLOW_UP,
    )

    excerpts = [result for result in context.tool_results if result.tool_name == "read_file_excerpt"]
    assert len(excerpts) == 1
    files = excerpts[0].payload["files"]
    assert [item["relative_path"] for item in files] == ["app.py"]
    assert all(item["line_count"] <= 60 for item in files)


def test_deterministic_seed_results_use_cache() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    conversation = ConversationState(current_repo_id=repo.repo_id)
    call_count = 0
    context_budget.GLOBAL_TOOL_RESULT_CACHE.clear()
    original_execute = context_budget.DEFAULT_TOOL_REGISTRY.execute

    def counting_execute(tool_name, arguments, ctx):
        nonlocal call_count
        if tool_name == "m1.get_repository_context":
            call_count += 1
        return original_execute(tool_name, arguments, ctx)

    context_budget.DEFAULT_TOOL_REGISTRY.execute = counting_execute
    try:
        for _ in range(2):
            build_llm_tool_context(
                repository=repo,
                file_tree=file_tree,
                conversation=conversation,
                scenario=PromptScenario.FOLLOW_UP,
            )
    finally:
        context_budget.DEFAULT_TOOL_REGISTRY.execute = original_execute

    assert call_count == 1


def test_tool_result_cache_is_safe_under_parallel_same_tool_call() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    cache = ToolResultCache(max_entries=8)

    def call_tool() -> dict[str, object]:
        return json.loads(
            execute_tool_call(
                "m1.get_repository_context",
                {},
                repository=repo,
                file_tree=file_tree,
                result_cache=cache,
            )
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call_tool(), range(16)))

    assert {result["display_name"] for result in results} == {repo.display_name}
    assert len(cache) == 1


def test_repository_reader_tools_are_read_only_and_redact_secrets() -> None:
    repo = _repository(_fixture_repo("secret_repo"), repo_id="repo_secret_test")
    file_tree = scan_repository_tree(repo)

    excerpt = read_file_excerpt(repo, file_tree, relative_path="main.py", max_lines=5)
    sensitive = read_file_excerpt(repo, file_tree, relative_path=".env", max_lines=5)
    matches = search_text(repo, file_tree, query="API_KEY")

    assert excerpt.payload["available"] is True
    assert "[redacted_secret]" in excerpt.payload["excerpt"]
    assert "sk-1234567890abcdefghijklmnop" not in excerpt.payload["excerpt"]
    assert sensitive.payload["available"] is False
    assert matches.payload["matches"]
    assert "[redacted_secret]" in matches.payload["matches"][0]["line"]
