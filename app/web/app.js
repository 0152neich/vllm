import { managementFetch, onUnauthorized } from "./api.js";
import { byId, element, showToast } from "./components.js";
import { applyKeyPermissions, initKeys, loadKeys, syncKeyProjectOptions } from "./pages/keys.js";
import { initOverview, loadOverview } from "./pages/overview.js";
import { initPlayground, syncPlaygroundModels } from "./pages/playground.js";
import { applyProjectPermissions, initProjects, loadProjects, renderProjects } from "./pages/projects.js";
import { initSettings, loadSettings } from "./pages/settings.js";
import { initUsage, loadUsage } from "./pages/usage.js";
import { MANAGEMENT_KEY_STORAGE, state, THEME_STORAGE } from "./state.js";

const routes = {
  overview: ["Overview", "Theo dõi hoạt động của Gateway."],
  projects: ["Projects", "Quản lý ứng dụng, trạng thái và nhóm API key."],
  keys: ["API Keys", "Cấp và thu hồi credential theo project."],
  usage: ["Usage", "Phân tích request, token và độ trễ."],
  playground: ["Playground", "Kiểm thử Chat Completions trên Gateway."],
  settings: ["Settings", "Thông tin cấu hình public và trạng thái hệ thống."],
};

function readSessionKey() {
  try { return sessionStorage.getItem(MANAGEMENT_KEY_STORAGE) || ""; }
  catch (_) { return ""; }
}

function persistSessionKey(value) {
  try {
    if (value) sessionStorage.setItem(MANAGEMENT_KEY_STORAGE, value);
    else sessionStorage.removeItem(MANAGEMENT_KEY_STORAGE);
  } catch (_) {
    showToast("Trình duyệt không cho lưu phiên; reload sẽ cần đăng nhập lại.", true);
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem(THEME_STORAGE, theme); } catch (_) { /* Preference không bắt buộc. */ }
}

function initialTheme() {
  try { return localStorage.getItem(THEME_STORAGE) || "light"; }
  catch (_) { return "light"; }
}

function logout(message = "") {
  state.managementKey = "";
  state.projects = [];
  state.models = [];
  state.selectedProjectId = "";
  state.principal = null;
  state.issuedPlaintext = "";
  state.rawPlaygroundResponse = null;
  state.showRawResponse = false;
  byId("playground-form").elements.runtime_key.value = "";
  byId("issued-key").textContent = "";
  document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
  persistSessionKey("");
  byId("app-shell").hidden = true;
  byId("login-screen").hidden = false;
  byId("management-key").value = "";
  byId("management-key").focus();
  if (message) showToast(message, true);
}

onUnauthorized(() => logout("Phiên quản trị không hợp lệ hoặc đã hết hạn."));

function syncProjectSelectors() {
  const select = byId("global-project");
  const options = [element("option", { value: "", text: "Tất cả project" }), ...state.projects.map((project) => element("option", { value: project.id, text: project.name }))];
  select.replaceChildren(...options);
  select.value = state.selectedProjectId;
  syncKeyProjectOptions();
  syncPlaygroundModels(state.models);
}

async function connect(key) {
  state.managementKey = key;
  persistSessionKey(key);
  try {
    const status = await managementFetch("/system/status");
    state.principal = status.data.principal;
    state.models = status.data.models.map((model) => model.id);
    state.selectedProjectId = state.principal.project_id || "";
    applyProjectPermissions();
    applyKeyPermissions();
    await loadProjects();
    byId("login-screen").hidden = true;
    byId("app-shell").hidden = false;
    byId("connection").textContent = "Đã kết nối";
    byId("connection-dot").className = "status-dot";
    await navigate(currentHashRoute(), false);
  } catch (error) {
    if (state.managementKey) logout(error.message);
  }
}

function currentHashRoute() {
  const candidate = window.location.hash.replace(/^#\/?/, "");
  return routes[candidate] ? candidate : "overview";
}

async function loadRoute(route) {
  if (route === "overview") await loadOverview();
  else if (route === "projects") renderProjects();
  else if (route === "keys") await loadKeys();
  else if (route === "usage") await loadUsage();
  else if (route === "settings") await loadSettings();
}

async function navigate(route, updateHash = true) {
  if (!routes[route]) route = "overview";
  state.currentRoute = route;
  if (updateHash && window.location.hash !== `#${route}`) window.location.hash = route;
  document.querySelectorAll("[data-page]").forEach((page) => { page.hidden = page.dataset.page !== route; });
  document.querySelectorAll("[data-route]").forEach((item) => item.classList.toggle("active", item.dataset.route === route));
  byId("page-title").textContent = routes[route][0];
  byId("page-description").textContent = routes[route][1];
  document.body.classList.remove("sidebar-open");
  try { await loadRoute(route); }
  catch (error) { showToast(error.message, true); }
}

function confirmDialog(title, message) {
  return new Promise((resolve) => {
    const dialog = byId("confirm-dialog");
    byId("confirm-title").textContent = title;
    byId("confirm-message").textContent = message;
    const accept = byId("confirm-accept");
    const cancel = byId("confirm-cancel");
    const finish = (result) => {
      accept.onclick = null;
      cancel.onclick = null;
      dialog.close();
      resolve(result);
    };
    accept.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
    dialog.showModal();
  });
}

initOverview();
initProjects(syncProjectSelectors, confirmDialog);
initKeys(confirmDialog);
initUsage();
initPlayground();
initSettings();
applyTheme(initialTheme());

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const key = byId("management-key").value.trim();
  byId("management-key").value = "";
  await connect(key);
});
byId("logout-button").addEventListener("click", () => logout());
byId("theme-button").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
byId("menu-button").addEventListener("click", () => document.body.classList.add("sidebar-open"));
byId("sidebar-backdrop").addEventListener("click", () => document.body.classList.remove("sidebar-open"));
byId("global-project").addEventListener("change", async (event) => {
  state.selectedProjectId = event.target.value;
  syncKeyProjectOptions();
  await loadRoute(state.currentRoute);
});
document.querySelectorAll("[data-route]").forEach((item) => item.addEventListener("click", () => navigate(item.dataset.route)));
document.querySelectorAll("[data-go]").forEach((item) => item.addEventListener("click", () => navigate(item.dataset.go)));
document.querySelectorAll(".dialog-close").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
byId("issued-key-dialog").addEventListener("close", () => {
  state.issuedPlaintext = "";
  byId("issued-key").textContent = "";
});
window.addEventListener("hashchange", () => { if (state.managementKey) navigate(currentHashRoute(), false); });

const restoredKey = readSessionKey();
if (restoredKey) connect(restoredKey);
else logout();
