#!/usr/bin/env bash
set -Eeuo pipefail

fixture="security-scan-fixture.tmp"
cleanup() {
  git rm -f --quiet "$fixture" >/dev/null 2>&1 || true
  rm -f "$fixture" scan-safe.out scan-safe.err scan-secret.out scan-secret.err scan-self.out scan-self.err
}
trap cleanup EXIT

run_scan() {
  local stdout_file="$1" stderr_file="$2"
  scripts/security-scan.sh >"$stdout_file" 2>"$stderr_file"
}

if ! run_scan scan-safe.out scan-safe.err; then
  echo "Expected safe repository state to pass security scan." >&2
  cat scan-safe.err >&2
  exit 1
fi

secret_value="fake_test_secret_value_123456789"
printf 'api_key = %s\n' "$secret_value" >"$fixture"
git add --intent-to-add "$fixture"

if run_scan scan-secret.out scan-secret.err; then
  echo "Expected temporary fake secret fixture to fail security scan." >&2
  exit 1
fi

if ! grep -q "$fixture" scan-secret.err; then
  echo "Expected security scan to report the fixture path." >&2
  cat scan-secret.err >&2
  exit 1
fi

if rg --fixed-strings --quiet -- "$secret_value" scan-secret.out scan-secret.err; then
  echo "Security scan printed a secret value." >&2
  exit 1
fi

git rm -f --quiet "$fixture"

if ! run_scan scan-self.out scan-self.err; then
  echo "Expected scanner pattern definitions not to self-match." >&2
  cat scan-self.err >&2
  exit 1
fi

if grep -E 'scripts/(security-scan|verify-docker)\.sh' scan-self.out scan-self.err >/dev/null; then
  echo "Scanner definitions self-matched." >&2
  cat scan-self.err >&2
  exit 1
fi
