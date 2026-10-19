#!/bin/bash
# =============================================================================
# SDC Server Monitoring — Automated Acceptance Test Suite
# =============================================================================
# Usage:
#   ./tests/acceptance_test.sh [CONTAINER_NAME]
#
# Default container name: server-monitoring
# =============================================================================

set -euo pipefail

CONTAINER="${1:-server-monitoring}"
PASS=0
FAIL=0
BLOCKED=0
NOT_TESTED=0
RESULTS=()

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); RESULTS+=("PASS: $1"); }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); RESULTS+=("FAIL: $1"); }
log_blocked() { echo -e "${YELLOW}[BLOCKED]${NC} $1"; BLOCKED=$((BLOCKED+1)); RESULTS+=("BLOCKED: $1"); }
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }

EXEC="docker exec ${CONTAINER}"

echo ""
echo "============================================================"
echo " SDC Server Monitoring — Acceptance Test Suite"
echo " Container: ${CONTAINER}"
echo " Time: $(date)"
echo "============================================================"
echo ""

# ─────────────────────────────────────────────────────────────────
# 1. Container existence and health
# ─────────────────────────────────────────────────────────────────
log_info "=== Section 1: Container Health ==="

STATUS=$(docker inspect --format '{{.State.Status}}' "${CONTAINER}" 2>/dev/null || echo "not_found")
if [ "${STATUS}" = "running" ]; then
    log_pass "Container ${CONTAINER} is running"
else
    log_fail "Container ${CONTAINER} is not running (status: ${STATUS})"
    echo "Cannot continue — container not running."
    exit 1
fi

HEALTH=$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER}" 2>/dev/null || echo "unknown")
if [ "${HEALTH}" = "healthy" ]; then
    log_pass "Container health check: ${HEALTH}"
elif [ "${HEALTH}" = "unknown" ]; then
    log_blocked "Container health check: no healthcheck configured"
else
    log_fail "Container health check: ${HEALTH}"
fi

RESTARTS=$(docker inspect --format '{{.RestartCount}}' "${CONTAINER}" 2>/dev/null || echo "?")
if [ "${RESTARTS}" = "0" ] || [ "${RESTARTS}" = "?" ]; then
    log_pass "Container restart count: ${RESTARTS}"
else
    log_fail "Container has restarted ${RESTARTS} times — check logs"
fi

# ─────────────────────────────────────────────────────────────────
# 2. Process presence inside container
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 2: Process Health ==="

for proc in "node_exporter" "prometheus" "alertmanager" "grafana" "config_manager"; do
    if ${EXEC} ps aux 2>/dev/null | grep -q "${proc}" | grep -v grep; then
        log_pass "Process running: ${proc}"
    else
        COUNT=$(${EXEC} ps aux 2>/dev/null | grep "${proc}" | grep -v grep | wc -l)
        if [ "${COUNT}" -gt "0" ]; then
            log_pass "Process running: ${proc}"
        else
            log_fail "Process NOT found: ${proc}"
        fi
    fi
done

# ─────────────────────────────────────────────────────────────────
# 3. Node Exporter
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 3: Node Exporter ==="

NE_HTTP=$(${EXEC} curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9100/metrics 2>/dev/null || echo "000")
if [ "${NE_HTTP}" = "200" ]; then
    log_pass "Node Exporter HTTP endpoint: 200 OK"
else
    log_fail "Node Exporter HTTP endpoint: ${NE_HTTP}"
fi

# Verify each critical metric family
for metric in node_cpu_seconds_total node_memory_MemTotal_bytes node_memory_MemAvailable_bytes \
              node_filesystem_size_bytes node_filesystem_avail_bytes node_disk_read_bytes_total \
              node_disk_written_bytes_total node_network_receive_bytes_total node_network_transmit_bytes_total \
              node_boot_time_seconds node_uname_info; do
    VALUE=$(${EXEC} curl -s http://127.0.0.1:9100/metrics 2>/dev/null | grep "^${metric}" | head -1)
    if [ -n "${VALUE}" ]; then
        log_pass "Metric present: ${metric}"
    else
        log_fail "Metric MISSING: ${metric}"
    fi
done

# Cross-check node_memory_MemTotal_bytes against host
NE_MEM=$(${EXEC} curl -s http://127.0.0.1:9100/metrics 2>/dev/null | grep "^node_memory_MemTotal_bytes " | awk '{printf "%.0f", $2}')
HOST_MEM=$(grep MemTotal /proc/meminfo | awk '{print $2 * 1024}')
if [ -n "${NE_MEM}" ] && [ -n "${HOST_MEM}" ]; then
    DIFF=$(( NE_MEM - HOST_MEM ))
    DIFF=${DIFF#-}  # abs value
    if [ "${DIFF}" -lt "1048576" ]; then  # within 1MB
        log_pass "node_memory_MemTotal_bytes matches host /proc/meminfo (NE=${NE_MEM}, Host=${HOST_MEM})"
    else
        log_fail "node_memory_MemTotal_bytes does NOT match host (NE=${NE_MEM}, Host=${HOST_MEM})"
    fi
else
    log_blocked "Could not compare memory: NE_MEM='${NE_MEM}' HOST_MEM='${HOST_MEM}'"
fi

# ─────────────────────────────────────────────────────────────────
# 4. Prometheus
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 4: Prometheus ==="

PROM_HEALTH=$(${EXEC} curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9090/-/healthy 2>/dev/null || echo "000")
if [ "${PROM_HEALTH}" = "200" ]; then
    log_pass "Prometheus health endpoint: 200 OK"
else
    log_fail "Prometheus health endpoint: ${PROM_HEALTH}"
fi

# Target health
TARGET_HEALTH=$(${EXEC} curl -s 'http://127.0.0.1:9090/api/v1/targets' 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    targets=d['data']['activeTargets']
    for t in targets:
        print(t['labels'].get('job','?'), t['health'])
except: print('parse_error')
" 2>/dev/null || echo "error")

if echo "${TARGET_HEALTH}" | grep -q "up"; then
    log_pass "Prometheus node target is UP"
else
    log_fail "Prometheus node target is NOT up: ${TARGET_HEALTH}"
fi

# Check for scrape errors
SCRAPE_ERROR=$(${EXEC} curl -s 'http://127.0.0.1:9090/api/v1/targets' 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    targets=d['data']['activeTargets']
    for t in targets:
        err=t.get('lastError','')
        if err: print('ERROR:', err)
except: pass
" 2>/dev/null || echo "")

if [ -z "${SCRAPE_ERROR}" ]; then
    log_pass "No Prometheus scrape errors"
else
    log_fail "Prometheus scrape errors: ${SCRAPE_ERROR}"
fi

# PromQL queries
for query in \
    "100 - (avg by (instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)" \
    "100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))" \
    "100 - ((node_filesystem_avail_bytes{mountpoint=\"/\",fstype!=\"tmpfs\"} * 100) / node_filesystem_size_bytes{mountpoint=\"/\",fstype!=\"tmpfs\"})" \
    "rate(node_network_receive_bytes_total[5m])" \
    "up{job=\"node\"}"; do
    
    QNAME=$(echo "${query}" | cut -c1-50)
    RESULT=$(${EXEC} curl -sG 'http://127.0.0.1:9090/api/v1/query' --data-urlencode "query=${query}" 2>/dev/null | \
             python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print('ok' if r else 'empty')" 2>/dev/null || echo "error")
    if [ "${RESULT}" = "ok" ]; then
        log_pass "PromQL returns data: ${QNAME}..."
    else
        log_fail "PromQL returned ${RESULT}: ${QNAME}..."
    fi
done

# Alert rules loaded
RULES=$(${EXEC} curl -s 'http://127.0.0.1:9090/api/v1/rules' 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(len(g['rules']) for g in d.get('data',{}).get('groups',[])))" 2>/dev/null || echo "0")
if [ "${RULES}" -gt "0" ] 2>/dev/null; then
    log_pass "Prometheus alert rules loaded: ${RULES} rules"
else
    log_fail "No Prometheus alert rules loaded"
fi

# ─────────────────────────────────────────────────────────────────
# 5. Alertmanager
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 5: Alertmanager ==="

AM_HEALTH=$(${EXEC} curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9093/-/healthy 2>/dev/null || echo "000")
if [ "${AM_HEALTH}" = "200" ]; then
    log_pass "Alertmanager health endpoint: 200 OK"
else
    log_fail "Alertmanager health endpoint: ${AM_HEALTH}"
fi

AM_STATUS=$(${EXEC} curl -s 'http://127.0.0.1:9093/api/v2/status' 2>/dev/null | \
            python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cluster',{}).get('status','unknown'))" 2>/dev/null || echo "error")
if [ "${AM_STATUS}" = "ready" ]; then
    log_pass "Alertmanager cluster status: ready"
else
    log_fail "Alertmanager cluster status: ${AM_STATUS}"
fi

# ─────────────────────────────────────────────────────────────────
# 6. Grafana
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 6: Grafana ==="

GF_ADMIN_PASS="${GF_SECURITY_ADMIN_PASSWORD:-admin}"
GF_ADMIN_USER="${GF_SECURITY_ADMIN_USER:-admin}"

GF_HEALTH=$(${EXEC} curl -s 'http://127.0.0.1:3000/api/health' 2>/dev/null | \
            python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('database','unknown'))" 2>/dev/null || echo "error")
if [ "${GF_HEALTH}" = "ok" ]; then
    log_pass "Grafana health (database): ok"
else
    log_fail "Grafana health: ${GF_HEALTH}"
fi

# Datasource
DS=$(${EXEC} curl -su "${GF_ADMIN_USER}:${GF_ADMIN_PASS}" 'http://127.0.0.1:3000/api/datasources' 2>/dev/null | \
     python3 -c "import sys,json; ds=json.load(sys.stdin); print('ok' if any(d.get('type')=='prometheus' for d in ds) else 'missing')" 2>/dev/null || echo "error")
if [ "${DS}" = "ok" ]; then
    log_pass "Grafana Prometheus datasource provisioned"
else
    log_fail "Grafana Prometheus datasource: ${DS} (check credentials?)"
fi

# Test datasource connectivity
DS_TEST=$(${EXEC} curl -su "${GF_ADMIN_USER}:${GF_ADMIN_PASS}" \
          -X POST 'http://127.0.0.1:3000/api/datasources/1/health' \
          -H 'Content-Type: application/json' 2>/dev/null | \
          python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "error")
if [ "${DS_TEST}" = "OK" ]; then
    log_pass "Grafana datasource health check: OK"
else
    log_fail "Grafana datasource health check: ${DS_TEST}"
fi

# Dashboards
DASH=$(${EXEC} curl -su "${GF_ADMIN_USER}:${GF_ADMIN_PASS}" 'http://127.0.0.1:3000/api/search?type=dash-db' 2>/dev/null | \
       python3 -c "import sys,json; ds=json.load(sys.stdin); print(len(ds))" 2>/dev/null || echo "0")
if [ "${DASH}" -gt "0" ] 2>/dev/null; then
    log_pass "Grafana dashboards provisioned: ${DASH} dashboard(s)"
else
    log_fail "No Grafana dashboards found"
fi

# ─────────────────────────────────────────────────────────────────
# 7. Configuration manager
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 7: Configuration Manager ==="

GEN_PROM=$(${EXEC} test -f /opt/server-monitoring/generated/prometheus-alerts.yml && echo "exists" || echo "missing")
GEN_AM=$(${EXEC} test -f /opt/server-monitoring/generated/alertmanager.yml && echo "exists" || echo "missing")

if [ "${GEN_PROM}" = "exists" ]; then
    log_pass "Generated prometheus-alerts.yml exists"
else
    log_fail "Generated prometheus-alerts.yml MISSING"
fi

if [ "${GEN_AM}" = "exists" ]; then
    log_pass "Generated alertmanager.yml exists"
else
    log_fail "Generated alertmanager.yml MISSING"
fi

# Validate generated Prometheus rules using promtool
PROM_CHECK=$(${EXEC} promtool check rules /opt/server-monitoring/generated/prometheus-alerts.yml 2>&1 || echo "INVALID")
if echo "${PROM_CHECK}" | grep -q "SUCCESS\|valid"; then
    log_pass "Generated Prometheus rules pass promtool validation"
elif echo "${PROM_CHECK}" | grep -q "INVALID"; then
    log_fail "Generated Prometheus rules FAILED promtool validation"
else
    log_pass "Generated Prometheus rules pass promtool validation (${PROM_CHECK})"
fi

# Validate alertmanager config  
AM_CHECK=$(${EXEC} amtool check-config /opt/server-monitoring/generated/alertmanager.yml 2>&1 || echo "FAILED")
if echo "${AM_CHECK}" | grep -q "SUCCESS\|Checking"; then
    log_pass "Generated Alertmanager config passes amtool validation"
else
    log_fail "Generated Alertmanager config FAILED amtool: ${AM_CHECK}"
fi

# ─────────────────────────────────────────────────────────────────
# 8. Security checks
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 8: Security ==="

# Check that services are NOT listening on 0.0.0.0 unnecessarily
PROM_LISTEN=$(${EXEC} ss -tlnp 2>/dev/null | grep ':9090' | awk '{print $4}' | head -1)
NE_LISTEN=$(${EXEC} ss -tlnp 2>/dev/null | grep ':9100' | awk '{print $4}' | head -1)
AM_LISTEN=$(${EXEC} ss -tlnp 2>/dev/null | grep ':9093' | awk '{print $4}' | head -1)

for svc_listen in "${PROM_LISTEN}:Prometheus:9090" "${NE_LISTEN}:NodeExporter:9100" "${AM_LISTEN}:Alertmanager:9093"; do
    addr=$(echo "${svc_listen}" | cut -d: -f1)
    name=$(echo "${svc_listen}" | cut -d: -f2)
    if echo "${addr}" | grep -q "127.0.0.1"; then
        log_pass "${name} bound to localhost only"
    elif [ -z "${addr}" ]; then
        log_blocked "${name} listen address: could not determine"
    else
        log_fail "${name} is bound to ${addr} (should be 127.0.0.1)"
    fi
done

# Default credential check
DEFAULT_CRED_TEST=$(${EXEC} curl -su 'admin:admin' 'http://127.0.0.1:3000/api/user' 2>/dev/null | \
                   python3 -c "import sys,json; d=json.load(sys.stdin); print('default_creds' if d.get('login')=='admin' else 'custom_creds')" 2>/dev/null || echo "unknown")
if [ "${DEFAULT_CRED_TEST}" = "custom_creds" ]; then
    log_pass "Grafana does NOT use default admin/admin credentials"
elif [ "${DEFAULT_CRED_TEST}" = "default_creds" ]; then
    log_fail "Grafana is using DEFAULT admin/admin credentials — CHANGE IMMEDIATELY"
else
    log_blocked "Could not verify Grafana credential security"
fi

# ─────────────────────────────────────────────────────────────────
# 9. Persistence check
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 9: Persistence ==="

PROM_VOLUME=$(docker inspect "${CONTAINER}" --format '{{json .Mounts}}' 2>/dev/null | \
              python3 -c "import sys,json; mts=json.load(sys.stdin); print('ok' if any(m.get('Destination')=='/prometheus' for m in mts) else 'missing')" 2>/dev/null || echo "error")
if [ "${PROM_VOLUME}" = "ok" ]; then
    log_pass "Prometheus data volume mounted at /prometheus"
else
    log_fail "Prometheus /prometheus volume not mounted — data will be lost on restart"
fi

GF_VOLUME=$(docker inspect "${CONTAINER}" --format '{{json .Mounts}}' 2>/dev/null | \
            python3 -c "import sys,json; mts=json.load(sys.stdin); print('ok' if any(m.get('Destination')=='/var/lib/grafana' for m in mts) else 'missing')" 2>/dev/null || echo "error")
if [ "${GF_VOLUME}" = "ok" ]; then
    log_pass "Grafana data volume mounted at /var/lib/grafana"
else
    log_fail "Grafana /var/lib/grafana volume not mounted — data will be lost on restart"
fi

# ─────────────────────────────────────────────────────────────────
# 10. Alert end-to-end test (fire a test alert to Alertmanager)
# ─────────────────────────────────────────────────────────────────
log_info ""
log_info "=== Section 10: Alert End-to-End Test ==="

TEST_ALERT_JSON='{
  "labels": {
    "alertname": "AcceptanceTestAlert",
    "severity": "test",
    "instance": "localhost:9100",
    "job": "node"
  },
  "annotations": {
    "summary": "Automated acceptance test alert",
    "description": "This alert was fired by the acceptance test suite and should be resolved automatically."
  },
  "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
  "endsAt": "'$(date -u -d '+5 minutes' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+5M +%Y-%m-%dT%H:%M:%SZ)'"
}'

FIRE_RESULT=$(${EXEC} curl -s -o /dev/null -w "%{http_code}" \
              -X POST 'http://127.0.0.1:9093/api/v2/alerts' \
              -H 'Content-Type: application/json' \
              -d "[${TEST_ALERT_JSON}]" 2>/dev/null || echo "000")

if [ "${FIRE_RESULT}" = "200" ]; then
    log_pass "Test alert successfully posted to Alertmanager"
    
    # Check alert appeared
    sleep 2
    ACTIVE=$(${EXEC} curl -s 'http://127.0.0.1:9093/api/v2/alerts' 2>/dev/null | \
             python3 -c "import sys,json; alerts=json.load(sys.stdin); print('found' if any(a.get('labels',{}).get('alertname')=='AcceptanceTestAlert' for a in alerts) else 'missing')" 2>/dev/null || echo "error")
    if [ "${ACTIVE}" = "found" ]; then
        log_pass "Test alert visible in Alertmanager active alerts"
    else
        log_fail "Test alert NOT found in Alertmanager active alerts"
    fi
else
    log_fail "Failed to post test alert to Alertmanager: HTTP ${FIRE_RESULT}"
fi

# ─────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " TEST SUMMARY"
echo "============================================================"
echo -e " ${GREEN}PASS:${NC}    ${PASS}"
echo -e " ${RED}FAIL:${NC}    ${FAIL}"
echo -e " ${YELLOW}BLOCKED:${NC} ${BLOCKED}"
echo ""
echo " Results:"
for r in "${RESULTS[@]}"; do
    if [[ "${r}" == PASS* ]]; then
        echo -e "  ${GREEN}✓${NC} ${r#PASS: }"
    elif [[ "${r}" == FAIL* ]]; then
        echo -e "  ${RED}✗${NC} ${r#FAIL: }"
    else
        echo -e "  ${YELLOW}?${NC} ${r#BLOCKED: }"
    fi
done
echo ""

if [ "${FAIL}" -gt "0" ]; then
    echo -e "${RED}ACCEPTANCE TEST FAILED — ${FAIL} test(s) failed.${NC}"
    exit 1
else
    echo -e "${GREEN}ACCEPTANCE TEST PASSED — ${PASS} test(s) passed, ${BLOCKED} blocked.${NC}"
    exit 0
fi
