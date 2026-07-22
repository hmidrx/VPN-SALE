#!/usr/bin/env bash
# Shared hardened installer helpers. Source this file; do not execute it.

redact(){ sed -E 's/(TOKEN|PASSWORD|SECRET|KEY|DATABASE_URL)=([^[:space:]]+)/\1=<redacted>/g'; }

atomic_write_file(){
  local dest="$1" mode="$2" dir tmp
  dir="$(dirname "$dest")"
  install -d -m 0700 "$dir"
  tmp="$(mktemp "$dir/.tmp.$(basename "$dest").XXXXXX")"
  chmod "$mode" "$tmp"
  cat >"$tmp"
  mv -f "$tmp" "$dest"
  chmod "$mode" "$dest"
}

get_env(){ local key="$1" file="$2"; [[ -f "$file" ]] && awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); print; exit}' "$file"; }

set_kv_atomic(){
  local file="$1" key="$2" value="$3" tmp
  tmp="$(mktemp "$(dirname "$file")/.tmp.env.XXXXXX")"
  chmod 600 "$tmp"
  if [[ -f "$file" ]]; then
    awk -v k="$key" -v v="$value" 'BEGIN{done=0} $0 ~ "^" k "=" {$0=k "=" v; done=1} {print} END{if(!done) print k "=" v}' "$file" >"$tmp"
  else
    printf '%s=%s\n' "$key" "$value" >"$tmp"
  fi
  mv -f "$tmp" "$file"; chmod 600 "$file"
}

generate_secret(){ python3 -c 'import secrets; print(secrets.token_urlsafe(48))'; }

urlencode_secret(){ RAW_VALUE="$1" python3 - <<'PY'
import os, urllib.parse
print(urllib.parse.quote(os.environ["RAW_VALUE"], safe=""))
PY
}

build_pg_url(){
  local driver="$1" user="$2" pass="$3" host="$4" port="$5" db="$6" encoded
  encoded="$(urlencode_secret "$pass")"
  printf 'postgresql%s://%s:%s@%s:%s/%s\n' "$driver" "$user" "$encoded" "$host" "$port" "$db"
}

validate_secret_file(){
  local file="$1"
  [[ -f "$file" ]] || return 1
  [[ "$(stat -c %a "$file")" == "600" ]] || return 1
  [[ -s "$file" ]] || return 1
}

ensure_secret_file(){
  local file="$1"
  umask 077
  if [[ -e "$file" ]]; then validate_secret_file "$file" || return 1; return 0; fi
  generate_secret | atomic_write_file "$file" 0600
}

write_state(){
  local file="$1" phase="$2" environment="$3" root_domain="$4" repo="$5" ref="$6" commit="$7" project="$8"
  python3 - "$phase" "$environment" "$root_domain" "$repo" "$ref" "$commit" "$project" <<'PY' | atomic_write_file "$file" 0600
import json, sys
from datetime import datetime, timezone
phase, environment, root_domain, repo, ref, commit, project = sys.argv[1:]
print(json.dumps({
    "environment": environment,
    "root_domain": root_domain,
    "repository": repo,
    "selected_ref": ref,
    "selected_commit": commit,
    "compose_project": project,
    "last_completed_phase": phase,
    "updated_at": datetime.now(timezone.utc).isoformat(),
}, sort_keys=True, indent=2))
PY
}

CADDY_KEY_URL="https://dl.cloudsmith.io/public/caddy/stable/gpg.key"
CADDY_SOURCE_URL="https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt"
CADDY_KEYRING_PATH="/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
CADDY_SOURCE_LIST_PATH="/etc/apt/sources.list.d/caddy-stable.list"

rooted_path(){ local root="${CADDY_APT_ROOT:-}" path="$1"; printf '%s%s\n' "$root" "$path"; }
file_mode(){ stat -c %a "$1"; }
ensure_mode_0644(){ local file="$1"; chmod 0644 "$file"; [[ "$(file_mode "$file")" == "644" ]]; }

install_caddy_apt_repository(){
  local keyring source_list keyring_dir source_dir tmp_key tmp_keyring tmp_source
  keyring="$(rooted_path "$CADDY_KEYRING_PATH")"
  source_list="$(rooted_path "$CADDY_SOURCE_LIST_PATH")"
  keyring_dir="$(dirname "$keyring")"
  source_dir="$(dirname "$source_list")"
  install -d -m 0755 "$keyring_dir" "$source_dir"
  tmp_key="$(mktemp "$keyring_dir/.tmp.caddy-key.XXXXXX")"
  tmp_keyring="$(mktemp "$keyring_dir/.tmp.caddy-keyring.XXXXXX")"
  tmp_source="$(mktemp "$source_dir/.tmp.caddy-source.XXXXXX")"
  rm -f "$tmp_keyring"
  cleanup_caddy_repo_tmp(){ rm -f "$tmp_key" "$tmp_keyring" "$tmp_source"; }

  curl -1fsSL "$CADDY_KEY_URL" -o "$tmp_key" || { cleanup_caddy_repo_tmp; return 1; }
  [[ -s "$tmp_key" ]] || { cleanup_caddy_repo_tmp; return 1; }
  gpg --batch --yes --dearmor --output "$tmp_keyring" "$tmp_key" || { cleanup_caddy_repo_tmp; return 1; }
  [[ -s "$tmp_keyring" ]] || { cleanup_caddy_repo_tmp; return 1; }
  curl -1fsSL "$CADDY_SOURCE_URL" -o "$tmp_source" || { cleanup_caddy_repo_tmp; return 1; }
  [[ -s "$tmp_source" ]] || { cleanup_caddy_repo_tmp; return 1; }
  grep -Fq "$CADDY_KEYRING_PATH" "$tmp_source" || { cleanup_caddy_repo_tmp; return 1; }
  ensure_mode_0644 "$tmp_keyring" || { cleanup_caddy_repo_tmp; return 1; }
  ensure_mode_0644 "$tmp_source" || { cleanup_caddy_repo_tmp; return 1; }
  mv -f "$tmp_keyring" "$keyring"
  mv -f "$tmp_source" "$source_list"
  ensure_mode_0644 "$keyring" || { cleanup_caddy_repo_tmp; return 1; }
  ensure_mode_0644 "$source_list" || { cleanup_caddy_repo_tmp; return 1; }
  rm -f "$tmp_key"
}

apt_get_update_with_caddy_retry(){
  local output status
  output="$(mktemp)"
  if apt-get update >"$output" 2>&1; then rm -f "$output"; return 0; fi
  status=$?
  if grep -Fq 'NO_PUBKEY' "$output" && grep -Fq 'dl.cloudsmith.io/public/caddy/stable' "$output"; then
    cat "$output" >&2
    install_caddy_apt_repository || { rm -f "$output"; return 1; }
    if apt-get update; then rm -f "$output"; return 0; fi
    status=$?
  else
    cat "$output" >&2
  fi
  rm -f "$output"
  return "$status"
}

is_default_caddyfile(){
  local file="${1:-/etc/caddy/Caddyfile}"
  [[ -f "$file" ]] || return 1
  grep -Fq ':80 {' "$file" && grep -Fq 'root * /usr/share/caddy' "$file" && grep -Fq 'file_server' "$file"
}

is_managed_caddyfile(){ local file="${1:-/etc/caddy/Caddyfile}"; [[ -f "$file" ]] && grep -Fq '# vpn-sale-test-server-managed' "$file"; }

render_managed_caddyfile(){
  local domain="$1"
  [[ "$domain" != fast.dr-ping.com && "$domain" != *.fast.dr-ping.com ]] || return 64
  cat <<CADDY
# vpn-sale-test-server-managed
(app_headers) {
  header {
    -Server
  }
  @blocked path /metrics /metrics/* /internal/* /debug/*
  respond @blocked 404
}
app.$domain {
  import app_headers
  reverse_proxy 127.0.0.1:3000 {
    header_up X-Forwarded-Proto {scheme}
    header_up X-Forwarded-Host {host}
    header_up X-Real-IP {remote_host}
  }
}
api.$domain {
  import app_headers
  reverse_proxy 127.0.0.1:8000 {
    header_up X-Forwarded-Proto {scheme}
    header_up X-Forwarded-Host {host}
    header_up X-Real-IP {remote_host}
  }
}
admin.$domain {
  import app_headers
  reverse_proxy 127.0.0.1:3001 {
    header_up X-Forwarded-Proto {scheme}
    header_up X-Forwarded-Host {host}
    header_up X-Real-IP {remote_host}
  }
}
reseller.$domain {
  import app_headers
  reverse_proxy 127.0.0.1:3002 {
    header_up X-Forwarded-Proto {scheme}
    header_up X-Forwarded-Host {host}
    header_up X-Real-IP {remote_host}
  }
}
CADDY
}
