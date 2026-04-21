window.RTV3 = window.RTV3 || {};

(function (ns) {
  async function apiRequest(method, path, { body, sessionId } = {}) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (sessionId) headers["X-Session-Id"] = sessionId;
    const resp = await fetch(ns.API_BASE + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      mode: "cors",
    });
    let payload = null;
    try {
      payload = await resp.json();
    } catch (_) {
      // ignore
    }
    if (!resp.ok || (payload && payload.ok === false)) {
      const failure = (payload && payload.error) || {
        error_code: "unknown",
        message: "HTTP " + resp.status,
        retryable: false,
        stage: "idle",
        input_preserved: true,
      };
      const err = new Error(failure.message);
      err.payload = failure;
      err.status = resp.status;
      throw err;
    }
    return payload;
  }

  const api = {
    submitRepo: (inputValue, analysisMode = "quick_guide") =>
      apiRequest("POST", "/api/repo", { body: { input_value: inputValue, analysis_mode: analysisMode } }),
    validateRepo: (inputValue) =>
      apiRequest("POST", "/api/repo/validate", { body: { input_value: inputValue } }),
    getSession: (sessionId) =>
      apiRequest("GET", "/api/session", { sessionId: sessionId || undefined }),
    clearSession: (sessionId) => apiRequest("DELETE", "/api/session", { sessionId }),
    sendMessage: (sessionId, message) =>
      apiRequest("POST", "/api/chat", { body: { message }, sessionId }),
    explainSidecar: (question) =>
      apiRequest("POST", "/api/sidecar/explain", { body: { question } }),
  };

  function openStream(kind, sessionId, onEvent, onClose) {
    const path = kind === "analysis" ? "/api/analysis/stream" : "/api/chat/stream";
    const url = ns.API_BASE + path + "?session_id=" + encodeURIComponent(sessionId);
    const source = new EventSource(url);
    const names = [
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
    const handlers = names.map((name) => {
      const fn = (ev) => {
        if (!ev.data) return;
        try {
          onEvent(name, JSON.parse(ev.data));
        } catch (_) {
          // ignore parse errors
        }
      };
      source.addEventListener(name, fn);
      return [name, fn];
    });
    source.onerror = () => {
      if (onClose) onClose(source.readyState);
    };
    return () => {
      for (const [name, fn] of handlers) source.removeEventListener(name, fn);
      source.close();
    };
  }

  ns.apiRequest = apiRequest;
  ns.api = api;
  ns.openStream = openStream;
})(window.RTV3);
