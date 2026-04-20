import { api, openStream } from "./api.js";
import { clear, el, frag } from "./dom.js";
import { report } from "./errors.js";
import {
  appendMessageDelta,
  applySessionSnapshot,
  getState,
  resetState,
  setState,
  setStreamingMessage,
  subscribe,
  upsertMessage,
} from "./state.js";

const STATUS_LABELS = {
  idle: "Idle",
  accessing: "Connecting",
  analyzing: "Analyzing",
  chatting: "Teaching",
  access_error: "Access error",
  analysis_error: "Analysis error",
};

const SUBSTATUS_LABELS = {
  waiting_user: "Ready for the next question",
  agent_thinking: "Agent is thinking",
  agent_streaming: "Agent is streaming",
};

const STEP_LABELS = {
  repo_access: "Repo access",
  file_tree_scan: "File tree scan",
  initial_report_generation: "Initial report",
  research_planning: "Research planning",
  source_sweep: "Source sweep",
  chapter_synthesis: "Chapter synthesis",
  final_report_write: "Final report",
  entry_and_module_analysis: "Entry and module analysis",
  dependency_analysis: "Dependency analysis",
  skeleton_assembly: "Teaching skeleton",
};

let statusRoot;
let stageHeader;
let stageBody;
let stageFoot;
let sideRoot;
let lastSessionId = null;
let analysisCloser = null;
let chatCloser = null;

let repoDraft = "";
let modeDraft = "quick_guide";
let chatDraft = "";
let sidecarDraft = "";
let sidecarState = "idle";
let sidecarAnswer = "Ask for a quick explanation of a term or phrase from the current answer.";

export function initViews() {
  statusRoot = document.getElementById("status-panel");
  stageHeader = document.getElementById("stage-header");
  stageBody = document.getElementById("stage-body");
  stageFoot = document.getElementById("stage-foot");
  sideRoot = document.getElementById("side-panel");

  subscribe(render);
  render(getState());
}

function render(state) {
  if (!repoDraft && state.repository?.input_value) {
    repoDraft = state.repository.input_value;
  }

  if (state.sessionId !== lastSessionId) {
    closeStreams();
    lastSessionId = state.sessionId;
  }

  ensureStreams(state);
  renderStatusPanel(state);
  renderStage(state);
  renderSidePanel(state);

  if (state.view !== "input" && (state.subStatus === "agent_streaming" || state.view === "analysis")) {
    requestAnimationFrame(() => {
      stageBody.scrollTop = stageBody.scrollHeight;
    });
  }
}

function renderStatusPanel(state) {
  clear(statusRoot);

  const tone = state.activeError
    ? "error"
    : state.status === "idle"
      ? "idle"
      : state.status.includes("error")
        ? "error"
        : state.subStatus && state.subStatus !== "waiting_user"
          ? "busy"
          : "busy";

  statusRoot.appendChild(
    el(
      "section",
      { class: "brand-card" },
      el("div", { class: "brand-card__eyebrow" }, "Repo Tutor"),
      el("h1", { class: "brand-card__title" }, "PIXEL CONSOLE"),
      el(
        "p",
        { class: "brand-card__meta" },
        "A bright, read-only teaching surface for exploring repositories with live backend events.",
      ),
    ),
  );

  statusRoot.appendChild(
    el(
      "section",
      { class: "status-card" },
      el("div", { class: "panel-title" }, "Session"),
      el(
        "div",
        { class: "status-dot", dataset: { tone } },
        STATUS_LABELS[state.status] || state.status,
      ),
      state.subStatus
        ? el("p", { class: "muted" }, SUBSTATUS_LABELS[state.subStatus] || state.subStatus)
        : null,
    ),
  );

  if (state.repository) {
    statusRoot.appendChild(
      el(
        "section",
        { class: "status-card" },
        el("div", { class: "panel-title" }, "Repository"),
        el(
          "dl",
          { class: "kv-list" },
          kv("Display", state.repository.display_name),
          kv("Source", state.repository.source_type),
          kv("Input", state.repository.input_value),
          state.analysisMode ? kv("Mode", state.analysisMode.replace("_", " ")) : null,
        ),
        el(
          "div",
          { class: "badge-row" },
          state.repository.primary_language
            ? el("span", { class: "badge badge--accent" }, state.repository.primary_language)
            : null,
          state.repository.repo_size_level
            ? el("span", { class: "badge" }, state.repository.repo_size_level)
            : null,
          state.repository.source_code_file_count != null
            ? el("span", { class: "badge" }, `${state.repository.source_code_file_count} files`)
            : null,
        ),
      ),
    );
  }

  if (state.progressSteps.length) {
    statusRoot.appendChild(
      el(
        "section",
        { class: "status-card" },
        el("div", { class: "panel-title" }, "Pipeline"),
        el(
          "div",
          { class: "progress-list" },
          state.progressSteps.map(renderStepRow),
        ),
      ),
    );
  }

  if (state.deepResearchState && state.analysisMode === "deep_research") {
    const coverage = state.deepResearchState.total_files
      ? `${Math.round((state.deepResearchState.coverage_ratio || 0) * 100)}%`
      : "0%";
    statusRoot.appendChild(
      el(
        "section",
        { class: "status-card" },
        el("div", { class: "panel-title" }, "Deep research"),
        el(
          "dl",
          { class: "kv-list" },
          kv("Phase", state.deepResearchState.phase || "pending"),
          kv("Coverage", coverage),
          kv(
            "Files",
            `${state.deepResearchState.completed_files || 0}/${state.deepResearchState.total_files || 0}`,
          ),
          state.deepResearchState.current_target
            ? kv("Current", state.deepResearchState.current_target)
            : null,
          state.deepResearchState.last_completed_target
            ? kv("Last", state.deepResearchState.last_completed_target)
            : null,
        ),
      ),
    );
  }

  if (state.activeAgentActivity && state.subStatus !== "waiting_user") {
    statusRoot.appendChild(
      el(
        "section",
        { class: "status-card" },
        el("div", { class: "panel-title" }, "Agent activity"),
        el("div", { class: "summary-list" }, renderActivitySummary(state.activeAgentActivity)),
      ),
    );
  }

  if (state.degradationNotices.length) {
    statusRoot.appendChild(
      el(
        "section",
        { class: "status-card" },
        el("div", { class: "panel-title" }, "Notices"),
        el(
          "div",
          { class: "notice-list" },
          state.degradationNotices.map((notice) =>
            el(
              "div",
              { class: "notice-item" },
              `${notice.type}: ${notice.user_notice}`,
            ),
          ),
        ),
      ),
    );
  }

  if (state.activeError) {
    statusRoot.appendChild(
      el(
        "section",
        { class: "status-card" },
        el("div", { class: "panel-title" }, "Current error"),
        el("div", { class: "notice-item notice-item--error" }, state.activeError.message),
      ),
    );
  }
}

function renderStage(state) {
  clear(stageHeader);
  clear(stageBody);
  clear(stageFoot);

  if (state.view === "input") {
    renderInputHeader(state);
    renderInputView(state);
    return;
  }

  renderActiveHeader(state);

  if (state.view === "analysis") {
    renderAnalysisView(state);
    return;
  }

  renderChatView(state);
  renderComposer(state);
}

function renderInputHeader(state) {
  stageHeader.appendChild(
    el(
      "div",
      { class: "chip-row" },
      el("span", { class: "chip" }, "no-build frontend"),
      el("span", { class: "chip" }, "backend @ 127.0.0.1:8000"),
      el("span", { class: "chip" }, state.activeError ? "recoverable error" : "ready"),
    ),
  );
}

function renderInputView(state) {
  const root = el("div", { class: "hero-card" });

  root.appendChild(
    el(
      "pre",
      { class: "hero-ascii" },
      String.raw`+---------------------------------------------+
| REPO TUTOR // PIXEL READING CONSOLE         |
| LIVE FASTAPI CONTRACTS // STATIC FRONTEND   |
+---------------------------------------------+`,
    ),
  );

  root.appendChild(
    frag(
      el("p", { class: "eyebrow" }, "Read-only source tour"),
      el("h2", { class: "hero-title" }, "Turn a repository into a guided conversation."),
      el(
        "p",
        { class: "hero-copy" },
        "Paste a local path or a public GitHub URL. The backend will analyze the repo and stream the first report into this pixel console.",
      ),
    ),
  );

  if (state.activeError) {
    root.appendChild(el("div", { class: "notice-item notice-item--error" }, state.activeError.message));
  }

  const form = el("form", { class: "pixel-card form-grid" });
  form.appendChild(el("div", { class: "panel-title" }, "Repository input"));

  const repoInput = el("input", {
    class: "pixel-input",
    type: "text",
    placeholder: "C:\\path\\to\\repo or https://github.com/owner/repo",
    value: repoDraft,
    spellcheck: "false",
    oninput: (event) => {
      repoDraft = event.target.value;
    },
  });

  form.appendChild(repoInput);

  const radioRow = el("div", { class: "radio-row" });
  for (const option of [
    { value: "quick_guide", label: "Quick guide" },
    { value: "deep_research", label: "Deep research" },
  ]) {
    const radio = el("input", {
      type: "radio",
      name: "analysis-mode",
      value: option.value,
      checked: modeDraft === option.value,
      onchange: () => {
        modeDraft = option.value;
      },
    });
    radioRow.appendChild(
      el("label", { class: "radio-pill" }, radio, el("span", null, option.label)),
    );
  }
  form.appendChild(radioRow);

  form.appendChild(
    el(
      "div",
      { class: "form-actions" },
      el(
        "p",
        { class: "muted" },
        "Quick guide focuses on a compact first answer. Deep research exposes the longer multi-phase scan and coverage state.",
      ),
      el("button", { class: "pixel-btn", type: "submit" }, "Start analysis"),
    ),
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitRepository();
  });

  root.appendChild(form);

  root.appendChild(
    el(
      "section",
      { class: "pixel-card" },
      el("div", { class: "panel-title" }, "Examples"),
      el(
        "div",
        { class: "summary-list" },
        exampleButton("C:\\Users\\you\\projects\\demo"),
        exampleButton("https://github.com/pallets/flask"),
        exampleButton("https://github.com/tiangolo/fastapi"),
      ),
    ),
  );

  stageBody.appendChild(root);
}

function renderActiveHeader(state) {
  stageHeader.appendChild(
    el(
      "div",
      { class: "form-actions" },
      el(
        "div",
        null,
        el("div", { class: "eyebrow" }, state.view === "analysis" ? "Analyzing" : "Conversation"),
        el("div", { class: "hero-copy" }, state.repository?.display_name || "Active session"),
      ),
      state.sessionId
        ? el(
            "button",
            {
              class: "pixel-btn",
              type: "button",
              onclick: () => void switchRepository(),
            },
            "Switch repo",
          )
        : null,
    ),
  );
}

function renderAnalysisView(state) {
  const streamMessage = [...state.messages]
    .reverse()
    .find((message) => message.message_type === "initial_report" && !message.streaming_complete);

  const root = el(
    "section",
    { class: "analysis-card" },
    el("div", { class: "eyebrow" }, "Live backend pipeline"),
    el(
      "h2",
      { class: "hero-title" },
      state.repository?.display_name || "Repository analysis",
    ),
    el(
      "p",
      { class: "hero-copy" },
      "The backend is driving the status, progress steps, and the initial report preview via server-sent events.",
    ),
    el(
      "div",
      { class: "progress-list" },
      (state.progressSteps.length ? state.progressSteps : defaultSteps(state.analysisMode)).map(renderStepRow),
    ),
    state.degradationNotices.length
      ? el(
          "div",
          { class: "notice-list" },
          state.degradationNotices.map((notice) =>
            el("div", { class: "notice-item" }, notice.user_notice),
          ),
        )
      : null,
    streamMessage
      ? el(
          "section",
          { class: "analysis-stream" },
          el("header", null, "Streaming initial report"),
          el("pre", null, streamMessage.raw_text || "Waiting for first tokens..."),
        )
      : null,
  );

  stageBody.appendChild(root);
}

function renderChatView(state) {
  const thread = el("div", { class: "thread" });

  if (state.activeAgentActivity && state.subStatus !== "waiting_user") {
    thread.appendChild(
      el(
        "section",
        { class: "msg-card thinking-card" },
        el(
          "div",
          { class: "msg-head" },
          el("span", null, activityLabel(state.activeAgentActivity)),
          el(
            "span",
            { class: "thinking-card__dots" },
            el("span"),
            el("span"),
            el("span"),
          ),
        ),
        el("div", { class: "msg-body" }, renderActivitySummary(state.activeAgentActivity)),
      ),
    );
  }

  if (!state.messages.length) {
    thread.appendChild(
      el(
        "section",
        { class: "msg-card empty-state" },
        "The initial report will appear here and the follow-up conversation will continue in the same thread.",
      ),
    );
  }

  for (const message of state.messages) {
    thread.appendChild(renderMessage(message));
  }

  stageBody.appendChild(thread);
}

function renderComposer(state) {
  const disabled = state.subStatus !== "waiting_user";
  const composer = el("form", { class: "composer" });
  composer.appendChild(
    el(
      "div",
      { class: "panel-title" },
      disabled ? SUBSTATUS_LABELS[state.subStatus] || "Waiting" : "Ask the next question",
    ),
  );

  const row = el("div", { class: "composer__row" });
  const sendButton = el(
    "button",
    {
      class: "pixel-btn",
      type: "submit",
      disabled: disabled || !chatDraft.trim(),
    },
    "Send",
  );
  const textarea = el("textarea", {
    class: "pixel-textarea",
    rows: "3",
    placeholder: disabled ? "The backend is still working..." : "Ask about flow, modules, entry points, or a specific file.",
    disabled,
    oninput: (event) => {
      chatDraft = event.target.value;
      sendButton.disabled = disabled || !chatDraft.trim();
    },
  });
  textarea.value = chatDraft;
  row.appendChild(textarea);
  row.appendChild(sendButton);

  composer.appendChild(row);
  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendMessage();
  });
  stageFoot.appendChild(composer);
}

function renderSidePanel(state) {
  clear(sideRoot);

  sideRoot.appendChild(
    el(
      "section",
      { class: "side-card" },
      el("div", { class: "panel-title" }, "Term explainer"),
      el(
        "p",
        { class: "muted" },
        "Send a short question to the lightweight explainer without touching the active repo session.",
      ),
      buildSidecarForm(),
      el(
        "div",
        { class: "side-card__answer", dataset: { state: sidecarState } },
        sidecarAnswer,
      ),
    ),
  );

  const latestSuggestions = latestSuggestionTexts(state.messages);
  sideRoot.appendChild(
    el(
      "section",
      { class: "side-card" },
      el("div", { class: "panel-title" }, "Follow-up prompts"),
      latestSuggestions.length
        ? el(
            "div",
            { class: "suggestion-row" },
            latestSuggestions.map((text) =>
              el(
                "button",
                {
                  class: "suggestion-chip",
                  type: "button",
                  disabled: state.subStatus !== "waiting_user",
                  onclick: () => {
                    chatDraft = text;
                    render(getState());
                  },
                },
                text,
              ),
            ),
          )
        : el(
            "p",
            { class: "muted" },
            "Suggestions will appear here after the backend returns them.",
          ),
    ),
  );

  sideRoot.appendChild(
    el(
      "section",
      { class: "side-card" },
      el("div", { class: "panel-title" }, "What is wired"),
      el(
        "div",
        { class: "summary-list" },
        el("div", null, "POST /api/repo"),
        el("div", null, "GET /api/analysis/stream"),
        el("div", null, "POST /api/chat"),
        el("div", null, "GET /api/chat/stream"),
        el("div", null, "GET /api/session"),
        el("div", null, "DELETE /api/session"),
        el("div", null, "POST /api/sidecar/explain"),
      ),
    ),
  );
}

function buildSidecarForm() {
  const form = el("form", { class: "form-grid" });
  const button = el(
    "button",
    {
      class: "pixel-btn",
      type: "submit",
      disabled: !sidecarDraft.trim() || sidecarState === "loading",
    },
    sidecarState === "loading" ? "Explaining..." : "Explain",
  );
  const input = el("textarea", {
    class: "pixel-textarea",
    rows: "3",
    placeholder: "What does dependency injection mean here?",
    oninput: (event) => {
      sidecarDraft = event.target.value;
      button.disabled = !sidecarDraft.trim() || sidecarState === "loading";
    },
  });
  input.value = sidecarDraft;
  form.appendChild(input);
  form.appendChild(button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await explainSidecar();
  });
  return form;
}

async function submitRepository() {
  const inputValue = repoDraft.trim();
  if (!inputValue) return;

  report({ source: "ui", level: "info", message: `Submitting repo: ${inputValue}` });

  try {
    const response = await api.submitRepo(inputValue, modeDraft);
    setState({
      sessionId: response.session_id,
      status: response.data.status,
      subStatus: response.data.sub_status,
      view: response.data.view,
      analysisMode: response.data.analysis_mode,
      repository: response.data.repository,
      progressSteps: defaultSteps(response.data.analysis_mode),
      deepResearchState: response.data.analysis_mode === "deep_research"
        ? {
            phase: "pending",
            total_files: 0,
            completed_files: 0,
            skipped_files: 0,
            coverage_ratio: 0,
            current_target: null,
            last_completed_target: null,
            relevant_files: [],
          }
        : null,
      degradationNotices: [],
      messages: [],
      activeAgentActivity: null,
      activeError: null,
    });
  } catch (error) {
    report({ source: "ui", level: "error", message: "Repo submission failed", where: "submitRepository", error });
    setState({
      status: "idle",
      subStatus: null,
      view: "input",
      activeError: error.payload || { message: error.message || "Repo submission failed" },
    });
  }
}

async function sendMessage() {
  const state = getState();
  const text = chatDraft.trim();
  if (!state.sessionId || !text || state.subStatus !== "waiting_user") return;

  chatDraft = "";
  upsertMessage({
    message_id: `local_user_${Date.now()}`,
    role: "user",
    message_type: "user_question",
    created_at: new Date().toISOString(),
    raw_text: text,
    suggestions: [],
    streaming_complete: true,
    error_state: null,
  });
  setState({
    subStatus: "agent_thinking",
    activeAgentActivity: {
      activity_id: `local_activity_${Date.now()}`,
      phase: "thinking",
      summary: "Preparing the next answer",
      tool_name: null,
      tool_arguments: {},
      round_index: null,
      elapsed_ms: null,
      soft_timed_out: false,
      failed: false,
      retryable: false,
    },
    activeError: null,
  });

  try {
    await api.sendMessage(state.sessionId, text);
    if (!chatCloser) chatCloser = openStream("chat", state.sessionId, (event) => handleStreamEvent("chat", event));
  } catch (error) {
    report({ source: "ui", level: "error", message: "Chat send failed", where: "sendMessage", error });
    setState({
      subStatus: "waiting_user",
      activeAgentActivity: null,
      activeError: error.payload || { message: error.message || "Chat send failed" },
    });
  }
}

async function explainSidecar() {
  const question = sidecarDraft.trim();
  if (!question) return;

  sidecarState = "loading";
  sidecarAnswer = "Working on a short explanation...";
  render(getState());

  try {
    const response = await api.explainSidecar(question);
    sidecarState = "ready";
    sidecarAnswer = response.data.answer;
    sidecarDraft = "";
  } catch (error) {
    sidecarState = "error";
    sidecarAnswer = error.payload?.message || error.message || "Sidecar request failed.";
    report({ source: "ui", level: "warn", message: "Sidecar explain failed", where: "explainSidecar", error });
  }

  render(getState());
}

async function switchRepository() {
  const state = getState();
  if (!state.sessionId) return;

  try {
    await api.clearSession(state.sessionId);
    closeStreams();
    resetState();
    repoDraft = "";
    chatDraft = "";
    modeDraft = "quick_guide";
    const response = await api.getSession();
    applySessionSnapshot(response.data);
  } catch (error) {
    report({ source: "ui", level: "error", message: "Could not clear session", where: "switchRepository", error });
  }
}

function ensureStreams(state) {
  const wantsAnalysis = Boolean(
    state.sessionId && (state.status === "accessing" || state.status === "analyzing"),
  );
  const wantsChat = Boolean(
    state.sessionId && state.status === "chatting" && state.subStatus && state.subStatus !== "waiting_user",
  );

  if (wantsAnalysis && !analysisCloser) {
    analysisCloser = openStream("analysis", state.sessionId, (event) => handleStreamEvent("analysis", event));
    report({ source: "sse", level: "info", message: "Connected analysis stream" });
  } else if (!wantsAnalysis && analysisCloser) {
    analysisCloser();
    analysisCloser = null;
  }

  if (wantsChat && !chatCloser) {
    chatCloser = openStream("chat", state.sessionId, (event) => handleStreamEvent("chat", event));
    report({ source: "sse", level: "info", message: "Connected chat stream" });
  } else if (!wantsChat && chatCloser) {
    chatCloser();
    chatCloser = null;
  }
}

function closeStreams() {
  if (analysisCloser) {
    analysisCloser();
    analysisCloser = null;
  }
  if (chatCloser) {
    chatCloser();
    chatCloser = null;
  }
}

function handleStreamEvent(kind, event) {
  const state = getState();
  if (state.sessionId && event.session_id && event.session_id !== state.sessionId) {
    report({ source: "sse", level: "warn", message: `Ignoring stale ${kind} event`, raw: event });
    return;
  }

  switch (event.event_type) {
    case "status_changed":
      setState({
        status: event.status,
        subStatus: event.sub_status ?? null,
        view: event.view,
      });
      return;

    case "analysis_progress":
      setState({
        progressSteps: event.progress_steps || getState().progressSteps,
        deepResearchState: event.deep_research_state ?? getState().deepResearchState,
      });
      if (event.user_notice) {
        report({ source: "analysis", level: "info", message: event.user_notice, where: event.step_key });
      }
      return;

    case "degradation_notice":
      setState((current) => ({
        degradationNotices: [...current.degradationNotices, event.degradation],
      }));
      report({ source: "analysis", level: "warn", message: event.degradation.user_notice, where: event.degradation.type });
      return;

    case "agent_activity":
      setState({ activeAgentActivity: event.activity });
      return;

    case "answer_stream_start":
      setStreamingMessage(event.message_id, event.message_type);
      return;

    case "answer_stream_delta":
      appendMessageDelta(event.message_id, event.delta_text || "");
      return;

    case "answer_stream_end":
      return;

    case "message_completed":
      upsertMessage({ ...event.message, _streaming: false });
      setState({
        status: event.status,
        subStatus: event.sub_status ?? null,
        view: event.view,
        activeAgentActivity: null,
        activeError: null,
      });
      return;

    case "error":
      setState({
        status: event.status,
        subStatus: event.sub_status ?? null,
        view: event.view,
        activeAgentActivity: null,
        activeError: event.error,
      });
      report({ source: kind, level: "error", message: event.error.message, where: event.error.error_code, raw: event.error });
      return;
  }
}

function renderStepRow(step) {
  return el(
    "div",
    { class: "progress-row", dataset: { state: step.step_state } },
    el("span", { class: "progress-row__state" }, stepStateGlyph(step.step_state)),
    el("span", { class: "progress-row__label" }, STEP_LABELS[step.step_key] || step.step_key),
    el("span", { class: "progress-row__hint" }, step.step_state),
  );
}

function renderMessage(message) {
  const card = el("section", {
    class: `msg-card msg-card--${message.role === "user" ? "user" : "agent"}`,
  });

  card.appendChild(
    el(
      "div",
      { class: "msg-head" },
      el("span", null, message.role === "user" ? "You" : labelForMessage(message.message_type)),
      el("span", null, formatTime(message.created_at)),
    ),
  );

  if (message.message_type === "initial_report" && message.raw_text) {
    const headings = extractHeadings(message.raw_text);
    if (headings.length) {
      card.appendChild(
        el(
          "div",
          { class: "report-map" },
          el("div", { class: "panel-title" }, "Report map"),
          el("ol", null, headings.map((heading) => el("li", null, heading))),
        ),
      );
    }
  }

  if (message.error_state) {
    card.appendChild(
      el(
        "div",
        { class: "notice-item notice-item--error" },
        message.error_state.error?.message || "Unknown message error",
      ),
    );
  }

  if (message._streaming || !message.streaming_complete) {
    card.appendChild(el("pre", { class: "msg-body" }, message.raw_text || "..."));
  } else if (message.role === "user") {
    card.appendChild(el("div", { class: "msg-body" }, message.raw_text || ""));
  } else {
    card.appendChild(el("div", { class: "msg-body", html: markdownToHtml(message.raw_text || "(no content)") }));
  }

  const suggestions = suggestionTexts(message.suggestions);
  if (suggestions.length) {
    card.appendChild(
      el(
        "div",
        { class: "suggestion-row" },
        suggestions.map((text) =>
          el(
            "button",
            {
              class: "suggestion-chip",
              type: "button",
              disabled: getState().subStatus !== "waiting_user",
              onclick: () => {
                chatDraft = text;
                render(getState());
              },
            },
            text,
          ),
        ),
      ),
    );
  }

  return card;
}

function renderActivitySummary(activity) {
  const bits = [activity.summary || "Working"];
  if (activity.tool_name) bits.push(`Tool: ${activity.tool_name}`);
  if (activity.round_index != null) bits.push(`Round ${activity.round_index}`);
  if (activity.elapsed_ms != null) bits.push(`${(activity.elapsed_ms / 1000).toFixed(1)}s`);
  return bits.join(" | ");
}

function activityLabel(activity) {
  const labels = {
    thinking: "Thinking",
    planning_tool_call: "Planning tool call",
    tool_running: "Running tool",
    tool_succeeded: "Tool complete",
    tool_failed: "Tool failed",
    degraded_continue: "Degraded continue",
    waiting_llm_after_tool: "Writing answer",
    slow_warning: "Still working",
  };
  return labels[activity.phase] || activity.phase;
}

function labelForMessage(messageType) {
  if (messageType === "initial_report") return "Agent initial report";
  if (messageType === "stage_summary") return "Agent summary";
  if (messageType === "goal_switch_confirmation") return "Agent update";
  return "Agent";
}

function kv(label, value) {
  return frag(el("dt", null, label), el("dd", null, value));
}

function stepStateGlyph(stepState) {
  if (stepState === "done") return "[ok]";
  if (stepState === "running") return "[>]";
  if (stepState === "error") return "[!]";
  return "[ ]";
}

function defaultSteps(analysisMode) {
  const keys = analysisMode === "deep_research"
    ? [
        "repo_access",
        "file_tree_scan",
        "research_planning",
        "source_sweep",
        "chapter_synthesis",
        "final_report_write",
      ]
    : ["repo_access", "file_tree_scan", "initial_report_generation"];
  return keys.map((stepKey) => ({ step_key: stepKey, step_state: "pending" }));
}

function exampleButton(value) {
  return el(
    "button",
    {
      class: "pixel-btn",
      type: "button",
      onclick: () => {
        repoDraft = value;
        render(getState());
      },
    },
    value,
  );
}

function latestSuggestionTexts(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const items = suggestionTexts(messages[index].suggestions);
    if (items.length) return items;
  }
  return [];
}

function suggestionTexts(items) {
  if (!Array.isArray(items)) return [];
  const texts = [];
  const seen = new Set();
  for (const item of items) {
    const text = (item?.text || "").trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    texts.push(text);
    if (texts.length >= 3) break;
  }
  return texts;
}

function extractHeadings(text) {
  return String(text)
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.match(/^##\s+(.*)$/))
    .filter(Boolean)
    .map((match) => match[1].trim())
    .filter(Boolean)
    .slice(0, 6);
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (number) => String(number).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function markdownToHtml(text) {
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  const html = [];
  let paragraph = [];
  let listType = null;
  let listItems = [];
  let inCode = false;
  let codeLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map(formatInlineMarkdown).join("<br>")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listType || !listItems.length) return;
    html.push(`<${listType}>${listItems.map((item) => `<li>${formatInlineMarkdown(item)}</li>`).join("")}</${listType}>`);
    listItems = [];
    listType = null;
  };

  const flushCode = () => {
    if (!codeLines.length) return;
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  };

  for (const line of lines) {
    if (/^```/.test(line)) {
      flushParagraph();
      flushList();
      if (inCode) {
        flushCode();
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(heading[1].length + 3, 6);
      html.push(`<h${level}>${formatInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const ordered = line.match(/^\s*\d+\.\s+(.*)$/);
    const unordered = line.match(/^\s*[-*]\s+(.*)$/);
    if (ordered || unordered) {
      flushParagraph();
      const nextType = ordered ? "ol" : "ul";
      if (listType && listType !== nextType) flushList();
      listType = nextType;
      listItems.push((ordered || unordered)[1]);
      continue;
    }
    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  if (inCode) flushCode();
  return html.join("");
}

function formatInlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return html;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
