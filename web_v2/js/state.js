const initialState = {
  sessionId: null,
  status: "idle",
  subStatus: null,
  view: "input",
  analysisMode: null,
  repository: null,
  progressSteps: [],
  deepResearchState: null,
  degradationNotices: [],
  messages: [],
  activeAgentActivity: null,
  activeError: null,
};

const listeners = new Set();
let state = { ...initialState };

export function getState() {
  return state;
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setState(patch) {
  const nextPatch = typeof patch === "function" ? patch(state) : patch;
  if (!nextPatch) return;
  state = { ...state, ...nextPatch };
  for (const listener of listeners) listener(state);
}

export function applySessionSnapshot(snapshot) {
  setState({
    sessionId: snapshot.session_id ?? null,
    status: snapshot.status,
    subStatus: snapshot.sub_status ?? null,
    view: snapshot.view,
    analysisMode: snapshot.analysis_mode ?? null,
    repository: snapshot.repository ?? null,
    progressSteps: snapshot.progress_steps ?? [],
    deepResearchState: snapshot.deep_research_state ?? null,
    degradationNotices: snapshot.degradation_notices ?? [],
    messages: snapshot.messages ?? [],
    activeAgentActivity: snapshot.active_agent_activity ?? null,
    activeError: snapshot.active_error ?? null,
  });
}

export function upsertMessage(message) {
  setState((current) => {
    const next = current.messages.slice();
    const index = next.findIndex((item) => item.message_id === message.message_id);
    if (index >= 0) next[index] = { ...next[index], ...message };
    else next.push(message);
    return { messages: next };
  });
}

export function setStreamingMessage(messageId, messageType) {
  upsertMessage({
    message_id: messageId,
    role: "agent",
    message_type: messageType,
    created_at: new Date().toISOString(),
    raw_text: "",
    suggestions: [],
    streaming_complete: false,
    error_state: null,
    _streaming: true,
  });
}

export function appendMessageDelta(messageId, delta) {
  setState((current) => ({
    messages: current.messages.map((message) =>
      message.message_id === messageId
        ? { ...message, raw_text: `${message.raw_text || ""}${delta || ""}` }
        : message,
    ),
  }));
}

export function resetState() {
  state = { ...initialState };
  for (const listener of listeners) listener(state);
}
