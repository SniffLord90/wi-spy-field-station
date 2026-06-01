from pathlib import Path
from typing import Optional

import requests

from config.settings import (
    SERVER_ENABLED,
    SERVER_BASE_URL,
    ANALYZER_ID,
    ANALYZER_NAME,
    ANALYZER_LOCATION,
    SERVER_TIMEOUT_SECONDS,
)


class ServerClient:
    def __init__(self) -> None:
        self.enabled = SERVER_ENABLED
        self.base_url = SERVER_BASE_URL.rstrip("/")
        self.analyzer_id = ANALYZER_ID
        self.analyzer_name = ANALYZER_NAME
        self.analyzer_location = ANALYZER_LOCATION
        self.timeout = SERVER_TIMEOUT_SECONDS

    def _post_json(self, path: str, payload: dict) -> Optional[dict]:
        if not self.enabled:
            return None

        url = f"{self.base_url}{path}"

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            print(f"[server_client] POST {url} failed: {exc}")
            return None

    def register_analyzer(self) -> Optional[dict]:
        payload = {
            "analyzer_id": self.analyzer_id,
            "name": self.analyzer_name,
            "location": self.analyzer_location,
            "status": "online",
        }
        return self._post_json("/analyzers", payload)

    def send_heartbeat(
        self,
        current_session_id: Optional[str] = None,
        current_profile: Optional[str] = None,
        status: str = "online",
    ) -> Optional[dict]:
        payload = {
            "analyzer_id": self.analyzer_id,
            "status": status,
            "current_session_id": current_session_id,
            "current_profile": current_profile,
        }
        return self._post_json("/analyzers/heartbeat", payload)

    def start_remote_session(
        self,
        session_id: str,
        customer_number: str,
        profile_name: str,
        notes: str = "",
    ) -> Optional[dict]:
        payload = {
            "session_id": session_id,
            "analyzer_id": self.analyzer_id,
            "customer_number": customer_number,
            "profile_name": profile_name,
            "notes": notes,
        }
        return self._post_json("/sessions", payload)

    def send_live_update(self, payload: dict) -> Optional[dict]:
        if not self.enabled:
            return None

        payload = dict(payload)
        payload["analyzer_id"] = self.analyzer_id

        return self._post_json("/live/update", payload)

    def finish_remote_session(self, session_id: str) -> Optional[dict]:
        if not self.enabled:
            return None

        url = f"{self.base_url}/sessions/{session_id}/finish"

        try:
            response = requests.post(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            print(f"[server_client] POST {url} failed: {exc}")
            return None

    def upload_file(
        self,
        session_id: str,
        customer_number: str,
        filepath: str,
    ) -> Optional[dict]:
        if not self.enabled:
            return None

        path = Path(filepath)
        if not path.exists():
            print(f"[server_client] upload_file: file does not exist: {filepath}")
            return None

        url = f"{self.base_url}/sessions/{session_id}/upload"

        try:
            with path.open("rb") as handle:
                files = {
                    "file": (path.name, handle),
                }
                data = {
                    "customer_number": customer_number,
                }

                response = requests.post(
                    url,
                    data=data,
                    files=files,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            print(f"[server_client] POST {url} failed: {exc}")
            return None

    def upload_session_artifacts(
        self,
        session_id: str,
        customer_number: str,
        session_dir: str,
    ) -> dict:
        result = {
            "ok": True,
            "session_id": session_id,
            "customer_number": customer_number,
            "session_dir": session_dir,
            "files": {},
        }

        session_path = Path(session_dir)

        files_to_upload = [
            "metadata.json",
            "sweeps.jsonl",
            "summary.json",
        ]

        for filename in files_to_upload:
            filepath = session_path / filename

            if not filepath.exists():
                result["ok"] = False
                result["files"][filename] = {
                    "ok": False,
                    "reason": "missing_local_file",
                    "path": str(filepath),
                }
                continue

            upload_result = self.upload_file(
                session_id=session_id,
                customer_number=customer_number,
                filepath=str(filepath),
            )

            if upload_result and upload_result.get("status") == "ok":
                result["files"][filename] = {
                    "ok": True,
                    "response": upload_result,
                }
            else:
                result["ok"] = False
                result["files"][filename] = {
                    "ok": False,
                    "response": upload_result,
                }

        return result