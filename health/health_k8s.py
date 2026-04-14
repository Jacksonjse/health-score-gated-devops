import requests
import subprocess
import math
import time

PROM_URL = "http://localhost:9090/api/v1/query"

LATENCY_THRESHOLD = 0.5
DB_THRESHOLD = 0.3

wL, wE, wC, wM, wD = 0.3, 0.3, 0.15, 0.15, 0.1


def query(promql):
    try:
        res = requests.get(PROM_URL, params={"query": promql}).json()
        val = float(res['data']['result'][0]['value'][1])
        if math.isnan(val):
            return 0.0
        return val
    except:
        return 0.0


def get_latency():
    return query('rate(order_latency_seconds_sum[1m]) / rate(order_latency_seconds_count[1m])')


# 🔥 NEW: Get CPU & Memory from Kubernetes
def get_k8s_metrics():
    try:
        output = subprocess.check_output(["kubectl", "top", "pods"]).decode()

        cpu = 0
        memory = 0

        for line in output.split("\n"):
            if "order" in line:
                parts = line.split()
                cpu_raw = parts[1]     # e.g., 120m
                mem_raw = parts[2]     # e.g., 80Mi

                cpu = int(cpu_raw.replace("m", ""))
                memory = int(mem_raw.replace("Mi", ""))

        return cpu, memory

    except:
        return 0, 0


def compute_score():
    latency = get_latency()
    error_rate = 0.05

    cpu, memory = get_k8s_metrics()

    db_latency = 0.1

    # Normalize CPU (assuming 500m max)
    SC = 1 - min(cpu / 500, 1)

    # Normalize Memory (assuming 200Mi max)
    SM = 1 - min(memory / 200, 1)

    SL = max(0, 1 - latency / LATENCY_THRESHOLD)
    SE = 1 - error_rate
    SD = max(0, 1 - db_latency / DB_THRESHOLD)

    H = wL*SL + wE*SE + wC*SC + wM*SM + wD*SD

    return latency, cpu, memory, H


def rollout_restart():
    subprocess.run(["kubectl", "rollout", "restart", "deployment/order"])


def rollback():
    subprocess.run(["kubectl", "rollout", "undo", "deployment/order"])


if __name__ == "__main__":
    latency, cpu, memory, score = compute_score()

    print(f"Latency: {latency:.3f}")
    print(f"CPU: {cpu}m")
    print(f"Memory: {memory}Mi")
    print(f"Health Score: {score:.3f}")

    if score >= 0.75:
        print("✅ HEALTHY")
    else:
        print("❌ UNHEALTHY → rollback")
        rollback()