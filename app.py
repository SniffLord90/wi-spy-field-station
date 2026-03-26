from flask import Flask, jsonify, render_template, request

from capture.spectool_capture import SpectoolManager
from config.settings import HOST, PORT

app = Flask(__name__)
capture = SpectoolManager()


@app.route("/")
def index():
    return render_template("index.html")


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


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False, threaded=True)