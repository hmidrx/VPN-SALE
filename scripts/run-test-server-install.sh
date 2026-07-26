#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'ERROR: run as root' >&2; exit 1; }
unit=vpn-sale-test-install
case "${1:-}" in
 status) exec systemctl status "$unit.service";; follow) exec journalctl -fu "$unit.service" --no-hostname;;
 start) shift; systemd-run --unit="$unit" --collect --property=Type=exec --property=StandardOutput=journal --property=StandardError=journal --property=SyslogIdentifier="$unit" /opt/vpn-sale/scripts/install-test-server.sh "$@"; printf 'Status: systemctl status %s.service\nFollow: journalctl -fu %s.service\n' "$unit" "$unit";;
 *) echo 'Usage: run-test-server-install.sh {start [installer args...]|status|follow}' >&2; exit 64;; esac
