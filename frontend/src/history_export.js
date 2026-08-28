import "./history_export.css";

const AUTH_STORAGE_KEY = "plts-monitoring.supabase-session";
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

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

function parseDate(value) {
  const [year, month, day] = String(value || "").split("-").map(Number);
  if (!year || !month || !day) return new Date();
  return new Date(year, month - 1, day);
}

function formatDisplayDate(value) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(parseDate(value));
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

function chevronIcon() {
  const wrapper = el("span", { className: "history-control-icon", "aria-hidden": "true" });
  wrapper.innerHTML = '<svg viewBox="0 0 20 20"><path d="m6 8 4 4 4-4" /></svg>';
  return wrapper;
}

function calendarIcon() {
  const wrapper = el("span", { className: "history-control-leading", "aria-hidden": "true" });
  wrapper.innerHTML = '<svg viewBox="0 0 20 20"><path d="M5 3v3M15 3v3M3.5 7.5h13M4.5 5h11a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z" /></svg>';
  return wrapper;
}

function setError(message = "") {
  const target = document.querySelector("#history-export-error");
  if (!target) return;
  target.textContent = message;
  target.hidden = !message;
}

function closePopovers(except = null) {
  document.querySelectorAll(".history-popover.open").forEach((popover) => {
    if (popover === except) return;
    popover.classList.remove("open");
    const control = popover.parentElement?.querySelector(".history-control-button");
    control?.setAttribute("aria-expanded", "false");
  });
}

function togglePopover(control, popover) {
  const opening = !popover.classList.contains("open");
  closePopovers(opening ? popover : null);
  popover.classList.toggle("open", opening);
  control.setAttribute("aria-expanded", String(opening));
}

function createDropdown({ name, options, value = "", ariaLabel }) {
  const wrapper = el("div", { className: "history-field-control history-dropdown" });
  const hidden = el("input", { type: "hidden", name, value });
  const valueText = el("span", { className: "history-control-value" });
  const control = el("button", {
    type: "button",
    className: "history-control-button",
    "aria-haspopup": "listbox",
    "aria-expanded": "false",
    "aria-label": ariaLabel,
  }, [valueText, chevronIcon()]);
  const menu = el("div", { className: "history-popover history-dropdown-menu", role: "listbox" });
  let items = [];

  const render = () => {
    menu.replaceChildren();
    const selected = items.find((item) => item.value === hidden.value) || items[0];
    valueText.textContent = selected?.label || "Select";
    for (const item of items) {
      const option = el("button", {
        type: "button",
        className: `history-option ${item.value === hidden.value ? "selected" : ""}`,
        role: "option",
        "aria-selected": String(item.value === hidden.value),
      }, [
        el("span", { text: item.label }),
        item.meta ? el("small", { text: item.meta }) : null,
      ]);
      option.addEventListener("click", () => {
        hidden.value = item.value;
        render();
        closePopovers();
      });
      menu.append(option);
    }
  };

  const setOptions = (nextItems) => {
    items = nextItems;
    if (!items.some((item) => item.value === hidden.value)) hidden.value = items[0]?.value || "";
    render();
  };

  control.addEventListener("click", () => togglePopover(control, menu));
  wrapper.append(hidden, control, menu);
  setOptions(options);
  return { node: wrapper, input: hidden, control, menu, setOptions };
}

function createDatePicker({ name, value, ariaLabel }) {
  const wrapper = el("div", { className: "history-field-control history-date-picker" });
  const hidden = el("input", { type: "hidden", name, value });
  const valueText = el("span", { className: "history-control-value", text: formatDisplayDate(value) });
  const control = el("button", {
    type: "button",
    className: "history-control-button history-date-button",
    "aria-haspopup": "dialog",
    "aria-expanded": "false",
    "aria-label": ariaLabel,
  }, [calendarIcon(), valueText]);
  const popover = el("div", { className: "history-popover history-calendar", role: "dialog", "aria-label": ariaLabel });
  let viewDate = parseDate(value);

  const renderCalendar = () => {
    popover.replaceChildren();
    const header = el("div", { className: "history-calendar-head" });
    const previous = el("button", { type: "button", className: "history-calendar-nav", "aria-label": "Previous month", text: "‹" });
    const title = el("strong", { text: `${MONTHS[viewDate.getMonth()]} ${viewDate.getFullYear()}` });
    const next = el("button", { type: "button", className: "history-calendar-nav", "aria-label": "Next month", text: "›" });
    previous.addEventListener("click", () => {
      viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1);
      renderCalendar();
    });
    next.addEventListener("click", () => {
      viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1);
      renderCalendar();
    });
    header.append(previous, title, next);

    const weekdays = el("div", { className: "history-calendar-weekdays" });
    WEEKDAYS.forEach((day) => weekdays.append(el("span", { text: day })));

    const grid = el("div", { className: "history-calendar-grid" });
    const year = viewDate.getFullYear();
    const month = viewDate.getMonth();
    const firstWeekday = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const selectedValue = hidden.value;
    const todayValue = dateText(new Date());

    for (let index = 0; index < firstWeekday; index += 1) {
      grid.append(el("span", { className: "history-calendar-empty" }));
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      const currentValue = dateText(new Date(year, month, day));
      const dayButton = el("button", {
        type: "button",
        className: [
          "history-calendar-day",
          currentValue === selectedValue ? "selected" : "",
          currentValue === todayValue ? "today" : "",
        ].filter(Boolean).join(" "),
        text: String(day),
        "aria-label": formatDisplayDate(currentValue),
      });
      dayButton.addEventListener("click", () => {
        hidden.value = currentValue;
        valueText.textContent = formatDisplayDate(currentValue);
        viewDate = parseDate(currentValue);
        renderCalendar();
        closePopovers();
      });
      grid.append(dayButton);
    }

    const footer = el("div", { className: "history-calendar-footer" });
    const today = el("button", { type: "button", text: "Today" });
    today.addEventListener("click", () => {
      const currentValue = dateText(new Date());
      hidden.value = currentValue;
      valueText.textContent = formatDisplayDate(currentValue);
      viewDate = new Date();
      renderCalendar();
      closePopovers();
    });
    footer.append(today);
    popover.append(header, weekdays, grid, footer);
  };

  control.addEventListener("click", () => {
    viewDate = parseDate(hidden.value);
    renderCalendar();
    togglePopover(control, popover);
  });
  wrapper.append(hidden, control, popover);
  renderCalendar();
  return { node: wrapper, input: hidden, control, popover };
}

function field(label, control, className = "") {
  return el("div", { className: `history-field ${className}`.trim() }, [
    el("span", { className: "history-field-label", text: label }),
    control,
  ]);
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

async function loadStations(dropdown) {
  dropdown.setOptions([{ value: "", label: "All stations", meta: "Fleet" }]);
  const response = await authorizedFetch(`/api/current?ts=${Date.now()}`);
  if (!response.ok) throw new Error(`Unable to load stations (${response.status}).`);
  const data = await response.json();
  const stations = [];
  Object.entries(data?.by_site || {}).forEach(([platform, site]) => {
    (site?.stations || []).forEach((station) => {
      if (station?.station_id === undefined || station?.station_id === null) return;
      stations.push({
        value: `${platform}::${String(station.station_id)}`,
        label: station.name || String(station.station_id),
        meta: platform,
      });
    });
  });
  stations.sort((a, b) => a.label.localeCompare(b.label));
  dropdown.setOptions([{ value: "", label: "All stations", meta: "Fleet" }, ...stations]);
}

function openModal(modal, stationDropdown) {
  setError();
  closePopovers();
  modal.hidden = false;
  document.body.classList.add("history-export-open");
  loadStations(stationDropdown).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  window.setTimeout(() => modal.querySelector(".history-control-button, button")?.focus(), 0);
}

function closeModal(modal) {
  closePopovers();
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

  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, resolution });
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
  const stationDropdown = createDropdown({
    name: "station",
    ariaLabel: "Select station",
    options: [{ value: "", label: "All stations", meta: "Fleet" }],
  });
  const startPicker = createDatePicker({ name: "start_date", value: dates.start, ariaLabel: "Select start date" });
  const endPicker = createDatePicker({ name: "end_date", value: dates.end, ariaLabel: "Select end date" });
  const resolutionDropdown = createDropdown({
    name: "resolution",
    value: "daily",
    ariaLabel: "Select history resolution",
    options: [
      { value: "daily", label: "Daily", meta: "Long-term rollup" },
      { value: "hourly", label: "Hourly snapshots", meta: "Up to 31 days" },
    ],
  });

  form.append(
    field("Station", stationDropdown.node),
    el("div", { className: "history-export-date-grid" }, [
      field("From", startPicker.node, "history-date-field"),
      field("To", endPicker.node, "history-date-field"),
    ]),
    field("Resolution", resolutionDropdown.node),
    el("p", {
      className: "history-export-note",
      text: "CSV opens directly in Excel or Google Sheets. Hourly data follows snapshot retention; daily data uses the long-term rollup table.",
    }),
  );

  const error = el("div", { id: "history-export-error", className: "history-export-error", role: "alert", hidden: "" });
  const submit = el("button", { type: "submit", className: "history-export-submit", text: "Download CSV" });
  form.append(error, submit);
  panel.append(head, form);
  modal.append(backdrop, panel);
  root.append(modal);
  document.body.append(root);

  trigger.addEventListener("click", () => openModal(modal, stationDropdown));
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
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".history-field-control")) closePopovers();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const openPopover = document.querySelector(".history-popover.open");
    if (openPopover) closePopovers();
    else if (!modal.hidden) closeModal(modal);
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
