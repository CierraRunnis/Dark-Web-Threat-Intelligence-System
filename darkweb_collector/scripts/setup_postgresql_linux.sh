#!/usr/bin/env bash
set -Eeuo pipefail

ACTION="${1:-install}"
POSTGRESQL_MAJOR="${DARKWEB_POSTGRESQL_MAJOR:-16}"
POSTGRESQL_HOST="${DARKWEB_POSTGRESQL_HOST:-127.0.0.1}"
POSTGRESQL_PORT="${DARKWEB_POSTGRESQL_PORT:-5432}"
DATABASE_NAME="${DARKWEB_POSTGRESQL_DATABASE:-darkweb_intelligence}"
APPLICATION_USER="${DARKWEB_POSTGRESQL_USER:-darkweb_app}"
USER_DATA_ROOT="${DARKWEB_USER_DATA_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/darkweb-threat-intel}"
TARGET_CONFIG_PATH="${DARKWEB_POSTGRESQL_TARGET_CONFIG:-$USER_DATA_ROOT/postgresql-target.json}"
PGDG_KEY_FINGERPRINT="B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"
PGDG_KEYRING="/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg"
PGDG_SOURCE_LIST="/etc/apt/sources.list.d/darkweb-postgresql-pgdg.list"
PGDG_PRIMARY_REPOSITORY="https://apt.postgresql.org/pub/repos/apt"
PGDG_ARCHIVE_REPOSITORY="https://apt-archive.postgresql.org/pub/repos/apt"

info() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

validate_identifier() {
  [[ "$1" =~ ^[a-z][a-z0-9_]{0,62}$ ]] || die "invalid PostgreSQL identifier: $1"
}

validate_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 >= 1024 && 10#$1 <= 65535 )) || die "invalid PostgreSQL port: $1"
}

run_root() {
  if [[ "$(id -u)" == "0" ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "root privileges or sudo are required to install PostgreSQL"
  fi
}

run_as_postgres() {
  if ! id postgres >/dev/null 2>&1; then
    die "PostgreSQL system account is unavailable"
  fi
  if [[ "$(id -u)" == "0" ]]; then
    runuser -u postgres -- "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo -u postgres "$@"
  else
    die "sudo is required to configure PostgreSQL"
  fi
}

read_os_release() {
  [[ -r /etc/os-release ]] || die "unsupported Linux distribution; configure DARKWEB_MIGRATION_TARGET_DATABASE_URL manually"
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    ubuntu|debian) ;;
    *) die "automatic PostgreSQL installation supports Debian and Ubuntu; configure an external target on ${ID:-unknown}" ;;
  esac
  [[ -n "${VERSION_CODENAME:-}" ]] || die "Linux distribution codename is unavailable"
}

ensure_pgdg_repository() {
  read_os_release
  local key_file fingerprint source_line repository_base release_url
  key_file="$(mktemp)"
  curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o "$key_file"
  fingerprint="$(gpg --batch --show-keys --with-colons "$key_file" | awk -F: '$1 == "fpr" { print $10; exit }')"
  [[ "$fingerprint" == "$PGDG_KEY_FINGERPRINT" ]] || die "PostgreSQL repository signing key fingerprint mismatch"
  run_root install -d -m 0755 "$(dirname "$PGDG_KEYRING")"
  run_root gpg --batch --yes --dearmor --output "$PGDG_KEYRING" "$key_file"
  repository_base="${DARKWEB_PGDG_REPOSITORY_BASE:-$PGDG_PRIMARY_REPOSITORY}"
  [[ "$repository_base" == https://* ]] || die "PostgreSQL repository URL must use HTTPS"
  release_url="$repository_base/dists/${VERSION_CODENAME}-pgdg/Release"
  if ! curl -fsSL --retry 2 --output /dev/null "$release_url"; then
    [[ -z "${DARKWEB_PGDG_REPOSITORY_BASE:-}" ]] || die "configured PostgreSQL repository does not publish ${VERSION_CODENAME}-pgdg"
    repository_base="$PGDG_ARCHIVE_REPOSITORY"
    release_url="$repository_base/dists/${VERSION_CODENAME}-pgdg/Release"
    curl -fsSL --retry 2 --output /dev/null "$release_url" || die "PostgreSQL archive does not publish ${VERSION_CODENAME}-pgdg"
    info "using the official PostgreSQL archive for EOL distribution: ${VERSION_CODENAME}"
  fi
  source_line="deb [signed-by=$PGDG_KEYRING] $repository_base ${VERSION_CODENAME}-pgdg main"
  printf '%s\n' "$source_line" | run_root tee "$PGDG_SOURCE_LIST" >/dev/null
  rm -f -- "$key_file"
}

install_postgresql_packages() {
  if command -v psql >/dev/null 2>&1 && command -v pg_isready >/dev/null 2>&1 && command -v pg_ctlcluster >/dev/null 2>&1 && command -v pg_lsclusters >/dev/null 2>&1; then
    return
  fi
  command -v apt-get >/dev/null 2>&1 || die "automatic PostgreSQL installation requires apt-get"
  run_root env DEBIAN_FRONTEND=noninteractive apt-get update
  run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl gnupg
  ensure_pgdg_repository
  run_root env DEBIAN_FRONTEND=noninteractive apt-get update
  run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "postgresql-$POSTGRESQL_MAJOR" "postgresql-client-$POSTGRESQL_MAJOR"
}

wait_postgresql() {
  local attempt
  for attempt in $(seq 1 60); do
    if pg_isready -q -h "$POSTGRESQL_HOST" -p "$POSTGRESQL_PORT"; then
      return
    fi
    sleep 2
  done
  die "PostgreSQL did not become ready on $POSTGRESQL_HOST:$POSTGRESQL_PORT"
}

start_postgresql_cluster() {
  if pg_isready -q -h "$POSTGRESQL_HOST" -p "$POSTGRESQL_PORT"; then
    return
  fi

  local cluster_version cluster_name cluster_port cluster_status selected_version selected_name
  if command -v pg_lsclusters >/dev/null 2>&1; then
    while read -r cluster_version cluster_name cluster_port cluster_status _; do
      [[ -n "$cluster_version" ]] || continue
      if [[ "$cluster_port" == "$POSTGRESQL_PORT" ]]; then
        selected_version="$cluster_version"
        selected_name="$cluster_name"
        break
      fi
    done < <(pg_lsclusters --no-header 2>/dev/null || true)
  fi

  if [[ -n "${selected_version:-}" ]]; then
    run_root pg_ctlcluster "$selected_version" "$selected_name" start || true
  elif command -v pg_createcluster >/dev/null 2>&1; then
    run_root pg_createcluster "$POSTGRESQL_MAJOR" main --port "$POSTGRESQL_PORT" --start
  elif command -v service >/dev/null 2>&1; then
    run_root service postgresql start
  else
    die "PostgreSQL cluster tools are unavailable"
  fi
  wait_postgresql
}

load_target_config() {
  [[ -f "$TARGET_CONFIG_PATH" ]] || return 1
  chmod 600 "$TARGET_CONFIG_PATH"
  mapfile -t TARGET_CONFIG_VALUES < <(python3 - "$TARGET_CONFIG_PATH" <<'PY' | tr -d '\r'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("format") != 1:
    raise SystemExit("unsupported PostgreSQL target configuration")
for key in ("host", "port", "database", "application_user", "application_password"):
    value = payload.get(key)
    if value is None or str(value) == "":
        raise SystemExit(f"missing PostgreSQL target field: {key}")
    print(value)
PY
  )
  [[ "${#TARGET_CONFIG_VALUES[@]}" == "5" ]] || die "invalid PostgreSQL target configuration: $TARGET_CONFIG_PATH"
  CONFIG_HOST="${TARGET_CONFIG_VALUES[0]}"
  CONFIG_PORT="${TARGET_CONFIG_VALUES[1]}"
  CONFIG_DATABASE="${TARGET_CONFIG_VALUES[2]}"
  CONFIG_USER="${TARGET_CONFIG_VALUES[3]}"
  CONFIG_PASSWORD="${TARGET_CONFIG_VALUES[4]}"
}

save_target_config() {
  local application_password="$1" temporary_path config_dir
  config_dir="$(dirname "$TARGET_CONFIG_PATH")"
  if [[ ! -d "$config_dir" ]]; then
    (umask 077; mkdir -p -- "$config_dir")
  fi
  if [[ "$TARGET_CONFIG_PATH" == "$USER_DATA_ROOT/postgresql-target.json" ]]; then
    chmod 700 "$USER_DATA_ROOT"
  fi
  temporary_path="$TARGET_CONFIG_PATH.tmp-$$"
  umask 077
  DWTI_PG_HOST="$POSTGRESQL_HOST" \
  DWTI_PG_PORT="$POSTGRESQL_PORT" \
  DWTI_PG_DATABASE="$DATABASE_NAME" \
  DWTI_PG_USER="$APPLICATION_USER" \
  DWTI_PG_PASSWORD="$application_password" \
  DWTI_PG_MAJOR="$POSTGRESQL_MAJOR" \
    python3 - "$temporary_path" <<'PY'
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path

payload = {
    "format": 1,
    "host": os.environ["DWTI_PG_HOST"],
    "port": int(os.environ["DWTI_PG_PORT"]),
    "database": os.environ["DWTI_PG_DATABASE"],
    "application_user": os.environ["DWTI_PG_USER"],
    "application_password": os.environ["DWTI_PG_PASSWORD"],
    "postgresql_major": os.environ["DWTI_PG_MAJOR"],
    "configured_at": datetime.now(timezone.utc).isoformat(),
}
Path(sys.argv[1]).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "$temporary_path"
  mv -f -- "$temporary_path" "$TARGET_CONFIG_PATH"
}

psql_as_app() {
  local password="$1"
  shift
  PGPASSWORD="$password" psql --no-password --set ON_ERROR_STOP=on \
    --host "$POSTGRESQL_HOST" --port "$POSTGRESQL_PORT" \
    --username "$APPLICATION_USER" --dbname "$DATABASE_NAME" "$@"
}

ensure_database_and_role() {
  local application_password application_password_sql role_exists database_exists check_schema had_config=0
  if load_target_config; then
    had_config=1
    [[ "$CONFIG_HOST" == "$POSTGRESQL_HOST" && "$CONFIG_PORT" == "$POSTGRESQL_PORT" && "$CONFIG_DATABASE" == "$DATABASE_NAME" && "$CONFIG_USER" == "$APPLICATION_USER" ]] || \
      die "existing PostgreSQL target configuration does not match requested settings"
    application_password="$CONFIG_PASSWORD"
  else
    application_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  fi

  role_exists="$(run_as_postgres psql --no-align --tuples-only --dbname postgres --port "$POSTGRESQL_PORT" --command "SELECT 1 FROM pg_roles WHERE rolname = '$APPLICATION_USER';" | tr -d '[:space:]')"
  database_exists="$(run_as_postgres psql --no-align --tuples-only --dbname postgres --port "$POSTGRESQL_PORT" --command "SELECT 1 FROM pg_database WHERE datname = '$DATABASE_NAME';" | tr -d '[:space:]')"
  if [[ "$role_exists" == "1" && "$had_config" == "0" ]]; then
    die "PostgreSQL role $APPLICATION_USER already exists but no matching private configuration is available"
  fi
  if [[ "$database_exists" == "1" && "$had_config" == "0" ]]; then
    die "PostgreSQL database $DATABASE_NAME already exists but no matching private configuration is available"
  fi
  if [[ "$had_config" == "0" ]]; then
    save_target_config "$application_password"
  fi
  if [[ "$role_exists" != "1" ]]; then
    application_password_sql="${application_password//\'/\'\'}"
    printf "CREATE ROLE %s LOGIN PASSWORD '%s';\n" "$APPLICATION_USER" "$application_password_sql" | \
      run_as_postgres psql --set ON_ERROR_STOP=on --dbname postgres --port "$POSTGRESQL_PORT" >/dev/null
    info "created PostgreSQL application role"
  fi

  if [[ "$database_exists" != "1" ]]; then
    run_as_postgres createdb --port "$POSTGRESQL_PORT" --owner "$APPLICATION_USER" --encoding UTF8 --template template0 "$DATABASE_NAME"
    info "created PostgreSQL application database"
  fi
  run_as_postgres psql --set ON_ERROR_STOP=on --dbname postgres --port "$POSTGRESQL_PORT" --command "GRANT CONNECT, CREATE, TEMPORARY ON DATABASE $DATABASE_NAME TO $APPLICATION_USER;" >/dev/null

  check_schema="dwti_setup_check_$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
  psql_as_app "$application_password" --command "CREATE SCHEMA $check_schema AUTHORIZATION $APPLICATION_USER; CREATE TABLE $check_schema.connection_check(id BIGINT PRIMARY KEY); INSERT INTO $check_schema.connection_check VALUES (1); DROP SCHEMA $check_schema CASCADE;" >/dev/null
  info "verified PostgreSQL schema and table permissions"
}

show_plan() {
  printf 'Linux PostgreSQL setup plan\n'
  printf '  Version:  PostgreSQL %s\n' "$POSTGRESQL_MAJOR"
  printf '  Endpoint: %s:%s\n' "$POSTGRESQL_HOST" "$POSTGRESQL_PORT"
  printf '  Database: %s\n' "$DATABASE_NAME"
  printf '  Role:     %s\n' "$APPLICATION_USER"
  printf '  Config:   %s (mode 600)\n' "$TARGET_CONFIG_PATH"
  printf '  Safety:   existing SQLite data is not imported, deleted, or switched\n'
}

show_status() {
  command -v psql >/dev/null 2>&1 && command -v pg_isready >/dev/null 2>&1 || { warn "PostgreSQL client is not installed"; return 1; }
  pg_isready -q -h "$POSTGRESQL_HOST" -p "$POSTGRESQL_PORT" || { warn "PostgreSQL is not accepting connections"; return 1; }
  load_target_config || { warn "PostgreSQL target configuration is missing"; return 1; }
  PGPASSWORD="$CONFIG_PASSWORD" psql --no-password --host "$CONFIG_HOST" --port "$CONFIG_PORT" --username "$CONFIG_USER" --dbname "$CONFIG_DATABASE" --tuples-only --no-align --command "SELECT 1" >/dev/null
  info "PostgreSQL migration target is ready: $CONFIG_HOST:$CONFIG_PORT/$CONFIG_DATABASE"
}

validate_identifier "$DATABASE_NAME"
validate_identifier "$APPLICATION_USER"
validate_port "$POSTGRESQL_PORT"
[[ "$POSTGRESQL_MAJOR" =~ ^[0-9]+$ ]] || die "invalid PostgreSQL major version"

case "$ACTION" in
  plan) show_plan ;;
  status) show_status ;;
  install)
    install_postgresql_packages
    start_postgresql_cluster
    ensure_database_and_role
    info "PostgreSQL migration target is ready"
    ;;
  *) die "usage: $0 [install|status|plan]" ;;
esac
