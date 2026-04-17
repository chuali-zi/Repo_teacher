// Example plugin: "Thinking Dots"
// Renders a small animated icon in the thinking plugin slot when the Agent is thinking.
//
// To enable: add to index.html before closing </body>:
//   <script type="module" data-plugin="./plugins/thinking_dots.js"></script>

export default {
  name: "thinking-dots",
  init(ctx) {
    const host = ctx.slots?.thinking;
    if (!host) return;

    let dotBox = null;

    ctx.bus.on("thinking:start", () => {
      if (dotBox) return;
      dotBox = document.createElement("div");
      dotBox.innerHTML = `
        <div style="
          display: flex; align-items: center; gap: 10px;
          padding: 10px 0; font-family: var(--f-display); font-style: italic;
          color: var(--lamp); font-size: 14px;
        ">
          <span>正在凝视仓库</span>
          <span class="thinking__dots">
            <span></span><span></span><span></span>
          </span>
        </div>`;
      host.appendChild(dotBox);
      host.parentElement.hidden = false;
    });

    ctx.bus.on("thinking:stop", () => {
      if (dotBox) {
        dotBox.remove();
        dotBox = null;
      }
      if (host.children.length === 0) host.parentElement.hidden = true;
    });
  },
};
