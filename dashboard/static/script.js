/**
 * HealthOps Dashboard — script.js
 * Real-time polling, Chart.js charts, service card rendering,
 * event log, alert/toast system.
 */

"use strict";

// ─────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────
const POLL_INTERVAL   = 2000;   // ms
const HISTORY_MAX     = 60;     // data points retained
const THRESHOLD       = 0.75;
const RING_CIRCUMFERENCE = 2 * Math.PI * 52;  // matches r=52 in SVG

const SERVICES = ["order", "tracking", "delivery"];

const SVC_ICONS = {
  order:    "📦",
  tracking: "📡",
  delivery: "🚚",
};

const SVC_COLORS = {
  order:    { line: "#3d9be9", fill: "rgba(61,155,233,0.12)"  },
  tracking: { line: "#a78bfa", fill: "rgba(167,139,250,0.12)" },
  delivery: { line: "#f97316", fill: "rgba(249,115,22,0.12)"  },
};

// ─────────────────────────────────────────────
// State
// ─────────────────────────────────────────────
const history = {
  labels:   [],   // timestamps (short HH:MM:SS)
  health: { order: [], tracking: [], delivery: [] },
  cpu:    { order: [], tracking: [], delivery: [] },
  latency:{ order: [], tracking: [], delivery: [] },
};

let prevSystemHealth   = null;
let lastRollbackSeenAt = null;
let alertDismissed     = false;
let toastTimer         = null;
let consecutiveFails   = 0;

// ─────────────────────────────────────────────
// Chart.js global defaults
// ─────────────────────────────────────────────
Chart.defaults.color              = "#7a9ab8";
Chart.defaults.borderColor        = "#1e2a3a";
Chart.defaults.font.family        = "'JetBrains Mono', monospace";
Chart.defaults.font.size          = 11;
Chart.defaults.animation.duration = 400;

function makeTimeSeriesChart(canvasId, datasets, yLabel, yMin, yMax, tickFmt) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  return new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: {
            usePointStyle: true,
            pointStyle:    "circle",
            boxWidth:      8,
            padding:       16,
            font:          { size: 11, family: "'JetBrains Mono', monospace" },
          },
        },
        tooltip: {
          backgroundColor: "#1a2130",
          borderColor:     "#2a3a50",
          borderWidth:     1,
          padding:         10,
          callbacks: {
            label: ctx => {
              const v = ctx.parsed.y;
              return `  ${ctx.dataset.label}: ${tickFmt ? tickFmt(v) : v}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(30,42,58,0.7)" },
          ticks: { maxTicksLimit: 8, maxRotation: 0 },
        },
        y: {
          min: yMin,
          max: yMax,
          grid:  { color: "rgba(30,42,58,0.7)" },
          title: { display: true, text: yLabel, color: "#3d5470", font: { size: 10 } },
          ticks: {
            callback: tickFmt || (v => v),
          },
        },
      },
    },
  });
}

// Build dataset specs for each service
function svcDatasets(field) {
  return SERVICES.map(svc => ({
    label:           svc,
    data:            [],
    borderColor:     SVC_COLORS[svc].line,
    backgroundColor: SVC_COLORS[svc].fill,
    fill:            true,
    tension:         0.35,
    pointRadius:     0,
    pointHitRadius:  12,
    borderWidth:     2,
  }));
}

const chartHealth  = makeTimeSeriesChart(
  "chart-health",
  svcDatasets("health"),
  "H-score",
  0, 1,
  v => v.toFixed(2)
);

const chartCPU = makeTimeSeriesChart(
  "chart-cpu",
  svcDatasets("cpu"),
  "millicores",
  0, null,
  v => `${v}m`
);

const chartLatency = makeTimeSeriesChart(
  "chart-latency",
  svcDatasets("latency"),
  "seconds",
  0, null,
  v => `${v.toFixed(3)}s`
);

// Add threshold line plugin for health chart
chartHealth.options.plugins.annotation = {};  // optional — keep it clean

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────
function healthClass(h) {
  if (h >= THRESHOLD) return "healthy";
  if (h >= 0.5)       return "degraded";
  return "critical";
}

function healthLabel(h) {
  if (h >= THRESHOLD) return "Healthy";
  if (h >= 0.5)       return "Degraded";
  return "Unhealthy";
}

function healthColor(cls) {
  return { healthy: "#00e5a0", degraded: "#f5c842", critical: "#ff4d6a" }[cls];
}

// Returns a CSS width% for a progress bar (clamped 0–100)
function pct(val, max) {
  return `${Math.min(100, Math.max(0, (val / max) * 100)).toFixed(1)}%`;
}

function shortTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  return isNaN(d) ? ts : ts; // already formatted by Python; pass through
}

// ─────────────────────────────────────────────
// System panel updater
// ─────────────────────────────────────────────
function updateSystemPanel(data) {
  const h   = data.system_health ?? 0;
  const cls = healthClass(h);

  // Badge
  const badge = document.getElementById("sys-badge");
  badge.className = `sys-badge ${cls}`;
  badge.querySelector(".sys-badge-label").textContent = healthLabel(h);

  // Ring
  const ring   = document.getElementById("ring-fill");
  const color  = healthColor(cls);
  const offset = RING_CIRCUMFERENCE * (1 - h);
  ring.style.strokeDashoffset = offset;
  ring.style.stroke           = color;
  ring.style.filter           = `drop-shadow(0 0 8px ${color})`;

  // Big score
  const scoreEl = document.getElementById("sys-score");
  scoreEl.textContent = h.toFixed(3);
  scoreEl.style.color = color;

  // Meta
  document.getElementById("last-update").textContent    = data.last_update  ?? "—";
  document.getElementById("last-rollback").textContent  = data.last_rollback ?? "Never";
  document.getElementById("rollback-count").textContent = data.rollback_count ?? 0;

  const lastEventEl = document.getElementById("last-event");
  lastEventEl.textContent = data.last_event ?? "—";

  // Footer clock
  document.getElementById("footer-time").textContent = new Date().toLocaleTimeString();
}

// ─────────────────────────────────────────────
// Service card builder / updater
// ─────────────────────────────────────────────
function renderServiceCard(svcName, svcData) {
  const h   = svcData.health   ?? 0;
  const cls = healthClass(h);
  const color = healthColor(cls);

  const lat = (svcData.latency ?? 0).toFixed(4);
  const cpu = svcData.cpu    ?? 0;
  const mem = svcData.memory ?? 0;

  const card = document.getElementById(`card-${svcName}`);
  if (!card) return;

  card.className = `svc-card state-${cls}`;
  card.style.borderColor = color + "55";
  card.style.boxShadow   = `0 0 20px ${color}11`;

  card.innerHTML = `
    <div class="accent-bar" style="background:${color};"></div>

    <div class="card-head">
      <div>
        <div class="card-name">${svcName} <span class="svc-icon">${SVC_ICONS[svcName]}</span></div>
      </div>
      <div class="status-badge ${cls}">
        <span>●</span>
        <span>${healthLabel(h)}</span>
      </div>
    </div>

    <div class="card-score">
      <span class="card-score-num" style="color:${color}">${h.toFixed(3)}</span>
      <span class="card-score-label">health score</span>
    </div>

    <div class="card-metrics">

      <div class="metric-row">
        <div class="metric-label-row">
          <span class="metric-name">Latency</span>
          <span class="metric-value">${lat}s</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill"
               style="width:${pct(parseFloat(lat), 0.5)};
                      background:${latencyColor(parseFloat(lat))};"></div>
        </div>
      </div>

      <div class="metric-row">
        <div class="metric-label-row">
          <span class="metric-name">CPU</span>
          <span class="metric-value">${cpu}m</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill"
               style="width:${pct(cpu, 500)};
                      background:${cpuColor(cpu)};"></div>
        </div>
      </div>

      <div class="metric-row">
        <div class="metric-label-row">
          <span class="metric-name">Memory</span>
          <span class="metric-value">${mem} Mi</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill"
               style="width:${pct(mem, 200)};
                      background:${memColor(mem)};"></div>
        </div>
      </div>

    </div>
  `;
}

function latencyColor(v) {
  if (v < 0.2) return "#00e5a0";
  if (v < 0.4) return "#f5c842";
  return "#ff4d6a";
}
function cpuColor(v) {
  if (v < 200) return "#00e5a0";
  if (v < 400) return "#f5c842";
  return "#ff4d6a";
}
function memColor(v) {
  if (v < 100) return "#00e5a0";
  if (v < 160) return "#f5c842";
  return "#ff4d6a";
}

// ─────────────────────────────────────────────
// Chart history updater
// ─────────────────────────────────────────────
function pushHistory(data) {
  const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });

  history.labels.push(ts);
  if (history.labels.length > HISTORY_MAX) history.labels.shift();

  SERVICES.forEach(svc => {
    const svcData = data.services?.[svc] ?? {};

    ["health", "cpu", "latency"].forEach(field => {
      history[field][svc].push(svcData[field] ?? 0);
      if (history[field][svc].length > HISTORY_MAX)
        history[field][svc].shift();
    });
  });
}

function syncChart(chart, field) {
  chart.data.labels = [...history.labels];
  SERVICES.forEach((svc, i) => {
    chart.data.datasets[i].data = [...history[field][svc]];
  });
  chart.update("none");   // no animation for live updates — smooth & fast
}

// ─────────────────────────────────────────────
// Event log updater
// ─────────────────────────────────────────────
function updateEventLog(events) {
  if (!events || !events.length) return;
  const log = document.getElementById("event-log");

  // Rebuild from scratch on each poll (events are already ordered newest-last)
  log.innerHTML = "";
  const reversed = [...events].reverse();  // newest on top

  reversed.forEach((ev, idx) => {
    const li = document.createElement("li");
    li.textContent = ev;

    if (ev.includes("Rollback") || ev.includes("rollback"))
      li.classList.add("ev-rollback");
    else if (ev.includes("✅"))
      li.classList.add("ev-healthy");
    else if (ev.includes("⚠️") || ev.includes("cooldown") || ev.includes("spike"))
      li.classList.add("ev-warn");

    if (idx === 0) li.style.animationDelay = "0ms";

    log.appendChild(li);
  });

  // Auto-scroll to top (newest)
  log.scrollTop = 0;
}

// ─────────────────────────────────────────────
// Alert / toast system
// ─────────────────────────────────────────────
function showAlert(text) {
  if (alertDismissed) return;
  const banner = document.getElementById("alert-banner");
  document.getElementById("alert-text").textContent = text;
  banner.classList.remove("hidden");
}

function hideAlert() {
  document.getElementById("alert-banner").classList.add("hidden");
  alertDismissed = false;
}

window.dismissAlert = () => {
  document.getElementById("alert-banner").classList.add("hidden");
  alertDismissed = true;
};

function showRollbackToast(ts) {
  const toast = document.getElementById("rollback-toast");
  document.getElementById("toast-sub").textContent = ts ?? "—";
  toast.classList.remove("hidden");

  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.add("hidden");
  }, 6000);
}

// ─────────────────────────────────────────────
// Poll indicator
// ─────────────────────────────────────────────
function setPollStatus(ok) {
  const pill = document.getElementById("poll-pill");
  if (ok) {
    pill.textContent = "LIVE";
    pill.classList.remove("stale");
  } else {
    pill.textContent = "STALE";
    pill.classList.add("stale");
  }
}

// ─────────────────────────────────────────────
// Main polling loop
// ─────────────────────────────────────────────
async function fetchAndRender() {
  try {
    const resp = await fetch("/data", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const data = await resp.json();
    consecutiveFails = 0;
    setPollStatus(true);

    // System panel
    updateSystemPanel(data);

    // Service cards
    SERVICES.forEach(svc => {
      renderServiceCard(svc, data.services?.[svc] ?? {});
    });

    // History + charts
    pushHistory(data);
    syncChart(chartHealth,  "health");
    syncChart(chartCPU,     "cpu");
    syncChart(chartLatency, "latency");

    // Event log
    if (data.events) updateEventLog(data.events);

    // Alerts
    const h = data.system_health ?? 1;
    if (h < THRESHOLD) {
      showAlert(`⚠️  System health critical: H = ${h.toFixed(3)} (threshold 0.75) — auto-rollback may be triggered`);
      alertDismissed = false;
    } else {
      hideAlert();
    }

    // Rollback toast — show only on new rollback
    if (data.last_rollback && data.last_rollback !== lastRollbackSeenAt) {
      lastRollbackSeenAt = data.last_rollback;
      if (prevSystemHealth !== null)   // skip the very first poll
        showRollbackToast(data.last_rollback);
    }

    prevSystemHealth = h;

  } catch (err) {
    consecutiveFails++;
    console.warn("Poll error:", err);
    if (consecutiveFails >= 3) setPollStatus(false);
  }
}

// ─────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────
(async function init() {
  // Initialise service cards with shimmer placeholders
  SERVICES.forEach(svc => {
    const card = document.getElementById(`card-${svc}`);
    if (card) {
      card.innerHTML = `
        <div class="accent-bar shimmer" style="background:var(--border-bright);"></div>
        <div class="card-head">
          <div class="card-name">${svc} ${SVC_ICONS[svc]}</div>
          <div class="status-badge" style="background:var(--bg-elevated);color:var(--text-muted);border-color:var(--border);">
            Loading…
          </div>
        </div>
        <div class="card-score">
          <span class="card-score-num" style="color:var(--text-muted)">—</span>
          <span class="card-score-label">health score</span>
        </div>
      `;
    }
  });

  await fetchAndRender();
  setInterval(fetchAndRender, POLL_INTERVAL);
})();
