"""Contract-layer defaults and combination tests for ReportKind wiring."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from new_kernel.contracts import (
    ChatMessage,
    ChatMode,
    ReportKind,
    SendTeachingMessageRequest,
)


def test_chat_message_kind_default_is_answer() -> None:
    """A minimal ChatMessage must default to ReportKind.ANSWER for backward compatibility."""
    msg = ChatMessage(
        message_id="m-1",
        role="assistant",
        content="hello",
        created_at=datetime.now(timezone.utc),
    )
    # use_enum_values=True serializes to the string value, so compare to the string form.
    assert msg.kind == ReportKind.ANSWER.value


def test_send_teaching_request_report_kind_default_is_answer() -> None:
    """SendTeachingMessageRequest.report_kind defaults to ANSWER so existing callers stay green."""
    req = SendTeachingMessageRequest(message="hi")
    assert req.report_kind == ReportKind.ANSWER.value
    assert req.mode == ChatMode.CHAT.value


def test_send_teaching_request_accepts_repo_onboarding_with_deep_mode() -> None:
    """Deep-mode + REPO_ONBOARDING must be a valid contract-layer combination (route layer enforces semantics)."""
    req = SendTeachingMessageRequest(
        mode=ChatMode.DEEP,
        report_kind=ReportKind.REPO_ONBOARDING,
        message="x",
    )
    assert req.mode == ChatMode.DEEP.value
    assert req.report_kind == ReportKind.REPO_ONBOARDING.value


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
