#!/bin/bash

TAG=$1

if [ -z "$TAG" ]; then
  echo "❌ Usage: ./deploy.sh <tag>"
  exit 1
fi

IMAGE_PREFIX="jksonjse/miniproject"

echo "🚀 Deploying version: $TAG"

kubectl set image deployment/order order=$IMAGE_PREFIX-order:$TAG
kubectl set image deployment/tracking tracking=$IMAGE_PREFIX-tracking:$TAG
kubectl set image deployment/delivery delivery=$IMAGE_PREFIX-delivery:$TAG

echo "⏳ Waiting for rollout..."

kubectl rollout status deployment/order
kubectl rollout status deployment/tracking
kubectl rollout status deployment/delivery

echo "✅ Deployment complete"