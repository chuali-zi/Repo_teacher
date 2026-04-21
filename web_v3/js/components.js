window.RTV3 = window.RTV3 || {};

(function (ns) {
  const { useState, useEffect, useRef, useCallback } = React;
  const { C, FF, glow, textGlow, STEP_LABELS, api } = ns;

  const PxBox = ({ children, accent = false, glow: g = false, style = {}, ...rest }) => (
    <div
      style={{
        border: `1px solid ${accent ? C.teal : C.bdrX}`,
        background: accent ? C.tealV : C.bgE,
        boxShadow: g ? `0 0 12px ${C.tealG},inset 0 0 8px ${C.tealV}` : "none",
        position: "relative",
        ...style,
      }}
      {...rest}
    >
      <div style={{ position: "absolute", top: -1, left: -1, width: 4, height: 4, background: accent ? C.teal : C.bdrX }} />
      <div style={{ position: "absolute", top: -1, right: -1, width: 4, height: 4, background: accent ? C.teal : C.bdrX }} />
      <div style={{ position: "absolute", bottom: -1, left: -1, width: 4, height: 4, background: accent ? C.teal : C.bdrX }} />
      <div style={{ position: "absolute", bottom: -1, right: -1, width: 4, height: 4, background: accent ? C.teal : C.bdrX }} />
      {children}
    </div>
  );

  const PxLabel = ({ children, color = C.inkM, style = {} }) => (
    <span style={{ fontFamily: FF.mono, fontSize: 9, letterSpacing: "0.2em", textTransform: "uppercase", color, ...style }}>
      {children}
    </span>
  );

  // ── Step row ─────────────────────────────────────────────────
  const StepRow = ({ step }) => {
    const st = step.step_state || "pending";
    const stateSymbol = { pending: "[ ]", running: "[>]", done: "[✓]", error: "[!]" };
    const stateColor = { pending: C.inkD, running: C.teal, done: C.ivy, error: C.rust };
    const label = STEP_LABELS[step.step_key] || (step.step_key || "").toUpperCase();
    return (
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "center",
          padding: "5px 8px",
          background: st === "running" ? C.tealV : "transparent",
          borderLeft: `2px solid ${st === "running" ? C.teal : st === "done" ? C.ivy : C.bdrX}`,
          transition: "all 200ms ease",
        }}
      >
        <span
          style={{
            fontFamily: FF.mono,
            fontSize: 11,
            color: stateColor[st] || C.inkD,
            textShadow: st === "running" ? textGlow(C.teal) : st === "done" ? textGlow(C.ivy) : "none",
            minWidth: 30,
          }}
        >
          {stateSymbol[st] || "[ ]"}
        </span>
        <span
          style={{
            fontFamily: FF.mono,
            fontSize: 11,
            color: st === "running" ? C.tealB : st === "done" ? C.inkS : C.inkM,
            letterSpacing: "0.08em",
          }}
        >
          {label}
        </span>
        {st === "running" && (
          <span className="blink" style={{ color: C.teal, fontFamily: FF.mono, fontSize: 11 }}>
            _
          </span>
        )}
      </div>
    );
  };

  // ── LEFT PANEL ───────────────────────────────────────────────
  const LeftPanel = ({ view, steps, repo, status, subStatus, activeActivity, msgCount, deepResearch }) => {
    const statusMap = {
      idle: "IDLE",
      accessing: "ACCESSING",
      analyzing: "ANALYZING",
      chatting: "CHATTING",
      access_error: "ERR:ACCESS",
      analysis_error: "ERR:ANALYSIS",
    };
    const statusColor = { chatting: C.ivy, analyzing: C.teal, accessing: C.blue }[status] || C.inkM;
    const isActive = ["analyzing", "accessing"].includes(status) || ["agent_thinking", "agent_streaming"].includes(subStatus);

    return (
      <div style={{ height: "100%", display: "flex", flexDirection: "column", background: C.bgP, borderRight: `1px solid ${C.bdrX}`, overflow: "hidden" }}>
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 10px", display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ padding: "8px 0 10px", borderBottom: `1px solid ${C.bdrX}`, marginBottom: 2 }}>
            <div style={{ fontFamily: FF.px, fontSize: 9, color: C.teal, textShadow: textGlow(C.teal), letterSpacing: "0.1em", marginBottom: 6 }}>
              REPO TUTOR
            </div>
            <div style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkM, letterSpacing: "0.16em" }}>
              // 阅读间 · AGENT SYS · v3
            </div>
          </div>

          <PxBox accent={isActive} glow={isActive} style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
            <PxLabel>SESSION STATUS</PxLabel>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div
                style={{
                  width: 8,
                  height: 8,
                  background: statusColor,
                  boxShadow: glow(statusColor, 6),
                  animation: isActive ? "pulse 1.4s ease-out infinite" : "none",
                }}
              />
              <span style={{ fontFamily: FF.mono, fontSize: 12, color: statusColor, textShadow: textGlow(statusColor), letterSpacing: "0.1em" }}>
                {statusMap[status] || (status || "").toUpperCase()}
              </span>
            </div>
            {subStatus && (
              <div style={{ fontFamily: FF.mono, fontSize: 10, color: C.blueB, paddingLeft: 16, letterSpacing: "0.06em" }}>
                → {String(subStatus).replace(/_/g, " ").toUpperCase()}
              </div>
            )}
            {repo && (
              <>
                <div style={{ height: 1, background: C.bdrX, margin: "2px 0" }} />
                <PxLabel>REPOSITORY</PxLabel>
                <div style={{ fontFamily: FF.mono, fontSize: 11, color: C.tealB, wordBreak: "break-all", letterSpacing: "0.04em" }}>
                  {repo.display && repo.display.length > 34 ? "…" + repo.display.slice(-32) : repo.display || ""}
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {[repo.primary_language, repo.repo_size_level].filter(Boolean).map((t) => (
                    <span key={t} style={{ fontFamily: FF.mono, fontSize: 9, padding: "2px 6px", border: `1px solid ${C.bdrX}`, color: C.inkM, letterSpacing: "0.08em" }}>
                      {String(t).toUpperCase()}
                    </span>
                  ))}
                </div>
              </>
            )}
          </PxBox>

          {(view === "analyzing" || view === "chatting") && steps.length > 0 && (
            <PxBox style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 4 }}>
              <PxLabel style={{ marginBottom: 4 }}>ANALYSIS PIPELINE</PxLabel>
              {steps.map((s) => (
                <StepRow key={s.step_key} step={s} />
              ))}
            </PxBox>
          )}

          {view === "chatting" && (
            <PxBox style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 7 }}>
              <PxLabel>TEACHING STATE</PxLabel>
              <div style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkM, borderTop: `1px solid ${C.bdrX}`, paddingTop: 6 }}>
                MSG COUNT: {msgCount}
              </div>
            </PxBox>
          )}

          {deepResearch && (
            <PxBox style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 5 }}>
              <PxLabel>DEEP RESEARCH</PxLabel>
              <div style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkS }}>PHASE: {String(deepResearch.phase || "?").toUpperCase()}</div>
              <div style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkM }}>
                {deepResearch.completed_files}/{deepResearch.total_files} files · {(deepResearch.coverage_ratio * 100).toFixed(0)}%
              </div>
              {deepResearch.current_target && (
                <div style={{ fontFamily: FF.mono, fontSize: 9, color: C.blueB, wordBreak: "break-all" }}>
                  ▸ {deepResearch.current_target}
                </div>
              )}
            </PxBox>
          )}

          {isActive && (
            <PxBox accent glow style={{ padding: "10px 10px", display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <PxLabel color={C.teal}>AGENT ACTIVITY</PxLabel>
                <span className="blink" style={{ color: C.teal, fontFamily: FF.mono, fontSize: 11 }}>
                  █
                </span>
              </div>
              <div style={{ fontFamily: FF.mono, fontSize: 11, color: C.tealB, lineHeight: 1.6 }}>
                {activeActivity
                  ? "> " + (activeActivity.summary || "WORKING...")
                  : subStatus === "agent_thinking"
                    ? "> BUILDING PROMPT CONTEXT..."
                    : subStatus === "agent_streaming"
                      ? "> STREAMING OUTPUT..."
                      : "> SCANNING FILE TREE..."}
              </div>
              {activeActivity && activeActivity.tool_name && (
                <div style={{ fontFamily: FF.mono, fontSize: 9, color: C.inkM, letterSpacing: "0.08em" }}>
                  {activeActivity.phase}::{activeActivity.tool_name}
                </div>
              )}
            </PxBox>
          )}
        </div>
      </div>
    );
  };

  // ── CENTER PANEL ─────────────────────────────────────────────
  const CenterPanel = ({ view, steps, repoInput, setRepoInput, analysisMode, setAnalysisMode, onSubmit, onSend, messages, inputDisabled, streaming, analysisStream, activeError }) => {
    const threadRef = useRef(null);
    useEffect(() => {
      if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }, [messages, streaming]);

    if (view === "input")
      return (
        <div style={{ flex: 1, overflowY: "auto", padding: "5vh 48px 48px", display: "flex", flexDirection: "column", gap: 28, maxWidth: 740, margin: "0 auto", width: "100%" }}>
          <div>
            <pre style={{ fontFamily: FF.mono, fontSize: 9, color: C.tealD, lineHeight: 1.4, marginBottom: 16, letterSpacing: "0.06em", userSelect: "none" }}>{`╔══════════════════════════════════════╗
║  REPO TUTOR  //  SOURCE CODE READER  ║
║  VERSION 3.0.0  //  LIVE BACKEND     ║
╚══════════════════════════════════════╝`}</pre>
            <div style={{ fontFamily: FF.mono, fontSize: 13, color: C.inkS, maxWidth: "52ch", lineHeight: 1.8 }}>
              粘贴本地路径或 GitHub 公开仓库 URL。<br />
              <span style={{ color: C.inkM }}>// 我会先观察骨架，再陪你逐层走进去。</span>
            </div>
          </div>

          <PxBox glow style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
            <PxLabel color={C.teal}>INPUT REPOSITORY</PxLabel>
            <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", gap: 0, border: `1px solid ${C.bdrX}`, background: C.bgD }}>
                <span style={{ fontFamily: FF.mono, fontSize: 13, color: C.teal, padding: "10px 10px", borderRight: `1px solid ${C.bdrX}`, userSelect: "none", textShadow: textGlow(C.teal) }}>▶</span>
                <input
                  value={repoInput}
                  onChange={(e) => setRepoInput(e.target.value)}
                  placeholder="C:\path\to\repo  |  https://github.com/owner/repo"
                  style={{ flex: 1, background: "transparent", border: 0, outline: 0, fontFamily: FF.mono, fontSize: 13, color: C.tealB, padding: "10px 12px", caretColor: C.teal }}
                  spellCheck={false}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <div style={{ display: "flex", gap: 14 }}>
                  {[["quick_guide", "Quick guide"], ["deep_research", "Deep research"]].map(([val, label]) => (
                    <label key={val} style={{ display: "flex", alignItems: "center", gap: 7, fontFamily: FF.mono, fontSize: 11, color: C.inkS, cursor: "pointer", letterSpacing: "0.06em" }}>
                      <input type="radio" name="mode" value={val} checked={analysisMode === val} onChange={(e) => setAnalysisMode(e.target.value)} style={{ accentColor: C.teal }} />
                      {label.toUpperCase()}
                    </label>
                  ))}
                </div>
                <PxBtn type="submit" style={{ marginLeft: "auto" }}>
                  START →
                </PxBtn>
              </div>
            </form>
            <div style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkD, borderTop: `1px solid ${C.bdrX}`, paddingTop: 8, lineHeight: 1.6 }}>
              // Python repos: full teaching mode
              <br />
              // Other languages: file-tree overview
            </div>
          </PxBox>

          {activeError && (
            <PxBox style={{ padding: "12px 14px", borderColor: C.rust, display: "flex", flexDirection: "column", gap: 6 }}>
              <PxLabel color={C.rust}>ERROR · {activeError.error_code}</PxLabel>
              <div style={{ fontFamily: FF.mono, fontSize: 12, color: C.rust, lineHeight: 1.6 }}>{activeError.message}</div>
            </PxBox>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <PxLabel>EXAMPLES</PxLabel>
            {["https://github.com/pallets/flask", "https://github.com/tiangolo/fastapi", "C:\\Users\\you\\projects\\demo"].map((ex) => (
              <div
                key={ex}
                onClick={() => setRepoInput(ex)}
                style={{ fontFamily: FF.mono, fontSize: 11, color: C.inkM, padding: "5px 10px", border: `1px solid ${C.bdrX}`, cursor: "pointer", transition: "all 150ms ease", background: C.bgD, letterSpacing: "0.04em" }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = C.teal;
                  e.currentTarget.style.color = C.tealB;
                  e.currentTarget.style.background = C.tealV;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = C.bdrX;
                  e.currentTarget.style.color = C.inkM;
                  e.currentTarget.style.background = C.bgD;
                }}
              >
                {">"} {ex}
              </div>
            ))}
          </div>
        </div>
      );

    if (view === "analyzing")
      return (
        <div style={{ flex: 1, overflowY: "auto", padding: "24px 48px" }}>
          <PxBox glow style={{ maxWidth: 680, margin: "0 auto", padding: "24px 24px 20px", display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <div className="glow-text" style={{ fontFamily: FF.px, fontSize: 10, color: C.teal, letterSpacing: "0.12em", marginBottom: 8 }}>
                ANALYZING
              </div>
              <div style={{ fontFamily: FF.mono, fontSize: 15, color: C.tealB, wordBreak: "break-all", letterSpacing: "0.04em" }}>{repoInput || "owner/repo"}</div>
              <div style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkM, marginTop: 4 }}>// mode: {analysisMode.replace("_", " ")}</div>
            </div>
            <div style={{ height: 1, background: `linear-gradient(90deg,${C.teal},transparent)`, boxShadow: glow(C.teal, 4) }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {steps.map((s) => {
                const st = s.step_state || "pending";
                const label = STEP_LABELS[s.step_key] || (s.step_key || "").toUpperCase();
                return (
                  <div
                    key={s.step_key}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 12px",
                      background: st === "running" ? C.tealV : st === "done" ? "rgba(0,204,136,0.04)" : "transparent",
                      borderLeft: `2px solid ${st === "running" ? C.teal : st === "done" ? C.ivy : st === "error" ? C.rust : C.bdrX}`,
                      transition: "all 200ms ease",
                    }}
                  >
                    <span
                      style={{
                        fontFamily: FF.mono,
                        fontSize: 12,
                        color: st === "running" ? C.teal : st === "done" ? C.ivy : st === "error" ? C.rust : C.inkD,
                        textShadow: st === "running" ? textGlow(C.teal) : st === "done" ? textGlow(C.ivy) : "none",
                        width: 24,
                      }}
                    >
                      {st === "done" ? "[✓]" : st === "running" ? "[>]" : st === "error" ? "[!]" : "[ ]"}
                    </span>
                    <span style={{ fontFamily: FF.mono, fontSize: 12, color: st === "running" ? C.tealB : st === "done" ? C.inkS : C.inkD, letterSpacing: "0.08em" }}>{label}</span>
                    {st === "running" && (
                      <span style={{ marginLeft: "auto", fontFamily: FF.mono, fontSize: 10, color: C.teal }}>
                        RUNNING<span className="blink">_</span>
                      </span>
                    )}
                    {st === "done" && <span style={{ marginLeft: "auto", fontFamily: FF.mono, fontSize: 10, color: C.ivy }}>DONE</span>}
                    {st === "error" && <span style={{ marginLeft: "auto", fontFamily: FF.mono, fontSize: 10, color: C.rust }}>ERROR</span>}
                  </div>
                );
              })}
              {steps.length === 0 && <div style={{ fontFamily: FF.mono, fontSize: 11, color: C.inkM, padding: "10px 4px" }}>// awaiting progress stream...</div>}
            </div>
            {analysisStream && (
              <div style={{ borderTop: `1px solid ${C.bdrX}`, paddingTop: 12 }}>
                <PxLabel color={C.teal} style={{ display: "block", marginBottom: 8 }}>
                  REPORT STREAM
                </PxLabel>
                <div style={{ background: C.bgD, border: `1px solid ${C.bdrX}`, padding: "12px 14px", fontFamily: FF.mono, fontSize: 12, color: C.inkS, lineHeight: 1.8, maxHeight: 260, overflowY: "auto", whiteSpace: "pre-wrap", letterSpacing: "0.02em" }}>
                  {analysisStream}
                  <span className="blink" style={{ color: C.teal }}>
                    █
                  </span>
                </div>
              </div>
            )}
            {activeError && (
              <div style={{ borderTop: `1px solid ${C.rust}`, paddingTop: 12 }}>
                <PxLabel color={C.rust} style={{ display: "block", marginBottom: 6 }}>
                  ERROR · {activeError.error_code}
                </PxLabel>
                <div style={{ fontFamily: FF.mono, fontSize: 12, color: C.rust, lineHeight: 1.6 }}>{activeError.message}</div>
              </div>
            )}
          </PxBox>
        </div>
      );

    // Chat view
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div ref={threadRef} style={{ flex: 1, overflowY: "auto", padding: "20px 32px", display: "flex", flexDirection: "column", gap: 18 }}>
          {messages.map((msg) => (
            <div key={msg.message_id || msg.id} className="fade-up">
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
                <span
                  style={{
                    fontFamily: FF.mono,
                    fontSize: 10,
                    letterSpacing: "0.14em",
                    padding: "2px 8px",
                    border: `1px solid ${msg.role === "user" ? C.blue : C.teal}`,
                    color: msg.role === "user" ? C.blueB : C.teal,
                    background: msg.role === "user" ? C.blueG : C.tealV,
                    textShadow: textGlow(msg.role === "user" ? C.blue : C.teal),
                  }}
                >
                  {msg.role === "user" ? "USER ▶" : "AGENT ◈"}
                </span>
                <span style={{ fontFamily: FF.mono, fontSize: 9, color: C.inkD }}>{msg.time || ""}</span>
                {msg.role === "agent" && msg.streaming_complete && <span style={{ fontFamily: FF.mono, fontSize: 9, color: C.ivy, marginLeft: "auto" }}>// DONE</span>}
              </div>

              {msg.role === "user" ? (
                <div style={{ background: C.bgR, border: `1px solid ${C.blue}`, padding: "12px 16px", boxShadow: `0 0 10px ${C.blueG}`, position: "relative" }}>
                  <span style={{ position: "absolute", top: 8, left: 10, fontFamily: FF.mono, fontSize: 14, color: C.blueD, opacity: 0.6 }}>▶</span>
                  <div style={{ fontFamily: FF.mono, fontSize: 13, color: C.inkS, lineHeight: 1.7, paddingLeft: 20 }}>{msg.raw_text || msg.content || ""}</div>
                </div>
              ) : (
                <PxBox accent={!!msg.streaming_complete} glow={!!msg.streaming_complete} style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ fontFamily: FF.mono, fontSize: 12.5, color: C.ink, lineHeight: 1.8, whiteSpace: "pre-wrap", letterSpacing: "0.02em" }}>
                    {msg.raw_text || msg.content || ""}
                    {!msg.streaming_complete && (
                      <span className="blink" style={{ color: C.teal }}>
                        █
                      </span>
                    )}
                  </div>
                  {msg.error_state && (
                    <div style={{ borderTop: `1px solid ${C.rust}`, paddingTop: 8, fontFamily: FF.mono, fontSize: 11, color: C.rust }}>
                      ! {msg.error_state.error.message}
                    </div>
                  )}
                  {msg.suggestions && msg.suggestions.length > 0 && msg.streaming_complete && (
                    <div style={{ borderTop: `1px solid ${C.bdrX}`, paddingTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {msg.suggestions.map((s) => (
                        <button
                          key={s.suggestion_id || s.text}
                          onClick={() => onSend(s.text)}
                          style={{ background: C.bgD, border: `1px solid ${C.bdrX}`, color: C.inkS, padding: "5px 12px", fontFamily: FF.mono, fontSize: 11, cursor: "pointer", letterSpacing: "0.04em", transition: "all 150ms ease" }}
                          onMouseEnter={(e) => {
                            e.target.style.borderColor = C.teal;
                            e.target.style.color = C.tealB;
                            e.target.style.background = C.tealV;
                            e.target.style.textShadow = textGlow(C.teal);
                          }}
                          onMouseLeave={(e) => {
                            e.target.style.borderColor = C.bdrX;
                            e.target.style.color = C.inkS;
                            e.target.style.background = C.bgD;
                            e.target.style.textShadow = "none";
                          }}
                        >
                          ↳ {s.text}
                        </button>
                      ))}
                    </div>
                  )}
                </PxBox>
              )}
            </div>
          ))}
          {streaming && (
            <div style={{ fontFamily: FF.mono, fontSize: 12, color: C.teal, display: "flex", gap: 8, padding: "4px 0", textShadow: textGlow(C.teal) }}>
              <span>AGENT THINKING</span>
              <span className="blink">▌</span>
            </div>
          )}
          {activeError && (
            <div style={{ border: `1px solid ${C.rust}`, background: C.bgD, padding: "10px 12px", marginTop: 4 }}>
              <PxLabel color={C.rust} style={{ display: "block", marginBottom: 4 }}>
                ERROR · {activeError.error_code}
              </PxLabel>
              <div style={{ fontFamily: FF.mono, fontSize: 11, color: C.rust, lineHeight: 1.6 }}>{activeError.message}</div>
            </div>
          )}
        </div>

        <div style={{ padding: "10px 32px 18px", borderTop: `1px solid ${C.bdrX}`, background: C.bgP }}>
          <PixelComposer onSend={onSend} disabled={inputDisabled} />
        </div>
      </div>
    );
  };

  const PxBtn = ({ children, onClick, type = "button", style = {} }) => (
    <button
      type={type}
      onClick={onClick}
      style={{
        background: C.tealD,
        border: `1px solid ${C.teal}`,
        color: C.bgD,
        fontFamily: FF.mono,
        fontSize: 11,
        padding: "8px 16px",
        cursor: "pointer",
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        boxShadow: glow(C.teal, 6),
        transition: "all 150ms ease",
        ...style,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = C.teal;
        e.currentTarget.style.boxShadow = glow(C.teal, 12);
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = C.tealD;
        e.currentTarget.style.boxShadow = glow(C.teal, 6);
      }}
    >
      {children}
    </button>
  );

  const PixelComposer = ({ onSend, disabled }) => {
    const [val, setVal] = useState("");
    const submit = (e) => {
      e.preventDefault();
      if (val.trim() && !disabled) {
        onSend(val.trim());
        setVal("");
      }
    };
    return (
      <form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
        <div style={{ flex: 1, border: `1px solid ${disabled ? C.bdrX : C.teal}`, background: C.bgD, display: "flex", boxShadow: disabled ? "none" : glow(C.teal, 4), transition: "all 200ms ease" }}>
          <span style={{ fontFamily: FF.mono, fontSize: 12, color: disabled ? C.inkD : C.teal, padding: "10px 10px", borderRight: `1px solid ${C.bdrX}`, userSelect: "none" }}>
            {disabled ? "░" : "▶"}
          </span>
          <textarea
            value={val}
            onChange={(e) => setVal(e.target.value)}
            disabled={disabled}
            rows={1}
            placeholder={disabled ? "// AGENT IS THINKING..." : "// 输入你的问题，或点击上方建议…"}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(e);
              }
            }}
            style={{ flex: 1, background: "transparent", border: 0, outline: 0, resize: "none", fontFamily: FF.mono, color: disabled ? C.inkD : C.tealB, fontSize: 13, padding: "9px 12px", maxHeight: 140, lineHeight: 1.6, caretColor: C.teal }}
          />
        </div>
        <button
          type="submit"
          disabled={!val.trim() || disabled}
          style={{
            background: val.trim() && !disabled ? C.teal : C.bgR,
            border: `1px solid ${val.trim() && !disabled ? C.teal : C.bdrX}`,
            color: val.trim() && !disabled ? C.bgD : C.inkD,
            padding: "10px 14px",
            cursor: val.trim() && !disabled ? "pointer" : "not-allowed",
            fontFamily: FF.mono,
            fontSize: 12,
            letterSpacing: "0.1em",
            boxShadow: val.trim() && !disabled ? glow(C.teal, 6) : "none",
            transition: "all 150ms ease",
          }}
        >
          SEND
        </button>
      </form>
    );
  };

  // ── RIGHT PANEL ──────────────────────────────────────────────
  const RightPanel = ({ view, messages, addLog }) => {
    const [term, setTerm] = useState("");
    const [answer, setAnswer] = useState("");
    const [loading, setLoading] = useState(false);
    const [errMsg, setErrMsg] = useState("");

    const askTerm = async (e) => {
      e.preventDefault();
      if (!term.trim()) return;
      setLoading(true);
      setAnswer("");
      setErrMsg("");
      addLog("info", "api", "POST /api/sidecar/explain");
      try {
        const resp = await api.explainSidecar(term.trim());
        setAnswer(resp.data && resp.data.answer ? resp.data.answer : "// (no answer)");
      } catch (err) {
        setErrMsg((err.payload && err.payload.message) || err.message || "EXPLAIN FAILED");
        addLog("error", "api", "sidecar/explain failed: " + (err.message || "?"));
      }
      setLoading(false);
    };

    const lastAgent = messages.filter((m) => m.role === "agent" && m.streaming_complete).slice(-1)[0];
    const evidenceRefs = (() => {
      if (!lastAgent) return [];
      const refs = new Set();
      const sc = lastAgent.structured_content;
      if (sc && sc.evidence_lines) sc.evidence_lines.forEach((e) => (e.evidence_refs || []).forEach((r) => refs.add(r)));
      const ir = lastAgent.initial_report_content;
      if (ir) {
        (ir.overview?.evidence_refs || []).forEach((r) => refs.add(r));
        (ir.key_directories || []).forEach((d) => (d.evidence_refs || []).forEach((r) => refs.add(r)));
        (ir.entry_section?.entries || []).forEach((e) => (e.evidence_refs || []).forEach((r) => refs.add(r)));
      }
      return Array.from(refs).slice(0, 6);
    })();

    const suggestions = lastAgent && lastAgent.suggestions ? lastAgent.suggestions : [];

    return (
      <div style={{ height: "100%", display: "flex", flexDirection: "column", background: C.bgP, borderLeft: `1px solid ${C.bdrX}`, overflow: "hidden" }}>
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 10px", display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ paddingBottom: 10, borderBottom: `1px dashed ${C.bdrX}` }}>
            <PxLabel color={C.teal}>SIDECAR // 术语解释</PxLabel>
          </div>

          <PxBox glow style={{ padding: "12px 12px", display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontFamily: FF.mono, fontSize: 12, color: C.tealB, lineHeight: 1.6 }}>遇到不懂的词？</div>
            <div style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkM }}>// 输入术语获取简短解释</div>
            <form onSubmit={askTerm} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ border: `1px solid ${C.bdrX}`, background: C.bgD, display: "flex" }}>
                <span style={{ fontFamily: FF.mono, fontSize: 11, color: C.teal, padding: "8px 8px", borderRight: `1px solid ${C.bdrX}`, userSelect: "none" }}>?</span>
                <textarea value={term} onChange={(e) => setTerm(e.target.value)} rows={2} placeholder="DTO, SSE, session_id..." style={{ flex: 1, background: "transparent", border: 0, outline: 0, resize: "none", fontFamily: FF.mono, fontSize: 12, color: C.tealB, padding: "8px 10px", lineHeight: 1.6, caretColor: C.teal }} />
              </div>
              <PxBtn type="submit" style={{ alignSelf: "stretch", justifyContent: "center", textAlign: "center" }}>
                {loading ? "QUERYING..." : "EXPLAIN >>"}
              </PxBtn>
            </form>
            {(loading || answer || errMsg) && (
              <div style={{ border: `1px solid ${errMsg ? C.rust : C.bdrA}`, background: C.bgD, padding: "10px 12px", boxShadow: errMsg ? "none" : `0 0 8px ${C.tealG}` }}>
                <PxLabel color={errMsg ? C.rust : C.teal} style={{ display: "block", marginBottom: 6 }}>
                  {errMsg ? "ERROR" : "OUTPUT"}
                </PxLabel>
                {loading ? (
                  <div style={{ fontFamily: FF.mono, fontSize: 11, color: C.inkM }}>
                    PROCESSING<span className="blink">_</span>
                  </div>
                ) : errMsg ? (
                  <div style={{ fontFamily: FF.mono, fontSize: 11, color: C.rust, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{errMsg}</div>
                ) : (
                  <div style={{ fontFamily: FF.mono, fontSize: 11, color: C.inkS, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{answer}</div>
                )}
              </div>
            )}
          </PxBox>

          {view === "chatting" && suggestions.length > 0 && (
            <PxBox style={{ padding: "10px 10px", display: "flex", flexDirection: "column", gap: 7 }}>
              <PxLabel>RELATED QUERIES</PxLabel>
              {suggestions.map((q) => (
                <div key={q.suggestion_id || q.text} style={{ fontFamily: FF.mono, fontSize: 11, color: C.inkM, padding: "6px 8px", border: `1px solid ${C.bdrX}`, background: C.bgD, lineHeight: 1.5, letterSpacing: "0.02em" }}>
                  ↳ {q.text}
                </div>
              ))}
            </PxBox>
          )}

          {view === "chatting" && evidenceRefs.length > 0 && (
            <PxBox style={{ padding: "10px 10px", display: "flex", flexDirection: "column", gap: 5 }}>
              <PxLabel>EVIDENCE REFS</PxLabel>
              {evidenceRefs.map((f) => (
                <div key={f} style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkM, padding: "4px 8px", borderLeft: `2px solid ${C.tealD}`, background: C.bgD, letterSpacing: "0.02em", wordBreak: "break-all" }}>
                  § {f}
                </div>
              ))}
            </PxBox>
          )}
        </div>
      </div>
    );
  };

  // ── DEBUG LOG (draggable) ────────────────────────────────────
  const DebugOverlay = ({ logs, onClear }) => {
    const [open, setOpen] = useState(false);
    const [pos, setPos] = useState({ x: window.innerWidth - 424, y: 10 });
    const listRef = useRef(null);
    const panelRef = useRef(null);
    const dragging = useRef(false);
    const dragOffset = useRef({ x: 0, y: 0 });

    useEffect(() => {
      if (open && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
    }, [logs, open]);

    const onMouseDown = useCallback(
      (e) => {
        if (e.target.closest("[data-no-drag]")) return;
        dragging.current = true;
        dragOffset.current = { x: e.clientX - pos.x, y: e.clientY - pos.y };
        e.preventDefault();
        const move = (ev) => {
          if (!dragging.current) return;
          const nx = ev.clientX - dragOffset.current.x;
          const ny = ev.clientY - dragOffset.current.y;
          const maxX = window.innerWidth - (panelRef.current?.offsetWidth || 400);
          const maxY = window.innerHeight - (panelRef.current?.offsetHeight || 48);
          setPos({ x: Math.max(0, Math.min(maxX, nx)), y: Math.max(0, Math.min(maxY, ny)) });
        };
        const up = () => {
          dragging.current = false;
          window.removeEventListener("mousemove", move);
          window.removeEventListener("mouseup", up);
        };
        window.addEventListener("mousemove", move);
        window.addEventListener("mouseup", up);
      },
      [pos],
    );

    const errors = logs.filter((l) => l.level === "error").length;
    return (
      <div ref={panelRef} onMouseDown={onMouseDown} style={{ position: "fixed", left: pos.x, top: pos.y, zIndex: 1000, width: 400, userSelect: "none", cursor: "grab", filter: `drop-shadow(0 0 8px ${C.tealG})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "5px 12px", background: C.bgE, border: `1px solid ${open ? C.teal : C.bdrX}`, borderBottom: open ? `1px solid ${C.bdrX}` : "none", boxShadow: open ? glow(C.teal, 4) : "none", transition: "border-color 200ms ease" }}>
          <span style={{ width: 7, height: 7, background: errors > 0 ? C.rust : logs.length > 0 ? C.teal : C.inkD, flexShrink: 0, display: "block", animation: errors > 0 ? "pulse 1.4s ease-out infinite" : "none" }} />
          <span style={{ fontFamily: FF.mono, fontSize: 10, color: C.inkS, letterSpacing: "0.12em", flex: 1 }}>DEBUG LOG</span>
          <span style={{ fontFamily: FF.mono, fontSize: 9, color: C.inkM, padding: "1px 5px", border: `1px solid ${C.bdrX}`, background: C.bgD }}>{logs.length}</span>
          <span style={{ fontFamily: FF.mono, fontSize: 8, color: C.inkD, letterSpacing: "0.06em", padding: "0 4px" }}>⠿</span>
          <button
            data-no-drag
            onClick={() => setOpen((o) => !o)}
            style={{ background: "transparent", border: `1px solid ${C.bdrX}`, color: C.inkM, fontFamily: FF.mono, fontSize: 9, padding: "2px 6px", cursor: "pointer", lineHeight: 1, transition: "all 150ms ease" }}
            onMouseEnter={(e) => {
              e.target.style.borderColor = C.teal;
              e.target.style.color = C.tealB;
            }}
            onMouseLeave={(e) => {
              e.target.style.borderColor = C.bdrX;
              e.target.style.color = C.inkM;
            }}
          >
            {open ? "▲" : "▼"}
          </button>
        </div>
        {open && (
          <div data-no-drag style={{ background: C.bgD, border: `1px solid ${C.teal}`, borderTop: 0, boxShadow: `0 16px 40px -8px rgba(0,0,0,0.9),0 0 20px ${C.tealG}`, overflow: "hidden", cursor: "default" }}>
            <div style={{ display: "flex", gap: 6, padding: "6px 10px", borderBottom: `1px solid ${C.bdrX}`, background: C.bgE }}>
              <button data-no-drag onClick={onClear} style={{ background: "transparent", border: `1px solid ${C.bdrX}`, color: C.inkM, fontSize: 10, padding: "2px 8px", fontFamily: FF.mono, cursor: "pointer", letterSpacing: "0.08em" }}>
                CLEAR
              </button>
              <button data-no-drag onClick={() => navigator.clipboard?.writeText(logs.map((l) => `[${l.t}][${l.level.toUpperCase()}][${l.src}] ${l.msg}`).join("\n"))} style={{ background: "transparent", border: `1px solid ${C.bdrX}`, color: C.inkM, fontSize: 10, padding: "2px 8px", fontFamily: FF.mono, cursor: "pointer", letterSpacing: "0.08em" }}>
                COPY ALL
              </button>
              <span style={{ marginLeft: "auto", fontFamily: FF.mono, fontSize: 9, color: C.inkD, alignSelf: "center" }}>// DEBUG CONSOLE</span>
            </div>
            <ul ref={listRef} style={{ listStyle: "none", maxHeight: 280, overflowY: "auto" }}>
              {logs.length === 0 && <li style={{ padding: "12px 10px", color: C.inkD, fontFamily: FF.mono, fontSize: 11, fontStyle: "italic" }}>// no logs yet</li>}
              {logs.map((l) => (
                <li key={l.id} style={{ borderBottom: `1px solid ${C.bdrX}`, padding: "6px 10px" }}>
                  <div style={{ display: "flex", gap: 6, marginBottom: 3, fontFamily: FF.mono, fontSize: 9 }}>
                    <span style={{ color: C.inkD }}>{l.t}</span>
                    <span style={{ color: { error: C.rust, warn: C.amber, info: C.teal, debug: C.blue }[l.level] || C.inkM, textShadow: textGlow({ error: C.rust, warn: C.amber, info: C.teal, debug: C.blue }[l.level] || C.inkM) }}>{l.level.toUpperCase()}</span>
                    <span style={{ color: C.blueB }}>{l.src}</span>
                  </div>
                  <div style={{ color: C.inkS, fontFamily: FF.mono, fontSize: 11, whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.6 }}>{l.msg}</div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  };

  // ── DRAG DIVIDER ─────────────────────────────────────────────
  const Divider = ({ onDrag }) => {
    const dragging = useRef(false);
    const onMouseDown = useCallback(
      (e) => {
        dragging.current = true;
        e.preventDefault();
        const move = (ev) => {
          if (dragging.current) onDrag(ev.movementX);
        };
        const up = () => {
          dragging.current = false;
          window.removeEventListener("mousemove", move);
          window.removeEventListener("mouseup", up);
        };
        window.addEventListener("mousemove", move);
        window.addEventListener("mouseup", up);
      },
      [onDrag],
    );
    return (
      <div onMouseDown={onMouseDown} style={{ width: 5, cursor: "col-resize", background: "transparent", flexShrink: 0, position: "relative", zIndex: 10, transition: "background 200ms ease" }} onMouseEnter={(e) => (e.currentTarget.style.background = C.tealV)} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
        <div style={{ position: "absolute", top: 0, bottom: 0, left: "50%", width: 1, background: `repeating-linear-gradient(180deg,${C.bdrX} 0px,${C.bdrX} 4px,transparent 4px,transparent 8px)` }} />
      </div>
    );
  };

  // ── CHAT HEADER ──────────────────────────────────────────────
  const ChatHeader = ({ repo, onReset }) => (
    <div style={{ padding: "10px 32px", borderBottom: `1px solid ${C.bdrX}`, display: "flex", alignItems: "center", gap: 16, background: C.bgP, flexShrink: 0 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <PxLabel style={{ display: "block", marginBottom: 4 }}>REPO TUTOR // CHATTING</PxLabel>
        <div style={{ fontFamily: FF.mono, fontSize: 13, color: C.tealB, wordBreak: "break-all", letterSpacing: "0.04em", textShadow: textGlow(C.teal) }}>{repo}</div>
      </div>
      <button
        onClick={onReset}
        style={{ background: "transparent", border: `1px solid ${C.bdrX}`, color: C.inkM, padding: "6px 14px", fontFamily: FF.mono, fontSize: 10, cursor: "pointer", letterSpacing: "0.1em", flexShrink: 0, transition: "all 150ms ease" }}
        onMouseEnter={(e) => {
          e.target.style.borderColor = C.teal;
          e.target.style.color = C.tealB;
        }}
        onMouseLeave={(e) => {
          e.target.style.borderColor = C.bdrX;
          e.target.style.color = C.inkM;
        }}
      >
        [SWITCH REPO]
      </button>
    </div>
  );

  ns.PxBox = PxBox;
  ns.PxLabel = PxLabel;
  ns.StepRow = StepRow;
  ns.LeftPanel = LeftPanel;
  ns.CenterPanel = CenterPanel;
  ns.PxBtn = PxBtn;
  ns.PixelComposer = PixelComposer;
  ns.RightPanel = RightPanel;
  ns.DebugOverlay = DebugOverlay;
  ns.Divider = Divider;
  ns.ChatHeader = ChatHeader;
})(window.RTV3);
