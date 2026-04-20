import { report } from "./errors.js";

export const API_BASE = (() => {
  const meta = document.querySelector('meta[name="rt-api-base"]');
  if (meta?.content) return meta.content.replace(/\/+$/, "");
  const host = location.hostname || "127.0.0.1";
  return `http://${host}:8000`;
})();

async function request(method, path, { body, sessionId } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (sessionId) headers["X-Session-Id"] = sessionId;

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      mode: "cors",
    });
  } catch (error) {
    report({ source: "fetch", level: "error", message: `${method} ${path} failed`, where: "api.request", error });
    throw error;
  }

  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    report({ source: "fetch", level: "error", message: `${method} ${path} returned invalid JSON`, where: "api.parse", error });
    throw error;
  }

  if (!response.ok || payload?.ok === false) {
    const failure = payload?.error || {
      error_code: "unknown",
      message: `HTTP ${response.status}`,
      retryable: false,
      stage: "idle",
      input_preserved: true,
    };
    const error = new Error(failure.message);
    error.payload = failure;
    error.status = response.status;
    report({
      source: "api",
      level: "warn",
      message: `${method} ${path} -> ${failure.error_code}: ${failure.message}`,
      raw: payload,
    });
    throw error;
  }

  return payload;
}

export const api = {
  submitRepo(inputValue, analysisMode = "quick_guide") {
    return request("POST", "/api/repo", {
      body: { input_value: inputValue, analysis_mode: analysisMode },
    });
  },
  getSession(sessionId) {
    return request("GET", "/api/session", { sessionId: sessionId || undefined });
  },
  clearSession(sessionId) {
    return request("DELETE", "/api/session", { sessionId });
  },
  sendMessage(sessionId, message) {
    return request("POST", "/api/chat", { body: { message }, sessionId });
  },
  explainSidecar(question) {
    return request("POST", "/api/sidecar/explain", { body: { question } });
  },
};

export function openStream(kind, sessionId, onEvent) {
  const path = kind === "analysis" ? "/api/analysis/stream" : "/api/chat/stream";
  const url = `${API_BASE}${path}?session_id=${encodeURIComponent(sessionId)}`;

  let source;
  try {
    source = new EventSource(url);
  } catch (error) {
    report({ source: "sse", level: "error", message: `Could not open ${kind} stream`, where: `openStream(${kind})`, error });
    throw error;
  }

  const eventNames = [
    "status_changed",
    "analysis_progress",
    "degradation_notice",
    "agent_activity",
    "answer_stream_start",
    "answer_stream_delta",
    "answer_stream_end",
    "message_completed",
    "error",
  ];

  const listeners = eventNames.map((name) => {
    const listener = (message) => {
      if (!message.data) return;
      try {
        onEvent(JSON.parse(message.data));
      } catch (error) {
        report({ source: "sse", level: "warn", message: `${kind} event ${name} failed to parse`, raw: message.data, error });
      }
    };
    source.addEventListener(name, listener);
    return [name, listener];
  });

  source.onerror = () => {
    const level = source.readyState === EventSource.CONNECTING ? "warn" : "info";
    report({ source: "sse", level, message: `${kind} stream state ${source.readyState}` });
  };

  return () => {
    for (const [name, listener] of listeners) source.removeEventListener(name, listener);
    source.close();
  };
}
