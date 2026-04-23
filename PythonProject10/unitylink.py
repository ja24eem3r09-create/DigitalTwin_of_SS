import socket
import threading
import time
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Store connections globally
unity_conn = None
unity_lock = threading.Lock()

# Latest data storage
latest_data = {
    "T2":  {"voltage": 11.5, "current": 1.2,
             "temp": 45, "status": "SAFE"},
    "DG1": {"voltage": 415, "rpm": 1500,
             "fuel": 100, "status": "STANDBY"}
}

# ── Send command to Unity ──────────────────────────────────────
def send_to_unity(command):
    global unity_conn
    with unity_lock:
        if unity_conn:
            try:
                unity_conn.send((command + "\n").encode())
                print(f"[Flask] Sent to Unity: {command}")
                return True
            except Exception as e:
                print(f"[Flask] Unity send error: {e}")
                return False
    return False

# ── Flask API Routes ───────────────────────────────────────────

@app.route('/api/status')
def get_status():
    return jsonify(latest_data)

@app.route('/api/focus/<equipment_id>')
def focus_equipment(equipment_id):
    success = send_to_unity(f"FOCUS:{equipment_id}")
    if success:
        return jsonify({
            "status": "sent",
            "equipment": equipment_id,
            "message": f"Camera moving to {equipment_id}"
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Unity not connected!"
        }), 500

# ── Unity Socket Server ────────────────────────────────────────
def unity_server():
    global unity_conn, latest_data

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 5005))
    sock.listen(1)
    print("[Unity Server] Waiting for Unity on port 5005...")

    while True:
        try:
            conn, addr = sock.accept()
            print(f"[Unity Server] Unity Connected from {addr}!")

            with unity_lock:
                unity_conn = conn

            start_time = time.time()

            while True:
                elapsed = time.time() - start_time

                # Transformer data
                temp   = 45.0 if elapsed < 30 else 95.0
                status = "SAFE" if elapsed < 30 else "CRITICAL"

                tr_data = f"T2,F2,11.5,1.2,13.8,{temp},{status}"

                # DG data
                dg_running = elapsed > 35
                dg_voltage = 415 if dg_running else 0
                dg_rpm     = 1500 if dg_running else 0
                dg_fuel    = max(0, 100 - elapsed * 0.3)
                dg_coolant = 75.0
                dg_status  = "RUNNING" if dg_running else "STANDBY"

                dg_data = f"DG1,{dg_voltage},{0},{dg_rpm},{dg_fuel:.1f},{dg_coolant},{dg_status}"

                # Update latest data for dashboard
                latest_data["T2"] = {
                    "voltage": 11.5,
                    "current": 1.2,
                    "temp":    temp,
                    "status":  status
                }
                latest_data["DG1"] = {
                    "voltage": dg_voltage,
                    "rpm":     dg_rpm,
                    "fuel":    round(dg_fuel, 1),
                    "status":  dg_status
                }

                try:
                    conn.send((tr_data + "\n").encode())
                    conn.send((dg_data + "\n").encode())
                    print(f"[{elapsed:.0f}s] TR:{status} DG:{dg_status}")
                except Exception as e:
                    print(f"[Unity Server] Send error: {e}")
                    break

                time.sleep(1)

        except Exception as e:
            print(f"[Unity Server] Error: {e}")
        finally:
            with unity_lock:
                unity_conn = None
            print("[Unity Server] Unity disconnected. Waiting again...")

# Start Unity server thread
unity_thread = threading.Thread(target=unity_server)
unity_thread.daemon = True
unity_thread.start()

# Start Flask
print("[Flask] Dashboard server starting on port 8080...")
print("[Flask] Open dashboard.html in browser!")
app.run(host='0.0.0.0', port=8080, debug=False)