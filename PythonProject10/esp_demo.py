import socket
import time

sock = socket.socket()
sock.bind(("127.0.0.1", 5005))
sock.listen(1)

print("Waiting for Unity...")
conn, addr = sock.accept()
print("Unity Connected!")

while True:
    # Demo values (you can change these later)
    transformer_id = "T1"
    feeder_id = "F1"

    voltage = 11.5
    current = 1.2
    power = 13.8
    temperature = 45.0   # Transformer temperature

    # Create data string
    data = f"{transformer_id},{feeder_id},{voltage},{current},{power},{temperature}"

    conn.send((data + "\n").encode())
    print("Sent:", data)

    time.sleep(1)
    