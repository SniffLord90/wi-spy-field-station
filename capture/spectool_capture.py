import subprocess
import threading
import time
from collections import deque

import numpy as np

from config.settings import MAX_ROWS, FREQ_START, FREQ_END, SPECTOOL_PATH


class SpectoolManager:
    def __init__(self):
        self.max_rows = MAX_ROWS
        self.freq_start = FREQ_START
        self.freq_end = FREQ_END
        self.spectool_path = SPECTOOL_PATH

        self.waterfall = deque(maxlen=self.max_rows)
        self.latest_sweep = None
        self.latest_analysis = None
        self.last_update_time = 0.0
        self.running = False
        self.thread = None
        self.process = None
        self.lock = threading.Lock()
        self.last_error = None

        self.sweeps_received = 0
        self.rows_committed = 0
        self.expected_bins = None

    def _spectool_stream(self):
        while self.running:
            try:
                self.last_error = None

                self.process = subprocess.Popen(
                    ["sudo", self.spectool_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                for line in self.process.stdout:
                    if not self.running:
                        break

                    line = line.strip()

                    if not line.startswith("Wi-Spy DBx USB"):
                        continue

                    try:
                        _, values_str = line.split(":", 1)
                        values = [int(x) for x in values_str.strip().split()]
                        if not values:
                            continue
                        yield np.array(values, dtype=np.int16)
                    except Exception:
                        continue

                if self.process and self.process.poll() is None:
                    self.process.terminate()

                if self.running:
                    self.last_error = "spectool_raw gestopt of geen output"
                    time.sleep(1)

            except Exception as exc:
                self.last_error = str(exc)
                time.sleep(1)

    def _bin_to_freq(self, idx: int, total_bins: int) -> float:
        if total_bins <= 1:
            return float(self.freq_start)
        return self.freq_start + (idx / (total_bins - 1)) * (self.freq_end - self.freq_start)

    def _mhz_to_bin(self, mhz: float, total_bins: int) -> int:
        if total_bins <= 1:
            return 0
        ratio = (mhz - self.freq_start) / (self.freq_end - self.freq_start)
        idx = int(round(ratio * (total_bins - 1)))
        return max(0, min(total_bins - 1, idx))

    def _window_stats(self, sweep: np.ndarray, start_mhz: float, end_mhz: float) -> dict:
        total_bins = len(sweep)
        start_idx = self._mhz_to_bin(start_mhz, total_bins)
        end_idx = self._mhz_to_bin(end_mhz, total_bins)

        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx

        window = sweep[start_idx:end_idx + 1]
        if len(window) == 0:
            return {
                "mean": -110.0,
                "peak": -110.0,
                "peak_idx_local": 0,
                "peak_idx_global": start_idx,
            }

        peak_idx_local = int(np.argmax(window))
        peak_idx_global = start_idx + peak_idx_local

        return {
            "mean": float(np.mean(window)),
            "peak": float(np.max(window)),
            "peak_idx_local": peak_idx_local,
            "peak_idx_global": peak_idx_global,
        }

    def _detect_channels(self, sweep: np.ndarray, noise_floor: float) -> dict:
        channels = {
            "1": 2412,
            "6": 2437,
            "11": 2462,
        }

        results = {}
        for ch, center in channels.items():
            stats = self._window_stats(sweep, center - 10, center + 10)

            mean_dbm = round(stats["mean"], 1)
            peak_dbm = round(stats["peak"], 1)
            snr_avg = round(mean_dbm - noise_floor, 1)
            snr_peak = round(peak_dbm - noise_floor, 1)

            results[ch] = {
                "center_mhz": center,
                "mean_dbm": mean_dbm,
                "peak_dbm": peak_dbm,
                "snr_avg_db": snr_avg,
                "snr_peak_db": snr_peak,
            }

        return results

    def _find_best_channel(self, channels: dict) -> str:
        # Beste kanaal = laagste gemiddelde belasting
        best = min(channels.items(), key=lambda item: item[1]["mean_dbm"])
        return best[0]

    def _detect_interference(self, sweep: np.ndarray) -> dict:
        total_bins = len(sweep)
        if total_bins < 5:
            return {
                "detected": False,
                "severity": "low",
                "type": "unknown",
                "message": "Onvoldoende data",
            }

        noise_floor = float(np.percentile(sweep, 20))
        peak = float(np.max(sweep))
        span = peak - noise_floor

        narrow_count = 0
        for i in range(1, total_bins - 1):
            if sweep[i] > noise_floor + 18 and sweep[i] > sweep[i - 1] + 4 and sweep[i] > sweep[i + 1] + 4:
                narrow_count += 1

        strong_bins = int(np.sum(sweep > noise_floor + 12))
        strong_ratio = strong_bins / total_bins

        if strong_ratio > 0.55:
            return {
                "detected": True,
                "severity": "high",
                "type": "wideband",
                "message": "Brede RF-bezetting / mogelijke ruisbron",
            }

        if narrow_count >= 3:
            return {
                "detected": True,
                "severity": "medium",
                "type": "narrowband",
                "message": "Smalle pieken / mogelijke niet-WiFi bron",
            }

        if span < 10:
            return {
                "detected": False,
                "severity": "low",
                "type": "low_activity",
                "message": "Weinig RF-activiteit",
            }

        return {
            "detected": False,
            "severity": "low",
            "type": "wifi_like",
            "message": "Voornamelijk WiFi-achtig patroon",
        }

    def _active_zone(self, sweep: np.ndarray) -> dict:
        total_bins = len(sweep)
        if total_bins == 0:
            return {"start_mhz": self.freq_start, "end_mhz": self.freq_end}

        noise_floor = float(np.percentile(sweep, 20))
        threshold = noise_floor + 10

        active_indices = np.where(sweep > threshold)[0]
        if len(active_indices) == 0:
            return {"start_mhz": self.freq_start, "end_mhz": self.freq_end}

        start_idx = int(active_indices[0])
        end_idx = int(active_indices[-1])

        return {
            "start_mhz": round(self._bin_to_freq(start_idx, total_bins), 1),
            "end_mhz": round(self._bin_to_freq(end_idx, total_bins), 1),
        }

    def _rf_health_score(self, sweep: np.ndarray, interference: dict) -> int:
        noise_floor = float(np.percentile(sweep, 20))
        peak = float(np.max(sweep))
        span = peak - noise_floor

        score = 100

        if noise_floor > -92:
            score -= 20
        elif noise_floor > -96:
            score -= 10

        if span > 45:
            score -= 10

        if interference["detected"]:
            if interference["type"] == "wideband":
                score -= 25
            elif interference["type"] == "narrowband":
                score -= 15

        return max(0, min(100, int(score)))

    def _snr_quality(self, snr: float | None) -> str:
        if snr is None:
            return "unknown"
        if snr >= 35:
            return "excellent"
        if snr >= 25:
            return "good"
        if snr >= 15:
            return "fair"
        return "poor"

    def _build_verdict(self, analysis: dict) -> dict:
        noise_floor = analysis["noise_floor_dbm"]
        health_score = analysis["health_score"]
        interference = analysis["interference"]
        channels = analysis["channels"]
        best_channel = analysis["best_channel"]

        best_avg_snr = channels.get(best_channel, {}).get("snr_avg_db")
        best_peak_snr = channels.get(best_channel, {}).get("snr_peak_db")
        best_snr_quality = self._snr_quality(best_avg_snr)

        severity = "good"
        title = "WiFi omgeving OK"
        summary = "Spectrum oogt bruikbaar. Geen duidelijke zware interferentie."
        details = []

        if interference["detected"] and interference["severity"] == "high":
            severity = "bad"
            title = "Interferentie vermoed"
            summary = "Brede RF-bezetting zichtbaar. Niet-WiFi storing is plausibel."
            details.append(interference["message"])

        elif noise_floor > -92:
            severity = "bad"
            title = "Spectrum te vuil"
            summary = "Hoge basisruis. WiFi-kwaliteit kan hierdoor sterk lijden."
            details.append(f"Noise floor is hoog: {noise_floor} dBm")

        elif best_avg_snr is not None and best_avg_snr < 15:
            severity = "bad"
            title = "WiFi omgeving verdacht voor buffering"
            summary = "Laag gemiddeld signaal boven de ruis. Streamingproblemen zijn plausibel."
            details.append(f"Beste kanaal avg SNR: {best_avg_snr} dB")
            if best_peak_snr is not None:
                details.append(f"Peak SNR op beste kanaal: {best_peak_snr} dB")

        elif best_avg_snr is not None and (best_avg_snr < 25 or health_score < 60):
            severity = "warn"
            title = "Kanaal druk of matige RF-kwaliteit"
            summary = "Omgeving is bruikbaar, maar niet ideaal. Wifi kan onstabiel aanvoelen."
            details.append(f"Beste kanaal avg SNR: {best_avg_snr} dB ({best_snr_quality})")
            if best_peak_snr is not None:
                details.append(f"Peak SNR op beste kanaal: {best_peak_snr} dB")

        elif interference["detected"] and interference["severity"] == "medium":
            severity = "warn"
            title = "Mogelijke interferentie"
            summary = "Er zijn smalle pieken zichtbaar die niet typisch WiFi lijken."
            details.append(interference["message"])

        else:
            details.append(f"Beste kanaal: {best_channel}")
            if best_avg_snr is not None:
                details.append(f"Beste kanaal avg SNR: {best_avg_snr} dB ({best_snr_quality})")
            if best_peak_snr is not None:
                details.append(f"Beste kanaal peak SNR: {best_peak_snr} dB")

        action = f"Aanbevolen kanaal: {best_channel}"

        return {
            "severity": severity,
            "title": title,
            "summary": summary,
            "details": details,
            "action": action,
        }

    def _analyze_sweep(self, sweep: np.ndarray) -> dict:
        noise_floor = round(float(np.percentile(sweep, 20)), 1)
        peak_dbm = round(float(np.max(sweep)), 1)
        peak_idx = int(np.argmax(sweep))
        peak_freq = round(self._bin_to_freq(peak_idx, len(sweep)), 1)
        global_peak_snr = round(peak_dbm - noise_floor, 1)

        channels = self._detect_channels(sweep, noise_floor)
        best_channel = self._find_best_channel(channels)
        interference = self._detect_interference(sweep)
        active_zone = self._active_zone(sweep)
        health_score = self._rf_health_score(sweep, interference)

        analysis = {
            "noise_floor_dbm": noise_floor,
            "peak_dbm": peak_dbm,
            "peak_freq_mhz": peak_freq,
            "global_peak_snr_db": global_peak_snr,
            "channels": channels,
            "best_channel": best_channel,
            "interference": interference,
            "active_zone": active_zone,
            "health_score": health_score,
        }

        analysis["verdict"] = self._build_verdict(analysis)
        return analysis

    def _capture_loop(self):
        for raw_sweep in self._spectool_stream():
            if not self.running:
                break

            now = time.time()
            self.sweeps_received += 1

            if self.expected_bins is None:
                self.expected_bins = len(raw_sweep)

            if len(raw_sweep) != self.expected_bins:
                with self.lock:
                    self.last_error = (
                        f"ongeldige sweep-lengte: {len(raw_sweep)} "
                        f"(verwacht {self.expected_bins})"
                    )
                continue

            raw_list = raw_sweep.tolist()
            analysis = self._analyze_sweep(raw_sweep.astype(np.float32))

            with self.lock:
                self.latest_sweep = raw_list
                self.latest_analysis = analysis
                self.waterfall.append(raw_list)
                self.last_update_time = now
                self.rows_committed += 1

    def start(self):
        with self.lock:
            if self.running:
                return

            self.running = True
            self.last_error = None
            self.waterfall.clear()
            self.latest_sweep = None
            self.latest_analysis = None
            self.last_update_time = 0.0
            self.sweeps_received = 0
            self.rows_committed = 0
            self.expected_bins = None

        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self.running = False

        if self.process and self.process.poll() is None:
            self.process.terminate()

    def get_data(self):
        with self.lock:
            wf = list(self.waterfall)
            samples = len(wf[0]) if wf else 0
            age = time.time() - self.last_update_time if self.last_update_time else None

            return {
                "freq_start": self.freq_start,
                "freq_end": self.freq_end,
                "rows": len(wf),
                "samples": samples,
                "last_update_time": self.last_update_time,
                "running": self.running,
                "last_error": self.last_error,
                "age_seconds": age,
                "sweeps_received": self.sweeps_received,
                "rows_committed": self.rows_committed,
                "waterfall": wf,
                "analysis": self.latest_analysis,
            }

    def get_status(self):
        with self.lock:
            age = time.time() - self.last_update_time if self.last_update_time else None
            return {
                "running": self.running,
                "rows": len(self.waterfall),
                "samples": len(self.latest_sweep) if self.latest_sweep else 0,
                "last_update_time": self.last_update_time,
                "age_seconds": age,
                "last_error": self.last_error,
                "sweeps_received": self.sweeps_received,
                "rows_committed": self.rows_committed,
                "expected_bins": self.expected_bins,
                "analysis": self.latest_analysis,
            }