import os
import sys
import time
import yaml
import subprocess
import hashlib
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

CONFIG_PATH = '/opt/server-monitoring/config/monitoring.yaml'
PROMETHEUS_ALERTS_PATH = '/opt/server-monitoring/generated/prometheus-alerts.yml'
ALERTMANAGER_CONFIG_PATH = '/opt/server-monitoring/generated/alertmanager.yml'

def get_file_hash(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return None

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
        
        # Build interface regex
        interfaces_config = net.get('interfaces', {})
        includes = interfaces_config.get('include', [])
        excludes = interfaces_config.get('exclude', ['^docker0$', '^br-.*', '^veth.*'])
        
        if includes:
            device_match = f'device=~"{",".join(includes)}"'
        else:
            if excludes:
                device_match = f'device!~"{",".join(excludes)}"'
            else:
                device_match = 'device=~".*"'

        rules.append({
            'alert': 'HighNetworkRX',
            'expr': f'rate(node_network_receive_bytes_total{{{device_match}}}[5m]) > {net["rx_bytes_per_second"]}',
            'for': net['duration'],
            'labels': {'severity': net['severity']},
            'annotations': {
                'summary': 'High Network RX',
                'description': f'Network RX bytes per second > {net["rx_bytes_per_second"]} for {net["duration"]}.'
            }
        })
        rules.append({
            'alert': 'HighNetworkTX',
            'expr': f'rate(node_network_transmit_bytes_total{{{device_match}}}[5m]) > {net["tx_bytes_per_second"]}',
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
    def __init__(self):
        self.last_hash = get_file_hash(CONFIG_PATH)
        self.last_trigger_time = 0
        self.debounce_seconds = 2

    def on_any_event(self, event):
        if event.is_directory:
            return
            
        # Ignore temp and swap files
        if event.src_path.endswith('.swp') or event.src_path.endswith('.tmp') or event.src_path.endswith('~'):
            return

        # Ensure we're only looking at the target config path
        if os.path.basename(event.src_path) != os.path.basename(CONFIG_PATH):
            return

        current_time = time.time()
        if current_time - self.last_trigger_time < self.debounce_seconds:
            return

        # Wait for file stability
        time.sleep(1)
        current_hash = get_file_hash(CONFIG_PATH)
        if not current_hash:
            return
            
        if current_hash != self.last_hash:
            print("[INFO] Configuration file stability detected. Processing...")
            self.last_hash = current_hash
            self.last_trigger_time = current_time
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
