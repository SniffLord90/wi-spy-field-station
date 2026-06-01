import json
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, url_for
from server_client import ServerClient
from heartbeat_worker import HeartbeatWorker

from capture.spectool_capture import SpectoolManager
from config.settings import HOST, PORT, LOG_DIR
from wifi_manager import WifiManager

app = Flask(__name__)

server_client = ServerClient()
heartbeat_worker = HeartbeatWorker()

current_remote_session_id = None
current_remote_profile = None
current_customer_number = None


def push_live_update(payload: dict):
    result = server_client.send_live_update(payload)
    print("[app] send_live_update result:", result)


capture = SpectoolManager(live_update_hook=push_live_update)
wifi = WifiManager()


def upload_state_path_for_session_dir(session_dir: str | Path) -> Path:
    return Path(session_dir) / "upload_state.json"


def write_upload_state(
    session_dir: str | Path,
    *,
    remote_session_id: str,
    customer_number: str,
    status: str,
    upload_result: dict | None = None,
) -> Path:
    path = upload_state_path_for_session_dir(session_dir)
    payload = {
        "remote_session_id": remote_session_id,
        "customer_number": customer_number,
        "session_dir": str(session_dir),
        "status": status,
        "updated_at": datetime.now().isoformat(),
        "upload_result": upload_result,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_upload_state(path: str | Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[app] Failed to read upload state {path}: {exc}")
        return None


def mark_upload_state_uploaded(
    session_dir: str | Path,
    *,
    remote_session_id: str,
    customer_number: str,
    upload_result: dict | None = None,
):
    write_upload_state(
        session_dir,
        remote_session_id=remote_session_id,
        customer_number=customer_number,
        status="uploaded",
        upload_result=upload_result,
    )


def mark_upload_state_pending(
    session_dir: str | Path,
    *,
    remote_session_id: str,
    customer_number: str,
    upload_result: dict | None = None,
):
    write_upload_state(
        session_dir,
        remote_session_id=remote_session_id,
        customer_number=customer_number,
        status="pending_upload",
        upload_result=upload_result,
    )


def cleanup_session_dir(session_dir: str | Path) -> dict:
    session_path = Path(session_dir)

    if not session_path.exists():
        return {
            "ok": True,
            "reason": "already_missing",
            "session_dir": str(session_path),
        }

    try:
        shutil.rmtree(session_path)
        print(f"[app] Cleaned up local session dir: {session_path}")
        return {
            "ok": True,
            "reason": "deleted",
            "session_dir": str(session_path),
        }
    except Exception as exc:
        print(f"[app] Failed to clean up session dir {session_path}: {exc}")
        return {
            "ok": False,
            "reason": str(exc),
            "session_dir": str(session_path),
        }


def scan_upload_states() -> list[Path]:
    log_root = Path(LOG_DIR)
    if not log_root.exists():
        return []

    return list(log_root.glob("*/upload_state.json"))


def retry_pending_uploads():
    state_files = scan_upload_states()
    pending_files: list[Path] = []

    for state_file in state_files:
        data = read_upload_state(state_file)
        if not data:
            continue

        if data.get("status") == "pending_upload":
            pending_files.append(state_file)

    print(f"[app] Pending upload states found: {len(pending_files)}")

    for state_file in pending_files:
        data = read_upload_state(state_file)
        if not data:
            continue

        remote_session_id = data.get("remote_session_id")
        customer_number = data.get("customer_number")
        session_dir = data.get("session_dir")

        if not remote_session_id or not customer_number or not session_dir:
            print(f"[app] Invalid pending upload state: {state_file}")
            continue

        print(
            "[app] Retrying pending upload:",
            f"session={remote_session_id}",
            f"customer={customer_number}",
            f"dir={session_dir}",
        )

        upload_result = server_client.upload_session_artifacts(
            session_id=remote_session_id,
            customer_number=customer_number,
            session_dir=session_dir,
        )
        print("[app] retry upload_session_artifacts result:", upload_result)

        if upload_result.get("ok"):
            mark_upload_state_uploaded(
                session_dir=session_dir,
                remote_session_id=remote_session_id,
                customer_number=customer_number,
                upload_result=upload_result,
            )
            cleanup_result = cleanup_session_dir(session_dir)
            print("[app] retry cleanup result:", cleanup_result)
        else:
            mark_upload_state_pending(
                session_dir=session_dir,
                remote_session_id=remote_session_id,
                customer_number=customer_number,
                upload_result=upload_result,
            )


def cleanup_uploaded_sessions():
    state_files = scan_upload_states()
    uploaded_files: list[Path] = []

    for state_file in state_files:
        data = read_upload_state(state_file)
        if not data:
            continue

        if data.get("status") == "uploaded":
            uploaded_files.append(state_file)

    print(f"[app] Uploaded session states found for cleanup: {len(uploaded_files)}")

    for state_file in uploaded_files:
        data = read_upload_state(state_file)
        if not data:
            continue

        session_dir = data.get("session_dir")
        if not session_dir:
            continue

        cleanup_result = cleanup_session_dir(session_dir)
        print("[app] startup cleanup result:", cleanup_result)


def bootstrap_server_integration():
    print("[app] Bootstrapping server integration...")

    register_result = server_client.register_analyzer()
    print("[app] register_analyzer result:", register_result)

    heartbeat_worker.update_state(
        current_session_id=None,
        current_profile=None,
        status="online",
    )
    heartbeat_worker.start()

    print("[app] Heartbeat worker started.")

    retry_pending_uploads()
    cleanup_uploaded_sessions()


def build_remote_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{server_client.analyzer_id}"


def send_final_stopped_live_update():
    global current_remote_session_id
    global current_remote_profile

    latest_data = capture.get_data()
    latest_analysis = latest_data.get("analysis") or {}

    payload = {
        "session_id": current_remote_session_id,
        "timestamp": datetime.now().isoformat(),
        "profile_name": current_remote_profile,
        "noise_floor_dbm": latest_analysis.get("noise_floor"),
        "peak_power_dbm": latest_analysis.get("peak"),
        "verdict": "Meting gestopt",
        "running": False,
    }

    push_live_update(payload)


def try_upload_session_artifacts():
    global current_remote_session_id
    global current_customer_number

    status = capture.get_status()
    session_dir = status.get("session_dir")

    if not current_remote_session_id:
        print("[app] No remote session id available for upload.")
        return {
            "ok": False,
            "reason": "missing_remote_session_id",
        }

    if not current_customer_number:
        print("[app] No customer number available for upload.")
        return {
            "ok": False,
            "reason": "missing_customer_number",
        }

    if not session_dir:
        print("[app] No local session_dir available for upload.")
        return {
            "ok": False,
            "reason": "missing_session_dir",
        }

    upload_result = server_client.upload_session_artifacts(
        session_id=current_remote_session_id,
        customer_number=current_customer_number,
        session_dir=session_dir,
    )
    print("[app] upload_session_artifacts result:", upload_result)
    return upload_result


def inject_once(html: str, marker: str, snippet: str, *, before: bool = True) -> str:
    if snippet in html:
        return html

    if marker not in html:
        return html

    if before:
        return html.replace(marker, f"{snippet}\n{marker}", 1)

    return html.replace(marker, f"{marker}\n{snippet}", 1)


def build_wifi_panel_html() -> str:
    return """
  <section class="wifi-panel" id="wifiPanel">
    <div class="wifi-panel-header">
      <div>
        <h2 class="wifi-title">WiFi verbinding</h2>
        <div class="wifi-subtitle">
          Scan netwerken, kies een SSID en verbind de Raspberry Pi via WLAN.
        </div>
      </div>
      <div class="wifi-panel-actions">
        <button id="wifiRefreshBtn" type="button">Scan WiFi</button>
        <button id="wifiDisconnectBtn" type="button">Verbreek WiFi</button>
      </div>
    </div>

    <div class="wifi-status-line" id="wifiStatusLine">
      WiFi-status laden...
    </div>

    <div class="wifi-message hidden" id="wifiMessage"></div>

    <div class="wifi-grid">
      <div class="wifi-list-wrap">
        <div class="wifi-section-title">Beschikbare netwerken</div>
        <div class="wifi-list" id="wifiList">
          <div class="wifi-empty">Nog geen scan uitgevoerd</div>
        </div>
      </div>

      <div class="wifi-form-wrap">
        <div class="wifi-section-title">Verbinden</div>

        <label class="wifi-label" for="wifiSelectedSsid">Geselecteerde SSID</label>
        <input
          id="wifiSelectedSsid"
          class="wifi-input"
          type="text"
          placeholder="Klik links op een netwerk of vul manueel in"
          autocomplete="off"
        >

        <label class="wifi-label" for="wifiPassword">Wachtwoord</label>
        <input
          id="wifiPassword"
          class="wifi-input"
          type="password"
          placeholder="WPA/WPA2/WPA3 wachtwoord"
          autocomplete="current-password"
        >

        <div class="wifi-form-hint">
          Laat het wachtwoord leeg voor een open netwerk.
        </div>

        <button id="wifiConnectBtn" type="button">Verbind Raspberry Pi met WiFi</button>
      </div>
    </div>
  </section>
""".rstrip()


def render_index_with_wifi() -> str:
    html = render_template("index.html")

    wifi_css = f'<link rel="stylesheet" href="{url_for("static", filename="css/wifi.css")}">'
    wifi_js = f'<script src="{url_for("static", filename="js/wifi.js")}"></script>'
    wifi_panel_html = build_wifi_panel_html()

    html = inject_once(html, "</head>", wifi_css, before=True)
    html = inject_once(html, "</body>", wifi_js, before=True)

    anchor = '<div class="status" id="profileInfo">Nog geen profiel geladen</div>'
    html = inject_once(html, anchor, wifi_panel_html, before=True)

    return html


@app.route("/")
def index():
    return render_index_with_wifi()


@app.route("/profiles")
def profiles():
    return jsonify(
        {
            "profiles": capture.get_profiles(),
            "default_profile_key": capture.get_default_profile_key(),
        }
    )


@app.route("/data")
def data():
    return jsonify(capture.get_data())


@app.route("/start", methods=["POST"])
def start():
    global current_remote_session_id
    global current_remote_profile
    global current_customer_number

    payload = request.get_json(silent=True) or {}
    profile_key = payload.get("profile_key")
    customer_number = (payload.get("customer_number") or "PENDING").strip()
    notes = payload.get("notes") or ""

    result = capture.start(profile_key=profile_key)

    if result.get("ok"):
        session_id = build_remote_session_id()
        profile_name = profile_key or "default"

        remote_result = server_client.start_remote_session(
            session_id=session_id,
            customer_number=customer_number,
            profile_name=profile_name,
            notes=notes,
        )
        print("[app] start_remote_session result:", remote_result)

        current_remote_session_id = session_id
        current_remote_profile = profile_name
        current_customer_number = customer_number

        capture.set_remote_session_context(
            session_id=current_remote_session_id,
            profile_name=current_remote_profile,
        )

        heartbeat_worker.update_state(
            current_session_id=current_remote_session_id,
            current_profile=current_remote_profile,
            status="online",
        )

        result["remote_session_id"] = current_remote_session_id
        result["remote_customer_number"] = current_customer_number

    return jsonify(result)


@app.route("/stop", methods=["POST"])
def stop():
    global current_remote_session_id
    global current_remote_profile
    global current_customer_number

    result = capture.stop()

    upload_result = None
    cleanup_result = None
    status = capture.get_status()
    session_dir = status.get("session_dir")

    if current_remote_session_id:
        send_final_stopped_live_update()

        finish_result = server_client.finish_remote_session(current_remote_session_id)
        print("[app] finish_remote_session result:", finish_result)

        upload_result = try_upload_session_artifacts()

        if session_dir and current_customer_number:
            if upload_result and upload_result.get("ok"):
                mark_upload_state_uploaded(
                    session_dir=session_dir,
                    remote_session_id=current_remote_session_id,
                    customer_number=current_customer_number,
                    upload_result=upload_result,
                )
                cleanup_result = cleanup_session_dir(session_dir)
            else:
                mark_upload_state_pending(
                    session_dir=session_dir,
                    remote_session_id=current_remote_session_id,
                    customer_number=current_customer_number,
                    upload_result=upload_result,
                )

    capture.clear_remote_session_context()

    current_remote_session_id = None
    current_remote_profile = None
    current_customer_number = None

    heartbeat_worker.update_state(
        current_session_id=None,
        current_profile=None,
        status="online",
    )

    if upload_result is not None:
        result["upload_result"] = upload_result

    if cleanup_result is not None:
        result["cleanup_result"] = cleanup_result

    return jsonify(result)


@app.route("/status")
def status():
    return jsonify(capture.get_status())


@app.route("/wifi/status")
def wifi_status():
    result = wifi.get_status()
    status_code = 200 if result.get("ok") else 500
    return jsonify(result), status_code


@app.route("/wifi/networks")
def wifi_networks():
    result = wifi.scan_networks()
    status_code = 200 if result.get("ok") else 500
    return jsonify(result), status_code


@app.route("/wifi/connect", methods=["POST"])
def wifi_connect():
    payload = request.get_json(silent=True) or {}
    ssid = (payload.get("ssid") or "").strip()
    password = payload.get("password") or ""

    result = wifi.connect(ssid=ssid, password=password)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/wifi/disconnect", methods=["POST"])
def wifi_disconnect():
    result = wifi.disconnect()
    status_code = 200 if result.get("ok") else 500
    return jsonify(result), status_code


if __name__ == "__main__":
    bootstrap_server_integration()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)