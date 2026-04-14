"""
Health-Score-Gated CI/CD Dashboard
Flask backend — serves /data endpoint and dashboard UI.

Run with:
    cd dashboard
    python app.py

The health engine loop is started in a background thread.
If Kubernetes / Prometheus are unavailable, mock data is served
so the dashboard UI can still be developed / demoed.
"""

from flask import Flask, render_template, jsonify
import threading
import time
import random
import math
import os

app = Flask(__name__)

# ─────────────────────────────────────────────
# Shared state (written by health loop, read by /data)
# ─────────────────────────────────────────────
latest_data: dict = {
    "services": {
        "order":    {"latency": 0.0, "cpu": 0, "memory": 0, "health": 0.0},
        "tracking": {"latency": 0.0, "cpu": 0, "memory": 0, "health": 0.0},
        "delivery": {"latency": 0.0, "cpu": 0, "memory": 0, "health": 0.0},
    },
    "system_health": 0.0,
    "last_update":   "—",
    "last_event":    "System starting…",
    "last_rollback": None,
    "events": [],          # ring buffer, last 20 events
    "rollback_count": 0,
}
_lock = threading.Lock()


# ─────────────────────────────────────────────
# Event logger (thread-safe)
# ─────────────────────────────────────────────
def log_event(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    with _lock:
        latest_data["last_event"] = entry
        latest_data["events"].append(entry)
        if len(latest_data["events"]) > 20:
            latest_data["events"].pop(0)


# ─────────────────────────────────────────────
# Try to import the real health engine;
# fall back to mock loop so the UI always works.
# ─────────────────────────────────────────────
USE_MOCK = os.environ.get("MOCK_DATA", "false").lower() in ("1", "true", "yes")

if not USE_MOCK:
    try:
        # The real health engine lives one level up in health/health_multi.py
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from health import health_multi as _hm
        USE_MOCK = False
        print("✅  Real health engine loaded.")
    except ImportError:
        USE_MOCK = True
        print("⚠️  health_multi not found — using mock data loop.")
else:
    print("ℹ️  MOCK_DATA=true — using simulated data loop.")


# ─────────────────────────────────────────────
# REAL health loop wrapper
# ─────────────────────────────────────────────
def _real_health_loop() -> None:
    """Wraps health_multi.main_loop and mirrors its data into latest_data."""
    SERVICES = ["order", "tracking", "delivery"]
    LATENCY_THRESHOLD = 0.5
    DB_THRESHOLD = 0.3
    COOLDOWN = 60
    wL, wE, wC, wM, wD = 0.30, 0.30, 0.15, 0.15, 0.10
    last_rollback = 0

    import requests, subprocess

    def _query(promql):
        try:
            res = requests.get("http://localhost:9090/api/v1/query",
                               params={"query": promql}, timeout=2).json()
            val = float(res["data"]["result"][0]["value"][1])
            return 0.0 if math.isnan(val) else val
        except Exception:
            return 0.0

    def _k8s_metrics():
        data = {}
        try:
            out = subprocess.check_output(["kubectl", "top", "pods"],
                                          timeout=5).decode()
            for line in out.strip().split("\n")[1:]:
                parts = line.split()
                pod, cpu_raw, mem_raw = parts[0], parts[1], parts[2]
                cpu = int(cpu_raw.replace("m", ""))
                mem = int(mem_raw.replace("Mi", ""))
                for svc in SERVICES:
                    if pod.startswith(svc):
                        data[svc] = (cpu, mem)
        except Exception as exc:
            log_event(f"⚠️ kubectl error: {exc}")
        return data

    def _score(svc, metrics):
        latency    = _query(f"rate({svc}_latency_seconds_sum[1m]) / "
                            f"rate({svc}_latency_seconds_count[1m])")
        cpu, memory = metrics.get(svc, (0, 0))
        error_rate  = 0.05
        db_latency  = 0.10
        SL = max(0, 1 - latency  / LATENCY_THRESHOLD)
        SE = 1 - error_rate
        SC = 1 - min(cpu    / 500,  1)
        SM = 1 - min(memory / 200,  1)
        SD = max(0, 1 - db_latency / DB_THRESHOLD)
        H  = wL*SL + wE*SE + wC*SC + wM*SM + wD*SD
        return latency, cpu, memory, H

    log_event("🚀 Real health engine started")

    while True:
        metrics = _k8s_metrics()
        scores  = []
        svc_snapshot = {}

        for svc in SERVICES:
            lat, cpu, mem, H = _score(svc, metrics)
            scores.append(H)
            svc_snapshot[svc] = {"latency": lat, "cpu": cpu,
                                  "memory": mem, "health": H}

        H_total = min(scores)
        now     = time.time()

        with _lock:
            latest_data["services"]     = svc_snapshot
            latest_data["system_health"] = H_total
            latest_data["last_update"]  = time.strftime("%Y-%m-%d %H:%M:%S")

        if H_total < 0.75:
            if now - last_rollback < COOLDOWN:
                log_event("⏳ System degraded — cooldown active, rollback skipped")
            else:
                bad = [SERVICES[i] for i, h in enumerate(scores) if h < 0.75]
                for svc in bad:
                    subprocess.run(
                        ["kubectl", "rollout", "undo", f"deployment/{svc}"],
                        capture_output=True)
                last_rollback = now
                with _lock:
                    latest_data["last_rollback"]  = time.strftime("%Y-%m-%d %H:%M:%S")
                    latest_data["rollback_count"] += 1
                log_event(f"🔁 Rollback triggered for: {', '.join(bad)}")
        else:
            log_event("✅ All services healthy")

        time.sleep(5)


# ─────────────────────────────────────────────
# MOCK health loop (no Kubernetes required)
# ─────────────────────────────────────────────
def _mock_health_loop() -> None:
    """
    Simulates realistic fluctuating metrics so the dashboard can be
    demonstrated without a live Kubernetes cluster.
    """
    SERVICES = ["order", "tracking", "delivery"]

    # Each service has independent state that drifts over time
    state = {
        svc: {
            "latency": random.uniform(0.05, 0.15),
            "cpu":     random.randint(40, 120),
            "memory":  random.randint(60, 130),
            "drift_l": random.uniform(-0.005, 0.005),
            "drift_c": random.randint(-2, 2),
            "drift_m": random.randint(-1, 1),
        }
        for svc in SERVICES
    }

    LATENCY_THRESHOLD = 0.5
    wL, wE, wC, wM, wD = 0.30, 0.30, 0.15, 0.15, 0.10
    last_rollback  = 0
    COOLDOWN       = 30
    tick           = 0
    incident_until = 0   # simulate a degradation window

    log_event("🚀 Mock health engine started (demo mode)")

    while True:
        tick += 1
        now = time.time()

        # Every ~60 s inject a brief degradation on a random service
        if tick % 30 == 0:
            victim = random.choice(SERVICES)
            incident_until = tick + random.randint(5, 12)
            log_event(f"⚡ Simulated spike on {victim} service")
            state[victim]["latency"] += random.uniform(0.25, 0.45)
            state[victim]["cpu"]     += random.randint(150, 250)

        svc_snapshot = {}
        scores = []

        for svc in SERVICES:
            s = state[svc]

            # Random walk
            s["latency"] = max(0.01, s["latency"] + s["drift_l"]
                               + random.gauss(0, 0.003))
            s["cpu"]     = max(5, min(490, s["cpu"] + s["drift_c"]
                               + random.randint(-3, 3)))
            s["memory"]  = max(20, min(195, s["memory"] + s["drift_m"]
                               + random.randint(-2, 2)))

            # Slowly decay back to normal
            if tick > incident_until:
                s["latency"] = s["latency"] * 0.92 + 0.08 * random.uniform(0.05, 0.12)
                s["cpu"]     = int(s["cpu"]    * 0.93 + 0.07 * random.randint(50, 100))

            lat = s["latency"]
            cpu = s["cpu"]
            mem = s["memory"]

            SL = max(0, 1 - lat / LATENCY_THRESHOLD)
            SE = 1 - 0.05
            SC = 1 - min(cpu / 500, 1)
            SM = 1 - min(mem / 200, 1)
            SD = max(0, 1 - 0.10 / 0.3)
            H  = wL*SL + wE*SE + wC*SC + wM*SM + wD*SD

            scores.append(H)
            svc_snapshot[svc] = {
                "latency": round(lat, 4),
                "cpu":     cpu,
                "memory":  mem,
                "health":  round(H, 4),
            }

        H_total = min(scores)

        with _lock:
            latest_data["services"]      = svc_snapshot
            latest_data["system_health"] = round(H_total, 4)
            latest_data["last_update"]   = time.strftime("%Y-%m-%d %H:%M:%S")

        if H_total < 0.75:
            if now - last_rollback < COOLDOWN:
                log_event("⏳ System degraded — cooldown active, rollback skipped")
            else:
                bad = [SERVICES[i] for i, h in enumerate(scores) if h < 0.75]
                last_rollback = now
                with _lock:
                    latest_data["last_rollback"]  = time.strftime("%Y-%m-%d %H:%M:%S")
                    latest_data["rollback_count"] += 1
                log_event(f"🔁 Auto-rollback triggered → {', '.join(bad)}")
        else:
            if tick % 6 == 0:          # log a heartbeat every ~30 s
                log_event("✅ All services nominal")

        time.sleep(5)


# ─────────────────────────────────────────────
# Start background thread
# ─────────────────────────────────────────────
_loop_fn = _mock_health_loop if USE_MOCK else _real_health_loop
threading.Thread(target=_loop_fn, daemon=True, name="health-loop").start()


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/data")
def data():
    with _lock:
        payload = dict(latest_data)           # shallow copy is fine for JSON
    return jsonify(payload)


@app.route("/health")
def health_check():
    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5005))
    print(f"\n🖥️  Dashboard → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
