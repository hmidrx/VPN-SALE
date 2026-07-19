#!/usr/bin/env bash
set -Eeuo pipefail

typed_fixture="security-scan-typed-fixture.tmp"
secret_fixture="security-scan-secret-fixture.conf"
safe_secret_fixture="security-scan-safe-secret-fixture.tmp"
subscription_fixture="security-scan-subscription-fixture.tmp"
safe_subscription_fixture="security-scan-safe-subscription-fixture.tmp"
cleanup() {
  git rm -f --quiet "$typed_fixture" "$secret_fixture" "$safe_secret_fixture" "$subscription_fixture" "$safe_subscription_fixture" >/dev/null 2>&1 || true
  rm -f "$typed_fixture" "$secret_fixture" "$safe_secret_fixture" "$subscription_fixture" "$safe_subscription_fixture" \
    scan-safe.out scan-safe.err \
    scan-typed.out scan-typed.err \
    scan-secret.out scan-secret.err \
    scan-safe-secret.out scan-safe-secret.err \
    scan-credential-url.out scan-credential-url.err \
    scan-private-key.out scan-private-key.err \
    scan-self.out scan-self.err \
    scan-subscription.out scan-subscription.err \
    scan-safe-subscription.out scan-safe-subscription.err
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

cat >"$typed_fixture" <<'PY'
from sqlalchemy.orm import Mapped

password_hash: str
encrypted_secret: Mapped[str]
refresh_token_hash: str
token = request.cookies.get("refresh")
SENSITIVE_VALUE_RE = r"(password=|token=|secret=)"
PY
git add --intent-to-add "$typed_fixture"

if ! run_scan scan-typed.out scan-typed.err; then
  echo "Expected typed secret-storage fields and runtime token assignments to pass." >&2
  cat scan-typed.err >&2
  exit 1
fi

git rm -f --quiet "$typed_fixture"

cat >"$safe_subscription_fixture" <<'PY'
SUBSCRIPTION_ROUTE = "/subscriptions/{opaqueToken}"
SUBSCRIPTION_PARTS = {"prefix": "/subscriptions", "parameter": "opaque_token"}
REDACTED_SUBSCRIPTION_URL = "https://customer.example.test/subscriptions/[redacted]"
def build_route(token: str) -> str:
    return f"/subscriptions/{token}"
def build_vless(uuid: str, host: str) -> str:
    return f"vless://{uuid}@{host}:443"
PY
git add --intent-to-add "$safe_subscription_fixture"

if ! run_scan scan-safe-subscription.out scan-safe-subscription.err; then
  echo "Expected explicit placeholders, split route metadata, redacted URLs and runtime builders to pass." >&2
  cat scan-safe-subscription.err >&2
  exit 1
fi

git rm -f --quiet "$safe_subscription_fixture"

cat >"$safe_secret_fixture" <<'EOF_SAFE'
TOKEN="${TOKEN_FROM_ENV:-}"
TOKEN="$(cat "$TOKEN_FILE")"
SECRET="$(openssl rand -hex 32)"
PASSWORD="$(generate_secret)"
STATUS="MISSING"
TOKEN_STATUS="REDACTED"
# Documentation mentions TOKEN and PASSWORD names but assigns no credentials.
normal_package_lock_metadata = {"integrity":"sha512-deadbeef", "resolved":"https://registry.npmjs.org/example/-/example-1.0.0.tgz"}
EOF_SAFE
git add --intent-to-add "$safe_secret_fixture"
if ! run_scan scan-safe-secret.out scan-safe-secret.err; then
  echo "Expected runtime secret assignments, redacted values and package metadata to pass." >&2
  cat scan-safe-secret.err >&2
  exit 1
fi
git rm -f --quiet "$safe_secret_fixture"

secret_cases=()
secret_cases+=("assigned token|TOKEN=\"actual-looking-literal-value\"")
secret_cases+=("assigned password|PASSWORD='literal-password'")
secret_cases+=("database url|DATABASE_URL=\"postgresql://user:password@host/db\"")
secret_cases+=("credential url|url = \"https://user:password@example.invalid/path\"")
secret_cases+=("access token url|url = \"https://example.invalid/path?access_token=actualtokenvalue\"")
for entry in "${secret_cases[@]}"; do
  case_name="${entry%%|*}"
  line="${entry#*|}"
  printf '%s\n' "$line" >"$secret_fixture"
  git add --intent-to-add "$secret_fixture"
  if run_scan scan-secret.out scan-secret.err; then
    echo "Expected security scan to reject ${case_name}." >&2
    exit 1
  fi
  if ! grep -q "$secret_fixture" scan-secret.err; then
    echo "Expected security scan to report fixture for ${case_name}." >&2
    cat scan-secret.err >&2
    exit 1
  fi
  git rm -f --quiet "$secret_fixture"
done

cat >"$secret_fixture" <<'EOF_KEY'
-----BEGIN PRIVATE KEY-----
not-a-real-test-key-fixture
-----END PRIVATE KEY-----
EOF_KEY
git add --intent-to-add "$secret_fixture"
if run_scan scan-private-key.out scan-private-key.err; then
  echo "Expected PEM private key fixture to fail security scan." >&2
  exit 1
fi
git rm -f --quiet "$secret_fixture"

secret_value="fake_test_secret_value_123456789"
printf 'api_key = %s\n' "$secret_value" >"$secret_fixture"
git add --intent-to-add "$secret_fixture"

if run_scan scan-secret.out scan-secret.err; then
  echo "Expected temporary fake secret fixture to fail security scan." >&2
  exit 1
fi

if ! grep -q "$secret_fixture" scan-secret.err; then
  echo "Expected security scan to report the fixture path." >&2
  cat scan-secret.err >&2
  exit 1
fi

if rg --fixed-strings --quiet -- "$secret_value" scan-secret.out scan-secret.err; then
  echo "Security scan printed a secret value." >&2
  exit 1
fi

git rm -f --quiet "$secret_fixture"

subscription_prefix="/subscriptions"
http_origin="https://customer.example.test"
opaque_segment="$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
uuid_reference="$(python - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"
vless_scheme="vless://"
subscription_scheme="subscription://"
subscription_cases=()
subscription_cases+=("complete subscription URL with opaque token|url = \"${http_origin}${subscription_prefix}/${opaque_segment}\"")
subscription_cases+=("subscription URL with UUID reference|url = \"${http_origin}${subscription_prefix}/${uuid_reference}\"")
subscription_cases+=("high-entropy token path|path = \"${subscription_prefix}/${opaque_segment}\"")
subscription_cases+=("token in Telegram callback|callback = \"b:v1:sub_open:${opaque_segment}\"")
subscription_cases+=("token in source-code example|example = \"${subscription_scheme}${opaque_segment}\"")
subscription_cases+=("token in test assertion|assert output.startswith(\"${vless_scheme}${uuid_reference}@edge.example:443\")")

for entry in "${subscription_cases[@]}"; do
  case_name="${entry%%|*}"
  line="${entry#*|}"
  printf '%s\n' "$line" >"$subscription_fixture"
  git add --intent-to-add "$subscription_fixture"
  if run_scan scan-subscription.out scan-subscription.err; then
    echo "Expected security scan to reject ${case_name}." >&2
    exit 1
  fi
  if ! grep -q "$subscription_fixture" scan-subscription.err; then
    echo "Expected security scan to report subscription fixture for ${case_name}." >&2
    cat scan-subscription.err >&2
    exit 1
  fi
  git rm -f --quiet "$subscription_fixture"
done

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
