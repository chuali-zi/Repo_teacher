from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

from backend.contracts.domain import MessageRecord, RuntimeEvent, StructuredAnswer
from backend.contracts.enums import (
    ConversationSubStatus,
    MessageRole,
    RuntimeEventType,
    SessionStatus,
)
from backend.m5_session.common import new_id, utc_now
from backend.m6_response.answer_generator import (
    LlmStreamer,
    ToolAwareLlmStreamer,
    ToolStreamActivity,
    ToolStreamTextDelta,
    parse_answer,
    stream_answer_text,
    stream_answer_text_with_tools,
)

ENV_CHAT_TURN_TIMEOUT_SECONDS = "REPO_TUTOR_CHAT_TURN_TIMEOUT_SECONDS"
DEFAULT_CHAT_TURN_TIMEOUT_SECONDS = 240.0


@dataclass(frozen=True)
class ChatTurnTimeouts:
    total_seconds: float = DEFAULT_CHAT_TURN_TIMEOUT_SECONDS


class ChatWorkflow:
    def __init__(self, *, repository, events, teaching, timeouts: ChatTurnTimeouts | None = None) -> None:
        self.repository = repository
        self.events = events
        self.teaching = teaching
        self.timeouts = timeouts or load_chat_turn_timeouts()

    async def run(
        self,
        session_id: str,
        *,
        llm_streamer: LlmStreamer,
        tool_streamer: ToolAwareLlmStreamer,
    ) -> AsyncIterator[RuntimeEvent]:
        session = self.repository.require(session_id)
        if (
            session.status != SessionStatus.CHATTING
            or session.conversation.sub_status != ConversationSubStatus.AGENT_THINKING
        ):
            return

        prompt_input = self.teaching.build_prompt_input(session)
        answer_id = new_id("msg_agent")
        status_start_index = len(session.runtime_events)
        self.events.transition_status(
            session,
            SessionStatus.CHATTING,
            ConversationSubStatus.AGENT_STREAMING,
        )
        for event in session.runtime_events[status_start_index:]:
            yield event

        yield self.events.append_runtime_event(
            session,
            RuntimeEventType.ANSWER_STREAM_START,
            message_id=answer_id,
            payload={"message_type": self.teaching.message_type_for_prompt(prompt_input.scenario)},
        )

        use_tool_calls = prompt_input.enable_tool_calls and session.repository and session.file_tree
        if use_tool_calls:
            answer_stream = stream_answer_text_with_tools(
                prompt_input,
                repository=session.repository,
                file_tree=session.file_tree,
                analysis=session.analysis,
                teaching_skeleton=session.teaching_skeleton,
                tool_streamer=tool_streamer,
                on_activity=lambda **payload: self.events.record_agent_activity(
                    session,
                    **payload,
                ),
            )
        else:
            answer_stream = stream_answer_text(prompt_input, llm_streamer=llm_streamer)

        raw_chunks: list[str] = []
        visible_chunks: list[str] = []
        visible_buffer = ""
        json_output_started = False
        answer_stream_ended = False
        json_marker = "<json_output>"
        marker_tail_size = len(json_marker) - 1
        timeout_scope = None
        try:
            timeout_scope = asyncio.timeout(self.timeouts.total_seconds)
            async with timeout_scope:
                async for item in answer_stream:
                    if isinstance(item, ToolStreamActivity):
                        event = (
                            item.recorded_event
                            if isinstance(item.recorded_event, RuntimeEvent)
                            else self.events.record_agent_activity(session, **item.payload)
                        )
                        yield event
                        continue
                    chunk = item.text if isinstance(item, ToolStreamTextDelta) else item
                    raw_chunks.append(chunk)
                    if json_output_started:
                        continue
                    visible_buffer += chunk
                    marker_index = visible_buffer.find(json_marker)
                    if marker_index >= 0:
                        visible_chunk = visible_buffer[:marker_index]
                        visible_buffer = ""
                        json_output_started = True
                    elif len(visible_buffer) > marker_tail_size:
                        visible_chunk = visible_buffer[:-marker_tail_size]
                        visible_buffer = visible_buffer[-marker_tail_size:]
                    else:
                        visible_chunk = ""
                    if visible_chunk:
                        visible_chunks.append(visible_chunk)
                        yield self.events.append_runtime_event(
                            session,
                            RuntimeEventType.ANSWER_STREAM_DELTA,
                            message_id=answer_id,
                            message_chunk=visible_chunk,
                        )
                    if json_output_started and not answer_stream_ended:
                        yield self.events.append_runtime_event(
                            session,
                            RuntimeEventType.ANSWER_STREAM_END,
                            message_id=answer_id,
                        )
                        answer_stream_ended = True
        except asyncio.CancelledError as exc:
            self.events.cancel_chat_turn(session, exc)
            raise
        except TimeoutError as exc:
            error = (
                TimeoutError(f"Chat turn exceeded {self.timeouts.total_seconds:.1f} seconds")
                if timeout_scope is not None and timeout_scope.expired()
                else exc
            )
            for event in self.events.fail_chat_turn(session, error):
                yield event
            return
        except Exception as exc:
            for event in self.events.fail_chat_turn(session, exc):
                yield event
            return

        if visible_buffer and not json_output_started:
            visible_chunks.append(visible_buffer)
            yield self.events.append_runtime_event(
                session,
                RuntimeEventType.ANSWER_STREAM_DELTA,
                message_id=answer_id,
                message_chunk=visible_buffer,
            )

        raw_text = "".join(raw_chunks).strip()
        if not raw_text:
            error = RuntimeError("LLM returned an empty response")
            for event in self.events.fail_chat_turn(session, error):
                yield event
            return

        if not answer_stream_ended:
            yield self.events.append_runtime_event(
                session,
                RuntimeEventType.ANSWER_STREAM_END,
                message_id=answer_id,
            )

        try:
            parsed_answer = parse_answer(prompt_input, raw_text)
            if not isinstance(parsed_answer, StructuredAnswer):
                raise RuntimeError("M6 returned an initial-report answer for a chat turn")
            answer = parsed_answer.model_copy(update={"answer_id": answer_id})
            self.teaching.ensure_answer_suggestions(session, answer)
        except Exception as exc:
            for event in self.events.fail_chat_turn(session, exc):
                yield event
            return

        visible_text = "".join(visible_chunks)
        message = MessageRecord(
            message_id=answer.answer_id,
            role=MessageRole.AGENT,
            message_type=answer.message_type,
            created_at=utc_now(),
            raw_text=visible_text,
            structured_content=answer.structured_content,
            related_goal=session.conversation.current_learning_goal,
            suggestions=answer.suggestions,
            streaming_complete=True,
        )
        session.conversation.messages.append(message)
        session.conversation.last_suggestions = answer.suggestions
        session.conversation.current_stage = self.teaching.stage_for_goal(
            session.conversation.current_learning_goal,
            answer.message_type,
        )
        session.active_agent_activity = None
        session.last_error = None
        self.teaching.record_explained_items(session, answer, message.message_id)
        self.teaching.update_teaching_state_after_answer(
            session,
            answer,
            user_text=prompt_input.user_message or "",
            message_id=message.message_id,
            scenario=prompt_input.scenario,
        )
        self.teaching.update_history_summary(session)
        completion_start_index = len(session.runtime_events)
        self.events.transition_status(session, SessionStatus.CHATTING, ConversationSubStatus.WAITING_USER)
        for event in session.runtime_events[completion_start_index:]:
            yield event
        yield self.events.append_runtime_event(
            session,
            RuntimeEventType.MESSAGE_COMPLETED,
            message_id=message.message_id,
            payload={"message": message.model_dump(mode="python")},
        )


def load_chat_turn_timeouts() -> ChatTurnTimeouts:
    raw = os.getenv(ENV_CHAT_TURN_TIMEOUT_SECONDS)
    if not raw:
        return ChatTurnTimeouts()
    try:
        total_seconds = float(raw)
    except ValueError:
        return ChatTurnTimeouts()
    if total_seconds <= 0:
        return ChatTurnTimeouts()
    return ChatTurnTimeouts(total_seconds=total_seconds)
