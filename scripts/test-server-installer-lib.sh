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
