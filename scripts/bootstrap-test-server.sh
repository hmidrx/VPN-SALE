#!/usr/bin/env bash
set -euo pipefail
REPO="https://github.com/hmidrx/VPN-SALE.git"; REF="main"; INSTALL_DIR="/opt/vpn-sale"; installer_args=()
usage(){ cat <<'HELP'
Usage: bootstrap-test-server.sh [--repo URL] [--ref REF] [--install-dir DIR] -- INSTALLER_ARGS...
Clones a complete, exact checkout before executing its canonical installer.
HELP
}
while (($#)); do case "$1" in
 --repo) REPO="${2:?}"; shift 2;; --ref) REF="${2:?}"; shift 2;; --install-dir) INSTALL_DIR="${2:?}"; shift 2;;
 --help) usage; exit 0;; --) shift; installer_args=("$@"); break;; *) installer_args+=("$1"); shift;; esac; done
[[ $(id -u) -eq 0 ]] || { echo 'ERROR: bootstrap must run as root' >&2; exit 1; }
resolved="$(git ls-remote "$REPO" "$REF" "refs/heads/$REF" "refs/tags/$REF^{}" | awk 'NR==1{print $1}')"
[[ "$resolved" =~ ^[0-9a-f]{40}$ ]] || { echo 'ERROR: ref did not resolve to one commit' >&2; exit 1; }
printf 'Selected ref: %s\nSelected commit: %s\n' "$REF" "$resolved"
[[ ! -e "$INSTALL_DIR" || -d "$INSTALL_DIR/.git" ]] || { echo "ERROR: install path is not a Git checkout: $INSTALL_DIR" >&2; exit 1; }
[[ -d "$INSTALL_DIR/.git" ]] || git clone --no-checkout "$REPO" "$INSTALL_DIR"
git -C "$INSTALL_DIR" diff --quiet --ignore-submodules -- || { echo 'ERROR: tracked worktree is dirty' >&2; exit 1; }
git -C "$INSTALL_DIR" fetch --no-tags origin "$resolved"
git -C "$INSTALL_DIR" checkout --detach --force "$resolved"
exec "$INSTALL_DIR/scripts/install-test-server.sh" --repo "$REPO" --ref "$REF" --expected-commit "$resolved" --install-dir "$INSTALL_DIR" "${installer_args[@]}"
