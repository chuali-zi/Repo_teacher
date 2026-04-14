# Repo Tutor

Repo Tutor is a local, single-user teaching assistant for reading repositories.
It follows the current spec entry in `docs/CURRENT_SPEC.md`.

## Current Spec Set

1. `docs/PRD_v5_agent.md`
2. `docs/interaction_design_v1.md`
3. `docs/technical_architecture_v3.md`
4. `docs/data_structure_design_v3.md`
5. `docs/interface_hard_spec_v3.md`
6. `docs/spec_audit_report_v2.md`

When documents conflict, treat `docs/CURRENT_SPEC.md` as the version gate and do
not invent alternate enum values, route names, SSE event names, or DTO shapes in
code.

## Layout

- `backend/`: FastAPI app, shared contracts, routes, M1-M6 backend modules, and tests.
- `frontend/`: React + TypeScript SPA, API client, SSE client, session store, views, and components.
- `docs/`: Product, architecture, data structure, and API specifications.
- `scripts/`: Windows helper scripts for local backend/frontend startup.

## Usage Guide

- User-facing setup and operation guide: `docs/USAGE_GUIDE.md`
- Current implementation scope and verification status: this `README.md`
- Normative product/interface constraints: `docs/CURRENT_SPEC.md` and the spec set it points to

## Backend Status

The backend is no longer only a scaffold. The current implementation includes:

- M1 repository access for local absolute paths and public GitHub URLs.
- M2 read-only file tree scan, ignore rules, sensitive-file marking, language detection, and repo size classification.
- M3 deterministic Python-first static analysis for entry candidates, imports, modules, layers, flows, reading path, evidence, warnings, and degradation.
- M4 teaching skeleton assembly in the initial-report field order required by the interface spec.
- M5 single active session orchestration, progress snapshots, SSE event mapping, chat turn lifecycle, and temp clone cleanup.
- M6 prompt building, DeepSeek/OpenAI-compatible calling, structured response parsing, and suggestion generation utilities.

Important runtime constraints:

- M5 is the only coordinator. Routes call M5; M5 calls M1-M4 for first analysis.
- M1-M4 are deterministic and do not call an LLM.
- Sensitive files may be reported as present, but their body is not read into analysis, SSE, DTOs, logs, or prompts.
- The app keeps only one in-memory active session and does not use a database.
- Multi-turn chat now routes through M5 -> M6: M5 builds a controlled `PromptBuildInput`, M6 builds the prompt, calls the configured LLM, parses the final structured answer, and M5 records the resulting message.
- If the LLM call or response parsing fails, chat emits `llm_api_failed` or `llm_api_timeout` instead of silently returning the old deterministic fallback answer.

## Frontend Status

The frontend is now implemented as a working React + TypeScript SPA aligned to the
current DTO/SSE contract. The current implementation includes:

- Input view with format validation messaging for local absolute paths and public GitHub URLs.
- Analysis view with server-driven progress rendering, degradation notices, timeout notice, and clear-session flow.
- Chat view with structured initial report rendering, structured multi-turn answer rendering, per-answer suggestion actions, and disabled-state mapping from `status + sub_status`.
- API client + SSE client wiring for `GET /api/session`, repo submit, chat submit, analysis stream, chat stream, and session clearing.
- Session recovery on page load through `GET /api/session`, including reconnecting analysis/chat SSE when the server reports an in-flight session.

Frontend behavior constraints:

- Frontend view state, disabled state, errors, and degradation messaging are driven by server DTOs or SSE events.
- Initial report rendering follows the `initial_report_content` section order from the interface spec.
- Multi-turn answer rendering follows the `structured_content` field order from the interface spec.
- Old SSE connections are closed on repo switch, reconnect, and unmount.

## Backend API

HTTP routes use the API envelope from `backend/contracts/dto.py`.

- `POST /api/repo/validate`: format-only validation; does not touch the filesystem or GitHub.
- `POST /api/repo`: creates a new session and returns `202 Accepted` with `analysis_stream_url`.
- `GET /api/session`: returns the current session snapshot; may omit `X-Session-Id` for local single-user recovery.
- `DELETE /api/session`: clears the active session and temp clone resources.
- `GET /api/analysis/stream?session_id=...`: SSE stream for repository access, scan, analysis, and initial report.
- `POST /api/chat`: accepts a user message when the session is `chatting + waiting_user`.
- `GET /api/chat/stream?session_id=...`: SSE stream for the current chat answer.

## Backend Setup

Using `uv`:

```bash
uv sync --extra dev
uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Using the existing Windows helper:

```cmd
scripts\dev_backend.cmd
```

GitHub repository input requires `git` on PATH. Live M6 LLM calls now read from
the visible root config file `llm_config.json` instead of environment variables.
The `openai` package is preferred when installed; if it is unavailable, the
backend falls back to a standard-library HTTP call against the same
OpenAI-compatible `/chat/completions` endpoint.

Example:

```json
{
  "api_key": "your_key_here",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "timeout_seconds": 60
}
```

Rules:

- `api_key` is required.
- `base_url`, `model`, and `timeout_seconds` are optional and fall back to defaults.
- If `llm_config.json` is missing or `api_key` is empty, M6 LLM calls will fail fast with a user-facing runtime error.

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Or on Windows:

```cmd
scripts\dev_frontend.cmd
```

The backend CORS allowlist currently includes `http://localhost:5173`.

## Tests

```bash
pytest -q -p no:cacheprovider
```

If Windows temp-directory permissions block pytest fixtures, use a local base
temp directory:

```bash
pytest -q --basetemp pytest_tmp -p no:cacheprovider
```

Current backend verification after this audit:

```text
51 passed, 1 skipped
```

`python -m compileall -q backend` also passes. `ruff` is listed in the dev
extras but was not available on the current PATH during this audit.

Current frontend verification:

```bash
cd frontend
npm run build
```

This currently passes and produces a production bundle in `frontend/dist/`.

Current end-to-end integration verification:

- Backend and frontend local dev servers can be started together on `127.0.0.1:8000` and `127.0.0.1:5173`.
- Vite `/api` proxy forwards correctly to the FastAPI backend in local development.
- Verified end-to-end flow: repo validate -> repo submit -> analysis SSE -> session snapshot recovery -> chat submit -> chat SSE -> session clear.
- Verified DTO/SSE behavior: initial report returns `initial_report_content`, follow-up answer returns `structured_content`, and session cleanup returns the app to `idle/input`.

Known integration note:

- In the current Windows PowerShell + `curl.exe` environment, directly posting Chinese JSON text may hit shell encoding/escaping issues and surface as `invalid_request`. Browser `fetch` and PowerShell `Invoke-RestMethod` based requests were verified successfully.

## Quick Start

1. Start the backend on `127.0.0.1:8000`.
2. Start the frontend dev server on `127.0.0.1:5173`.
3. Open `http://127.0.0.1:5173` in the browser.
4. Enter a local absolute repo path or a public GitHub repo URL.
5. Wait for the analysis stream to complete and review the first report.
6. Continue asking follow-up questions in chat, or click suggestion buttons.

For detailed daily usage, troubleshooting, and recommended workflows, see `docs/USAGE_GUIDE.md`.

## Audit Notes

This backend audit found and corrected several integration risks:

- M5 previously bypassed the implemented M2/M3/M4 modules with simplified internal placeholder analysis. It now delegates to `scan_repository_tree`, `run_static_analysis`, and `assemble_teaching_skeleton`.
- The first-analysis path now preserves M2 sensitive-file filtering before M3/M4 consume repository facts.
- Unexpected analysis exceptions are converted into user-facing `analysis_failed` SSE errors instead of leaking raw failures out of the stream.
- FastAPI request validation errors now return the project API envelope with `invalid_request`.
- Stale SSE session errors now keep the requested `session_id` in the error event, so clients can discard or close the correct stream.
- M3 now backfills referenced evidence IDs into `evidence_catalog` when deterministic modules emit evidence references without full evidence objects.
- Module package docstrings were updated to describe current implementation status instead of stale TODO-only scaffold text.
- M5 multi-turn chat previously never called M6/LLM and returned a hard-coded conservative answer. It now calls M6, streams LLM text, parses the structured result, updates conversation state, and surfaces explicit LLM errors when generation fails.

## Implementation Rules

- Use `backend/contracts` and `frontend/src/types/contracts.ts` as the naming source of truth.
- Do not add alternate route names, message types, SSE event names, enum values, or status transitions.
- M5 remains the only coordinator. Other modules must not mutate `ConversationState` directly.
- M1-M4 produce deterministic facts and must not call LLMs.
- Sensitive files may be recorded as existing, but their content must not be read or sent to M6.
- Frontend view state must come from server DTOs or SSE events, not local inference.
- For implementation status and currently completed frontend/backend scope, use this `README.md` as the latest source of truth.
