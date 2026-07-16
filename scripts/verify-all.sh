#!/usr/bin/env bash
set -Eeuo pipefail

scripts/verify-backend.sh
scripts/verify-frontend.sh
scripts/security-scan.sh
if command -v docker >/dev/null 2>&1; then
  scripts/verify-docker.sh
else
  if [[ "${ALLOW_MISSING_DOCKER:-}" == "1" ]]; then
    echo "::warning::Docker is unavailable; skipping Docker verification only because ALLOW_MISSING_DOCKER=1."
  else
    echo "Docker is required for full verification. Set ALLOW_MISSING_DOCKER=1 only in restricted environments." >&2
    exit 127
  fi
fi
