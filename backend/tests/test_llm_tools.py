from __future__ import annotations

from pathlib import Path

from backend.contracts.domain import ConversationState, MessageRecord, RepositoryContext
from backend.contracts.enums import MessageRole, MessageType, PromptScenario
from backend.agent_runtime import context_budget
from backend.llm_tools import build_llm_tool_context, read_file_excerpt, search_text
from backend.m5_session.common import utc_now
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m3_analysis import run_static_analysis
from backend.m4_skeleton import assemble_teaching_skeleton
from backend.m6_response.prompt_builder import build_messages
from backend.security.safety import build_default_read_policy


def _repository(root: Path) -> RepositoryContext:
    return RepositoryContext(
        repo_id="repo_tool_test",
        source_type="local_path",
        display_name=root.name,
        input_value=str(root),
        root_path=str(root),
        is_temp_dir=False,
        access_verified=True,
        read_policy=build_default_read_policy(),
    )


def test_llm_tool_context_wraps_budgeted_seed_outputs(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Run with python app.py\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )

    repo = _repository(tmp_path)
    file_tree = scan_repository_tree(repo)
    analysis = run_static_analysis(repo, file_tree)
    skeleton = assemble_teaching_skeleton(analysis)
    topic_slice = skeleton.topic_index.entry_refs[:2]

    context = build_llm_tool_context(
        repository=repo,
        file_tree=file_tree,
        analysis=analysis,
        teaching_skeleton=skeleton,
        conversation=ConversationState(current_repo_id=repo.repo_id),
        topic_slice=topic_slice,
        scenario=PromptScenario.INITIAL_REPORT,
    )

    tool_names = {tool.tool_name for tool in context.tools}
    result_names = {result.tool_name for result in context.tool_results}

    assert "m1.get_repository_context" in tool_names
    assert "read_file_excerpt" in tool_names
    assert "m2.get_file_tree_summary" in result_names
    assert "m4.get_initial_report_skeleton" in result_names
    assert "teaching.get_state_snapshot" in result_names
    assert "read_file_excerpt" not in result_names
    assert "get_module_map" not in result_names
    assert "get_reading_path" not in result_names
    assert len(result_names) == 5
    repo_result = next(
        result for result in context.tool_results if result.tool_name == "m1.get_repository_context"
    )
    assert "root_path" not in repo_result.payload
    assert "read-only" in context.policy


def test_followup_tool_context_starts_small_and_prompt_omits_tool_definitions(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("Run with python app.py\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    repo = _repository(tmp_path)
    file_tree = scan_repository_tree(repo)
    analysis = run_static_analysis(repo, file_tree)
    skeleton = assemble_teaching_skeleton(analysis)
    context = build_llm_tool_context(
        repository=repo,
        file_tree=file_tree,
        analysis=analysis,
        teaching_skeleton=skeleton,
        conversation=ConversationState(current_repo_id=repo.repo_id),
        topic_slice=skeleton.topic_index.structure_refs[:2],
        scenario=PromptScenario.FOLLOW_UP,
    )

    result_names = {result.tool_name for result in context.tool_results}
    assert result_names == {
        "m1.get_repository_context",
        "m4.get_topic_slice",
        "teaching.get_state_snapshot",
    }

    from backend.contracts.domain import OutputContract, PromptBuildInput
    from backend.contracts.enums import DepthLevel, MessageSection

    prompt_input = PromptBuildInput(
        scenario=PromptScenario.FOLLOW_UP,
        user_message="这个仓库先看哪里？",
        teaching_skeleton=skeleton,
        topic_slice=skeleton.topic_index.structure_refs[:2],
        tool_context=context,
        conversation_state=ConversationState(current_repo_id=repo.repo_id),
        history_summary=None,
        depth_level=DepthLevel.DEFAULT,
        output_contract=OutputContract(
            required_sections=[MessageSection.FOCUS],
            max_core_points=3,
            must_include_next_steps=True,
            must_mark_uncertainty=True,
            must_use_candidate_wording=True,
        ),
    )
    system_text = build_messages(prompt_input)[0]["content"]
    assert '"tools":' not in system_text
    assert "input_schema" not in system_text
    assert "available_tool_names" in system_text


def test_source_question_adds_single_small_starter_excerpt(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Run with python app.py\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("\n".join(f"print({i})" for i in range(80)), encoding="utf-8")

    repo = _repository(tmp_path)
    file_tree = scan_repository_tree(repo)
    analysis = run_static_analysis(repo, file_tree)
    skeleton = assemble_teaching_skeleton(analysis)
    conversation = ConversationState(
        current_repo_id=repo.repo_id,
        messages=[
            MessageRecord(
                message_id="msg_user",
                role=MessageRole.USER,
                message_type=MessageType.USER_QUESTION,
                created_at=utc_now(),
                raw_text="结合代码讲 app.py",
                streaming_complete=True,
            )
        ],
    )

    context = build_llm_tool_context(
        repository=repo,
        file_tree=file_tree,
        analysis=analysis,
        teaching_skeleton=skeleton,
        conversation=conversation,
        topic_slice=skeleton.topic_index.entry_refs[:2],
        scenario=PromptScenario.FOLLOW_UP,
    )

    excerpts = [result for result in context.tool_results if result.tool_name == "read_file_excerpt"]
    assert len(excerpts) == 1
    assert len(excerpts[0].payload["files"]) == 1
    assert excerpts[0].payload["files"][0]["line_count"] <= 40


def test_deterministic_seed_results_use_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "README.md").write_text("Run with python app.py\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    repo = _repository(tmp_path)
    file_tree = scan_repository_tree(repo)
    analysis = run_static_analysis(repo, file_tree)
    skeleton = assemble_teaching_skeleton(analysis)
    conversation = ConversationState(current_repo_id=repo.repo_id)
    call_count = 0
    context_budget.GLOBAL_TOOL_RESULT_CACHE._store.clear()
    original_execute = context_budget.DEFAULT_TOOL_REGISTRY.execute

    def counting_execute(tool_name, arguments, ctx):
        nonlocal call_count
        if tool_name == "m1.get_repository_context":
            call_count += 1
        return original_execute(tool_name, arguments, ctx)

    monkeypatch.setattr(context_budget.DEFAULT_TOOL_REGISTRY, "execute", counting_execute)
    for _ in range(2):
        build_llm_tool_context(
            repository=repo,
            file_tree=file_tree,
            analysis=analysis,
            teaching_skeleton=skeleton,
            conversation=conversation,
            topic_slice=skeleton.topic_index.structure_refs[:2],
            scenario=PromptScenario.FOLLOW_UP,
        )

    assert call_count == 1


def test_repository_reader_tools_are_read_only_and_redact_secrets(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text(
        "API_KEY = 'sk-1234567890abcdefghijklmnop'\nprint(API_KEY)\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")

    repo = _repository(tmp_path)
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
