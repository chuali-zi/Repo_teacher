// HTTP + SSE clients. Every error path is reported with a clear "where".

import { report } from "./errors.js";

export const API_BASE = (() => {
  // Allow override via <meta name="rt-api-base" content="..."> if hosted elsewhere.
  const meta = document.querySelector('meta[name="rt-api-base"]');
  if (meta && meta.content) return meta.content.replace(/\/+$/, "");
  // localhost preferred (matches existing CORS); fall back to current host.
  const host = location.hostname || "127.0.0.1";
  return `http://${host}:8000`;
})();

async function request(method, path, { body, sessionId } = {}) {
  const url = `${API_BASE}${path}`;
  const headers = { "Accept": "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (sessionId) headers["X-Session-Id"] = sessionId;

  let resp;
  try {
    resp = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      mode: "cors",
    });
  } catch (err) {
    report({
      source: "fetch",
      level: "error",
      message: `网络请求失败：${method} ${path}`,
      where: "api.request",
      error: err,
    });
    throw err;
  }

  let payload = null;
  try {
    payload = await resp.json();
  } catch (err) {
    report({
      source: "fetch",
      level: "error",
      message: `响应不是合法 JSON：${method} ${path}（HTTP ${resp.status}）`,
      where: "api.parse",
      error: err,
    });
    throw err;
  }

  if (!resp.ok || (payload && payload.ok === false)) {
    const errPayload = (payload && payload.error) || {
      error_code: "unknown",
      message: `HTTP ${resp.status}`,
      retryable: false,
      stage: "idle",
      input_preserved: true,
    };
    report({
      source: "api",
      level: "warn",
      message: `${method} ${path} → ${errPayload.error_code}: ${errPayload.message}`,
      where: `HTTP ${resp.status}`,
      raw: payload,
    });
    const e = new Error(errPayload.message);
    e.payload = errPayload;
    e.status = resp.status;
    throw e;
  }
  return payload;
}

export const api = {
  validateRepo(inputValue) {
    return request("POST", "/api/repo/validate", { body: { input_value: inputValue } });
  },
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

// ---- SSE ----
// EventSource semantics: it auto-reconnects unless we close it.
// We treat any error after open as fatal — server is supposed to close cleanly.
export function openStream(kind, sessionId, onEvent) {
  const path = kind === "analysis" ? "/api/analysis/stream" : "/api/chat/stream";
  const url = `${API_BASE}${path}?session_id=${encodeURIComponent(sessionId)}`;
  let es;
  try {
    es = new EventSource(url);
  } catch (err) {
    report({ source: "sse", level: "error", message: `创建 ${kind} 流失败`, where: `openStream(${kind})`, error: err });
    throw err;
  }

  // Server uses named events. EventSource only fires "message" for unnamed payloads —
  // we have to subscribe to each event name.
  const NAMED = [
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

  const listeners = NAMED.map((name) => {
    const fn = (msg) => {
      if (msg.data == null || msg.data === "" || msg.data === "undefined") return;
      let data;
      try { data = JSON.parse(msg.data); }
      catch (err) {
        report({ source: "sse", level: "warn", message: `${kind} 流事件解析失败（非 JSON）`, where: `event ${name}`, raw: msg.data });
        return;
      }
      try { onEvent(data); }
      catch (err) {
        report({ source: "sse", level: "error", message: `${kind} 流事件处理异常`, where: `handle ${name}`, error: err, raw: data });
      }
    };
    es.addEventListener(name, fn);
    return [name, fn];
  });

  es.onerror = () => {
    // EventSource fires onerror on close as well as failure. Distinguish by readyState.
    if (es.readyState === EventSource.CLOSED) {
      report({ source: "sse", level: "info", message: `${kind} 流已关闭`, where: "EventSource.CLOSED" });
    } else if (es.readyState === EventSource.CONNECTING) {
      report({ source: "sse", level: "warn", message: `${kind} 流断开，浏览器自动重连中…`, where: "EventSource.CONNECTING" });
    } else {
      report({ source: "sse", level: "error", message: `${kind} 流出现错误`, where: `readyState=${es.readyState}` });
    }
  };

  return () => {
    for (const [name, fn] of listeners) es.removeEventListener(name, fn);
    es.close();
  };
}
