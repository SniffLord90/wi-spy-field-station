import json
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from config.settings import (
    DBM_MAX,
    DBM_MIN,
    DEFAULT_PROFILE_KEY,
    LIVE_UPDATE_INTERVAL_SECONDS,
    LOG_DIR,
    LONG_WINDOW_SECONDS,
    MAX_ROWS,
    MEASUREMENT_PROFILES,
    NARROW_MAX_WIDTH_MHZ,
    PERSISTENCE_MEDIUM_RATIO,
    POLL_INTERVAL_MS,
    SHORT_WINDOW_SECONDS,
    SIGNAL_ACTIVITY_THRESHOLD,
    SPECTOOL_DEVICE_INDEX,
    SPECTOOL_PATH,
    STRONG_SIGNAL_THRESHOLD,
    VERY_STRONG_SIGNAL_THRESHOLD,
    WIDEBAND_MIN_WIDTH_MHZ,
)


@dataclass
class SweepEntry:
    ts: float
    values: list[int]
    analysis: dict[str, Any]


class SpectoolManager:
    def __init__(self, live_update_hook: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self.lock = threading.RLock()

        self.running = False
        self.capture_thread: threading.Thread | None = None
        self.spectool_proc: subprocess.Popen[str] | None = None

        self.active_profile_key = DEFAULT_PROFILE_KEY
        self.active_profile = self._profile_by_key(DEFAULT_PROFILE_KEY)

        self.latest_sweep: list[int] = []
        self.latest_analysis: dict[str, Any] = {}
        self.last_update_time: float | None = None

        self.waterfall: deque[list[int]] = deque(maxlen=MAX_ROWS)
        self.history: deque[SweepEntry] = deque(maxlen=4000)

        self.rows_committed = 0
        self.expected_bins: int | None = None
        self._bin_freqs_cache: np.ndarray | None = None

        self.log_root = Path(LOG_DIR)
        self.log_root.mkdir(parents=True, exist_ok=True)

        self.session_id: str | None = None
        self.session_dir: Path | None = None
        self.session_start_ts: float | None = None
        self.session_file = None
        self.session_rows_logged = 0

        self.live_update_hook = live_update_hook
        self.remote_session_id: str | None = None
        self.remote_profile_name: str | None = None
        self._last_live_update_push_ts: float = 0.0

    # -------------------------------------------------------------------------
    # Remote session context
    # -------------------------------------------------------------------------

    def set_remote_session_context(self, session_id: str | None, profile_name: str | None) -> None:
        with self.lock:
            self.remote_session_id = session_id
            self.remote_profile_name = profile_name

    def clear_remote_session_context(self) -> None:
        with self.lock:
            self.remote_session_id = None
            self.remote_profile_name = None

    # -------------------------------------------------------------------------
    # Profiles
    # -------------------------------------------------------------------------

    def _profile_by_key(self, profile_key: str | None) -> dict[str, Any]:
        key = profile_key or DEFAULT_PROFILE_KEY
        return dict(MEASUREMENT_PROFILES.get(key, MEASUREMENT_PROFILES[DEFAULT_PROFILE_KEY]))

    def get_profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for key, profile in MEASUREMENT_PROFILES.items():
            item = dict(profile)
            item["key"] = key
            profiles.append(item)
        return profiles

    def get_default_profile_key(self) -> str:
        return DEFAULT_PROFILE_KEY

    def get_active_profile(self) -> dict[str, Any]:
        return dict(self.active_profile)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def start_capture(self, profile_key: str | None = None) -> dict[str, Any]:
        with self.lock:
            selected = self._profile_by_key(profile_key)

            if self.running:
                if selected["key"] == self.active_profile_key:
                    return {
                        "ok": True,
                        "message": "Capture already running",
                        "status": self.get_status(),
                    }
                return {
                    "ok": False,
                    "message": "Stop eerst de huidige meting voor je van range wisselt",
                    "status": self.get_status(),
                }

            self.active_profile_key = selected["key"]
            self.active_profile = selected

            self.latest_sweep = []
            self.latest_analysis = {}
            self.last_update_time = None
            self.waterfall.clear()
            self.history.clear()
            self.rows_committed = 0
            self.expected_bins = None
            self._bin_freqs_cache = None
            self._last_live_update_push_ts = 0.0

            self._start_session_logging()

            self.running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()

            return {
                "ok": True,
                "message": f'Meting gestart: {self.active_profile["label"]}',
                "status": self.get_status(),
            }

    def stop_capture(self) -> dict[str, Any]:
        with self.lock:
            self.running = False
            self._stop_spectool_process()

        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)

        with self.lock:
            self._stop_session_logging()
            return {
                "ok": True,
                "message": "Capture stopped",
                "status": self.get_status(),
            }

    def start(self, profile_key: str | None = None) -> dict[str, Any]:
        return self.start_capture(profile_key=profile_key)

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
                "session_id": self.session_id,
                "session_rows_logged": self.session_rows_logged,
                "session_dir": str(self.session_dir) if self.session_dir else None,
                "active_profile_key": self.active_profile_key,
                "active_profile": dict(self.active_profile),
                "remote_session_id": self.remote_session_id,
                "remote_profile_name": self.remote_profile_name,
            }

    def get_latest_data(self) -> dict[str, Any]:
        with self.lock:
            return {
                "freq_start_mhz": self.active_profile["freq_start_mhz"],
                "freq_end_mhz": self.active_profile["freq_end_mhz"],
                "axis_labels_mhz": list(self.active_profile["axis_labels_mhz"]),
                "profile": dict(self.active_profile),
                "waterfall": list(self.waterfall),
                "latest_sweep": list(self.latest_sweep),
                "analysis": dict(self.latest_analysis) if self.latest_analysis else {},
                "status": self.get_status(),
            }

    def get_data(self) -> dict[str, Any]:
        return self.get_latest_data()

    # -------------------------------------------------------------------------
    # Session logging
    # -------------------------------------------------------------------------

    def _start_session_logging(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = ts
        self.session_dir = self.log_root / ts
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_start_ts = time.time()
        self.session_rows_logged = 0

        metadata = {
            "session_id": self.session_id,
            "created_at": datetime.now().isoformat(),
            "profile_key": self.active_profile_key,
            "profile_label": self.active_profile["label"],
            "range_index": self.active_profile["range_index"],
            "freq_start_mhz": self.active_profile["freq_start_mhz"],
            "freq_end_mhz": self.active_profile["freq_end_mhz"],
            "spectool_path": SPECTOOL_PATH,
            "device_index": SPECTOOL_DEVICE_INDEX,
        }

        metadata_path = self.session_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self.session_file = open(self.session_dir / "sweeps.jsonl", "a", encoding="utf-8")

    def _stop_session_logging(self) -> None:
        if self.session_file:
            try:
                self.session_file.flush()
                self.session_file.close()
            except Exception:
                pass

        self.session_file = None

        if self.session_dir:
            summary = {
                "session_id": self.session_id,
                "ended_at": datetime.now().isoformat(),
                "rows_logged": self.session_rows_logged,
                "rows_committed_total": self.rows_committed,
                "duration_seconds": (
                    round(time.time() - self.session_start_ts, 2)
                    if self.session_start_ts
                    else None
                ),
                "profile_key": self.active_profile_key,
                "profile_label": self.active_profile["label"],
            }

            try:
                (self.session_dir / "summary.json").write_text(
                    json.dumps(summary, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def _log_sweep(self, ts: float, sweep: list[int], analysis: dict[str, Any]) -> None:
        if not self.session_file:
            return

        row = {
            "timestamp": ts,
            "profile_key": self.active_profile_key,
            "profile_label": self.active_profile["label"],
            "freq_start_mhz": self.active_profile["freq_start_mhz"],
            "freq_end_mhz": self.active_profile["freq_end_mhz"],
            "sweep": sweep,
            "analysis": {
                "rf_health": analysis.get("rf_health"),
                "noise_floor": analysis.get("noise_floor"),
                "peak": analysis.get("peak"),
                "peak_freq_mhz": analysis.get("peak_freq_mhz"),
                "peak_snr": analysis.get("peak_snr"),
                "interference_label": analysis.get("interference_label"),
                "best_channel": analysis.get("best_channel"),
                "action": analysis.get("action"),
            },
        }

        try:
            self.session_file.write(json.dumps(row) + "\n")
            self.session_file.flush()
            self.session_rows_logged += 1
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Live update helper
    # -------------------------------------------------------------------------

    def _build_live_payload(self, ts: float, analysis: dict[str, Any]) -> dict[str, Any]:
        verdict = analysis.get("verdict", {}) or {}

        latest_sweep = list(self.latest_sweep) if self.latest_sweep else []
        axis_labels = list(self.active_profile.get("axis_labels_mhz", []))

        return {
            "session_id": self.remote_session_id or self.session_id,
            "timestamp": datetime.fromtimestamp(ts).isoformat(),
            "profile_name": self.remote_profile_name or self.active_profile.get("label"),
            "profile_key": self.active_profile_key,
            "freq_start_mhz": self.active_profile.get("freq_start_mhz"),
            "freq_end_mhz": self.active_profile.get("freq_end_mhz"),
            "axis_labels_mhz": axis_labels,
            "noise_floor_dbm": analysis.get("noise_floor"),
            "peak_power_dbm": analysis.get("peak"),
            "peak_freq_mhz": analysis.get("peak_freq_mhz"),
            "verdict": verdict.get("summary") or analysis.get("interference_label") or "Live update",
            "running": self.running,
            "latest_sweep": latest_sweep,
        }

    def _maybe_send_live_update(self, ts: float, analysis: dict[str, Any]) -> None:
        if not self.live_update_hook:
            return

        if (ts - self._last_live_update_push_ts) < LIVE_UPDATE_INTERVAL_SECONDS:
            return

        payload = self._build_live_payload(ts, analysis)

        try:
            self.live_update_hook(payload)
            self._last_live_update_push_ts = ts
        except Exception as exc:
            print(f"[spectool_capture] live update hook failed: {exc}")

    # -------------------------------------------------------------------------
    # Spectool process handling
    # -------------------------------------------------------------------------

    def _start_spectool_process(self) -> bool:
        self._stop_spectool_process()

        try:
            range_arg = f'{SPECTOOL_DEVICE_INDEX}:{self.active_profile["range_index"]}'
            self.spectool_proc = subprocess.Popen(
                [SPECTOOL_PATH, "-r", range_arg],
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

        if not line or ":" not in line:
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

            with self.lock:
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
                self.history.append(SweepEntry(ts=now, values=raw_list, analysis=analysis))
                self.last_update_time = now
                self.rows_committed += 1
                self._log_sweep(now, raw_list, analysis)
                self._maybe_send_live_update(now, analysis)

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
            "profile_key": self.active_profile_key,
            "profile_label": self.active_profile["label"],
            "freq_start_mhz": self.active_profile["freq_start_mhz"],
            "freq_end_mhz": self.active_profile["freq_end_mhz"],
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
    # Metrics helpers
    # -------------------------------------------------------------------------

    def _window_entries(self, ts_start: float, ts_end: float) -> list[SweepEntry]:
        return [entry for entry in self.history if ts_start <= entry.ts <= ts_end]

    def _matrix_from_entries(self, entries: list[SweepEntry], bins: int) -> np.ndarray:
        if not entries:
            return np.empty((0, bins), dtype=float)
        return np.array([entry.values for entry in entries], dtype=float)

    def _instant_metrics(self, arr: np.ndarray) -> dict[str, Any]:
        if arr.size == 0:
            return {
                "noise_floor_estimate_dbm": None,
                "peak_dbm": None,
                "mean_dbm": None,
                "busy_ratio": 0.0,
            }

        noise_floor = float(np.percentile(arr, 20))
        peak_dbm = float(np.max(arr))
        mean_dbm = float(np.mean(arr))
        busy_ratio = float(np.mean(arr >= SIGNAL_ACTIVITY_THRESHOLD))

        return {
            "noise_floor_estimate_dbm": round(noise_floor, 1),
            "peak_dbm": round(peak_dbm, 1),
            "mean_dbm": round(mean_dbm, 1),
            "busy_ratio": round(busy_ratio, 3),
        }

    def _window_metrics(self, matrix: np.ndarray) -> dict[str, Any]:
        if matrix.size == 0:
            return {
                "rows": 0,
                "mean_dbm": None,
                "peak_dbm": None,
                "noise_floor_estimate_dbm": None,
                "busy_ratio": 0.0,
            }

        flat = matrix.flatten()
        return {
            "rows": int(matrix.shape[0]),
            "mean_dbm": round(float(np.mean(flat)), 1),
            "peak_dbm": round(float(np.max(flat)), 1),
            "noise_floor_estimate_dbm": round(float(np.percentile(flat, 20)), 1),
            "busy_ratio": round(float(np.mean(matrix >= SIGNAL_ACTIVITY_THRESHOLD)), 3),
        }

    def _get_bin_freqs(self, bins: int) -> np.ndarray:
        if self._bin_freqs_cache is not None and len(self._bin_freqs_cache) == bins:
            return self._bin_freqs_cache

        freqs = np.linspace(
            self.active_profile["freq_start_mhz"],
            self.active_profile["freq_end_mhz"],
            bins,
        )
        self._bin_freqs_cache = freqs
        return freqs

    def _persistent_mask(self, matrix: np.ndarray, threshold_dbm: float) -> np.ndarray:
        if matrix.size == 0:
            return np.array([], dtype=bool)

        ratio = np.mean(matrix >= threshold_dbm, axis=0)
        return ratio >= PERSISTENCE_MEDIUM_RATIO

    def _find_segments(self, mask: np.ndarray, freqs: np.ndarray) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        if len(mask) == 0 or len(freqs) == 0:
            return segments

        start_idx: int | None = None

        for idx, is_active in enumerate(mask):
            if is_active and start_idx is None:
                start_idx = idx
            elif not is_active and start_idx is not None:
                end_idx = idx - 1
                segments.append(self._segment_from_indices(start_idx, end_idx, freqs))
                start_idx = None

        if start_idx is not None:
            segments.append(self._segment_from_indices(start_idx, len(mask) - 1, freqs))

        return segments

    def _segment_from_indices(self, start_idx: int, end_idx: int, freqs: np.ndarray) -> dict[str, Any]:
        start_freq = float(freqs[start_idx])
        end_freq = float(freqs[end_idx])
        width = max(0.0, end_freq - start_freq)

        return {
            "start_idx": start_idx,
            "end_idx": end_idx,
            "start_freq_mhz": round(start_freq, 2),
            "end_freq_mhz": round(end_freq, 2),
            "center_freq_mhz": round((start_freq + end_freq) / 2.0, 2),
            "width_mhz": round(width, 2),
        }

    # -------------------------------------------------------------------------
    # Interference / channel scoring / verdict
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
        del freqs, long_metrics

        if arr.size == 0:
            return {
                "type": "clean",
                "label": "Geen duidelijke storing",
                "severity": "good",
                "details": [],
            }

        busy_ratio = short_metrics.get("busy_ratio") or 0.0
        persistent_ratio = float(np.mean(persistent_mask)) if len(persistent_mask) else 0.0
        strongest_width = max((seg["width_mhz"] for seg in segments_now), default=0.0)
        persistent_width = max((seg["width_mhz"] for seg in segments_persistent), default=0.0)
        strong_ratio = float(np.mean(strong_mask)) if len(strong_mask) else 0.0

        if strongest_width >= WIDEBAND_MIN_WIDTH_MHZ and persistent_ratio > 0.22:
            return {
                "type": "wideband_interferer",
                "label": "Brede storing",
                "severity": "bad",
                "details": [
                    f"Breed actief segment: {round(strongest_width, 1)} MHz",
                    f"Persistente bezetting: {round(persistent_ratio * 100, 1)}%",
                ],
            }

        if strongest_width <= NARROW_MAX_WIDTH_MHZ and persistent_width <= NARROW_MAX_WIDTH_MHZ and strong_ratio > 0.01:
            return {
                "type": "narrowband_interferer",
                "label": "Smalbandige storing",
                "severity": "warn",
                "details": [
                    f"Smal actief segment: {round(strongest_width, 1)} MHz",
                ],
            }

        if busy_ratio > 0.35:
            return {
                "type": "wifi_congestion",
                "label": "Wifi congestie",
                "severity": "warn",
                "details": [
                    f"Hoge activiteit in de sweep: {round(busy_ratio * 100, 1)}%",
                ],
            }

        if np.mean(active_mask) > 0.05:
            return {
                "type": "wifi_activity",
                "label": "Normale wifi-activiteit",
                "severity": "good",
                "details": [],
            }

        return {
            "type": "clean",
            "label": "Geen duidelijke storing",
            "severity": "good",
            "details": [],
        }

    def _score_channels(
        self,
        arr: np.ndarray,
        freqs: np.ndarray,
        short_matrix: np.ndarray,
        persistent_mask: np.ndarray,
        interference: dict[str, Any],
    ) -> dict[str, Any]:
        if self.active_profile["channel_mode"] != "2g":
            return {
                "channels": {},
                "best_non_overlapping": [],
                "recommended_top3": [],
            }

        channels = {
            1: 2412.0,
            6: 2437.0,
            11: 2462.0,
        }

        results: dict[str, Any] = {}

        for ch, center in channels.items():
            window_mask = (freqs >= (center - 10.0)) & (freqs <= (center + 10.0))
            if not np.any(window_mask):
                continue

            window = arr[window_mask]
            noise_est = float(np.percentile(window, 20))
            peak_dbm = float(np.max(window))
            mean_dbm = float(np.mean(window))
            avg_snr = mean_dbm - noise_est
            peak_snr = peak_dbm - noise_est
            busy_ratio = float(np.mean(window >= SIGNAL_ACTIVITY_THRESHOLD))

            overlap_penalty = float(np.mean(persistent_mask[window_mask])) if len(persistent_mask) else 0.0
            interference_penalty = 12.0 if interference.get("severity") == "bad" else 6.0 if interference.get("severity") == "warn" else 0.0

            score = (
                100.0
                - max(0.0, mean_dbm + 100.0) * 1.8
                - busy_ratio * 40.0
                - overlap_penalty * 25.0
                - interference_penalty
            )
            score = max(0.0, min(100.0, score))

            results[str(ch)] = {
                "center_mhz": center,
                "noise_estimate_dbm": round(noise_est, 1),
                "peak_dbm": round(peak_dbm, 1),
                "mean_dbm": round(mean_dbm, 1),
                "avg_snr": round(avg_snr, 1),
                "peak_snr": round(peak_snr, 1),
                "busy_ratio": round(busy_ratio, 3),
                "score": round(score, 1),
            }

        ranked = sorted(results.items(), key=lambda item: item[1]["score"], reverse=True)
        recommended = [item[0] for item in ranked]

        return {
            "channels": results,
            "best_non_overlapping": recommended[:3],
            "recommended_top3": recommended[:3],
        }

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
        del long_metrics, strong_ratio, very_strong_ratio, persistent_ratio_long

        noise_floor = instantaneous.get("noise_floor_estimate_dbm")
        busy_ratio = short_metrics.get("busy_ratio") or 0.0

        severity = "good"
        badge = "OK"
        title = "Wi-Spy omgeving oogt gezond"
        summary = "Geen duidelijke zware storing zichtbaar."
        details: list[str] = []

        if interference["severity"] == "bad":
            severity = "bad"
            badge = "SLECHT"
            title = "Duidelijke storing of brede bezetting"
            summary = interference["label"]
            details.extend(interference.get("details", []))
        elif interference["severity"] == "warn":
            severity = "warn"
            badge = "OPGELET"
            title = "RF-omgeving is niet ideaal"
            summary = interference["label"]
            details.extend(interference.get("details", []))
        elif noise_floor is not None and noise_floor > -92:
            severity = "warn"
            badge = "MATIG"
            title = "Noise floor is relatief hoog"
            summary = "De basisruis ligt hoger dan ideaal."
        elif busy_ratio > 0.35 or active_ratio > 0.30:
            severity = "warn"
            badge = "DRUK"
            title = "Er is veel activiteit zichtbaar"
            summary = "De band is merkbaar bezet."
        else:
            details.append("Geen uitgesproken abnormale RF-signatuur zichtbaar.")

        action = "Geen specifieke actie"
        if self.active_profile["channel_mode"] == "2g":
            best = channel_scores.get("best_non_overlapping", [])
            if best:
                action = f"Aanbevolen kanaal: {best[0]}"
                details.append(f"Beste niet-overlappende kanaalkeuze: {best[0]}")
        else:
            action = f'Actieve range: {self.active_profile["label"]}'
            details.append(f'Analyse gebeurt in range: {self.active_profile["label"]}')

        field_status = {
            "good": "good",
            "warn": "degraded",
            "bad": "bad",
        }[severity]

        if persistent_ratio_short > 0.35 and severity != "bad":
            field_status = "degraded"

        return {
            "severity": severity,
            "badge": badge,
            "title": title,
            "summary": summary,
            "details": details,
            "action": action,
            "field_status": field_status,
        }

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

        best_channel = (
            best_non_overlap[0]
            if best_non_overlap
            else (recommended_top3[0] if recommended_top3 else None)
        )

        peak_dbm = instantaneous.get("peak_dbm")
        noise_floor = instantaneous.get("noise_floor_estimate_dbm")
        peak_idx = int(np.argmax(arr)) if len(arr) else None
        peak_freq = round(float(freqs[peak_idx]), 2) if peak_idx is not None else None

        peak_snr = round(float(peak_dbm - noise_floor), 1) if peak_dbm is not None and noise_floor is not None else None

        active_zone = "--"
        if segments_now:
            widest = max(segments_now, key=lambda seg: seg["width_mhz"])
            active_zone = f'{widest["start_freq_mhz"]} - {widest["end_freq_mhz"]} MHz'

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

        def channel_block(ch: int) -> dict[str, Any] | None:
            data = channels.get(str(ch))
            if not data:
                return None
            return {
                "label": self._channel_label_from_score(data["score"]),
                "mean_dbm": data["mean_dbm"],
                "avg_snr": data["avg_snr"],
                "peak_snr": data["peak_snr"],
                "score": data["score"],
            }

        return {
            "rf_health": rf_health_map.get(verdict.get("field_status", "unknown"), "Onbekend"),
            "noise_floor": noise_floor,
            "peak": peak_dbm,
            "peak_freq_mhz": peak_freq,
            "peak_snr": peak_snr,
            "active_zone": active_zone,
            "interference_label": interference_map.get(interference.get("type"), interference.get("label", "Onbekend")),
            "best_channel": best_channel,
            "action": verdict.get("action"),
            "channel_1": channel_block(1),
            "channel_6": channel_block(6),
            "channel_11": channel_block(11),
        }

    def _channel_label_from_score(self, score: float) -> str:
        if score >= 80:
            return "Goed"
        if score >= 60:
            return "OK"
        if score >= 45:
            return "Matig"
        return "Slecht"