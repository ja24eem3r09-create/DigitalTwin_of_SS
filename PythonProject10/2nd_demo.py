import socket
import time

sock = socket.socket()
sock.bind(("127.0.0.1", 5005))
sock.listen(1)

print("Waiting for Unity...")
conn, addr = sock.accept()
print("Unity Connected!")

start_time = time.time()

while True:
    elapsed = time.time() - start_time 

    transformer_id = "T2"   # ← Change to T2 for your NEW transformer
    feeder_id = "F2"
    voltage = 11.5
    current = 1.2
    power = 13.8
    # For first 30 seconds → SAFE temperature (green)
    # After 30 seconds → CRITICAL temperature (red)
    if elapsed < 30:
        temperature = 45.0   # Safe: below threshold
        status = "SAFE"
    else:
        temperature = 95.0   # Critical: above threshold (threshold = 85°C)
        status = "CRITICAL"

    data = f"{transformer_id},{feeder_id},{voltage},{current},{power},{temperature},{status}"

    try:
        conn.send((data + "\n").encode())
        print(f"[{elapsed:.1f}s] Sent: {data}")
    except:
        print("Connection lost.")
        break

    time.sleep(1)