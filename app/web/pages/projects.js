import { managementFetch } from "../api.js";
import { badge, byId, formatDate, renderTable, setButtonBusy, showToast } from "../components.js";
import { state } from "../state.js";

let projectsChanged = () => {};
let confirmAction = async () => false;

function filteredProjects() {
  const query = byId("project-search").value.trim().toLocaleLowerCase("vi");
  const status = byId("project-status-filter").value;
  return state.projects.filter((project) =>
    (!query || project.name.toLocaleLowerCase("vi").includes(query) || project.id.includes(query)) &&
    (!status || project.status === status)
  );
}

export function renderProjects() {
  renderTable(byId("projects"), [
    { label: "Project", render: (row) => row.name },
    { label: "Status", render: (row) => badge(row.status) },
    { label: "Updated", render: (row) => formatDate(row.updated_at) },
  ], filteredProjects(), {
    emptyMessage: "Không tìm thấy project.",
    onRowClick: state.principal?.role === "platform_admin" ? selectProject : null,
  });
}

export function applyProjectPermissions() {
  const platformAdmin = state.principal?.role === "platform_admin";
  byId("new-project-button").hidden = !platformAdmin;
  byId("delete-project-button").hidden = !platformAdmin;
  if (!platformAdmin) byId("project-detail").hidden = true;
}

export async function loadProjects() {
  const body = await managementFetch("/projects");
  state.projects = body.data;
  if (state.selectedProjectId && !state.projects.some((project) => project.id === state.selectedProjectId)) state.selectedProjectId = "";
  renderProjects();
  projectsChanged();
}

function selectProject(project) {
  state.selectedProjectId = project.id;
  const form = byId("project-policy-form");
  form.elements.project_id.value = project.id;
  for (const field of ["version", "name", "status"]) {
    form.elements[field].value = project[field];
  }
  byId("project-detail-name").textContent = project.name;
  byId("project-detail-id").textContent = project.id;
  byId("project-detail-status").textContent = project.status;
  byId("project-detail-status").className = `badge ${project.status}`;
  byId("project-detail").hidden = false;
  projectsChanged();
  byId("project-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

function projectPayload(form) {
  return {
    name: form.get("name"),
  };
}

export function initProjects(onProjectsChanged, confirm) {
  projectsChanged = onProjectsChanged;
  confirmAction = confirm;
  byId("project-search").addEventListener("input", renderProjects);
  byId("project-status-filter").addEventListener("change", renderProjects);
  byId("refresh-projects").addEventListener("click", () => loadProjects().catch((error) => showToast(error.message, true)));
  byId("new-project-button").addEventListener("click", () => byId("project-dialog").showModal());
  byId("delete-project-button").addEventListener("click", async () => {
    const projectId = byId("project-policy-form").elements.project_id.value;
    const name = byId("project-detail-name").textContent;
    if (!projectId) return;
    if (!await confirmAction("Xóa project?", `Project ${name} chỉ được xóa khi không có usage và mọi API key đã revoked. Thao tác này không thể hoàn tác.`)) return;
    const button = byId("delete-project-button");
    setButtonBusy(button, true, "Đang xóa…");
    try {
      await managementFetch(`/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
      state.selectedProjectId = "";
      byId("project-detail").hidden = true;
      await loadProjects();
      showToast("Đã xóa project và các API key đã revoked.");
    } catch (error) {
      showToast(error.code === "project_not_empty" ? "Project còn usage hoặc API key chưa revoked." : error.message, true);
    } finally { setButtonBusy(button, false); }
  });
  byId("project-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    // Event.currentTarget không còn bảo đảm tồn tại sau await; giữ form để POST xong vẫn reset được.
    const projectForm = event.currentTarget;
    const button = projectForm.querySelector('button[type="submit"]');
    setButtonBusy(button, true);
    try {
      await managementFetch("/projects", { method: "POST", body: JSON.stringify(projectPayload(new FormData(projectForm))) });
      byId("project-dialog").close();
      projectForm.reset();
      showToast("Đã tạo project.");
      await loadProjects();
    } catch (error) { showToast(error.message, true); }
    finally { setButtonBusy(button, false); }
  });
  byId("project-policy-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const projectId = form.get("project_id");
    if (!projectId || projectId === "undefined") {
      showToast("Không xác định được project. Hãy chọn lại project.", true);
      return;
    }
    setButtonBusy(button, true);
    try {
      await managementFetch(`/projects/${encodeURIComponent(projectId)}`, {
        method: "PATCH",
        body: JSON.stringify({ ...projectPayload(form), status: form.get("status"), version: Number(form.get("version")) }),
      });
      showToast("Đã cập nhật project.");
      await loadProjects();
      const updated = state.projects.find((project) => project.id === projectId);
      if (updated) selectProject(updated);
    } catch (error) {
      showToast(error.status === 409 ? "Project đã thay đổi. Hãy tải lại và thử lại." : error.message, true);
    } finally { setButtonBusy(button, false); }
  });
}
