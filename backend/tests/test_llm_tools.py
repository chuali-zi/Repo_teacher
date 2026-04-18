from __future__ import annotations

from pathlib import Path

from backend.contracts.domain import ConversationState, RepositoryContext
from backend.contracts.enums import PromptScenario
from backend.llm_tools import build_llm_tool_context, read_file_excerpt, search_text
from backend.m2_file_tree.tree_scanner import scan_repository_tree
from backend.m3_analysis import run_static_analysis
from backend.m4_skeleton import assemble_teaching_skeleton
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
    assert "read_file_excerpt" in result_names
    assert len(result_names) >= 6
    repo_result = next(
        result for result in context.tool_results if result.tool_name == "m1.get_repository_context"
    )
    assert "root_path" not in repo_result.payload
    assert "read-only" in context.policy


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
