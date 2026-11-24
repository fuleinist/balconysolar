"use strict";

const $ = (id) => document.getElementById(id);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const state = {
  obstructions: [],
  panels: [],
  inverters: [],
  result: null,
  scenarioId: null,
};

/* ------------------------------------------------------------------ utils */
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

const num = (id) => Number($(id).value);

function compassName(deg) {
  const names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  return names[Math.round(((deg % 360) / 22.5)) % 16];
}

function fmt(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/* ------------------------------------------------------------- obstruction */
function renderObstructions() {
  const host = $("obstruction-list");
  if (!state.obstructions.length) {
    host.innerHTML = '<p class="empty">No edges. The model assumes open sky aside from the panel tilt.</p>';
    return;
  }
  host.innerHTML = state.obstructions
    .map(
      (item, index) => `
      <div class="obs-item">
        <span class="obs-az">${Math.round(item.azimuth)}° ${compassName(item.azimuth)}</span>
        <span class="obs-meta">top at ${Math.round(item.elevation)}° · ${Math.round(item.width)}° wide</span>
        <button type="button" data-remove="${index}" aria-label="Remove edge">×</button>
      </div>`
    )
    .join("");
  host.querySelectorAll("[data-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      state.obstructions.splice(Number(button.dataset.remove), 1);
      renderObstructions();
    });
  });
}

function presets() {
  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.preset;
      if (kind === "open") {
        state.obstructions = [];
      } else if (kind === "opposite") {
        state.obstructions = [{ azimuth: num("azimuth"), elevation: 32, width: 70 }];
      } else if (kind === "side") {
        state.obstructions = [
          { azimuth: (num("azimuth") + 270) % 360, elevation: 45, width: 60 },
        ];
      }
      renderObstructions();
    });
  });
}

/* ------------------------------------------------------------------ payload */
function buildPayload() {
  const panel = state.panels.find((item) => item.id === $("panel").value) || {};
  return {
    location: { lat: num("lat"), lon: num("lon"), label: $("place").value || "Balcony" },
    balcony: {
      azimuth: num("azimuth"),
      tilt: num("tilt"),
      rail_height_m: num("rail"),
      floor_level: num("floor"),
    },
    panel: {
      wp: num("wp"),
      area_m2: num("area"),
      efficiency: panel.efficiency || 0.205,
      temp_coeff: panel.temp_coeff || -0.0035,
      noct: panel.noct || 45,
    },
    inverter: (() => {
      const inverter = state.inverters.find((item) => item.id === $("inverter").value) || {};
      return { limit_w: inverter.limit_w || num("wp"), efficiency: inverter.efficiency || 0.96 };
    })(),
    obstructions: state.obstructions,
    load: { daily_kwh: num("daily") },
    tariff: {
      import_aud_kwh: num("import"),
      export_aud_kwh: num("export"),
      export_allowed: $("allow-export").checked,
    },
    capex_aud: num("capex"),
  };
}

/* ------------------------------------------------------------------- charts */
function barChart(monthly) {
  const width = 560;
  const height = 190;
  const pad = { top: 16, right: 6, bottom: 22, left: 30 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const peak = Math.max(1, ...monthly.map((m) => m.kwh));
  const step = innerW / 12;
  const barW = Math.min(30, step * 0.62);

  const ticks = [0, peak / 2, peak].map((value, index) => {
    const y = pad.top + innerH - (value / peak) * innerH;
    return `<line class="grid-line" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" />
            <text class="axis-text" x="${pad.left - 6}" y="${y + 3}" text-anchor="end">${Math.round(value)}</text>`;
  });

  const bars = monthly
    .map((item, index) => {
      const h = Math.max(2, (item.kwh / peak) * innerH);
      const x = pad.left + index * step + (step - barW) / 2;
      const y = pad.top + innerH - h;
      return `<g>
        <rect class="bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3">
          <title>${MONTHS[index]}: ${item.kwh.toFixed(1)} kWh</title>
        </rect>
        <text class="axis-text" x="${x + barW / 2}" y="${height - 6}" text-anchor="middle">${MONTHS[index][0]}</text>
      </g>`;
    })
    .join("");

  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly yield">
    <defs><linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#f2b134" /><stop offset="100%" stop-color="#e08b1f" />
    </linearGradient></defs>
    ${ticks.join("")}${bars}
  </svg>`;
}

function dayChart(profile) {
  const width = 560;
  const height = 170;
  const pad = { top: 14, right: 8, bottom: 22, left: 30 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const peak = Math.max(0.05, ...profile);
  const x = (index) => pad.left + (index / 23) * innerW;
  const y = (value) => pad.top + innerH - (value / peak) * innerH;

  const points = profile.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`);
  const area = `M ${pad.left},${pad.top + innerH} L ${points.join(" L ")} L ${pad.left + innerW},${pad.top + innerH} Z`;

  const labels = [0, 6, 12, 18, 23]
    .map((hour) => `<text class="axis-text" x="${x(hour)}" y="${height - 6}" text-anchor="middle">${hour}:00</text>`)
    .join("");

  const gridY = pad.top + innerH;
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Mean daily generation">
    <line class="grid-line" x1="${pad.left}" y1="${gridY}" x2="${width - pad.right}" y2="${gridY}" />
    <line class="grid-line" x1="${pad.left}" y1="${pad.top}" x2="${width - pad.right}" y2="${pad.top}" />
    <text class="axis-text" x="${pad.left - 6}" y="${pad.top + 4}" text-anchor="end">${peak.toFixed(2)}</text>
    <text class="axis-text" x="${pad.left - 6}" y="${gridY + 3}" text-anchor="end">0</text>
    <path class="area" d="${area}" />
    <polyline class="line" points="${points.join(" ")}" />
    ${labels}
  </svg>`;
}

function lossBars(result) {
  const losses = result.losses || {};
  const rows = [
    { name: "Shading", value: losses.shading_kwh || 0, cls: "bad" },
    { name: "Temperature", value: losses.temperature_kwh || 0, cls: "" },
    { name: "Clipping", value: losses.clipping_kwh || 0, cls: "" },
    { name: "Soiling and wiring", value: losses.system_kwh || 0, cls: "" },
    { name: "Used at home", value: result.self_consumed_kwh, cls: "good" },
    { name: "Exported", value: result.exported_kwh, cls: "good" },
    { name: "Curtailed", value: result.curtailed_kwh || 0, cls: "bad" },
  ];
  const peak = Math.max(1, ...rows.map((row) => row.value));

  $("loss-bars").innerHTML = rows
    .map(
      (row) => `
      <div class="loss-row">
        <span class="name">${row.name}</span>
        <span class="track"><span class="fill ${row.cls}" style="width:${((row.value / peak) * 100).toFixed(1)}%"></span></span>
        <span class="val">${fmt(row.value, 0)}</span>
      </div>`
    )
    .join("");

  $("split-legend").innerHTML = `
    <span><i class="dotmark" style="background:var(--green)"></i>Delivered to the home or the grid</span>
    <span><i class="dotmark" style="background:var(--red)"></i>Lost or spilled</span>
    <span><i class="dotmark" style="background:#f1ebdf"></i>Total panel irradiance ${fmt(result.irradiance.poa_kwh_m2, 0)} kWh/m²</span>`;
}

/* ------------------------------------------------------------------ render */
function renderResult(result) {
  state.result = result;

  const payback = result.payback_years;
  $("payback").textContent = payback ? fmt(payback, 1) : "—";
  $("payback-range").textContent = payback
    ? `Range ${fmt(result.payback_range[0], 1)} to ${fmt(result.payback_range[1], 1)} years at A$${fmt(result.capex_aud, 0)} installed`
    : "No payback at these tariffs. The panel still cuts evening imports.";

  $("annual").textContent = fmt(result.annual_kwh, 0);
  $("savings").textContent = fmt(result.savings_aud, 0);
  $("selfuse").textContent = fmt(result.self_consumption_ratio * 100, 0);

  const badge = $("hero-badge");
  if (payback && payback <= 6) {
    badge.textContent = "strong";
    badge.className = "badge good";
  } else if (payback && payback <= 10) {
    badge.textContent = "moderate";
    badge.className = "badge";
  } else {
    badge.textContent = "weak";
    badge.className = "badge warn";
  }

  $("chart-monthly").innerHTML = barChart(result.monthly);
  $("chart-day").innerHTML = dayChart(result.day_profile);
  $("daily-kwh-note") && ($("daily-kwh-note").textContent = fmt(result.day_kwh, 1) + " kWh on an average day");

  lossBars(result);

  $("assumptions").innerHTML = (result.assumptions || [])
    .map((item) => `<li>${item}</li>`)
    .join("");

  const dataBadge = $("data-badge");
  dataBadge.textContent = result.source_kind === "archive" ? "Measured weather" : "Modelled weather";
  dataBadge.className = "badge " + (result.source_kind === "archive" ? "good" : "warn");
  $("source-pill").textContent = result.source_kind === "archive" ? "Open-Meteo archive" : "Offline clear-sky";

  $("btn-print").disabled = !state.scenarioId;
  $("btn-pvgis").disabled = false;
  $("pvgis-out").textContent = "";
}

/* ----------------------------------------------------------------- actions */
async function calculate(event) {
  if (event) event.preventDefault();
  const status = $("form-status");
  status.textContent = "Running one year of hourly weather…";
  status.className = "hint";
  document.querySelector(".results").classList.add("is-loading");

  try {
    const result = await api("/api/estimate", {
      method: "POST",
      body: JSON.stringify(buildPayload()),
    });
    renderResult(result);
    status.textContent = "Done. " + result.hours.toLocaleString() + " hours modelled.";
    state.scenarioId = null;
    $("btn-print").disabled = true;
  } catch (error) {
    status.textContent = error.message;
    status.className = "hint warn";
  } finally {
    document.querySelector(".results").classList.remove("is-loading");
  }
}

async function saveScenario() {
  const status = $("form-status");
  if (!state.result) await calculate();
  try {
    const payload = await api("/api/scenarios", {
      method: "POST",
      body: JSON.stringify(buildPayload()),
    });
    state.scenarioId = payload.id;
    $("btn-print").disabled = false;
    status.textContent = `Saved as ${payload.id}. Print brief is ready.`;
    status.className = "hint";
    loadScenarios();
  } catch (error) {
    status.textContent = error.message;
    status.className = "hint warn";
  }
}

function printBrief() {
  if (!state.scenarioId) return;
  window.open(`/brief/${state.scenarioId}`, "_blank");
}

async function pvgisCheck() {
  const out = $("pvgis-out");
  const result = state.result;
  if (!result) return;
  out.textContent = "Calling PVGIS…";
  const params = new URLSearchParams({
    lat: num("lat"),
    lon: num("lon"),
    tilt: num("tilt"),
    azimuth: num("azimuth"),
    peakpower: (num("wp") / 1000).toFixed(3),
  });
  try {
    const payload = await api(`/api/pvgis?${params}`);
    if (!payload.available) {
      out.textContent = "PVGIS did not answer. The model result stands.";
      return;
    }
    const reference = payload.reference;
    const delta = ((result.annual_kwh - reference.annual_kwh) / reference.annual_kwh) * 100;
    out.textContent = `PVGIS ${fmt(reference.annual_kwh, 0)} kWh/yr · this model ${delta >= 0 ? "+" : ""}${fmt(delta, 1)}%`;
  } catch (error) {
    out.textContent = error.message;
  }
}

async function loadScenarios() {
  const card = $("saved-card");
  card.hidden = false;
  const list = $("saved-list");
  try {
    const payload = await api("/api/scenarios");
    if (!payload.scenarios.length) {
      list.innerHTML = '<li class="muted">No saved scenarios yet.</li>';
      return;
    }
    list.innerHTML = payload.scenarios
      .map(
        (item) => `<li>
          <span class="s-label">${item.label}</span>
          <span class="s-meta">${fmt(item.annual_kwh, 0)} kWh · ${item.payback_years ? fmt(item.payback_years, 1) + " yr" : "no payback"}</span>
          <a href="/brief/${item.id}" target="_blank" rel="noopener">Brief</a>
          <button class="ghost small" data-load="${item.id}">Load</button>
        </li>`
      )
      .join("");
    list.querySelectorAll("[data-load]").forEach((button) => {
      button.addEventListener("click", () => loadScenario(button.dataset.load));
    });
  } catch (error) {
    list.innerHTML = `<li class="muted">${error.message}</li>`;
  }
}

async function loadScenario(id) {
  const scenario = await api(`/api/scenarios/${id}`);
  const payload = scenario.payload;
  $("lat").value = payload.location.lat;
  $("lon").value = payload.location.lon;
  $("place").value = payload.location.label || "";
  $("azimuth").value = payload.balcony.azimuth;
  $("tilt").value = payload.balcony.tilt;
  $("rail").value = payload.balcony.rail_height_m;
  $("floor").value = payload.balcony.floor_level;
  $("wp").value = payload.panel.wp;
  $("area").value = payload.panel.area_m2;
  $("daily").value = payload.load.daily_kwh;
  $("import").value = payload.tariff.import_aud_kwh;
  $("export").value = payload.tariff.export_aud_kwh;
  $("allow-export").checked = payload.tariff.export_allowed !== false;
  $("capex").value = payload.capex_aud;
  state.obstructions = payload.obstructions || [];
  renderObstructions();
  syncCompass();
  renderResult(scenario.result);
  state.scenarioId = id;
  $("btn-print").disabled = false;
}

async function searchPlace() {
  const term = $("place").value.trim();
  if (!term) return;
  const hint = $("search-hint");
  hint.textContent = "Searching…";
  try {
    const payload = await api(`/api/geocode?q=${encodeURIComponent(term)}`);
    if (!payload.results.length) {
      hint.textContent = "No match. Enter latitude and longitude by hand.";
      return;
    }
    const best = payload.results[0];
    $("lat").value = best.lat.toFixed(4);
    $("lon").value = best.lon.toFixed(4);
    hint.textContent = `Found ${best.name}, ${best.admin || ""} ${best.country || ""}. Adjusted the coordinates.`;
  } catch (error) {
    hint.textContent = error.message;
  }
}

/* ------------------------------------------------------------------ wiring */
function syncCompass() {
  const azimuth = num("azimuth");
  const tilt = num("tilt");
  $("compass-needle").setAttribute("transform", `rotate(${azimuth} 60 60)`);
  $("orientation-out").textContent = `${azimuth}° ${compassName(azimuth)}`;
  $("tilt-out").textContent = `${tilt}°`;
}

async function boot() {
  try {
    const payload = await api("/api/panels");
    state.panels = payload.panels;
    state.inverters = payload.inverters;
    $("panel").innerHTML = payload.panels
      .map((item) => `<option value="${item.id}">${item.name}</option>`)
      .join("");
    $("inverter").innerHTML = payload.inverters
      .map((item) => `<option value="${item.id}">${item.name}</option>`)
      .join("");
    $("panel").value = "rigid-400";
    $("inverter").value = "micro-400";
  } catch (error) {
    console.warn("presets failed", error);
  }

  $("panel").addEventListener("change", () => {
    const panel = state.panels.find((item) => item.id === $("panel").value);
    if (panel) {
      $("wp").value = panel.wp;
      $("area").value = panel.area_m2;
    }
  });

  $("azimuth").addEventListener("input", syncCompass);
  $("tilt").addEventListener("input", syncCompass);
  $("size-form").addEventListener("submit", calculate);
  $("btn-save").addEventListener("click", saveScenario);
  $("btn-print").addEventListener("click", printBrief);
  $("btn-pvgis").addEventListener("click", pvgisCheck);
  $("btn-scenarios").addEventListener("click", loadScenarios);
  $("btn-close-saved").addEventListener("click", () => ($("saved-card").hidden = true));
  $("btn-search").addEventListener("click", searchPlace);
  $("place").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchPlace();
    }
  });

  $("btn-add-obs").addEventListener("click", () => {
    state.obstructions.push({
      azimuth: num("obs-az") % 360,
      elevation: Math.max(0, Math.min(89, num("obs-el"))),
      width: Math.max(1, Math.min(180, num("obs-w"))),
    });
    renderObstructions();
  });

  presets();
  renderObstructions();
  syncCompass();
  calculate();
}

document.addEventListener("DOMContentLoaded", boot);