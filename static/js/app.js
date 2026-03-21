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
    startBtn.disabled = running;
    stopBtn.disabled = !running;
}

function scoreClass(score) {
    if (score >= 80) return "good";
    if (score >= 55) return "warn";
    return "bad";
}

function snrClass(snr) {
    if (snr >= 35) return "good";
    if (snr >= 25) return "warn";
    return "bad";
}

function setFieldDefaults() {
    healthScoreEl.textContent = "--";
    healthScoreEl.className = "card-value neutral";

    noiseFloorEl.textContent = "--";
    peakInfoEl.textContent = "--";
    peakSnrEl.textContent = "--";
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

    ch1El.className = "channel-value neutral";
    ch6El.className = "channel-value neutral";
    ch11El.className = "channel-value neutral";

    snr1AvgEl.className = "channel-sub neutral";
    snr6AvgEl.className = "channel-sub neutral";
    snr11AvgEl.className = "channel-sub neutral";

    snr1PeakEl.className = "channel-sub neutral";
    snr6PeakEl.className = "channel-sub neutral";
    snr11PeakEl.className = "channel-sub neutral";

    verdictPanelEl.className = "verdict-panel neutral";
    verdictBadgeEl.textContent = "--";
    verdictTitleEl.textContent = "Nog geen meting";
    verdictSummaryEl.textContent = "Start een meting om analyse te zien.";
    verdictActionEl.textContent = "--";
    verdictDetailsEl.innerHTML = "";
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

    verdictPanelEl.className = `verdict-panel ${verdict.severity}`;
    verdictBadgeEl.textContent = verdict.severity.toUpperCase();
    verdictTitleEl.textContent = verdict.title;
    verdictSummaryEl.textContent = verdict.summary;
    verdictActionEl.textContent = verdict.action || "--";

    verdictDetailsEl.innerHTML = "";
    (verdict.details || []).forEach((item) => {
        const row = document.createElement("div");
        row.textContent = `• ${item}`;
        verdictDetailsEl.appendChild(row);
    });
}

function renderAnalysis(analysis) {
    if (!analysis) {
        setFieldDefaults();
        return;
    }

    const score = analysis.health_score;
    healthScoreEl.textContent = `${score}/100`;
    healthScoreEl.className = `card-value ${scoreClass(score)}`;

    noiseFloorEl.textContent = `${analysis.noise_floor_dbm} dBm`;
    peakInfoEl.textContent = `${analysis.peak_dbm} dBm @ ${analysis.peak_freq_mhz} MHz`;
    peakSnrEl.textContent = `${analysis.global_peak_snr_db} dB`;
    peakSnrEl.className = `card-value ${snrClass(analysis.global_peak_snr_db)}`;
    activeZoneEl.textContent = `${analysis.active_zone.start_mhz} - ${analysis.active_zone.end_mhz} MHz`;
    interferenceInfoEl.textContent = analysis.interference.message;
    bestChannelEl.textContent = `Kanaal ${analysis.best_channel}`;

    const channels = analysis.channels || {};

    function paintChannel(el, avgEl, peakEl, chData, bestChannel, chNumber) {
        if (!chData) {
            el.textContent = "--";
            avgEl.textContent = "Avg SNR --";
            peakEl.textContent = "Peak SNR --";
            el.className = "channel-value neutral";
            avgEl.className = "channel-sub neutral";
            peakEl.className = "channel-sub neutral";
            return;
        }

        el.textContent = `${chData.mean_dbm} dBm`;
        avgEl.textContent = `Avg SNR ${chData.snr_avg_db} dB`;
        peakEl.textContent = `Peak SNR ${chData.snr_peak_db} dB`;

        if (bestChannel === chNumber) {
            el.className = "channel-value good";
        } else if (chData.mean_dbm > -85) {
            el.className = "channel-value bad";
        } else {
            el.className = "channel-value warn";
        }

        avgEl.className = `channel-sub ${snrClass(chData.snr_avg_db)}`;
        peakEl.className = `channel-sub ${snrClass(chData.snr_peak_db)}`;
    }

    paintChannel(ch1El, snr1AvgEl, snr1PeakEl, channels["1"], analysis.best_channel, "1");
    paintChannel(ch6El, snr6AvgEl, snr6PeakEl, channels["6"], analysis.best_channel, "6");
    paintChannel(ch11El, snr11AvgEl, snr11PeakEl, channels["11"], analysis.best_channel, "11");

    renderVerdict(analysis.verdict);
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

        if (data.waterfall && data.waterfall.length > 0) {
            drawWaterfall(data.waterfall);
        } else if (!data.running) {
            clearWaterfall();
        }

        renderAnalysis(data.analysis);
        updateButtons(data.running);

        const age = data.last_update_time
            ? (Date.now() / 1000) - data.last_update_time
            : null;

        let ageText = "gestopt";
        if (data.running) {
            ageText = age !== null && age < 2
                ? "live"
                : `laatste update ${age.toFixed(1)}s geleden`;
        }

        let extra = "";
        if (data.last_error) {
            extra += ` | Fout: ${data.last_error}`;
        }

        if (typeof data.sweeps_received !== "undefined" && typeof data.rows_committed !== "undefined") {
            extra += ` | Sweeps: ${data.sweeps_received} | Rows: ${data.rows_committed}`;
        }

        statusEl.textContent =
            `Rows zichtbaar: ${data.rows} | Samples: ${data.samples} | Status: ${ageText}${extra}`;
    } catch (err) {
        statusEl.textContent = "Verbinding mislukt, opnieuw proberen...";
        updateButtons(false);
        setFieldDefaults();
    }
}

startBtn.addEventListener("click", async () => {
    await fetch("/start", { method: "POST" });
    setTimeout(poll, 200);
});

stopBtn.addEventListener("click", async () => {
    await fetch("/stop", { method: "POST" });
    setTimeout(poll, 200);
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
setInterval(poll, 250);