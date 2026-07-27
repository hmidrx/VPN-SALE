#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/test-server-installer-lib.sh disable=SC1091
source "$repo_root/scripts/test-server-installer-lib.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

equal=(
  'https://app.dr-ping.com|https://app.dr-ping.com/'
  'https://app.dr-ping.com:443|https://app.dr-ping.com/'
  'https://app.dr-ping.com:8443|https://app.dr-ping.com:8443/'
)
different=(
  'http://app.dr-ping.com|https://app.dr-ping.com'
  'https://evil.example|https://app.dr-ping.com'
  'https://app.dr-ping.com.evil.example|https://app.dr-ping.com'
  'https://app.dr-ping.com/path|https://app.dr-ping.com/'
  'https://app.dr-ping.com/?unexpected=1|https://app.dr-ping.com/'
  'https://app.dr-ping.com:8443|https://app.dr-ping.com:9443'
)
for pair in "${equal[@]}"; do IFS='|' read -r left right <<<"$pair"; https_url_equal "$left" "$right"; done
for pair in "${different[@]}"; do
  IFS='|' read -r left right <<<"$pair"
  if https_url_equal "$left" "$right"; then echo "unsafe URL match: $pair" >&2; exit 1; fi
done

cat >"$tmp/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
config="$(cat)"
method="${config##*/}"
method="${method%%\"*}"
printf '%s\n' "$method" >>"${CALLS:?}"
[[ "$config" != *"${SECRET_TOKEN:?}"* ]] || : # token is expected only on private stdin
if [[ "${REJECT_METHOD:-}" == "$method" ]]; then printf '{"ok":false}\n'; exit 0; fi
printf '{"ok":true,"result":true}\n'
SH
chmod +x "$tmp/curl"
secret_token='123456789:abcdefghijklmnopqrstuvwxyz_SECRET_TOKEN'
export PATH="$tmp:$PATH" CALLS="$tmp/calls" SECRET_TOKEN="$secret_token"
output="$(telegram_configure_default_menu "$secret_token" 'https://app.dr-ping.com' 2>&1)"
[[ -z "$output" && "$(cat "$CALLS")" == $'deleteWebhook\nsetChatMenuButton' ]]
telegram_configure_default_menu "$secret_token" 'https://app.dr-ping.com' >/dev/null 2>&1
[[ "$(grep -c '^setChatMenuButton$' "$CALLS")" == 2 ]]
if REJECT_METHOD=setChatMenuButton telegram_configure_default_menu "$secret_token" 'https://app.dr-ping.com' >"$tmp/out" 2>&1; then
  echo 'rejected Telegram operation passed' >&2; exit 1
fi
if grep -Fq "$secret_token" "$tmp/out"; then echo 'Telegram token leaked to output' >&2; exit 1; fi

rg -Fq 'telegram_configure_default_menu "$BOT_TOKEN" "$CUSTOMER_ORIGIN"' "$repo_root/scripts/install-test-server.sh"
rg -Fq '.result.type // empty' "$repo_root/scripts/smoke-test-test-server.sh"
rg -Fq 'telegram bot polling initialization successful' "$repo_root/scripts/verify-test-server.sh"
printf 'Telegram runtime hotfix regression tests passed\n'
