# Kubernetes Deployment Guide

This guide covers deploying Cloudarr as Docker containers in Kubernetes alongside Sonarr.

## Prerequisites

- Kubernetes cluster running on the same host as Sonarr
- `kubectl` configured to access the cluster
- Docker installed for building images

## Step 1: Build Docker Image

Build the Cloudarr Docker image on your host machine:

```bash
cd /path/to/Cloudarr
docker build -t cloudarr:latest .
```

If using a private registry, tag and push:

```bash
docker tag cloudarr:latest your-registry.com/cloudarr:latest
docker push your-registry.com/cloudarr:latest
```

## Step 2: Configure Secrets

Before deploying, update the `cloudarr.k8s.yaml` file with your Real-Debrid credentials:

```bash
kubectl edit secret cloudarr-secrets -n media-system
```

Or directly modify in the YAML:

```yaml
stringData:
  CLOUDARR_SECRET_KEY: "<generate-random-secret>"
  CLOUDARR_ADMIN_PASSWORD: "<choose-password>"
  CLOUDARR_QBIT_PASSWORD: "sonarr-pass"
  CLOUDARR_REALDEBRID_API_TOKEN: "<your-real-debrid-token>"
  CLOUDARR_WEBDAV_USERNAME: "<your-real-debrid-username>"
  CLOUDARR_WEBDAV_PASSWORD: "<your-real-debrid-password>"
```

Generate a random secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Step 3: Deploy to Kubernetes

Apply the deployment:

```bash
kubectl apply -f cloudarr.k8s.yaml
```

Verify pods are running:

```bash
kubectl get pods -n media-system
kubectl logs -n media-system deployment/cloudarr-api
kubectl logs -n media-system deployment/cloudarr-worker
```

## Step 4: Verify Connectivity with Sonarr

Once deployed, Sonarr can access Cloudarr via the service name `cloudarr.media-system:8080` (or `cloudarr:8080` if in same namespace).

Add Cloudarr as Download Client in Sonarr:

1. Go to Settings → Download Clients
2. Add qBittorrent client
3. Host: `cloudarr.media-system` (or `cloudarr` if both in same namespace)
4. Port: `8080`
5. Username: `sonarr`
6. Password: `sonarr-pass` (or what you set in `CLOUDARR_QBIT_PASSWORD`)
7. Require Authentication: ✓

## Volume Mounts

The deployment uses hostPath volumes that must exist on the host:

```
/srv/media/
├── config/
│   └── cloudarr/          # Config and SQLite DB
├── data/                  # Media library
└── mnt/
    └── debrid/
        └── imports/       # Symlink staging directory
```

Create these on your host:

```bash
sudo mkdir -p /srv/media/{config/cloudarr,data,mnt/debrid/imports}
sudo chown -R 1000:1000 /srv/media/
```

## Updating ConfigMap

To update configuration without rebuilding:

```bash
kubectl edit configmap cloudarr-config -n media-system
```

Changes take effect after pod restart:

```bash
kubectl rollout restart deployment/cloudarr-api -n media-system
kubectl rollout restart deployment/cloudarr-worker -n media-system
```

## Checking Health

Access the Cloudarr dashboard:

```bash
# Port-forward to local machine
kubectl port-forward -n media-system svc/cloudarr 8080:8080

# Then visit http://localhost:8080
# Login: admin / <your-admin-password>
```

Or if using LoadBalancer with `loadBalancerIP: 192.168.30.60`:

```
http://192.168.30.60:8080
```

Check API health:

```bash
curl http://192.168.30.60:8080/api/health
```

## Troubleshooting

### Pods not starting

```bash
kubectl describe pod -n media-system deployment/cloudarr-api
kubectl logs -n media-system deployment/cloudarr-api
```

### Permission issues

Ensure volumes are owned by user ID 1000 (cloudarr user in container):

```bash
sudo chown -R 1000:1000 /srv/media/
```

### Database locked

If using SQLite on networked storage, consider migrating to PostgreSQL:

```yaml
env:
  - name: CLOUDARR_DB_URL
    value: "postgresql://user:pass@postgres-service:5432/cloudarr"
```

### WebDAV mount issues

Check if `/mnt/torbox` is mounted correctly:

```bash
mount | grep /mnt/torbox
ls /mnt/torbox
```

If not mounted, the rclone mount service may not be running. Check:

```bash
systemctl status torbox-rclone-mount.service
journalctl -xeu torbox-rclone-mount.service
```

## Image Management

### Using imagePullPolicy

Update the deployment to pull from a registry:

1. Change `imagePullPolicy: Never` to `imagePullPolicy: Always`
2. Update `image: cloudarr:latest` to your registry URL
3. Create imagePullSecret if registry is private

### Rebuilding after code changes

```bash
docker build -t cloudarr:latest .
docker push your-registry.com/cloudarr:latest
kubectl rollout restart deployment/cloudarr-api -n media-system
kubectl rollout restart deployment/cloudarr-worker -n media-system
```

## LoadBalancer IP Assignment

The deployment includes a LoadBalancer service on `192.168.30.60`. If this IP is unavailable or you want to change it:

```yaml
spec:
  loadBalancerIP: 192.168.30.XX  # Change this
```

Or remove the LoadBalancer service entirely and use port-forwarding or an Ingress instead.
