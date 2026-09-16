import { managementFetch } from "../api.js";
import { byId, element, formatDate, formatNumber, renderLineChart, renderTable, showToast } from "../components.js";
import { state } from "../state.js";

export async function loadOverview() {
  const hours = Number(byId("overview-hours").value);
  const projectQuery = state.selectedProjectId ? `&project_id=${encodeURIComponent(state.selectedProjectId)}` : "";
  try {
    const body = await managementFetch(`/dashboard?hours=${hours}${projectQuery}`);
    const data = body.data;
    const totals = data.usage.totals;
    byId("metric-requests").textContent = formatNumber(totals.requests);
    byId("metric-success").textContent = `${formatNumber(totals.successful_requests)} thành công`;
    byId("metric-tokens").textContent = formatNumber(totals.total_tokens);
    byId("metric-latency").textContent = `${formatNumber(totals.avg_latency_ms)} ms`;
    byId("metric-keys").textContent = formatNumber(data.keys.active);
    byId("metric-projects").textContent = `${formatNumber(data.projects.total)} projects`;
    renderLineChart(byId("overview-chart"), data.usage.series);
    const statuses = ["active", "suspended", "archived"].map((status) =>
      element("div", { className: "status-row" }, [
        element("span", { text: status[0].toUpperCase() + status.slice(1) }),
        element("strong", { text: formatNumber(data.projects[status]) }),
      ])
    );
    byId("project-status").replaceChildren(...statuses);
    await loadRecentRequests();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loadRecentRequests() {
  const root = byId("overview-recent");
  if (!state.selectedProjectId) {
    root.replaceChildren(element("div", { className: "empty-state", text: "Chọn một project để xem request gần đây." }));
    return;
  }
  const body = await managementFetch(`/projects/${encodeURIComponent(state.selectedProjectId)}/usage?limit=8`);
  renderTable(root, [
    { label: "Request ID", render: (row) => element("span", { className: "mono", text: row.request_id }) },
    { label: "Model", key: "model" },
    { label: "Status", render: (row) => String(row.status_code) },
    { label: "Latency", render: (row) => `${row.latency_ms} ms` },
    { label: "Tokens", render: (row) => formatNumber(row.total_tokens) },
    { label: "Time", render: (row) => formatDate(row.created_at) },
  ], body.data, { emptyMessage: "Project chưa có request." });
}

export function initOverview() {
  byId("overview-hours").addEventListener("change", loadOverview);
  byId("refresh-overview").addEventListener("click", loadOverview);
}
