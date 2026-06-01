import threading
import time
from typing import Optional

from config.settings import HEARTBEAT_INTERVAL_SECONDS
from server_client import ServerClient


class HeartbeatWorker:
    def __init__(self) -> None:
        self.client = ServerClient()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.current_session_id: Optional[str] = None
        self.current_profile: Optional[str] = None
        self.status: str = "online"

    def update_state(
        self,
        current_session_id: Optional[str] = None,
        current_profile: Optional[str] = None,
        status: str = "online",
    ) -> None:
        self.current_session_id = current_session_id
        self.current_profile = current_profile
        self.status = status

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            result = self.client.send_heartbeat(
                current_session_id=self.current_session_id,
                current_profile=self.current_profile,
                status=self.status,
            )
            print("[heartbeat_worker] heartbeat result:", result)
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("[heartbeat_worker] started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        print("[heartbeat_worker] stopped")