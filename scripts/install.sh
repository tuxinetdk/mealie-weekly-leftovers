#!/usr/bin/env bash
set -Eeuo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo/root." >&2; exit 1; }

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEALIE_DIR_DEFAULT="/docker_data/mealie"
BACKUP_DIR_DEFAULT="/docker_data/mealie-update-guard/backups"
BUILD_DIR_DEFAULT="/docker_data/mealie-update-guard/build"
INSTALL_ROOT="/usr/local/lib/mealie-weekly-leftovers"
CONFIG_FILE="/etc/mealie-update-guard.conf"

for c in docker curl python3 tar sha256sum flock systemctl grep sed awk sort; do
  command -v "$c" >/dev/null 2>&1 || { echo "Missing required command: $c" >&2; exit 1; }
done

TIMEZONE_DEFAULT="$(cat /etc/timezone 2>/dev/null || true)"
if [[ -z "$TIMEZONE_DEFAULT" ]] && command -v timedatectl >/dev/null 2>&1; then
  TIMEZONE_DEFAULT="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
fi
TIMEZONE_DEFAULT="${TIMEZONE_DEFAULT:-UTC}"

echo "Mealie Weekly Leftovers v1.0.0 installer"
read -r -p "Mealie directory [$MEALIE_DIR_DEFAULT]: " MEALIE_DIR
MEALIE_DIR="${MEALIE_DIR:-$MEALIE_DIR_DEFAULT}"
[[ -f "$MEALIE_DIR/docker-compose.yml" && -f "$MEALIE_DIR/.env" ]] || {
  echo "Could not find docker-compose.yml and .env in $MEALIE_DIR" >&2
  exit 1
}

read -r -p "Backup directory [$BACKUP_DIR_DEFAULT]: " BACKUP_DIR
BACKUP_DIR="${BACKUP_DIR:-$BACKUP_DIR_DEFAULT}"

read -r -p "Backup retention in days [14]: " RETENTION_DAYS
RETENTION_DAYS="${RETENTION_DAYS:-14}"

read -r -p "Server timezone [$TIMEZONE_DEFAULT]: " TIMEZONE
TIMEZONE="${TIMEZONE:-$TIMEZONE_DEFAULT}"

read -r -p "Automatic update time [00:00]: " AUTO_UPDATE_TIME
AUTO_UPDATE_TIME="${AUTO_UPDATE_TIME:-00:00}"
[[ "$AUTO_UPDATE_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || {
  echo "Invalid time; expected HH:MM" >&2
  exit 1
}

printf 'Discord webhook URL (leave blank to disable Discord notifications): '
IFS= read -rs DISCORD_WEBHOOK_URL
printf '\n'

MIGRATION_TS="$(date +%Y%m%d-%H%M%S)"
if [[ -f "$CONFIG_FILE" ]]; then
  cp -a "$CONFIG_FILE" "${CONFIG_FILE}.before-weekly-leftovers.${MIGRATION_TS}"
fi
if [[ -f /usr/local/sbin/mealie-update-guard ]]; then
  cp -a /usr/local/sbin/mealie-update-guard "/usr/local/sbin/mealie-update-guard.before-weekly-leftovers.${MIGRATION_TS}"
fi

install -d -m 0755 \
  "$INSTALL_ROOT/patch" \
  "$INSTALL_ROOT/locales" \
  "$INSTALL_ROOT/config" \
  "$INSTALL_ROOT/docker"

install -m 0755 "$SOURCE_DIR/patch/apply_patch.py" "$INSTALL_ROOT/patch/apply_patch.py"
install -m 0644 "$SOURCE_DIR"/locales/*.json "$INSTALL_ROOT/locales/"
install -m 0644 "$SOURCE_DIR/config/default.json" "$INSTALL_ROOT/config/default.json"
install -m 0644 "$SOURCE_DIR/docker/Dockerfile.frontend-deps" "$INSTALL_ROOT/docker/Dockerfile.frontend-deps"
install -m 0644 "$SOURCE_DIR/docker/Dockerfile.frontend-overlay" "$INSTALL_ROOT/docker/Dockerfile.frontend-overlay"
install -m 0750 "$SOURCE_DIR/scripts/mealie-update-guard.sh" /usr/local/sbin/mealie-update-guard

mkdir -p /var/lib/mealie-update-guard "$BACKUP_DIR" "$BUILD_DIR_DEFAULT"
chmod 0700 /var/lib/mealie-update-guard "$BACKUP_DIR" "$BUILD_DIR_DEFAULT"

{
  printf 'MEALIE_DIR=%q\n' "$MEALIE_DIR"
  printf 'DATA_DIR=%q\n' "$MEALIE_DIR/data"
  printf 'BACKUP_DIR=%q\n' "$BACKUP_DIR"
  printf 'STATE_DIR=%q\n' "/var/lib/mealie-update-guard"
  printf 'RETENTION_DAYS=%q\n' "$RETENTION_DAYS"
  printf 'HEALTH_TIMEOUT=%q\n' "300"
  printf 'DISCORD_WEBHOOK_URL=%q\n' "$DISCORD_WEBHOOK_URL"
  printf 'CUSTOM_PATCH_ENABLED=%q\n' "1"
  printf 'CUSTOM_PATCHER=%q\n' "$INSTALL_ROOT/patch/apply_patch.py"
  printf 'CUSTOM_BUILD_DIR=%q\n' "$BUILD_DIR_DEFAULT"
  printf 'CUSTOM_IMAGE_PREFIX=%q\n' "mealie-weekly-leftovers"
  printf 'CUSTOM_PATCH_REV=%q\n' "v1.0.0"
  printf 'CUSTOM_FAST_BUILD_ENABLED=%q\n' "1"
  printf 'CUSTOM_FAST_DOCKERFILE=%q\n' "$INSTALL_ROOT/docker/Dockerfile.frontend-overlay"
  printf 'CUSTOM_DEPS_DOCKERFILE=%q\n' "$INSTALL_ROOT/docker/Dockerfile.frontend-deps"
  printf 'CUSTOM_UPSTREAM_IMAGE_PREFIX=%q\n' "ghcr.io/mealie-recipes/mealie"
  printf 'CUSTOM_FRONTEND_DEPS_PREFIX=%q\n' "mealie-weekly-leftovers-frontend-deps"
} > "$CONFIG_FILE"
chmod 0600 "$CONFIG_FILE"

cat > /etc/systemd/system/mealie-update-check.service <<'UNIT'
[Unit]
Description=Mealie Update Guard - release check
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/mealie-update-guard check
UNIT

cat > /etc/systemd/system/mealie-update-check.timer <<'UNIT'
[Unit]
Description=Check for stable Mealie releases every hour

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
UNIT

cat > /etc/systemd/system/mealie-auto-update.service <<'UNIT'
[Unit]
Description=Mealie Update Guard - automatic update
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
TimeoutStartSec=30min
ExecStart=/usr/local/sbin/mealie-update-guard update
UNIT

cat > /etc/systemd/system/mealie-auto-update.timer <<UNIT
[Unit]
Description=Install pending stable Mealie update

[Timer]
OnCalendar=*-*-* ${AUTO_UPDATE_TIME}:00 ${TIMEZONE}
Persistent=true
AccuracySec=1s

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now mealie-update-check.timer mealie-auto-update.timer

echo
echo "Installed. Running non-destructive dry-run..."
/usr/local/sbin/mealie-update-guard dry-run

echo
echo "Next recommended commands:"
echo "  sudo mealie-update-guard test-discord"
echo "  sudo mealie-update-guard backup"
echo "  sudo mealie-update-guard install-leftovers"
echo "  sudo mealie-update-guard status"
