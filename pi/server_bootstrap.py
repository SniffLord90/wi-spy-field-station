from server_client import ServerClient
from heartbeat_worker import HeartbeatWorker


server_client = ServerClient()
heartbeat_worker = HeartbeatWorker()


def bootstrap_server_integration():
    print("[server_bootstrap] Bootstrapping server integration...")

    register_result = server_client.register_analyzer()
    print("[server_bootstrap] register_analyzer result:", register_result)

    heartbeat_worker.update_state(
        current_session_id=None,
        current_profile=None,
        status="online",
    )
    heartbeat_worker.start()

    print("[server_bootstrap] Heartbeat worker started.")

    return server_client, heartbeat_worker