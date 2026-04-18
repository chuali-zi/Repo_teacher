import assert from 'node:assert/strict';

import { applySseEvent, initialClientSessionStore } from '../src/store/sessionStore';
import type { ChatSseEvent, ClientSessionStore, MessageDto } from '../src/types/contracts';

const baseState: ClientSessionStore = {
  ...initialClientSessionStore,
  sessionId: 'sess_1',
  currentView: 'chat',
  status: 'chatting',
  subStatus: 'agent_streaming'
};

const activityEvent: ChatSseEvent = {
  event_id: 'evt_activity',
  event_type: 'agent_activity',
  session_id: 'sess_1',
  occurred_at: '2026-04-18T00:00:00Z',
  activity: {
    activity_id: 'act_1',
    phase: 'tool_running',
    summary: '正在读取 main.py 的代码摘录',
    tool_name: 'read_file_excerpt',
    tool_arguments: { relative_path: 'main.py' },
    round_index: 1,
    elapsed_ms: 120,
    soft_timed_out: false,
    failed: false,
    retryable: false
  }
};

const completedMessage: MessageDto = {
  message_id: 'msg_agent',
  role: 'agent',
  message_type: 'agent_answer',
  created_at: '2026-04-18T00:00:01Z',
  raw_text: 'done',
  structured_content: null,
  initial_report_content: null,
  related_goal: null,
  suggestions: [],
  streaming_complete: true,
  error_state: null
};

const messageCompletedEvent: ChatSseEvent = {
  event_id: 'evt_completed',
  event_type: 'message_completed',
  session_id: 'sess_1',
  occurred_at: '2026-04-18T00:00:01Z',
  message: completedMessage,
  status: 'chatting',
  sub_status: 'waiting_user',
  view: 'chat'
};

const activeState = applySseEvent(baseState, activityEvent);
assert.equal(activeState.activeAgentActivity?.phase, 'tool_running');
assert.equal(activeState.activeAgentActivity?.tool_name, 'read_file_excerpt');

const completedState = applySseEvent(activeState, messageCompletedEvent);
assert.equal(completedState.activeAgentActivity, null);
assert.equal(completedState.subStatus, 'waiting_user');
