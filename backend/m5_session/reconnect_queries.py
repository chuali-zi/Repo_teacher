from __future__ import annotations

from collections.abc import Iterable

from backend.contracts.enums import ConversationSubStatus, RuntimeEventType, SessionStatus


class ReconnectQueryService:
    def __init__(self, *, repository, events) -> None:
        self.repository = repository
        self.events = events

    def analysis_events(self, session_id: str) -> list:
        session = self.repository.require(session_id)
        events = [self.events.build_status_snapshot_event(session)]
        latest_progress = self.repository.latest_runtime_event(
            session_id,
            RuntimeEventType.ANALYSIS_PROGRESS,
        )
        if latest_progress is not None:
            events.append(latest_progress)

        if session.status == SessionStatus.CHATTING:
            final_event = self.repository.latest_initial_report_completed_event(session_id)
            if final_event is not None:
                events.append(final_event)
        elif session.status in {SessionStatus.ACCESS_ERROR, SessionStatus.ANALYSIS_ERROR}:
            error_event = self.repository.latest_runtime_event(session_id, RuntimeEventType.ERROR)
            if error_event is not None:
                events.append(error_event)
        return self._dedupe_by_event_id(events)

    def chat_events(self, session_id: str) -> list:
        session = self.repository.require(session_id)
        events = [self.events.build_status_snapshot_event(session)]
        if (
            session.status == SessionStatus.CHATTING
            and session.conversation.sub_status != ConversationSubStatus.WAITING_USER
        ):
            activity_event = self.repository.latest_runtime_event(
                session_id, RuntimeEventType.AGENT_ACTIVITY
            )
            if activity_event is not None:
                events.append(activity_event)
            return self._dedupe_by_event_id(events)

        final_event = self.repository.latest_chat_terminal_event(session_id)
        if final_event is not None:
            events.append(final_event)
        return self._dedupe_by_event_id(events)

    def _dedupe_by_event_id(self, events: Iterable) -> list:
        deduped = []
        seen: set[str] = set()
        for event in events:
            if event is None or event.event_id in seen:
                continue
            seen.add(event.event_id)
            deduped.append(event)
        return deduped
