const DBM_MIN = -110;
const DBM_MAX = -30;
const VIEW_ROWS = 180;
const AVG_HISTORY_LIMIT = 20;

const spectrumCanvas = document.getElementById("spectrumCanvas");
const spectrumCtx = spectrumCanvas.getContext("2d");
spectrumCtx.imageSmoothingEnabled = true;

const waterfallCanvas = document.getElementById("waterfall");
const waterfallCtx = waterfallCanvas.getContext("2d");
waterfallCtx.imageSmoothingEnabled = false;

const minimapCanvas = document.getElementById("minimapCanvas");
const minimapCtx = minimapCanvas.getContext("2d");
minimapCtx.imageSmoothingEnabled = false;

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const helpBtn = document.getElementById("helpBtn");
const closeHelpBtn = document.getElementById("closeHelpBtn");
const helpModalEl = document.getElementById("helpModal");
const followLiveBtn = document.getElementById("followLiveBtn");
const resetMaxHoldBtn = document.getElementById("resetMaxHoldBtn");
const profileSelect = document.getElementById("profileSelect");
const customerNumberInput = document.getElementById("customerNumberInput");
const notesInput = document.getElementById("notesInput");

const profileInfoEl = document.getElementById("profileInfo");
const statusEl = document.getElementById("status");

const verdictPanelEl = document.getElementById("verdictPanel");
const verdictBadgeEl = document.getElementById("verdictBadge");
const verdictTitleEl = document.getElementById("verdictTitle");
const verdictSummaryEl = document.getElementById("verdictSummary");
const verdictActionEl = document.getElementById("verdictAction");
const verdictDetailsEl = document.getElementById("verdictDetails");

const healthScoreEl = document.getElementById("healthScore");
const noiseFloorEl = document.getElementById("noiseFloor");
const peakInfoEl = document.getElementById("peakInfo");
const peakSnrEl = document.getElementById("peakSnr");
const activeZoneEl = document.getElementById("activeZone");
const interferenceLabelEl = document.getElementById("interferenceLabel");
const bestChannelEl = document.getElementById("bestChannel");

const ch1LabelEl = document.getElementById("ch1Label");
const ch1AvgEl = document.getElementById("ch1Avg");
const ch1PeakEl = document.getElementById("ch1Peak");

const ch6LabelEl = document.getElementById("ch6Label");
const ch6AvgEl = document.getElementById("ch6Avg");
const ch6PeakEl = document.getElementById("ch6Peak");

const ch11LabelEl = document.getElementById("ch11Label");
const ch11AvgEl = document.getElementById("ch11Avg");
const ch11PeakEl = document.getElementById("ch11Peak");

const channelStripEl = document.getElementById("channelStrip");
const channelMapEl = document.getElementById("channelMap");

const axisSpectrumStartEl = document.getElementById("axisSpectrumStart");
const axisSpectrumMidEl = document.getElementById("axisSpectrumMid");
const axisSpectrumEndEl = document.getElementById("axisSpectrumEnd");

const axisWaterfallStartEl = document.getElementById("axisWaterfallStart");
const axisWaterfallMidEl = document.getElementById("axisWaterfallMid");
const axisWaterfallEndEl = document.getElementById("axisWaterfallEnd");

const spectrumTitleEl = document.getElementById("spectrumTitle");
const waterfallTitleEl = document.getElementById("waterfallTitle");

const toggleCurrentBtn = document.getElementById("toggleCurrent");
const toggleAvgBtn = document.getElementById("toggleAvg");
const toggleHoldBtn = document.getElementById("toggleHold");

let profiles = [];
let defaultProfileKey = "";
let activeProfile = null;

let sessionRows = [];
let lastRowsCommitted = 0;
let followLive = true;
let viewportStart = 0;
let isDraggingMinimap = false;

let spectrumHistory = [];
let maxHold = null;

let waterfallBufferCanvas = null;
let waterfallBufferCtx = null;
let minimapBufferCanvas = null;
let minimapBufferCtx = null;

const traceState = {
  live: true,
  avg: true,
  hold: true,
};

function valueOrDash(value, suffix = "") {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  return `${value}${suffix}`;
}

function formatMHz(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return `${Number(value).toFixed(0)} MHz`;
}

function getProfileByKey(key) {
  return profiles.find((p) => p.key === key) || null;
}

function getSelectedProfile() {
  return getProfileByKey(profileSelect.value || defaultProfileKey);
}

function updateButtons(running) {
  startBtn.disabled = !!running;
  stopBtn.disabled = !running;
  profileSelect.disabled = !!running;
  customerNumberInput.disabled = !!running;
  notesInput.disabled = !!running;
}

function numberClassFromScore(score) {
  if (score === null || score === undefined || Number.isNaN(score)) return "neutral";
  if (score >= 70) return "good";
  if (score >= 45) return "warn";
  return "bad";
}

function snrClass(snr) {
  if (snr === null || snr === undefined || Number.isNaN(snr)) return "neutral";
  if (snr >= 35) return "good";
  if (snr >= 25) return "warn";
  return "bad";
}

function qualityClassFromLabel(label) {
  if (!label) return "neutral";
  const v = String(label).toLowerCase();
  if (v === "goed") return "good";
  if (v === "matig") return "warn";
  if (v === "slecht") return "bad";
  return "neutral";
}

function mapFieldStatusClass(fieldStatus) {
  switch (fieldStatus) {
    case "good":
    case "ok":
      return "good";
    case "degraded":
      return "warn";
    case "bad":
    case "critical":
      return "bad";
    default:
      return "neutral";
  }
}

function setToggleState(button, enabled) {
  if (enabled) {
    button.classList.add("active");
  } else {
    button.classList.remove("active");
  }
}

function setAxisLabels(axisLabels) {
  if (!Array.isArray(axisLabels) || axisLabels.length < 3) return;

  const [start, mid, end] = axisLabels;
  axisSpectrumStartEl.textContent = formatMHz(start);
  axisSpectrumMidEl.textContent = formatMHz(mid);
  axisSpectrumEndEl.textContent = formatMHz(end);

  axisWaterfallStartEl.textContent = formatMHz(start);
  axisWaterfallMidEl.textContent = formatMHz(mid);
  axisWaterfallEndEl.textContent = formatMHz(end);
}

function updateProfileMeta(profile) {
  activeProfile = profile || null;

  if (!profile) {
    profileInfoEl.textContent = "Nog geen profiel geladen";
    spectrumTitleEl.textContent = "Live spectrum";
    waterfallTitleEl.textContent = "Waterfall History";
    channelStripEl.style.display = "";
    channelMapEl.style.display = "";
    return;
  }

  profileInfoEl.textContent =
    `Profiel: ${profile.label} | Range index: ${profile.range_index} | ` +
    `${formatMHz(profile.freq_start_mhz)} - ${formatMHz(profile.freq_end_mhz)}`;

  spectrumTitleEl.textContent = `Live spectrum — ${profile.label}`;
  waterfallTitleEl.textContent = `Waterfall History — ${profile.label}`;

  const is2g = profile.channel_mode === "2g";
  channelStripEl.style.display = is2g ? "" : "none";
  channelMapEl.style.display = is2g ? "" : "none";

  setAxisLabels(profile.axis_labels_mhz || []);
}

async function loadProfiles() {
  const res = await fetch(`/profiles?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Kon profielen niet laden");
  }

  const data = await res.json();
  profiles = Array.isArray(data.profiles) ? data.profiles : [];
  defaultProfileKey = data.default_profile_key || "";

  profileSelect.innerHTML = "";

  for (const profile of profiles) {
    const option = document.createElement("option");
    option.value = profile.key;
    option.textContent = profile.label;
    profileSelect.appendChild(option);
  }

  if (defaultProfileKey) {
    profileSelect.value = defaultProfileKey;
    updateProfileMeta(getProfileByKey(defaultProfileKey));
  }
}

function bindTraceToggles() {
  toggleCurrentBtn.addEventListener("click", () => {
    traceState.live = !traceState.live;
    setToggleState(toggleCurrentBtn, traceState.live);
    drawSpectrumFromState();
  });

  toggleAvgBtn.addEventListener("click", () => {
    traceState.avg = !traceState.avg;
    setToggleState(toggleAvgBtn, traceState.avg);
    drawSpectrumFromState();
  });

  toggleHoldBtn.addEventListener("click", () => {
    traceState.hold = !traceState.hold;
    setToggleState(toggleHoldBtn, traceState.hold);
    drawSpectrumFromState();
  });

  setToggleState(toggleCurrentBtn, traceState.live);
  setToggleState(toggleAvgBtn, traceState.avg);
  setToggleState(toggleHoldBtn, traceState.hold);
}

function resetSessionState() {
  sessionRows = [];
  spectrumHistory = [];
  maxHold = null;
  lastRowsCommitted = 0;
  followLive = true;
  viewportStart = 0;
  clearSpectrum();
  clearWaterfall();
  drawMinimap();
}

function resetMaxHold() {
  if (spectrumHistory.length > 0) {
    maxHold = [...spectrumHistory[spectrumHistory.length - 1]];
  } else {
    maxHold = null;
  }
  drawSpectrumFromState();
}

function colorMap(dbm) {
  if (dbm < DBM_MIN) dbm = DBM_MIN;
  if (dbm > DBM_MAX) dbm = DBM_MAX;

  const t = (dbm - DBM_MIN) / (DBM_MAX - DBM_MIN);

  let r = 0, g = 0, b = 0;

  if (t < 0.25) {
    const x = t / 0.25;
    r = Math.round(40 * x);
    g = 0;
    b = Math.round(80 + 100 * x);
  } else if (t < 0.5) {
    const x = (t - 0.25) / 0.25;
    r = Math.round(40 + 120 * x);
    g = Math.round(20 * x);
    b = Math.round(180 - 100 * x);
  } else if (t < 0.75) {
    const x = (t - 0.5) / 0.25;
    r = Math.round(160 + 80 * x);
    g = Math.round(20 + 120 * x);
    b = Math.round(80 - 60 * x);
  } else {
    const x = (t - 0.75) / 0.25;
    r = 255;
    g = Math.round(140 + 115 * x);
    b = Math.round(20 + 180 * x);
  }

  return [r, g, b];
}

function clearWaterfall() {
  waterfallCtx.clearRect(0, 0, waterfallCanvas.width, waterfallCanvas.height);
}

function ensureBufferCanvas(targetWidth, targetHeight, type = "waterfall") {
  if (type === "waterfall") {
    if (
      !waterfallBufferCanvas ||
      waterfallBufferCanvas.width !== targetWidth ||
      waterfallBufferCanvas.height !== targetHeight
    ) {
      waterfallBufferCanvas = document.createElement("canvas");
      waterfallBufferCanvas.width = targetWidth;
      waterfallBufferCanvas.height = targetHeight;
      waterfallBufferCtx = waterfallBufferCanvas.getContext("2d", { alpha: false });
      waterfallBufferCtx.imageSmoothingEnabled = false;
    }
    return { canvas: waterfallBufferCanvas, ctx: waterfallBufferCtx };
  }

  if (
    !minimapBufferCanvas ||
    minimapBufferCanvas.width !== targetWidth ||
    minimapBufferCanvas.height !== targetHeight
  ) {
    minimapBufferCanvas = document.createElement("canvas");
    minimapBufferCanvas.width = targetWidth;
    minimapBufferCanvas.height = targetHeight;
    minimapBufferCtx = minimapBufferCanvas.getContext("2d", { alpha: false });
    minimapBufferCtx.imageSmoothingEnabled = false;
  }

  return { canvas: minimapBufferCanvas, ctx: minimapBufferCtx };
}

function drawRowsPixelStable(targetCtx, targetCanvas, rows, bufferType = "waterfall") {
  const w = targetCanvas.width;
  const h = targetCanvas.height;

  targetCtx.clearRect(0, 0, w, h);

  if (!rows || rows.length === 0) {
    return;
  }

  const rowCount = rows.length;
  const colCount = rows[0].length;

  const { canvas: bufferCanvas, ctx: bufferCtx } = ensureBufferCanvas(colCount, rowCount, bufferType);

  const imageData = bufferCtx.createImageData(colCount, rowCount);
  const pixels = imageData.data;

  for (let y = 0; y < rowCount; y++) {
    const row = rows[y];

    for (let x = 0; x < colCount; x++) {
      const [r, g, b] = colorMap(row[x]);
      const idx = (y * colCount + x) * 4;
      pixels[idx] = r;
      pixels[idx + 1] = g;
      pixels[idx + 2] = b;
      pixels[idx + 3] = 255;
    }
  }

  bufferCtx.putImageData(imageData, 0, 0);

  targetCtx.save();
  targetCtx.imageSmoothingEnabled = false;
  targetCtx.drawImage(bufferCanvas, 0, 0, w, h);
  targetCtx.restore();
}

function drawRowsToCanvas(ctx, canvas, rows, bufferType = "waterfall") {
  drawRowsPixelStable(ctx, canvas, rows, bufferType);
}

function getViewportRows() {
  if (sessionRows.length === 0) {
    return [];
  }

  const maxStart = Math.max(0, sessionRows.length - VIEW_ROWS);
  if (followLive) {
    viewportStart = maxStart;
  } else {
    viewportStart = Math.max(0, Math.min(viewportStart, maxStart));
  }

  return sessionRows.slice(viewportStart, viewportStart + VIEW_ROWS);
}

function drawWaterfallViewport() {
  const rows = getViewportRows();
  drawRowsToCanvas(waterfallCtx, waterfallCanvas, rows, "waterfall");
}

function drawMinimap() {
  minimapCtx.clearRect(0, 0, minimapCanvas.width, minimapCanvas.height);

  if (sessionRows.length === 0) {
    return;
  }

  drawRowsToCanvas(minimapCtx, minimapCanvas, sessionRows, "minimap");

  const totalRows = sessionRows.length;
  const visibleRows = Math.min(VIEW_ROWS, totalRows);
  const start = followLive ? Math.max(0, totalRows - visibleRows) : viewportStart;

  const y = (start / totalRows) * minimapCanvas.height;
  const h = Math.max(8, (visibleRows / totalRows) * minimapCanvas.height);

  minimapCtx.save();
  minimapCtx.strokeStyle = "rgba(255,255,255,0.95)";
  minimapCtx.lineWidth = 2;
  minimapCtx.strokeRect(1, y, minimapCanvas.width - 2, h);

  minimapCtx.fillStyle = "rgba(255,255,255,0.10)";
  minimapCtx.fillRect(1, y, minimapCanvas.width - 2, h);
  minimapCtx.restore();
}

function setViewportFromMinimapY(y) {
  if (sessionRows.length === 0) return;

  const ratio = y / minimapCanvas.height;
  const targetRow = Math.floor(ratio * sessionRows.length);
  viewportStart = Math.max(
    0,
    Math.min(
      targetRow - Math.floor(VIEW_ROWS / 2),
      Math.max(0, sessionRows.length - VIEW_ROWS)
    )
  );
  followLive = false;
  drawWaterfallViewport();
  drawMinimap();
}

function clearSpectrum() {
  spectrumCtx.clearRect(0, 0, spectrumCanvas.width, spectrumCanvas.height);
}

function dbmToY(dbm, height, paddingTop = 18, paddingBottom = 28) {
  const usableHeight = height - paddingTop - paddingBottom;
  const clamped = Math.max(DBM_MIN, Math.min(DBM_MAX, dbm));
  const normalized = (clamped - DBM_MIN) / (DBM_MAX - DBM_MIN);
  return height - paddingBottom - (normalized * usableHeight);
}

function xForIndex(index, total, width, paddingLeft = 42, paddingRight = 10) {
  if (total <= 1) return paddingLeft;
  const usableWidth = width - paddingLeft - paddingRight;
  return paddingLeft + (index / (total - 1)) * usableWidth;
}

function drawSpectrumBackground() {
  const w = spectrumCanvas.width;
  const h = spectrumCanvas.height;

  const gradient = spectrumCtx.createLinearGradient(0, 0, 0, h);
  gradient.addColorStop(0, "#071019");
  gradient.addColorStop(1, "#02050a");

  spectrumCtx.clearRect(0, 0, w, h);
  spectrumCtx.fillStyle = gradient;
  spectrumCtx.fillRect(0, 0, w, h);

  spectrumCtx.strokeStyle = "rgba(255,255,255,0.05)";
  spectrumCtx.lineWidth = 1;

  const verticalFractions = [0, 0.25, 0.5, 0.75, 1];
  verticalFractions.forEach((f) => {
    const x = 42 + (w - 52) * f;
    spectrumCtx.beginPath();
    spectrumCtx.moveTo(x, 10);
    spectrumCtx.lineTo(x, h - 20);
    spectrumCtx.stroke();
  });

  const dbmLines = [-110, -100, -90, -80, -70, -60, -50, -40];
  dbmLines.forEach((dbm) => {
    const y = dbmToY(dbm, h);
    spectrumCtx.beginPath();
    spectrumCtx.moveTo(36, y);
    spectrumCtx.lineTo(w - 6, y);
    spectrumCtx.stroke();

    spectrumCtx.fillStyle = "rgba(210,225,255,0.62)";
    spectrumCtx.font = "12px Arial";
    spectrumCtx.fillText(`${dbm}`, 8, y + 4);
  });

  spectrumCtx.strokeStyle = "rgba(130,180,255,0.18)";
  spectrumCtx.lineWidth = 1;
  spectrumCtx.strokeRect(36, 10, w - 46, h - 30);
}

function drawTrace(values, options = {}) {
  if (!values || values.length === 0) return;

  const w = spectrumCanvas.width;
  const h = spectrumCanvas.height;

  const {
    strokeStyle = "#ffffff",
    lineWidth = 2,
    glow = null,
    fill = null,
  } = options;

  if (fill) {
    spectrumCtx.beginPath();
    for (let i = 0; i < values.length; i++) {
      const x = xForIndex(i, values.length, w);
      const y = dbmToY(values[i], h);

      if (i === 0) {
        spectrumCtx.moveTo(x, y);
      } else {
        spectrumCtx.lineTo(x, y);
      }
    }

    const lastX = xForIndex(values.length - 1, values.length, w);
    const firstX = xForIndex(0, values.length, w);
    const baseY = dbmToY(DBM_MIN, h);

    spectrumCtx.lineTo(lastX, baseY);
    spectrumCtx.lineTo(firstX, baseY);
    spectrumCtx.closePath();

    spectrumCtx.fillStyle = fill;
    spectrumCtx.fill();
  }

  spectrumCtx.save();

  if (glow) {
    spectrumCtx.shadowBlur = glow.blur;
    spectrumCtx.shadowColor = glow.color;
  }

  spectrumCtx.beginPath();
  spectrumCtx.strokeStyle = strokeStyle;
  spectrumCtx.lineWidth = lineWidth;
  spectrumCtx.lineJoin = "round";
  spectrumCtx.lineCap = "round";

  for (let i = 0; i < values.length; i++) {
    const x = xForIndex(i, values.length, w);
    const y = dbmToY(values[i], h);

    if (i === 0) {
      spectrumCtx.moveTo(x, y);
    } else {
      spectrumCtx.lineTo(x, y);
    }
  }

  spectrumCtx.stroke();
  spectrumCtx.restore();
}

function updateSpectrumState(latestSweep) {
  if (!latestSweep || latestSweep.length === 0) return;

  spectrumHistory.push([...latestSweep]);
  if (spectrumHistory.length > AVG_HISTORY_LIMIT) {
    spectrumHistory.shift();
  }

  if (!maxHold || maxHold.length !== latestSweep.length) {
    maxHold = [...latestSweep];
  } else {
    for (let i = 0; i < latestSweep.length; i++) {
      if (latestSweep[i] > maxHold[i]) {
        maxHold[i] = latestSweep[i];
      }
    }
  }
}

function computeAverageTrace() {
  if (spectrumHistory.length === 0) return [];

  const bins = spectrumHistory[0].length;
  const avg = new Array(bins).fill(0);

  for (const row of spectrumHistory) {
    for (let i = 0; i < bins; i++) {
      avg[i] += row[i];
    }
  }

  for (let i = 0; i < bins; i++) {
    avg[i] = avg[i] / spectrumHistory.length;
  }

  return avg;
}

function drawSpectrumFromState() {
  drawSpectrumBackground();

  if (spectrumHistory.length === 0) {
    return;
  }

  const latestSweep = spectrumHistory[spectrumHistory.length - 1];
  const avgTrace = computeAverageTrace();

  if (traceState.hold && maxHold) {
    drawTrace(maxHold, {
      strokeStyle: "rgba(255, 86, 86, 0.95)",
      lineWidth: 1.8,
      glow: { blur: 6, color: "rgba(255, 86, 86, 0.45)" }
    });
  }

  if (traceState.avg && avgTrace.length > 0) {
    drawTrace(avgTrace, {
      strokeStyle: "rgba(255, 215, 75, 0.98)",
      lineWidth: 2.1,
      glow: { blur: 5, color: "rgba(255, 215, 75, 0.30)" }
    });
  }

  if (traceState.live && latestSweep) {
    drawTrace(latestSweep, {
      fill: "rgba(74, 194, 255, 0.10)",
      strokeStyle: "rgba(74, 194, 255, 1)",
      lineWidth: 2.4,
      glow: { blur: 8, color: "rgba(74, 194, 255, 0.35)" }
    });
  }
}

function renderVerdict(verdict) {
  if (!verdict) {
    verdictPanelEl.className = "verdict-panel neutral";
    verdictBadgeEl.textContent = "--";
    verdictTitleEl.textContent = "Nog geen meting";
    verdictSummaryEl.textContent = "Start een meting om analyse te zien.";
    verdictActionEl.textContent = "--";
    verdictDetailsEl.innerHTML = "";
    return;
  }

  const severity = verdict.severity || "neutral";
  verdictPanelEl.className = `verdict-panel ${severity}`;
  verdictBadgeEl.textContent = verdict.badge || "--";
  verdictTitleEl.textContent = verdict.title || "--";
  verdictSummaryEl.textContent = verdict.summary || "--";
  verdictActionEl.textContent = verdict.action || "--";

  verdictDetailsEl.innerHTML = "";
  const details = Array.isArray(verdict.details) ? verdict.details : [];
  for (const item of details) {
    const div = document.createElement("div");
    div.textContent = `• ${item}`;
    verdictDetailsEl.appendChild(div);
  }
}

function renderChannelBlock(data, labelEl, avgEl, peakEl) {
  if (!data) {
    labelEl.textContent = "--";
    avgEl.textContent = "Avg SNR --";
    peakEl.textContent = "Peak SNR --";
    return;
  }

  labelEl.textContent = data.label || "--";
  avgEl.textContent = `Avg SNR ${valueOrDash(data.avg_snr, " dB")}`;
  peakEl.textContent = `Peak SNR ${valueOrDash(data.peak_snr, " dB")}`;
}

function setFieldDefaults() {
  verdictPanelEl.className = "verdict-panel neutral";
  verdictBadgeEl.textContent = "--";
  verdictTitleEl.textContent = "Nog geen meting";
  verdictSummaryEl.textContent = "Start een meting om analyse te zien.";
  verdictActionEl.textContent = "--";
  verdictDetailsEl.innerHTML = "";

  healthScoreEl.textContent = "--";
  noiseFloorEl.textContent = "--";
  peakInfoEl.textContent = "--";
  peakSnrEl.textContent = "--";
  activeZoneEl.textContent = "--";
  interferenceLabelEl.textContent = "--";
  bestChannelEl.textContent = "--";

  renderChannelBlock(null, ch1LabelEl, ch1AvgEl, ch1PeakEl);
  renderChannelBlock(null, ch6LabelEl, ch6AvgEl, ch6PeakEl);
  renderChannelBlock(null, ch11LabelEl, ch11AvgEl, ch11PeakEl);
}

function renderAnalysis(analysis) {
  if (!analysis || Object.keys(analysis).length === 0) {
    setFieldDefaults();
    return;
  }

  renderVerdict(analysis.verdict);

  healthScoreEl.textContent = analysis.rf_health || "--";
  healthScoreEl.className = `card-value ${mapFieldStatusClass(analysis?.verdict?.field_status)}`;

  noiseFloorEl.textContent = valueOrDash(analysis.noise_floor, " dBm");

  if (
    analysis.peak !== null &&
    analysis.peak !== undefined &&
    analysis.peak_freq_mhz !== null &&
    analysis.peak_freq_mhz !== undefined
  ) {
    peakInfoEl.textContent = `${analysis.peak} dBm @ ${analysis.peak_freq_mhz} MHz`;
  } else {
    peakInfoEl.textContent = valueOrDash(analysis.peak, " dBm");
  }

  peakSnrEl.textContent = valueOrDash(analysis.peak_snr, " dB");
  peakSnrEl.className = `card-value ${snrClass(analysis.peak_snr)}`;

  activeZoneEl.textContent = analysis.active_zone || "--";
  interferenceLabelEl.textContent = analysis.interference_label || "--";
  bestChannelEl.textContent =
    analysis.best_channel || (activeProfile?.channel_mode === "2g" ? "--" : "n.v.t.");

  renderChannelBlock(analysis.channel_1 || null, ch1LabelEl, ch1AvgEl, ch1PeakEl);
  renderChannelBlock(analysis.channel_6 || null, ch6LabelEl, ch6AvgEl, ch6PeakEl);
  renderChannelBlock(analysis.channel_11 || null, ch11LabelEl, ch11AvgEl, ch11PeakEl);
}

function openHelp() {
  helpModalEl.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeHelp() {
  helpModalEl.classList.add("hidden");
  document.body.style.overflow = "";
}

function formatRunningText(running, lastUpdateTime) {
  if (!running) return "gestopt";
  if (!lastUpdateTime) return "startend";

  const age = (Date.now() / 1000) - lastUpdateTime;
  if (age < 2) return "live";
  return `laatste update ${age.toFixed(1)}s geleden`;
}

function appendLatestSweepIfNeeded(data) {
  const status = data.status || {};
  const rowsCommitted = status.rows_committed ?? 0;
  const latestSweep = data.latest_sweep || [];

  if (!Array.isArray(latestSweep) || latestSweep.length === 0) {
    return;
  }

  if (rowsCommitted > lastRowsCommitted) {
    sessionRows.push([...latestSweep]);
    lastRowsCommitted = rowsCommitted;
  }
}

async function startCapture() {
  const selectedKey = profileSelect.value || defaultProfileKey;
  const customerNumber = (customerNumberInput.value || "").trim();
  const notes = (notesInput.value || "").trim();

  if (!customerNumber) {
    alert("Vul eerst een klantnummer in.");
    customerNumberInput.focus();
    return;
  }

  resetSessionState();
  setFieldDefaults();

  const res = await fetch("/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      profile_key: selectedKey,
      customer_number: customerNumber,
      notes: notes
    }),
  });

  const data = await res.json();

  if (!res.ok || !data.ok) {
    throw new Error(data.message || "Start mislukt");
  }

  if (data.status?.active_profile) {
    updateProfileMeta(data.status.active_profile);
  }
}

async function stopCapture() {
  const res = await fetch("/stop", { method: "POST" });
  const data = await res.json();

  if (!res.ok || !data.ok) {
    throw new Error(data.message || "Stop mislukt");
  }
}

async function poll() {
  try {
    const res = await fetch(`/data?t=${Date.now()}`, { cache: "no-store" });

    if (!res.ok) {
      statusEl.textContent = "Geen data beschikbaar";
      updateButtons(false);
      setFieldDefaults();
      return;
    }

    const data = await res.json();
    const status = data.status || {};
    const running = !!status.running;

    if (data.profile) {
      updateProfileMeta(data.profile);

      if (running && profileSelect.value !== data.profile.key) {
        profileSelect.value = data.profile.key;
      }
    }

    appendLatestSweepIfNeeded(data);

    if (Array.isArray(data.latest_sweep) && data.latest_sweep.length > 0) {
      updateSpectrumState(data.latest_sweep);
      drawSpectrumFromState();
    } else if (!running) {
      clearSpectrum();
    }

    if (sessionRows.length > 0) {
      drawWaterfallViewport();
      drawMinimap();
    } else if (!running) {
      clearWaterfall();
    }

    renderAnalysis(data.analysis);
    updateButtons(running);

    const rowsVisible = getViewportRows().length;
    const samples = Array.isArray(data.latest_sweep) ? data.latest_sweep.length : 0;
    const ageText = formatRunningText(running, status.last_update_time);
    const modeText = followLive ? "live volgen" : "history mode";

    statusEl.textContent =
      `Rows zichtbaar: ${rowsVisible} | Totaal sessie: ${sessionRows.length} | Samples: ${samples} | Status: ${ageText} | Mode: ${modeText} | Session: ${status.session_id ?? "--"}`;
  } catch (err) {
    console.error("Poll error:", err);
    statusEl.textContent = "Verbinding mislukt, opnieuw proberen...";
    updateButtons(false);
    setFieldDefaults();
  }
}

function bindMinimap() {
  const handlePointer = (event) => {
    const rect = minimapCanvas.getBoundingClientRect();
    const y = event.clientY - rect.top;
    setViewportFromMinimapY(y);
  };

  minimapCanvas.addEventListener("mousedown", (event) => {
    isDraggingMinimap = true;
    handlePointer(event);
  });

  window.addEventListener("mousemove", (event) => {
    if (!isDraggingMinimap) return;
    handlePointer(event);
  });

  window.addEventListener("mouseup", () => {
    isDraggingMinimap = false;
  });

  minimapCanvas.addEventListener("click", handlePointer);

  waterfallCanvas.addEventListener(
    "wheel",
    (event) => {
      if (sessionRows.length === 0) return;

      event.preventDefault();
      followLive = false;

      const step = Math.max(1, Math.floor(VIEW_ROWS / 8));
      if (event.deltaY > 0) {
        viewportStart += step;
      } else {
        viewportStart -= step;
      }

      viewportStart = Math.max(
        0,
        Math.min(viewportStart, Math.max(0, sessionRows.length - VIEW_ROWS))
      );
      drawWaterfallViewport();
      drawMinimap();
    },
    { passive: false }
  );
}

profileSelect.addEventListener("change", () => {
  const selected = getSelectedProfile();
  if (selected) {
    updateProfileMeta(selected);
  }
});

startBtn.addEventListener("click", async () => {
  try {
    await startCapture();
  } catch (err) {
    console.error(err);
    alert(err.message);
  }
  setTimeout(poll, 300);
});

stopBtn.addEventListener("click", async () => {
  try {
    await stopCapture();
  } catch (err) {
    console.error(err);
    alert(err.message);
  }
  setTimeout(poll, 300);
});

followLiveBtn.addEventListener("click", () => {
  followLive = true;
  drawWaterfallViewport();
  drawMinimap();
});

resetMaxHoldBtn.addEventListener("click", () => {
  resetMaxHold();
});

helpBtn.addEventListener("click", openHelp);
closeHelpBtn.addEventListener("click", closeHelp);

helpModalEl.addEventListener("click", (event) => {
  if (event.target === helpModalEl) {
    closeHelp();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !helpModalEl.classList.contains("hidden")) {
    closeHelp();
  }
});

bindTraceToggles();
bindMinimap();
setFieldDefaults();
clearSpectrum();
clearWaterfall();

(async function init() {
  try {
    await loadProfiles();
  } catch (err) {
    console.error(err);
    profileInfoEl.textContent = "Kon profielen niet laden";
  }

  poll();
  setInterval(poll, 250);
})();