import os
import json
from pathlib import Path
from flask import Flask, jsonify, request, render_template
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit, join_room
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.config["SECRET_KEY"] = "wispy-live-secret"

socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_ROOT = Path("/app/uploads")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

LIVE_STATE = {}


def get_db_connection():
    return psycopg2.connect(
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        cursor_factory=RealDictCursor,
    )


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS analyzers (
            id SERIAL PRIMARY KEY,
            analyzer_id VARCHAR(100) UNIQUE NOT NULL,
            name VARCHAR(255),
            location VARCHAR(255),
            status VARCHAR(50) DEFAULT 'offline',
            current_session_id VARCHAR(100),
            current_profile VARCHAR(100),
            last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        ALTER TABLE analyzers
        ADD COLUMN IF NOT EXISTS current_session_id VARCHAR(100);
    """)

    cur.execute("""
        ALTER TABLE analyzers
        ADD COLUMN IF NOT EXISTS current_profile VARCHAR(100);
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            session_id VARCHAR(100) UNIQUE NOT NULL,
            analyzer_id VARCHAR(100) NOT NULL,
            customer_number VARCHAR(100) NOT NULL,
            profile_name VARCHAR(100),
            notes TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            status VARCHAR(50) DEFAULT 'running',
            data_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()


def get_session_folder(customer_number: str, session_id: str) -> Path:
    return UPLOAD_ROOT / customer_number / session_id


@app.route("/")
def dashboard():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS count FROM analyzers;")
        total_analyzers = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM analyzers WHERE status = 'online';")
        online_analyzers = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM sessions;")
        total_sessions = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM sessions WHERE status = 'running';")
        running_sessions = cur.fetchone()["count"]

        cur.execute("""
            SELECT *
            FROM sessions
            ORDER BY started_at DESC
            LIMIT 5;
        """)
        recent_sessions = cur.fetchall()

        cur.execute("""
            SELECT *
            FROM analyzers
            ORDER BY last_seen DESC NULLS LAST, created_at DESC
            LIMIT 5;
        """)
        recent_analyzers = cur.fetchall()

        cur.close()
        conn.close()

        stats = {
            "total_analyzers": total_analyzers,
            "online_analyzers": online_analyzers,
            "total_sessions": total_sessions,
            "running_sessions": running_sessions,
        }

        return render_template(
            "dashboard.html",
            stats=stats,
            recent_sessions=recent_sessions,
            recent_analyzers=recent_analyzers
        )
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


@app.route("/db-test")
def db_test():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()["version"]
        cur.close()
        conn.close()

        return jsonify({
            "status": "ok",
            "database_connected": True,
            "postgres_version": version
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "database_connected": False,
            "error": str(e)
        }), 500


@app.route("/init-db", methods=["POST"])
def initialize_database():
    try:
        init_db()
        return jsonify({
            "status": "ok",
            "message": "Database initialized successfully"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/api")
def api_home():
    return jsonify({
        "message": "WiSpy server API is running",
        "status": "ok"
    })


@app.route("/analyzers", methods=["GET"])
def get_analyzers():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT *
            FROM analyzers
            ORDER BY created_at DESC;
        """)
        analyzers = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            "status": "ok",
            "analyzers": analyzers
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/analyzers/view", methods=["GET"])
def analyzers_page():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM analyzers
            ORDER BY created_at DESC;
        """)

        analyzers = cur.fetchall()
        cur.close()
        conn.close()

        return render_template(
            "analyzers.html",
            analyzers=analyzers
        )
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/analyzers/<analyzer_id>/view", methods=["GET"])
def analyzer_detail_page(analyzer_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM analyzers
            WHERE analyzer_id = %s
            LIMIT 1;
        """, (analyzer_id,))
        analyzer = cur.fetchone()

        cur.execute("""
            SELECT *
            FROM sessions
            WHERE analyzer_id = %s
            ORDER BY started_at DESC
            LIMIT 10;
        """, (analyzer_id,))
        recent_sessions = cur.fetchall()

        cur.close()
        conn.close()

        if not analyzer:
            return jsonify({
                "status": "error",
                "error": "analyzer not found"
            }), 404

        live_state = LIVE_STATE.get(analyzer_id)

        return render_template(
            "analyzer_detail.html",
            analyzer=analyzer,
            recent_sessions=recent_sessions,
            live_state=live_state
        )
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/analyzers", methods=["POST"])
def create_or_update_analyzer():
    try:
        data = request.get_json()

        analyzer_id = data.get("analyzer_id")
        name = data.get("name")
        location = data.get("location")
        status = data.get("status", "online")

        if not analyzer_id:
            return jsonify({
                "status": "error",
                "error": "analyzer_id is required"
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO analyzers (
                analyzer_id, name, location, status,
                current_session_id, current_profile, last_seen
            )
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (analyzer_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                location = EXCLUDED.location,
                status = EXCLUDED.status,
                last_seen = CURRENT_TIMESTAMP
            RETURNING *;
        """, (
            analyzer_id,
            name,
            location,
            status,
            None,
            None
        ))

        analyzer = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "ok",
            "analyzer": analyzer
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/analyzers/heartbeat", methods=["POST"])
def analyzer_heartbeat():
    try:
        data = request.get_json()

        analyzer_id = data.get("analyzer_id")
        status = data.get("status", "online")
        current_session_id = data.get("current_session_id")
        current_profile = data.get("current_profile")

        if not analyzer_id:
            return jsonify({
                "status": "error",
                "error": "analyzer_id is required"
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE analyzers
            SET
                status = %s,
                current_session_id = %s,
                current_profile = %s,
                last_seen = CURRENT_TIMESTAMP
            WHERE analyzer_id = %s
            RETURNING *;
        """, (
            status,
            current_session_id,
            current_profile,
            analyzer_id
        ))

        analyzer = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not analyzer:
            return jsonify({
                "status": "error",
                "error": "analyzer not found"
            }), 404

        return jsonify({
            "status": "ok",
            "message": "heartbeat received",
            "analyzer": analyzer
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/sessions", methods=["GET"])
def get_sessions():
    try:
        customer_number = request.args.get("customer_number")

        conn = get_db_connection()
        cur = conn.cursor()

        if customer_number:
            cur.execute("""
                SELECT *
                FROM sessions
                WHERE customer_number = %s
                ORDER BY started_at DESC;
            """, (customer_number,))
        else:
            cur.execute("""
                SELECT *
                FROM sessions
                ORDER BY started_at DESC;
            """)

        sessions = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            "status": "ok",
            "sessions": sessions
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/sessions/detail/<session_id>", methods=["GET"])
def get_session_detail(session_id):
    try:
        customer_number = request.args.get("customer_number")

        if not customer_number:
            return jsonify({
                "status": "error",
                "error": "customer_number is required"
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM sessions
            WHERE session_id = %s AND customer_number = %s
            LIMIT 1;
        """, (session_id, customer_number))

        session = cur.fetchone()
        cur.close()
        conn.close()

        if not session:
            return jsonify({
                "status": "error",
                "error": "session not found"
            }), 404

        return jsonify({
            "status": "ok",
            "session": session
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/sessions", methods=["POST"])
def create_session():
    try:
        data = request.get_json()

        session_id = data.get("session_id")
        analyzer_id = data.get("analyzer_id")
        customer_number = data.get("customer_number")
        profile_name = data.get("profile_name")
        notes = data.get("notes")

        if not session_id or not analyzer_id or not customer_number:
            return jsonify({
                "status": "error",
                "error": "session_id, analyzer_id and customer_number are required"
            }), 400

        session_folder = get_session_folder(customer_number, session_id)
        session_folder.mkdir(parents=True, exist_ok=True)

        data_path = f"uploads/{customer_number}/{session_id}"

        metadata = {
            "session_id": session_id,
            "analyzer_id": analyzer_id,
            "customer_number": customer_number,
            "profile_name": profile_name,
            "notes": notes,
        }

        metadata_file = session_folder / "metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO sessions (
                session_id,
                analyzer_id,
                customer_number,
                profile_name,
                notes,
                data_path
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id)
            DO UPDATE SET
                analyzer_id = EXCLUDED.analyzer_id,
                customer_number = EXCLUDED.customer_number,
                profile_name = EXCLUDED.profile_name,
                notes = EXCLUDED.notes,
                data_path = EXCLUDED.data_path
            RETURNING *;
        """, (
            session_id,
            analyzer_id,
            customer_number,
            profile_name,
            notes,
            data_path
        ))

        session = cur.fetchone()

        cur.execute("""
            UPDATE analyzers
            SET
                current_session_id = %s,
                current_profile = %s,
                status = 'online',
                last_seen = CURRENT_TIMESTAMP
            WHERE analyzer_id = %s;
        """, (
            session_id,
            profile_name,
            analyzer_id
        ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "ok",
            "session": session,
            "folder_created": str(session_folder)
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/sessions/<session_id>/finish", methods=["POST"])
def finish_session(session_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE sessions
            SET
                status = 'finished',
                ended_at = CURRENT_TIMESTAMP
            WHERE session_id = %s
            RETURNING *;
        """, (session_id,))

        session = cur.fetchone()

        if not session:
            cur.close()
            conn.close()
            return jsonify({
                "status": "error",
                "error": "session not found"
            }), 404

        cur.execute("""
            UPDATE analyzers
            SET
                current_session_id = NULL,
                current_profile = NULL,
                last_seen = CURRENT_TIMESTAMP
            WHERE analyzer_id = %s;
        """, (session["analyzer_id"],))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "ok",
            "session": session
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/sessions/<session_id>/upload", methods=["POST"])
def upload_session_file(session_id):
    try:
        customer_number = request.form.get("customer_number")
        file = request.files.get("file")

        if not customer_number:
            return jsonify({
                "status": "error",
                "error": "customer_number is required"
            }), 400

        if not file:
            return jsonify({
                "status": "error",
                "error": "file is required"
            }), 400

        session_folder = get_session_folder(customer_number, session_id)
        session_folder.mkdir(parents=True, exist_ok=True)

        filename = secure_filename(file.filename)
        target_path = session_folder / filename
        file.save(target_path)

        return jsonify({
            "status": "ok",
            "message": "file uploaded successfully",
            "saved_to": str(target_path),
            "filename": filename
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/sessions/<session_id>/files", methods=["GET"])
def list_session_files(session_id):
    try:
        customer_number = request.args.get("customer_number")

        if not customer_number:
            return jsonify({
                "status": "error",
                "error": "customer_number is required"
            }), 400

        session_folder = get_session_folder(customer_number, session_id)

        if not session_folder.exists():
            return jsonify({
                "status": "error",
                "error": "session folder not found"
            }), 404

        files = []
        for item in session_folder.iterdir():
            if item.is_file():
                files.append({
                    "name": item.name,
                    "size_bytes": item.stat().st_size
                })

        return jsonify({
            "status": "ok",
            "session_id": session_id,
            "customer_number": customer_number,
            "files": files
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/history", methods=["GET"])
def history_page():
    try:
        customer_number = request.args.get("customer_number")

        conn = get_db_connection()
        cur = conn.cursor()

        if customer_number:
            cur.execute("""
                SELECT *
                FROM sessions
                WHERE customer_number = %s
                ORDER BY started_at DESC;
            """, (customer_number,))
        else:
            cur.execute("""
                SELECT *
                FROM sessions
                ORDER BY started_at DESC;
            """)

        sessions = cur.fetchall()
        cur.close()
        conn.close()

        return render_template(
            "history.html",
            sessions=sessions,
            customer_number=customer_number
        )
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/sessions/<session_id>/view", methods=["GET"])
def session_detail_page(session_id):
    try:
        customer_number = request.args.get("customer_number")

        if not customer_number:
            return jsonify({
                "status": "error",
                "error": "customer_number is required"
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM sessions
            WHERE session_id = %s AND customer_number = %s
            LIMIT 1;
        """, (session_id, customer_number))

        session = cur.fetchone()
        cur.close()
        conn.close()

        if not session:
            return jsonify({
                "status": "error",
                "error": "session not found"
            }), 404

        session_folder = get_session_folder(customer_number, session_id)
        files = []

        if session_folder.exists():
            for item in session_folder.iterdir():
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "size_bytes": item.stat().st_size
                    })

        return render_template(
            "session_detail.html",
            session=session,
            files=files
        )
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/live/view/<analyzer_id>", methods=["GET"])
def live_view_page(analyzer_id):
    return render_template("live_view.html", analyzer_id=analyzer_id)


@app.route("/live/state/<analyzer_id>", methods=["GET"])
def get_live_state(analyzer_id):
    return jsonify({
        "status": "ok",
        "analyzer_id": analyzer_id,
        "live_state": LIVE_STATE.get(analyzer_id)
    })


@app.route("/live/update", methods=["POST"])
def receive_live_update():
    try:
        data = request.get_json()

        analyzer_id = data.get("analyzer_id")
        if not analyzer_id:
            return jsonify({
                "status": "error",
                "error": "analyzer_id is required"
            }), 400

        LIVE_STATE[analyzer_id] = data

        socketio.emit("live_update", data, room=f"analyzer:{analyzer_id}")

        return jsonify({
            "status": "ok",
            "message": "live update received"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route("/live/test/<analyzer_id>", methods=["POST"])
def create_test_live_update(analyzer_id):
    try:
        payload = {
            "analyzer_id": analyzer_id,
            "session_id": request.args.get("session_id", "live-test-session"),
            "timestamp": request.args.get("timestamp", "test"),
            "profile_name": request.args.get("profile_name", "2.4GHz Full"),
            "noise_floor_dbm": float(request.args.get("noise_floor_dbm", "-96")),
            "peak_power_dbm": float(request.args.get("peak_power_dbm", "-54")),
            "verdict": request.args.get("verdict", "Moderate RF activity"),
            "running": request.args.get("running", "true").lower() == "true"
        }

        LIVE_STATE[analyzer_id] = payload

        socketio.emit("live_update", payload, room=f"analyzer:{analyzer_id}")

        return jsonify({
            "status": "ok",
            "message": "test live update emitted",
            "payload": payload
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@socketio.on("join_analyzer_room")
def handle_join_analyzer_room(data):
    analyzer_id = data.get("analyzer_id")
    if analyzer_id:
        join_room(f"analyzer:{analyzer_id}")
        if analyzer_id in LIVE_STATE:
            emit("live_update", LIVE_STATE[analyzer_id])


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)