#!/usr/bin/env bash
set -Eeuo pipefail

fail=0
report_match() {
  local label="$1" pattern="$2"
  shift 2
  mapfile -t matches < <(git grep -IlE -e "$pattern" -- "$@" ':(exclude)scripts/security-scan.sh' ':(exclude)scripts/verify-docker.sh' \
    ':(exclude)scripts/test-security-scan.sh' 2>/dev/null || true)
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
  git grep -InE '((vless|trojan|ss)://[A-Za-z0-9%+._~-]{8,}|vmess://[A-Za-z0-9+/=_-]{16,}|subscription://[A-Za-z0-9%+._~-]{8,}|https?://[^[:space:]"'"'"'`<>]*/subscriptions/[A-Za-z0-9_-]{16,}|/subscriptions/[A-Za-z0-9_-]{16,}|/(subscriptions)\?[A-Za-z0-9_&=.-]*token=|sub_open:[A-Za-z0-9_-]{16,}|cfg_open:[A-Za-z0-9_-]{16,})' -- . ':(exclude)scripts/security-scan.sh' ':(exclude)scripts/verify-docker.sh' \
    ':(exclude)scripts/test-security-scan.sh' >"$tmp" 2>/dev/null || true
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

# Detect hard-coded literals while allowing runtime-only assignments such as
# TOKEN="${TOKEN_FROM_ENV:-}", TOKEN="$(cat "$TOKEN_FILE")", and generated
# values. The scanner reports file paths only so it never prints matched secret
# material in CI logs.
sensitive_name='(api[_-]?key|secret|token|cookie|password|database_url)'
assigned_secret_candidates() {
  git grep -IinE "${sensitive_name}[[:space:]]*[:=][[:space:]]*([\"'][^\"']{8,}[\"']|[A-Za-z0-9_./+:-]{8,}([[:space:]]|$))" -- . \
    ':(exclude)scripts/security-scan.sh' \
    ':(exclude)scripts/verify-docker.sh' \
    ':(exclude)scripts/test-security-scan.sh' 2>/dev/null || true
}

is_safe_assigned_secret_line() {
  local line="$1"
  # npm lockfile integrity hashes and registry metadata are not credentials;
  # credential-bearing package URLs are checked separately below.
  [[ "$line" =~ package-lock\.json:.*\"integrity\"[[:space:]]*:[[:space:]]*\"sha(1|256|384|512)- ]] && return 0
  [[ "$line" =~ \"resolved\"[[:space:]]*:[[:space:]]*\"https://registry\.npmjs\.org/[^?[:space:]\"]+\.tgz\" ]] && return 0
  [[ "$line" =~ package-lock\.json:.*\"(version|license|name)\"[[:space:]]*: ]] && return 0
  # Runtime expansion or command substitution reads/generates a value at install
  # time rather than committing a literal secret.
  # Literal shell syntax marker in scanned text.
  # shellcheck disable=SC2016
  [[ "$line" == *'${'* ]] && return 0
  # Literal command-substitution marker in scanned text.
  # shellcheck disable=SC2016
  [[ "$line" == *'$('* ]] && return 0
  [[ "$line" == *'`'* ]] && return 0
  [[ "$line" == *'_hash'* || "$line" == *'bot_token = bot_token'* || "$line" == *'# noqa: S105'* ]] && return 0
  [[ "$line" =~ (tests|fixtures)/.*(synthetic|inert-test) ]] && return 0
  [[ "$line" =~ (REDACTED|redacted|MISSING|missing|CHANGEME|change-me|example|placeholder) ]] && return 0
  # An unquoted Python attribute/method expression is runtime data, not a
  # committed literal. Keep this language-scoped so shell TOKEN=literal.value
  # remains detectable.
  [[ "$line" =~ \.py:.*=[[:space:]]*[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*(\(|[[:space:]]|$) ]] && return 0
  # Prompts and prose are not assignments even when they contain words like "token:".
  [[ "$line" == *'read -r -s -p'* ]] && return 0
  return 1
}

report_assigned_secrets() {
  local tmp files
  tmp="$(mktemp)"
  while IFS= read -r line; do
    if ! is_safe_assigned_secret_line "$line"; then
      printf '%s\n' "${line%%:*}" >>"$tmp"
    fi
  done < <(assigned_secret_candidates)
  mapfile -t files < <(sort -u "$tmp")
  rm -f "$tmp"
  if (( ${#files[@]} > 0 )); then
    echo "Obvious assigned secret detected in tracked files:" >&2
    printf '  %s\n' "${files[@]}" >&2
    fail=1
  fi
}

report_credential_urls() {
  local tmp files
  tmp="$(mktemp)"
  while IFS= read -r line; do
    # Match a literal expansion marker in scanned text.
    # shellcheck disable=SC2016
    if [[ "$line" == *'${'* || "$line" == *'REDACTED'* || "$line" == *'REPLACE_WITH_'* || "$line" == *'vpnsale_dev_password'* || "$line" == *'ci-placeholder'* || "$line" == *'127.0.0.1'* || "$line" == *'localhost'* || "$line" == *'encoded}@'* ]]; then
      continue
    fi
    printf '%s\n' "${line%%:*}" >>"$tmp"
  done < <(git grep -IinE "(https?|postgresql(\+asyncpg)?|mysql|redis)://[^[:space:]\"'\`/@]+:[^[:space:]\"'\`/@]+@|[?&](access[_-]?token|auth[_-]?token|api[_-]?key|token|password)=[A-Za-z0-9._~+/%-]{8,}" -- . \
    ':(exclude)scripts/security-scan.sh' \
    ':(exclude)scripts/verify-docker.sh' \
    ':(exclude)scripts/test-security-scan.sh' 2>/dev/null || true)
  mapfile -t files < <(sort -u "$tmp")
  rm -f "$tmp"
  if (( ${#files[@]} > 0 )); then
    echo "Credential-bearing URL detected in tracked files:" >&2
    printf '  %s\n' "${files[@]}" >&2
    fail=1
  fi
}

report_assigned_secrets
report_credential_urls

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
