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

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "Tracked .env file detected." >&2
  fail=1
fi
report_match "Private key material" '-----BEGIN (RSA |EC |OPENSSH |DSA |PRIVATE )?PRIVATE KEY-----' .
report_match "Subscription URL" '(vless://|vmess://|trojan://|subscription://)' .
report_match "Obvious assigned secret" '(api[_-]?key|secret|token|cookie|password)[[:space:]]*[:=][[:space:]]*[^[:space:]]{8,}' .
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
