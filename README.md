# Repo Tutor

Repo Tutor is a read-only repository teaching agent. The current runtime is deliberately conservative: the backend only provides repository access, file-tree indexing, teaching state, and safe source-reading tools. It does not generate static explanations of entry points, flows, layers, or dependencies for the agent to repeat as facts.

## Current Runtime

- Active stack: `backend/` + `web_v2/`
- `web_v2/` is the default live frontend. `web/` is a legacy static fallback, and `frontend/` is the older React/Vite prototype.
- Agent messages render from `MessageDto.raw_text`. The frontend does not synthesize visible prose from `structured_content` or `initial_report_content`.
- `structured_content` and `initial_report_content` still exist in the backend/SSE contracts for teaching state, suggestions, and compatibility.
- Chat turns allow up to `50` tool rounds by default. Set `REPO_TUTOR_MAX_TOOL_ROUNDS` to override it.
- Chat turns time out after `600` seconds by default. Set `REPO_TUTOR_CHAT_TURN_TIMEOUT_SECONDS` to override it.
- `MAX_SELECTED_TOOLS = 5` only limits how many tool schemas are exposed in one round.

## Architecture

### What the backend still does

- `m1_repo_access`: validate local paths or public GitHub URLs and establish a read-only repository boundary
- `m2_file_tree`: scan the repository, apply ignore and sensitive-file policy, and build a compact file-tree index
- `m5_session`: manage session lifecycle, SSE events, teaching plan, student state, and prompt assembly
- `m6_response`: build prompts, stream LLM output, parse sidecar JSON, and run tool-calling loops
- `agent_tools` + `agent_runtime`: expose safe read-only tools such as file listing, text search, and bounded file excerpts

### What the backend no longer does

- No `m3`-style static entry inference
- No `m4`-style teaching skeleton or topic index
- No static `repo_kb` query layer
- No backend-authored “likely architecture” payload presented as verified teaching facts

### Current flow

Initial session:

1. `POST /api/repo`
2. M1 validates access
3. M2 scans the file tree
4. M5 initializes lightweight teaching state from the file tree
5. M6 generates the initial report with tool calling enabled
6. The agent verifies source files directly when needed

Follow-up turns:

1. `POST /api/chat`
2. M5 builds a prompt from conversation state + file-tree context
3. M6 may call read-only tools such as `m2.list_relevant_files`, `search_text`, and `read_file_excerpt`
4. The answer must stay evidence-first and mark uncertainty when source verification is incomplete

## Tooling Model

The agent can rely on:

- `m1.get_repository_context`
- `m2.get_file_tree_summary`
- `m2.list_relevant_files`
- `teaching.get_state_snapshot`
- `search_text`
- `read_file_excerpt`

The backend should not expose tools that return inferred entry points, module maps, reading paths, or “teaching skeleton” facts.

## Directory Guide

```text
Irene/
├── backend/
│   ├── main.py
│   ├── contracts/
│   ├── routes/
│   ├── m1_repo_access/
│   ├── m2_file_tree/
│   ├── m5_session/
│   ├── m6_response/
│   ├── llm_tools/
│   ├── agent_tools/
│   ├── agent_runtime/
│   ├── security/
│   └── tests/
├── web/
├── frontend/
├── docs/
├── scripts/
├── llm_config.example.json
└── pyproject.toml
```

## Quick Start

### 1. Requirements

- Python `3.11+`
- `git` on `PATH` if you want to inspect public GitHub repositories
- An OpenAI-compatible model endpoint

### 2. Configure the LLM

Create `llm_config.json` in the repo root:

```json
{
  "api_key": "your_api_key",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "timeout_seconds": 60
}
```

Supported environment variable overrides:

- `REPO_TUTOR_LLM_API_KEY`
- `REPO_TUTOR_LLM_BASE_URL`
- `REPO_TUTOR_LLM_MODEL`
- `REPO_TUTOR_LLM_TIMEOUT_SECONDS`
- `REPO_TUTOR_LLM_MAX_TOKENS`
- `REPO_TUTOR_MAX_TOOL_ROUNDS`
- `REPO_TUTOR_CHAT_TURN_TIMEOUT_SECONDS`

### 3. Install dependencies

```bash
uv sync --extra dev
```

Or:

```bash
python -m pip install -e ".[dev]"
```

### 4. Run the backend

```bash
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Or:

```bash
scripts\dev_backend.cmd
```

### 5. Run the live frontend

```bash
cd web_v2
python -m http.server 5180 --bind 127.0.0.1
```

Or:

```bash
scripts\dev_web.cmd
scripts\dev_all.cmd
```

Legacy static frontend:

```bash
scripts\dev_web_legacy.cmd
scripts\dev_all_legacy.cmd
```

### 6. Use it

1. Open `http://127.0.0.1:5180`
2. Submit a local repository path or `https://github.com/owner/repo`
3. Wait for the initial report
4. Continue asking source-oriented questions such as “where should I verify the entry?”, “read `main.py` with me”, or “show me the files related to the API layer”

## API Summary

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/repo/validate` | `POST` | Validate input only |
| `/api/repo` | `POST` | Create a session and start analysis |
| `/api/session` | `GET` | Return the current snapshot |
| `/api/session` | `DELETE` | Clear the active session |
| `/api/analysis/stream` | `GET` | Initial analysis / report SSE |
| `/api/chat` | `POST` | Submit a user message |
| `/api/chat/stream` | `GET` | Follow-up answer SSE |

## Testing

Backend:

```bash
pytest -q -p no:cacheprovider
```

If Windows temp permissions are problematic:

```bash
pytest -q --basetemp pytest_tmp_run -p no:cacheprovider
```

Legacy frontend prototype:

```bash
cd frontend
npm run build
```

## Notes For Maintainers

- Prefer `web_v2/` for current frontend work.
- Use `web/` only when you need the legacy static frontend, and `frontend/` only for the older React prototype.
- The backend should provide navigation help, not static teaching conclusions.
- Claims about entry points, flow, layering, or dependency sources must be backed by source-tool evidence or explicitly marked as uncertain.
- Some older design docs may still mention `m3` / `m4`. Treat the current code and this README as the source of truth for the live runtime.
