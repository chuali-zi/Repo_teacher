# SessionState：单个 session 的全部内存状态，字段含 session_id / repository / agent_status / parse_log / messages / scratchpad / current_code / mode / active_turn_id / event_bus 引用。
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..contracts import (
    AgentStatus,
    ChatMessage,
    ChatMode,
    ParseLogLine,
    RepositorySummary,
    TeachingCodeSnippet,
)

if TYPE_CHECKING:
    from ..events.event_bus import EventBus
    from ..memory.scratchpad import Scratchpad


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _ScratchpadFallback:
    """Structural placeholder used only until memory.scratchpad exposes Scratchpad."""

    question: str = ""
    reading_plan: list[Any] = field(default_factory=list)
    read_entries: list[Any] = field(default_factory=list)
    covered_points: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def default_scratchpad_factory() -> "Scratchpad":
    try:
        from ..memory.scratchpad import Scratchpad
    except ImportError:
        return _ScratchpadFallback()  # type: ignore[return-value]
    return Scratchpad()


@dataclass
class SessionState:
    """
    Single in-memory state container for one repository tutoring session.

    The state object is intentionally passive: it owns no repo parsing, turn execution,
    LLM, tool, or event construction behavior. Writers are constrained by
    module_interaction_spec.md section 8.
    """

    session_id: str
    event_bus: "EventBus"
    agent_status: AgentStatus

    mode: ChatMode = ChatMode.CHAT
    repository: RepositorySummary | None = None
    repo_root: Path | None = None
    parse_log: list[ParseLogLine] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)
    scratchpad: "Scratchpad" = field(default_factory=default_scratchpad_factory)
    current_code: TeachingCodeSnippet | None = None
    active_turn_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.session_id = _normalize_session_id(self.session_id)
        self.mode = ChatMode(self.mode)
        if self.repo_root is not None and not isinstance(self.repo_root, Path):
            self.repo_root = Path(self.repo_root)

    def touch(self) -> None:
        """Refresh the session timestamp without changing ownership of any state field."""

        self.updated_at = utc_now()


def _normalize_session_id(session_id: str) -> str:
    normalized = session_id.strip()
    if not normalized:
        raise ValueError("session_id must be a non-empty string")
    return normalized


__all__ = [
    "SessionState",
    "default_scratchpad_factory",
    "utc_now",
]
