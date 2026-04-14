#!/bin/bash

echo "🚀 Starting Health-Score-Gated System..."

# -------------------------------
# STEP 0: Get TAG input
# -------------------------------
TAG=$1

if [ -z "$TAG" ]; then
  echo "❌ Usage: ./start_system.sh <TAG>"
  exit 1
fi

IMAGE_PREFIX="jksonjse/miniproject"

# -------------------------------
# STEP 1: Start Minikube
# -------------------------------
echo "🔹 Starting Minikube..."
minikube start

# -------------------------------
# STEP 2: Enable Metrics Server
# -------------------------------
echo "🔹 Enabling Metrics Server..."
minikube addons enable metrics-server
sleep 20

# -------------------------------
# STEP 3: Deploy base K8s configs
# -------------------------------
echo "🔹 Applying Kubernetes configs..."
kubectl apply -f k8s/

# -------------------------------
# STEP 4: Ensure rollout history
# -------------------------------
echo "🔹 Creating rollout history..."
kubectl rollout restart deployment/order
kubectl rollout restart deployment/tracking
kubectl rollout restart deployment/delivery

# -------------------------------
# STEP 5: Wait for base pods
# -------------------------------
echo "⏳ Waiting for base deployments..."
kubectl wait --for=condition=available deployment/order --timeout=120s
kubectl wait --for=condition=available deployment/tracking --timeout=120s
kubectl wait --for=condition=available deployment/delivery --timeout=120s

# -------------------------------
# STEP 6: Deploy NEW VERSION
# -------------------------------
echo "🚀 Deploying version: $TAG"

kubectl set image deployment/order order=$IMAGE_PREFIX-order:$TAG
kubectl set image deployment/tracking tracking=$IMAGE_PREFIX-tracking:$TAG
kubectl set image deployment/delivery delivery=$IMAGE_PREFIX-delivery:$TAG

echo "⏳ Waiting for rollout..."
kubectl rollout status deployment/order
kubectl rollout status deployment/tracking
kubectl rollout status deployment/delivery

# -------------------------------
# STEP 7: Start Prometheus
# -------------------------------
echo "🔹 Starting Prometheus..."
kubectl apply -f k8s/prometheus-deployment.yml
kubectl apply -f k8s/prometheus-service.yml

sleep 15

# -------------------------------
# STEP 8: Port-forward Prometheus
# -------------------------------
echo "🔹 Starting Prometheus port-forward..."
kubectl port-forward svc/prometheus-service 9090:9090 > /dev/null 2>&1 &

# -------------------------------
# STEP 9: Show system status
# -------------------------------
echo "📊 Current Pods:"
kubectl get pods

echo "📊 Metrics:"
kubectl top pods || echo "⚠️ Metrics not ready yet"

# -------------------------------
# STEP 10: Start Health Monitor
# -------------------------------
echo "🔁 Starting Health Monitoring..."
cd health
python3 health_multi.py
