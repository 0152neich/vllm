import { state } from "./state.js";

let unauthorizedHandler = () => {};

export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}

async function parseResponse(response) {
  // DELETE thành công theo HTTP chuẩn trả 204 và không có JSON để parse.
  if (response.status === 204) return null;
  let body;
  try {
    body = await response.json();
  } catch (_) {
    throw new Error(`Gateway trả response không hợp lệ (HTTP ${response.status}).`);
  }
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler();
    const error = new Error(body.error?.message || `HTTP ${response.status}`);
    error.status = response.status;
    error.code = body.error?.code;
    throw error;
  }
  return body;
}

export async function managementFetch(path, options = {}) {
  if (!state.managementKey) throw new Error("Hãy nhập management key trước.");
  const response = await fetch(`/management/v1${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${state.managementKey}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  return parseResponse(response);
}

export async function chatCompletion(runtimeKey, payload) {
  const response = await fetch("/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${runtimeKey}`, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}
