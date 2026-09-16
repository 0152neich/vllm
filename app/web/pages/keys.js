import { managementFetch } from "../api.js";
import { badge, byId, element, formatDate, renderTable, setButtonBusy, showToast } from "../components.js";
import { state } from "../state.js";

let confirmAction = async () => false;
let selectedKey = null;
let createTags = [];
let settingsTags = [];

async function copyPlaintext(value) {
  if (window.isSecureContext && navigator.clipboard) {
    try { await navigator.clipboard.writeText(value); return true; } catch (_) { /* fallback */ }
  }
  const input = element("textarea", { readonly: "", "aria-hidden": "true" });
  input.value = value; input.style.position = "fixed"; input.style.opacity = "0";
  document.body.append(input); input.select(); const copied = document.execCommand("copy"); input.remove();
  return copied;
}

function parseSettings(form, tags) {
  let metadata;
  try { metadata = JSON.parse(String(form.get("metadata") || "{}").trim() || "{}"); }
  catch (_) { throw new Error("Metadata phải là JSON object hợp lệ."); }
  if (metadata === null || Array.isArray(metadata) || typeof metadata !== "object") throw new Error("Metadata phải là JSON object.");
  const integerOrNull = (name) => { const value = String(form.get(name) || "").trim(); return value ? Number(value) : null; };
  const models = String(form.get("allowed_models") || "").split(",").map((model) => model.trim()).filter(Boolean);
  return {
    tpm: integerOrNull("tpm"), rpm: integerOrNull("rpm"),
    allowed_models: models.length ? models : null,
    max_concurrency: integerOrNull("max_concurrency"),
    max_input_characters: integerOrNull("max_input_characters"),
    max_output_tokens: integerOrNull("max_output_tokens"),
    timeout_seconds: integerOrNull("timeout_seconds"),
    metadata, tags,
  };
}

function renderTags(rootId, tags, onDelete = null) {
  byId(rootId).replaceChildren(...(tags.length ? tags.map((tag) => element("span", { className: "tag", text: tag }, onDelete ? [element("button", { type: "button", text: "×", "aria-label": `Xóa tag ${tag}`, onclick: () => onDelete(tag) })] : [])) : [element("small", { text: "Chưa có tags" })]));
}

function bindTagInput(inputId, rootId, getTags, setTags) {
  byId(inputId).addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== ",") return;
    event.preventDefault();
    const tag = event.currentTarget.value.trim();
    if (tag && !getTags().includes(tag)) setTags([...getTags(), tag]);
    event.currentTarget.value = "";
  });
  const refresh = () => renderTags(rootId, getTags(), (tag) => setTags(getTags().filter((item) => item !== tag)));
  return refresh;
}

const projectFor = (key) => state.projects.find((project) => project.id === key.project_id);

function setDetailTab(tab) {
  document.querySelectorAll("[data-key-tab]").forEach((button) => button.classList.toggle("active", button.dataset.keyTab === tab));
  byId("key-overview").hidden = tab !== "overview";
  byId("key-settings").hidden = tab !== "settings";
}

async function selectKey(row) {
  const body = await managementFetch(`/keys/${encodeURIComponent(row.id)}`);
  selectedKey = body.data;
  const key = selectedKey; const project = projectFor(key);
  byId("keys-list-panel").hidden = true; byId("key-detail").hidden = false;
  byId("key-detail-name").textContent = key.name; byId("key-detail-prefix").textContent = `Key prefix: ${key.prefix}`;
  byId("key-detail-status").textContent = key.status; byId("key-detail-status").className = `badge ${key.status}`;
  const facts = [["Project", project?.name || key.project_id], ["Created", formatDate(key.created_at)], ["Last active", formatDate(key.last_used_at)], ["Expires", key.expires_at ? formatDate(key.expires_at) : "Never"]];
  byId("key-detail-facts").replaceChildren(...facts.map(([label, value]) => element("div", { className: "key-fact" }, [element("span", { text: label }), element("strong", { text: value })])));
  byId("key-detail-limits").textContent = `TPM: ${key.tpm ?? "Unlimited"} · RPM: ${key.rpm}`;
  byId("key-detail-limit-source").textContent = "Theo API key";
  byId("key-detail-models").textContent = key.allowed_models.join(", ");
  byId("key-detail-request-policy").textContent = `Input ${key.max_input_characters} · Output ${key.max_output_tokens} · ${key.timeout_seconds}s · ${key.max_concurrency} concurrent`;
  renderTags("key-detail-tags", key.tags || []);
  const platformAdmin = state.principal?.role === "platform_admin";
  byId("key-settings-form").hidden = !platformAdmin; byId("key-settings-readonly").hidden = platformAdmin; byId("detail-revoke-key").hidden = key.status !== "active";
  if (platformAdmin) {
    const form = byId("key-settings-form"); form.elements.allowed_models.value = key.allowed_models.join(", "); form.elements.tpm.value = key.tpm ?? ""; form.elements.rpm.value = key.rpm; form.elements.max_concurrency.value = key.max_concurrency; form.elements.max_input_characters.value = key.max_input_characters; form.elements.max_output_tokens.value = key.max_output_tokens; form.elements.timeout_seconds.value = key.timeout_seconds; form.elements.metadata.value = JSON.stringify(key.metadata || {}, null, 2);
    settingsTags = [...(key.tags || [])];
    const refreshSettingsTags = () => renderTags("key-settings-tags", settingsTags, (tag) => { settingsTags = settingsTags.filter((item) => item !== tag); refreshSettingsTags(); });
    refreshSettingsTags();
  }
  setDetailTab("overview");
}

async function revokeSelectedKey() {
  if (!selectedKey || selectedKey.status !== "active") return;
  if (!await confirmAction("Thu hồi API key?", `Key ${selectedKey.name} (${selectedKey.prefix}) sẽ ngừng hoạt động ngay.`)) return;
  await managementFetch(`/keys/${encodeURIComponent(selectedKey.id)}/revoke`, { method: "POST" });
  showToast("Đã thu hồi API key."); selectedKey = null; byId("key-detail").hidden = true; byId("keys-list-panel").hidden = false; await loadKeys();
}

export function syncKeyProjectOptions() {
  const filter = byId("key-project-filter"); const projectInput = byId("key-form").elements.project_id;
  const active = state.projects.filter((project) => project.status === "active");
  filter.replaceChildren(element("option", { value: "", text: "Tất cả project" }), ...state.projects.map((project) => element("option", { value: project.id, text: project.name })));
  projectInput.replaceChildren(element("option", { value: "", text: "Chọn project active" }), ...active.map((project) => element("option", { value: project.id, text: project.name })));
  if (state.selectedProjectId) { filter.value = state.selectedProjectId; if (active.some((project) => project.id === state.selectedProjectId)) projectInput.value = state.selectedProjectId; }
  byId("new-key-button").disabled = active.length === 0; byId("new-key-button").title = active.length ? "" : "Không có project active để cấp key"; applyKeyPermissions();
}

export function applyKeyPermissions() {
  const option = byId("key-form").elements.kind.querySelector('option[value="management"]'); const platformAdmin = state.principal?.role === "platform_admin";
  option.hidden = !platformAdmin; option.disabled = !platformAdmin;
  byId("key-optional-settings").hidden = !platformAdmin;
  if (!platformAdmin && byId("key-form").elements.kind.value === "management") byId("key-form").elements.kind.value = "runtime";
}

export async function loadKeys() {
  const query = new URLSearchParams({ limit: "1000" }); const projectId = byId("key-project-filter").value || state.selectedProjectId;
  for (const [field, value] of [["project_id", projectId], ["kind", byId("key-kind-filter").value], ["status", byId("key-status-filter").value]]) if (value) query.set(field, value);
  const body = await managementFetch(`/keys?${query}`);
  renderTable(byId("keys-table"), [
    { label: "Name", key: "name" }, { label: "Prefix", render: (row) => element("span", { className: "mono", text: row.prefix }) }, { label: "Type", key: "kind" }, { label: "Status", render: (row) => badge(row.status) }, { label: "RPM", key: "rpm" }, { label: "Tags", render: (row) => (row.tags || []).join(", ") || "—" }, { label: "Last used", render: (row) => formatDate(row.last_used_at) },
  ], body.data, { emptyMessage: "Chưa có API key phù hợp.", onRowClick: (row) => selectKey(row).catch((error) => showToast(error.message, true)) });
}

export function initKeys(confirm) {
  confirmAction = confirm;
  const refreshCreateTags = bindTagInput("key-create-tag-input", "key-create-tags", () => createTags, (value) => { createTags = value; refreshCreateTags(); });
  const refreshSettingsTags = bindTagInput("key-settings-tag-input", "key-settings-tags", () => settingsTags, (value) => { settingsTags = value; refreshSettingsTags(); });
  byId("new-key-button").addEventListener("click", () => { syncKeyProjectOptions(); createTags = []; refreshCreateTags(); byId("key-dialog").showModal(); });
  for (const id of ["key-project-filter", "key-kind-filter", "key-status-filter"]) byId(id).addEventListener("change", () => loadKeys().catch((error) => showToast(error.message, true)));
  byId("refresh-keys").addEventListener("click", () => loadKeys().catch((error) => showToast(error.message, true)));
  byId("back-to-keys").addEventListener("click", () => { selectedKey = null; byId("key-detail").hidden = true; byId("keys-list-panel").hidden = false; });
  byId("detail-revoke-key").addEventListener("click", () => revokeSelectedKey().catch((error) => showToast(error.message, true)));
  document.querySelectorAll("[data-key-tab]").forEach((button) => button.addEventListener("click", () => setDetailTab(button.dataset.keyTab)));
  byId("key-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const button = formElement.querySelector('button[type="submit"]');
    try { const expiresAt = form.get("expires_at"); const payload = { name: form.get("name"), kind: form.get("kind"), expires_at: expiresAt ? new Date(expiresAt).toISOString() : null, ...parseSettings(form, createTags) }; setButtonBusy(button, true); const body = await managementFetch(`/projects/${encodeURIComponent(String(form.get("project_id")))}/keys`, { method: "POST", body: JSON.stringify(payload) }); state.issuedPlaintext = body.data.api_key; byId("issued-key").textContent = `Key ID: ${body.data.id}\nAPI key: ${body.data.api_key}`; byId("key-dialog").close(); byId("issued-key-dialog").showModal(); showToast("Đã tạo API key."); await loadKeys(); formElement.reset(); }
    catch (error) { showToast(error.message, true); } finally { setButtonBusy(button, false); }
  });
  byId("key-settings-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!selectedKey) return; const formElement = event.currentTarget; const button = formElement.querySelector('button[type="submit"]');
    try { setButtonBusy(button, true); await managementFetch(`/keys/${encodeURIComponent(selectedKey.id)}`, { method: "PATCH", body: JSON.stringify(parseSettings(new FormData(formElement), settingsTags)) }); showToast("Đã lưu key settings."); await selectKey(selectedKey); await loadKeys(); }
    catch (error) { showToast(error.message, true); } finally { setButtonBusy(button, false); }
  });
  byId("copy-key-button").addEventListener("click", async () => { try { const copied = await copyPlaintext(state.issuedPlaintext); showToast(copied ? "Đã sao chép API key." : "Không thể sao chép tự động.", !copied); } catch (_) { showToast("Không thể truy cập clipboard. Hãy sao chép thủ công.", true); } });
}
