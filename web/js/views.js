// View rendering. State-driven, with a thin diff: we re-render only the active view
// when its inputs change. Streaming text bubbles update by mutating textContent,
// not re-rendering the whole thread, so it stays buttery smooth.

import { el, frag, clone, clear, $ } from "./dom.js";
import { getState, subscribe, setState, appendMessage, applySessionSnapshot } from "./state.js";
import { api, openStream } from "./api.js";
import { report } from "./errors.js";
import { bus } from "./plugins.js";

let stageBody, stageHead, stageTitle, stageActions, stageFoot;
let lastView = null;
let lastSubStatus = null;
let activeStreamCloser = null;
let chatStreamCloser = null;
let analysisStreamCloser = null;
let lastSessionId = null;

const STEP_LABELS = {
  repo_access: "仓库接入",
  file_tree_scan: "文件树扫描",
  entry_and_module_analysis: "入口与模块分析",
  dependency_analysis: "依赖来源分析",
  skeleton_assembly: "教学骨架组装",
  initial_report_generation: "首轮报告生成",
};

const STATUS_LABELS = {
  idle: "静候输入",
  accessing: "接入仓库",
  analyzing: "正在分析",
  chatting: "教学中",
  access_error: "接入失败",
  analysis_error: "分析失败",
};

const SUB_STATUS_LABELS = {
  waiting_user: "等待你的下一步",
  agent_thinking: "Agent 正在思考…",
  agent_streaming: "Agent 正在书写…",
};

export function initViews() {
  stageBody = $("#stage-body");
  stageHead = $("#stage-head");
  stageTitle = $("#stage-title");
  stageActions = $("#stage-actions");
  stageFoot = $("#stage-foot");

  subscribe(render);
}

function render(state) {
  // sidebar bits
  renderSidebar(state);
  renderTitle(state);
  renderActions(state);

  // session changes → reset stream wiring
  if (state.sessionId !== lastSessionId) {
    closeAllStreams();
    lastSessionId = state.sessionId;
  }

  // wire streams when applicable
  ensureStreams(state);

  // view switch
  if (state.view !== lastView) {
    bus.emit("view:change", { from: lastView, to: state.view });
    lastView = state.view;
    mountView(state);
  } else {
    updateView(state);
  }

  // sub-status thinking signal
  if (state.subStatus !== lastSubStatus) {
    if (state.subStatus === "agent_thinking") bus.emit("thinking:start", {});
    else bus.emit("thinking:stop", {});
    lastSubStatus = state.subStatus;
  }
}

function closeAllStreams() {
  if (activeStreamCloser) { try { activeStreamCloser(); } catch {} activeStreamCloser = null; }
  if (chatStreamCloser) { try { chatStreamCloser(); } catch {} chatStreamCloser = null; }
  if (analysisStreamCloser) { try { analysisStreamCloser(); } catch {} analysisStreamCloser = null; }
}

function ensureStreams(state) {
  if (!state.sessionId) return;
  if ((state.status === "accessing" || state.status === "analyzing") && !analysisStreamCloser) {
    analysisStreamCloser = openStream("analysis", state.sessionId, (evt) => handleSseEvent("analysis", evt));
    report({ source: "sse", level: "info", message: "已连接分析流", where: "/api/analysis/stream" });
  }
  if (state.status === "chatting" && state.subStatus !== "waiting_user" && !chatStreamCloser) {
    chatStreamCloser = openStream("chat", state.sessionId, (evt) => handleSseEvent("chat", evt));
    report({ source: "sse", level: "info", message: "已连接聊天流", where: "/api/chat/stream" });
  }
}

function handleSseEvent(kind, evt) {
  bus.emit("sse:event", { kind, evt });
  const st = getState();
  if (st.sessionId && evt.session_id && evt.session_id !== st.sessionId) {
    report({ source: "sse", level: "warn", message: "丢弃旧会话事件", where: `${evt.event_type}` , raw: evt });
    return;
  }

  switch (evt.event_type) {
    case "status_changed":
      setState({ status: evt.status, subStatus: evt.sub_status, view: evt.view });
      break;

    case "analysis_progress":
      setState({ progressSteps: evt.progress_steps });
      // user_notice as transient toast
      if (evt.user_notice) report({ source: "analysis", level: "info", message: evt.user_notice, where: evt.step_key });
      break;

    case "degradation_notice":
      setState((s) => ({ degradationNotices: [...s.degradationNotices, evt.degradation] }));
      report({ source: "analysis", level: "warn", message: `降级：${evt.degradation.user_notice}`, where: evt.degradation.type });
      break;

    case "answer_stream_start": {
      // synthesize a temporary message
      const placeholder = {
        message_id: evt.message_id,
        role: "agent",
        message_type: evt.message_type,
        created_at: evt.occurred_at,
        raw_text: "",
        structured_content: null,
        initial_report_content: null,
        related_goal: null,
        suggestions: [],
        streaming_complete: false,
        error_state: null,
        _streaming: true,
      };
      appendMessage(placeholder);
      bus.emit("stream:start", { messageId: evt.message_id, kind, type: evt.message_type });
      break;
    }

    case "answer_stream_delta": {
      // Mutate streaming bubble in place — don't re-render the thread.
      const node = document.querySelector(`[data-stream-id="${evt.message_id}"]`);
      if (node) {
        node.textContent += evt.delta_text || "";
        const stage = $("#stage-body");
        if (stage) stage.scrollTop = stage.scrollHeight;
      } else {
        // fallback: still update in-state so a later render shows it
        setState((s) => ({
          messages: s.messages.map((m) =>
            m.message_id === evt.message_id ? { ...m, raw_text: (m.raw_text || "") + (evt.delta_text || "") } : m,
          ),
        }));
      }
      bus.emit("stream:delta", { messageId: evt.message_id, delta: evt.delta_text });
      break;
    }

    case "answer_stream_end":
      bus.emit("stream:end", { messageId: evt.message_id });
      break;

    case "message_completed":
      // Replace placeholder with full structured message
      appendMessage({ ...evt.message, _streaming: false });
      setState({ status: evt.status, subStatus: evt.sub_status, view: evt.view });
      bus.emit("message:append", evt.message);
      // close stream after initial report
      if (evt.message.message_type === "initial_report") {
        if (analysisStreamCloser) { analysisStreamCloser(); analysisStreamCloser = null; }
      }
      // close chat stream when user-input is again expected
      if (evt.sub_status === "waiting_user" && chatStreamCloser) {
        chatStreamCloser();
        chatStreamCloser = null;
      }
      break;

    case "error":
      setState({ status: evt.status, subStatus: evt.sub_status, view: evt.view, activeError: evt.error });
      report({ source: kind, level: "error", message: `${evt.error.error_code}: ${evt.error.message}`, where: `stage=${evt.error.stage}`, raw: evt.error });
      bus.emit("error:user", evt.error);
      // close failed stream
      if (kind === "analysis" && analysisStreamCloser) { analysisStreamCloser(); analysisStreamCloser = null; }
      if (kind === "chat" && chatStreamCloser) { chatStreamCloser(); chatStreamCloser = null; }
      break;
  }
}

// ---------- sidebar / header ----------

function renderSidebar(state) {
  const repoPanel = $("#repo-panel");
  const repoSummary = $("#repo-summary");
  if (state.repository) {
    repoPanel.hidden = false;
    clear(repoSummary);
    repoSummary.appendChild(renderRepoSummary(state.repository));
  } else {
    repoPanel.hidden = true;
    clear(repoSummary);
  }

  const progressPanel = $("#progress-panel");
  const stepsList = $("#progress-steps");
  if (state.progressSteps.length > 0 && (state.status === "accessing" || state.status === "analyzing" || state.view === "analysis")) {
    progressPanel.hidden = false;
    clear(stepsList);
    for (const step of state.progressSteps) stepsList.appendChild(renderStep(step));
  } else {
    progressPanel.hidden = true;
  }

  const degPanel = $("#degradation-panel");
  const degList = $("#degradation-list");
  if (state.degradationNotices.length > 0) {
    degPanel.hidden = false;
    clear(degList);
    for (const d of state.degradationNotices) {
      degList.appendChild(el("li", { class: "notice" },
        el("strong", null, degLabel(d.type)),
        el("span", null, d.user_notice),
      ));
    }
  } else {
    degPanel.hidden = true;
  }
}

function degLabel(t) {
  switch (t) {
    case "large_repo": return "大仓库";
    case "non_python_repo": return "非 Python";
    case "entry_not_found": return "入口未知";
    case "flow_not_reliable": return "流程不可靠";
    case "layer_not_reliable": return "分层不可靠";
    case "analysis_timeout": return "分析超时";
    default: return t;
  }
}

function renderRepoSummary(repo) {
  const meta = el("div", { class: "repo-meta" });
  if (repo.primary_language) meta.appendChild(el("span", null, repo.primary_language));
  if (repo.repo_size_level) meta.appendChild(el("span", null, repo.repo_size_level));
  if (repo.source_code_file_count != null) meta.appendChild(el("span", null, `${repo.source_code_file_count} files`));
  return frag(
    el("div", { class: "repo-name" }, repo.display_name),
    meta,
    el("div", { class: "repo-source" }, repo.input_value),
  );
}

function renderStep(step) {
  return el("li", { class: "step", dataset: { state: step.step_state } },
    el("span", { class: "step__icon" }),
    el("span", { class: "step__label" }, STEP_LABELS[step.step_key] || step.step_key),
    el("span", { class: "step__hint" }, step.step_state),
  );
}

function renderTitle(state) {
  clear(stageTitle);
  const eye = el("span", { class: "stage__eyebrow" }, statusEyebrow(state));
  const heading = el("h2", null, statusHeading(state));
  stageTitle.appendChild(eye);
  stageTitle.appendChild(heading);
}

function statusEyebrow(state) {
  if (state.status === "chatting") return state.subStatus === "agent_thinking" ? "AGENT THINKING" : "CONVERSATION";
  return STATUS_LABELS[state.status] || state.status;
}
function statusHeading(state) {
  if (state.repository) return state.repository.display_name;
  if (state.status === "idle") return "静候输入";
  if (state.status === "access_error" || state.status === "analysis_error") return "出错了，请再试一次";
  return STATUS_LABELS[state.status] || "—";
}

function renderActions(state) {
  clear(stageActions);
  if (state.sessionId && (state.status === "chatting" || state.status === "analyzing")) {
    const btn = el("button", {
      class: "btn-ghost",
      type: "button",
      onclick: handleSwitchRepo,
    }, "切换仓库");
    stageActions.appendChild(btn);
  }
}

async function handleSwitchRepo() {
  const st = getState();
  if (!st.sessionId) return;
  if (!confirm("切换仓库会清空当前会话和所有进度，确定要继续吗？")) return;
  try {
    await api.clearSession(st.sessionId);
    closeAllStreams();
    const snap = await api.getSession();
    if (snap && snap.data) {

      applySessionSnapshot(snap.data);
    }
  } catch (err) {
    report({ source: "ui", level: "error", message: "切换仓库失败", where: "handleSwitchRepo", error: err });
  }
}

// ---------- view mounting ----------

function mountView(state) {
  clear(stageBody);
  switch (state.view) {
    case "input":
      stageBody.appendChild(renderInputView(state));
      stageFoot.hidden = true;
      clear(stageFoot);
      break;
    case "analysis":
      stageBody.appendChild(renderAnalysisView(state));
      stageFoot.hidden = true;
      clear(stageFoot);
      break;
    case "chat":
      stageBody.appendChild(renderChatView(state));
      mountChatComposer(state);
      stageFoot.hidden = false;
      break;
  }
}

function updateView(state) {
  // For input + analysis view, we rebuild (small DOM, no harm).
  // For chat view, we use targeted updates so streaming stays smooth.
  if (state.view === "chat") {
    updateThread(state);
    updateChatComposer(state);
  } else {
    mountView(state);
  }
}

// ---------- INPUT VIEW ----------

function renderInputView(state) {
  const root = clone("tmpl-input-view");
  const form = root.querySelector("#repo-form");
  const input = root.querySelector("#repo-input");
  const btn = root.querySelector("#repo-submit");
  const hint = root.querySelector("#repo-hint");

  if (state.activeError) {
    hint.textContent = `${state.activeError.message}`;
    hint.dataset.tone = "error";
  }

  // examples click
  for (const code of root.querySelectorAll("#repo-examples code")) {
    code.addEventListener("click", () => { input.value = code.textContent; input.focus(); });
  }

  let validateTimer = null;
  let lastValidated = "";
  let submitting = false;

  const setHint = (text, tone) => {
    hint.textContent = text;
    if (tone) hint.dataset.tone = tone;
    else delete hint.dataset.tone;
  };

  const debouncedValidate = (value) => {
    clearTimeout(validateTimer);
    if (!value.trim()) {
      setHint("支持 Python 仓库完整教学；其他语言提供基础结构概览。", null);
      btn.disabled = true;
      return;
    }
    validateTimer = setTimeout(async () => {
      if (value === lastValidated) return;
      lastValidated = value;
      try {
        const res = await api.validateRepo(value);
        if (!res.data.is_valid) {
          setHint(res.data.message || "格式不合法", "error");
          btn.disabled = true;
        } else {
          setHint(`格式合法 · ${res.data.input_kind === "github_url" ? "GitHub 仓库" : "本地路径"}`, "ok");
          btn.disabled = false;
        }
      } catch (err) {
        setHint("校验失败，请检查后端是否启动", "error");
        btn.disabled = true;
      }
    }, 220);
  };

  input.addEventListener("input", (e) => debouncedValidate(e.target.value));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (submitting) return;
    const value = input.value.trim();
    if (!value) return;
    submitting = true;
    btn.disabled = true;
    btn.querySelector("span").textContent = "提交中…";
    try {
      const res = await api.submitRepo(value);

      // Hydrate immediate state from submit response
      setState({
        sessionId: res.session_id,
        status: res.data.status,
        subStatus: res.data.sub_status,
        view: res.data.view,
        repository: res.data.repository,
        activeError: null,
        progressSteps: [
          { step_key: "repo_access", step_state: "running" },
          { step_key: "file_tree_scan", step_state: "pending" },
          { step_key: "entry_and_module_analysis", step_state: "pending" },
          { step_key: "dependency_analysis", step_state: "pending" },
          { step_key: "skeleton_assembly", step_state: "pending" },
          { step_key: "initial_report_generation", step_state: "pending" },
        ],
        degradationNotices: [],
        messages: [],
      });
    } catch (err) {
      const message = (err.payload && err.payload.message) || err.message || "提交失败";
      setHint(message, "error");
      btn.disabled = false;
      btn.querySelector("span").textContent = "开始阅读";
    } finally {
      submitting = false;
    }
  });

  // restore last input value
  if (state.activeError && state.activeError.input_preserved) {
    // input value not preserved across reloads, that's fine
  }

  return root;
}

// ---------- ANALYSIS VIEW ----------

function renderAnalysisView(state) {
  const root = clone("tmpl-analysis-view");
  $("#analysis-repo", root).textContent = state.repository?.display_name || "—";

  const stepsRoot = $("#analysis-steps", root);
  for (const step of (state.progressSteps.length ? state.progressSteps : defaultSteps())) {
    stepsRoot.appendChild(renderStep(step));
  }

  const noticesRoot = $("#analysis-notices", root);
  for (const d of state.degradationNotices) {
    noticesRoot.appendChild(el("div", { class: "notice" },
      el("strong", null, degLabel(d.type)),
      el("span", null, d.user_notice),
    ));
  }

  // Live streaming preview area: shows raw_text from initial_report streaming msg
  const streamMsg = state.messages.find((m) => m._streaming || (m.message_type === "initial_report" && !m.streaming_complete));
  if (streamMsg) {
    const streamCard = $("#analysis-stream", root);
    streamCard.hidden = false;
    const pre = $("#analysis-stream-text", root);
    pre.textContent = streamMsg.raw_text || "(等待 LLM 输出…)";
    pre.dataset.streamId = streamMsg.message_id; // delta handler attaches here
  }

  return root;
}

function defaultSteps() {
  return Object.keys(STEP_LABELS).map((k) => ({ step_key: k, step_state: "pending" }));
}

// ---------- CHAT VIEW ----------

function renderChatView(state) {
  const root = clone("tmpl-chat-view");
  const thread = $("#thread", root);
  for (const msg of state.messages) thread.appendChild(renderMessage(msg));
  if (state.subStatus === "agent_thinking") thread.appendChild(renderThinking());
  return root;
}

function updateThread(state) {
  const thread = document.getElementById("thread");
  if (!thread) return;

  // Build a map of currently rendered messages by id
  const present = new Map();
  for (const node of Array.from(thread.children)) {
    if (node.dataset && node.dataset.msgId) present.set(node.dataset.msgId, node);
  }

  const seen = new Set();
  let lastNode = null;
  for (const msg of state.messages) {
    seen.add(msg.message_id);
    const existing = present.get(msg.message_id);
    if (existing) {
      // Replace if streaming → final transition
      const wasStreaming = existing.dataset.streaming === "true";
      const nowStreaming = !!msg._streaming;
      if (wasStreaming && !nowStreaming) {
        const fresh = renderMessage(msg);
        existing.replaceWith(fresh);
        lastNode = fresh;
      } else if (!nowStreaming && msg.message_type === "user_question") {
        // user messages don't change after creation
        lastNode = existing;
      } else {
        lastNode = existing;
      }
    } else {
      const node = renderMessage(msg);
      if (lastNode && lastNode.nextSibling) thread.insertBefore(node, lastNode.nextSibling);
      else thread.appendChild(node);
      lastNode = node;
    }
  }

  // Remove messages no longer present
  for (const [id, node] of present.entries()) {
    if (!seen.has(id) && !node.classList.contains("thinking")) node.remove();
  }

  // Thinking indicator
  const existingThinking = thread.querySelector(".thinking-row");
  if (state.subStatus === "agent_thinking") {
    if (!existingThinking) thread.appendChild(renderThinking());
  } else if (existingThinking) {
    existingThinking.remove();
  }

  // Auto-scroll if user is near the bottom
  const stage = document.getElementById("stage-body");
  if (stage) {
    const nearBottom = stage.scrollHeight - stage.scrollTop - stage.clientHeight < 240;
    if (nearBottom) stage.scrollTop = stage.scrollHeight;
  }
}

function renderThinking() {
  return el("div", { class: "thinking-row", dataset: { msgId: "__thinking__" } },
    el("div", { class: "thinking" },
      "Agent 正在思考",
      el("span", { class: "thinking__dots" },
        el("span"), el("span"), el("span"),
      ),
    ),
  );
}

function renderMessage(msg) {
  const wrap = el("div", { class: `msg msg--${msg.role}`, dataset: { msgId: msg.message_id, streaming: msg._streaming ? "true" : "false" } });
  wrap.appendChild(renderMessageHead(msg));
  if (msg.role === "user") {
    wrap.appendChild(el("div", { class: "bubble bubble--user" }, msg.raw_text || ""));
  } else if (msg.message_type === "error" || msg.error_state) {
    wrap.appendChild(renderErrorBubble(msg));
  } else if (msg._streaming || (!msg.streaming_complete && !msg.structured_content && !msg.initial_report_content)) {
    // streaming: just show the live text, will be replaced when message_completed arrives
    wrap.appendChild(el("pre", { class: "bubble bubble--stream", dataset: { streamId: msg.message_id } }, msg.raw_text || ""));
  } else if (msg.message_type === "initial_report" && msg.initial_report_content) {
    wrap.appendChild(renderInitialReport(msg));
  } else if (msg.structured_content) {
    wrap.appendChild(renderStructuredAnswer(msg));
  } else {
    // final fallback — show raw text
    wrap.appendChild(el("div", { class: "bubble" }, msg.raw_text || "(无内容)"));
  }
  bus.emit("message:render", { msg, root: wrap });
  return wrap;
}

function renderMessageHead(msg) {
  const roleLabel = msg.role === "user" ? "你" : msg.role === "agent" ? msg.message_type === "initial_report" ? "Agent · 首轮报告" : msg.message_type === "stage_summary" ? "Agent · 阶段总结" : msg.message_type === "goal_switch_confirmation" ? "Agent · 目标切换" : "Agent" : "系统";
  return el("div", { class: "msg__head" },
    el("span", { class: "msg__role" }, roleLabel),
    el("span", { class: "msg__time" }, formatTimestamp(msg.created_at)),
  );
}

function formatTimestamp(s) {
  if (!s) return "";
  try {
    const d = new Date(s);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch { return ""; }
}

function renderErrorBubble(msg) {
  const err = msg.error_state?.error || { message: msg.raw_text || "未知错误", error_code: "unknown" };
  return el("div", { class: "bubble bubble--error" },
    el("h4", null, `${err.error_code}`),
    el("p", null, err.message),
    msg.error_state?.partial_text_available && el("pre", { class: "bubble--stream", style: { marginTop: "8px" } }, msg.raw_text || ""),
  );
}

// ---------- structured answer (six sections) ----------

function renderStructuredAnswer(msg) {
  const sc = msg.structured_content;
  const wrap = el("div", { class: "bubble" });
  const inner = el("div", { class: "answer" });
  if (sc.focus) inner.appendChild(el("div", { class: "answer__focus" }, sc.focus));
  if (sc.direct_explanation) {
    inner.appendChild(renderSection("DIRECT EXPLANATION",
      el("div", { class: "answer__direct" }, sc.direct_explanation),
    ));
  }
  if (sc.relation_to_overall) {
    inner.appendChild(renderSection("RELATION TO OVERALL",
      el("div", { class: "answer__relation" }, sc.relation_to_overall),
    ));
  }
  if (Array.isArray(sc.evidence_lines) && sc.evidence_lines.length) {
    const list = el("ul", { class: "evidence-list" });
    for (const ev of sc.evidence_lines) {
      list.appendChild(el("li", null,
        el("div", null,
          ev.text,
          ev.confidence && confidenceTag(ev.confidence),
          renderRefs(ev.evidence_refs),
        ),
      ));
    }
    inner.appendChild(renderSection("EVIDENCE", list));
  }
  if (Array.isArray(sc.uncertainties) && sc.uncertainties.length) {
    const ul = el("ul", { class: "uncertainty-list" });
    for (const u of sc.uncertainties) ul.appendChild(el("li", null, u));
    inner.appendChild(renderSection("UNCERTAINTIES", ul));
  }
  if (Array.isArray(sc.next_steps) && sc.next_steps.length) {
    inner.appendChild(renderSection("NEXT STEPS", renderSuggestions(sc.next_steps)));
  }
  wrap.appendChild(inner);
  return wrap;
}

function renderSection(label, body) {
  return el("div", { class: "answer__section" },
    el("div", { class: "answer__label" }, label),
    body,
  );
}

function renderRefs(refs) {
  if (!refs || refs.length === 0) return null;
  const c = el("div", { class: "evidence-refs" });
  for (const r of refs) c.appendChild(el("code", null, r));
  return c;
}

function confidenceTag(level) {
  return el("span", { class: `tag tag--${level}` }, level);
}

function renderSuggestions(list) {
  const wrap = el("div", { class: "suggestions" });
  for (const s of list) {
    const btn = el("button", {
      type: "button",
      class: "suggestion",
      onclick: () => sendMessageNow(s.text),
    }, s.text);
    wrap.appendChild(btn);
  }
  return wrap;
}

async function sendMessageNow(text) {
  const st = getState();
  if (!st.sessionId) return;
  if (st.status !== "chatting" || st.subStatus !== "waiting_user") return;
  // Optimistic: append user message immediately
  appendMessage({
    message_id: `local-${Date.now()}`,
    role: "user",
    message_type: "user_question",
    created_at: new Date().toISOString(),
    raw_text: text,
    structured_content: null,
    initial_report_content: null,
    related_goal: null,
    suggestions: [],
    streaming_complete: true,
    error_state: null,
  });
  setState({ subStatus: "agent_thinking" });
  try {
    await api.sendMessage(st.sessionId, text);
    // Open chat stream now (renderer will too on next tick — duplicate-safe because of guard)
    if (!chatStreamCloser) chatStreamCloser = openStream("chat", st.sessionId, (evt) => handleSseEvent("chat", evt));
  } catch (err) {
    report({ source: "ui", level: "error", message: "发送消息失败", where: "sendMessageNow", error: err });
    setState({ subStatus: "waiting_user" });
  }
}

// ---------- initial report ----------

function renderInitialReport(msg) {
  const c = msg.initial_report_content;
  const wrap = el("div", { class: "bubble" });
  const root = el("article", { class: "report" });

  // 1. overview
  root.appendChild(renderReportSection("仓库概览",
    el("div", { class: "report__overview" },
      el("p", null, c.overview.summary, " ", confidenceTag(c.overview.confidence)),
    ),
  ));

  // 2. focus points
  if (c.focus_points?.length) {
    const grid = el("div", { class: "focus-grid" });
    for (const fp of c.focus_points) {
      grid.appendChild(el("div", { class: "focus-card" },
        el("h5", null, fp.title),
        el("p", null, fp.reason),
        el("span", null, fp.topic),
      ));
    }
    root.appendChild(renderReportSection("先抓什么", grid));
  }

  // 3. mapping
  if (c.repo_mapping?.length) {
    const list = el("ul", { class: "mapping-list" });
    for (const m of c.repo_mapping) {
      list.appendChild(el("li", { class: "mapping-row" },
        el("div", { class: "mapping-concept" }, m.concept),
        el("div", { class: "mapping-body" },
          m.explanation,
          confidenceTag(m.confidence),
          renderRefs(m.evidence_refs),
        ),
      ));
    }
    root.appendChild(renderReportSection("当前仓库映射", list));
  }

  // 4. language and type
  if (c.language_and_type) {
    const lt = c.language_and_type;
    const row = el("div", { class: "lang-row" },
      el("span", { class: "lang-pill" }, lt.primary_language || "未知语言"),
      el("div", { class: "lang-types" },
        ...(lt.project_types || []).map((p) =>
          el("span", null, `${p.type} `, confidenceTag(p.confidence)),
        ),
      ),
    );
    const sect = renderReportSection("语言与项目类型", row);
    if (lt.degradation_notice) sect.appendChild(el("div", { class: "notice", style: { marginTop: "6px" } }, lt.degradation_notice));
    root.appendChild(sect);
  }

  // 5. key directories
  if (c.key_directories?.length) {
    const list = el("ul", { class: "keydir-list" });
    for (const kd of c.key_directories) {
      list.appendChild(el("li", { class: "keydir-row", dataset: { role: kd.main_path_role } },
        el("div", null,
          el("div", { class: "keydir-path" }, kd.path),
          el("div", { class: "keydir-role" }, kd.role),
        ),
        el("div", { class: "keydir-meta" },
          el("span", null, kd.main_path_role),
          confidenceTag(kd.confidence),
        ),
      ));
    }
    root.appendChild(renderReportSection("关键目录", list));
  }

  // 6. entry candidates
  const ent = c.entry_section;
  if (ent) {
    const list = el("ul", { class: "entry-list" });
    if (ent.entries?.length) {
      for (const e of ent.entries) {
        list.appendChild(el("li", { class: "entry-row", dataset: { rank: String(e.rank) } },
          el("div", { class: "entry-target" },
            el("small", null, `#${e.rank} ${e.target_type}`),
            e.target_value,
            confidenceTag(e.confidence),
          ),
          el("div", { class: "entry-reason" }, e.reason),
          renderRefs(e.evidence_refs),
        ));
      }
    } else {
      list.appendChild(el("li", { class: "unknown-row" }, ent.fallback_advice || "未找到可靠入口候选"));
    }
    const sect = renderReportSection(`入口候选（${ent.status}）`, list);
    root.appendChild(sect);
  }

  // 7. recommended first step
  if (c.recommended_first_step) {
    const fs = c.recommended_first_step;
    root.appendChild(renderReportSection("推荐第一步",
      el("div", { class: "first-step" },
        el("div", { class: "first-step__target" }, fs.target),
        el("p", { class: "first-step__reason" }, fs.reason),
        el("p", { class: "first-step__gain" }, fs.learning_gain),
        renderRefs(fs.evidence_refs),
      ),
    ));
  }

  // 8. reading path preview
  if (c.reading_path_preview?.length) {
    const list = el("ul", { class: "reading-list" });
    for (const r of c.reading_path_preview) {
      list.appendChild(el("li", { class: "reading-row" },
        el("div", { class: "reading-step" }, String(r.step_no).padStart(2, "0")),
        el("div", null,
          el("div", { class: "reading-target" }, `${r.target_type} · ${r.target}`),
          el("p", { class: "reading-reason" }, r.reason),
          el("p", { class: "reading-gain" }, "↳ ", r.learning_gain),
          r.skippable && el("p", { class: "reading-skip" }, "可跳过：", el("span", null, r.skippable)),
          renderRefs(r.evidence_refs),
        ),
      ));
    }
    root.appendChild(renderReportSection("阅读路径预览", list));
  }

  // 9. unknown items
  if (c.unknown_section?.length) {
    const list = el("ul", { class: "unknown-list" });
    for (const u of c.unknown_section) {
      list.appendChild(el("li", { class: "unknown-row" },
        el("strong", null, u.topic),
        u.description,
      ));
    }
    root.appendChild(renderReportSection("不确定项", list));
  }

  // 10. suggestions
  if (c.suggested_next_questions?.length) {
    root.appendChild(renderReportSection("下一步建议", renderSuggestions(c.suggested_next_questions)));
  }

  wrap.appendChild(root);
  return wrap;
}

function renderReportSection(title, body) {
  const sect = el("section", { class: "report__section" },
    el("h3", { class: "report__heading" }, title),
  );
  sect.appendChild(body);
  return sect;
}

// ---------- chat composer ----------

function mountChatComposer(state) {
  clear(stageFoot);
  const composer = clone("tmpl-chat-composer");
  const ta = $("#chat-input", composer);
  const btn = $("#chat-send", composer);
  ta.disabled = state.subStatus !== "waiting_user";
  btn.disabled = state.subStatus !== "waiting_user";
  if (ta.disabled) ta.placeholder = SUB_STATUS_LABELS[state.subStatus] || "Agent 正在思考…";

  ta.addEventListener("input", () => {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 180) + "px";
    btn.disabled = ta.value.trim().length === 0 || ta.disabled;
  });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  });
  composer.addEventListener("submit", (e) => { e.preventDefault(); submit(); });

  async function submit() {
    if (ta.disabled) return;
    const text = ta.value.trim();
    if (!text) return;
    ta.value = "";
    ta.style.height = "auto";
    await sendMessageNow(text);
  }

  stageFoot.appendChild(composer);
}

function updateChatComposer(state) {
  const ta = document.getElementById("chat-input");
  const btn = document.getElementById("chat-send");
  if (!ta || !btn) return mountChatComposer(state);
  const enabled = state.subStatus === "waiting_user";
  ta.disabled = !enabled;
  btn.disabled = !enabled || ta.value.trim().length === 0;
  ta.placeholder = enabled ? "输入你的问题，或点击上方建议…" : (SUB_STATUS_LABELS[state.subStatus] || "…");
}
