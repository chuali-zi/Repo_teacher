import { el } from "../js/dom.js";
import { report } from "../js/errors.js";

function buildSidecarCard() {
  const answerLabel = el("div", { class: "sidecar-answer-panel__label" }, "小回答");
  const answerText = el(
    "p",
    { class: "sidecar-answer-panel__text" },
    "适合问术语、概念和一句话听不懂的地方。",
  );
  const answerPanel = el(
    "section",
    { class: "sidecar-answer-panel", "aria-live": "polite", dataset: { state: "idle" } },
    answerLabel,
    answerText,
  );

  const input = el("textarea", {
    rows: "3",
    placeholder: "比如：控制反转到底是什么意思？",
    spellcheck: "false",
  });
  const submit = el("button", { class: "sidecar-form__submit", type: "submit" }, "问一下");
  const form = el(
    "form",
    { class: "sidecar-form", autocomplete: "off" },
    el("label", { class: "sidecar-form__label" }, "术语 / 疑惑"),
    input,
    submit,
  );

  const root = el(
    "section",
    { class: "sidecar-card sidecar-card--sidebar", dataset: { pluginRoot: "sidecar-explainer" } },
    el(
      "div",
      { class: "sidecar-card__head" },
      el("p", { class: "sidecar-card__eyebrow" }, "SIDE NOTE"),
      el("h3", null, "术语解释器"),
      el("p", { class: "sidecar-card__note" }, "只看你当前这句话，用老师口吻把术语讲成白话。"),
    ),
    form,
    answerPanel,
  );

  return { root, form, input, submit, answerLabel, answerText, answerPanel };
}

export default {
  name: "sidecar-explainer",
  init(ctx) {
    const host = ctx.slots?.sidebar;
    if (!host || host.querySelector('[data-plugin-root="sidecar-explainer"]')) return;

    const api = ctx.api;
    const { root, form, input, submit, answerLabel, answerText, answerPanel } = buildSidecarCard();
    host.prepend(root);

    let submitting = false;

    const paint = (state, text) => {
      answerPanel.dataset.state = state;
      if (state === "loading") answerLabel.textContent = "老师在压缩说法";
      else if (state === "error") answerLabel.textContent = "暂时没答上来";
      else answerLabel.textContent = "小回答";
      answerText.textContent = text;
    };

    const syncSubmit = () => {
      submit.disabled = submitting || input.value.trim().length === 0;
    };

    const autoresize = () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
    };

    const run = async () => {
      const question = input.value.trim();
      if (!question || submitting) return;
      if (!api?.explainSidecar) {
        paint("error", "术语解释接口尚未接入。");
        return;
      }

      submitting = true;
      syncSubmit();
      paint("loading", "先把问题拆小一点，马上给你一个短回答。");

      try {
        const res = await api.explainSidecar(question);
        paint("ready", res.data.answer);
        input.value = "";
        autoresize();
      } catch (err) {
        const message = (err.payload && err.payload.message) || err.message || "小回答器暂时不可用。";
        paint("error", message);
        report({ source: "sidecar", level: "warn", message, where: "sidecar-explainer", error: err });
      } finally {
        submitting = false;
        syncSubmit();
      }
    };

    input.addEventListener("input", () => {
      autoresize();
      syncSubmit();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      event.preventDefault();
      run();
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      run();
    });

    submit.disabled = true;
  },
};
