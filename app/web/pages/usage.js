import { managementFetch } from "../api.js";
import { byId, element, formatDate, formatNumber, renderLineChart, renderTable, showToast } from "../components.js";
import { state } from "../state.js";

export async function loadUsage() {
  const hours = Number(byId("usage-hours").value);
  const scope = state.selectedProjectId ? `&project_id=${encodeURIComponent(state.selectedProjectId)}` : "";
  try {
    const body = await managementFetch(`/usage/summary?hours=${hours}${scope}`);
    const totals = body.data.totals;
    byId("usage-requests").textContent = formatNumber(totals.requests);
    byId("usage-tokens").textContent = formatNumber(totals.total_tokens);
    byId("usage-errors").textContent = totals.requests ? `${((totals.failed_requests / totals.requests) * 100).toFixed(1)}%` : "0%";
    byId("usage-latency").textContent = `${formatNumber(totals.avg_latency_ms)} ms`;
    renderLineChart(byId("usage-chart"), body.data.series);
    await loadUsageRows();
  } catch (error) { showToast(error.message, true); }
}

async function loadUsageRows() {
  if (!state.selectedProjectId) {
    byId("usage-output").replaceChildren(element("div", { className: "empty-state", text: "Chọn một project trên thanh tiêu đề để xem request log." }));
    return;
  }
  const body = await managementFetch(`/projects/${encodeURIComponent(state.selectedProjectId)}/usage?limit=100`);
  renderTable(byId("usage-output"), [
    { label: "Request ID", render: (row) => element("span", { className: "mono", text: row.request_id }) },
    { label: "Model", key: "model" },
    { label: "Status", render: (row) => {
      const className = row.status_code < 400 ? "badge" : "badge error";
      return element("span", { className, text: String(row.status_code) });
    } },
    { label: "Latency", render: (row) => `${row.latency_ms} ms` },
    { label: "Input", render: (row) => formatNumber(row.prompt_tokens) },
    { label: "Output", render: (row) => formatNumber(row.completion_tokens) },
    { label: "Time", render: (row) => formatDate(row.created_at) },
  ], body.data, { emptyMessage: "Project chưa có request." });
}

export function initUsage() {
  byId("usage-hours").addEventListener("change", loadUsage);
  byId("refresh-usage").addEventListener("click", loadUsage);
}
