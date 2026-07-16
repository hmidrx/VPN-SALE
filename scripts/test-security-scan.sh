#!/usr/bin/env bash
set -Eeuo pipefail

temp_file="security-scan-fixture.tmp"
secret_value="token = super-secret-fixture-value"
cleanup() {
  git reset -q -- "$temp_file" >/dev/null 2>&1 || true
  rm -f "$temp_file"
}
trap cleanup EXIT

safe_output="$(scripts/security-scan.sh 2>&1)"
if grep -Eq 'scripts/security-scan\.sh|scripts/verify-docker\.sh' <<<"$safe_output"; then
  echo "Security scanner flagged its own intentional regex definitions." >&2
  exit 1
fi

printf '%s\n' "$secret_value" > "$temp_file"
git add "$temp_file"
set +e
fixture_output="$(scripts/security-scan.sh 2>&1)"
fixture_status=$?
set -e
if [[ "$fixture_status" -eq 0 ]]; then
  echo "Security scanner did not fail for a staged secret fixture." >&2
  exit 1
fi
if ! grep -q "$temp_file" <<<"$fixture_output"; then
  echo "Security scanner did not report the fixture file path." >&2
  exit 1
fi
if grep -q "super-secret-fixture-value" <<<"$fixture_output"; then
  echo "Security scanner printed a secret value." >&2
  exit 1
fi

echo "Security scanner self-test passed"
