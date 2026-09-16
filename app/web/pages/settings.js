import { managementFetch } from "../api.js";
import { badge, byId, element, renderTable, showToast } from "../components.js";

export async function loadSettings() {
  try {
    const body = await managementFetch("/system/status");
    const data = body.data;
    const serviceRows = [
      ["Service", data.service.name], ["Version", data.service.version],
      ["Runtime API", data.service.runtime_prefix], ["Management API", data.service.management_prefix],
    ];
    byId("service-settings").replaceChildren(...serviceRows.flatMap(([name, value]) => [element("dt", { text: name }), element("dd", { text: value })]));
    byId("dependency-status").replaceChildren(...Object.entries(data.dependencies).map(([name, status]) => element("div", { className: "status-row" }, [element("span", { text: name }), badge(status)])));
    renderTable(byId("model-settings"), [
      { label: "Public alias", render: (row) => element("span", { className: "mono", text: row.id }) },
      { label: "Upstream model", render: (row) => element("span", { className: "mono", text: row.upstream_model }) },
    ], data.models);
  } catch (error) { showToast(error.message, true); }
}

export function initSettings() {
  byId("refresh-settings").addEventListener("click", loadSettings);
}
