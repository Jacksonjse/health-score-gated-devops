from flask import Flask, jsonify, Response
import time
import random
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

REQUEST_COUNT = Counter('delivery_requests_total', 'Total requests')
LATENCY = Histogram('delivery_latency_seconds', 'Request latency')

@app.route("/")
def delivery():
    start = time.time()
    REQUEST_COUNT.inc()

    delay = random.uniform(0.3, 0.7)
    time.sleep(delay)

    LATENCY.observe(time.time() - start)
    return jsonify({"service": "delivery", "status": "ok"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)