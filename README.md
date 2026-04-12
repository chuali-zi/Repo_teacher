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

## Backend Status

The backend is no longer only a scaffold. The current implementation includes:

- M1 repository access for local absolute paths and public GitHub URLs.
- M2 read-only file tree scan, ignore rules, sensitive-file marking, language detection, and repo size classification.
- M3 deterministic Python-first static analysis for entry candidates, imports, modules, layers, flows, reading path, evidence, warnings, and degradation.
- M4 teaching skeleton assembly in the initial-report field order required by the interface spec.
- M5 single active session orchestration, progress snapshots, SSE event mapping, chat turn lifecycle, and temp clone cleanup.
- M6 prompt building, DeepSeek/OpenAI-compatible streaming helper, structured response parsing, and suggestion generation utilities.

Important runtime constraints:

- M5 is the only coordinator. Routes call M5; M5 calls M1-M4 for first analysis.
- M1-M4 are deterministic and do not call an LLM.
- Sensitive files may be reported as present, but their body is not read into analysis, SSE, DTOs, logs, or prompts.
- The app keeps only one in-memory active session and does not use a database.
- Multi-turn chat currently uses a deterministic structured fallback in M5. M6 has prompt/parser/LLM utilities, but full live LLM orchestration is still a follow-up integration step.

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

GitHub repository input requires `git` on PATH. Live M6 LLM calls require either
`DEEPSEEK_API_KEY` or `OPENAI_API_KEY`; optional overrides are `M6_LLM_BASE_URL`,
`M6_LLM_MODEL`, and `M6_LLM_TIMEOUT_SECONDS`.

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
44 passed, 1 skipped
```

`python -m compileall -q backend` also passes. `ruff` is listed in the dev
extras but was not available on the current PATH during this audit.

## Audit Notes

This backend audit found and corrected several integration risks:

- M5 previously bypassed the implemented M2/M3/M4 modules with simplified internal placeholder analysis. It now delegates to `scan_repository_tree`, `run_static_analysis`, and `assemble_teaching_skeleton`.
- The first-analysis path now preserves M2 sensitive-file filtering before M3/M4 consume repository facts.
- Unexpected analysis exceptions are converted into user-facing `analysis_failed` SSE errors instead of leaking raw failures out of the stream.
- FastAPI request validation errors now return the project API envelope with `invalid_request`.
- Stale SSE session errors now keep the requested `session_id` in the error event, so clients can discard or close the correct stream.
- M3 now backfills referenced evidence IDs into `evidence_catalog` when deterministic modules emit evidence references without full evidence objects.
- Module package docstrings were updated to describe current implementation status instead of stale TODO-only scaffold text.

## Implementation Rules

- Use `backend/contracts` and `frontend/src/types/contracts.ts` as the naming source of truth.
- Do not add alternate route names, message types, SSE event names, enum values, or status transitions.
- M5 remains the only coordinator. Other modules must not mutate `ConversationState` directly.
- M1-M4 produce deterministic facts and must not call LLMs.
- Sensitive files may be recorded as existing, but their content must not be read or sent to M6.
- Frontend view state must come from server DTOs or SSE events, not local inference.
