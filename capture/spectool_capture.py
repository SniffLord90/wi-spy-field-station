from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from config.settings import (
    FREQ_START,
    FREQ_END,
    LONG_WINDOW_SECONDS,
    MAX_ROWS,
    PERSISTENCE_MEDIUM_RATIO,
    POLL_INTERVAL_MS,
    SHORT_WINDOW_SECONDS,
    SIGNAL_ACTIVITY_THRESHOLD,
    SPECTOOL_PATH,
    STRONG_SIGNAL_THRESHOLD,
    VERY_STRONG_SIGNAL_THRESHOLD,
    WEIGHT_BUSY,
    WEIGHT_INTERFERENCE,
    WEIGHT_NOISE,
    WEIGHT_OVERLAP,
    WEIGHT_PEAK,
    NARROW_MAX_WIDTH_MHZ,
    WIDEBAND_MIN_WIDTH_MHZ,
)


@dataclass
class SweepEntry:
    ts: float
    values: list[int]
    analysis: dict[str, Any]


class SpectoolManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = False
        self.capture_thread: threading.Thread | None = None
        self.spectool_proc: subprocess.Popen[str] | None = None

        self.latest_sweep: list[int] = []
        self.latest_analysis: dict[str, Any] = {}
        self.last_update_time: float | None = None

        self.waterfall: deque[list[int]] = deque(maxlen=MAX_ROWS)
        self.history: deque[SweepEntry] = deque(maxlen=4000)

        self.rows_committed = 0
        self.expected_bins: int | None = None

        self.freq_start = float(FREQ_START)
        self.freq_end = float(FREQ_END)
        self._bin_freqs_cache: np.ndarray | None = None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def start_capture(self) -> dict[str, Any]:
        with self.lock:
            if self.running:
                return {"ok": True, "message": "Capture already running"}

            self.running = True
            self.capture_thread = threading.Thread(
                target=self._capture_loop,
                daemon=True
            )
            self.capture_thread.start()

        return {"ok": True, "message": "Capture started"}

    def stop_capture(self) -> dict[str, Any]:
        with self.lock:
            self.running = False

        self._stop_spectool_process()

        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)

        return {"ok": True, "message": "Capture stopped"}

    def start(self) -> dict[str, Any]:
        return self.start_capture()

    def stop(self) -> dict[str, Any]:
        return self.stop_capture()

    def status(self) -> dict[str, Any]:
        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "last_update_time": self.last_update_time,
                "rows_committed": self.rows_committed,
                "expected_bins": self.expected_bins,
                "waterfall_rows": len(self.waterfall),
                "history_rows": len(self.history),
            }

    def get_latest_data(self) -> dict[str, Any]:
        with self.lock:
            status = {
                "running": self.running,
                "last_update_time": self.last_update_time,
                "rows_committed": self.rows_committed,
                "expected_bins": self.expected_bins,
                "waterfall_rows": len(self.waterfall),
                "history_rows": len(self.history),
            }

            return {
                "waterfall": list(self.waterfall),
                "latest_sweep": list(self.latest_sweep),
                "analysis": dict(self.latest_analysis) if self.latest_analysis else {},
                "status": status,
            }

    def get_data(self) -> dict[str, Any]:
        return self.get_latest_data()

    # -------------------------------------------------------------------------
    # Spectool process handling
    # -------------------------------------------------------------------------

    def _start_spectool_process(self) -> bool:
        self._stop_spectool_process()

        try:
            self.spectool_proc = subprocess.Popen(
                [SPECTOOL_PATH],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            return True
        except Exception:
            self.spectool_proc = None
            return False

    def _stop_spectool_process(self) -> None:
        proc = self.spectool_proc
        self.spectool_proc = None

        if not proc:
            return

        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1.5)
        except Exception:
            pass

    def _parse_sweep_line(self, line: str) -> list[int]:
        line = line.strip()
        if not line:
            return []

        if ":" not in line:
            return []

        prefix, payload = line.split(":", 1)

        if "Wi-Spy" not in prefix:
            return []

        parts = payload.strip().split()
        if not parts:
            return []

        values: list[int] = []
        for item in parts:
            try:
                values.append(int(float(item)))
            except ValueError:
                return []

        return values

    # -------------------------------------------------------------------------
    # Capture loop
    # -------------------------------------------------------------------------

    def _capture_loop(self) -> None:
        while True:
            with self.lock:
                if not self.running:
                    break

            if not self.spectool_proc or self.spectool_proc.poll() is not None:
                started = self._start_spectool_process()
                if not started:
                    time.sleep(1.0)
                    continue

            proc = self.spectool_proc
            if not proc or not proc.stdout:
                time.sleep(0.25)
                continue

            try:
                line = proc.stdout.readline()
            except Exception:
                self._stop_spectool_process()
                time.sleep(0.5)
                continue

            if not line:
                if proc.poll() is not None:
                    self._stop_spectool_process()
                    time.sleep(0.5)
                else:
                    time.sleep(POLL_INTERVAL_MS / 1000.0)
                continue

            raw_list = self._parse_sweep_line(line)
            if not raw_list:
                continue

            now = time.time()

            if self.expected_bins is None:
                self.expected_bins = len(raw_list)
                self._bin_freqs_cache = None

            if len(raw_list) != self.expected_bins:
                continue

            analysis = self._analyze_sweep(raw_list, now)

            with self.lock:
                self.latest_sweep = raw_list
                self.latest_analysis = analysis
                self.waterfall.append(raw_list)
                self.history.append(
                    SweepEntry(ts=now, values=raw_list, analysis=analysis)
                )
                self.last_update_time = now
                self.rows_committed += 1

    # -------------------------------------------------------------------------
    # Main analysis
    # -------------------------------------------------------------------------

    def _analyze_sweep(self, sweep: list[int], ts: float) -> dict[str, Any]:
        arr = np.array(sweep, dtype=float)
        freqs = self._get_bin_freqs(len(sweep))

        short_entries = self._window_entries(ts - SHORT_WINDOW_SECONDS, ts)
        long_entries = self._window_entries(ts - LONG_WINDOW_SECONDS, ts)

        short_matrix = self._matrix_from_entries(short_entries, len(sweep))
        long_matrix = self._matrix_from_entries(long_entries, len(sweep))

        instantaneous = self._instant_metrics(arr)
        short_metrics = self._window_metrics(short_matrix)
        long_metrics = self._window_metrics(long_matrix)

        active_mask = arr >= SIGNAL_ACTIVITY_THRESHOLD
        strong_mask = arr >= STRONG_SIGNAL_THRESHOLD
        very_strong_mask = arr >= VERY_STRONG_SIGNAL_THRESHOLD

        persistent_mask_short = self._persistent_mask(short_matrix, SIGNAL_ACTIVITY_THRESHOLD)
        persistent_mask_long = self._persistent_mask(long_matrix, SIGNAL_ACTIVITY_THRESHOLD)

        segments_now = self._find_segments(active_mask, freqs)
        segments_persistent = self._find_segments(persistent_mask_short, freqs)

        interference = self._detect_interference(
            arr=arr,
            freqs=freqs,
            active_mask=active_mask,
            strong_mask=strong_mask,
            persistent_mask=persistent_mask_short,
            segments_now=segments_now,
            segments_persistent=segments_persistent,
            short_metrics=short_metrics,
            long_metrics=long_metrics,
        )

        channel_scores = self._score_channels(
            arr=arr,
            freqs=freqs,
            short_matrix=short_matrix,
            persistent_mask=persistent_mask_short,
            interference=interference,
        )

        verdict = self._build_verdict(
            instantaneous=instantaneous,
            short_metrics=short_metrics,
            long_metrics=long_metrics,
            interference=interference,
            channel_scores=channel_scores,
            active_ratio=float(np.mean(active_mask)) if len(active_mask) else 0.0,
            strong_ratio=float(np.mean(strong_mask)) if len(strong_mask) else 0.0,
            very_strong_ratio=float(np.mean(very_strong_mask)) if len(very_strong_mask) else 0.0,
            persistent_ratio_short=float(np.mean(persistent_mask_short)) if len(persistent_mask_short) else 0.0,
            persistent_ratio_long=float(np.mean(persistent_mask_long)) if len(persistent_mask_long) else 0.0,
        )

        legacy = self._build_legacy_fields(
            arr=arr,
            freqs=freqs,
            segments_now=segments_now,
            instantaneous=instantaneous,
            interference=interference,
            channel_scores=channel_scores,
            verdict=verdict,
        )

        return {
            "timestamp": ts,
            "freq_start_mhz": self.freq_start,
            "freq_end_mhz": self.freq_end,
            "bins": len(sweep),
            "instantaneous": instantaneous,
            "short_window": short_metrics,
            "long_window": long_metrics,
            "segments_now": segments_now,
            "segments_persistent": segments_persistent,
            "interference": interference,
            "channel_scores": channel_scores,
            "verdict": verdict,
            "legacy": legacy,
            **legacy,
        }

    # -------------------------------------------------------------------------
    # Legacy compatibility for existing frontend
    # -------------------------------------------------------------------------

    def _build_legacy_fields(
        self,
        arr: np.ndarray,
        freqs: np.ndarray,
        segments_now: list[dict[str, Any]],
        instantaneous: dict[str, Any],
        interference: dict[str, Any],
        channel_scores: dict[str, Any],
        verdict: dict[str, Any],
    ) -> dict[str, Any]:
        channels = channel_scores.get("channels", {})
        best_non_overlap = channel_scores.get("best_non_overlapping", [])
        recommended_top3 = channel_scores.get("recommended_top3", [])

        best_channel = best_non_overlap[0] if best_non_overlap else (recommended_top3[0] if recommended_top3 else None)

        peak_dbm = instantaneous.get("peak_dbm")
        noise_floor = instantaneous.get("noise_floor_estimate_dbm")

        peak_idx = int(np.argmax(arr)) if len(arr) else None
        peak_freq = round(float(freqs[peak_idx]), 2) if peak_idx is not None else None

        if peak_dbm is not None and noise_floor is not None:
            peak_snr = round(float(peak_dbm - noise_floor), 1)
        else:
            peak_snr = None

        active_zone = "--"
        if segments_now:
            widest = max(segments_now, key=lambda seg: seg["width_mhz"])
            active_zone = f'{widest["start_freq_mhz"]} - {widest["end_freq_mhz"]} MHz'

        rf_health = verdict.get("field_status", "unknown")
        rf_health_map = {
            "good": "Goed",
            "ok": "OK",
            "degraded": "Matig",
            "bad": "Slecht",
            "critical": "Kritiek",
        }

        interference_map = {
            "clean": "Geen duidelijke storing",
            "wifi_activity": "Normale wifi-activiteit",
            "wifi_congestion": "Wifi congestie",
            "narrowband_interferer": "Smalbandige storing",
            "wideband_interferer": "Brede storing",
            "possible_wideband_interference": "Mogelijke brede storing",
            "unknown_anomaly": "Onbekende anomalie",
        }

        def channel_block(ch: int) -> dict[str, Any]:
            data = channels.get(str(ch), {})
            ch_noise = data.get("noise_estimate_dbm")
            ch_peak = data.get("peak_dbm")

            center = {
                1: 2412,
                6: 2437,
                11: 2462,
            }[ch]

            idx = np.where((freqs >= center - 10) & (freqs <= center + 10))[0]
            mean_dbm = round(float(np.mean(arr[idx])), 1) if len(idx) else None

            if ch_noise is not None and ch_peak is not None:
                ch_peak_snr = round(float(ch_peak - ch_noise), 1)
            else:
                ch_peak_snr = None

            if mean_dbm is not None and ch_noise is not None:
                ch_avg_snr = round(float(mean_dbm - ch_noise), 1)
            else:
                ch_avg_snr = None

            score = data.get("score")
            if score is None:
                label = "--"
            elif score >= 70:
                label = "Goed"
            elif score >= 45:
                label = "Matig"
            else:
                label = "Slecht"

            return {
                "label": label,
                "mean_dbm": mean_dbm,
                "avg_snr": ch_avg_snr,
                "peak_snr": ch_peak_snr,
                "score": score,
            }

        return {
            "rf_health": rf_health_map.get(rf_health, "Onbekend"),
            "noise_floor": noise_floor,
            "peak": peak_dbm,
            "peak_freq_mhz": peak_freq,
            "peak_snr": peak_snr,
            "active_zone": active_zone,
            "interference_label": interference_map.get(
                interference.get("classification", "clean"),
                "Onbekend"
            ),
            "best_channel": best_channel,
            "summary": verdict.get("summary", "Nog geen meting"),
            "action": verdict.get("action", "Start een meting om analyse te zien."),
            "ch1": channel_block(1),
            "ch6": channel_block(6),
            "ch11": channel_block(11),
        }

    # -------------------------------------------------------------------------
    # Window helpers
    # -------------------------------------------------------------------------

    def _window_entries(self, start_ts: float, end_ts: float) -> list[SweepEntry]:
        with self.lock:
            return [e for e in self.history if start_ts <= e.ts <= end_ts]

    def _matrix_from_entries(self, entries: list[SweepEntry], expected_len: int) -> np.ndarray:
        if not entries:
            return np.empty((0, expected_len), dtype=float)

        rows = []
        for entry in entries:
            if len(entry.values) == expected_len:
                rows.append(entry.values)

        if not rows:
            return np.empty((0, expected_len), dtype=float)

        return np.array(rows, dtype=float)

    def _window_metrics(self, matrix: np.ndarray) -> dict[str, Any]:
        if matrix.size == 0:
            return {
                "sweeps": 0,
                "mean_dbm": None,
                "median_dbm": None,
                "max_dbm": None,
                "min_dbm": None,
                "std_db": None,
                "activity_ratio": 0.0,
                "strong_ratio": 0.0,
                "very_strong_ratio": 0.0,
            }

        return {
            "sweeps": int(matrix.shape[0]),
            "mean_dbm": round(float(np.mean(matrix)), 2),
            "median_dbm": round(float(np.median(matrix)), 2),
            "max_dbm": round(float(np.max(matrix)), 2),
            "min_dbm": round(float(np.min(matrix)), 2),
            "std_db": round(float(np.std(matrix)), 2),
            "activity_ratio": round(float(np.mean(matrix >= SIGNAL_ACTIVITY_THRESHOLD)), 4),
            "strong_ratio": round(float(np.mean(matrix >= STRONG_SIGNAL_THRESHOLD)), 4),
            "very_strong_ratio": round(float(np.mean(matrix >= VERY_STRONG_SIGNAL_THRESHOLD)), 4),
        }

    def _instant_metrics(self, arr: np.ndarray) -> dict[str, Any]:
        return {
            "mean_dbm": round(float(np.mean(arr)), 2),
            "median_dbm": round(float(np.median(arr)), 2),
            "peak_dbm": round(float(np.max(arr)), 2),
            "min_dbm": round(float(np.min(arr)), 2),
            "std_db": round(float(np.std(arr)), 2),
            "active_bin_ratio": round(float(np.mean(arr >= SIGNAL_ACTIVITY_THRESHOLD)), 4),
            "strong_bin_ratio": round(float(np.mean(arr >= STRONG_SIGNAL_THRESHOLD)), 4),
            "very_strong_bin_ratio": round(float(np.mean(arr >= VERY_STRONG_SIGNAL_THRESHOLD)), 4),
            "noise_floor_estimate_dbm": round(float(np.percentile(arr, 15)), 2),
        }

    # -------------------------------------------------------------------------
    # Frequency helpers
    # -------------------------------------------------------------------------

    def _get_bin_freqs(self, bins: int) -> np.ndarray:
        if self._bin_freqs_cache is not None and len(self._bin_freqs_cache) == bins:
            return self._bin_freqs_cache

        freqs = np.linspace(self.freq_start, self.freq_end, bins)
        self._bin_freqs_cache = freqs
        return freqs

    # -------------------------------------------------------------------------
    # Persistence / segments
    # -------------------------------------------------------------------------

    def _persistent_mask(self, matrix: np.ndarray, threshold_dbm: float) -> np.ndarray:
        if matrix.size == 0:
            return np.array([], dtype=bool)

        ratio = np.mean(matrix >= threshold_dbm, axis=0)
        return ratio >= PERSISTENCE_MEDIUM_RATIO

    def _find_segments(self, mask: np.ndarray, freqs: np.ndarray) -> list[dict[str, Any]]:
        if len(mask) == 0:
            return []

        segments: list[dict[str, Any]] = []
        start = None

        for i, value in enumerate(mask):
            if value and start is None:
                start = i
            elif not value and start is not None:
                end = i - 1
                segments.append(self._segment_to_dict(start, end, freqs))
                start = None

        if start is not None:
            segments.append(self._segment_to_dict(start, len(mask) - 1, freqs))

        return segments

    def _segment_to_dict(self, start_idx: int, end_idx: int, freqs: np.ndarray) -> dict[str, Any]:
        start_freq = float(freqs[start_idx])
        end_freq = float(freqs[end_idx])
        center_freq = (start_freq + end_freq) / 2.0
        width_mhz = max(0.0, end_freq - start_freq)

        return {
            "start_idx": start_idx,
            "end_idx": end_idx,
            "start_freq_mhz": round(start_freq, 2),
            "end_freq_mhz": round(end_freq, 2),
            "center_freq_mhz": round(center_freq, 2),
            "width_mhz": round(width_mhz, 2),
        }

    # -------------------------------------------------------------------------
    # Interference detection
    # -------------------------------------------------------------------------

    def _detect_interference(
        self,
        arr: np.ndarray,
        freqs: np.ndarray,
        active_mask: np.ndarray,
        strong_mask: np.ndarray,
        persistent_mask: np.ndarray,
        segments_now: list[dict[str, Any]],
        segments_persistent: list[dict[str, Any]],
        short_metrics: dict[str, Any],
        long_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        active_ratio = float(np.mean(active_mask)) if len(active_mask) else 0.0
        strong_ratio = float(np.mean(strong_mask)) if len(strong_mask) else 0.0
        persistent_ratio = float(np.mean(persistent_mask)) if len(persistent_mask) else 0.0

        widest_now = max((seg["width_mhz"] for seg in segments_now), default=0.0)
        widest_persistent = max((seg["width_mhz"] for seg in segments_persistent), default=0.0)

        narrow_persistent_segments = [
            seg for seg in segments_persistent
            if 0 < seg["width_mhz"] <= NARROW_MAX_WIDTH_MHZ
        ]

        wide_segments_now = [
            seg for seg in segments_now
            if seg["width_mhz"] >= WIDEBAND_MIN_WIDTH_MHZ
        ]

        wide_segments_persistent = [
            seg for seg in segments_persistent
            if seg["width_mhz"] >= WIDEBAND_MIN_WIDTH_MHZ
        ]

        wifi_like = self._estimate_wifi_likeness(
            arr=arr,
            freqs=freqs,
            segments_now=segments_now,
            active_ratio=active_ratio,
            strong_ratio=strong_ratio,
        )

        classification = "clean"
        reasons: list[str] = []
        confidence = 0.15

        if wide_segments_persistent and persistent_ratio >= PERSISTENCE_MEDIUM_RATIO:
            classification = "wideband_interferer"
            reasons.append("Brede persistente energie over groot deel van de band")
            confidence = min(0.98, 0.70 + persistent_ratio * 0.25)

        elif narrow_persistent_segments and wifi_like["score"] < 0.45:
            classification = "narrowband_interferer"
            reasons.append("Smalbandige persistente energie past niet goed bij normaal wifi-patroon")
            confidence = min(0.95, 0.62 + persistent_ratio * 0.20)

        elif wifi_like["score"] >= 0.62 and active_ratio >= 0.18:
            if short_metrics["activity_ratio"] >= 0.35 or strong_ratio >= 0.12:
                classification = "wifi_congestion"
                reasons.append("Energie volgt voornamelijk wifi-kanaalstructuur")
                reasons.append("Hoge activiteit of sterke belasting aanwezig")
                confidence = min(0.95, 0.60 + wifi_like["score"] * 0.25)
            else:
                classification = "wifi_activity"
                reasons.append("Spectrum oogt wifi-achtig zonder zware congestie")
                confidence = min(0.92, 0.50 + wifi_like["score"] * 0.25)

        elif wide_segments_now and wifi_like["score"] < 0.50:
            classification = "possible_wideband_interference"
            reasons.append("Brede energie aanwezig, maar nog onvoldoende persistent")
            confidence = 0.55

        elif active_ratio >= 0.15 and wifi_like["score"] < 0.45:
            classification = "unknown_anomaly"
            reasons.append("Er is activiteit, maar patroon lijkt niet typisch wifi")
            confidence = 0.48

        else:
            classification = "clean"
            reasons.append("Geen sterke indicatie van storing of zware congestie")
            confidence = 0.35

        return {
            "classification": classification,
            "confidence": round(float(confidence), 2),
            "reasons": reasons,
            "active_ratio": round(active_ratio, 4),
            "strong_ratio": round(strong_ratio, 4),
            "persistent_ratio": round(persistent_ratio, 4),
            "widest_segment_now_mhz": round(widest_now, 2),
            "widest_segment_persistent_mhz": round(widest_persistent, 2),
            "wifi_likeness": wifi_like,
        }

    def _estimate_wifi_likeness(
        self,
        arr: np.ndarray,
        freqs: np.ndarray,
        segments_now: list[dict[str, Any]],
        active_ratio: float,
        strong_ratio: float,
    ) -> dict[str, Any]:
        channel_centers = {
            1: 2412,
            2: 2417,
            3: 2422,
            4: 2427,
            5: 2432,
            6: 2437,
            7: 2442,
            8: 2447,
            9: 2452,
            10: 2457,
            11: 2462,
            12: 2467,
            13: 2472,
        }

        channel_energy_hits = 0
        total_strong_bins = int(np.sum(arr >= STRONG_SIGNAL_THRESHOLD))

        if total_strong_bins > 0:
            for _, center in channel_centers.items():
                left = center - 10
                right = center + 10
                idx = np.where((freqs >= left) & (freqs <= right))[0]
                if len(idx) == 0:
                    continue
                if np.any(arr[idx] >= STRONG_SIGNAL_THRESHOLD):
                    channel_energy_hits += 1

        typical_width_hits = 0
        for seg in segments_now:
            width = seg["width_mhz"]
            if 8.0 <= width <= 26.0:
                typical_width_hits += 1

        width_score = min(1.0, typical_width_hits / 2.0) if segments_now else 0.0
        channel_alignment_score = min(1.0, channel_energy_hits / 3.0)
        activity_score = min(1.0, (active_ratio * 2.2) + (strong_ratio * 2.0))

        score = (
            0.45 * channel_alignment_score
            + 0.35 * width_score
            + 0.20 * activity_score
        )

        reasons = []
        if channel_alignment_score >= 0.66:
            reasons.append("Sterke energie valt op typische wifi-kanaalzones")
        if width_score >= 0.5:
            reasons.append("Segmentbreedte lijkt op wifi-achtige kanaalbezetting")
        if activity_score >= 0.4:
            reasons.append("Er is voldoende activiteit om wifi-gedrag te ondersteunen")

        return {
            "score": round(float(score), 2),
            "channel_alignment_score": round(float(channel_alignment_score), 2),
            "width_score": round(float(width_score), 2),
            "activity_score": round(float(activity_score), 2),
            "reasons": reasons,
        }

    # -------------------------------------------------------------------------
    # Channel scoring
    # -------------------------------------------------------------------------

    def _score_channels(
        self,
        arr: np.ndarray,
        freqs: np.ndarray,
        short_matrix: np.ndarray,
        persistent_mask: np.ndarray,
        interference: dict[str, Any],
    ) -> dict[str, Any]:
        channels = {
            1: 2412,
            2: 2417,
            3: 2422,
            4: 2427,
            5: 2432,
            6: 2437,
            7: 2442,
            8: 2447,
            9: 2452,
            10: 2457,
            11: 2462,
            12: 2467,
            13: 2472,
        }

        scored: dict[str, Any] = {}
        classif = interference.get("classification", "clean")
        interference_penalty = {
            "clean": 0.0,
            "wifi_activity": 0.2,
            "wifi_congestion": 0.45,
            "possible_wideband_interference": 0.55,
            "wideband_interferer": 0.85,
            "narrowband_interferer": 0.70,
            "unknown_anomaly": 0.50,
        }.get(classif, 0.40)

        for channel, center in channels.items():
            primary_idx = np.where((freqs >= center - 10) & (freqs <= center + 10))[0]
            overlap_idx = np.where((freqs >= center - 15) & (freqs <= center + 15))[0]

            if len(primary_idx) == 0 or len(overlap_idx) == 0:
                continue

            primary_vals = arr[primary_idx]
            overlap_vals = arr[overlap_idx]

            if short_matrix.size > 0:
                short_primary = short_matrix[:, primary_idx]
                busy_ratio = float(np.mean(short_primary >= SIGNAL_ACTIVITY_THRESHOLD))
                peak_ratio = float(np.mean(short_primary >= STRONG_SIGNAL_THRESHOLD))
            else:
                busy_ratio = float(np.mean(primary_vals >= SIGNAL_ACTIVITY_THRESHOLD))
                peak_ratio = float(np.mean(primary_vals >= STRONG_SIGNAL_THRESHOLD))

            noise_est = float(np.percentile(primary_vals, 20))
            peak_dbm = float(np.max(primary_vals))
            overlap_active = float(np.mean(overlap_vals >= SIGNAL_ACTIVITY_THRESHOLD))

            if len(persistent_mask) == len(freqs):
                persistent_ratio = float(np.mean(persistent_mask[primary_idx]))
            else:
                persistent_ratio = 0.0

            noise_penalty = self._normalize_noise_penalty(noise_est)
            peak_penalty = self._normalize_peak_penalty(peak_dbm)
            busy_penalty = min(1.0, busy_ratio * 1.25)
            overlap_penalty = min(1.0, overlap_active)
            total_interference_penalty = min(1.0, interference_penalty * (0.6 + persistent_ratio))

            raw_score = (
                WEIGHT_NOISE * noise_penalty
                + WEIGHT_PEAK * peak_penalty
                + WEIGHT_BUSY * busy_penalty
                + WEIGHT_OVERLAP * overlap_penalty
                + WEIGHT_INTERFERENCE * total_interference_penalty
            )

            clean_score = max(0.0, 100.0 - (raw_score * 20.0))

            scored[str(channel)] = {
                "center_freq_mhz": center,
                "noise_estimate_dbm": round(noise_est, 2),
                "peak_dbm": round(peak_dbm, 2),
                "busy_ratio": round(busy_ratio, 4),
                "peak_ratio": round(peak_ratio, 4),
                "overlap_ratio": round(overlap_active, 4),
                "persistent_ratio": round(persistent_ratio, 4),
                "score": round(clean_score, 2),
            }

        sorted_channels = sorted(
            scored.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )

        recommended = [int(ch) for ch, _ in sorted_channels[:3]]
        best_non_overlapping = self._best_non_overlapping(scored)

        return {
            "channels": scored,
            "recommended_top3": recommended,
            "best_non_overlapping": best_non_overlapping,
        }

    def _best_non_overlapping(self, scored: dict[str, Any]) -> list[int]:
        candidates = [1, 6, 11]
        available = [c for c in candidates if str(c) in scored]
        available.sort(key=lambda c: scored[str(c)]["score"], reverse=True)
        return available

    def _normalize_noise_penalty(self, noise_est_dbm: float) -> float:
        value = (noise_est_dbm - (-100.0)) / 20.0
        return float(np.clip(value, 0.0, 1.0))

    def _normalize_peak_penalty(self, peak_dbm: float) -> float:
        value = (peak_dbm - (-90.0)) / 40.0
        return float(np.clip(value, 0.0, 1.0))

    # -------------------------------------------------------------------------
    # Final verdict
    # -------------------------------------------------------------------------

    def _build_verdict(
        self,
        instantaneous: dict[str, Any],
        short_metrics: dict[str, Any],
        long_metrics: dict[str, Any],
        interference: dict[str, Any],
        channel_scores: dict[str, Any],
        active_ratio: float,
        strong_ratio: float,
        very_strong_ratio: float,
        persistent_ratio_short: float,
        persistent_ratio_long: float,
    ) -> dict[str, Any]:
        classification = interference["classification"]
        confidence = interference["confidence"]

        field_status = "good"
        summary = "Band oogt bruikbaar"
        action = "Geen duidelijke storing zichtbaar"

        best_non_overlap = channel_scores.get("best_non_overlapping", [])
        top3 = channel_scores.get("recommended_top3", [])

        if classification == "wideband_interferer":
            field_status = "critical"
            summary = "Waarschijnlijk brede niet-wifi storing in 2.4 GHz"
            action = "Kanaalwissel alleen zal waarschijnlijk niet volstaan"

        elif classification == "narrowband_interferer":
            field_status = "bad"
            summary = "Waarschijnlijk smalbandige stoorbron aanwezig"
            action = "Controleer bron in omgeving en vergelijk persistentie over tijd"

        elif classification == "wifi_congestion":
            field_status = "degraded"
            summary = "Vooral wifi-congestie / druk spectrum"
            action = "Optimaliseer kanaalkeuze; focus eerst op 1/6/11"

        elif classification == "wifi_activity":
            field_status = "ok"
            summary = "Normale wifi-activiteit zichtbaar"
            action = "Geen directe aanwijzing voor niet-wifi storing"

        elif classification == "possible_wideband_interference":
            field_status = "degraded"
            summary = "Mogelijke brede storing, maar nog niet persistent genoeg"
            action = "Langer observeren en capture bewaren"

        elif classification == "unknown_anomaly":
            field_status = "degraded"
            summary = "Atypisch patroon gedetecteerd"
            action = "Meer metingen nodig om wifi vs interferentie te onderscheiden"

        recommended_text = (
            f"Aanbevolen kanaalvolgorde: {top3}"
            if top3 else
            "Nog geen kanaalaanbeveling beschikbaar"
        )

        clean_1_6_11 = (
            f"Beste niet-overlappende kanalen: {best_non_overlap}"
            if best_non_overlap else
            "1/6/11 score nog niet beschikbaar"
        )

        return {
            "field_status": field_status,
            "summary": summary,
            "action": action,
            "recommended_text": recommended_text,
            "non_overlapping_text": clean_1_6_11,
            "classification": classification,
            "confidence": confidence,
            "active_ratio": round(active_ratio, 4),
            "strong_ratio": round(strong_ratio, 4),
            "very_strong_ratio": round(very_strong_ratio, 4),
            "persistent_ratio_short": round(persistent_ratio_short, 4),
            "persistent_ratio_long": round(persistent_ratio_long, 4),
            "instant_peak_dbm": instantaneous["peak_dbm"],
            "short_window_activity_ratio": short_metrics["activity_ratio"],
            "long_window_activity_ratio": long_metrics["activity_ratio"],
        }