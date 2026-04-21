window.RTV3 = window.RTV3 || {};

(function (ns) {
  const { useState, useEffect, useRef, useCallback } = React;
  const {
    TWEAK_DEFAULTS,
    API_BASE,
    VIEW_MAP,
    mkLog,
    api,
    openStream,
    C,
    LeftPanel,
    CenterPanel,
    RightPanel,
    DebugOverlay,
    Divider,
    ChatHeader,
  } = ns;

  function App() {
    const [tweaks, setTweaks] = useState({ ...TWEAK_DEFAULTS });
    const [view, setView] = useState("input");
    const [repoInput, setRepoInput] = useState("");
    const [analysisMode, setAnalysisMode] = useState("quick_guide");
    const [sessionId, setSessionId] = useState(null);
    const [repoSummary, setRepoSummary] = useState(null);
    const [steps, setSteps] = useState([]);
    const [messages, setMessages] = useState([]);
    const [status, setStatus] = useState("idle");
    const [subStatus, setSubStatus] = useState(null);
    const [inputDisabled, setInputDisabled] = useState(false);
    const [streaming, setStreaming] = useState(false);
    const [analysisStream, setAnalysisStream] = useState("");
    const [activeActivity, setActiveActivity] = useState(null);
    const [activeError, setActiveError] = useState(null);
    const [deepResearch, setDeepResearch] = useState(null);
    const [logs, setLogs] = useState([mkLog("info", "system", "REPO TUTOR v3 INITIALIZED"), mkLog("debug", "system", "api_base: " + API_BASE)]);
    const [leftW, setLeftW] = useState(256);
    const [rightW, setRightW] = useState(264);

    const sseCloseRef = useRef(null);

    const addLog = useCallback((level, src, msg) => setLogs((l) => [...l, mkLog(level, src, msg)]), []);

    const closeStream = useCallback(() => {
      if (sseCloseRef.current) {
        sseCloseRef.current();
        sseCloseRef.current = null;
      }
    }, []);

    // unified SSE event router
    const handleSseEvent = useCallback(
      (name, event) => {
        switch (name) {
          case "status_changed":
            setStatus(event.status);
            setSubStatus(event.sub_status || null);
            setView(VIEW_MAP[event.view] || event.view || "input");
            addLog("info", "sse", `status_changed → ${event.status}${event.sub_status ? "/" + event.sub_status : ""}`);
            return;
          case "analysis_progress":
            if (Array.isArray(event.progress_steps) && event.progress_steps.length) {
              setSteps(event.progress_steps);
            } else {
              setSteps((prev) => {
                const idx = prev.findIndex((s) => s.step_key === event.step_key);
                if (idx < 0) return [...prev, { step_key: event.step_key, step_state: event.step_state }];
                const next = prev.slice();
                next[idx] = { ...next[idx], step_state: event.step_state };
                return next;
              });
            }
            if (event.deep_research_state) setDeepResearch(event.deep_research_state);
            addLog("info", "sse", `analysis_progress: ${event.step_key} → ${event.step_state}`);
            return;
          case "degradation_notice":
            addLog("warn", "sse", `degradation: ${event.degradation.type} — ${event.degradation.user_notice}`);
            return;
          case "agent_activity":
            setActiveActivity(event.activity);
            if (event.activity.phase) addLog("debug", "agent", `${event.activity.phase}: ${event.activity.summary || ""}`);
            return;
          case "answer_stream_start": {
            const now = new Date().toLocaleTimeString("zh", { hour: "2-digit", minute: "2-digit" });
            const stubMsg = {
              message_id: event.message_id,
              role: "agent",
              message_type: event.message_type,
              raw_text: "",
              suggestions: [],
              streaming_complete: false,
              time: now,
            };
            setMessages((m) => {
              const idx = m.findIndex((x) => x.message_id === event.message_id);
              if (idx >= 0) {
                const next = m.slice();
                next[idx] = { ...next[idx], ...stubMsg };
                return next;
              }
              return [...m, stubMsg];
            });
            setStreaming(false);
            setSubStatus("agent_streaming");
            if (event.message_type === "initial_report") setAnalysisStream("");
            return;
          }
          case "answer_stream_delta": {
            const delta = event.delta_text || "";
            setMessages((m) => m.map((x) => (x.message_id === event.message_id ? { ...x, raw_text: (x.raw_text || "") + delta } : x)));
            // mirror initial-report stream into the analyzing view textbox
            setMessages((m) => {
              const found = m.find((x) => x.message_id === event.message_id);
              if (found && found.message_type === "initial_report") {
                setAnalysisStream((s) => s + delta);
              }
              return m;
            });
            return;
          }
          case "answer_stream_end":
            return;
          case "message_completed": {
            const now = new Date().toLocaleTimeString("zh", { hour: "2-digit", minute: "2-digit" });
            const full = { ...event.message, time: now };
            setMessages((m) => {
              const idx = m.findIndex((x) => x.message_id === full.message_id);
              if (idx >= 0) {
                const next = m.slice();
                next[idx] = { ...next[idx], ...full, streaming_complete: true };
                return next;
              }
              return [...m, { ...full, streaming_complete: true }];
            });
            setStatus(event.status);
            setSubStatus(event.sub_status || null);
            setView(VIEW_MAP[event.view] || event.view || "chatting");
            setActiveActivity(null);
            setActiveError(null);
            setInputDisabled(false);
            setStreaming(false);
            setAnalysisStream("");
            addLog("info", "sse", `message_completed: ${event.message.message_type}`);
            return;
          }
          case "error":
            setActiveError(event.error);
            setStatus(event.status);
            setSubStatus(event.sub_status || null);
            setView(VIEW_MAP[event.view] || event.view || "input");
            setStreaming(false);
            setInputDisabled(false);
            setActiveActivity(null);
            addLog("error", "sse", `${event.error.error_code}: ${event.error.message}`);
            return;
          default:
            addLog("debug", "sse", `unhandled event: ${name}`);
        }
      },
      [addLog],
    );

    // boot: restore existing session if any
    useEffect(() => {
      let cancelled = false;
      (async () => {
        try {
          const resp = await api.getSession();
          if (cancelled) return;
          const snap = resp.data;
          if (snap.session_id) {
            setSessionId(snap.session_id);
            setStatus(snap.status);
            setSubStatus(snap.sub_status || null);
            setView(VIEW_MAP[snap.view] || "input");
            setSteps(snap.progress_steps || []);
            setMessages((snap.messages || []).map((m) => ({ ...m, streaming_complete: true, time: new Date(m.created_at || Date.now()).toLocaleTimeString("zh", { hour: "2-digit", minute: "2-digit" }) })));
            if (snap.repository) {
              setRepoInput(snap.repository.input_value || "");
              setRepoSummary({
                display: snap.repository.display_name || snap.repository.input_value,
                primary_language: snap.repository.primary_language,
                repo_size_level: snap.repository.repo_size_level,
              });
            }
            if (snap.analysis_mode) setAnalysisMode(snap.analysis_mode);
            if (snap.deep_research_state) setDeepResearch(snap.deep_research_state);
            if (snap.active_error) setActiveError(snap.active_error);
            addLog("info", "boot", `restored session ${snap.session_id} (${snap.status})`);
          } else {
            addLog("info", "boot", "no active session; starting fresh");
          }
        } catch (err) {
          if (!cancelled) addLog("warn", "boot", "GET /api/session failed: " + (err.message || "?"));
        }
      })();
      return () => {
        cancelled = true;
        closeStream();
      };
    }, [addLog, closeStream]);

    const onSubmit = useCallback(
      async (e) => {
        e.preventDefault();
        if (!repoInput.trim()) return;
        addLog("info", "ui", "SUBMIT: " + repoInput + " [" + analysisMode + "]");
        setActiveError(null);
        setSteps([]);
        setAnalysisStream("");
        setDeepResearch(null);
        setMessages([]);
        setView("analyzing");
        setStatus("accessing");
        setInputDisabled(true);
        try {
          const resp = await api.submitRepo(repoInput.trim(), analysisMode);
          const sid = resp.session_id;
          setSessionId(sid);
          if (resp.data && resp.data.repository) {
            setRepoSummary({
              display: resp.data.repository.display_name || resp.data.repository.input_value,
              primary_language: resp.data.repository.primary_language,
              repo_size_level: resp.data.repository.repo_size_level,
            });
          }
          addLog("info", "api", `POST /api/repo → 202 (session ${sid})`);
          closeStream();
          addLog("debug", "sse", `CONNECT /api/analysis/stream?session_id=${sid}`);
          sseCloseRef.current = openStream(
            "analysis",
            sid,
            (name, ev) => handleSseEvent(name, ev),
            (state) => addLog(state === 2 ? "info" : "warn", "sse", `analysis stream state=${state}`),
          );
        } catch (err) {
          const p = err.payload || { error_code: "unknown", message: err.message || "submit failed" };
          setActiveError(p);
          setStatus("access_error");
          setView("input");
          setInputDisabled(false);
          addLog("error", "api", "POST /api/repo failed: " + p.message);
        }
      },
      [repoInput, analysisMode, addLog, handleSseEvent, closeStream],
    );

    const onSend = useCallback(
      async (text) => {
        if (inputDisabled || !sessionId) return;
        const now = new Date().toLocaleTimeString("zh", { hour: "2-digit", minute: "2-digit" });
        setActiveError(null);
        setMessages((m) => [
          ...m,
          {
            message_id: `u_${Date.now()}`,
            role: "user",
            raw_text: text,
            streaming_complete: true,
            time: now,
          },
        ]);
        setInputDisabled(true);
        setSubStatus("agent_thinking");
        setStreaming(true);
        addLog("info", "api", `POST /api/chat (session ${sessionId})`);
        try {
          await api.sendMessage(sessionId, text);
        } catch (err) {
          const p = err.payload || { error_code: "unknown", message: err.message || "send failed" };
          setActiveError(p);
          setInputDisabled(false);
          setStreaming(false);
          setSubStatus("waiting_user");
          addLog("error", "api", "POST /api/chat failed: " + p.message);
          return;
        }
        closeStream();
        addLog("debug", "sse", `CONNECT /api/chat/stream?session_id=${sessionId}`);
        sseCloseRef.current = openStream(
          "chat",
          sessionId,
          (name, ev) => handleSseEvent(name, ev),
          (state) => addLog(state === 2 ? "info" : "warn", "sse", `chat stream state=${state}`),
        );
      },
      [inputDisabled, sessionId, addLog, handleSseEvent, closeStream],
    );

    const onReset = useCallback(
      async () => {
        addLog("info", "ui", "RESET session");
        closeStream();
        if (sessionId) {
          try {
            await api.clearSession(sessionId);
            addLog("info", "api", `DELETE /api/session (${sessionId})`);
          } catch (err) {
            addLog("warn", "api", "DELETE /api/session failed: " + (err.message || "?"));
          }
        }
        setSessionId(null);
        setRepoSummary(null);
        setView("input");
        setStatus("idle");
        setSubStatus(null);
        setMessages([]);
        setSteps([]);
        setAnalysisStream("");
        setActiveActivity(null);
        setActiveError(null);
        setDeepResearch(null);
        setInputDisabled(false);
        setStreaming(false);
      },
      [sessionId, addLog, closeStream],
    );

    const leftRepoInfo = repoSummary ? repoSummary : repoInput ? { display: repoInput } : null;

    return (
      <div style={{ width: "100vw", height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden", background: C.bg, position: "relative" }}>
        {tweaks.scanlines && <div style={{ position: "fixed", inset: 0, zIndex: 9998, pointerEvents: "none", background: "repeating-linear-gradient(0deg,rgba(0,0,0,0.15) 0px,rgba(0,0,0,0.15) 1px,transparent 1px,transparent 3px)" }} />}

        <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
          {tweaks.showLeftPanel && (
            <>
              <div style={{ width: leftW, minWidth: 160, maxWidth: 400, flexShrink: 0 }}>
                <LeftPanel view={view} steps={steps} repo={view !== "input" ? leftRepoInfo : null} status={status} subStatus={subStatus} activeActivity={activeActivity} msgCount={messages.length} deepResearch={deepResearch} />
              </div>
              <Divider onDrag={(dx) => setLeftW((w) => Math.max(160, Math.min(400, w + dx)))} />
            </>
          )}

          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, background: C.bg, overflow: "hidden" }}>
            {view === "chatting" && <ChatHeader repo={repoSummary?.display || repoInput} onReset={onReset} />}
            <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
              <CenterPanel view={view} steps={steps} repoInput={repoInput} setRepoInput={setRepoInput} analysisMode={analysisMode} setAnalysisMode={setAnalysisMode} onSubmit={onSubmit} onSend={onSend} messages={messages} inputDisabled={inputDisabled} streaming={streaming} analysisStream={analysisStream} activeError={activeError} />
            </div>
          </div>

          {tweaks.showRightPanel && (
            <>
              <Divider onDrag={(dx) => setRightW((w) => Math.max(180, Math.min(420, w - dx)))} />
              <div style={{ width: rightW, minWidth: 180, maxWidth: 420, flexShrink: 0 }}>
                <RightPanel view={view} messages={messages} addLog={addLog} />
              </div>
            </>
          )}
        </div>

        <DebugOverlay logs={logs} onClear={() => setLogs([])} />
      </div>
    );
  }

  ns.App = App;
})(window.RTV3);
