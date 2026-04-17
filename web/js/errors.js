// Error capture + always-visible debug panel.
// Goal: when something breaks, the user (and especially their teacher) immediately
// sees WHERE — module, function, and stack location.

import { el, clone, clear } from "./dom.js";
import { bus } from "./plugins.js";

const MAX = 200;
let entries = []; // { id, ts, level, source, where, message, stack, raw }
let counter = 0;
let listEl, dotEl, countEl, panelEl, bodyEl;
let highestLevel = "info"; // info < warn < error

const LEVEL_RANK = { info: 0, warn: 1, error: 2 };

export function initErrorPanel() {
  panelEl = document.getElementById("debug-panel");
  bodyEl = document.getElementById("debug-body");
  listEl = document.getElementById("debug-list");
  dotEl = document.getElementById("debug-dot");
  countEl = document.getElementById("debug-count");

  const toggle = document.getElementById("debug-toggle");
  toggle.addEventListener("click", () => {
    const open = panelEl.dataset.open === "true";
    panelEl.dataset.open = open ? "false" : "true";
    bodyEl.hidden = open;
    if (!open) acknowledgeAll();
  });

  document.getElementById("debug-clear").addEventListener("click", () => {
    entries = [];
    highestLevel = "info";
    panelEl.dataset.state = "";
    countEl.textContent = "0";
    clear(listEl);
  });
  document.getElementById("debug-copy").addEventListener("click", async () => {
    const text = entries.map(formatPlain).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      report({ source: "debug", level: "info", message: `已复制 ${entries.length} 条日志` });
    } catch (err) {
      report({ source: "debug", level: "warn", message: "复制失败：浏览器不允许写入剪贴板", error: err });
    }
  });

  // Global capture
  window.addEventListener("error", (ev) => {
    report({
      source: "window",
      level: "error",
      message: ev.message || String(ev.error),
      where: ev.filename ? `${trimFile(ev.filename)}:${ev.lineno}:${ev.colno}` : null,
      error: ev.error,
    });
  });
  window.addEventListener("unhandledrejection", (ev) => {
    const r = ev.reason;
    report({
      source: "promise",
      level: "error",
      message: r && r.message ? r.message : String(r),
      error: r,
    });
  });
}

export function report({ source, level = "info", message, where = null, error = null, raw = null }) {
  const entry = {
    id: ++counter,
    ts: new Date(),
    level,
    source: source || "app",
    where,
    message: message || (error && error.message) || "(no message)",
    stack: error && error.stack ? cleanStack(error.stack) : null,
    raw,
  };
  entries.push(entry);
  if (entries.length > MAX) entries.splice(0, entries.length - MAX);

  if (LEVEL_RANK[level] > LEVEL_RANK[highestLevel]) {
    highestLevel = level;
    panelEl && (panelEl.dataset.state = level === "error" ? "errors" : "warn");
  }
  countEl && (countEl.textContent = String(entries.length));

  renderEntry(entry);
  bus.emit("debug:entry", entry);
  // Mirror to console for browser devtools too
  const log = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
  log(`[RT][${entry.source}]${entry.where ? ` ${entry.where}` : ""}`, entry.message, error || raw || "");
}

function renderEntry(entry) {
  if (!listEl) return;
  const li = el("li", { class: "debug-entry", dataset: { level: entry.level } });
  const head = el(
    "div", { class: "debug-entry__head" },
    el("span", { class: "debug-entry__time" }, formatTime(entry.ts)),
    el("span", { class: "debug-entry__src" }, `${entry.source} · ${entry.level}`),
    entry.where && el("span", { class: "debug-entry__where" }, entry.where),
  );
  const msg = el("div", { class: "debug-entry__msg" }, entry.message);
  li.appendChild(head);
  li.appendChild(msg);
  if (entry.stack) {
    const det = el(
      "details", { class: "debug-entry__stack" },
      el("summary", null, "stack"),
      el("div", null, entry.stack),
    );
    li.appendChild(det);
  }
  if (entry.raw && typeof entry.raw === "object") {
    const det = el(
      "details", { class: "debug-entry__stack" },
      el("summary", null, "payload"),
      el("div", null, safeStringify(entry.raw)),
    );
    li.appendChild(det);
  }
  listEl.insertBefore(li, listEl.firstChild);
}

function acknowledgeAll() {
  highestLevel = "info";
  panelEl.dataset.state = "";
}

function cleanStack(stack) {
  return String(stack)
    .split("\n")
    .map((l) => l.replace(/https?:\/\/[^/]+/g, "").trim())
    .filter(Boolean)
    .slice(0, 12)
    .join("\n");
}

function trimFile(url) {
  try {
    const u = new URL(url);
    return u.pathname.split("/").slice(-2).join("/");
  } catch {
    return url;
  }
}

function formatTime(d) {
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

function formatPlain(e) {
  return `[${formatTime(e.ts)}] ${e.source}/${e.level}${e.where ? " @" + e.where : ""}\n  ${e.message}${e.stack ? "\n  " + e.stack.replace(/\n/g, "\n  ") : ""}`;
}

function safeStringify(obj) {
  try { return JSON.stringify(obj, null, 2); } catch { return String(obj); }
}

// helper: wrap an async fn so failures land in the panel with a clear "where"
export function trace(where, fn) {
  return async (...args) => {
    try { return await fn(...args); }
    catch (err) {
      report({ source: "trace", level: "error", message: err && err.message ? err.message : String(err), where, error: err });
      throw err;
    }
  };
}
