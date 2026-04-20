import { clear, el } from "./dom.js";

const MAX_ENTRIES = 200;
const LEVEL_RANK = { info: 0, warn: 1, error: 2 };

let entries = [];
let entryId = 0;
let topLevel = "info";
let listEl = null;
let panelEl = null;
let bodyEl = null;
let countEl = null;

export function initErrorPanel() {
  panelEl = document.getElementById("debug-panel");
  bodyEl = document.getElementById("debug-body");
  listEl = document.getElementById("debug-list");
  countEl = document.getElementById("debug-count");

  document.getElementById("debug-toggle").addEventListener("click", () => {
    const isOpen = panelEl.dataset.open === "true";
    panelEl.dataset.open = isOpen ? "false" : "true";
    bodyEl.hidden = isOpen;
  });

  document.getElementById("debug-clear").addEventListener("click", () => {
    entries = [];
    topLevel = "info";
    panelEl.dataset.state = "";
    countEl.textContent = "0";
    clear(listEl);
  });

  document.getElementById("debug-copy").addEventListener("click", async () => {
    const text = entries.map(formatPlain).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      report({ source: "debug", level: "info", message: `Copied ${entries.length} log lines` });
    } catch (error) {
      report({ source: "debug", level: "warn", message: "Clipboard copy failed", error });
    }
  });

  window.addEventListener("error", (event) => {
    report({
      source: "window",
      level: "error",
      message: event.message || String(event.error),
      where: event.filename ? `${event.filename}:${event.lineno}:${event.colno}` : null,
      error: event.error,
    });
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    report({
      source: "promise",
      level: "error",
      message: reason?.message || String(reason),
      error: reason,
    });
  });
}

export function report({ source, level = "info", message, where = null, error = null, raw = null }) {
  const entry = {
    id: ++entryId,
    source: source || "app",
    level,
    message: message || error?.message || "(no message)",
    where,
    stack: error?.stack ? String(error.stack) : null,
    raw,
    timestamp: new Date(),
  };

  entries.push(entry);
  if (entries.length > MAX_ENTRIES) entries = entries.slice(-MAX_ENTRIES);

  if (LEVEL_RANK[level] > LEVEL_RANK[topLevel]) {
    topLevel = level;
    if (panelEl) panelEl.dataset.state = level;
  }

  if (countEl) countEl.textContent = String(entries.length);
  if (listEl) listEl.insertBefore(renderEntry(entry), listEl.firstChild);

  const sink = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
  sink(`[RT][${entry.source}]${entry.where ? ` ${entry.where}` : ""}`, entry.message, error || raw || "");
}

function renderEntry(entry) {
  const item = el("li", { class: "debug-entry" });
  item.appendChild(
    el(
      "div",
      { class: "debug-entry__head" },
      formatTime(entry.timestamp),
      el("span", null, `${entry.source}/${entry.level}`),
      entry.where ? el("span", null, entry.where) : null,
    ),
  );
  item.appendChild(el("div", { class: "debug-entry__msg" }, entry.message));
  if (entry.stack) item.appendChild(el("div", { class: "debug-entry__stack" }, entry.stack));
  if (entry.raw && typeof entry.raw === "object") {
    item.appendChild(el("div", { class: "debug-entry__stack" }, safeStringify(entry.raw)));
  }
  return item;
}

function formatTime(date) {
  const pad = (value, width = 2) => String(value).padStart(width, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

function formatPlain(entry) {
  return `[${formatTime(entry.timestamp)}] ${entry.source}/${entry.level}${entry.where ? ` @${entry.where}` : ""}\n  ${entry.message}`;
}

function safeStringify(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
