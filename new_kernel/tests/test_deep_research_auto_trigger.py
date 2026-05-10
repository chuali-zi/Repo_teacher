"""SA-08 auto-trigger unit tests — deep_research/AGENTS.md §4 / §9.3.

Exercises ``new_kernel.api.routes.repositories._kickoff_repo_onboarding`` in
isolation: a fake ``ApiRuntime`` namespace + a placeholder session object are
fed in directly so the test does not stand up FastAPI, the parse pipeline,
or any real ``TurnRuntime``. The tests pin three behaviours required by the
spec:

1. When ``runtime.turn_runtime`` exists, ``start_turn`` is invoked exactly
   once with ``mode=DEEP``, ``report_kind=REPO_ONBOARDING``, ``initiator=
   "system"``, and ``state`` set to the supplied session.
2. When ``runtime.turn_runtime is None`` the helper returns silently without
   raising.
3. When ``start_turn`` itself raises (e.g. ``InvalidTurnStateError`` because
   another turn is already running), the helper swallows it so the parse
   pipeline result remains visible to the user.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from new_kernel.api.routes.repositories import _kickoff_repo_onboarding
from new_kernel.contracts import ChatMode, ReportKind, SendTeachingMessageRequest


@dataclass
class _FakeRuntime:
    """Minimal stand-in for ``ApiRuntime`` exposing only what the helper reads."""

    turn_runtime: Any = None


class _FakeSession:
    """Inert placeholder — the helper just hands it back as ``state=`` kwarg."""

    def __init__(self, session_id: str = "sess_test_onboarding") -> None:
        self.session_id = session_id


class _RecordingTurnRuntime:
    """Capture ``start_turn`` calls without exercising real turn machinery."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def start_turn(
        self,
        *,
        state: Any,
        request: SendTeachingMessageRequest,
        initiator: str = "user",
    ) -> None:
        self.calls.append(
            {
                "state": state,
                "request": request,
                "initiator": initiator,
            }
        )


class _ExplodingTurnRuntime:
    """Mimic ``InvalidTurnStateError`` (or any RuntimeError) during start_turn."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.call_count = 0

    async def start_turn(
        self,
        *,
        state: Any,
        request: SendTeachingMessageRequest,
        initiator: str = "user",
    ) -> None:
        self.call_count += 1
        raise self._exc


def test_auto_trigger_calls_start_turn_with_correct_request() -> None:
    """Happy path: helper calls start_turn once with the spec-mandated payload."""

    turn_runtime = _RecordingTurnRuntime()
    runtime = _FakeRuntime(turn_runtime=turn_runtime)
    session = _FakeSession()

    asyncio.run(_kickoff_repo_onboarding(runtime=runtime, session=session))

    assert len(turn_runtime.calls) == 1, "start_turn should be invoked exactly once"
    call = turn_runtime.calls[0]
    assert call["state"] is session, "state must be the supplied session object"
    assert call["initiator"] == "system", "initiator must be 'system' for auto-trigger"
    request = call["request"]
    assert isinstance(request, SendTeachingMessageRequest)
    assert ChatMode(request.mode) == ChatMode.DEEP
    assert ReportKind(request.report_kind) == ReportKind.REPO_ONBOARDING
    assert request.message  # non-empty seed text per AGENTS.md §4.1


def test_auto_trigger_no_op_when_turn_runtime_missing() -> None:
    """Helper must short-circuit silently when ``runtime.turn_runtime is None``."""

    runtime = _FakeRuntime(turn_runtime=None)
    session = _FakeSession()

    # Must not raise; nothing to assert beyond "no exception escapes".
    asyncio.run(_kickoff_repo_onboarding(runtime=runtime, session=session))


def test_auto_trigger_swallows_start_turn_exception() -> None:
    """Per AGENTS.md §4.1, parse pipeline must not fail if onboarding can't start."""

    boom = _ExplodingTurnRuntime(RuntimeError("boom"))
    runtime = _FakeRuntime(turn_runtime=boom)
    session = _FakeSession()

    # Must not propagate the RuntimeError.
    asyncio.run(_kickoff_repo_onboarding(runtime=runtime, session=session))
    assert boom.call_count == 1, "start_turn should still have been attempted once"
