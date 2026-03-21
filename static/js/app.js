const canvas = document.getElementById("waterfall");
const ctx = canvas.getContext("2d");
ctx.imageSmoothingEnabled = false;

const statusEl = document.getElementById("status");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const helpBtn = document.getElementById("helpBtn");

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

function colorMap(dbm) {
    if (dbm < -110) dbm = -110;
    if (dbm > -30) dbm = -30;

    const t = (dbm + 110) / 80;

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
    ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function drawWaterfall(rows) {
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

function updateButtons(running) {
    startBtn.disabled = !!running;
    stopBtn.disabled = !running;
}

function valueOrDash(value, suffix = "") {
    if (value === null || value === undefined || value === "") {
        return "--";
    }
    return `${value}${suffix}`;
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

function formatRunningText(running, lastUpdateTime) {
    if (!running) {
        return "gestopt";
    }

    if (!lastUpdateTime) {
        return "startend...";
    }

    const age = (Date.now() / 1000) - lastUpdateTime;

    if (age < 2) {
        return "live";
    }

    return `laatste update ${age.toFixed(1)}s geleden`;
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

function qualityClassFromLabel(label) {
    if (!label) return "neutral";
    const value = String(label).toLowerCase();

    if (value === "goed") return "good";
    if (value === "matig") return "warn";
    if (value === "slecht") return "bad";

    return "neutral";
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

async function poll() {
    try {
        const res = await fetch("/data?t=" + Date.now(), { cache: "no-store" });

        if (!res.ok) {
            statusEl.textContent = "Geen data beschikbaar";
            updateButtons(false);
            setFieldDefaults();
            return;
        }

        const data = await res.json();
        const status = data.status || {};
        const running = !!status.running;

        if (data.waterfall && data.waterfall.length > 0) {
            drawWaterfall(data.waterfall);
        } else if (!running) {
            clearWaterfall();
        }

        renderAnalysis(data.analysis);
        updateButtons(running);

        const rowsVisible = Array.isArray(data.waterfall) ? data.waterfall.length : 0;
        const samples = Array.isArray(data.latest_sweep) ? data.latest_sweep.length : 0;
        const ageText = formatRunningText(running, status.last_update_time);

        statusEl.textContent =
            `Rows zichtbaar: ${rowsVisible} | Samples: ${samples} | Status: ${ageText} | Committed: ${status.rows_committed ?? 0}`;

    } catch (err) {
        statusEl.textContent = "Verbinding mislukt, opnieuw proberen...";
        updateButtons(false);
        setFieldDefaults();
    }
}

startBtn.addEventListener("click", async () => {
    try {
        await fetch("/start", { method: "POST" });
    } catch (err) {
    }
    setTimeout(poll, 300);
});

stopBtn.addEventListener("click", async () => {
    try {
        await fetch("/stop", { method: "POST" });
    } catch (err) {
    }
    setTimeout(poll, 300);
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

setFieldDefaults();
poll();
setInterval(poll, 500);