import requests
import math

PROM_URL = "http://localhost:9090/api/v1/query"

# Thresholds
LATENCY_THRESHOLD = 0.5
DB_THRESHOLD = 0.3  # simulated

# Weights
wL, wE, wC, wM, wD = 0.3, 0.3, 0.15, 0.15, 0.1


def query(promql):
    res = requests.get(PROM_URL, params={"query": promql}).json()
    try:
        val = float(res['data']['result'][0]['value'][1])
        if math.isnan(val):
            return 0.0
        return val
    except:
        return 0.0


def get_latency():
    return query('rate(order_latency_seconds_sum[1m]) / rate(order_latency_seconds_count[1m])')


def get_error_rate():
    return 0.05  # simulated for now


def get_cpu():
    return 50  # simulated


def get_memory():
    return 60  # simulated


def get_db_latency():
    return 0.1  # simulated


def compute_score():
    latency = get_latency()
    error_rate = get_error_rate()
    cpu = get_cpu()
    memory = get_memory()
    db_latency = get_db_latency()

    SL = max(0, 1 - latency / LATENCY_THRESHOLD)
    SE = 1 - error_rate
    SC = 1 - cpu / 100
    SM = 1 - memory / 100
    SD = max(0, 1 - db_latency / DB_THRESHOLD)

    H = wL*SL + wE*SE + wC*SC + wM*SM + wD*SD

    return {
        "latency": latency,
        "H": H
    }


if __name__ == "__main__":
    result = compute_score()

    print("Latency:", result["latency"])
    print("Health Score:", round(result["H"], 3))

    if result["H"] >= 0.75:
        print("✅ DEPLOY")
    else:
        print("❌ ROLLBACK")