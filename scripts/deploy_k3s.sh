#!/bin/bash
set -e

# Cloudarr K3s Deployment Script
# This script builds the Docker image, distributes it to all k3s nodes, and deploys

# Configuration - UPDATE THESE
K3S_NODES=(
  "latis@192.168.30.11"
  "latis@192.168.30.12"
)
IMAGE_NAME="cloudarr:latest"
IMAGE_FILE="/tmp/cloudarr-latest.tar"
NAMESPACE="media-system"
YAML_FILE="cloudarr.k8s.yaml"

echo "=== Cloudarr K3s Deployment ==="
echo ""

# Step 1: Build image
echo "[1/5] Building Docker image..."
docker build --no-cache -t "${IMAGE_NAME}" .
echo "✓ Image built"
echo ""

# Step 2: Export image
echo "[2/5] Exporting image..."
docker save "${IMAGE_NAME}" -o "${IMAGE_FILE}"
echo "✓ Image exported to ${IMAGE_FILE}"
echo ""

# Step 3: Copy to all nodes and import
echo "[3/5] Distributing image to k3s nodes..."
for node in "${K3S_NODES[@]}"; do
  echo "  Preparing host paths on ${node}..."
  ssh -t "${node}" "sudo mkdir -p /srv/media/config/cloudarr /srv/media/mnt/debrid/imports /srv/media/data && sudo chown -R 1000:1000 /srv/media/config/cloudarr /srv/media/mnt/debrid /srv/media/data"
  echo "  Copying to ${node}..."
  scp "${IMAGE_FILE}" "${node}:/tmp/"
  echo "  Importing on ${node}..."
  ssh -t "${node}" "sudo k3s ctr images import ${IMAGE_FILE}"
  echo "  ✓ ${node} done"
done
echo "✓ Image distributed and imported"
echo ""

# Step 4: Verify image on all nodes
echo "[4/5] Verifying image on all nodes..."
ssh -t "${K3S_NODES[0]}" "sudo k3s ctr images ls | grep cloudarr"
echo "✓ Image verified"
echo ""

# Step 5: Deploy to Kubernetes
echo "[5/5] Deploying to Kubernetes..."
kubectl apply -f "${YAML_FILE}"
echo "✓ Deployment applied"
echo ""

# Wait for rollout
echo "Waiting for deployments to be ready..."
kubectl rollout status deployment/cloudarr-api -n "${NAMESPACE}" --timeout=2m || true
kubectl rollout status deployment/cloudarr-worker -n "${NAMESPACE}" --timeout=2m || true
echo ""

# Show status
echo "=== Final Status ==="
kubectl get pods -n "${NAMESPACE}" -l app=cloudarr
echo ""
echo "=== Pod Details ==="
kubectl describe pods -n "${NAMESPACE}" -l app=cloudarr | grep -A 5 "Events:\|Image:"
echo ""

echo "✓ Deployment complete!"
echo ""
echo "Access dashboard: http://192.168.30.59:8080"
echo "Check logs: kubectl logs -n ${NAMESPACE} -f deployment/cloudarr-api"
