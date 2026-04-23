import socket
import time

sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 5006))  # ← PORT 5006 (different from transformer!)
sock.listen(1)

print("Waiting for Unity DG connection...")
conn, addr = sock.accept()
print("Unity DG Connected!")

start_time = time.time()

while True:
    elapsed = time.time() - start_time

    dg_id = "DG1"

    # First 30 seconds → DG STANDBY (not running)
    # After 30 seconds → DG RUNNING (working condition)
    if elapsed < 30:
        voltage  = 0
        current  = 0
        rpm      = 0
        fuel     = 100.0
        coolant  = 30.0
        status   = "STANDBY"
    else:
        voltage  = 415.0
        current  = 85.0
        rpm      = 1500
        fuel     = max(0, 100.0 - (elapsed - 30) * 0.3)
        coolant  = min(90.0, 30.0 + (elapsed - 30) * 0.5)
        status   = "RUNNING"

    data = f"{dg_id},{voltage},{current},{rpm},{fuel:.1f},{coolant:.1f},{status}"

    try:
        conn.send((data + "\n").encode())
        print(f"[{elapsed:.1f}s] Sent: {data}")
    except Exception as e:
        print(f"Error: {e}")
        break

    time.sleep(1)