#!/usr/bin/env bash
set -Eeuo pipefail

mkdir -p test-reports
exec > >(tee test-reports/frontend-verification.log) 2>&1

log() { printf '\n==> %s\n' "$*"; }

build_workspace() {
  local workspace="$1"
  local app_dir="$2"
  log "$workspace production build"
  if npm run build -w "$workspace"; then
    return 0
  fi

  echo "Build failed for $workspace; running post-build TypeScript diagnostics." >&2
  find "$app_dir/.next/types" -maxdepth 4 -type f -print 2>/dev/null || true
  npx tsc -p "$app_dir/tsconfig.json" --pretty false --noEmit || true
  return 1
}

log "Node and npm versions"
node --version
npm --version

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

log "Frontend lint"
npm run lint
log "Frontend typecheck"
npm run typecheck
log "Frontend tests"
npm run test
build_workspace "@vpnsale/customer-web" "apps/customer-web"
build_workspace "@vpnsale/admin-web" "apps/admin-web"
build_workspace "@vpnsale/reseller-web" "apps/reseller-web"
log "Shared package validation"
npm run typecheck -w @vpnsale/shared-typescript
npm run typecheck -w @vpnsale/ui
npm run test -w @vpnsale/shared-typescript
npm run test -w @vpnsale/ui
