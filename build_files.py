import os

files = {
    "/mnt/ai/Projects/monitor/src/config_manager/requirements.txt": """PyYAML==6.0.1
requests==2.31.0
watchdog==3.0.0
""",
    "/mnt/ai/Projects/monitor/prometheus/prometheus.yml": """global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "/opt/server-monitoring/generated/prometheus-alerts.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - "127.0.0.1:9093"

scrape_configs:
  - job_name: "node"
    static_configs:
      - targets: ["127.0.0.1:9100"]
""",
    "/mnt/ai/Projects/monitor/alertmanager/alertmanager.yml": """route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'default-receiver'

receivers:
  - name: 'default-receiver'
""",
    "/mnt/ai/Projects/monitor/grafana/provisioning/datasources/prometheus.yml": """apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://127.0.0.1:9090
    access: proxy
    isDefault: true
    editable: false
""",
    "/mnt/ai/Projects/monitor/grafana/provisioning/dashboards/dashboards.yml": """apiVersion: 1
providers:
  - name: 'default'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    options:
      path: /var/lib/grafana/dashboards
""",
    "/mnt/ai/Projects/monitor/grafana/dashboards/server-monitoring.json": """{
  "title": "Server Monitoring",
  "panels": [
    {
      "type": "timeseries",
      "title": "CPU Usage",
      "targets": [
        {
          "expr": "100 - (avg by (instance) (rate(node_cpu_seconds_total{mode=\\"idle\\"}[5m])) * 100)",
          "refId": "A"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Memory Usage",
      "targets": [
        {
          "expr": "100 * (1 - ((node_memory_MemFree_bytes + node_memory_Buffers_bytes + node_memory_Cached_bytes) / node_memory_MemTotal_bytes))",
          "refId": "A"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Disk Usage (/host/root)",
      "targets": [
        {
          "expr": "100 - ((node_filesystem_avail_bytes{mountpoint=\\"/host/root\\"} * 100) / node_filesystem_size_bytes{mountpoint=\\"/host/root\\"})",
          "refId": "A"
        }
      ]
    }
  ],
  "schemaVersion": 16
}
""",
    "/mnt/ai/Projects/monitor/scripts/entrypoint.sh": """#!/bin/bash
set -e

echo "[INFO] Initializing directories..."
mkdir -p /opt/server-monitoring/generated
mkdir -p /var/lib/grafana/dashboards
cp /opt/server-monitoring/grafana/dashboards/*.json /var/lib/grafana/dashboards/ || true

echo "[INFO] Running initial configuration generation..."
python3 /opt/server-monitoring/src/config_manager/main.py --initial

echo "[INFO] Starting supervisord..."
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
""",
    "/mnt/ai/Projects/monitor/scripts/healthcheck.sh": """#!/bin/bash
set -e

curl -sf http://127.0.0.1:9100/metrics > /dev/null || exit 1
curl -sf http://127.0.0.1:9090/-/healthy > /dev/null || exit 1
curl -sf http://127.0.0.1:9093/-/healthy > /dev/null || exit 1
curl -sf http://127.0.0.1:3000/api/health > /dev/null || exit 1
exit 0
""",
    "/mnt/ai/Projects/monitor/supervisor/supervisord.conf": """[supervisord]
nodaemon=true
logfile=/dev/stdout
logfile_maxbytes=0
loglevel=info

[program:node_exporter]
command=/usr/local/bin/node_exporter --path.procfs=/host/proc --path.sysfs=/host/sys --path.rootfs=/host/root --collector.filesystem.mount-points-exclude="^/(dev|proc|sys|run)($|/)"
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:prometheus]
command=/usr/local/bin/prometheus --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --web.console.libraries=/usr/local/share/prometheus/console_libraries --web.console.templates=/usr/local/share/prometheus/consoles --web.listen-address=127.0.0.1:9090
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:alertmanager]
command=/usr/local/bin/alertmanager --config.file=/opt/server-monitoring/generated/alertmanager.yml --storage.path=/alertmanager --web.listen-address=127.0.0.1:9093
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:grafana]
command=/usr/share/grafana/bin/grafana server --homepath=/usr/share/grafana --config=/etc/grafana/grafana.ini
environment=GF_PATHS_DATA="/var/lib/grafana",GF_PATHS_LOGS="/var/log/grafana",GF_PATHS_PLUGINS="/var/lib/grafana/plugins",GF_PATHS_PROVISIONING="/etc/grafana/provisioning",GF_SERVER_HTTP_PORT="3000"
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:config_manager]
command=python3 /opt/server-monitoring/src/config_manager/main.py --watch
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
""",
    "/mnt/ai/Projects/monitor/Dockerfile": """FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PROMETHEUS_VERSION=2.45.0
ENV ALERTMANAGER_VERSION=0.25.0
ENV NODE_EXPORTER_VERSION=1.6.1
ENV GRAFANA_VERSION=10.0.3

RUN apt-get update && apt-get install -y \
    curl \
    wget \
    supervisor \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz && \
    tar xvf prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz && \
    cp prometheus-${PROMETHEUS_VERSION}.linux-amd64/prometheus /usr/local/bin/ && \
    cp prometheus-${PROMETHEUS_VERSION}.linux-amd64/promtool /usr/local/bin/ && \
    mkdir -p /etc/prometheus /usr/local/share/prometheus && \
    cp -r prometheus-${PROMETHEUS_VERSION}.linux-amd64/console_libraries /usr/local/share/prometheus/ && \
    cp -r prometheus-${PROMETHEUS_VERSION}.linux-amd64/consoles /usr/local/share/prometheus/ && \
    rm -rf prometheus-${PROMETHEUS_VERSION}.linux-amd64*

RUN wget -q https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz && \
    tar xvf alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz && \
    cp alertmanager-${ALERTMANAGER_VERSION}.linux-amd64/alertmanager /usr/local/bin/ && \
    cp alertmanager-${ALERTMANAGER_VERSION}.linux-amd64/amtool /usr/local/bin/ && \
    mkdir -p /etc/alertmanager && \
    rm -rf alertmanager-${ALERTMANAGER_VERSION}.linux-amd64*

RUN wget -q https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz && \
    tar xvf node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz && \
    cp node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/ && \
    rm -rf node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64*

RUN apt-get update && apt-get install -y apt-transport-https software-properties-common && \
    wget -q -O /usr/share/keyrings/grafana.key https://apt.grafana.com/gpg.key && \
    echo "deb [signed-by=/usr/share/keyrings/grafana.key] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list && \
    apt-get update && apt-get install -y grafana=${GRAFANA_VERSION} && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/server-monitoring/config \
    /opt/server-monitoring/src \
    /opt/server-monitoring/prometheus \
    /opt/server-monitoring/alertmanager \
    /opt/server-monitoring/grafana \
    /opt/server-monitoring/scripts \
    /opt/server-monitoring/supervisor \
    /opt/server-monitoring/generated \
    /prometheus \
    /alertmanager \
    /var/lib/grafana/dashboards

WORKDIR /opt/server-monitoring

COPY src/config_manager/requirements.txt /opt/server-monitoring/src/config_manager/requirements.txt
RUN pip3 install -r /opt/server-monitoring/src/config_manager/requirements.txt

COPY . /opt/server-monitoring/

RUN cp /opt/server-monitoring/prometheus/prometheus.yml /etc/prometheus/prometheus.yml && \
    cp -r /opt/server-monitoring/grafana/provisioning/* /etc/grafana/provisioning/ && \
    cp /opt/server-monitoring/supervisor/supervisord.conf /etc/supervisor/supervisord.conf && \
    chmod +x /opt/server-monitoring/scripts/entrypoint.sh && \
    chmod +x /opt/server-monitoring/scripts/healthcheck.sh

EXPOSE 3000 9090 9093

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD /opt/server-monitoring/scripts/healthcheck.sh

ENTRYPOINT ["/opt/server-monitoring/scripts/entrypoint.sh"]
""",
    "/mnt/ai/Projects/monitor/src/config_manager/main.py": """import os
import sys
import time
import yaml
import subprocess
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

CONFIG_PATH = '/opt/server-monitoring/config/monitoring.yaml'
PROMETHEUS_ALERTS_PATH = '/opt/server-monitoring/generated/prometheus-alerts.yml'
ALERTMANAGER_CONFIG_PATH = '/opt/server-monitoring/generated/alertmanager.yml'

def generate_prometheus_rules(config):
    rules = []
    
    if config.get('alerts', {}).get('cpu', {}).get('enabled', False):
        cpu = config['alerts']['cpu']
        rules.append({
            'alert': 'HighCPUUsage',
            'expr': f'100 - (avg by (instance) (rate(node_cpu_seconds_total{{mode="idle"}}[5m])) * 100) > {cpu["threshold"]}',
            'for': cpu['duration'],
            'labels': {'severity': cpu['severity']},
            'annotations': {
                'summary': 'High CPU usage',
                'description': f'CPU usage has remained above {cpu["threshold"]}% for {cpu["duration"]}.'
            }
        })
        
    if config.get('alerts', {}).get('memory', {}).get('enabled', False):
        mem = config['alerts']['memory']
        rules.append({
            'alert': 'HighMemoryUsage',
            'expr': f'100 * (1 - ((node_memory_MemFree_bytes + node_memory_Buffers_bytes + node_memory_Cached_bytes) / node_memory_MemTotal_bytes)) > {mem["threshold"]}',
            'for': mem['duration'],
            'labels': {'severity': mem['severity']},
            'annotations': {
                'summary': 'High Memory usage',
                'description': f'Memory usage has remained above {mem["threshold"]}% for {mem["duration"]}.'
            }
        })

    if config.get('alerts', {}).get('disk', {}).get('enabled', False):
        disk = config['alerts']['disk']
        rules.append({
            'alert': 'HighDiskUsage',
            'expr': f'100 - ((node_filesystem_avail_bytes{{mountpoint="/host/root"}} * 100) / node_filesystem_size_bytes{{mountpoint="/host/root"}}) > {disk["threshold"]}',
            'for': disk['duration'],
            'labels': {'severity': disk['severity']},
            'annotations': {
                'summary': 'High Disk usage',
                'description': f'Disk usage on /host/root has remained above {disk["threshold"]}% for {disk["duration"]}.'
            }
        })

    if config.get('alerts', {}).get('network', {}).get('enabled', False):
        net = config['alerts']['network']
        rules.append({
            'alert': 'HighNetworkRX',
            'expr': f'rate(node_network_receive_bytes_total[5m]) > {net["rx_bytes_per_second"]}',
            'for': net['duration'],
            'labels': {'severity': net['severity']},
            'annotations': {
                'summary': 'High Network RX',
                'description': f'Network RX bytes per second > {net["rx_bytes_per_second"]} for {net["duration"]}.'
            }
        })
        rules.append({
            'alert': 'HighNetworkTX',
            'expr': f'rate(node_network_transmit_bytes_total[5m]) > {net["tx_bytes_per_second"]}',
            'for': net['duration'],
            'labels': {'severity': net['severity']},
            'annotations': {
                'summary': 'High Network TX',
                'description': f'Network TX bytes per second > {net["tx_bytes_per_second"]} for {net["duration"]}.'
            }
        })

    return {'groups': [{'name': 'server-monitoring', 'rules': rules}]}

def generate_alertmanager_config(config):
    receivers = []
    for rec in config.get('notifications', {}).get('receivers', []):
        if rec['type'] == 'webhook':
            url_env = rec.get('url_env')
            url = os.environ.get(url_env, 'http://localhost:8080/default-webhook') if url_env else 'http://localhost:8080/default-webhook'
            receivers.append({
                'name': rec['name'],
                'webhook_configs': [{'url': url}]
            })
            
    if not receivers:
        receivers.append({'name': 'default-receiver'})
        
    return {
        'route': {
            'group_by': ['alertname'],
            'group_wait': '10s',
            'group_interval': '10s',
            'repeat_interval': '1h',
            'receiver': receivers[0]['name']
        },
        'receivers': receivers
    }

def process_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
            
        prom_rules = generate_prometheus_rules(config)
        am_config = generate_alertmanager_config(config)
        
        with open(PROMETHEUS_ALERTS_PATH + '.tmp', 'w') as f:
            yaml.dump(prom_rules, f)
            
        with open(ALERTMANAGER_CONFIG_PATH + '.tmp', 'w') as f:
            yaml.dump(am_config, f)
            
        # Validate Prometheus rules
        res = subprocess.run(['promtool', 'check', 'rules', PROMETHEUS_ALERTS_PATH + '.tmp'], capture_output=True)
        if res.returncode != 0:
            print(f"[ERROR] Invalid Prometheus rules generated: {res.stderr.decode()}")
            return False
            
        # Validate Alertmanager config
        res = subprocess.run(['amtool', 'check-config', ALERTMANAGER_CONFIG_PATH + '.tmp'], capture_output=True)
        if res.returncode != 0:
            print(f"[ERROR] Invalid Alertmanager config generated: {res.stderr.decode()}")
            return False
            
        os.rename(PROMETHEUS_ALERTS_PATH + '.tmp', PROMETHEUS_ALERTS_PATH)
        os.rename(ALERTMANAGER_CONFIG_PATH + '.tmp', ALERTMANAGER_CONFIG_PATH)
        
        print("[INFO] Configuration validated successfully. Generated rules.")
        
        # Reload Prometheus
        subprocess.run(['curl', '-s', '-X', 'POST', 'http://127.0.0.1:9090/-/reload'])
        print("[INFO] Prometheus reload requested.")
        
        # Reload Alertmanager
        subprocess.run(['curl', '-s', '-X', 'POST', 'http://127.0.0.1:9093/-/reload'])
        print("[INFO] Alertmanager reload requested.")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to process configuration: {e}")
        return False

class ConfigHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path == CONFIG_PATH:
            print("[INFO] Configuration change detected.")
            process_config()

if __name__ == '__main__':
    if '--initial' in sys.argv:
        process_config()
    elif '--watch' in sys.argv:
        observer = Observer()
        observer.schedule(ConfigHandler(), path=os.path.dirname(CONFIG_PATH), recursive=False)
        observer.start()
        print("[INFO] Watching for configuration changes...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
"""
}

for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

print("Files written successfully")
