#!/usr/bin/env bash
set -Eeuo pipefail

ACTION="${1:-install}"
POSTGRESQL_MAJOR="${DARKWEB_POSTGRESQL_MAJOR:-16}"
POSTGRESQL_HOST="${DARKWEB_POSTGRESQL_HOST:-127.0.0.1}"
POSTGRESQL_PORT="${DARKWEB_POSTGRESQL_PORT:-5432}"
DATABASE_NAME="${DARKWEB_POSTGRESQL_DATABASE:-darkweb_intelligence}"
MIGRATION_USER="${DARKWEB_POSTGRESQL_MIGRATION_USER:-darkweb_migrator}"
RUNTIME_USER="${DARKWEB_POSTGRESQL_RUNTIME_USER:-darkweb_app}"
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
  if [[ "$(id -u)" == "0" ]]; then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else die "root privileges or sudo are required to install PostgreSQL"
  fi
}

run_as_postgres() {
  id postgres >/dev/null 2>&1 || die "PostgreSQL system account is unavailable"
  if [[ "$(id -u)" == "0" ]]; then runuser -u postgres -- "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo -u postgres "$@"
  else die "sudo is required to configure PostgreSQL"
  fi
}

read_os_release() {
  [[ -r /etc/os-release ]] || die "unsupported Linux distribution; configure both PostgreSQL URLs manually"
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in ubuntu|debian) ;; *) die "automatic installation supports Debian and Ubuntu only" ;; esac
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
  release_url="$repository_base/dists/$VERSION_CODENAME-pgdg/Release"
  if ! curl -fsSL --retry 2 --output /dev/null "$release_url"; then
    [[ -z "${DARKWEB_PGDG_REPOSITORY_BASE:-}" ]] || die "configured repository does not publish $VERSION_CODENAME-pgdg"
    repository_base="$PGDG_ARCHIVE_REPOSITORY"
    release_url="$repository_base/dists/$VERSION_CODENAME-pgdg/Release"
    curl -fsSL --retry 2 --output /dev/null "$release_url" || die "official archive does not publish $VERSION_CODENAME-pgdg"
    info "using official PostgreSQL archive for $VERSION_CODENAME"
  fi
  source_line="deb [signed-by=$PGDG_KEYRING] $repository_base $VERSION_CODENAME-pgdg main"
  printf '%s\n' "$source_line" | run_root tee "$PGDG_SOURCE_LIST" >/dev/null
  rm -f -- "$key_file"
}

install_postgresql_packages() {
  if command -v psql >/dev/null 2>&1 && command -v pg_isready >/dev/null 2>&1 &&
     command -v pg_ctlcluster >/dev/null 2>&1 && command -v pg_lsclusters >/dev/null 2>&1 &&
     [[ -x "/usr/lib/postgresql/$POSTGRESQL_MAJOR/bin/postgres" ]]; then return; fi
  command -v apt-get >/dev/null 2>&1 || die "automatic installation requires apt-get"
  run_root env DEBIAN_FRONTEND=noninteractive apt-get update
  run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl gnupg
  ensure_pgdg_repository
  run_root env DEBIAN_FRONTEND=noninteractive apt-get update
  run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    "postgresql-$POSTGRESQL_MAJOR" "postgresql-client-$POSTGRESQL_MAJOR"
}

wait_postgresql() {
  local attempt
  for attempt in $(seq 1 60); do
    pg_isready -q -h "$POSTGRESQL_HOST" -p "$POSTGRESQL_PORT" && return
    sleep 2
  done
  die "PostgreSQL did not become ready on $POSTGRESQL_HOST:$POSTGRESQL_PORT"
}

require_postgresql_16_server() {
  local version_num
  version_num="$(run_as_postgres psql --no-align --tuples-only --dbname postgres \
    --port "$POSTGRESQL_PORT" --command "SHOW server_version_num;" |
    tr -d '[:space:]')"
  [[ "$version_num" =~ ^[0-9]+$ ]] || die "unable to read PostgreSQL server_version_num"
  (( version_num >= 160000 && version_num < 170000 )) ||
    die "PostgreSQL 16.x is required, target server reports version_num=$version_num"
}

start_postgresql_cluster() {
  pg_isready -q -h "$POSTGRESQL_HOST" -p "$POSTGRESQL_PORT" && return
  local cluster_version cluster_name cluster_port cluster_status selected_version="" selected_name=""
  if command -v pg_lsclusters >/dev/null 2>&1; then
    while read -r cluster_version cluster_name cluster_port cluster_status _; do
      [[ -n "$cluster_version" ]] || continue
      if [[ "$cluster_port" == "$POSTGRESQL_PORT" ]]; then selected_version="$cluster_version"; selected_name="$cluster_name"; break; fi
    done < <(pg_lsclusters --no-header 2>/dev/null || true)
  fi
  if [[ -n "$selected_version" ]]; then run_root pg_ctlcluster "$selected_version" "$selected_name" start || true
  elif command -v pg_createcluster >/dev/null 2>&1; then run_root pg_createcluster "$POSTGRESQL_MAJOR" main --port "$POSTGRESQL_PORT" --start
  elif command -v service >/dev/null 2>&1; then run_root service postgresql start
  else die "PostgreSQL cluster tools are unavailable"; fi
  wait_postgresql
}

config_value() {
  python3 - "$TARGET_CONFIG_PATH" "$1" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("format") != 2:
    raise SystemExit("unsupported PostgreSQL target configuration")
value = payload.get(sys.argv[2])
if value is None or str(value) == "":
    raise SystemExit(f"missing PostgreSQL target field: {sys.argv[2]}")
print(value)
PY
}

load_target_config() {
  [[ -f "$TARGET_CONFIG_PATH" ]] || return 1
  chmod 600 "$TARGET_CONFIG_PATH"
  CONFIG_HOST="$(config_value host)"
  CONFIG_PORT="$(config_value port)"
  CONFIG_DATABASE="$(config_value database)"
  CONFIG_MIGRATION_USER="$(config_value migration_user)"
  CONFIG_MIGRATION_PASSWORD="$(config_value migration_password)"
  CONFIG_RUNTIME_USER="$(config_value runtime_user)"
  CONFIG_RUNTIME_PASSWORD="$(config_value runtime_password)"
  CONFIG_MIGRATION_URL="$(config_value migration_database_url)"
  CONFIG_RUNTIME_URL="$(config_value runtime_database_url)"
}

save_target_config() {
  local migration_password="$1" runtime_password="$2" temporary_path config_dir
  config_dir="$(dirname "$TARGET_CONFIG_PATH")"
  if [[ ! -d "$config_dir" ]]; then (umask 077; mkdir -p -- "$config_dir"); fi
  chmod 700 "$config_dir"
  temporary_path="$TARGET_CONFIG_PATH.tmp-$$"
  umask 077
  DWTI_PG_HOST="$POSTGRESQL_HOST" DWTI_PG_PORT="$POSTGRESQL_PORT" \
  DWTI_PG_DATABASE="$DATABASE_NAME" DWTI_PG_MIGRATION_USER="$MIGRATION_USER" \
  DWTI_PG_MIGRATION_PASSWORD="$migration_password" DWTI_PG_RUNTIME_USER="$RUNTIME_USER" \
  DWTI_PG_RUNTIME_PASSWORD="$runtime_password" DWTI_PG_MAJOR="$POSTGRESQL_MAJOR" \
    python3 - "$temporary_path" <<'PY'
from datetime import datetime, timezone
import json, os, sys
from pathlib import Path
from urllib.parse import quote
host, port, database = os.environ["DWTI_PG_HOST"], int(os.environ["DWTI_PG_PORT"]), os.environ["DWTI_PG_DATABASE"]
mu, mp = os.environ["DWTI_PG_MIGRATION_USER"], os.environ["DWTI_PG_MIGRATION_PASSWORD"]
ru, rp = os.environ["DWTI_PG_RUNTIME_USER"], os.environ["DWTI_PG_RUNTIME_PASSWORD"]
def url(user, password):
    return "postgresql://" + quote(user, safe="") + ":" + quote(password, safe="") + f"@{host}:{port}/" + quote(database, safe="")
payload = {
    "format": 2, "host": host, "port": port, "database": database,
    "migration_user": mu, "migration_password": mp,
    "runtime_user": ru, "runtime_password": rp,
    "migration_database_url": url(mu, mp), "runtime_database_url": url(ru, rp),
    "postgresql_major": os.environ["DWTI_PG_MAJOR"],
    "configured_at": datetime.now(timezone.utc).isoformat(),
}
Path(sys.argv[1]).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "$temporary_path"
  mv -f -- "$temporary_path" "$TARGET_CONFIG_PATH"
}

psql_as_role() {
  local password="$1" role="$2"; shift 2
  PGPASSWORD="$password" psql --no-password --set ON_ERROR_STOP=on \
    --host "$POSTGRESQL_HOST" --port "$POSTGRESQL_PORT" --username "$role" --dbname "$DATABASE_NAME" "$@"
}

role_exists() {
  run_as_postgres psql --no-align --tuples-only --dbname postgres --port "$POSTGRESQL_PORT" \
    --command "SELECT 1 FROM pg_roles WHERE rolname = '$1';" | tr -d '[:space:]'
}

database_exists() {
  run_as_postgres psql --no-align --tuples-only --dbname postgres --port "$POSTGRESQL_PORT" \
    --command "SELECT 1 FROM pg_database WHERE datname = '$DATABASE_NAME';" | tr -d '[:space:]'
}

create_login_role() {
  local role="$1" password="$2"
  run_as_postgres psql --set ON_ERROR_STOP=on --set role_name="$role" --set role_password="$password"     --dbname postgres --port "$POSTGRESQL_PORT" <<'SQL' >/dev/null
SELECT format(
  'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
  :'role_name',
  :'role_password'
) \gexec
SQL
}

ensure_database_and_roles() {
  local migration_password runtime_password migration_exists runtime_exists db_exists had_config=0
  if load_target_config; then
    had_config=1
    [[ "$CONFIG_HOST" == "$POSTGRESQL_HOST" && "$CONFIG_PORT" == "$POSTGRESQL_PORT" &&
       "$CONFIG_DATABASE" == "$DATABASE_NAME" && "$CONFIG_MIGRATION_USER" == "$MIGRATION_USER" &&
       "$CONFIG_RUNTIME_USER" == "$RUNTIME_USER" ]] || die "existing target configuration does not match requested settings"
    migration_password="$CONFIG_MIGRATION_PASSWORD"; runtime_password="$CONFIG_RUNTIME_PASSWORD"
  else
    migration_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    runtime_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  fi
  migration_exists="$(role_exists "$MIGRATION_USER")"; runtime_exists="$(role_exists "$RUNTIME_USER")"; db_exists="$(database_exists)"
  if [[ "$had_config" == "0" && ("$migration_exists" == "1" || "$runtime_exists" == "1" || "$db_exists" == "1") ]]; then
    die "database or roles already exist but no matching private format-2 configuration is available"
  fi
  [[ "$had_config" == "1" ]] || save_target_config "$migration_password" "$runtime_password"
  if [[ "$migration_exists" != "1" ]]; then create_login_role "$MIGRATION_USER" "$migration_password"; info "created migration role"; fi
  if [[ "$runtime_exists" != "1" ]]; then create_login_role "$RUNTIME_USER" "$runtime_password"; info "created runtime role"; fi
  if [[ "$db_exists" != "1" ]]; then
    run_as_postgres createdb --port "$POSTGRESQL_PORT" --owner "$MIGRATION_USER" --encoding UTF8 --template template0 "$DATABASE_NAME"
    info "created PostgreSQL database"
  fi
  run_as_postgres psql --set ON_ERROR_STOP=on --dbname postgres --port "$POSTGRESQL_PORT" <<SQL >/dev/null
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE $DATABASE_NAME TO $MIGRATION_USER;
GRANT CONNECT, TEMPORARY ON DATABASE $DATABASE_NAME TO $RUNTIME_USER;
REVOKE CREATE ON DATABASE $DATABASE_NAME FROM $RUNTIME_USER;
SQL
  run_as_postgres psql --set ON_ERROR_STOP=on --dbname "$DATABASE_NAME" --port "$POSTGRESQL_PORT" <<SQL >/dev/null
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO PUBLIC;
SQL
  local check_schema
  check_schema="dwti_setup_check_$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
  psql_as_role "$migration_password" "$MIGRATION_USER" <<SQL >/dev/null
CREATE SCHEMA $check_schema AUTHORIZATION $MIGRATION_USER;
REVOKE ALL ON SCHEMA $check_schema FROM PUBLIC;
CREATE TABLE $check_schema.connection_check(id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, value TEXT NOT NULL);
GRANT USAGE ON SCHEMA $check_schema TO $RUNTIME_USER;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA $check_schema TO $RUNTIME_USER;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA $check_schema TO $RUNTIME_USER;
SQL
  psql_as_role "$runtime_password" "$RUNTIME_USER" \
    --command "INSERT INTO $check_schema.connection_check(value) VALUES ('ok'); SELECT COUNT(*) FROM $check_schema.connection_check;" >/dev/null
  psql_as_role "$migration_password" "$MIGRATION_USER" --command "DROP SCHEMA $check_schema CASCADE;" >/dev/null
  info "verified separated roles and revoked PUBLIC CREATE"
}

show_plan() {
  printf 'Linux PostgreSQL setup plan\n'
  printf '  Version:        PostgreSQL %s\n' "$POSTGRESQL_MAJOR"
  printf '  Endpoint:       %s:%s\n' "$POSTGRESQL_HOST" "$POSTGRESQL_PORT"
  printf '  Database:       %s\n' "$DATABASE_NAME"
  printf '  Migration role: %s (schema/DDL owner)\n' "$MIGRATION_USER"
  printf '  Runtime role:   %s (USAGE/DML only)\n' "$RUNTIME_USER"
  printf '  Config:         %s (mode 600, two private URLs)\n' "$TARGET_CONFIG_PATH"
  printf '  Hardening:      revoke PUBLIC CREATE on public schema\n'
  printf '  Safety:         no SQLite data is imported, deleted, or activated\n'
}

show_status() {
  command -v psql >/dev/null 2>&1 && command -v pg_isready >/dev/null 2>&1 ||
    { warn "PostgreSQL client is not installed"; return 1; }
  pg_isready -q -h "$POSTGRESQL_HOST" -p "$POSTGRESQL_PORT" ||
    { warn "PostgreSQL is not accepting connections"; return 1; }
  require_postgresql_16_server
  load_target_config || { warn "PostgreSQL target configuration is missing"; return 1; }
  psql_as_role "$CONFIG_MIGRATION_PASSWORD" "$CONFIG_MIGRATION_USER" --tuples-only --no-align --command "SELECT current_user" >/dev/null
  psql_as_role "$CONFIG_RUNTIME_PASSWORD" "$CONFIG_RUNTIME_USER" --tuples-only --no-align --command "SELECT current_user" >/dev/null
  local public_create
  public_create="$(run_as_postgres psql --no-align --tuples-only --dbname "$DATABASE_NAME" --port "$POSTGRESQL_PORT" \
    --command "SELECT EXISTS (
      SELECT 1
      FROM pg_namespace AS n,
           aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) AS acl
      WHERE n.nspname='public' AND acl.grantee=0 AND acl.privilege_type='CREATE'
    );" | tr -d '[:space:]')"
  [[ "$public_create" == "f" ]] || { warn "PUBLIC still has CREATE on public schema"; return 1; }
  info "PostgreSQL migration and runtime targets are ready: $CONFIG_HOST:$CONFIG_PORT/$CONFIG_DATABASE"
}

validate_identifier "$DATABASE_NAME"
validate_identifier "$MIGRATION_USER"
validate_identifier "$RUNTIME_USER"
[[ "$MIGRATION_USER" != "$RUNTIME_USER" ]] || die "migration and runtime roles must be different"
validate_port "$POSTGRESQL_PORT"
[[ "$POSTGRESQL_MAJOR" == "16" ]] || die "this migration is pinned to PostgreSQL 16"
[[ "$POSTGRESQL_HOST" == "127.0.0.1" || "$POSTGRESQL_HOST" == "localhost" ]] ||
  die "automatic installation only manages a local PostgreSQL instance"

case "$ACTION" in
  plan) show_plan ;;
  status) show_status ;;
  install)
    install_postgresql_packages
    start_postgresql_cluster
    require_postgresql_16_server
    ensure_database_and_roles
    info "PostgreSQL 16 migration target is ready"
    ;;
  *) die "usage: $0 [install|status|plan]" ;;
esac
