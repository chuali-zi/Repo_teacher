// Repo Tutor · Reading Room — application bootstrap.
// No framework, no build step. Just ES modules served over http.

import { initErrorPanel, report } from "./errors.js";
import { initPlugins, exposeGlobals } from "./plugins.js";
import { getState, subscribe, applySessionSnapshot } from "./state.js";
import { api } from "./api.js";
import { initViews } from "./views.js";

async function boot() {
  initErrorPanel();
  report({ source: "boot", level: "info", message: "阅读间启动" });

  exposeGlobals();

  const pluginCtx = initPlugins({ state: getState, api });

  initViews();

  // Restore session from backend
  try {
    const res = await api.getSession();
    if (res && res.ok !== false && res.data) {
      applySessionSnapshot(res.data);
      report({ source: "boot", level: "info", message: `会话恢复完成 · status=${res.data.status}`, where: "GET /api/session" });
    }
  } catch (err) {
    report({
      source: "boot",
      level: "warn",
      message: "未能获取会话快照（后端可能未启动）",
      where: "GET /api/session",
      error: err,
    });
    // Fall through to idle/input view — that's fine.
    applySessionSnapshot({
      session_id: null,
      status: "idle",
      sub_status: null,
      view: "input",
      repository: null,
      progress_steps: [],
      degradation_notices: [],
      messages: [],
      active_error: null,
    });
  }

  // Load user plugins declared via <script data-plugin>
  const pluginScripts = document.querySelectorAll('script[data-plugin]');
  for (const s of pluginScripts) {
    try {
      const href = s.src || new URL(s.dataset.plugin, document.baseURI).href;
      const mod = await import(href);
      if (mod && mod.default) window.RepoTutor.registerPlugin(mod.default);
    } catch (err) {
      report({ source: "plugin", level: "warn", message: `插件加载失败：${s.src || s.dataset.plugin}`, error: err });
    }
  }

  report({ source: "boot", level: "info", message: "启动完成" });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
