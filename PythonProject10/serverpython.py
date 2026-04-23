import socket
import threading
import time
from flask import Flask, jsonify
from flask_cors import CORS

app  = Flask(__name__)
CORS(app)

unity_conn  = None
unity_lock  = threading.Lock()
latest_data = {
    "T2":  {"voltage":11.5,"current":1.2,
             "power":13.8,"temp":45,"status":"SAFE"},
    "DG1": {"voltage":0,"rpm":0,
             "fuel":100,"coolant":30,"status":"STANDBY"}
}

def send_to_unity(command):
    global unity_conn
    with unity_lock:
        if unity_conn:
            try:
                unity_conn.send((command+"\n").encode())
                print(f"[Flask] → Unity: {command}")
                return True
            except:
                return False
    return False

@app.route('/api/status')
def get_status():
    return jsonify(latest_data)

@app.route('/api/focus/<eid>')
def focus(eid):
    ok = send_to_unity(f"FOCUS:{eid}")
    return jsonify({"status":"sent" if ok else "error",
                    "equipment":eid})

@app.route('/api/focus/ALL')
def focus_all():
    send_to_unity("FOCUS:ALL")
    return jsonify({"status":"sent"})

def unity_server():
    global unity_conn, latest_data
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 5005))
    sock.listen(1)
    print("[Server] Waiting for Unity on port 5005...")

    while True:
        try:
            conn, addr = sock.accept()
            print(f"[Server] Unity Connected!")
            with unity_lock:
                unity_conn = conn

            start = time.time()
            while True:
                elapsed = time.time() - start
                temp    = 45.0 if elapsed < 30 else 95.0
                status  = "SAFE" if elapsed < 30 else "CRITICAL"

                dg_on      = elapsed > 35
                dg_voltage = 415  if dg_on else 0
                dg_rpm     = 1500 if dg_on else 0
                dg_fuel    = max(0, 100 - elapsed * 0.3)
                dg_coolant = min(90, 30 + (elapsed-35)*0.3) if dg_on else 30
                dg_status  = "RUNNING" if dg_on else "STANDBY"

                tr_data = f"T2,F2,11.5,1.2,13.8,{temp},{status}"
                dg_data = f"DG1,{dg_voltage},0,{dg_rpm},{dg_fuel:.1f},{dg_coolant:.1f},{dg_status}"

                latest_data["T2"]  = {"voltage":11.5,"current":1.2,
                                       "power":13.8,"temp":temp,"status":status}
                latest_data["DG1"] = {"voltage":dg_voltage,"rpm":dg_rpm,
                                       "fuel":round(dg_fuel,1),
                                       "coolant":round(dg_coolant,1),
                                       "status":dg_status}
                try:
                    conn.send((tr_data+"\n").encode())
                    conn.send((dg_data+"\n").encode())
                    print(f"[{elapsed:.0f}s] TR:{status} | DG:{dg_status}")
                except:
                    break
                time.sleep(1)
        except Exception as e:
            print(f"Error: {e}")
        finally:
            with unity_lock:
                unity_conn = None
            print("[Server] Unity disconnected. Waiting...")

t = threading.Thread(target=unity_server)
t.daemon = True
t.start()

print("[Flask] Dashboard server on http://127.0.0.1:8080")
print("[Flask] Open dashboard.html in browser!")
app.run(host='0.0.0.0', port=8080, debug=False)