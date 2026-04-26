# Repo Tutor Agent README

This file is the maintenance guide for future agents working in this repository. Use the
current code plus `docs/current_architecture.md`, `docs/data_contracts.md`, and
`docs/protocols.md` as the live runtime baseline.

## First Principles

1. The live product is `backend/` + `web_v3/`.
2. `docs/` is the maintained documentation set; `new_docs/` is not source of truth.
3. Visible message text comes from `MessageDto.raw_text` and streamed `delta_text`.
4. Structured payloads still exist for metadata, evidence, suggestions, and compatibility.
5. Entry points, flows, layers, and dependency sources must come from source verification
   or be labeled as uncertain.

## Current Runtime Chain

Runtime defaults:

- Chat turns allow up to `50` tool rounds by default via `REPO_TUTOR_MAX_TOOL_ROUNDS`.
- Chat turns time out after `600` seconds by default via
  `REPO_TUTOR_CHAT_TURN_TIMEOUT_SECONDS`.

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
  -> M6 initial report (tool-aware when enabled)
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
  -> update teaching state / history summary / suggestions
```

## What Exists Now

| Path | Role |
| --- | --- |
| `backend/contracts/` | Domain, DTO, enum, and SSE contracts |
| `backend/routes/` | API entrypoints |
| `backend/m1_repo_access/` | Read-only repository access |
| `backend/m2_file_tree/` | File-tree indexing and safety filtering |
| `backend/m5_session/` | Session lifecycle, SSE, teaching state, workflow orchestration |
| `backend/m6_response/` | Prompt building, tool-loop integration, response parsing |
| `backend/agent_tools/` | Tool registry and safe repository readers |
| `backend/agent_runtime/` | Tool selection, context budget, and tool loop |
| `backend/deep_research/` | Deep-research selection and report synthesis |
| `web_v3/` | Active frontend |

## What Is Deprecated

- `web/`
- `web_v2/`
- historical spec trees that were previously stored in `docs/`
- anything in `new_docs/` unless the user explicitly says it is a draft they want edited

## Tooling Rules

The only backend tool surfaces the agent should treat as current are:

- `m1.get_repository_context`
- `m2.get_file_tree_summary`
- `m2.list_relevant_files`
- `teaching.get_state_snapshot`
- `search_text`
- `read_file_excerpt`

Do not add a tool that returns explanatory architecture guesses.

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

### If you are changing API, SSE, or contracts

- `backend/contracts/dto.py`
- `backend/contracts/domain.py`
- `backend/contracts/enums.py`
- `backend/contracts/sse.py`
- `backend/routes/`
- `backend/m5_session/event_mapper.py`
- `docs/current_architecture.md`
- `docs/data_contracts.md`
- `docs/protocols.md`

### If you are changing the live frontend

- `web_v3/index.html`
- `web_v3/js/services/api.js`
- `web_v3/js/app.js`
- `web_v3/js/components.js`
- `web_v3/js/config.js`
- `backend/tests/test_web_v3_contracts.py`

## Testing

Backend:

```bash
python -m pytest -q -p no:cacheprovider
```

If Windows temp permissions are noisy:

```bash
python -m pytest -q --basetemp pytest_tmp_run -p no:cacheprovider
```

Live frontend:

```bash
cd web_v3
python -m http.server 5181 --bind 127.0.0.1
```

## Hard Constraints

1. Do not reintroduce backend-authored static teaching facts for entry, flow, layer, or
   dependency explanations.
2. Do not make `PromptBuildInput`, `SessionContext`, or tool execution depend on
   `teaching_skeleton` or `topic_slice` again.
3. Do not expose sensitive file contents or secrets through SSE, prompts, tool results,
   or logs.
4. Do not treat deprecated frontends or `new_docs/` as current product truth.
5. If documentation and code disagree, trust the current runtime code first, then update
   the three maintained docs in `docs/`.
