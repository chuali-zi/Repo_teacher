import type {
  AnalysisSseEvent,
  ChatSseEvent,
  ClientSessionStore,
  MessageDto,
  SessionSnapshotDto
} from '../types/contracts';

export const initialClientSessionStore: ClientSessionStore = {
  sessionId: null,
  currentView: 'input',
  status: 'idle',
  subStatus: null,
  repoDisplayName: null,
  progressSteps: [],
  degradationNotices: [],
  messages: [],
  activeError: null
};

export type SessionAction =
  | { type: 'snapshot'; snapshot: SessionSnapshotDto }
  | { type: 'event'; event: AnalysisSseEvent | ChatSseEvent }
  | { type: 'reset' };

export function sessionReducer(
  state: ClientSessionStore,
  action: SessionAction
): ClientSessionStore {
  switch (action.type) {
    case 'snapshot':
      return fromSnapshot(action.snapshot);
    case 'event':
      return applySseEvent(state, action.event);
    case 'reset':
      return initialClientSessionStore;
  }
}

export function fromSnapshot(snapshot: SessionSnapshotDto): ClientSessionStore {
  return {
    sessionId: snapshot.session_id,
    currentView: snapshot.view,
    status: snapshot.status,
    subStatus: snapshot.sub_status,
    repoDisplayName: snapshot.repository?.display_name ?? null,
    progressSteps: snapshot.progress_steps,
    degradationNotices: snapshot.degradation_notices,
    messages: snapshot.messages,
    activeError: snapshot.active_error
  };
}

export function applySseEvent(
  state: ClientSessionStore,
  event: AnalysisSseEvent | ChatSseEvent
): ClientSessionStore {
  if (state.sessionId && event.session_id !== state.sessionId) {
    return state;
  }

  switch (event.event_type) {
    case 'status_changed':
      return {
        ...state,
        sessionId: event.session_id,
        status: event.status,
        subStatus: event.sub_status,
        currentView: event.view
      };
    case 'analysis_progress':
      return { ...state, progressSteps: event.progress_steps };
    case 'degradation_notice':
      return {
        ...state,
        degradationNotices: upsertById(
          state.degradationNotices,
          event.degradation,
          (item) => item.degradation_id
        )
      };
    case 'answer_stream_start':
      return {
        ...state,
        messages: upsertMessage(state.messages, {
          message_id: event.message_id,
          role: 'agent',
          message_type: event.message_type,
          created_at: event.occurred_at,
          raw_text: '',
          structured_content: null,
          initial_report_content: null,
          related_goal: null,
          suggestions: [],
          streaming_complete: false,
          error_state: null
        })
      };
    case 'answer_stream_delta':
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.message_id === event.message_id
            ? { ...message, raw_text: `${message.raw_text}${event.delta_text}` }
            : message
        )
      };
    case 'answer_stream_end':
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.message_id === event.message_id
            ? { ...message, streaming_complete: true }
            : message
        )
      };
    case 'message_completed':
      return {
        ...state,
        status: event.status,
        subStatus: event.sub_status,
        currentView: event.view,
        messages: upsertMessage(state.messages, event.message)
      };
    case 'error':
      return {
        ...state,
        status: event.status,
        subStatus: event.sub_status,
        currentView: event.view,
        activeError: event.error
      };
  }
}

function upsertMessage(messages: MessageDto[], next: MessageDto): MessageDto[] {
  const exists = messages.some((message) => message.message_id === next.message_id);
  if (!exists) {
    return [...messages, next];
  }
  return messages.map((message) => (message.message_id === next.message_id ? next : message));
}

function upsertById<T>(items: T[], next: T, getId: (item: T) => string): T[] {
  const nextId = getId(next);
  if (!items.some((item) => getId(item) === nextId)) {
    return [...items, next];
  }
  return items.map((item) => (getId(item) === nextId ? next : item));
}

