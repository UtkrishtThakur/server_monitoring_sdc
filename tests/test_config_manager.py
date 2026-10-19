#!/usr/bin/env python3
"""
Unit tests for the config_manager.
Tests config parsing, validation, rule generation, and error handling.
"""
import os
import sys
import json
import yaml
import tempfile
import unittest
import subprocess

# Add parent src dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'config_manager'))

# Patch the paths before importing main
import main as cm

class TestGeneratePrometheusRules(unittest.TestCase):
    
    def test_cpu_alert_generated(self):
        config = {
            'alerts': {
                'cpu': {'enabled': True, 'threshold': 80, 'duration': '5m', 'severity': 'warning'}
            }
        }
        result = cm.generate_prometheus_rules(config)
        self.assertEqual(result['groups'][0]['name'], 'server-monitoring')
        rules = result['groups'][0]['rules']
        cpu_rule = next((r for r in rules if r['alert'] == 'HighCPUUsage'), None)
        self.assertIsNotNone(cpu_rule)
        self.assertIn('80', cpu_rule['expr'])
        self.assertEqual(cpu_rule['for'], '5m')
        self.assertEqual(cpu_rule['labels']['severity'], 'warning')

    def test_cpu_alert_disabled(self):
        config = {
            'alerts': {
                'cpu': {'enabled': False, 'threshold': 80, 'duration': '5m', 'severity': 'warning'}
            }
        }
        result = cm.generate_prometheus_rules(config)
        rules = result['groups'][0]['rules']
        cpu_rule = next((r for r in rules if r['alert'] == 'HighCPUUsage'), None)
        self.assertIsNone(cpu_rule)

    def test_memory_alert_generated(self):
        config = {
            'alerts': {
                'memory': {'enabled': True, 'threshold': 85, 'duration': '5m', 'severity': 'warning'}
            }
        }
        result = cm.generate_prometheus_rules(config)
        rules = result['groups'][0]['rules']
        mem_rule = next((r for r in rules if r['alert'] == 'HighMemoryUsage'), None)
        self.assertIsNotNone(mem_rule)
        self.assertIn('85', mem_rule['expr'])

    def test_disk_alert_uses_correct_mountpoint(self):
        """Critical: disk alert must use mountpoint="/" not "/host/root" """
        config = {
            'alerts': {
                'disk': {'enabled': True, 'threshold': 90, 'duration': '10m', 'severity': 'critical'}
            }
        }
        result = cm.generate_prometheus_rules(config)
        rules = result['groups'][0]['rules']
        disk_rule = next((r for r in rules if r['alert'] == 'HighDiskUsage'), None)
        self.assertIsNotNone(disk_rule)
        # Must NOT use /host/root — node_exporter normalizes mountpoints
        self.assertNotIn('/host/root', disk_rule['expr'], 
            'Disk alert must not use /host/root — node_exporter reports host root as /')
        self.assertIn('mountpoint="/"', disk_rule['expr'],
            'Disk alert must use mountpoint="/" to match host root filesystem')

    def test_hostdown_alert_always_present(self):
        """HostDown alert should always be generated regardless of config"""
        config = {'alerts': {}}
        result = cm.generate_prometheus_rules(config)
        rules = result['groups'][0]['rules']
        hostdown = next((r for r in rules if r['alert'] == 'HostDown'), None)
        self.assertIsNotNone(hostdown, 'HostDown alert should always be generated')
        self.assertEqual(hostdown['labels']['severity'], 'critical')

    def test_network_alert_device_regex_uses_pipe(self):
        """Network device filter must use | not , for regex alternation"""
        config = {
            'alerts': {
                'network': {
                    'enabled': True,
                    'rx_bytes_per_second': 100000000,
                    'tx_bytes_per_second': 100000000,
                    'duration': '5m',
                    'severity': 'warning',
                    'interfaces': {
                        'exclude': ['^docker0$', '^br-.*', '^veth.*']
                    }
                }
            }
        }
        result = cm.generate_prometheus_rules(config)
        rules = result['groups'][0]['rules']
        rx_rule = next((r for r in rules if r['alert'] == 'HighNetworkRX'), None)
        self.assertIsNotNone(rx_rule)
        # Regex alternation must use | not ,
        self.assertIn('|', rx_rule['expr'])
        self.assertNotIn('docker0$,', rx_rule['expr'])

    def test_empty_config_does_not_crash(self):
        config = {}
        result = cm.generate_prometheus_rules(config)
        self.assertIn('groups', result)

    def test_network_alerts_include_list(self):
        config = {
            'alerts': {
                'network': {
                    'enabled': True,
                    'rx_bytes_per_second': 50000000,
                    'tx_bytes_per_second': 50000000,
                    'duration': '5m',
                    'severity': 'warning',
                    'interfaces': {
                        'include': ['eth0', 'ens3']
                    }
                }
            }
        }
        result = cm.generate_prometheus_rules(config)
        rules = result['groups'][0]['rules']
        rx_rule = next((r for r in rules if r['alert'] == 'HighNetworkRX'), None)
        self.assertIsNotNone(rx_rule)
        # Should use =~ for includes
        self.assertIn('=~', rx_rule['expr'])
        # Should use | separator
        self.assertIn('eth0|ens3', rx_rule['expr'])


class TestGenerateAlertmanagerConfig(unittest.TestCase):

    def test_default_receiver_when_no_notifications(self):
        config = {}
        result = cm.generate_alertmanager_config(config)
        self.assertEqual(len(result['receivers']), 1)
        self.assertEqual(result['receivers'][0]['name'], 'default-receiver')

    def test_webhook_receiver_from_env(self):
        os.environ['TEST_WEBHOOK_URL'] = 'https://example.com/webhook'
        config = {
            'notifications': {
                'receivers': [{'name': 'test', 'type': 'webhook', 'url_env': 'TEST_WEBHOOK_URL'}]
            }
        }
        result = cm.generate_alertmanager_config(config)
        self.assertEqual(result['receivers'][0]['name'], 'test')
        self.assertEqual(result['receivers'][0]['webhook_configs'][0]['url'], 'https://example.com/webhook')
        del os.environ['TEST_WEBHOOK_URL']

    def test_webhook_fallback_when_env_not_set(self):
        config = {
            'notifications': {
                'receivers': [{'name': 'admin', 'type': 'webhook', 'url_env': 'NONEXISTENT_ENV_VAR_XYZ'}]
            }
        }
        result = cm.generate_alertmanager_config(config)
        url = result['receivers'][0]['webhook_configs'][0]['url']
        # Should fall back to default
        self.assertIn('localhost', url)

    def test_route_uses_first_receiver(self):
        config = {
            'notifications': {
                'receivers': [{'name': 'my_receiver', 'type': 'webhook', 'url_env': 'NONEXISTENT'}]
            }
        }
        result = cm.generate_alertmanager_config(config)
        self.assertEqual(result['route']['receiver'], 'my_receiver')


class TestPromQLValidity(unittest.TestCase):
    """Validate generated PromQL expressions using promtool if available"""
    
    PROMTOOL = '/usr/local/bin/promtool'
    
    def _promtool_available(self):
        return os.path.exists(self.PROMTOOL)

    def test_generated_rules_pass_promtool(self):
        if not self._promtool_available():
            self.skipTest('promtool not found at ' + self.PROMTOOL)
        
        full_config = {
            'alerts': {
                'cpu': {'enabled': True, 'threshold': 80, 'duration': '5m', 'severity': 'warning'},
                'memory': {'enabled': True, 'threshold': 85, 'duration': '5m', 'severity': 'warning'},
                'disk': {'enabled': True, 'threshold': 90, 'duration': '10m', 'severity': 'critical'},
                'network': {
                    'enabled': True, 
                    'rx_bytes_per_second': 100000000,
                    'tx_bytes_per_second': 100000000,
                    'duration': '5m', 
                    'severity': 'warning'
                }
            }
        }
        rules = cm.generate_prometheus_rules(full_config)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(rules, f)
            tmppath = f.name
        
        try:
            result = subprocess.run(
                [self.PROMTOOL, 'check', 'rules', tmppath],
                capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, 
                f'promtool validation failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}')
        finally:
            os.unlink(tmppath)


class TestConfigFileHash(unittest.TestCase):
    
    def test_hash_changes_with_content(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("version: 1\n")
            path = f.name
        try:
            h1 = cm.get_file_hash(path)
            with open(path, 'a') as f:
                f.write("alerts: {}\n")
            h2 = cm.get_file_hash(path)
            self.assertNotEqual(h1, h2)
        finally:
            os.unlink(path)

    def test_hash_returns_none_for_missing_file(self):
        h = cm.get_file_hash('/nonexistent/path/file.yaml')
        self.assertIsNone(h)


if __name__ == '__main__':
    unittest.main(verbosity=2)
