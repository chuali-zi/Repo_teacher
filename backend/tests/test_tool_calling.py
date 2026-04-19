"""Tests for the hybrid tool-calling flow (M6 function calling extension)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from backend.contracts.domain import (
    ConversationState,
    OutputContract,
    PromptBuildInput,
    RepositoryContext,
)
from backend.contracts.enums import (
    DepthLevel,
    MessageSection,
    PromptScenario,
)
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m3_analysis import run_static_analysis
from backend.m4_skeleton import assemble_teaching_skeleton
from backend.agent_tools import repository_tools
from backend.agent_runtime import tool_loop
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


def _repository(root: Path) -> RepositoryContext:
    return RepositoryContext(
        repo_id="repo_tc_test",
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


def _prompt_input(skeleton, conversation, *, enable_tools: bool = True) -> PromptBuildInput:
    return PromptBuildInput(
        scenario=PromptScenario.FOLLOW_UP,
        user_message="这个函数具体怎么实现的？",
        teaching_skeleton=skeleton,
        topic_slice=skeleton.topic_index.entry_refs[:2],
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
        elif isinstance(item, str):
            chunks.append(item)
    return "".join(chunks), items


class TestToolSchemas:
    def test_tool_schemas_have_required_structure(self) -> None:
        assert len(TOOL_SCHEMAS) >= 7
        names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        assert {
            "get_repo_surfaces",
            "get_entry_candidates",
            "get_module_map",
            "get_reading_path",
            "get_evidence",
            "read_file_excerpt",
            "search_text",
        }.issubset(names)
        assert {
            "m1.get_repository_context",
            "m4.get_topic_slice",
            "teaching.get_state_snapshot",
        }.issubset(names)

    def test_read_file_excerpt_schema_has_required_fields(self) -> None:
        schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "read_file_excerpt")
        params = schema["function"]["parameters"]
        assert "relative_path" in params["properties"]
        assert "relative_path" in params["required"]
        assert params["properties"]["start_line"]["type"] == "integer"
        assert params["properties"]["max_lines"]["type"] == "integer"

    def test_search_text_schema_has_required_fields(self) -> None:
        schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "search_text")
        params = schema["function"]["parameters"]
        assert "query" in params["properties"]
        assert "query" in params["required"]


class TestToolExecutor:
    def test_execute_read_file_excerpt_returns_file_content(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)

        result_json = execute_tool_call(
            "read_file_excerpt",
            {"relative_path": "main.py", "start_line": 1, "max_lines": 10},
            repository=repo,
            file_tree=file_tree,
        )
        result = json.loads(result_json)
        assert result["available"] is True
        assert "def hello" in result["excerpt"]

    def test_execute_read_file_excerpt_uses_schema_default_line_count(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "main.py").write_text(
            "\n".join(f"print({line})" for line in range(80)),
            encoding="utf-8",
        )
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)

        result_json = execute_tool_call(
            "read_file_excerpt",
            {"relative_path": "main.py"},
            repository=repo,
            file_tree=file_tree,
        )
        result = json.loads(result_json)
        assert result["available"] is True
        assert result["line_count"] == 40

    def test_execute_read_file_excerpt_rejects_sensitive_file(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SECRET=abc\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)

        result_json = execute_tool_call(
            "read_file_excerpt",
            {"relative_path": ".env"},
            repository=repo,
            file_tree=file_tree,
        )
        result = json.loads(result_json)
        assert result["available"] is False

    def test_execute_search_text_finds_matches(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8"
        )
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)

        result_json = execute_tool_call(
            "search_text",
            {"query": "Flask"},
            repository=repo,
            file_tree=file_tree,
        )
        result = json.loads(result_json)
        assert len(result["matches"]) >= 1
        assert any("Flask" in m["line"] for m in result["matches"])

    def test_execute_search_text_degrades_on_rg_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "app.py").write_text("needle = True\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)

        monkeypatch.setattr(repository_tools.shutil, "which", lambda _: "rg")

        def timeout_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

        monkeypatch.setattr(repository_tools.subprocess, "run", timeout_run)
        result_json = execute_tool_call(
            "search_text",
            {"query": "needle"},
            repository=repo,
            file_tree=file_tree,
        )

        result = json.loads(result_json)
        assert result["degraded"] is True
        assert result["reason"] == "search_timeout"

    def test_execute_unknown_tool_returns_error(self, tmp_path: Path) -> None:
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)

        result_json = execute_tool_call(
            "nonexistent_tool",
            {},
            repository=repo,
            file_tree=file_tree,
        )
        result = json.loads(result_json)
        assert "error" in result


class TestPromptBuilderToolGuidance:
    def test_tool_guidance_included_when_enabled(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)

        prompt_input = _prompt_input(skeleton, conversation, enable_tools=True)
        messages = build_messages(prompt_input)
        system_text = messages[0]["content"]
        assert "工具调用说明" in system_text
        assert "read_file_excerpt" in system_text

    def test_tool_guidance_excluded_when_disabled(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)

        prompt_input = _prompt_input(skeleton, conversation, enable_tools=False)
        messages = build_messages(prompt_input)
        system_text = messages[0]["content"]
        assert "工具调用说明" not in system_text


class TestStreamAnswerWithTools:
    def test_direct_answer_without_tool_calls(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)
        prompt_input = _prompt_input(skeleton, conversation)

        async def fake_tool_streamer(
            messages, *, tools=None, on_content_delta=None, temperature=0.6
        ):
            text = '## 本轮重点\n直接回答。\n<json_output>{"focus":"直接"}</json_output>'
            if on_content_delta:
                await on_content_delta(text)
            return StreamResult(content_chunks=[text], finish_reason="stop")

        async def collect():
            text, _ = await _collect_tool_stream(
                stream_answer_text_with_tools(
                    prompt_input,
                    repository=repo,
                    file_tree=file_tree,
                    tool_streamer=fake_tool_streamer,
                )
            )
            return text

        result = asyncio.run(collect())
        assert "直接回答" in result

    def test_single_tool_call_round(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("def run():\n    pass\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)
        prompt_input = _prompt_input(skeleton, conversation)

        call_count = 0

        async def fake_tool_streamer(
            messages, *, tools=None, on_content_delta=None, temperature=0.6
        ):
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
            text = '## 本轮重点\n看了 main.py 后的回答。\n<json_output>{"focus":"main.py"}</json_output>'
            if on_content_delta:
                await on_content_delta(text)
            return StreamResult(content_chunks=[text], finish_reason="stop")

        async def collect():
            text, _ = await _collect_tool_stream(
                stream_answer_text_with_tools(
                    prompt_input,
                    repository=repo,
                    file_tree=file_tree,
                    tool_streamer=fake_tool_streamer,
                )
            )
            return text

        result = asyncio.run(collect())
        assert call_count == 2
        assert "main.py" in result

    def test_tool_calls_run_even_when_finish_reason_is_nonstandard(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("def run():\n    pass\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)
        prompt_input = _prompt_input(skeleton, conversation)
        call_count = 0

        async def nonstandard_finish_reason_streamer(
            messages, *, tools=None, on_content_delta=None, temperature=0.6
        ):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StreamResult(
                    tool_calls=[
                        ToolCallRequest(
                            call_id="",
                            function_name="repo.read_file_excerpt",
                            arguments_json=json.dumps({"relative_path": "main.py"}),
                        )
                    ],
                    finish_reason="stop",
                )
            text = '## 本轮重点\n非标准 finish_reason 仍完成回答。\n<json_output>{"focus":"ok"}</json_output>'
            if on_content_delta:
                await on_content_delta(text)
            return StreamResult(content_chunks=[text], finish_reason="stop")

        async def collect():
            text, items = await _collect_tool_stream(
                stream_answer_text_with_tools(
                    prompt_input,
                    repository=repo,
                    file_tree=file_tree,
                    tool_streamer=nonstandard_finish_reason_streamer,
                )
            )
            return text, items

        result, items = asyncio.run(collect())
        assert call_count == 2
        assert "仍完成回答" in result
        assert any(
            isinstance(item, ToolStreamActivity)
            and item.payload.get("tool_name") == "read_file_excerpt"
            for item in items
        )

    def test_max_tool_rounds_limit_prevents_infinite_loop(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("pass\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)
        prompt_input = _prompt_input(skeleton, conversation)
        prompt_input = prompt_input.model_copy(update={"max_tool_rounds": 2})

        call_count = 0

        async def always_call_tools(
            messages, *, tools=None, on_content_delta=None, temperature=0.6
        ):
            nonlocal call_count
            call_count += 1
            if tools == []:
                text = '## 本轮重点\n直接完成最终回答。\n<json_output>{"focus":"done"}</json_output>'
                if on_content_delta:
                    await on_content_delta(text)
                return StreamResult(content_chunks=[text], finish_reason="stop")
            return StreamResult(
                content_chunks=["partial..."],
                tool_calls=[
                    ToolCallRequest(
                        call_id=f"call_{call_count:03d}",
                        function_name="search_text",
                        arguments_json=json.dumps({"query": "something"}),
                    )
                ],
                finish_reason="tool_calls",
            )

        async def collect():
            text, items = await _collect_tool_stream(
                stream_answer_text_with_tools(
                    prompt_input,
                    repository=repo,
                    file_tree=file_tree,
                    tool_streamer=always_call_tools,
                )
            )
            return text, items

        text, items = asyncio.run(collect())
        assert call_count == 3  # 2 tool batches + final no-tool completion
        assert "直接完成" in text
        assert any(
            isinstance(item, ToolStreamActivity) and item.payload["phase"] == "degraded_continue"
            for item in items
        )

    def test_tool_call_with_search_then_read(self, tmp_path: Path) -> None:
        (tmp_path / "service.py").write_text(
            "class UserService:\n    def create_user(self):\n        pass\n",
            encoding="utf-8",
        )
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)
        prompt_input = _prompt_input(skeleton, conversation)
        prompt_input = prompt_input.model_copy(update={"max_tool_rounds": 2})

        call_count = 0

        async def multi_tool_streamer(
            messages, *, tools=None, on_content_delta=None, temperature=0.6
        ):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StreamResult(
                    content_chunks=[],
                    tool_calls=[
                        ToolCallRequest(
                            call_id="call_search",
                            function_name="search_text",
                            arguments_json=json.dumps({"query": "UserService"}),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            if call_count == 2:
                return StreamResult(
                    content_chunks=[],
                    tool_calls=[
                        ToolCallRequest(
                            call_id="call_read",
                            function_name="read_file_excerpt",
                            arguments_json=json.dumps({"relative_path": "service.py"}),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            text = "## 本轮重点\nUserService 分析完毕。"
            if on_content_delta:
                await on_content_delta(text)
            return StreamResult(content_chunks=[text], finish_reason="stop")

        async def collect():
            text, _ = await _collect_tool_stream(
                stream_answer_text_with_tools(
                    prompt_input,
                    repository=repo,
                    file_tree=file_tree,
                    tool_streamer=multi_tool_streamer,
                )
            )
            return text

        result = asyncio.run(collect())
        assert call_count == 3
        assert "UserService" in result

    def test_tool_activity_events_are_emitted(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("def run():\n    pass\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)
        prompt_input = _prompt_input(skeleton, conversation)
        prompt_input = prompt_input.model_copy(update={"max_tool_rounds": 2})
        activities: list[dict[str, object]] = []
        call_count = 0

        async def fake_tool_streamer(
            messages, *, tools=None, on_content_delta=None, temperature=0.6
        ):
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
            text = '## 本轮重点\n看了 main.py 后的回答。\n<json_output>{"focus":"main.py"}</json_output>'
            if on_content_delta:
                await on_content_delta(text)
            return StreamResult(content_chunks=[text], finish_reason="stop")

        async def collect():
            text, items = await _collect_tool_stream(
                stream_answer_text_with_tools(
                    prompt_input,
                    repository=repo,
                    file_tree=file_tree,
                    tool_streamer=fake_tool_streamer,
                    on_activity=lambda **payload: activities.append(payload),
                )
            )
            assert any(isinstance(item, ToolStreamActivity) for item in items)
            return text

        result = asyncio.run(collect())
        phases = [item["phase"] for item in activities]
        assert "planning_tool_call" in phases
        assert "tool_running" in phases
        assert "tool_succeeded" in phases
        assert "waiting_llm_after_tool" in phases
        assert "main.py" in result

    def test_tool_timeout_degrades_instead_of_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "service.py").write_text("def slow():\n    return True\n", encoding="utf-8")
        repo = _repository(tmp_path)
        file_tree = scan_repository_tree(repo)
        analysis = run_static_analysis(repo, file_tree)
        skeleton = assemble_teaching_skeleton(analysis)
        conversation = ConversationState(current_repo_id=repo.repo_id)
        prompt_input = _prompt_input(skeleton, conversation)
        activities: list[dict[str, object]] = []
        call_count = 0

        def slow_execute_tool_call(*args, **kwargs):
            import time

            time.sleep(0.05)
            return json.dumps({"tool_name": "read_file_excerpt", "available": True})

        monkeypatch.setattr(tool_loop, "execute_tool_call", slow_execute_tool_call)

        async def fake_tool_streamer(
            messages, *, tools=None, on_content_delta=None, temperature=0.6
        ):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StreamResult(
                    content_chunks=[],
                    tool_calls=[
                        ToolCallRequest(
                            call_id="call_slow",
                            function_name="read_file_excerpt",
                            arguments_json=json.dumps({"relative_path": "service.py"}),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            text = '## 本轮重点\n工具超时后仍继续回答。\n<json_output>{"focus":"degraded"}</json_output>'
            if on_content_delta:
                await on_content_delta(text)
            return StreamResult(content_chunks=[text], finish_reason="stop")

        async def collect():
            text, _ = await _collect_tool_stream(
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
            return text

        result = asyncio.run(collect())
        phases = [item["phase"] for item in activities]
        assert "tool_failed" in phases
        assert "degraded_continue" in phases
        assert "仍继续回答" in result
