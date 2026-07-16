#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '\n==> %s\n' "$*"; }
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
log "Customer web production build"
npm run build -w @vpnsale/customer-web
log "Admin web production build"
npm run build -w @vpnsale/admin-web
log "Reseller web production build"
npm run build -w @vpnsale/reseller-web
log "Shared package validation"
npm run typecheck -w @vpnsale/shared-typescript
npm run typecheck -w @vpnsale/ui
npm run test -w @vpnsale/shared-typescript
npm run test -w @vpnsale/ui
