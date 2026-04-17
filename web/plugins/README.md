# Repo Tutor Plugin Guide

Plugins are ES modules that hook into the Reading Room lifecycle.

## Quick Start

1. Create a `.js` file in this `plugins/` directory.
2. Export a default object with `name` and optionally `init(ctx)` and `hooks`.
3. Register the plugin in `index.html` before `</body>`:

```html
<script type="module" data-plugin="./plugins/my_plugin.js"></script>
```

## Plugin API

```js
export default {
  name: "my-plugin",

  // Called once after the plugin system boots.
  init(ctx) {
    // ctx.bus   — event bus (on / off / emit)
    // ctx.slots — named DOM containers: "sidebar", "header", "thinking"
    // ctx.state — function that returns current state snapshot
    // ctx.api   — HTTP client (validateRepo, submitRepo, getSession, clearSession, sendMessage)
  },

  // Shorthand — each key is an event name, value is the handler.
  hooks: {
    "thinking:start": (payload, ctx) => { /* ... */ },
    "thinking:stop":  (payload, ctx) => { /* ... */ },
  },
};
```

## Available Events

| Event | Payload | When |
|-------|---------|------|
| `boot:ready` | `{ ctx }` | App bootstrap complete |
| `state:change` | state object | Any state mutation |
| `view:change` | `{ from, to }` | View switched (input/analysis/chat) |
| `thinking:start` | `{}` | Agent begins thinking |
| `thinking:stop` | `{}` | Agent stops thinking |
| `stream:start` | `{ messageId, kind, type }` | Streaming message begins |
| `stream:delta` | `{ messageId, delta }` | New text chunk from Agent |
| `stream:end` | `{ messageId }` | Streaming finished |
| `message:append` | MessageDto | Final message added to thread |
| `message:render` | `{ msg, root }` | A message DOM node was created (mutate root) |
| `sse:event` | `{ kind, evt }` | Raw SSE event received |
| `error:user` | UserFacingErrorDto | Server-side error |
| `debug:entry` | debug entry object | New debug log entry |

## Plugin Slots (DOM containers)

- **`thinking`** — shown above the chat composer when Agent is thinking
- **`header`** — below the stage header
- **`sidebar`** — in the sidebar panel labeled "extensions"

Access via `ctx.slots.thinking`, etc.

## Runtime Registration

Plugins can also be registered at any time via the global API:

```js
window.RepoTutor.registerPlugin({ name: "late-plugin", init(ctx) { /* ... */ } });
```

## Example

See `thinking_dots.js` in this directory.
