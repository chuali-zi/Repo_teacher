// Plugin system + tiny event bus.
// A plugin is a plain object: { name, init?(ctx), hooks?: { event: handler } }
// Hooks supported (extensible — call bus.emit(event, payload) from anywhere):
//   - "boot:ready"            payload: { ctx }
//   - "state:change"          payload: state
//   - "view:change"           payload: { from, to }
//   - "thinking:start"        payload: { messageId? }
//   - "thinking:stop"         payload: { messageId? }
//   - "stream:delta"          payload: { messageId, delta }
//   - "stream:end"            payload: { messageId }
//   - "message:append"        payload: MessageDto
//   - "sse:event"             payload: { kind: "analysis"|"chat", evt }
//   - "error:user"            payload: UserFacingError
//   - "debug:entry"           payload: debugEntry

const handlers = new Map(); // event -> Set<fn>
const plugins = [];
const slots = new Map();    // host name -> DOM element
const ctx = {
  bus: null,
  slots: null,
  state: null,
  api: null,
};

export const bus = {
  on(event, fn) {
    if (!handlers.has(event)) handlers.set(event, new Set());
    handlers.get(event).add(fn);
    return () => handlers.get(event).delete(fn);
  },
  off(event, fn) {
    handlers.get(event)?.delete(fn);
  },
  emit(event, payload) {
    const set = handlers.get(event);
    if (!set || set.size === 0) return;
    for (const fn of set) {
      try { fn(payload, ctx); }
      catch (err) {
        // late-import to avoid cycle
        import("./errors.js").then((m) =>
          m.report({ source: "plugin", level: "error", message: `hook ${event} 抛出异常`, where: fn.name || "(anonymous)", error: err }),
        );
      }
    }
  },
};

export function initPlugins({ state, api }) {
  ctx.bus = bus;
  ctx.state = state;
  ctx.api = api;
  ctx.slots = {
    sidebar: document.querySelector('[data-host="sidebar"]'),
    header: document.querySelector('[data-host="header"]'),
    thinking: document.querySelector('[data-host="thinking"]'),
  };
  for (const [name, host] of Object.entries(ctx.slots)) slots.set(name, host);
  // Show / hide thinking slot when bus events fire — that way zero-plugin baseline works.
  bus.on("thinking:start", () => {
    const host = slots.get("thinking");
    if (host && host.children.length > 0) host.parentElement.hidden = false;
  });
  bus.on("thinking:stop", () => {
    const host = slots.get("thinking");
    if (host && host.children.length === 0) host.parentElement.hidden = true;
  });
  return ctx;
}

export function registerPlugin(plugin) {
  if (!plugin || !plugin.name) {
    import("./errors.js").then((m) => m.report({ source: "plugin", level: "warn", message: "插件缺少 name 字段，已忽略", raw: plugin }));
    return;
  }
  plugins.push(plugin);
  if (plugin.hooks) {
    for (const [event, fn] of Object.entries(plugin.hooks)) {
      bus.on(event, fn);
    }
  }
  try { plugin.init?.(ctx); }
  catch (err) {
    import("./errors.js").then((m) => m.report({ source: "plugin", level: "error", message: `插件 ${plugin.name} 初始化失败`, error: err }));
  }
  // Render a minimal listing in sidebar plugin slot
  const sidebar = slots.get("sidebar");
  if (sidebar) {
    const empty = sidebar.querySelector(".hint");
    if (empty) empty.remove();
    const tag = document.createElement("div");
    tag.className = "plugin-tag";
    tag.style.cssText = "font-family: var(--f-mono); font-size: 11px; color: var(--ink-muted); padding: 4px 8px; border: 1px solid var(--border); border-radius: 999px; display: inline-block; margin: 2px 4px 0 0;";
    tag.textContent = `· ${plugin.name}`;
    sidebar.appendChild(tag);
  }
}

// Make plugin host globally accessible — third-party plugins can be added at runtime.
export function exposeGlobals() {
  window.RepoTutor = window.RepoTutor || {};
  window.RepoTutor.registerPlugin = registerPlugin;
  window.RepoTutor.bus = bus;
  window.RepoTutor.slots = (name) => slots.get(name);
}
