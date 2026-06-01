from flask import Flask, jsonify, render_template, request, url_for

from capture.spectool_capture import SpectoolManager
from config.settings import HOST, PORT
from wifi_manager import WifiManager

app = Flask(__name__)

capture = SpectoolManager()
wifi = WifiManager()


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
    payload = request.get_json(silent=True) or {}
    profile_key = payload.get("profile_key")
    result = capture.start(profile_key=profile_key)
    return jsonify(result)


@app.route("/stop", methods=["POST"])
def stop():
    result = capture.stop()
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
    app.run(host=HOST, port=PORT, debug=False, threaded=True)