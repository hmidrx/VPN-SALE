#!/usr/bin/env bash
set -Eeuo pipefail

fail=0
report_match() {
  local label="$1" pattern="$2"
  shift 2
  mapfile -t matches < <(git grep -IlE "$pattern" -- "$@" ':(exclude)scripts/security-scan.sh' ':(exclude)scripts/verify-docker.sh' 2>/dev/null || true)
  if (( ${#matches[@]} > 0 )); then
    echo "${label} detected in tracked files:" >&2
    printf '  %s\n' "${matches[@]}" >&2
    fail=1
  fi
}

report_subscription_urls() {
  local label="Subscription URL"
  local tmp
  tmp="$(mktemp)"
  git grep -InE '((vless|trojan|ss)://[A-Za-z0-9%+._~-]{8,}|vmess://[A-Za-z0-9+/=_-]{16,}|subscription://[A-Za-z0-9%+._~-]{8,}|https?://[^[:space:]"'"'"'`<>]*/subscriptions/[A-Za-z0-9_-]{16,}|/subscriptions/[A-Za-z0-9_-]{16,}|/(subscriptions)\?[A-Za-z0-9_&=.-]*token=|sub_open:[A-Za-z0-9_-]{16,}|cfg_open:[A-Za-z0-9_-]{16,})' -- . ':(exclude)scripts/security-scan.sh' ':(exclude)scripts/verify-docker.sh' >"$tmp" 2>/dev/null || true
  mapfile -t matches < <(cut -d: -f1 "$tmp" | sort -u)
  rm -f "$tmp"
  if (( ${#matches[@]} > 0 )); then
    echo "${label} detected in tracked files:" >&2
    printf '  %s\n' "${matches[@]}" >&2
    fail=1
  fi
}

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "Tracked .env file detected." >&2
  fail=1
fi

report_match "Private key material" '-----BEGIN (RSA |EC |OPENSSH |DSA |PRIVATE )?PRIVATE KEY-----' .
report_subscription_urls

# Detect hard-coded literals while avoiding runtime assignments such as
# `token = request.cookies.get(...)` and typed fields such as `password: str`.
# Quoted literals are meaningful in source code, while unquoted literals are
# checked only in configuration and shell files where that syntax represents a
# concrete configured value rather than a Python/TypeScript expression.
sensitive_name='(api[_-]?key|secret|token|cookie|password)'
report_match "Obvious assigned secret" "${sensitive_name}[[:space:]]*[:=][[:space:]]*[\"'][^\"']{8,}[\"']" .
config_paths=(
  '*.yaml' '*.yml' '*.toml' '*.ini' '*.conf' '*.properties'
  '*.env' '*.env.*' '*.sh'
)
report_match "Obvious assigned secret" "${sensitive_name}[[:space:]]*=[[:space:]]*[A-Za-z0-9_./+:-]{8,}([[:space:]]|$)" "${config_paths[@]}"
report_match "Obvious assigned secret" "${sensitive_name}[[:space:]]*:[[:space:]]*[A-Za-z0-9_./+:-]{8,}([[:space:]]|$)" "${config_paths[@]}"

report_match "Panel credential marker" '(xui|pasarguard).*(password|secret|token|api[_-]?key)' .

mapfile -t unsafe < <(git ls-files '.env' '*.pem' '*.key' 'node_modules/*' '.next/*' 'apps/*/.next/*' '*.tsbuildinfo' 2>/dev/null || true)
if (( ${#unsafe[@]} > 0 )); then
  echo "Unsafe tracked generated/sensitive paths detected:" >&2
  printf '  %s\n' "${unsafe[@]}" >&2
  fail=1
fi

if [[ -f package-lock.json ]]; then
  node -e 'const fs=require("fs"); JSON.parse(fs.readFileSync("package-lock.json","utf8")); console.log("package-lock.json parses")'
else
  echo "::warning::package-lock.json is absent; frontend installs are not reproducible yet."
fi

exit "$fail"
