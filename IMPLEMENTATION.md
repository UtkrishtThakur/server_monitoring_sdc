# Monitoring System Implementation Details

This document outlines the architecture, implemented components, and operational mechanics of the server monitoring appliance.

## 1. Architecture Overview

The system is designed as a single, self-sufficient Docker container that acts as a monitoring appliance for the host server it runs on. It bundles multiple best-in-class open-source monitoring tools into a cohesive unit managed by a process supervisor.

### Core Components
- **node_exporter**: Collects system metrics (CPU, Memory, Disk, Network) from the host.
- **Prometheus**: Time-series database that scrapes `node_exporter` and evaluates alert rules.
- **Alertmanager**: Handles alert routing, grouping, and notifications.
- **Grafana**: Visualization layer with pre-provisioned dashboards.
- **Custom Configuration Manager**: A Python-based controller that translates user-friendly YAML configuration into native Prometheus and Alertmanager rules.
- **Supervisord**: Process manager (PID 1) that ensures all services start in the correct order and stay running.

## 2. What Is Implemented

- **Single Docker Image**: All components are installed and configured within a single `Dockerfile` based on Ubuntu 22.04.
- **Configuration Scaffolding**: 
  - `monitoring.yaml`: The single source of truth for alerts.
  - `prometheus.yml`: Pre-configured to scrape the local `node_exporter`.
  - `alertmanager.yml`: Pre-configured for basic routing.
  - Grafana provisioning files for automatic datasource and dashboard loading.
- **Custom Config Manager**: A Python script (`src/config_manager/main.py`) that uses `watchdog` to monitor `monitoring.yaml` for changes. It automatically generates Prometheus rules, validates them using `promtool`, and triggers hot-reloads via HTTP POST without container restarts.
- **Host Monitoring Integration**: `node_exporter` is configured to monitor the host server (via volume mounts `/host/proc`, `/host/sys`, `/host/root`) rather than the container's isolated environment.
- **Health Checks & Scripts**: Container health checks ensure that all HTTP endpoints for Prometheus, Alertmanager, and Grafana are responding.

## 3. How It Works on the Server

### Deployment
The system is deployed using a single `docker run` command. Critical host paths are mounted read-only so `node_exporter` can accurately report host metrics. Persistent volumes are used for Prometheus time-series data and Grafana's database.

```bash
docker run -d \
  --name server-monitoring \
  --restart unless-stopped \
  -p 3000:3000 \
  -p 9090:9090 \
  -p 9093:9093 \
  -v /opt/server-monitoring/config:/opt/server-monitoring/config \
  -v /opt/server-monitoring/prometheus-data:/prometheus \
  -v /opt/server-monitoring/grafana-data:/var/lib/grafana \
  -v /:/host/root:ro \
  -v /sys:/host/sys:ro \
  -v /proc:/host/proc:ro \
  -e ALERT_WEBHOOK_URL="https://your-webhook.example.com" \
  server-monitoring:latest
```

### Runtime Flow
1. **Startup**: `supervisord` starts as PID 1. It launches `node_exporter`, `Prometheus`, `Alertmanager`, `Grafana`, and the `config_manager`.
2. **Metrics Collection**: `node_exporter` continuously gathers host metrics.
3. **Scraping**: `Prometheus` scrapes `node_exporter` every 15 seconds.
4. **Alert Evaluation**: `Prometheus` evaluates the generated rules against the collected metrics. If a threshold is breached (e.g., CPU > 80% for 5m), it fires an alert to `Alertmanager`.
5. **Notification**: `Alertmanager` routes the alert to the configured receivers (e.g., a Webhook).
6. **Visualization**: `Grafana` queries `Prometheus` and displays the host's health on a pre-provisioned dashboard available on port 3000.

### Dynamic Reconfiguration
If the DevOps team updates `/opt/server-monitoring/config/monitoring.yaml`:
1. The Custom Config Manager detects the file change.
2. It parses the YAML and generates a temporary `prometheus-alerts.yml`.
3. It validates the rules using `promtool check rules`.
4. If valid, it atomically overwrites the live configuration and sends a `/-/reload` signal to Prometheus.
5. If invalid, it logs an error to `stdout` (visible via `docker logs`) and discards the change, leaving the monitoring system unbroken.
