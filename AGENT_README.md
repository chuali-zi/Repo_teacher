# Repo Tutor Agent README

This file is the maintenance guide for future agents working in this repository. Start here when you need the current runtime model rather than historical design intent.

## First Principles

1. The live product is `backend/` + `web/`, not `frontend/`.
2. Visible agent prose comes from `MessageDto.raw_text`.
3. The backend no longer provides `m3` static analysis conclusions or `m4` teaching skeletons.
4. The backend may help the agent navigate the repo, but it must not feed inferred architecture claims as facts.
5. Entry points, flows, layers, and dependency sources must come from source verification or be labeled as uncertain.

## Current Runtime Chain

Runtime defaults:

- Chat turns allow up to `50` tool rounds by default via `REPO_TUTOR_MAX_TOOL_ROUNDS`.
- Chat turns time out after `600` seconds by default via `REPO_TUTOR_CHAT_TURN_TIMEOUT_SECONDS`.

Initial analysis:

```text
POST /api/repo
  -> routes/repo.py
  -> m5_session.session_service.create_repo_session()
  -> SSE /api/analysis/stream
  -> AnalysisWorkflow
  -> M1 repo access
  -> M2 file tree scan
  -> TeachingService.initialize_teaching_state()
  -> M6 initial report with tool calling enabled
  -> status = chatting / waiting_user
```

Follow-up chat:

```text
POST /api/chat
  -> routes/chat.py
  -> m5_session.session_service.accept_chat_message()
  -> SSE /api/chat/stream
  -> ChatWorkflow
  -> TeachingService.build_prompt_input()
  -> agent_runtime.tool_loop (when tool calls are enabled)
  -> agent_tools / repository_tools
  -> M6 answer generation
  -> update teaching_state / history_summary / suggestions
```

## What Exists Now

| Path | Role |
| --- | --- |
| `backend/contracts/` | Domain, DTO, enum, and SSE contracts |
| `backend/routes/` | API entrypoints |
| `backend/m1_repo_access/` | Read-only repo access setup |
| `backend/m2_file_tree/` | File-tree indexing and safety filtering |
| `backend/m5_session/` | Session lifecycle, SSE, teaching state, workflow orchestration |
| `backend/m6_response/` | Prompt building, tool-loop integration, response parsing |
| `backend/llm_tools/` | Seeded LLM tool context builder |
| `backend/agent_tools/` | Tool registry and safe repo-reader implementations |
| `backend/agent_runtime/` | Tool selection, context budget, tool loop |
| `web/` | Active frontend |

## What Does Not Exist Anymore

- `m3_analysis/` as a live runtime dependency
- `m4_skeleton/` as a live runtime dependency
- `repo_kb/` as a live runtime dependency
- Prompt payloads that include `teaching_skeleton` or `topic_slice`
- Tool schemas such as `get_entry_candidates`, `get_module_map`, `get_reading_path`, or `get_evidence`

## Tooling Rules

The only backend tool surfaces the agent should treat as current are:

- `m1.get_repository_context`
- `m2.get_file_tree_summary`
- `m2.list_relevant_files`
- `teaching.get_state_snapshot`
- `search_text`
- `read_file_excerpt`

If you add a tool, keep it mechanical and evidence-oriented. Do not add a tool that returns explanatory architecture guesses.

## Files To Inspect For Common Changes

### If you are changing prompt behavior

- `backend/m5_session/teaching_service.py`
- `backend/m5_session/teaching_state.py`
- `backend/m6_response/prompt_builder.py`
- `backend/m6_response/response_parser.py`
- `backend/tests/test_m5_session.py`
- `backend/tests/test_m6_response.py`

### If you are changing tool calling

- `backend/agent_tools/analysis_tools.py`
- `backend/agent_tools/repository_tools.py`
- `backend/agent_runtime/context_budget.py`
- `backend/agent_runtime/tool_selection.py`
- `backend/agent_runtime/tool_loop.py`
- `backend/m6_response/tool_executor.py`
- `backend/tests/test_tool_calling.py`
- `backend/tests/test_llm_tools.py`

### If you are changing file-tree behavior

- `backend/m2_file_tree/`
- `backend/security/safety.py`
- `backend/tests/test_m2_file_tree.py`
- `backend/tests/test_security_safety.py`

### If you are changing API or SSE contracts

- `backend/contracts/dto.py`
- `backend/contracts/domain.py`
- `backend/contracts/enums.py`
- `backend/contracts/sse.py`
- `backend/routes/`
- `backend/m5_session/event_mapper.py`
- `web/js/api.js`
- `web/js/views.js`
- `backend/tests/test_routes.py`

### If you are changing the live frontend

- `web/index.html`
- `web/js/views.js`
- `web/js/state.js`
- `web/js/api.js`
- `web/css/main.css`
- `backend/tests/test_web_contracts.py`

## Testing

Backend:

```bash
pytest -q -p no:cacheprovider
```

If Windows temp permissions are noisy:

```bash
pytest -q --basetemp pytest_tmp_run -p no:cacheprovider
```

Live frontend:

```bash
cd web
python -m http.server 5180 --bind 127.0.0.1
```

Legacy prototype build:

```bash
cd frontend
npm run build
```

## Hard Constraints

1. Do not reintroduce backend-authored static teaching facts for entry, flow, layer, or dependency explanations.
2. Do not make `PromptBuildInput`, `SessionContext`, or tool execution depend on `teaching_skeleton` or `topic_slice` again.
3. Do not expose sensitive file contents or secrets through SSE, prompts, tool results, or logs.
4. Do not assume `frontend/` is the live UI unless the user explicitly asks for the legacy prototype.
5. If documentation and code disagree, trust the current runtime code first, then update the docs.
