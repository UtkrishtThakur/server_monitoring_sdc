# Server Monitoring Appliance

This is a self-contained, production-ready server monitoring appliance in a single Docker container.
It contains:
- `node_exporter` (for host metrics)
- Prometheus (TSDB and rules evaluation)
- Alertmanager (for routing alerts)
- Grafana (for visualization)
- Custom Config Manager (auto-generates Prometheus rules from a simple YAML)

## Architecture

```text
                        HOST SERVER
                            │
                            │ host /proc, /sys, /
                            ▼
┌────────────────────────────────────────────────────────────────┐
│                  server-monitoring container                   │
│                                                                │
│  ┌─────────────────┐                                           │
│  │ node_exporter   │                                           │
│  │                 │                                           │
│  │ Host metrics    │                                           │
│  └────────┬────────┘                                           │
│           │                                                    │
│           ▼                                                    │
│  ┌─────────────────┐       ┌─────────────────────┐             │
│  │   Prometheus    │──────►│    Alertmanager     │             │
│  │                 │       │                     │             │
│  │ TSDB + rules    │       │ notifications       │             │
│  └────────┬────────┘       └─────────────────────┘             │
│           │                                                    │
│           ▼                                                    │
│  ┌─────────────────┐                                           │
│  │     Grafana     │                                           │
│  │                 │                                           │
│  │ dashboards      │                                           │
│  │ alert status    │                                           │
│  └─────────────────┘                                           │
│                                                                │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ Custom Monitoring Configuration Controller                │ │
│  │                                                           │ │
│  │ monitoring.yaml → validate → generate Prometheus rules   │ │
│  │                    → reload Prometheus/Alertmanager       │ │
│  └───────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

## Build

```bash
docker build -t server-monitoring .
```

## Run

To run in production with persistent data and host metrics:

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

## Persistent volumes

- `/prometheus`: Prometheus metrics retention.
- `/var/lib/grafana`: Grafana database (users, dashboards, settings).
By mounting these as volumes, monitoring history and dashboard state survive container recreation.

## Host mounts

To accurately monitor the host server, the container needs read-only access to:
- `/proc` mapped to `/host/proc`
- `/sys` mapped to `/host/sys`
- `/` mapped to `/host/root`

## Ports

- `3000`: Grafana UI
- `9090`: Prometheus UI
- `9093`: Alertmanager UI

## Configuration

Alerts are configured via `/opt/server-monitoring/config/monitoring.yaml`. You don't need to write PromQL!
Example:
```yaml
alerts:
  cpu:
    enabled: true
    threshold: 80
    duration: 5m
    severity: warning
  memory:
    enabled: true
    threshold: 85
    duration: 5m
    severity: warning
```

## Notification configuration
Webhook URLs can be provided via environment variables as defined in `monitoring.yaml`, preventing secrets from being baked into the image.

## Runtime configuration reload
Modifying `monitoring.yaml` while the container is running will automatically trigger validation and reloading. If the configuration is invalid, the changes are discarded and the old configuration remains active.
