#!/bin/bash
set -e

curl -sf http://127.0.0.1:9100/metrics > /dev/null || exit 1
curl -sf http://127.0.0.1:9090/-/healthy > /dev/null || exit 1
curl -sf http://127.0.0.1:9093/-/healthy > /dev/null || exit 1
curl -sf http://127.0.0.1:3000/api/health > /dev/null || exit 1
exit 0
 