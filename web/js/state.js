// Tiny state store. Subscribe + notify, no proxies, no batching surprises.
// State shape mirrors ClientSessionStore from contracts.

const initial = {
  sessionId: null,
  status: "idle",
  subStatus: null,
  view: "input",
  repository: null,
  progressSteps: [],
  degradationNotices: [],
  messages: [], // MessageDto[]; streaming messages added with synthetic local entry
  activeAgentActivity: null,
  activityHistory: [],
  activeError: null,
  activeStream: null, // { kind: "analysis"|"chat", messageId: string, text: string }
  bootError: null,
};

const listeners = new Set();
let state = { ...initial };

export function getState() {
  return state;
}

export function setState(patch) {
  if (typeof patch === "function") patch = patch(state);
  if (!patch) return;
  state = { ...state, ...patch };
  notify();
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) {
    try { fn(state); }
    catch (err) { import("./errors.js").then((m) => m.report({ source: "state", level: "error", error: err, where: "subscriber" })); }
  }
  // Emit for plugin bus (lazy import to avoid import cycle at parse time)
  import("./plugins.js").then((m) => m.bus.emit("state:change", state)).catch(() => {});
}

// --- specialized mutators (keep semantics in one place) ---

export function applySessionSnapshot(snap) {
  setState({
    sessionId: snap.session_id ?? null,
    status: snap.status,
    subStatus: snap.sub_status,
    view: snap.view,
    repository: snap.repository,
    progressSteps: snap.progress_steps ?? [],
    degradationNotices: snap.degradation_notices ?? [],
    messages: snap.messages ?? [],
    activeAgentActivity: snap.active_agent_activity ?? null,
    activityHistory: snap.active_agent_activity ? [snap.active_agent_activity] : [],
    activeError: snap.active_error ?? null,
    activeStream: null,
  });
}

export function appendMessage(msg) {
  // dedup by message_id
  const existing = state.messages.findIndex((m) => m.message_id === msg.message_id);
  const messages = state.messages.slice();
  if (existing >= 0) messages[existing] = msg;
  else messages.push(msg);
  setState({ messages });
}

export function startStream(kind, messageId, messageType) {
  setState({
    activeStream: { kind, messageId, messageType, text: "" },
  });
}

export function appendStreamDelta(messageId, delta) {
  if (!state.activeStream || state.activeStream.messageId !== messageId) return;
  setState({
    activeStream: { ...state.activeStream, text: state.activeStream.text + delta },
  });
}

export function endStream(messageId) {
  if (!state.activeStream || state.activeStream.messageId !== messageId) return;
  setState({ activeStream: null });
}

export function reset() {
  state = { ...initial };
  notify();
}
