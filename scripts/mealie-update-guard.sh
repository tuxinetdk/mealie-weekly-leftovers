#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CONFIG_FILE="${MUG_CONFIG:-/etc/mealie-update-guard.conf}"
[[ -r "$CONFIG_FILE" ]] || { echo "Missing config: $CONFIG_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG_FILE"

: "${MEALIE_DIR:=/docker_data/mealie}"
: "${DATA_DIR:=$MEALIE_DIR/data}"
: "${BACKUP_DIR:=/docker_data/mealie-update-guard/backups}"
: "${STATE_DIR:=/var/lib/mealie-update-guard}"
: "${RETENTION_DAYS:=14}"
: "${HEALTH_TIMEOUT:=300}"
: "${RELEASE_API:=https://api.github.com/repos/mealie-recipes/mealie/releases/latest}"
: "${DISCORD_WEBHOOK_URL:=}"
: "${CUSTOM_PATCH_ENABLED:=1}"
: "${CUSTOM_PATCHER:=/usr/local/lib/mealie-weekly-leftovers/patch/apply_patch.py}"
: "${CUSTOM_BUILD_DIR:=/docker_data/mealie-update-guard/build}"
: "${CUSTOM_IMAGE_PREFIX:=mealie-weekly-leftovers}"
: "${CUSTOM_PATCH_REV:=v1.1.0}"
: "${CUSTOM_FAST_BUILD_ENABLED:=1}"
: "${CUSTOM_FAST_DOCKERFILE:=/usr/local/lib/mealie-weekly-leftovers/docker/Dockerfile.frontend-overlay}"
: "${CUSTOM_DEPS_DOCKERFILE:=/usr/local/lib/mealie-weekly-leftovers/docker/Dockerfile.frontend-deps}"
: "${CUSTOM_PNPM_DEPS_DOCKERFILE:=/usr/local/lib/mealie-weekly-leftovers/docker/Dockerfile.frontend-deps-pnpm}"
: "${CUSTOM_UPSTREAM_IMAGE_PREFIX:=ghcr.io/mealie-recipes/mealie}"
: "${CUSTOM_FRONTEND_DEPS_PREFIX:=mealie-weekly-leftovers-frontend-deps}"

ENV_FILE="$MEALIE_DIR/.env"
COMPOSE_FILE="$MEALIE_DIR/docker-compose.yml"
PENDING_FILE="$STATE_DIR/pending-version"
PENDING_NAME_FILE="$STATE_DIR/pending-name"
BLOCKED_FILE="$STATE_DIR/blocked-version"
LAST_SUCCESS_FILE="$STATE_DIR/last-success"
LAST_FAILURE_FILE="$STATE_DIR/last-failure"
BUILD_FAILURE_STAGE_FILE="$STATE_DIR/last-build-failure-stage"
LAST_BUILD_LOG_FILE="$STATE_DIR/last-build-log"
CUSTOM_OVERRIDE_FILE="$STATE_DIR/docker-compose.weekly-leftovers.yml"
ACTIVE_CUSTOM_IMAGE_FILE="$STATE_DIR/active-custom-image"
LOCK_FILE="/run/lock/mealie-update-guard.lock"

mkdir -p "$BACKUP_DIR" "$STATE_DIR" "$CUSTOM_BUILD_DIR" "$(dirname "$LOCK_FILE")"

log() { printf '%s %s\n' "$(date '+%F %T%z')" "$*" >&2; }
die() { log "ERROR: $*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"; }
for c in docker curl python3 tar sha256sum flock grep sed awk sort tee; do need "$c"; done

discord() {
  local message="$1"
  message="${message//\\n/$'\n'}"
  [[ -n "$DISCORD_WEBHOOK_URL" ]] || return 0
  local payload
  payload="$(python3 - "$message" <<'PY'
import json, sys
print(json.dumps({"content": sys.argv[1]}, ensure_ascii=False))
PY
)"
  if ! curl -fsS --max-time 15 -H 'Content-Type: application/json' -d "$payload" "$DISCORD_WEBHOOK_URL" >/dev/null; then
    log "WARNING: Discord notification failed"
  fi
}

current_version() {
  [[ -r "$ENV_FILE" ]] || die "Missing $ENV_FILE"
  local v
  v="$(grep -E '^MEALIE_VERSION=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r')"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  [[ "$v" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "MEALIE_VERSION is not pinned to an exact stable version: '$v'"
  printf '%s\n' "$v"
}

version_gt() {
  local a="$1" b="$2"
  [[ "$a" != "$b" && "$(printf '%s\n%s\n' "$a" "$b" | sort -V | tail -n1)" == "$a" ]]
}

major_of() { printf '%s\n' "$1" | sed -E 's/^v([0-9]+).*/\1/'; }

compose_service_for_container() {
  local container="$1"
  docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$container" 2>/dev/null || true
}


custom_image_tag() {
  local version="$1"
  printf '%s:%s-%s\n' "$CUSTOM_IMAGE_PREFIX" "${version#v}" "$CUSTOM_PATCH_REV"
}

compose_active() {
  if [[ -f "$CUSTOM_OVERRIDE_FILE" ]]; then
    docker compose --project-directory "$MEALIE_DIR" -f "$COMPOSE_FILE" -f "$CUSTOM_OVERRIDE_FILE" "$@"
  else
    docker compose --project-directory "$MEALIE_DIR" -f "$COMPOSE_FILE" "$@"
  fi
}

write_custom_override() {
  local service="$1" image="$2"
  [[ "$service" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Unsafe Compose service name: $service"
  [[ "$image" =~ ^[A-Za-z0-9._/:@-]+$ ]] || die "Unsafe custom image tag: $image"

  cat > "$CUSTOM_OVERRIDE_FILE" <<EOF
services:
  $service:
    image: $image
EOF
}

frontend_package_manager() {
  local source_dir="$1" has_yarn=0 has_pnpm=0
  [[ -f "$source_dir/frontend/yarn.lock" ]] && has_yarn=1
  [[ -f "$source_dir/frontend/pnpm-lock.yaml" ]] && has_pnpm=1

  if (( has_pnpm == 1 && has_yarn == 0 )); then
    printf 'pnpm\n'
    return 0
  fi
  if (( has_yarn == 1 && has_pnpm == 0 )); then
    printf 'yarn\n'
    return 0
  fi

  if (( has_pnpm == 1 && has_yarn == 1 )); then
    if grep -Eq 'RUN[[:space:]]+pnpm|pnpm[[:space:]]+(clean-install|install|generate)' "$source_dir/docker/Dockerfile"; then
      printf 'pnpm\n'
      return 0
    fi
    if grep -Eq 'RUN[[:space:]]+yarn|yarn[[:space:]]+(install|generate)' "$source_dir/docker/Dockerfile"; then
      printf 'yarn\n'
      return 0
    fi
  fi

  return 1
}

frontend_deps_hash() {
  local source_dir="$1" manager="$2"
  case "$manager" in
    yarn)
      [[ -f "$source_dir/frontend/package.json" && -f "$source_dir/frontend/yarn.lock" ]] || return 1
      cat "$source_dir/frontend/package.json" "$source_dir/frontend/yarn.lock"
      ;;
    pnpm)
      [[ -f "$source_dir/frontend/package.json" && -f "$source_dir/frontend/pnpm-lock.yaml" ]] || return 1
      cat "$source_dir/frontend/package.json" "$source_dir/frontend/pnpm-lock.yaml"
      [[ -f "$source_dir/frontend/pnpm-workspace.yaml" ]] && cat "$source_dir/frontend/pnpm-workspace.yaml"
      ;;
    *)
      return 1
      ;;
  esac | sha256sum | awk '{print substr($1,1,16)}'
}

frontend_node_image() {
  local source_dir="$1"
  awk '$1 == "FROM" && $2 ~ /^node:/ { print $2; exit }' "$source_dir/docker/Dockerfile"
}

ensure_frontend_deps_image() {
  local source_dir="$1" deps_hash="$2" node_image="$3" manager="$4" build_log="$5"
  local deps_tag="${CUSTOM_FRONTEND_DEPS_PREFIX}:${manager}-${deps_hash}"
  local deps_dockerfile=""

  case "$manager" in
    yarn) deps_dockerfile="$CUSTOM_DEPS_DOCKERFILE" ;;
    pnpm) deps_dockerfile="$CUSTOM_PNPM_DEPS_DOCKERFILE" ;;
    *) return 1 ;;
  esac

  if docker image inspect "$deps_tag" >/dev/null 2>&1; then
    log "Frontend dependency image already cached: $deps_tag"
    printf '%s\n' "$deps_tag"
    return 0
  fi

  [[ -r "$deps_dockerfile" ]] || {
    log "Fast-build dependency Dockerfile is missing for $manager: $deps_dockerfile"
    return 1
  }

  log "Creating $manager frontend dependency cache image $deps_tag"
  if ! DOCKER_BUILDKIT=1 docker build \
      --build-arg "NODE_IMAGE=$node_image" \
      --label "io.github.mealie-weekly-leftovers.frontend.package_manager=$manager" \
      --label "io.github.mealie-weekly-leftovers.frontend.deps_hash=$deps_hash" \
      -f "$deps_dockerfile" \
      -t "$deps_tag" \
      "$source_dir" 2>&1 | tee -a "$build_log" >&2; then
    log "Failed to build $manager frontend dependency cache image $deps_tag"
    return 1
  fi

  docker image inspect "$deps_tag" >/dev/null 2>&1 || return 1
  printf '%s\n' "$deps_tag"
}

ensure_upstream_base_image() {
  local version="$1" build_log="$2" image="${CUSTOM_UPSTREAM_IMAGE_PREFIX}:${version}"

  if docker image inspect "$image" >/dev/null 2>&1; then
    log "Official Mealie base image already available locally: $image"
    printf '%s\n' "$image"
    return 0
  fi

  log "Pulling official Mealie base image $image"
  if ! docker pull "$image" 2>&1 | tee -a "$build_log" >&2; then
    log "Failed to pull official Mealie base image: $image"
    return 1
  fi

  printf '%s\n' "$image"
}

try_fast_build() {
  local version="$1" tag="$2" source_dir="$3" build_log="$4"
  local manager deps_hash node_image deps_tag base_image

  [[ -r "$CUSTOM_FAST_DOCKERFILE" ]] || {
    log "Fast-build Dockerfile is missing: $CUSTOM_FAST_DOCKERFILE"
    return 1
  }

  manager="$(frontend_package_manager "$source_dir")" || {
    log "FAST BUILD unavailable: no supported Yarn/pnpm lockfile could be selected"
    return 1
  }
  log "FAST BUILD: detected frontend package manager: $manager"

  deps_hash="$(frontend_deps_hash "$source_dir" "$manager")" || {
    log "FAST BUILD unavailable: could not calculate $manager dependency hash"
    return 1
  }

  node_image="$(frontend_node_image "$source_dir")"
  [[ -n "$node_image" ]] || {
    log "FAST BUILD unavailable: could not determine Node image from upstream Dockerfile"
    return 1
  }

  deps_tag="$(ensure_frontend_deps_image "$source_dir" "$deps_hash" "$node_image" "$manager" "$build_log")" || return 1
  base_image="$(ensure_upstream_base_image "$version" "$build_log")" || return 1

  log "FAST BUILD: compiling patched frontend with $manager and overlaying it onto $base_image"
  if ! DOCKER_BUILDKIT=1 docker build \
      --label "io.github.mealie-weekly-leftovers.upstream=$version" \
      --label "io.github.mealie-weekly-leftovers.feature.patch=$CUSTOM_PATCH_REV" \
      --label "io.github.mealie-weekly-leftovers.build_mode=frontend-overlay" \
      --label "io.github.mealie-weekly-leftovers.frontend.package_manager=$manager" \
      --label "io.github.mealie-weekly-leftovers.frontend.deps_hash=$deps_hash" \
      --build-arg "FRONTEND_DEPS_IMAGE=$deps_tag" \
      --build-arg "BASE_IMAGE=$base_image" \
      --build-arg "PACKAGE_MANAGER=$manager" \
      --build-arg "COMMIT=${version}-weekly-leftovers-${CUSTOM_PATCH_REV}" \
      -f "$CUSTOM_FAST_DOCKERFILE" \
      -t "$tag" \
      "$source_dir" 2>&1 | tee -a "$build_log" >&2; then
    log "FAST BUILD failed for custom image $tag"
    return 1
  fi

  docker image inspect "$tag" >/dev/null 2>&1
}

full_build() {
  local version="$1" tag="$2" source_dir="$3" build_log="$4"
  log "FULL BUILD: building custom image $tag using upstream Dockerfile"
  if ! docker build \
      --pull \
      --label "io.github.mealie-weekly-leftovers.upstream=$version" \
      --label "io.github.mealie-weekly-leftovers.feature.patch=$CUSTOM_PATCH_REV" \
      --label "io.github.mealie-weekly-leftovers.build_mode=full" \
      --build-arg "COMMIT=${version}-weekly-leftovers-${CUSTOM_PATCH_REV}" \
      -f "$source_dir/docker/Dockerfile" \
      -t "$tag" \
      "$source_dir" 2>&1 | tee -a "$build_log" >&2; then
    log "FULL BUILD failed for custom image $tag"
    return 1
  fi

  docker image inspect "$tag" >/dev/null 2>&1
}

build_custom_image() {
  local version="$1" tag work tarball source_dir source_url build_log
  local fast_failed=0

  [[ "$CUSTOM_PATCH_ENABLED" == "1" ]] || die "build_custom_image called while CUSTOM_PATCH_ENABLED=$CUSTOM_PATCH_ENABLED"
  [[ -r "$CUSTOM_PATCHER" ]] || {
    log "Custom Weekly Leftovers patcher is missing or unreadable: $CUSTOM_PATCHER"
    return 1
  }

  tag="$(custom_image_tag "$version")"
  if docker image inspect "$tag" >/dev/null 2>&1; then
    log "Custom image already exists: $tag"
    printf '%s\n' "$tag"
    return 0
  fi

  build_log="$STATE_DIR/build-${version#v}-${CUSTOM_PATCH_REV}-$(date '+%Y%m%d-%H%M%S').log"
  : > "$build_log"
  chmod 0600 "$build_log" 2>/dev/null || true
  printf '%s\n' "$build_log" > "$LAST_BUILD_LOG_FILE"
  rm -f "$BUILD_FAILURE_STAGE_FILE"
  log "Build log: $build_log"

  work="$(mktemp -d "$CUSTOM_BUILD_DIR/${version#v}.XXXXXX")"
  tarball="$work/source.tar.gz"
  source_url="https://github.com/mealie-recipes/mealie/archive/refs/tags/${version}.tar.gz"

  log "Downloading Mealie source for $version"
  if ! curl -fsSL --max-time 180 "$source_url" -o "$tarball"; then
    printf 'download\n' > "$BUILD_FAILURE_STAGE_FILE"
    log "Failed to download Mealie source for $version"
    rm -rf "$work"
    return 1
  fi

  if ! tar -xzf "$tarball" -C "$work"; then
    printf 'extract\n' > "$BUILD_FAILURE_STAGE_FILE"
    log "Failed to extract Mealie source for $version"
    rm -rf "$work"
    return 1
  fi

  source_dir="$(find "$work" -mindepth 1 -maxdepth 1 -type d -name 'mealie-*' -print -quit)"
  [[ -n "$source_dir" && -f "$source_dir/docker/Dockerfile" ]] || {
    printf 'source\n' > "$BUILD_FAILURE_STAGE_FILE"
    log "Could not locate extracted Mealie source tree"
    rm -rf "$work"
    return 1
  }

  log "Checking Weekly Leftovers patch compatibility against $version"
  if ! python3 "$CUSTOM_PATCHER" --root "$source_dir" --check 2>&1 | tee -a "$build_log" >&2; then
    printf 'compatibility\n' > "$BUILD_FAILURE_STAGE_FILE"
    log "Weekly Leftovers patch is not compatible with $version"
    rm -rf "$work"
    return 1
  fi

  log "Applying Weekly Leftovers patch to $version source"
  if ! python3 "$CUSTOM_PATCHER" --root "$source_dir" --apply 2>&1 | tee -a "$build_log" >&2; then
    printf 'patch\n' > "$BUILD_FAILURE_STAGE_FILE"
    log "Weekly Leftovers patch application failed for $version"
    rm -rf "$work"
    return 1
  fi

  if [[ "$CUSTOM_FAST_BUILD_ENABLED" == "1" ]]; then
    if try_fast_build "$version" "$tag" "$source_dir" "$build_log"; then
      log "FAST BUILD completed successfully: $tag"
    else
      fast_failed=1
      docker image rm -f "$tag" >/dev/null 2>&1 || true
      log "WARNING: FAST BUILD failed for $version; falling back automatically to FULL BUILD"
      discord "⚠️ **Mealie $version Fast Build failed** on $(hostname).\nThe Weekly Leftovers compatibility check passed, so the guard is trying the official full Docker build instead.\nCurrent Mealie remains online and has not been stopped."
    fi
  fi

  if [[ "$CUSTOM_FAST_BUILD_ENABLED" != "1" || "$fast_failed" == "1" ]]; then
    if ! full_build "$version" "$tag" "$source_dir" "$build_log"; then
      if [[ "$fast_failed" == "1" ]]; then
        printf 'full-after-fast\n' > "$BUILD_FAILURE_STAGE_FILE"
      else
        printf 'full\n' > "$BUILD_FAILURE_STAGE_FILE"
      fi
      rm -rf "$work"
      return 1
    fi
  fi

  docker image inspect "$tag" >/dev/null 2>&1 || {
    printf 'inspect\n' > "$BUILD_FAILURE_STAGE_FILE"
    log "Built image cannot be inspected: $tag"
    rm -rf "$work"
    return 1
  }

  rm -rf "$work"
  rm -f "$BUILD_FAILURE_STAGE_FILE"
  printf '%s\n' "$tag"
}

container_env() {
  local container="$1" key="$2"
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" \
    | grep -E "^${key}=" | tail -n1 | cut -d= -f2-
}

health_status() {
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' mealie 2>/dev/null || printf 'missing\n'
}

wait_healthy() {
  local timeout="${1:-$HEALTH_TIMEOUT}" elapsed=0 status last_status=""
  while (( elapsed < timeout )); do
    status="$(health_status)"
    if [[ "$status" != "$last_status" ]]; then
      log "Mealie health while waiting: $status (${elapsed}s/${timeout}s)"
      last_status="$status"
    fi

    case "$status" in
      healthy) return 0 ;;
      running)
        # Containers without a Docker HEALTHCHECK are accepted as running.
        # When a HEALTHCHECK exists, health_status() returns starting/unhealthy/healthy instead.
        return 0
        ;;
      exited|dead)
        return 1
        ;;
      starting|unhealthy|missing)
        # Do not fail immediately. Mealie can need 20-40+ seconds to initialize its
        # database/backend and Docker may report transient unhealthy/missing states
        # while Compose recreates the container. Keep waiting until HEALTH_TIMEOUT.
        ;;
      *)
        log "WARNING: Unknown Mealie health state '$status'; continuing to wait"
        ;;
    esac

    sleep 5
    elapsed=$((elapsed+5))
  done

  log "Mealie did not become healthy within ${timeout}s (last status=$status)"
  return 1
}

capture_mealie_diagnostics() {
  local label="${1:-failure}" ts out
  ts="$(date '+%Y-%m-%d_%H%M%S')"
  out="$STATE_DIR/diagnostics-${ts}-${label}.log"

  {
    printf 'Mealie Update Guard diagnostics\n'
    printf 'Captured: %s\n' "$(date -Is)"
    printf 'Label: %s\n' "$label"
    printf 'Version: %s\n' "$(current_version 2>/dev/null || true)"
    printf 'Configured Feature revision: %s\n' "$CUSTOM_PATCH_REV"
    printf 'Health: %s\n' "$(health_status)"
    printf '\n--- docker inspect state ---\n'
    docker inspect -f '{{json .State}}' mealie 2>&1 || true
    printf '\n--- docker health log ---\n'
    docker inspect -f '{{range .State.Health.Log}}{{println .Start "exit=" .ExitCode}}{{println .Output}}{{end}}' mealie 2>&1 || true
    printf '\n--- docker logs (last 250 lines) ---\n'
    docker logs --tail 250 mealie 2>&1 || true
  } > "$out"

  chmod 0600 "$out" 2>/dev/null || true
  log "Candidate diagnostics saved: $out"
  printf '%s\n' "$out"
}

preflight() {
  [[ -d "$MEALIE_DIR" ]] || die "Missing Mealie directory: $MEALIE_DIR"
  [[ -d "$DATA_DIR" ]] || die "Missing Mealie data directory: $DATA_DIR"
  [[ -f "$COMPOSE_FILE" ]] || die "Missing compose file: $COMPOSE_FILE"
  [[ -f "$ENV_FILE" ]] || die "Missing env file: $ENV_FILE"
  docker info >/dev/null 2>&1 || die "Docker daemon is not available"
  docker inspect mealie >/dev/null 2>&1 || die "Container 'mealie' not found"
  docker inspect mealie-postgres >/dev/null 2>&1 || die "Container 'mealie-postgres' not found"
  local hs
  hs="$(health_status)"
  [[ "$hs" == "healthy" || "$hs" == "running" ]] || die "Mealie is not healthy before update (status=$hs)"
  [[ "$(docker inspect -f '{{.State.Running}}' mealie-postgres)" == "true" ]] || die "PostgreSQL container is not running"
}

fetch_release() {
  local tmp
  tmp="$(mktemp)"
  if ! curl -fsSL --max-time 30 \
      -H 'Accept: application/vnd.github+json' \
      -H 'User-Agent: mealie-update-guard/1.0' \
      "$RELEASE_API" > "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  python3 - "$tmp" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    d=json.load(f)
print(d.get('tag_name',''))
print('1' if d.get('prerelease') else '0')
print('1' if d.get('draft') else '0')
print((d.get('name') or '').replace('\n',' '))
body=(d.get('body') or '').replace('\r','')
print(body)
PY
  rm -f "$tmp"
}

check_release() {
  exec 9>"$LOCK_FILE"; flock -n 9 || { log "Another guard process is running; check skipped"; return 0; }
  local current release latest prerelease draft name body
  current="$(current_version)"
  if ! release="$(fetch_release)"; then
    log "Release check failed"
    discord "⚠️ **Mealie Update Guard**: Release check failed on $(hostname). Current version remains **$current**."
    return 1
  fi
  latest="$(printf '%s\n' "$release" | sed -n '1p')"
  prerelease="$(printf '%s\n' "$release" | sed -n '2p')"
  draft="$(printf '%s\n' "$release" | sed -n '3p')"
  name="$(printf '%s\n' "$release" | sed -n '4p')"
  body="$(printf '%s\n' "$release" | sed -n '5,$p')"

  [[ "$latest" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Unexpected release tag from GitHub: '$latest'"
  [[ "$prerelease" == "0" && "$draft" == "0" ]] || { log "Latest GitHub release is prerelease/draft; ignored"; return 0; }

  if [[ "$latest" == "$current" ]]; then
    rm -f "$PENDING_FILE" "$PENDING_NAME_FILE"
    log "No update available ($current)"
    return 0
  fi
  if ! version_gt "$latest" "$current"; then
    log "Remote release $latest is not newer than local $current; ignored"
    return 0
  fi

  local reason=""
  if [[ "$(major_of "$latest")" != "$(major_of "$current")" ]]; then
    reason="major version change"
  elif printf '%s\n' "$body" | grep -Eiq 'breaking[[:space:]-]+change|manual[[:space:]-]+(migration|upgrade)|requires[[:space:]].*manual'; then
    reason="release notes contain a breaking/manual-upgrade warning"
  fi

  if [[ -n "$reason" ]]; then
    if [[ ! -f "$BLOCKED_FILE" || "$(cat "$BLOCKED_FILE")" != "$latest" ]]; then
      printf '%s\n' "$latest" > "$BLOCKED_FILE"
      discord "⛔ **Mealie $latest was NOT scheduled** on $(hostname): $reason. Current version stays **$current**. Review the release manually."
    fi
    rm -f "$PENDING_FILE" "$PENDING_NAME_FILE"
    log "Blocked $latest: $reason"
    return 0
  fi

  if [[ ! -f "$PENDING_FILE" || "$(cat "$PENDING_FILE")" != "$latest" ]]; then
    printf '%s\n' "$latest" > "$PENDING_FILE"
    printf '%s\n' "$name" > "$PENDING_NAME_FILE"
    discord "🍴 **Mealie update available** on $(hostname)\nCurrent: **$current**\nAvailable: **$latest**${name:+ — $name}\nScheduled: **automatic maintenance timer**\nThe guard will first validate/build the custom **Weekly Leftovers** image while the current Mealie stays online. Only after a successful build will it stop Mealie, create and verify the PostgreSQL + /app/data backup, switch image, and run health checks."
  fi
  log "Update pending: $current -> $latest"
}

backup_create() {
  local old_version="$1"
  local ts backup pg_user pg_pass pg_db
  ts="$(date '+%Y-%m-%d_%H%M%S')"
  backup="$BACKUP_DIR/${ts}_${old_version}"
  mkdir -p "$backup"

  pg_user="$(container_env mealie-postgres POSTGRES_USER)"
  pg_pass="$(container_env mealie-postgres POSTGRES_PASSWORD)"
  pg_db="$(container_env mealie-postgres POSTGRES_DB)"
  [[ -n "$pg_user" && -n "$pg_db" ]] || die "Could not read PostgreSQL database settings from mealie-postgres"

  cp -a "$ENV_FILE" "$backup/.env"
  cp -a "$COMPOSE_FILE" "$backup/docker-compose.yml"
  [[ -f "$CUSTOM_OVERRIDE_FILE" ]] && cp -a "$CUSTOM_OVERRIDE_FILE" "$backup/docker-compose.weekly-leftovers.yml"
  [[ -f "$ACTIVE_CUSTOM_IMAGE_FILE" ]] && cp -a "$ACTIVE_CUSTOM_IMAGE_FILE" "$backup/active-custom-image"
  printf '%s\n' "$old_version" > "$backup/old-version.txt"
  docker inspect mealie mealie-postgres > "$backup/docker-inspect.json"

  log "Creating PostgreSQL logical backup"
  if ! docker exec -e "PGPASSWORD=$pg_pass" mealie-postgres \
      pg_dump -U "$pg_user" -d "$pg_db" -Fc > "$backup/postgres.dump"; then
    rm -rf "$backup"
    die "PostgreSQL pg_dump failed"
  fi
  [[ -s "$backup/postgres.dump" ]] || { rm -rf "$backup"; die "PostgreSQL dump is empty"; }
  if ! cat "$backup/postgres.dump" | docker exec -i mealie-postgres pg_restore -l >/dev/null; then
    rm -rf "$backup"
    die "PostgreSQL dump verification failed"
  fi

  log "Creating Mealie /app/data backup"
  tar -C "$DATA_DIR" -czf "$backup/mealie-data.tar.gz" .
  tar -tzf "$backup/mealie-data.tar.gz" >/dev/null || { rm -rf "$backup"; die "Data archive verification failed"; }

  local checksum_files=(.env docker-compose.yml docker-inspect.json old-version.txt postgres.dump mealie-data.tar.gz)
  [[ -f "$backup/docker-compose.weekly-leftovers.yml" ]] && checksum_files+=(docker-compose.weekly-leftovers.yml)
  [[ -f "$backup/active-custom-image" ]] && checksum_files+=(active-custom-image)
  (cd "$backup" && sha256sum "${checksum_files[@]}" > SHA256SUMS)
  (cd "$backup" && sha256sum -c SHA256SUMS >/dev/null) || { rm -rf "$backup"; die "Backup checksum verification failed"; }
  sync
  printf '%s\n' "$backup"
}

restore_backup() {
  local backup="$1"
  local pg_user pg_pass pg_db
  [[ -d "$backup" ]] || die "Backup directory not found: $backup"
  (cd "$backup" && sha256sum -c SHA256SUMS >/dev/null) || die "Refusing rollback: backup checksum verification failed"

  pg_user="$(container_env mealie-postgres POSTGRES_USER)"
  pg_pass="$(container_env mealie-postgres POSTGRES_PASSWORD)"
  pg_db="$(container_env mealie-postgres POSTGRES_DB)"

  log "Restoring old .env"
  cp -a "$backup/.env" "$ENV_FILE"

  if [[ -f "$backup/docker-compose.weekly-leftovers.yml" ]]; then
    cp -a "$backup/docker-compose.weekly-leftovers.yml" "$CUSTOM_OVERRIDE_FILE"
  else
    rm -f "$CUSTOM_OVERRIDE_FILE"
  fi

  if [[ -f "$backup/active-custom-image" ]]; then
    cp -a "$backup/active-custom-image" "$ACTIVE_CUSTOM_IMAGE_FILE"
  else
    rm -f "$ACTIVE_CUSTOM_IMAGE_FILE"
  fi

  log "Restoring Mealie /app/data"
  find "$DATA_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  tar -C "$DATA_DIR" -xzf "$backup/mealie-data.tar.gz"

  log "Restoring PostgreSQL database"
  docker exec -e "PGPASSWORD=$pg_pass" mealie-postgres psql -U "$pg_user" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$pg_db' AND pid <> pg_backend_pid();" >/dev/null
  docker exec -e "PGPASSWORD=$pg_pass" mealie-postgres dropdb -U "$pg_user" --if-exists "$pg_db"
  docker exec -e "PGPASSWORD=$pg_pass" mealie-postgres createdb -U "$pg_user" -O "$pg_user" "$pg_db"
  if ! cat "$backup/postgres.dump" | docker exec -i -e "PGPASSWORD=$pg_pass" mealie-postgres \
      pg_restore -U "$pg_user" -d "$pg_db" --no-owner --no-privileges --exit-on-error; then
    die "CRITICAL: PostgreSQL rollback restore failed"
  fi
}

set_version() {
  local new="$1"
  python3 - "$ENV_FILE" "$new" <<'PY'
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); new=sys.argv[2]
s=p.read_text()
ns,n=re.subn(r'(?m)^MEALIE_VERSION=.*$', f'MEALIE_VERSION={new}', s, count=1)
if n != 1:
    raise SystemExit('MEALIE_VERSION line not found exactly once')
p.write_text(ns)
PY
}

update_pending() {
  exec 9>"$LOCK_FILE"; flock -n 9 || die "Another guard process is running"
  [[ -f "$PENDING_FILE" ]] || { log "No pending Mealie update"; return 0; }

  local old new mealie_service backup="" candidate=""
  old="$(current_version)"
  new="$(cat "$PENDING_FILE")"
  [[ "$new" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Invalid pending version: $new"
  [[ "$new" != "$old" ]] || { rm -f "$PENDING_FILE" "$PENDING_NAME_FILE"; return 0; }

  preflight
  mealie_service="$(compose_service_for_container mealie)"
  [[ -n "$mealie_service" ]] || die "Could not determine Docker Compose service for container 'mealie'"

  if [[ "$CUSTOM_PATCH_ENABLED" == "1" ]]; then
    discord "🧩 **Mealie automatic update preparing** on $(hostname): **$old → $new**. Validating and building the custom **Weekly Leftovers** image first; the current Mealie remains online during this step."

    if ! candidate="$(build_custom_image "$new" | tail -n1)"; then
      local build_stage build_log reason
      build_stage="$(cat "$BUILD_FAILURE_STAGE_FILE" 2>/dev/null || printf 'unknown')"
      build_log="$(cat "$LAST_BUILD_LOG_FILE" 2>/dev/null || true)"
      case "$build_stage" in
        compatibility) reason="the Weekly Leftovers compatibility check failed" ;;
        patch) reason="the Weekly Leftovers patch could not be applied" ;;
        full-after-fast) reason="Fast Build failed and the automatic Full Build fallback also failed" ;;
        full) reason="the Full Build failed" ;;
        download) reason="the Mealie source download failed" ;;
        extract|source) reason="the Mealie source could not be prepared" ;;
        inspect) reason="the candidate image was built but could not be verified" ;;
        *) reason="candidate preparation failed" ;;
      esac
      printf '%s failed custom Weekly Leftovers build (%s) at %s; current stayed on %s\n' "$new" "$build_stage" "$(date -Is)" "$old" > "$LAST_FAILURE_FILE"
      printf '%s\n' "$new" > "$BLOCKED_FILE"
      rm -f "$PENDING_FILE" "$PENDING_NAME_FILE"
      discord "⛔ **Mealie $new was NOT installed** on $(hostname): $reason.\nCurrent **$old** was never stopped and remains online.\nThe release is blocked from automatic retry until reviewed.${build_log:+\nBuild log: \`$build_log\`}"
      return 1
    fi

    [[ "$candidate" == "$(custom_image_tag "$new")" ]] || die "Unexpected custom image tag returned: '$candidate'"
  fi

  discord "🕛 **Mealie automatic update starting** on $(hostname): **$old → $new**. Candidate preparation passed; creating a cold, verified backup now."
  cd "$MEALIE_DIR"

  # Stop only the application. PostgreSQL remains online for a consistent logical dump.
  compose_active stop "$mealie_service"

  if ! backup="$(backup_create "$old" | tail -n1)"; then
    compose_active up -d "$mealie_service" || true
    discord "❌ **Mealie update aborted before any version change** on $(hostname): backup creation/verification failed. Version remains **$old**."
    return 1
  fi

  log "Verified backup created: $backup"

  if ! set_version "$new"; then
    compose_active up -d "$mealie_service" || true
    discord "❌ **Mealie update aborted** on $(hostname): could not update MEALIE_VERSION. Verified backup: $backup"
    return 1
  fi

  if [[ "$CUSTOM_PATCH_ENABLED" == "1" ]]; then
    write_custom_override "$mealie_service" "$candidate"
  fi

  if [[ "$CUSTOM_PATCH_ENABLED" == "1" ]]; then
    if compose_active up -d "$mealie_service" && wait_healthy "$HEALTH_TIMEOUT"; then
      printf '%s\n' "$candidate" > "$ACTIVE_CUSTOM_IMAGE_FILE"
      printf '%s -> %s at %s; custom image %s\n' "$old" "$new" "$(date -Is)" "$candidate" > "$LAST_SUCCESS_FILE"
      rm -f "$PENDING_FILE" "$PENDING_NAME_FILE" "$BLOCKED_FILE"
      discord "✅ **Mealie update successful** on $(hostname): **$old → $new** with **Weekly Leftovers** patch **$CUSTOM_PATCH_REV**. Docker health check passed. Backup retained at: \`$backup\`"
      log "Update successful: $old -> $new ($candidate)"
      find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+$RETENTION_DAYS" -print -exec rm -rf {} + || true
      return 0
    fi
  else
    if docker compose pull "$mealie_service" && docker compose up -d "$mealie_service" && wait_healthy "$HEALTH_TIMEOUT"; then
      rm -f "$ACTIVE_CUSTOM_IMAGE_FILE" "$CUSTOM_OVERRIDE_FILE"
      printf '%s -> %s at %s\n' "$old" "$new" "$(date -Is)" > "$LAST_SUCCESS_FILE"
      rm -f "$PENDING_FILE" "$PENDING_NAME_FILE" "$BLOCKED_FILE"
      discord "✅ **Mealie update successful** on $(hostname): **$old → $new**. Docker health check passed. Backup retained at: \`$backup\`"
      log "Update successful: $old -> $new"
      find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+$RETENTION_DAYS" -print -exec rm -rf {} + || true
      return 0
    fi
  fi

  log "Update failed; capturing candidate diagnostics before rollback"
  capture_mealie_diagnostics "update-${new}-candidate" >/dev/null || true
  log "Update failed; starting rollback"
  compose_active stop "$mealie_service" >/dev/null 2>&1 || true
  if (restore_backup "$backup") && compose_active up -d "$mealie_service" && wait_healthy "$HEALTH_TIMEOUT"; then
    printf '%s failed at %s; rolled back to %s\n' "$new" "$(date -Is)" "$old" > "$LAST_FAILURE_FILE"
    rm -f "$PENDING_FILE" "$PENDING_NAME_FILE"
    printf '%s\n' "$new" > "$BLOCKED_FILE"
    discord "↩️ **Mealie update FAILED and was rolled back successfully** on $(hostname). Attempted: **$old → $new**. Current version: **$old**. Failed release is blocked from automatic retry."
    log "Rollback successful; current version restored to $old"
    return 1
  fi

  printf '%s failed at %s; rollback also failed\n' "$new" "$(date -Is)" > "$LAST_FAILURE_FILE"
  discord "🚨 **CRITICAL: Mealie update AND automatic rollback failed** on $(hostname). Attempted **$old → $new**. Manual intervention required. Backup: \`$backup\`"
  die "Update failed and rollback could not be verified"
}

backup_only() {
  exec 9>"$LOCK_FILE"; flock -n 9 || die "Another guard process is running"
  local v svc backup
  preflight
  v="$(current_version)"
  svc="$(compose_service_for_container mealie)"
  cd "$MEALIE_DIR"
  compose_active stop "$svc"
  if backup="$(backup_create "$v" | tail -n1)"; then
    compose_active up -d "$svc"
    wait_healthy "$HEALTH_TIMEOUT" || die "Backup completed but Mealie did not return healthy"
    log "Backup verified: $backup"
    discord "💾 **Mealie backup test successful** on $(hostname), version **$v**. Verified PostgreSQL + /app/data backup: \`$backup\`"
  else
    compose_active up -d "$svc" || true
    die "Backup failed"
  fi
}


install_leftovers() {
  exec 9>"$LOCK_FILE"; flock -n 9 || die "Another guard process is running"
  [[ "$CUSTOM_PATCH_ENABLED" == "1" ]] || die "CUSTOM_PATCH_ENABLED is not enabled"

  local v svc candidate backup=""
  preflight
  v="$(current_version)"
  svc="$(compose_service_for_container mealie)"
  [[ -n "$svc" ]] || die "Could not determine Docker Compose service for container 'mealie'"

  candidate="$(build_custom_image "$v" | tail -n1)" || {
    discord "⛔ **Mealie Weekly Leftovers install aborted** on $(hostname): compatibility check or Docker build failed for **$v**. Current Mealie was not stopped."
    return 1
  }
  [[ "$candidate" == "$(custom_image_tag "$v")" ]] || die "Unexpected custom image tag returned: '$candidate'"

  if [[ -f "$ACTIVE_CUSTOM_IMAGE_FILE" && "$(cat "$ACTIVE_CUSTOM_IMAGE_FILE")" == "$candidate" && -f "$CUSTOM_OVERRIDE_FILE" ]]; then
    log "Weekly Leftovers patch is already active with image $candidate"
    return 0
  fi

  discord "♻️ **Installing Mealie Weekly Leftovers feature** on $(hostname), upstream **$v**. Custom image built successfully; creating a verified backup before switching."
  cd "$MEALIE_DIR"
  compose_active stop "$svc"

  if ! backup="$(backup_create "$v" | tail -n1)"; then
    compose_active up -d "$svc" || true
    discord "❌ **Mealie Weekly Leftovers install aborted** on $(hostname): backup creation/verification failed. Original Mealie has been restarted."
    return 1
  fi

  write_custom_override "$svc" "$candidate"

  if compose_active up -d "$svc" && wait_healthy "$HEALTH_TIMEOUT"; then
    printf '%s\n' "$candidate" > "$ACTIVE_CUSTOM_IMAGE_FILE"
    printf 'Weekly Leftovers installed on %s at %s; custom image %s\n' "$v" "$(date -Is)" "$candidate" > "$LAST_SUCCESS_FILE"
    discord "✅ **Mealie Weekly Leftovers feature installed** on $(hostname), upstream **$v**, patch **$CUSTOM_PATCH_REV**. Health check passed. Backup retained at: \`$backup\`"
    log "Weekly Leftovers feature installed successfully: $candidate"
    return 0
  fi

  log "Weekly Leftovers activation failed; capturing candidate diagnostics before rollback"
  capture_mealie_diagnostics "leftovers-${CUSTOM_PATCH_REV}-candidate" >/dev/null || true
  log "Weekly Leftovers activation failed; rolling back"
  compose_active stop "$svc" >/dev/null 2>&1 || true
  if (restore_backup "$backup") && compose_active up -d "$svc" && wait_healthy "$HEALTH_TIMEOUT"; then
    printf 'Weekly Leftovers activation failed at %s; rolled back to pre-patch %s\n' "$(date -Is)" "$v" > "$LAST_FAILURE_FILE"
    discord "↩️ **Mealie Weekly Leftovers activation failed and was rolled back successfully** on $(hostname). Mealie is healthy again on **$v**."
    return 1
  fi

  discord "🚨 **CRITICAL: Mealie Weekly Leftovers activation and rollback both failed** on $(hostname). Manual intervention required. Backup: \`$backup\`"
  die "Weekly Leftovers activation failed and rollback could not be verified"
}

status_cmd() {
  local current pending blocked active_custom
  current="$(current_version)"
  pending="$(cat "$PENDING_FILE" 2>/dev/null || true)"
  blocked="$(cat "$BLOCKED_FILE" 2>/dev/null || true)"
  active_custom="$(cat "$ACTIVE_CUSTOM_IMAGE_FILE" 2>/dev/null || true)"
  printf 'Mealie Update Guard\n'
  printf '  Current version : %s\n' "$current"
  printf '  Container health: %s\n' "$(health_status)"
  printf '  Pending version : %s\n' "${pending:-none}"
  printf '  Blocked version : %s\n' "${blocked:-none}"
  printf '  Leftovers enabled  : %s\n' "$CUSTOM_PATCH_ENABLED"
  printf '  Feature revision : %s\n' "$CUSTOM_PATCH_REV"
  printf '  Fast build      : %s\n' "$CUSTOM_FAST_BUILD_ENABLED"
  printf '  Custom image    : %s\n' "${active_custom:-not active}"
  printf '  Backup dir      : %s\n' "$BACKUP_DIR"
  printf '  Retention       : %s days\n' "$RETENTION_DAYS"
  [[ -f "$LAST_SUCCESS_FILE" ]] && printf '  Last success    : %s\n' "$(cat "$LAST_SUCCESS_FILE")"
  [[ -f "$LAST_FAILURE_FILE" ]] && printf '  Last failure    : %s\n' "$(cat "$LAST_FAILURE_FILE")"
}

test_discord() {
  discord "🧪 **Mealie Update Guard test** from $(hostname). Discord notifications are configured. Current version: **$(current_version)**."
  log "Discord test sent"
}

dry_run() {
  preflight
  local v svc pg_user pg_db
  v="$(current_version)"
  svc="$(compose_service_for_container mealie)"
  pg_user="$(container_env mealie-postgres POSTGRES_USER)"
  pg_db="$(container_env mealie-postgres POSTGRES_DB)"
  printf 'DRY RUN OK\n'
  printf '  Mealie dir      : %s\n' "$MEALIE_DIR"
  printf '  Data dir        : %s\n' "$DATA_DIR"
  printf '  Current version : %s\n' "$v"
  printf '  Compose service : %s\n' "$svc"
  printf '  PostgreSQL DB   : %s\n' "$pg_db"
  printf '  PostgreSQL user : %s\n' "$pg_user"
  printf '  Health          : %s\n' "$(health_status)"
  printf '  Leftovers enabled  : %s\n' "$CUSTOM_PATCH_ENABLED"
  printf '  Weekly Leftovers patcher  : %s\n' "$CUSTOM_PATCHER"
  printf '  Feature revision : %s\n' "$CUSTOM_PATCH_REV"
  printf '  Fast build      : %s\n' "$CUSTOM_FAST_BUILD_ENABLED"
  if [[ "$CUSTOM_PATCH_ENABLED" == "1" ]]; then
    [[ -r "$CUSTOM_PATCHER" ]] || die "Weekly Leftovers patcher is not readable: $CUSTOM_PATCHER"
  fi
  printf 'No containers, database, .env, source code, or images were changed.\n'
}

case "${1:-status}" in
  check) check_release ;;
  update) update_pending ;;
  backup) backup_only ;;
  install-leftovers|install-rester) install_leftovers ;;
  status) status_cmd ;;
  test-discord) test_discord ;;
  dry-run) dry_run ;;
  *) echo "Usage: $0 {check|update|backup|install-leftovers|status|test-discord|dry-run}" >&2; exit 2 ;;
esac
