export const byId = (id) => document.getElementById(id);

export function element(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "className") node.className = value;
    else if (name === "text") node.textContent = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value);
  }
  for (const child of children) node.append(child);
  return node;
}

export function showToast(message, error = false) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.className = error ? "visible error" : "visible";
  window.setTimeout(() => { toast.className = ""; }, 3500);
}

export function badge(status) {
  return element("span", { className: `badge ${status}`, text: status });
}

export function formatNumber(value) {
  return new Intl.NumberFormat("vi-VN").format(Number(value || 0));
}

export function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function empty(message) {
  return element("div", { className: "empty-state", text: message });
}

export function renderTable(root, columns, rows, options = {}) {
  if (!rows.length) {
    root.replaceChildren(empty(options.emptyMessage || "Chưa có dữ liệu."));
    return;
  }
  const head = element("thead", {}, [element("tr", {}, columns.map((column) => element("th", { text: column.label })))]);
  const bodyRows = rows.map((row) => {
    const tr = element("tr", { className: options.onRowClick ? "clickable" : "" });
    if (options.onRowClick) tr.addEventListener("click", () => options.onRowClick(row));
    for (const column of columns) {
      const cell = element("td");
      const value = column.render ? column.render(row) : row[column.key];
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? "—";
      tr.append(cell);
    }
    return tr;
  });
  root.replaceChildren(element("table", {}, [head, element("tbody", {}, bodyRows)]));
}

export function renderLineChart(root, series) {
  if (!series.length) {
    root.className = "chart empty-state";
    root.textContent = "Chưa có usage trong khoảng này.";
    return;
  }
  root.className = "chart";
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 800 250");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Biểu đồ request theo thời gian");
  for (const y of [30, 90, 150, 210]) {
    const line = document.createElementNS(ns, "line");
    for (const [key, value] of Object.entries({ x1: 20, y1: y, x2: 780, y2: y, class: "chart-grid" })) line.setAttribute(key, value);
    svg.append(line);
  }
  const maximum = Math.max(...series.map((point) => point.requests), 1);
  const coordinates = series.map((point, index) => {
    const x = 20 + (index * 760) / Math.max(series.length - 1, 1);
    const y = 210 - (point.requests / maximum) * 180;
    return [x, y];
  });
  const pathValue = coordinates.map(([x, y], index) => `${index ? "L" : "M"}${x},${y}`).join(" ");
  const area = document.createElementNS(ns, "path");
  area.setAttribute("d", `${pathValue} L${coordinates.at(-1)[0]},210 L20,210 Z`);
  area.setAttribute("class", "chart-area");
  const line = document.createElementNS(ns, "path");
  line.setAttribute("d", pathValue);
  line.setAttribute("class", "chart-line");
  svg.append(area, line);
  root.replaceChildren(svg);
}

export function setButtonBusy(button, busy, label = "Đang xử lý…") {
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = label;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalLabel || button.textContent;
    button.disabled = false;
  }
}
