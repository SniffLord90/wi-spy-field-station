import time

from server_bootstrap import bootstrap_server_integration

server_client, heartbeat_worker = bootstrap_server_integration()

print("Bootstrap actief. Wachten 20 seconden...")
time.sleep(20)

heartbeat_worker.stop()
print("Klaar.")