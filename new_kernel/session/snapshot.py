# Snapshot 构造器：从 SessionState 装配 contracts.SessionSnapshotData（GET /api/v4/session 用），用于刷新页面后恢复 UI。
from __future__ import annotations

from ..contracts import SessionSnapshotData
from .session_state import SessionState


def build_snapshot(state: SessionState) -> SessionSnapshotData:
    """
    Build the public refresh/recovery snapshot for a session.

    This is a pure projection: it does not mutate timestamps, scratchpad, event bus,
    active turn state, or any owner-controlled field.
    """

    return SessionSnapshotData(
        session_id=state.session_id,
        repository=state.repository,
        agent_status=state.agent_status,
        parse_log=list(state.parse_log),
        messages=list(state.messages),
        current_code=state.current_code,
        mode=state.mode,
    )


__all__ = ["build_snapshot"]
