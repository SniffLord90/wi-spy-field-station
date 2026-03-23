const spectrumCanvas = document.getElementById("spectrumCanvas");
const spectrumCtx = spectrumCanvas.getContext("2d");
spectrumCtx.imageSmoothingEnabled = true;

const waterfallCanvas = document.getElementById("waterfall");
const waterfallCtx = waterfallCanvas.getContext("2d");
waterfallCtx.imageSmoothingEnabled = false;

const minimapCanvas = document.getElementById("minimapCanvas");
const minimapCtx = minimapCanvas.getContext("2d");
minimapCtx.imageSmoothingEnabled = false;

const statusEl = document.getElementById("status");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const helpBtn = document.getElementById("helpBtn");
const followLiveBtn = document.getElementById("followLiveBtn");
const resetMaxHoldBtn = document.getElementById("resetMaxHoldBtn");

const helpModalEl = document.getElementById("helpModal");
const closeHelpBtn = document.getElementById("closeHelpBtn");

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
const interferenceInfoEl = document.getElementById("interferenceInfo");
const bestChannelEl = document.getElementById("bestChannel");

const ch1El = document.getElementById("ch1");
const ch6El = document.getElementById("ch6");
const ch11El = document.getElementById("ch11");

const snr1AvgEl = document.getElementById("snr1avg");
const snr6AvgEl = document.getElementById("snr6avg");
const snr11AvgEl = document.getElementById("snr11avg");

const snr1PeakEl = document.getElementById("snr1peak");
const snr6PeakEl = document.getElementById("snr6peak");
const snr11PeakEl = document.getElementById("snr11peak");

const label1El = document.getElementById("label1");
const label6El = document.getElementById("label6");
const label11El = document.getElementById("label11");

const score1El = document.getElementById("score1");
const score6El = document.getElementById("score6");
const score11El = document.getElementById("score11");

const toggleLiveBtn = document.getElementById("toggleLive");
const toggleAvgBtn = document.getElementById("toggleAvg");
const toggleHoldBtn = document.getElementById("toggleHold");

const DBM_MIN = -110;
const DBM_MAX = -30;
const AVG_HISTORY_LIMIT = 20;
const VIEW_ROWS = 180;

let spectrumHistory = [];
let maxHold = null;

let sessionRows = [];
let lastRowsCommitted = 0;
let followLive = true;
let viewportStart = 0;
let isDraggingMinimap = false;

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

function updateButtons(running) {
    startBtn.disabled = !!running;
    stopBtn.disabled = !running;
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

function bindTraceToggles() {
    toggleLiveBtn.addEventListener("click", () => {
        traceState.live = !traceState.live;
        setToggleState(toggleLiveBtn, traceState.live);
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

    setToggleState(toggleLiveBtn, traceState.live);
    setToggleState(toggleAvgBtn, traceState.avg);
    setToggleState(toggleHoldBtn, traceState.hold);
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

    return `rgb(${r}, ${g}, ${b})`;
}

function clearWaterfall() {
    waterfallCtx.clearRect(0, 0, waterfallCanvas.width, waterfallCanvas.height);
}

function drawRowsToCanvas(ctx, canvas, rows) {
    const h = canvas.height;
    const w = canvas.width;

    ctx.clearRect(0, 0, w, h);

    if (!rows || rows.length === 0) {
        return;
    }

    const rowCount = rows.length;
    const colCount = rows[0].length;

    const rowHeight = h / rowCount;
    const colWidth = w / colCount;

    for (let y = 0; y < rowCount; y++) {
        const row = rows[rowCount - 1 - y];

        for (let x = 0; x < colCount; x++) {
            ctx.fillStyle = colorMap(row[x]);
            ctx.fillRect(
                x * colWidth,
                h - (y + 1) * rowHeight,
                Math.ceil(colWidth),
                Math.ceil(rowHeight)
            );
        }
    }
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
    drawRowsToCanvas(waterfallCtx, waterfallCanvas, rows);
}

function drawMinimap() {
    minimapCtx.clearRect(0, 0, minimapCanvas.width, minimapCanvas.height);

    if (sessionRows.length === 0) {
        return;
    }

    drawRowsToCanvas(minimapCtx, minimapCanvas, sessionRows);

    const totalRows = sessionRows.length;
    const visibleRows = Math.min(VIEW_ROWS, totalRows);
    const start = followLive ? Math.max(0, totalRows - visibleRows) : viewportStart;

    const y = (start / totalRows) * minimapCanvas.height;
    const h = Math.max(8, (visibleRows / totalRows) * minimapCanvas.height);

    minimapCtx.strokeStyle = "rgba(255,255,255,0.95)";
    minimapCtx.lineWidth = 2;
    minimapCtx.strokeRect(1, y, minimapCanvas.width - 2, h);

    minimapCtx.fillStyle = "rgba(255,255,255,0.10)";
    minimapCtx.fillRect(1, y, minimapCanvas.width - 2, h);
}

function setViewportFromMinimapY(y) {
    if (sessionRows.length === 0) return;

    const ratio = y / minimapCanvas.height;
    const targetRow = Math.floor(ratio * sessionRows.length);
    viewportStart = Math.max(0, Math.min(targetRow - Math.floor(VIEW_ROWS / 2), Math.max(0, sessionRows.length - VIEW_ROWS)));
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

function renderVerdict(verdict, analysis) {
    if (!verdict) {
        verdictPanelEl.className = "verdict-panel neutral";
        verdictBadgeEl.textContent = "--";
        verdictTitleEl.textContent = "Nog geen meting";
        verdictSummaryEl.textContent = "Start een meting om analyse te zien.";
        verdictActionEl.textContent = "--";
        verdictDetailsEl.innerHTML = "";
        return;
    }

    const severityClass = mapFieldStatusClass(verdict.field_status);
    verdictPanelEl.className = `verdict-panel ${severityClass}`;
    verdictBadgeEl.textContent = (verdict.field_status || "--").toUpperCase();
    verdictTitleEl.textContent = verdict.summary || "Analyse beschikbaar";
    verdictSummaryEl.textContent = analysis?.summary || verdict.recommended_text || "Analyse beschikbaar";
    verdictActionEl.textContent = verdict.action || analysis?.action || "--";

    verdictDetailsEl.innerHTML = "";

    const details = [];

    if (verdict.classification) {
        details.push(`Classificatie: ${verdict.classification}`);
    }

    if (verdict.confidence !== null && verdict.confidence !== undefined) {
        details.push(`Confidence: ${Math.round(verdict.confidence * 100)}%`);
    }

    if (verdict.non_overlapping_text) {
        details.push(verdict.non_overlapping_text);
    }

    details.forEach((item) => {
        const row = document.createElement("div");
        row.textContent = `• ${item}`;
        verdictDetailsEl.appendChild(row);
    });
}

function paintChannel(el, avgEl, peakEl, labelEl, scoreEl, chData, bestChannel, chNumber) {
    if (!chData) {
        el.textContent = "--";
        avgEl.textContent = "Avg SNR --";
        peakEl.textContent = "Peak SNR --";
        labelEl.textContent = "Kwaliteit --";
        scoreEl.textContent = "Score --";

        el.className = "channel-value neutral";
        avgEl.className = "channel-sub neutral";
        peakEl.className = "channel-sub neutral";
        labelEl.className = "channel-sub neutral";
        scoreEl.className = "channel-sub neutral";
        return;
    }

    el.textContent = valueOrDash(chData.mean_dbm, " dBm");
    avgEl.textContent = `Avg SNR ${valueOrDash(chData.avg_snr, " dB")}`;
    peakEl.textContent = `Peak SNR ${valueOrDash(chData.peak_snr, " dB")}`;
    labelEl.textContent = `Kwaliteit ${chData.label || "--"}`;
    scoreEl.textContent = `Score ${valueOrDash(chData.score)}`;

    let mainClass = "neutral";

    if (String(bestChannel) === String(chNumber)) {
        mainClass = "good";
    } else if (chData.score !== null && chData.score !== undefined) {
        mainClass = numberClassFromScore(chData.score);
    }

    el.className = `channel-value ${mainClass}`;
    avgEl.className = `channel-sub ${snrClass(chData.avg_snr)}`;
    peakEl.className = `channel-sub ${snrClass(chData.peak_snr)}`;
    labelEl.className = `channel-sub ${qualityClassFromLabel(chData.label)}`;
    scoreEl.className = `channel-sub ${numberClassFromScore(chData.score)}`;
}

function setFieldDefaults() {
    healthScoreEl.textContent = "--";
    healthScoreEl.className = "card-value neutral";

    noiseFloorEl.textContent = "--";
    peakInfoEl.textContent = "--";
    peakSnrEl.textContent = "--";
    peakSnrEl.className = "card-value neutral";
    activeZoneEl.textContent = "--";
    interferenceInfoEl.textContent = "--";
    bestChannelEl.textContent = "--";

    ch1El.textContent = "--";
    ch6El.textContent = "--";
    ch11El.textContent = "--";

    snr1AvgEl.textContent = "Avg SNR --";
    snr6AvgEl.textContent = "Avg SNR --";
    snr11AvgEl.textContent = "Avg SNR --";

    snr1PeakEl.textContent = "Peak SNR --";
    snr6PeakEl.textContent = "Peak SNR --";
    snr11PeakEl.textContent = "Peak SNR --";

    label1El.textContent = "Kwaliteit --";
    label6El.textContent = "Kwaliteit --";
    label11El.textContent = "Kwaliteit --";

    score1El.textContent = "Score --";
    score6El.textContent = "Score --";
    score11El.textContent = "Score --";

    ch1El.className = "channel-value neutral";
    ch6El.className = "channel-value neutral";
    ch11El.className = "channel-value neutral";

    snr1AvgEl.className = "channel-sub neutral";
    snr6AvgEl.className = "channel-sub neutral";
    snr11AvgEl.className = "channel-sub neutral";

    snr1PeakEl.className = "channel-sub neutral";
    snr6PeakEl.className = "channel-sub neutral";
    snr11PeakEl.className = "channel-sub neutral";

    label1El.className = "channel-sub neutral";
    label6El.className = "channel-sub neutral";
    label11El.className = "channel-sub neutral";

    score1El.className = "channel-sub neutral";
    score6El.className = "channel-sub neutral";
    score11El.className = "channel-sub neutral";

    verdictPanelEl.className = "verdict-panel neutral";
    verdictBadgeEl.textContent = "--";
    verdictTitleEl.textContent = "Nog geen meting";
    verdictSummaryEl.textContent = "Start een meting om analyse te zien.";
    verdictActionEl.textContent = "--";
    verdictDetailsEl.innerHTML = "";
}

function renderAnalysis(analysis) {
    if (!analysis || Object.keys(analysis).length === 0) {
        setFieldDefaults();
        return;
    }

    healthScoreEl.textContent = analysis.rf_health || "--";
    healthScoreEl.className = `card-value ${mapFieldStatusClass(analysis?.verdict?.field_status)}`;

    noiseFloorEl.textContent = valueOrDash(analysis.noise_floor, " dBm");

    if (analysis.peak !== null && analysis.peak !== undefined && analysis.peak_freq_mhz !== null && analysis.peak_freq_mhz !== undefined) {
        peakInfoEl.textContent = `${analysis.peak} dBm @ ${analysis.peak_freq_mhz} MHz`;
    } else {
        peakInfoEl.textContent = valueOrDash(analysis.peak, " dBm");
    }

    peakSnrEl.textContent = valueOrDash(analysis.peak_snr, " dB");
    peakSnrEl.className = `card-value ${snrClass(analysis.peak_snr)}`;

    activeZoneEl.textContent = analysis.active_zone || "--";
    interferenceInfoEl.textContent = analysis.interference_label || "--";

    if (analysis.best_channel !== null && analysis.best_channel !== undefined) {
        bestChannelEl.textContent = `Kanaal ${analysis.best_channel}`;
    } else {
        bestChannelEl.textContent = "--";
    }

    paintChannel(ch1El, snr1AvgEl, snr1PeakEl, label1El, score1El, analysis.ch1, analysis.best_channel, 1);
    paintChannel(ch6El, snr6AvgEl, snr6PeakEl, label6El, score6El, analysis.ch6, analysis.best_channel, 6);
    paintChannel(ch11El, snr11AvgEl, snr11PeakEl, label11El, score11El, analysis.ch11, analysis.best_channel, 11);

    renderVerdict(analysis.verdict, analysis);
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
    if (!lastUpdateTime) return "startend...";

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

    waterfallCanvas.addEventListener("wheel", (event) => {
        if (sessionRows.length === 0) return;

        event.preventDefault();
        followLive = false;

        const step = Math.max(1, Math.floor(VIEW_ROWS / 8));
        if (event.deltaY > 0) {
            viewportStart += step;
        } else {
            viewportStart -= step;
        }

        viewportStart = Math.max(0, Math.min(viewportStart, Math.max(0, sessionRows.length - VIEW_ROWS)));
        drawWaterfallViewport();
        drawMinimap();
    }, { passive: false });
}

startBtn.addEventListener("click", async () => {
    try {
        sessionRows = [];
        spectrumHistory = [];
        maxHold = null;
        lastRowsCommitted = 0;
        followLive = true;
        viewportStart = 0;

        await fetch("/start", { method: "POST" });
    } catch (err) {
        console.error(err);
    }
    setTimeout(poll, 300);
});

stopBtn.addEventListener("click", async () => {
    try {
        await fetch("/stop", { method: "POST" });
    } catch (err) {
        console.error(err);
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
poll();
setInterval(poll, 500);