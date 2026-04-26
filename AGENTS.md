# Repository Guidelines

## Project Structure & Module Organization
`backend/` contains the live FastAPI runtime, contracts, tool execution, and tests. Keep
tests in `backend/tests/`, with reusable fixture repositories under
`backend/tests/fixtures/`.

`web_v3/` is the current frontend served as static files. `web/` and `web_v2/` are
deprecated frontends and are not sources of truth. `docs/` is the maintained
documentation set and only keeps `current_architecture.md`, `data_contracts.md`, and
`protocols.md`. `new_docs/` is scratch material only. Helper launch scripts live in
`scripts/`.

## Build, Test, and Development Commands
Install dependencies with `uv sync --extra dev` or `python -m pip install -e ".[dev]"`.

Start the backend with `python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000`
or `scripts\dev_backend.cmd`.

Serve the default frontend with
`cd web_v3 && python -m http.server 5181 --bind 127.0.0.1`, or use `scripts\dev_web.cmd`.
On Windows, `scripts\dev_all.cmd` starts both backend and `web_v3`.

Run tests with `python -m pytest -q -p no:cacheprovider`. If temp directory permissions
are noisy on Windows, use
`python -m pytest -q --basetemp pytest_tmp_run -p no:cacheprovider`.

## Coding Style & Naming Conventions
Target Python 3.11+, use 4-space indentation, and keep lines within Ruff's configured
`100` character limit. Follow existing module naming: lowercase snake_case files,
descriptive service names such as `session_service.py`, and `test_*.py` for tests. Run
`python -m ruff check .` before submitting. `mypy` is available in dev dependencies for
type-sensitive changes.

## Documentation Rules
When documentation changes, treat `backend/` and `web_v3/` as the only implementation
bases. Update `docs/current_architecture.md`, `docs/data_contracts.md`, and
`docs/protocols.md` together when the live runtime changes. Do not reintroduce parallel
spec trees in `docs/` or treat `new_docs/` as normative.

## Testing Guidelines
Pytest is configured in `pyproject.toml` with `backend/tests` as the test root and `.`
on `PYTHONPATH`. Add focused unit tests beside the affected module area and reuse fixture
repos under `backend/tests/fixtures/` when validating repository access, file-tree
behavior, safety rules, scripts, or frontend contracts.

## Commit & Pull Request Guidelines
Recent git history uses very short numeric commit subjects (`1`, `3`, `5`), so there is
no strong enforced convention yet. For new work, prefer short imperative subjects that
describe the change clearly, for example `Align docs and web_v3 defaults`.

Pull requests should summarize behavior changes, list verification commands run, link the
relevant issue or spec, and include screenshots when UI files under `web_v3/` change.

## Configuration Tips
Keep secrets out of git. Start from `llm_config.example.json`, store local settings in
`llm_config.json`, and prefer environment variables for API credentials and runtime
overrides.
