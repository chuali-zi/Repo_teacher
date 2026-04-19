from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.contracts.domain import ConversationState, OutputContract, PromptBuildInput, RepositoryContext
from backend.contracts.enums import DepthLevel, MessageSection, PromptScenario
from backend.llm_tools import build_llm_tool_context
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m6_response.answer_generator import (
    ToolLoopTimeouts,
    ToolStreamActivity,
    ToolStreamTextDelta,
    stream_answer_text_with_tools,
)
from backend.m6_response.llm_caller import StreamResult, ToolCallRequest
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.tool_executor import TOOL_SCHEMAS, execute_tool_call
from backend.security.safety import build_default_read_policy


def _fixture_repo(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def _repository(root: Path, repo_id: str = "repo_tc_test") -> RepositoryContext:
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


def _output_contract() -> OutputContract:
    return OutputContract(
        required_sections=[
            MessageSection.FOCUS,
            MessageSection.DIRECT_EXPLANATION,
            MessageSection.RELATION_TO_OVERALL,
            MessageSection.EVIDENCE,
            MessageSection.UNCERTAINTY,
            MessageSection.NEXT_STEPS,
        ],
        max_core_points=5,
        must_include_next_steps=True,
        must_mark_uncertainty=True,
        must_use_candidate_wording=True,
    )


def _prompt_input(conversation: ConversationState, *, enable_tools: bool = True) -> PromptBuildInput:
    return PromptBuildInput(
        scenario=PromptScenario.FOLLOW_UP,
        user_message="Explain how main.py works.",
        tool_context=None,
        conversation_state=conversation,
        history_summary=None,
        depth_level=DepthLevel.DEFAULT,
        output_contract=_output_contract(),
        enable_tool_calls=enable_tools,
    )


async def _collect_tool_stream(stream) -> tuple[str, list[object]]:
    chunks: list[str] = []
    items: list[object] = []
    async for item in stream:
        items.append(item)
        if isinstance(item, ToolStreamTextDelta):
            chunks.append(item.text)
    return "".join(chunks), items


def test_tool_schemas_expose_only_m1_m2_and_source_readers() -> None:
    names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}

    assert names == {
        "m1_get_repository_context",
        "m2_get_file_tree_summary",
        "m2_list_relevant_files",
        "teaching_get_state_snapshot",
        "read_file_excerpt",
        "search_text",
    }


def test_execute_repository_tools_and_unknown_tool() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)

    excerpt = json.loads(
        execute_tool_call(
            "read_file_excerpt",
            {"relative_path": "main.py", "start_line": 1, "max_lines": 10},
            repository=repo,
            file_tree=file_tree,
        )
    )
    search = json.loads(
        execute_tool_call(
            "search_text",
            {"query": "hello"},
            repository=repo,
            file_tree=file_tree,
        )
    )
    unknown = json.loads(
        execute_tool_call(
            "nonexistent_tool",
            {},
            repository=repo,
            file_tree=file_tree,
        )
    )

    assert excerpt["available"] is True
    assert "hello from main" in excerpt["excerpt"]
    assert search["matches"]
    assert "error" in unknown


def test_execute_tool_call_accepts_api_safe_tool_names() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)

    result = json.loads(
        execute_tool_call(
            "m2_list_relevant_files",
            {"limit": 5},
            repository=repo,
            file_tree=file_tree,
        )
    )

    assert result["tool_name"] == "m2.list_relevant_files"
    assert result["files"]


def test_prompt_builder_includes_tool_guidance_only_when_enabled() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    conversation = ConversationState(current_repo_id=repo.repo_id)
    tool_context = build_llm_tool_context(
        repository=repo,
        file_tree=file_tree,
        conversation=conversation,
        scenario=PromptScenario.FOLLOW_UP,
    )
    prompt_enabled = _prompt_input(conversation, enable_tools=True).model_copy(
        update={"tool_context": tool_context}
    )
    prompt_disabled = _prompt_input(conversation, enable_tools=False).model_copy(
        update={"tool_context": tool_context}
    )

    enabled_text = build_messages(prompt_enabled)[0]["content"]
    disabled_text = build_messages(prompt_disabled)[0]["content"]

    assert "available_tool_names" in enabled_text
    assert "search_text" in enabled_text
    assert "Function schemas are passed through the API tools parameter" in enabled_text
    assert "Function schemas are passed through the API tools parameter" not in disabled_text


def test_single_tool_call_round_reads_source_then_answers() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    prompt_input = _prompt_input(ConversationState(current_repo_id=repo.repo_id))
    call_count = 0

    async def fake_tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return StreamResult(
                content_chunks=[],
                tool_calls=[
                    ToolCallRequest(
                        call_id="call_001",
                        function_name="read_file_excerpt",
                        arguments_json=json.dumps({"relative_path": "main.py"}),
                    )
                ],
                finish_reason="tool_calls",
            )
        text = "## Focus\nmain.py prints a greeting.\n<json_output>{\"focus\":\"main.py\"}</json_output>"
        if on_content_delta:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    async def collect() -> tuple[str, list[object]]:
        return await _collect_tool_stream(
            stream_answer_text_with_tools(
                prompt_input,
                repository=repo,
                file_tree=file_tree,
                tool_streamer=fake_tool_streamer,
            )
        )

    text, items = asyncio.run(collect())

    assert call_count == 2
    assert "main.py prints a greeting" in text
    assert any(
        isinstance(item, ToolStreamActivity) and item.payload.get("tool_name") == "read_file_excerpt"
        for item in items
    )


def test_tool_timeout_degrades_instead_of_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    prompt_input = _prompt_input(ConversationState(current_repo_id=repo.repo_id))
    activities: list[dict[str, object]] = []
    call_count = 0

    from backend.agent_runtime import tool_loop

    def slow_execute_tool_call(*args, **kwargs):
        import time

        time.sleep(0.05)
        return json.dumps({"tool_name": "read_file_excerpt", "available": True})

    monkeypatch.setattr(tool_loop, "execute_tool_call", slow_execute_tool_call)

    async def fake_tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return StreamResult(
                content_chunks=[],
                tool_calls=[
                    ToolCallRequest(
                        call_id="call_slow",
                        function_name="read_file_excerpt",
                        arguments_json=json.dumps({"relative_path": "main.py"}),
                    )
                ],
                finish_reason="tool_calls",
            )
        text = "## Focus\nThe tool timed out, so this answer stays conservative.\n<json_output>{\"focus\":\"degraded\"}</json_output>"
        if on_content_delta:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    async def collect() -> tuple[str, list[object]]:
        return await _collect_tool_stream(
            stream_answer_text_with_tools(
                prompt_input,
                repository=repo,
                file_tree=file_tree,
                tool_streamer=fake_tool_streamer,
                on_activity=lambda **payload: activities.append(payload),
                timeouts=ToolLoopTimeouts(
                    thinking_notice_seconds=0.001,
                    code_search_notice_seconds=0.002,
                    tool_soft_timeout_seconds=0.01,
                    tool_hard_timeout_seconds=0.02,
                ),
            )
        )

    text, _ = asyncio.run(collect())
    phases = [item["phase"] for item in activities]

    assert "The tool timed out" in text
    assert "tool_failed" in phases
    assert "degraded_continue" in phases


def test_tool_loop_allows_more_than_ten_rounds_before_answering() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    prompt_input = _prompt_input(ConversationState(current_repo_id=repo.repo_id))
    call_count = 0

    async def fake_tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        nonlocal call_count
        call_count += 1
        if call_count <= 11:
            return StreamResult(
                content_chunks=[],
                tool_calls=[
                    ToolCallRequest(
                        call_id=f"call_{call_count:03d}",
                        function_name="read_file_excerpt",
                        arguments_json=json.dumps({"relative_path": "main.py"}),
                    )
                ],
                finish_reason="tool_calls",
            )
        text = "## Focus\nAnswer after eleven tool rounds.\n<json_output>{\"focus\":\"main.py\"}</json_output>"
        if on_content_delta:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    async def collect() -> tuple[str, list[object]]:
        return await _collect_tool_stream(
            stream_answer_text_with_tools(
                prompt_input,
                repository=repo,
                file_tree=file_tree,
                tool_streamer=fake_tool_streamer,
            )
        )

    text, items = asyncio.run(collect())
    phases = [
        item.payload.get("phase")
        for item in items
        if isinstance(item, ToolStreamActivity)
    ]

    assert call_count == 12
    assert "Answer after eleven tool rounds." in text
    assert "degraded_continue" not in phases


def test_tool_limit_uses_final_no_tool_round_after_fifty_rounds() -> None:
    repo = _repository(_fixture_repo("source_repo"))
    file_tree = scan_repository_tree(repo)
    prompt_input = _prompt_input(ConversationState(current_repo_id=repo.repo_id))
    call_count = 0
    tool_counts: list[int] = []

    async def fake_tool_streamer(messages, *, tools=None, on_content_delta=None, max_tokens=None):
        nonlocal call_count
        call_count += 1
        tool_counts.append(len(tools or []))
        if call_count <= 50:
            return StreamResult(
                content_chunks=[],
                tool_calls=[
                    ToolCallRequest(
                        call_id=f"call_{call_count:03d}",
                        function_name="read_file_excerpt",
                        arguments_json=json.dumps({"relative_path": "main.py"}),
                    )
                ],
                finish_reason="tool_calls",
            )
        text = "## Focus\nAnswer after tool limit.\n<json_output>{\"focus\":\"main.py\"}</json_output>"
        if on_content_delta:
            await on_content_delta(text)
        return StreamResult(content_chunks=[text], finish_reason="stop")

    async def collect() -> tuple[str, list[object]]:
        return await _collect_tool_stream(
            stream_answer_text_with_tools(
                prompt_input,
                repository=repo,
                file_tree=file_tree,
                tool_streamer=fake_tool_streamer,
            )
        )

    text, items = asyncio.run(collect())
    phases = [
        item.payload.get("phase")
        for item in items
        if isinstance(item, ToolStreamActivity)
    ]

    assert call_count == 51
    assert "Answer after tool limit." in text
    assert tool_counts[-1] == 0
    assert phases.count("degraded_continue") == 1
