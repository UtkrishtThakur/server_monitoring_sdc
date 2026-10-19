#!/bin/bash
set -e

# Require explicit Grafana admin password — never start with default credentials
if [ -z "$GF_SECURITY_ADMIN_PASSWORD" ] && [ -z "$GF_SECURITY_ADMIN_PASSWORD__FILE" ]; then
    echo "[ERROR] Grafana administrator credentials are not configured."
    echo "Set GF_SECURITY_ADMIN_PASSWORD or GF_SECURITY_ADMIN_PASSWORD__FILE."
    echo "Refusing to start with insecure default credentials."
    exit 1
fi

echo "[INFO] Initializing directories..."
mkdir -p /opt/server-monitoring/generated
mkdir -p /var/lib/grafana/dashboards
cp /opt/server-monitoring/grafana/dashboards/*.json /var/lib/grafana/dashboards/ || true

echo "[INFO] Running initial configuration generation..."
python3 /opt/server-monitoring/src/config_manager/main.py --initial

if [ $? -ne 0 ]; then
    echo "[ERROR] Initial configuration generation failed. Check monitoring.yaml syntax."
    exit 1
fi

echo "[INFO] Starting supervisord..."
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
