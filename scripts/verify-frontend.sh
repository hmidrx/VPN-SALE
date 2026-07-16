#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '\n==> %s\n' "$*"; }

run_build() {
  local workspace="$1"
  log "Production build: ${workspace}"
  CI=1 NEXT_TELEMETRY_DISABLED=1 npm --workspace "$workspace" run build
}

log "Frontend tool versions"
node --version
npm --version
npx tsc --version
npx next --version

if [[ ! -d node_modules ]]; then
  if [[ -f package-lock.json ]]; then
    log "Installing dependencies with npm ci"
    npm ci
  else
    log "Installing dependencies with temporary npm install fallback"
    echo "::warning::package-lock.json is absent; npm install fallback is temporary until the lockfile is committed."
    npm install
  fi
fi

log "Frontend dependency audit (high/critical gate)"
npm audit --audit-level=high
log "Frontend lint"
npm run lint
log "Frontend typecheck"
npm run typecheck
log "Frontend tests"
npm run test
run_build "@vpnsale/customer-web"
run_build "@vpnsale/admin-web"
run_build "@vpnsale/reseller-web"
log "Shared package validation"
npm run typecheck -w @vpnsale/shared-typescript
npm run typecheck -w @vpnsale/ui
npm run test -w @vpnsale/shared-typescript
npm run test -w @vpnsale/ui
