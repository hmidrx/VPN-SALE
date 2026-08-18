#!/usr/bin/env bash
set -euo pipefail

if [[ "${VPN_SALE_ENVIRONMENT:-test}" == "production" ]]; then
  echo "Recovery drill refuses to run with VPN_SALE_ENVIRONMENT=production." >&2
  exit 2
fi

if [[ "${VPN_SALE_PROVIDER_WRITES_ENABLED:-false}" == "true" ]]; then
  echo "Recovery drill requires VPN_SALE_PROVIDER_WRITES_ENABLED=false." >&2
  exit 2
fi

python -m pytest -q \
  apps/api/tests/test_service_operation_guard.py \
  apps/worker/tests/test_recovery_drill.py \
  apps/worker/tests/test_manual_topup_delivery.py \
  apps/worker/tests/test_service_operation_notification.py \
  apps/worker/tests/test_service_usage_sync.py \
  apps/worker/tests/test_worker_heartbeat.py
