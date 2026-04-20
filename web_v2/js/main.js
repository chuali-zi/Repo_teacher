import { api } from "./api.js";
import { initErrorPanel, report } from "./errors.js";
import { applySessionSnapshot } from "./state.js";
import { initViews } from "./views.js";

async function boot() {
  initErrorPanel();
  initViews();

  report({ source: "boot", level: "info", message: "Booting web_v2" });

  try {
    const response = await api.getSession();
    applySessionSnapshot(response.data);
    report({
      source: "boot",
      level: "info",
      message: `Session restore complete (${response.data.status})`,
      where: "GET /api/session",
    });
  } catch (error) {
    report({
      source: "boot",
      level: "warn",
      message: "Could not restore session snapshot",
      where: "GET /api/session",
      error,
    });
    applySessionSnapshot({
      session_id: null,
      status: "idle",
      sub_status: null,
      view: "input",
      analysis_mode: null,
      repository: null,
      progress_steps: [],
      degradation_notices: [],
      messages: [],
      active_agent_activity: null,
      active_error: null,
      deep_research_state: null,
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
