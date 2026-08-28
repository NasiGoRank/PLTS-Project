import "./history_export.css";

const AUTH_STORAGE_KEY = "plts-monitoring.supabase-session";

function apiBase() {
  const configured = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  return configured || (import.meta.env.DEV ? "http://localhost:8000" : "");
}

function readSession() {
  try {
    return JSON.parse(window.localStorage.getItem(AUTH_STORAGE_KEY) || "null");
  } catch {
    return null;
  }
}

function dateText(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 29);
  return { start: dateText(start), end: dateText(end) };
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "className") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "htmlFor") node.htmlFor = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (value !== undefined && value !== null) node.setAttribute(key, String(value));
  });
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child) node.append(child);
  }
  return node;
}

function setError(message = "") {
  const target = document.querySelector("#history-export-error");
  if (!target) return;
  target.textContent = message;
  target.hidden = !message;
}

async function authorizedFetch(path, options = {}) {
  const session = readSession();
  if (!session?.access_token) throw new Error("Please sign in before downloading history.");
  const base = apiBase();
  if (!base) throw new Error("VITE_API_URL is not configured.");

  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${session.access_token}`);
  const response = await fetch(`${base}${path}`, { ...options, headers, cache: "no-store" });
  if (response.status === 401) throw new Error("Your session expired. Please sign in again.");
  return response;
}

async function loadStations(select) {
  select.innerHTML = "";
  select.append(el("option", { value: "", text: "All stations" }));
  const response = await authorizedFetch(`/api/current?ts=${Date.now()}`);
  if (!response.ok) throw new Error(`Unable to load stations (${response.status}).`);
  const data = await response.json();
  const stations = [];
  Object.entries(data?.by_site || {}).forEach(([platform, site]) => {
    (site?.stations || []).forEach((station) => {
      if (station?.station_id === undefined || station?.station_id === null) return;
      stations.push({
        platform,
        stationId: String(station.station_id),
        name: station.name || String(station.station_id),
      });
    });
  });
  stations.sort((a, b) => a.name.localeCompare(b.name));
  for (const station of stations) {
    const option = el("option", {
      value: `${station.platform}::${station.stationId}`,
      text: `${station.name} · ${station.platform}`,
    });
    select.append(option);
  }
}

function openModal(modal, stationSelect) {
  setError();
  modal.hidden = false;
  document.body.classList.add("history-export-open");
  loadStations(stationSelect).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  window.setTimeout(() => modal.querySelector("input, select, button")?.focus(), 0);
}

function closeModal(modal) {
  modal.hidden = true;
  document.body.classList.remove("history-export-open");
}

async function download(form, button) {
  setError();
  const formData = new FormData(form);
  const startDate = String(formData.get("start_date") || "");
  const endDate = String(formData.get("end_date") || "");
  const resolution = String(formData.get("resolution") || "daily");
  const stationValue = String(formData.get("station") || "");

  if (!startDate || !endDate) throw new Error("Choose both start and end dates.");
  if (endDate < startDate) throw new Error("End date must be on or after start date.");

  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    resolution,
  });
  if (stationValue) {
    const [platform, stationId] = stationValue.split("::");
    if (platform) params.set("platform", platform);
    if (stationId) params.set("station_id", stationId);
  }

  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Preparing CSV...";
  try {
    const response = await authorizedFetch(`/api/history/export?${params.toString()}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const detail = typeof payload.detail === "string" ? payload.detail : `Export failed (${response.status}).`;
      throw new Error(detail);
    }

    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `plts-history-${resolution}-${startDate}-to-${endDate}.csv`;
    const url = URL.createObjectURL(blob);
    const anchor = el("a", { href: url, download: filename });
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function mountHeaderTrigger(trigger) {
  const topNav = document.querySelector(".top-nav");
  const hasSession = Boolean(readSession()?.access_token);

  if (!topNav || !hasSession) {
    trigger.hidden = true;
    return;
  }

  const logoutButton = topNav.querySelector(".logout-button");
  if (trigger.parentElement !== topNav || trigger.nextElementSibling !== logoutButton) {
    topNav.insertBefore(trigger, logoutButton || topNav.querySelector(".mobile-menu-trigger") || null);
  }
  trigger.hidden = false;
}

function buildWidget() {
  if (document.querySelector("#history-export-root")) return;
  const dates = defaultDates();

  const root = el("div", { id: "history-export-root" });
  const trigger = el("button", {
    type: "button",
    className: "history-export-trigger",
    title: "Download history",
    "aria-label": "Download history",
    "aria-haspopup": "dialog",
  });
  trigger.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v11" />
      <path d="m8 10 4 4 4-4" />
      <path d="M5 17v3h14v-3" />
    </svg>
  `;

  const modal = el("div", {
    className: "history-export-modal",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "history-export-title",
    hidden: "",
  });
  const backdrop = el("button", { type: "button", className: "history-export-backdrop", "aria-label": "Close download history" });
  const panel = el("section", { className: "history-export-panel" });
  const head = el("div", { className: "history-export-head" }, [
    el("div", {}, [
      el("span", { className: "history-export-eyebrow", text: "Historical data" }),
      el("h2", { id: "history-export-title", text: "Download history" }),
    ]),
  ]);
  const close = el("button", { type: "button", className: "history-export-close", text: "Close" });
  head.append(close);

  const form = el("form", { className: "history-export-form" });
  const stationSelect = el("select", { id: "history-export-station", name: "station" }, [
    el("option", { value: "", text: "All stations" }),
  ]);
  form.append(
    el("label", {}, [el("span", { text: "Station" }), stationSelect]),
    el("div", { className: "history-export-date-grid" }, [
      el("label", {}, [el("span", { text: "From" }), el("input", { type: "date", name: "start_date", value: dates.start, required: "" })]),
      el("label", {}, [el("span", { text: "To" }), el("input", { type: "date", name: "end_date", value: dates.end, required: "" })]),
    ]),
    el("label", {}, [
      el("span", { text: "Resolution" }),
      el("select", { name: "resolution" }, [
        el("option", { value: "daily", text: "Daily · long-term" }),
        el("option", { value: "hourly", text: "Hourly snapshots · up to 31 days" }),
      ]),
    ]),
    el("p", { className: "history-export-note", text: "CSV opens directly in Excel or Google Sheets. Hourly data follows snapshot retention; daily data uses the long-term rollup table." }),
  );
  const error = el("div", { id: "history-export-error", className: "history-export-error", role: "alert", hidden: "" });
  const submit = el("button", { type: "submit", className: "history-export-submit", text: "Download CSV" });
  form.append(error, submit);
  panel.append(head, form);
  modal.append(backdrop, panel);
  root.append(modal);
  document.body.append(root);

  trigger.addEventListener("click", () => openModal(modal, stationSelect));
  backdrop.addEventListener("click", () => closeModal(modal));
  close.addEventListener("click", () => closeModal(modal));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await download(form, submit);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) closeModal(modal);
  });

  const syncTrigger = () => mountHeaderTrigger(trigger);
  const observer = new MutationObserver(syncTrigger);
  observer.observe(document.querySelector("#root") || document.body, { childList: true, subtree: true });
  window.addEventListener("storage", syncTrigger);
  syncTrigger();
  window.setInterval(syncTrigger, 1500);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", buildWidget, { once: true });
} else {
  buildWidget();
}
