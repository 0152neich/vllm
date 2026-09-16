import { chatCompletion } from "../api.js";
import { byId, element, setButtonBusy, showToast } from "../components.js";
import { state } from "../state.js";

function renderResponse() {
  const root = byId("playground-output");
  const body = state.rawPlaygroundResponse;
  if (!body) return;
  root.className = "assistant-output";
  root.textContent = state.showRawResponse ? JSON.stringify(body, null, 2) : (body.choices?.[0]?.message?.content || "Response không có nội dung.");
  byId("raw-toggle").textContent = state.showRawResponse ? "Assistant view" : "Raw JSON";
}

export function syncPlaygroundModels(models) {
  byId("playground-model").replaceChildren(...models.map((model) => element("option", { value: model, text: model })));
}

export function initPlayground() {
  byId("raw-toggle").addEventListener("click", () => { state.showRawResponse = !state.showRawResponse; renderResponse(); });
  byId("playground-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const startedAt = performance.now();
    setButtonBusy(button, true, "Đang chờ model…");
    byId("playground-output").className = "assistant-output empty-state";
    byId("playground-output").textContent = "Đang chờ model…";
    try {
      const body = await chatCompletion(form.get("runtime_key"), {
        model: form.get("model"),
        messages: [{ role: "system", content: form.get("system_prompt") }, { role: "user", content: form.get("user_prompt") }],
        temperature: Number(form.get("temperature")),
        max_tokens: Number(form.get("max_tokens")),
      });
      state.rawPlaygroundResponse = body;
      state.showRawResponse = false;
      renderResponse();
      const elapsed = Math.round(performance.now() - startedAt);
      const usage = body.usage || {};
      byId("playground-meta").replaceChildren(
        element("span", { text: `${elapsed} ms` }),
        element("span", { text: `${usage.prompt_tokens ?? "—"} input tokens` }),
        element("span", { text: `${usage.completion_tokens ?? "—"} output tokens` }),
        element("span", { text: body.id || "No request ID" }),
      );
    } catch (error) {
      byId("playground-output").textContent = error.message;
      showToast(error.message, true);
    } finally { setButtonBusy(button, false); }
  });
}
