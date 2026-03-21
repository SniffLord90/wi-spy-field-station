from flask import Flask, jsonify, render_template
from capture.spectool_capture import SpectoolManager
from config.settings import HOST, PORT

app = Flask(__name__)
capture = SpectoolManager()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/data")
def data():
    return jsonify(capture.get_data())


@app.route("/start", methods=["POST"])
def start():
    capture.start()
    return jsonify({"ok": True, "status": "running"})


@app.route("/stop", methods=["POST"])
def stop():
    capture.stop()
    return jsonify({"ok": True, "status": "stopped"})


@app.route("/status")
def status():
    return jsonify(capture.get_status())


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False, threaded=True)