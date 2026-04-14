import requests
import subprocess
import math
import time

latest_data = {}

PROM_URL = "http://localhost:9090/api/v1/query"

LATENCY_THRESHOLD = 0.5
DB_THRESHOLD = 0.3
COOLDOWN = 60  
last_rollback_time = 0

wL, wE, wC, wM, wD = 0.3, 0.3, 0.15, 0.15, 0.1

services = ["order", "tracking", "delivery"]


def query(promql):
    try:
        res = requests.get(PROM_URL, params={"query": promql}).json()
        val = float(res['data']['result'][0]['value'][1])
        if math.isnan(val):
            return 0.0
        return val
    except:
        return 0.0


# 🔹 Latency per service
def get_latency(service):
    return query(f'rate({service}_latency_seconds_sum[1m]) / rate({service}_latency_seconds_count[1m])')


# 🔹 CPU & Memory per service
def get_k8s_metrics():
    data = {}

    try:
        output = subprocess.check_output(["kubectl", "top", "pods"]).decode()

        lines = output.strip().split("\n")[1:]  # skip header

        for line in lines:
            parts = line.split()
            pod_name = parts[0]
            cpu_raw = parts[1]
            mem_raw = parts[2]

            cpu = int(cpu_raw.replace("m", ""))
            mem = int(mem_raw.replace("Mi", ""))

            # 🔥 map pod → service correctly
            for svc in services:
                if pod_name.startswith(svc):
                    data[svc] = (cpu, mem)

    except Exception as e:
        print("Error reading metrics:", e)

    return data


# 🔹 Compute health per service
def compute_service_health(service, metrics):
    latency = get_latency(service)
    error_rate = 0.05
    db_latency = 0.1

    cpu, memory = metrics.get(service, (0, 0))

    SL = max(0, 1 - latency / LATENCY_THRESHOLD)
    SE = 1 - error_rate
    SC = 1 - min(cpu / 500, 1)
    SM = 1 - min(memory / 200, 1)
    SD = max(0, 1 - db_latency / DB_THRESHOLD)

    H = wL*SL + wE*SE + wC*SC + wM*SM + wD*SD

    return latency, cpu, memory, H





def main_loop():
    global last_rollback_time

    print("🔁 Multi-service health monitoring...\n")

    while True:
        metrics = get_k8s_metrics()
        health_scores = []

        print("====== SYSTEM STATUS ======")

        for svc in services:
            latency, cpu, mem, H = compute_service_health(svc, metrics)
            health_scores.append(H)

            print(f"\nService: {svc}")
            print(f"Latency: {latency:.3f}")
            print(f"CPU: {cpu}m | Memory: {mem}Mi")
            print(f"Health: {H:.3f}")

            # ✅ FIXED: correct placement
            latest_data[svc] = {
                "latency": latency,
                "cpu": cpu,
                "memory": mem,
                "health": H
            }

        H_total = min(health_scores)

        print("\n---------------------------")
        print(f"System Health (min): {H_total:.3f}")

        latest_data["system_health"] = H_total

        current_time = time.time()

        if H_total < 0.75:
            if current_time - last_rollback_time < COOLDOWN:
                print("⏳ In cooldown period — skipping rollback")
            else:
                print("❌ SYSTEM UNHEALTHY → Targeted rollback")

                for i, svc in enumerate(services):
                    if health_scores[i] < 0.75:
                        print(f"🔁 Rolling back {svc}")

                        subprocess.run(
                            ["kubectl", "rollout", "undo", f"deployment/{svc}"]
                        )

                last_rollback_time = current_time
        else:
            print("✅ SYSTEM HEALTHY")

        print("===========================\n")

        time.sleep(5)


if __name__ == "__main__":
    main_loop()