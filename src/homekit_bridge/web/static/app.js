/**
 * HomeKit Bridge — app.js
 * Pure Vanilla JS, ES6+, no framework, no build step.
 *
 * Sections:
 *   1. Constants & state
 *   2. API helpers
 *   3. Toast / notification
 *   4. Navigation / view switching
 *   5. Dashboard
 *   6. Solar panel (shared renderer, used by Dashboard + Solar view)
 *   7. Device table
 *   8. Polling / lifecycle
 */

/* =================================================================
   1. Constants & state
   ================================================================= */

const POLL_INTERVAL_MS = 5_000;
const PEAK_POWER_W     = 6_000; // reference peak for power bar (adjust to system size)

/** Known HomeKit types, matching HKType enum in models.py */
const HK_TYPES = [
  { value: "",            label: "— auto —" },
  { value: "switch",      label: "Switch" },
  { value: "outlet",      label: "Outlet" },
  { value: "lightbulb",   label: "Lightbulb" },
  { value: "cover",       label: "Cover" },
  { value: "thermostat",  label: "Thermostat" },
  { value: "contact",     label: "Contact" },
  { value: "temperature", label: "Temperature" },
  { value: "humidity",    label: "Humidity" },
  { value: "motion",      label: "Motion" },
];

/** Application state — plain object, mutated in place */
const state = {
  /** @type {"dashboard"|"devices"|"solar"|"pairing"|"logs"} */
  activeView: "dashboard",

  /** @type {null|{power_w:number, energy_today_kwh:number, battery_pct:number|null, producing:boolean, available:boolean}} */
  solar: null,

  /** @type {null|{paired:boolean, accessory_count:number, ccu3_connected:boolean, solaredge_connected:boolean}} */
  status: null,

  /** @type {Array<{address:string, type:string, type_desc:string, room:string, exported:boolean, hk_type:string|null, suggested_hk_type:string|null, name:string}>} */
  devices: [],

  /** pending row edits keyed by address */
  rowEdits: {},

  /** @type {Set<string>} room names whose device table group is collapsed */
  collapsedRooms: new Set(),

  /** @type {null|{pin:string, uri:string, paired:boolean}} */
  pairing: null,

  /** @type {Array<{ts:number, level:string, logger:string, message:string}>} */
  logs: [],

  /** current log level filter */
  logLevel: "INFO",
};

/* =================================================================
   2. API helpers
   ================================================================= */

/**
 * Thin fetch wrapper — returns parsed JSON or throws an Error.
 * @param {string} path
 * @param {RequestInit} [opts]
 * @returns {Promise<any>}
 */
async function apiFetch(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return res.json();
}

async function fetchStatus() {
  return apiFetch("/api/status");
}

async function fetchSolar() {
  return apiFetch("/api/solar");
}

async function fetchDevices() {
  return apiFetch("/api/devices");
}

/**
 * Save a single device mapping.
 * @param {string} address
 * @param {{exported:boolean, hk_type:string|null, name:string}} payload
 */
async function saveDevice(address, payload) {
  return apiFetch(`/api/devices/${encodeURIComponent(address)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/* =================================================================
   3. Toast / notification
   ================================================================= */

/**
 * Show a transient toast message.
 * @param {string} message
 * @param {"ok"|"error"} [kind]
 */
function showToast(message, kind = "ok") {
  const region = document.getElementById("toast-region");
  const toast = document.createElement("div");
  toast.className = `toast toast--${kind}`;
  toast.textContent = message;
  region.appendChild(toast);
  setTimeout(() => toast.remove(), 3_500);
}

/* =================================================================
   4. Navigation / view switching
   ================================================================= */

function initNavigation() {
  const tabs = document.querySelectorAll(".nav__tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });
}

/**
 * @param {"dashboard"|"devices"|"solar"|"pairing"|"logs"} viewId
 */
function switchView(viewId) {
  state.activeView = viewId;

  // Update tab aria + visual state
  document.querySelectorAll(".nav__tab").forEach(t => {
    const active = t.dataset.view === viewId;
    t.classList.toggle("nav__tab--active", active);
    t.setAttribute("aria-selected", String(active));
  });

  // Show / hide view panels
  document.querySelectorAll(".view").forEach(v => {
    v.classList.toggle("view--active", v.id === `view-${viewId}`);
  });

  // Kick off view-specific refresh when switching to devices
  if (viewId === "devices" && state.devices.length === 0) {
    refreshDevices();
  }

  if (viewId === "pairing") fetchPairing();
  if (viewId === "logs") fetchLogs();
}

/* =================================================================
   5. Dashboard
   ================================================================= */

function renderDashboard() {
  renderStatusTiles();
  renderSolarPanel(
    "dashboard-solar-metrics",
    "power-bar-fill",
    "power-bar-current",
    "power-bar-peak",
    "solar-bar-track"  // unused here, just pass null-safe id
  );
}

function renderStatusTiles() {
  const container = document.getElementById("dashboard-tiles");
  const { status, solar } = state;

  if (!status && !solar) {
    container.innerHTML =
      '<div class="state-message"><span class="spinner" aria-hidden="true"></span> Lade Status&#8230;</div>';
    return;
  }

  const tiles = [];

  // Bridge paired state
  if (status) {
    const paired = status.paired;
    tiles.push({
      icon: "&#x1F517;",
      label: "HomeKit Pairing",
      value: paired ? "Verbunden" : "Nicht gepairt",
      unit: "",
      mod: paired ? "ok" : "warn",
    });

    // Active device count
    tiles.push({
      icon: "&#x1F4F1;",
      label: "Aktive Geraete",
      value: String(status.accessory_count ?? "—"),
      unit: "Geraete",
      mod: "",
    });

    // CCU3 connectivity
    const ccu3ok = status.ccu3_connected;
    tiles.push({
      icon: "&#x1F4E1;",
      label: "CCU3",
      value: ccu3ok ? "Verbunden" : "Getrennt",
      unit: "",
      mod: ccu3ok ? "ok" : "error",
    });

    // SolarEdge connectivity
    const seok = status.solaredge_connected;
    tiles.push({
      icon: "&#9728;&#65039;",
      label: "SolarEdge",
      value: seok ? "Verbunden" : "Nicht verfuegbar",
      unit: "",
      mod: seok ? "ok" : "warn",
    });
  }

  // PV power tile
  if (solar) {
    const avail = solar.available;
    tiles.push({
      icon: "&#9889;",
      label: "PV Leistung",
      value: avail ? formatPower(solar.power_w) : "—",
      unit: avail ? "W" : "",
      mod: "solar",
    });

    // Producing badge
    tiles.push({
      icon: solar.producing ? "&#x1F7E2;" : "&#x26AA;",
      label: "PV produziert",
      value: solar.producing ? "Ja" : "Nein",
      unit: "",
      mod: solar.producing ? "ok" : "",
    });
  }

  container.innerHTML = tiles.map(t => `
    <article class="tile tile--${t.mod}" aria-label="${escHtml(t.label)}">
      <div class="tile__icon" aria-hidden="true">${t.icon}</div>
      <div class="tile__label">${escHtml(t.label)}</div>
      <div class="tile__value">${escHtml(t.value)}</div>
      ${t.unit ? `<div class="tile__unit">${escHtml(t.unit)}</div>` : ""}
    </article>
  `).join("");
}

/* =================================================================
   6. Solar panel (shared renderer)
   ================================================================= */

/**
 * Render solar metrics into any set of target element IDs.
 * @param {string} metricsId   element id for metrics grid
 * @param {string} barFillId   element id for power bar fill div
 * @param {string} barCurrentId
 * @param {string} barPeakId
 * @param {string|null} trackId  element id for progress bar track (aria)
 */
function renderSolarPanel(metricsId, barFillId, barCurrentId, barPeakId, trackId) {
  const metricsEl   = document.getElementById(metricsId);
  const barFill     = document.getElementById(barFillId);
  const barCurrent  = document.getElementById(barCurrentId);
  const barPeak     = document.getElementById(barPeakId);
  const track       = trackId ? document.getElementById(trackId) : null;

  if (!metricsEl) return;

  const solar = state.solar;

  if (!solar) {
    metricsEl.innerHTML = '<p class="state-message">Lade Solar-Daten&#8230;</p>';
    return;
  }

  if (!solar.available) {
    metricsEl.innerHTML = `
      <p class="state-message">
        <span class="badge badge--warn">Nicht verfuegbar</span>
        SolarEdge nicht erreichbar.
      </p>`;
    if (barFill) barFill.style.width = "0%";
    return;
  }

  const metrics = [
    {
      label: "Aktuelle Leistung",
      value: formatPower(solar.power_w),
      unit: "W",
    },
    {
      label: "Ertrag heute",
      value: solar.energy_today_kwh != null
        ? solar.energy_today_kwh.toFixed(1)
        : "—",
      unit: "kWh",
    },
    {
      label: "Batterie",
      value: solar.battery_pct != null ? String(solar.battery_pct) : "—",
      unit: solar.battery_pct != null ? "%" : "",
    },
    {
      label: "Produziert",
      value: solar.producing ? "Ja" : "Nein",
      unit: "",
    },
  ];

  metricsEl.innerHTML = metrics.map(m => `
    <div class="solar-metric">
      <span class="solar-metric__label">${escHtml(m.label)}</span>
      <span class="solar-metric__value">${escHtml(m.value)}</span>
      ${m.unit ? `<span class="solar-metric__unit">${escHtml(m.unit)}</span>` : ""}
    </div>
  `).join("");

  // Power bar
  const pct = Math.min(100, Math.round((solar.power_w / PEAK_POWER_W) * 100));
  if (barFill) {
    barFill.style.width = `${pct}%`;
  }
  if (track) {
    track.setAttribute("aria-valuenow", String(pct));
  }
  if (barCurrent) {
    barCurrent.textContent = `${formatPower(solar.power_w)} W`;
  }
  if (barPeak) {
    barPeak.textContent = `Spitze: ${PEAK_POWER_W.toLocaleString("de-DE")} W`;
  }
}

function renderSolarViewFull() {
  renderSolarPanel(
    "solar-metrics-full",
    "solar-bar-fill",
    "solar-bar-current",
    "solar-bar-peak",
    "solar-bar-track"
  );
}

/* =================================================================
   7. Device table
   ================================================================= */

async function refreshDevices() {
  const tbody = document.getElementById("device-tbody");
  if (!tbody) return;

  tbody.innerHTML = `
    <tr><td colspan="6" class="state-message">
      <span class="spinner" aria-hidden="true"></span> Lade Geraete&#8230;
    </td></tr>`;

  try {
    state.devices = await fetchDevices();
  } catch (err) {
    tbody.innerHTML = `
      <tr><td colspan="6" class="state-message">
        Fehler beim Laden: ${escHtml(err.message)}
      </td></tr>`;
    return;
  }

  renderDeviceTable(state.devices);
}

/** @param {string} query */
function filterDevices(query) {
  const q = query.trim().toLowerCase();
  if (!q) {
    renderDeviceTable(state.devices);
    return;
  }
  const filtered = state.devices.filter(d =>
    d.name.toLowerCase().includes(q) ||
    d.address.toLowerCase().includes(q) ||
    d.type.toLowerCase().includes(q) ||
    (d.room || "").toLowerCase().includes(q)
  );
  renderDeviceTable(filtered);
}

/**
 * @param {Array} devices
 */
function renderDeviceTable(devices) {
  const table   = document.getElementById("device-table");
  const tbody   = document.getElementById("device-tbody");  // message-only tbody
  const countEl = document.getElementById("devices-count");

  if (!table || !tbody) return;

  if (countEl) {
    countEl.textContent = `${devices.length} Geraete`;
  }

  // Drop any room sections from a previous render before rebuilding.
  table.querySelectorAll("tbody.room-section").forEach(el => el.remove());

  if (devices.length === 0) {
    tbody.hidden = false;
    tbody.innerHTML =
      '<tr><td colspan="6" class="state-message">Keine Geraete gefunden.</td></tr>';
    return;
  }

  // Messages live in #device-tbody; the device rows go into per-room sections.
  tbody.hidden = true;
  tbody.innerHTML = "";

  // Group devices by their CCU3 room (read-only). Devices without a room
  // assignment are collected under a trailing "Ohne Raum" group. Each room is
  // its own <tbody> so it can be collapsed and visually separated as a block.
  const groups = groupByRoom(devices);

  const sectionsHtml = groups.map(([room, items]) => {
    const safeRoom = escHtml(room);
    const collapsed = state.collapsedRooms.has(room);
    const header = `
      <tr class="room-group">
        <th colspan="6" scope="rowgroup">
          <button type="button" class="room-group__toggle" data-room="${safeRoom}"
            aria-expanded="${collapsed ? "false" : "true"}">
            <span class="room-group__chevron" aria-hidden="true">&#9656;</span>
            <span class="room-group__name">${safeRoom}</span>
            <span class="room-group__count">(${items.length})</span>
          </button>
        </th>
      </tr>`;
    const rows = items.map(device => buildDeviceRow(device)).join("");
    const cls = "room-section" + (collapsed ? " room-section--collapsed" : "");
    return `<tbody class="${cls}" data-room="${safeRoom}">${header}${rows}</tbody>`;
  }).join("");

  tbody.insertAdjacentHTML("afterend", sectionsHtml);

  // Attach per-row event listeners
  devices.forEach(device => bindRowEvents(device.address));
  // Attach collapse toggles
  table.querySelectorAll(".room-group__toggle").forEach(btn => {
    btn.addEventListener("click", () => toggleRoom(btn.dataset.room));
  });
}

/**
 * Toggle the collapsed state of one room group and reflect it in the DOM
 * without a full re-render (so it stays snappy and keeps scroll position).
 * @param {string} room
 */
function toggleRoom(room) {
  const willCollapse = !state.collapsedRooms.has(room);
  if (willCollapse) state.collapsedRooms.add(room);
  else state.collapsedRooms.delete(room);

  const section = document.querySelector(`tbody.room-section[data-room="${CSS.escape(room)}"]`);
  if (section) {
    section.classList.toggle("room-section--collapsed", willCollapse);
    const btn = section.querySelector(".room-group__toggle");
    if (btn) btn.setAttribute("aria-expanded", willCollapse ? "false" : "true");
  }
}

const UNASSIGNED_ROOM = "Ohne Raum";

/**
 * Group devices by room, sorted alphabetically (de locale). The synthetic
 * "Ohne Raum" bucket for unassigned channels is always sorted last.
 * @param {Array} devices
 * @returns {Array<[string, Array]>}  [roomName, devices][] in display order
 */
function groupByRoom(devices) {
  const byRoom = new Map();
  for (const device of devices) {
    const room = (device.room && device.room.trim()) || UNASSIGNED_ROOM;
    if (!byRoom.has(room)) byRoom.set(room, []);
    byRoom.get(room).push(device);
  }
  return [...byRoom.entries()].sort(([a], [b]) => {
    if (a === UNASSIGNED_ROOM) return 1;
    if (b === UNASSIGNED_ROOM) return -1;
    return a.localeCompare(b, "de");
  });
}

/**
 * Build the HTML string for one device row.
 * API returns {address, type, exported, hk_type, suggested_hk_type, name}.
 * Dropdown shows the explicit hk_type override when set; falls back to
 * suggested_hk_type (auto-detected from HM type) when the user has not yet
 * configured an override.
 * @param {{ address:string, type:string, type_desc:string, exported:boolean, hk_type:string|null, suggested_hk_type:string|null, name:string }} device
 * @returns {string}
 */
function buildDeviceRow(device) {
  const { address, type, type_desc, name, exported, hk_type, suggested_hk_type } = device;
  const safeAddr = escHtml(address);

  // Role hint under the raw HM type — clarifies which channel of a multi-channel
  // device is the controllable one (e.g. the blind actuator vs its button channel).
  const descHtml = type_desc
    ? `<div class="type-desc">${escHtml(type_desc)}</div>`
    : "";

  // Effective dropdown value: explicit override > auto-suggestion > blank ("— auto —")
  const effectiveType = hk_type ?? suggested_hk_type ?? "";

  const typeOptions = HK_TYPES.map(t => {
    const selected = effectiveType === t.value ? " selected" : "";
    // Mark the suggestion visually when no override is set yet
    const isSuggestion = !hk_type && t.value && t.value === suggested_hk_type;
    const label = isSuggestion ? `${t.label} (Vorschlag)` : t.label;
    return `<option value="${escHtml(t.value)}"${selected}>${escHtml(label)}</option>`;
  }).join("");

  return `
    <tr id="row-${safeAddr}" data-address="${safeAddr}">
      <td>
        <input
          class="name-input"
          type="text"
          aria-label="Name fuer ${safeAddr}"
          value="${escHtml(name)}"
          data-field="name"
          data-address="${safeAddr}"
        />
      </td>
      <td><code class="address">${safeAddr}</code></td>
      <td><code class="hm-type">${escHtml(type)}</code>${descHtml}</td>
      <td>
        <select
          class="hktype-select"
          aria-label="HomeKit-Typ fuer ${safeAddr}"
          data-field="hk_type"
          data-address="${safeAddr}"
        >${typeOptions}</select>
      </td>
      <td>
        <input
          class="toggle"
          type="checkbox"
          aria-label="Export fuer ${safeAddr}"
          ${exported ? "checked" : ""}
          data-field="exported"
          data-address="${safeAddr}"
        />
      </td>
      <td>
        <button
          class="btn-save"
          aria-label="Speichern: ${safeAddr}"
          data-address="${safeAddr}"
        >Speichern</button>
        <span class="row-state" id="row-state-${safeAddr}" aria-live="polite"></span>
      </td>
    </tr>`;
}

/**
 * Attach change/click listeners to a single device row.
 * @param {string} address
 */
function bindRowEvents(address) {
  const row = document.getElementById(`row-${address}`);
  if (!row) return;

  const saveBtn = row.querySelector(".btn-save");
  saveBtn.addEventListener("click", () => handleSave(address));

  // Mark row as dirty on any change
  row.querySelectorAll("[data-field]").forEach(el => {
    el.addEventListener("change", () => markRowDirty(address));
    if (el.tagName === "INPUT" && el.type === "text") {
      el.addEventListener("input", () => markRowDirty(address));
    }
  });
}

function markRowDirty(address) {
  const stateEl = document.getElementById(`row-state-${address}`);
  if (stateEl && !stateEl.textContent) {
    // no-op: visual feedback only on save
  }
}

/**
 * Read current row values and POST to the API.
 * Applies optimistic UI: show saving/ok/error state in the row.
 * @param {string} address
 */
async function handleSave(address) {
  const row     = document.getElementById(`row-${address}`);
  const stateEl = document.getElementById(`row-state-${address}`);
  const saveBtn = row ? row.querySelector(".btn-save") : null;

  if (!row || !saveBtn) return;

  const nameInput   = row.querySelector('[data-field="name"]');
  const hktypeSelect = row.querySelector('[data-field="hk_type"]');
  const exportToggle = row.querySelector('[data-field="exported"]');

  const payload = {
    name:     nameInput   ? nameInput.value.trim()          : "",
    hk_type:  hktypeSelect ? (hktypeSelect.value || null)   : null,
    exported: exportToggle ? exportToggle.checked            : false,
  };

  // Optimistic: disable save while in flight
  saveBtn.disabled = true;
  if (stateEl) {
    stateEl.className = "row-state row-state--saving";
    stateEl.textContent = "…";
  }

  try {
    await saveDevice(address, payload);

    // Update local state
    const idx = state.devices.findIndex(d => d.address === address);
    if (idx !== -1) {
      state.devices[idx] = { ...state.devices[idx], ...payload };
    }

    if (stateEl) {
      stateEl.className = "row-state row-state--ok";
      stateEl.textContent = "OK";
      setTimeout(() => { stateEl.textContent = ""; }, 2_000);
    }
    showToast(`"${payload.name || address}" gespeichert.`, "ok");
  } catch (err) {
    if (stateEl) {
      stateEl.className = "row-state row-state--error";
      stateEl.textContent = "Fehler";
    }
    showToast(`Fehler beim Speichern (${address}): ${err.message}`, "error");
  } finally {
    saveBtn.disabled = false;
  }
}

function initDeviceSearch() {
  const input = document.getElementById("device-search");
  if (!input) return;
  input.addEventListener("input", () => filterDevices(input.value));
}

/* =================================================================
   Pairing view
   ================================================================= */

async function fetchPairing() {
  try {
    state.pairing = await apiFetch("/api/pairing");
  } catch (err) {
    state.pairing = null;
  }
  renderPairing();
}

function renderPairing() {
  const statusEl = document.getElementById("pairing-status");
  const pinEl = document.getElementById("pairing-pin");
  const qrEl = document.getElementById("pairing-qr");
  if (!statusEl || !pinEl || !qrEl) return;

  if (!state.pairing) {
    statusEl.textContent = "Pairing-Info nicht verfügbar";
    pinEl.textContent = "—";
    qrEl.removeAttribute("src");
    delete qrEl.dataset.uri;
    return;
  }
  statusEl.textContent = state.pairing.paired ? "Gekoppelt" : "Nicht gekoppelt";
  statusEl.classList.toggle("is-paired", state.pairing.paired);
  pinEl.textContent = state.pairing.pin;
  // Load the QR only when the pairing URI changes — avoids reloading
  // (and flickering) the image on every poll while the tab is open.
  if (qrEl.dataset.uri !== state.pairing.uri) {
    qrEl.dataset.uri = state.pairing.uri;
    qrEl.src = "/api/pairing/qr.svg?ts=" + Date.now();
  }
}

/* =================================================================
   Logs view
   ================================================================= */

async function fetchLogs() {
  const q = state.logLevel ? "?level=" + encodeURIComponent(state.logLevel) : "";
  try {
    const data = await apiFetch("/api/logs" + q);
    state.logs = data.records || [];
  } catch (err) {
    state.logs = [];
  }
  renderLogs();
}

function renderLogs() {
  const viewer = document.getElementById("log-viewer");
  if (!viewer) return;
  if (state.logs.length === 0) {
    viewer.innerHTML = '<div class="state-message">Keine Log-Einträge</div>';
    return;
  }
  viewer.innerHTML = state.logs.map((r) => {
    const t = new Date(r.ts * 1000).toLocaleTimeString("de-DE");
    const level = escHtml(r.level);
    return (
      '<div class="log-line log-line--' + level + '">' +
      '<span class="log-line__ts">' + t + "</span>" +
      '<span class="log-line__level">' + level + "</span>" +
      '<span class="log-line__logger">' + escHtml(r.logger) + "</span>" +
      '<span class="log-line__msg">' + escHtml(r.message) + "</span>" +
      "</div>"
    );
  }).join("");
  viewer.scrollTop = viewer.scrollHeight;
}

/* =================================================================
   8. Polling / lifecycle
   ================================================================= */

let pollIntervalId = null;

/**
 * Fetch status + solar data and update all active views.
 */
async function poll() {
  try {
    const [statusData, solarData] = await Promise.allSettled([
      fetchStatus(),
      fetchSolar(),
    ]);

    if (statusData.status === "fulfilled") {
      state.status = statusData.value;
    }
    if (solarData.status === "fulfilled") {
      state.solar = solarData.value;
    }

    // Update nav status bar
    updateNavStatus();

    // Re-render whichever views are active
    if (state.activeView === "dashboard") {
      renderDashboard();
    }
    if (state.activeView === "solar") {
      renderSolarViewFull();
    }
    if (state.activeView === "logs") {
      fetchLogs();
    }
    if (state.activeView === "pairing") {
      fetchPairing();
    }

    setPollIndicator(true);
  } catch (_) {
    setPollIndicator(false);
  }
}

function setPollIndicator(ok) {
  const dot   = document.getElementById("poll-dot");
  const label = document.getElementById("poll-label");
  if (dot) {
    dot.className = `dot ${ok ? "dot--ok" : "dot--error"}`;
  }
  if (label) {
    label.textContent = ok ? "Polling alle 5 s" : "Verbindungsfehler";
  }
}

function updateNavStatus() {
  const el = document.getElementById("nav-status");
  if (!el) return;

  const parts = [];

  if (state.status) {
    const dot = state.status.ccu3_connected
      ? '<span class="dot dot--ok" aria-hidden="true"></span>'
      : '<span class="dot dot--error" aria-hidden="true"></span>';
    parts.push(`${dot} CCU3`);
    parts.push(`${state.status.accessory_count ?? 0} Geraete`);
  }

  if (state.solar && state.solar.available) {
    parts.push(`&#9728;&#65039; ${formatPower(state.solar.power_w)} W`);
  }

  el.innerHTML = parts.join(" &middot; ");
}

function startPolling() {
  poll(); // immediate first poll
  pollIntervalId = setInterval(poll, POLL_INTERVAL_MS);
}

/* =================================================================
   Utilities
   ================================================================= */

/**
 * Escape HTML special chars to prevent XSS from API data.
 * @param {string} str
 * @returns {string}
 */
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Format a watt value with German locale thousands separator.
 * @param {number} w
 * @returns {string}
 */
function formatPower(w) {
  return Math.round(w).toLocaleString("de-DE");
}

/* =================================================================
   Entry point
   ================================================================= */

document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initDeviceSearch();
  startPolling();

  const logLevelEl = document.getElementById("log-level");
  if (logLevelEl) {
    state.logLevel = logLevelEl.value;
    logLevelEl.addEventListener("change", () => {
      state.logLevel = logLevelEl.value;
      fetchLogs();
    });
  }

  // When user switches to devices tab, load the table
  document.querySelectorAll(".nav__tab").forEach(tab => {
    tab.addEventListener("click", () => {
      if (tab.dataset.view === "devices" && state.devices.length === 0) {
        refreshDevices();
      }
    });
  });
});
