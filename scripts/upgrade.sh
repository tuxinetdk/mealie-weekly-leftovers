#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo/root." >&2; exit 1; }

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="/usr/local/lib/mealie-weekly-leftovers"
CONFIG_FILE="/etc/mealie-update-guard.conf"
GUARD_DST="/usr/local/sbin/mealie-update-guard"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="/var/backups/mealie-weekly-leftovers/${STAMP}"

[[ -f "$CONFIG_FILE" ]] || { echo "Missing $CONFIG_FILE" >&2; exit 1; }
[[ -f "$GUARD_DST" ]] || { echo "Missing $GUARD_DST" >&2; exit 1; }

for c in docker python3 systemctl grep sed awk sha256sum; do
  command -v "$c" >/dev/null 2>&1 || { echo "Missing required command: $c" >&2; exit 1; }
done

python3 -m py_compile \
  "$SOURCE_DIR/patch/apply_patch.py" \
  "$SOURCE_DIR/patch/apply_patch_v323.py" \
  "$SOURCE_DIR/patch/apply_patch_v324.py"
bash -n "$SOURCE_DIR/scripts/mealie-update-guard.sh"

mkdir -p "$BACKUP_ROOT"
cp -a "$CONFIG_FILE" "$BACKUP_ROOT/mealie-update-guard.conf"
cp -a "$GUARD_DST" "$BACKUP_ROOT/mealie-update-guard"
if [[ -d /usr/local/lib/mealie-update-guard ]]; then
  cp -a /usr/local/lib/mealie-update-guard "$BACKUP_ROOT/legacy-library"
fi
if [[ -d "$INSTALL_ROOT" ]]; then
  cp -a "$INSTALL_ROOT" "$BACKUP_ROOT/current-library"
fi

install -d -m 0755 \
  "$INSTALL_ROOT/patch" \
  "$INSTALL_ROOT/locales" \
  "$INSTALL_ROOT/config" \
  "$INSTALL_ROOT/docker"

install -m 0755 "$SOURCE_DIR"/patch/apply_patch*.py "$INSTALL_ROOT/patch/"
install -m 0644 "$SOURCE_DIR"/locales/*.json "$INSTALL_ROOT/locales/"
install -m 0644 "$SOURCE_DIR/config/default.json" "$INSTALL_ROOT/config/default.json"
install -m 0644 "$SOURCE_DIR/docker/Dockerfile.frontend-deps" "$INSTALL_ROOT/docker/Dockerfile.frontend-deps"
install -m 0644 "$SOURCE_DIR/docker/Dockerfile.frontend-deps-pnpm" "$INSTALL_ROOT/docker/Dockerfile.frontend-deps-pnpm"
install -m 0644 "$SOURCE_DIR/docker/Dockerfile.frontend-overlay" "$INSTALL_ROOT/docker/Dockerfile.frontend-overlay"
install -m 0750 "$SOURCE_DIR/scripts/mealie-update-guard.sh" "$GUARD_DST"

set_config() {
  local key="$1" value="$2"
  python3 - "$CONFIG_FILE" "$key" "$value" <<'PY'
from pathlib import Path
import shlex
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
new_line = f"{key}={shlex.quote(value)}"
found = False
out = []
for line in lines:
    if line.startswith(f"{key}="):
        if not found:
            out.append(new_line)
            found = True
        continue
    out.append(line)
if not found:
    out.append(new_line)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

set_config CUSTOM_PATCHER "$INSTALL_ROOT/patch/apply_patch.py"
set_config CUSTOM_PATCH_REV "v1.1.0"
set_config CUSTOM_FAST_BUILD_ENABLED "1"
set_config CUSTOM_FAST_DOCKERFILE "$INSTALL_ROOT/docker/Dockerfile.frontend-overlay"
set_config CUSTOM_DEPS_DOCKERFILE "$INSTALL_ROOT/docker/Dockerfile.frontend-deps"
set_config CUSTOM_PNPM_DEPS_DOCKERFILE "$INSTALL_ROOT/docker/Dockerfile.frontend-deps-pnpm"

chmod 0600 "$CONFIG_FILE"

install -d -m 0755 /etc/systemd/system/mealie-auto-update.service.d
cat > /etc/systemd/system/mealie-auto-update.service.d/timeout.conf <<'UNIT'
[Service]
TimeoutStartSec=60min
UNIT

systemctl daemon-reload

python3 -m py_compile "$INSTALL_ROOT"/patch/apply_patch*.py
bash -n "$GUARD_DST"

echo "Installed Mealie Weekly Leftovers v1.1.0 files."
echo "No Mealie container was stopped or restarted."
echo "Backup: $BACKUP_ROOT"
echo
"$GUARD_DST" dry-run
echo
"$GUARD_DST" status
echo
echo "To rebuild the currently installed Mealie with patch v1.1.0:"
echo "  sudo mealie-update-guard install-leftovers"
