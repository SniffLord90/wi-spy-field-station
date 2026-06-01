MAX_ROWS = 120

DBM_MIN = -110

DBM_MAX = -30

POLL_INTERVAL_MS = 250

HOST = "0.0.0.0"

PORT = 5000

SHORT_WINDOW_SECONDS = 8

LONG_WINDOW_SECONDS = 30

SIGNAL_ACTIVITY_THRESHOLD = -88

STRONG_SIGNAL_THRESHOLD = -75

VERY_STRONG_SIGNAL_THRESHOLD = -65

NARROW_MAX_WIDTH_MHZ = 4.0

WIDEBAND_MIN_WIDTH_MHZ = 18.0

PERSISTENCE_MEDIUM_RATIO = 0.40

WEIGHT_NOISE = 1.0

WEIGHT_PEAK = 1.2

WEIGHT_BUSY = 1.4

WEIGHT_OVERLAP = 1.0

WEIGHT_INTERFERENCE = 1.8

SPECTOOL_PATH = "/home/jproost/spectools/spectool_raw"

SPECTOOL_DEVICE_INDEX = 0

LOG_DIR = "/home/jproost/wi-spy-field-station/logs"

WIFI_INTERFACE = "wlan0"
WIFI_USE_SUDO = True
WIFI_SCAN_WAIT_SECONDS = 3
WIFI_COMMAND_TIMEOUT_SECONDS = 20

MEASUREMENT_PROFILES = {
    "2g_full": {
        "key": "2g_full",
        "label": "2.4 GHz",
        "range_index": 0,
        "freq_start_mhz": 2400.0,
        "freq_end_mhz": 2495.0,
        "axis_labels_mhz": [2400.0, 2447.5, 2495.0],
        "channel_mode": "2g",
    },
    "5g_full": {
        "key": "5g_full",
        "label": "Full 5GHz Band",
        "range_index": 2,
        "freq_start_mhz": 5150.0,
        "freq_end_mhz": 5836.0,
        "axis_labels_mhz": [5150.0, 5493.0, 5836.0],
        "channel_mode": "5g",
    },
    "5g_unii_36_64": {
        "key": "5g_unii_36_64",
        "label": "UNII Low/Mid ch. 36-64",
        "range_index": 3,
        "freq_start_mhz": 5150.0,
        "freq_end_mhz": 5350.0,
        "axis_labels_mhz": [5150.0, 5250.0, 5350.0],
        "channel_mode": "5g",
    },
    "5g_unii_100_140": {
        "key": "5g_unii_100_140",
        "label": "UNII ch. 100-140",
        "range_index": 4,
        "freq_start_mhz": 5470.0,
        "freq_end_mhz": 5725.0,
        "axis_labels_mhz": [5470.0, 5597.5, 5725.0],
        "channel_mode": "5g",
    },
    "5g_unii_149_165": {
        "key": "5g_unii_149_165",
        "label": "UNII ch. 149-165",
        "range_index": 5,
        "freq_start_mhz": 5725.0,
        "freq_end_mhz": 5836.0,
        "axis_labels_mhz": [5725.0, 5780.5, 5836.0],
        "channel_mode": "5g",
    },
}

DEFAULT_PROFILE_KEY = "2g_full"