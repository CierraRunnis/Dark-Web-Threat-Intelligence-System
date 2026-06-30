#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="bishe-stack"
API_HOST="127.0.0.1"
API_PORT="${DARKWEB_API_PORT:-8000}"
API_BASE_URL="http://${API_HOST}:${API_PORT}"
API_HEALTH_URL="${API_BASE_URL}/api/health"
API_JOBS_URL="${API_BASE_URL}/api/jobs"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="${DARKWEB_FRONTEND_PORT:-5173}"
FRONTEND_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"
SERVICE_WAIT_SECONDS=45
SCHEDULER_INTERVAL_SECONDS="${SCHEDULER_INTERVAL_SECONDS:-60}"
VULN_SYNC_INTERVAL_SECONDS="${VULN_SYNC_INTERVAL_SECONDS:-3600}"
VULN_SYNC_LIMIT="${VULN_SYNC_LIMIT:-300}"
DARKWEB_PANSOU_ENABLED="${DARKWEB_PANSOU_ENABLED:-1}"
PANSOU_PORT="${PANSOU_PORT:-8888}"
PANSOU_API_BASE="${PANSOU_API_BASE:-http://127.0.0.1:${PANSOU_PORT}}"
PANSOU_CONTAINER_NAME="${PANSOU_CONTAINER_NAME:-darkweb-pansou}"
PANSOU_IMAGE="${PANSOU_IMAGE:-ghcr.io/fish2018/pansou:latest}"
PANSOU_CHANNELS="${PANSOU_CHANNELS:-tgsearchers3}"
PANSOU_ENABLED_PLUGINS="${PANSOU_ENABLED_PLUGINS:-panyq,pansearch,qupansou,hunhepan,jikepan,pan666}"
BROWSER_CONCURRENCY="${DARKWEB_BROWSER_CONCURRENCY:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$COLLECTOR_ROOT/.." && pwd)"
DASHBOARD_ROOT="$(cd "$PROJECT_ROOT/threat-intelligence-dashboard" && pwd)"
COLLECTOR_VENV="$COLLECTOR_ROOT/venv"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
DEFAULT_PROJECT_SOURCE_DB="$COLLECTOR_ROOT/data/collector.db"
COLLECTOR_SOURCE_DB="${DARKWEB_COLLECTOR_SOURCE_DB_PATH:-}"
COLLECTOR_RUNTIME_DB="${DARKWEB_COLLECTOR_DB_PATH:-$HOME/.local/share/bishe/collector.db}"
COLLECTOR_RUNTIME_DB_META="${DARKWEB_RUNTIME_DB_META_PATH:-${COLLECTOR_RUNTIME_DB}.meta.json}"
COLLECTOR_SITES_FILE="${DARKWEB_COLLECTOR_SITES_FILE:-$COLLECTOR_ROOT/sites.yaml}"
COLLECTOR_OUTPUT_ROOT="${DARKWEB_COLLECTOR_OUTPUT_ROOT:-$COLLECTOR_ROOT/output}"
REQUIREMENTS_STAMP="$COLLECTOR_VENV/.requirements.sha256"
PLAYWRIGHT_STAMP="$COLLECTOR_VENV/.playwright.chromium.ready"
PACKAGE_LOCK_STAMP="$DASHBOARD_ROOT/node_modules/.package-lock.sha256"
NPM_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/darkweb-threat-intel/npm"
USER_BIN_DIR="$HOME/.local/bin"
USER_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/darkweb-threat-intel"
USER_ENV_FILE="$USER_CONFIG_DIR/env.sh"
USER_COMMAND_PATH="$USER_BIN_DIR/darkweb"
PROFILE_MARKER_BEGIN="# >>> darkweb bootstrap >>>"
PROFILE_MARKER_END="# <<< darkweb bootstrap <<<"
RUNTIME_DIR="$COLLECTOR_ROOT/.runtime/wsl"
LOG_DIR="$RUNTIME_DIR/logs"
RUNTIME_PORTS_FILE="$RUNTIME_DIR/ports.env"
SERVICE_STATE_FILE="$RUNTIME_DIR/services.state"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

info() {
  echo "[INFO] $*"
}

warn() {
  echo "[WARN] $*"
}

require_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || die "missing required command: $command_name"
}

run_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi
  die "automatic dependency install requires sudo or root privileges"
}

ensure_directory() {
  mkdir -p "$1"
}

set_api_port() {
  API_PORT="$1"
  API_BASE_URL="http://${API_HOST}:${API_PORT}"
  API_HEALTH_URL="${API_BASE_URL}/api/health"
  API_JOBS_URL="${API_BASE_URL}/api/jobs"
}

set_frontend_port() {
  FRONTEND_PORT="$1"
  FRONTEND_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"
}

validate_positive_integer() {
  local value="$1"
  local name="$2"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || (( value < 1 )); then
    die "${name} must be a positive integer, got: $value"
  fi
}

looks_like_windows_path() {
  [[ "$1" =~ ^[A-Za-z]:[\\/].* ]]
}

sanitize_path_overrides() {
  if looks_like_windows_path "$COLLECTOR_RUNTIME_DB"; then
    warn "ignoring Windows DARKWEB_COLLECTOR_DB_PATH override in Linux shell"
    COLLECTOR_RUNTIME_DB="$HOME/.local/share/bishe/collector.db"
  fi

  if looks_like_windows_path "$COLLECTOR_RUNTIME_DB_META"; then
    warn "ignoring Windows DARKWEB_RUNTIME_DB_META_PATH override in Linux shell"
    COLLECTOR_RUNTIME_DB_META="${COLLECTOR_RUNTIME_DB}.meta.json"
  fi

  if [[ -n "$COLLECTOR_SOURCE_DB" ]] && looks_like_windows_path "$COLLECTOR_SOURCE_DB" && [[ ! -e "$COLLECTOR_SOURCE_DB" ]]; then
    warn "ignoring Windows DARKWEB_COLLECTOR_SOURCE_DB_PATH override in Linux shell"
    COLLECTOR_SOURCE_DB=""
  fi

  if looks_like_windows_path "$COLLECTOR_SITES_FILE" || [[ ! -f "$COLLECTOR_SITES_FILE" ]]; then
    warn "ignoring invalid DARKWEB_COLLECTOR_SITES_FILE override in Linux shell"
    COLLECTOR_SITES_FILE="$COLLECTOR_ROOT/sites.yaml"
  fi

  if looks_like_windows_path "$COLLECTOR_OUTPUT_ROOT"; then
    warn "ignoring Windows DARKWEB_COLLECTOR_OUTPUT_ROOT override in Linux shell"
    COLLECTOR_OUTPUT_ROOT="$COLLECTOR_ROOT/output"
  fi
}

get_redis_host() {
  local endpoint="${REDIS_URL#redis://}"
  endpoint="${endpoint#*@}"
  endpoint="${endpoint%%/*}"
  if [[ "$endpoint" == \[*\]*:* ]]; then
    endpoint="${endpoint%\]:*}"
    endpoint="${endpoint#[}"
  elif [[ "$endpoint" == *:* ]]; then
    endpoint="${endpoint%:*}"
  fi
  if [[ -z "$endpoint" ]]; then
    endpoint="127.0.0.1"
  fi
  printf '%s\n' "$endpoint"
}

get_redis_port() {
  local endpoint="${REDIS_URL#redis://}"
  endpoint="${endpoint#*@}"
  endpoint="${endpoint%%/*}"
  if [[ "$endpoint" == \[*\]*:* ]]; then
    printf '%s\n' "${endpoint##*:}"
    return 0
  fi
  if [[ "$endpoint" == *:* ]]; then
    printf '%s\n' "${endpoint##*:}"
    return 0
  fi
  printf '%s\n' "6379"
}

redis_endpoint_is_local() {
  case "$(get_redis_host)" in
    127.0.0.1|localhost|::1)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

redis_ping() {
  redis-cli -u "$REDIS_URL" ping 2>/dev/null | grep -q "PONG"
}

file_sha256() {
  local file_path="$1"
  python3 - "$file_path" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser()
if not path.exists():
    print("")
    raise SystemExit(0)

digest = sha256(path.read_bytes()).hexdigest()
print(digest)
PY
}

install_system_dependencies() {
  local missing_packages=()
  command -v tmux >/dev/null 2>&1 || missing_packages+=("tmux")
  command -v python3 >/dev/null 2>&1 || missing_packages+=("python3")
  if ! python3 -m venv --help >/dev/null 2>&1; then
    missing_packages+=("python3-venv")
  fi
  python3 -m pip --version >/dev/null 2>&1 || missing_packages+=("python3-pip")
  command -v npm >/dev/null 2>&1 || missing_packages+=("npm")
  command -v redis-cli >/dev/null 2>&1 || missing_packages+=("redis-tools")
  command -v curl >/dev/null 2>&1 || missing_packages+=("curl")
  if redis_endpoint_is_local; then
    command -v redis-server >/dev/null 2>&1 || missing_packages+=("redis-server")
  fi

  if (( ${#missing_packages[@]} == 0 )); then
    return 0
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    die "missing required system packages (${missing_packages[*]}), and apt-get is unavailable for automatic install"
  fi

  info "installing missing system packages: ${missing_packages[*]}"
  run_as_root apt-get update
  run_as_root apt-get install -y "${missing_packages[@]}"
}

collector_venv_ready() {
  [[ -x "$COLLECTOR_VENV/bin/python" ]] || return 1
  "$COLLECTOR_VENV/bin/python" -c "import sys, pathlib, venv; raise SystemExit(0 if pathlib.Path(sys.executable).exists() and pathlib.Path(sys.prefix).exists() else 1)" >/dev/null 2>&1
}

ensure_collector_venv() {
  if [[ -d "$COLLECTOR_VENV" ]] && ! collector_venv_ready; then
    warn "collector venv is not usable on this machine, rebuilding it"
    [[ "$COLLECTOR_VENV" == "$COLLECTOR_ROOT/"* ]] || die "refusing to delete unexpected venv path: $COLLECTOR_VENV"
    rm -rf -- "$COLLECTOR_VENV"
  fi

  if collector_venv_ready; then
    return 0
  fi

  info "collector venv missing, creating virtual environment"
  python3 -m venv "$COLLECTOR_VENV"
}

collector_python_dependencies_ready() {
  (
    source "$COLLECTOR_VENV/bin/activate"
    python - <<'PY'
modules = ("celery", "redis", "playwright", "fastapi", "uvicorn", "pycountry", "babel")
for module_name in modules:
    __import__(module_name)
PY
  ) >/dev/null 2>&1
}

ensure_collector_python_dependencies() {
  local requirements_hash current_hash
  requirements_hash="$(file_sha256 "$COLLECTOR_ROOT/requirements.txt")"
  current_hash=""
  if [[ -f "$REQUIREMENTS_STAMP" ]]; then
    current_hash="$(<"$REQUIREMENTS_STAMP")"
  fi
  if [[ -n "$requirements_hash" && "$requirements_hash" == "$current_hash" ]] && collector_python_dependencies_ready; then
    return 0
  fi

  info "installing collector Python dependencies"
  (
    cd "$COLLECTOR_ROOT"
    source "$COLLECTOR_VENV/bin/activate"
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
  )
  ensure_directory "$(dirname "$REQUIREMENTS_STAMP")"
  printf '%s' "$requirements_hash" > "$REQUIREMENTS_STAMP"
}

playwright_runtime_ready() {
  (
    source "$COLLECTOR_VENV/bin/activate"
    python - <<'PY'
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    executables = (
        Path(playwright.chromium.executable_path),
        Path(playwright.firefox.executable_path),
    )
    raise SystemExit(0 if all(path.exists() for path in executables) else 1)
PY
  ) >/dev/null 2>&1
}

ensure_playwright_runtime() {
  if [[ -f "$PLAYWRIGHT_STAMP" ]] && playwright_runtime_ready; then
    return 0
  fi

  info "installing Playwright browser runtimes"
  (
    cd "$COLLECTOR_ROOT"
    source "$COLLECTOR_VENV/bin/activate"
    python -m playwright install chromium firefox
  )
  ensure_directory "$(dirname "$PLAYWRIGHT_STAMP")"
  : > "$PLAYWRIGHT_STAMP"
}

dashboard_dependencies_ready() {
  [[ -d "$DASHBOARD_ROOT/node_modules" && -f "$DASHBOARD_ROOT/node_modules/.bin/vite" ]]
}

ensure_dashboard_dependencies() {
  local expected_hash current_hash
  expected_hash="$(file_sha256 "$DASHBOARD_ROOT/package-lock.json")"
  current_hash=""
  if [[ -f "$PACKAGE_LOCK_STAMP" ]]; then
    current_hash="$(<"$PACKAGE_LOCK_STAMP")"
  fi

  if dashboard_dependencies_ready && [[ -n "$expected_hash" && "$expected_hash" == "$current_hash" ]]; then
    return 0
  fi

  info "installing dashboard dependencies"
  ensure_directory "$NPM_CACHE_DIR"
  (
    cd "$DASHBOARD_ROOT"
    export NPM_CONFIG_CACHE="$NPM_CACHE_DIR"
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
  )
  ensure_directory "$(dirname "$PACKAGE_LOCK_STAMP")"
  printf '%s' "$expected_hash" > "$PACKAGE_LOCK_STAMP"
}

initialize_empty_runtime_db() {
  info "no source database found, initializing empty runtime database"
  python3 - "$COLLECTOR_ROOT" "$COLLECTOR_RUNTIME_DB" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).expanduser().resolve()
target = Path(sys.argv[2]).expanduser().resolve()
src = root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from darkweb_collector.db import connect

target.parent.mkdir(parents=True, exist_ok=True)
connection = connect(target)
try:
    connection.commit()
finally:
    connection.close()
PY
}

db_has_data() {
  local db_path="$1"
  python3 - "$db_path" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
if not path.exists():
    raise SystemExit(2)

tables = ("collection_runs", "victims", "forum_details", "crawl_jobs", "vulnerability_records", "ransomware_live_victims", "normalized_intelligence_events")
connection = sqlite3.connect(str(path))
try:
    for table_name in tables:
        try:
            row = connection.execute("SELECT COUNT(1) FROM " + table_name).fetchone()
        except Exception:
            continue
        if row and int(row[0]) > 0:
            raise SystemExit(0)
finally:
    connection.close()

raise SystemExit(1)
PY
}

db_score() {
  local db_path="$1"
  python3 - "$db_path" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
if not path.exists():
    print(-1)
    raise SystemExit(0)

tables = ("victims", "forum_details", "crawl_jobs", "vulnerability_records", "ransomware_live_victims", "normalized_intelligence_events")
score = 0
connection = sqlite3.connect(str(path))
try:
    for table_name in tables:
        try:
            row = connection.execute("SELECT COUNT(1) FROM " + table_name).fetchone()
        except Exception:
            continue
        if row:
            score += int(row[0])
finally:
    connection.close()

print(score)
PY
}

resolve_source_db() {
  local candidates=()
  local candidate pattern score
  local best_path=""
  local best_score=-1

  if [[ -n "$COLLECTOR_SOURCE_DB" ]]; then
    candidates+=("$COLLECTOR_SOURCE_DB")
  else
    candidates+=("$COLLECTOR_RUNTIME_DB" "$DEFAULT_PROJECT_SOURCE_DB")
    for pattern in \
      /mnt/c/Users/*/AppData/Local/DarkWebThreatIntel/collector.db \
      /mnt/c/Users/*/.local/share/bishe/collector.db; do
      for candidate in $pattern; do
        [[ -e "$candidate" ]] || continue
        candidates+=("$candidate")
      done
    done
  fi

  for candidate in "${candidates[@]}"; do
    score="$(db_score "$candidate")"
    if (( score > best_score )); then
      best_score="$score"
      best_path="$candidate"
    fi
  done

  if [[ -n "$best_path" ]]; then
    COLLECTOR_SOURCE_DB="$best_path"
  else
    COLLECTOR_SOURCE_DB="$COLLECTOR_RUNTIME_DB"
  fi
}

sync_runtime_db_to_source() {
  if [[ "$COLLECTOR_RUNTIME_DB" == "$COLLECTOR_SOURCE_DB" ]]; then
    return 0
  fi

  local runtime_score source_score
  runtime_score="$(db_score "$COLLECTOR_RUNTIME_DB")"
  source_score="$(db_score "$COLLECTOR_SOURCE_DB")"
  if (( runtime_score <= 0 )) || (( runtime_score <= source_score )); then
    return 0
  fi

  info "syncing populated runtime db back to source db"
  ensure_directory "$(dirname "$COLLECTOR_SOURCE_DB")"
  cp -f "$COLLECTOR_RUNTIME_DB" "$COLLECTOR_SOURCE_DB"
}

site_configs_ready() {
  python3 - "$COLLECTOR_ROOT" "$COLLECTOR_SITES_FILE" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).expanduser().resolve()
sites_file = Path(sys.argv[2]).expanduser().resolve()
src = root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from darkweb_collector.config import load_site_configs
from darkweb_collector.adapters.registry import get_adapter

configs = load_site_configs(sites_file)
if not configs:
    raise SystemExit("no site config found")

missing = []
for config in configs:
    try:
        get_adapter(config.site_name)
    except Exception as exc:
        missing.append(f"{config.site_name}: {exc}")

if missing:
    raise SystemExit("adapter missing for configured sites: " + "; ".join(missing))
PY
}

build_env_exports() {
  local exports=()
  exports+=("export DARKWEB_HOME=$(printf '%q' "$PROJECT_ROOT")")
  exports+=("export DARKWEB_PROJECT_ROOT=$(printf '%q' "$PROJECT_ROOT")")
  exports+=("export DARKWEB_COLLECTOR_ROOT=$(printf '%q' "$COLLECTOR_ROOT")")
  exports+=("export DARKWEB_DASHBOARD_ROOT=$(printf '%q' "$DASHBOARD_ROOT")")
  exports+=("export REDIS_URL=$(printf '%q' "$REDIS_URL")")
  exports+=("export PYTHONPATH=$(printf '%q' "$COLLECTOR_ROOT/src"):\${PYTHONPATH:-}")
  exports+=("export DARKWEB_COLLECTOR_DB_PATH=$(printf '%q' "$COLLECTOR_RUNTIME_DB")")
  exports+=("export DARKWEB_COLLECTOR_SOURCE_DB_PATH=$(printf '%q' "$COLLECTOR_SOURCE_DB")")
  exports+=("export DARKWEB_RUNTIME_DB_META_PATH=$(printf '%q' "$COLLECTOR_RUNTIME_DB_META")")
  if [[ "$DARKWEB_PANSOU_ENABLED" != "0" ]]; then
    exports+=("export PANSOU_API_BASE=$(printf '%q' "$PANSOU_API_BASE")")
  fi
  exports+=("export DARKWEB_COLLECTOR_SITES_FILE=$(printf '%q' "$COLLECTOR_SITES_FILE")")
  exports+=("export DARKWEB_COLLECTOR_OUTPUT_ROOT=$(printf '%q' "$COLLECTOR_OUTPUT_ROOT")")
  exports+=("export DARKWEB_API_PORT=$(printf '%q' "$API_PORT")")
  exports+=("export DARKWEB_API_TARGET=$(printf '%q' "$API_BASE_URL")")
  exports+=("export DARKWEB_FRONTEND_PORT=$(printf '%q' "$FRONTEND_PORT")")
  exports+=("export DARKWEB_FRONTEND_URL=$(printf '%q' "$FRONTEND_URL")")
  exports+=("export VITE_API_TARGET=$(printf '%q' "$API_BASE_URL")")
  exports+=("export VITE_FRONTEND_PORT=$(printf '%q' "$FRONTEND_PORT")")
  exports+=("export DARKWEB_BROWSER_CONCURRENCY=$(printf '%q' "$BROWSER_CONCURRENCY")")
  for var_name in TOR_SOCKS_HOST TOR_SOCKS_PORT PROXY_HOST PROXY_PORT; do
    if [[ -n "${!var_name:-}" ]]; then
      exports+=("export ${var_name}=$(printf '%q' "${!var_name}")")
    fi
  done
  printf '%s; ' "${exports[@]}"
}

save_runtime_ports() {
  ensure_directory "$RUNTIME_DIR"
  cat > "$RUNTIME_PORTS_FILE" <<EOF
API_PORT=$API_PORT
API_BASE_URL=$(printf '%q' "$API_BASE_URL")
API_HEALTH_URL=$(printf '%q' "$API_HEALTH_URL")
API_JOBS_URL=$(printf '%q' "$API_JOBS_URL")
FRONTEND_PORT=$FRONTEND_PORT
FRONTEND_URL=$(printf '%q' "$FRONTEND_URL")
EOF
}

load_runtime_ports() {
  if [[ ! -f "$RUNTIME_PORTS_FILE" ]]; then
    return 0
  fi

  # shellcheck disable=SC1090
  . "$RUNTIME_PORTS_FILE"
  set_api_port "$API_PORT"
  set_frontend_port "$FRONTEND_PORT"
}

save_service_records() {
  ensure_directory "$RUNTIME_DIR"
  : > "$SERVICE_STATE_FILE"
  while (( "$#" )); do
    printf '%s|%s\n' "$1" "$2" >> "$SERVICE_STATE_FILE"
    shift 2
  done
}

service_window_exists() {
  local window_name="$1"
  tmux has-session -t "$SESSION_NAME" 2>/dev/null || return 1
  tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' 2>/dev/null | grep -qx "$window_name"
}

show_service_records() {
  if [[ ! -f "$SERVICE_STATE_FILE" ]]; then
    return 0
  fi

  while IFS='|' read -r service_name log_path; do
    [[ -n "$service_name" ]] || continue
    local state="down"
    if service_window_exists "$service_name"; then
      state="up"
    fi
    info "${service_name}: ${state} (log ${log_path})"
  done < "$SERVICE_STATE_FILE"
}

write_user_env_file() {
  ensure_directory "$USER_CONFIG_DIR"
  {
    echo "# Generated by darkweb register"
    printf 'export DARKWEB_HOME=%q\n' "$PROJECT_ROOT"
    printf 'export DARKWEB_PROJECT_ROOT=%q\n' "$PROJECT_ROOT"
    printf 'export DARKWEB_COLLECTOR_ROOT=%q\n' "$COLLECTOR_ROOT"
    printf 'export DARKWEB_DASHBOARD_ROOT=%q\n' "$DASHBOARD_ROOT"
    printf 'export REDIS_URL=%q\n' "$REDIS_URL"
    printf 'export DARKWEB_COLLECTOR_DB_PATH=%q\n' "$COLLECTOR_RUNTIME_DB"
    printf 'export DARKWEB_COLLECTOR_SOURCE_DB_PATH=%q\n' "$COLLECTOR_SOURCE_DB"
    printf 'export DARKWEB_RUNTIME_DB_META_PATH=%q\n' "$COLLECTOR_RUNTIME_DB_META"
    printf 'export DARKWEB_PANSOU_ENABLED=%q\n' "$DARKWEB_PANSOU_ENABLED"
    printf 'export PANSOU_PORT=%q\n' "$PANSOU_PORT"
    printf 'export PANSOU_API_BASE=%q\n' "$PANSOU_API_BASE"
    printf 'export PANSOU_CONTAINER_NAME=%q\n' "$PANSOU_CONTAINER_NAME"
    printf 'export PANSOU_IMAGE=%q\n' "$PANSOU_IMAGE"
    printf 'export PANSOU_CHANNELS=%q\n' "$PANSOU_CHANNELS"
    printf 'export PANSOU_ENABLED_PLUGINS=%q\n' "$PANSOU_ENABLED_PLUGINS"
    printf 'export DARKWEB_COLLECTOR_SITES_FILE=%q\n' "$COLLECTOR_SITES_FILE"
    printf 'export DARKWEB_COLLECTOR_OUTPUT_ROOT=%q\n' "$COLLECTOR_OUTPUT_ROOT"
    printf 'export DARKWEB_API_PORT=%q\n' "$API_PORT"
    printf 'export DARKWEB_API_TARGET=%q\n' "$API_BASE_URL"
    printf 'export DARKWEB_FRONTEND_PORT=%q\n' "$FRONTEND_PORT"
    printf 'export DARKWEB_FRONTEND_URL=%q\n' "$FRONTEND_URL"
    printf 'export VITE_API_TARGET=%q\n' "$API_BASE_URL"
    printf 'export VITE_FRONTEND_PORT=%q\n' "$FRONTEND_PORT"
    printf 'export DARKWEB_BROWSER_CONCURRENCY=%q\n' "$BROWSER_CONCURRENCY"
    for var_name in TOR_SOCKS_HOST TOR_SOCKS_PORT PROXY_HOST PROXY_PORT; do
      if [[ -n "${!var_name:-}" ]]; then
        printf 'export %s=%q\n' "$var_name" "${!var_name}"
      fi
    done
  } > "$USER_ENV_FILE"
}

write_darkweb_command() {
  ensure_directory "$USER_BIN_DIR"
  cat > "$USER_COMMAND_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${USER_ENV_FILE}"
if [ -f "\$ENV_FILE" ]; then
  . "\$ENV_FILE"
fi

COLLECTOR_ROOT="\${DARKWEB_COLLECTOR_ROOT:-${COLLECTOR_ROOT}}"
SCRIPT_PATH="\$COLLECTOR_ROOT/scripts/start_all_services_wsl.sh"

if [ ! -f "\$SCRIPT_PATH" ]; then
  echo "[ERROR] DARKWEB_COLLECTOR_ROOT is not valid. Run bash ${COLLECTOR_ROOT}/scripts/start_all_services_wsl.sh register from the project root." >&2
  exit 1
fi

if [ "\$#" -eq 0 ]; then
  exec bash "\$SCRIPT_PATH" start
fi

exec bash "\$SCRIPT_PATH" "\$@"
EOF
  chmod +x "$USER_COMMAND_PATH"
}

update_shell_startup_file() {
  local rc_file="$1"
  local rc_dir
  local temp_file

  rc_dir="$(dirname "$rc_file")"
  ensure_directory "$rc_dir"
  temp_file="${rc_file}.tmp.$$"

  if [[ -f "$rc_file" ]]; then
    awk -v begin="$PROFILE_MARKER_BEGIN" -v end="$PROFILE_MARKER_END" '
      $0 == begin { skip = 1; next }
      $0 == end { skip = 0; next }
      !skip { print }
    ' "$rc_file" > "$temp_file"
    mv "$temp_file" "$rc_file"
  else
    : > "$rc_file"
  fi

  if [[ -s "$rc_file" ]]; then
    printf '\n' >> "$rc_file"
  fi

  cat >> "$rc_file" <<EOF
$PROFILE_MARKER_BEGIN
export PATH="$USER_BIN_DIR:\$PATH"
if [ -f "$USER_ENV_FILE" ]; then
  . "$USER_ENV_FILE"
fi
$PROFILE_MARKER_END
EOF
}

register_darkweb_command() {
  load_runtime_ports
  validate_positive_integer "$API_PORT" "DARKWEB_API_PORT"
  validate_positive_integer "$FRONTEND_PORT" "DARKWEB_FRONTEND_PORT"
  validate_positive_integer "$BROWSER_CONCURRENCY" "DARKWEB_BROWSER_CONCURRENCY"
  if [[ -z "$COLLECTOR_SOURCE_DB" ]]; then
    if [[ -f "$DEFAULT_PROJECT_SOURCE_DB" ]]; then
      COLLECTOR_SOURCE_DB="$DEFAULT_PROJECT_SOURCE_DB"
    else
      COLLECTOR_SOURCE_DB="$COLLECTOR_RUNTIME_DB"
    fi
  fi
  write_user_env_file
  write_darkweb_command
  update_shell_startup_file "$HOME/.profile"
  update_shell_startup_file "$HOME/.bashrc"
  info "registered darkweb command: $USER_COMMAND_PATH"
  info "registered user environment file: $USER_ENV_FILE"
  info "open a new shell, or run: . \"$USER_ENV_FILE\" && export PATH=\"$USER_BIN_DIR:\$PATH\""
}

ensure_pansou() {
  if [[ "$DARKWEB_PANSOU_ENABLED" == "0" ]]; then
    info "PanSou disabled"
    return 0
  fi

  local health_url="${PANSOU_API_BASE%/}/api/health"

  if curl -fsS "$health_url" >/dev/null 2>&1; then
    info "PanSou already running: $PANSOU_API_BASE"
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    warn "PanSou is enabled but docker is unavailable; netdisk scan will continue with HTML aggregation sources only"
    return 0
  fi
  if ! docker info >/dev/null 2>&1; then
    warn "PanSou is enabled but docker engine is not running; netdisk scan will continue with HTML aggregation sources only"
    return 0
  fi
  if docker ps --filter "name=^/${PANSOU_CONTAINER_NAME}$" --format '{{.Names}}' | grep -qx "$PANSOU_CONTAINER_NAME"; then
    info "PanSou container already running: $PANSOU_CONTAINER_NAME"
    return 0
  fi
  if docker ps -a --filter "name=^/${PANSOU_CONTAINER_NAME}$" --format '{{.Names}}' | grep -qx "$PANSOU_CONTAINER_NAME"; then
    info "starting PanSou container: $PANSOU_CONTAINER_NAME"
    docker start "$PANSOU_CONTAINER_NAME" >/dev/null || warn "failed to start PanSou container"
  else
    info "creating PanSou container: $PANSOU_CONTAINER_NAME"
    docker run -d \
      --name "$PANSOU_CONTAINER_NAME" \
      -p "${PANSOU_PORT}:8888" \
      -e CHANNELS="$PANSOU_CHANNELS" \
      -e ENABLED_PLUGINS="$PANSOU_ENABLED_PLUGINS" \
      "$PANSOU_IMAGE" >/dev/null || warn "failed to create PanSou container"
  fi
  if ! wait_for_condition "curl -fsS $(printf '%q' "$health_url") >/dev/null 2>&1" 30; then
    warn "PanSou did not become ready within 30s: $PANSOU_API_BASE"
  else
    info "PanSou: $PANSOU_API_BASE"
  fi
}

ensure_environment() {
  validate_positive_integer "$API_PORT" "DARKWEB_API_PORT"
  validate_positive_integer "$FRONTEND_PORT" "DARKWEB_FRONTEND_PORT"
  validate_positive_integer "$BROWSER_CONCURRENCY" "DARKWEB_BROWSER_CONCURRENCY"
  validate_positive_integer "$SCHEDULER_INTERVAL_SECONDS" "SCHEDULER_INTERVAL_SECONDS"
  validate_positive_integer "$VULN_SYNC_INTERVAL_SECONDS" "VULN_SYNC_INTERVAL_SECONDS"
  validate_positive_integer "$VULN_SYNC_LIMIT" "VULN_SYNC_LIMIT"

  install_system_dependencies
  require_command tmux
  require_command python3
  require_command npm
  require_command redis-cli
  require_command curl
  if redis_endpoint_is_local; then
    require_command redis-server
  fi

  ensure_collector_venv
  [[ -f "$COLLECTOR_ROOT/scripts/serve_api.py" ]] || die "API launcher not found"
  [[ -f "$DASHBOARD_ROOT/package.json" ]] || die "dashboard package.json not found"

  ensure_collector_python_dependencies
  ensure_playwright_runtime
  resolve_source_db
  ensure_dashboard_dependencies

  if [[ ! -f "$COLLECTOR_RUNTIME_DB" ]] || ! db_has_data "$COLLECTOR_RUNTIME_DB"; then
    if [[ -f "$COLLECTOR_SOURCE_DB" ]] && db_has_data "$COLLECTOR_SOURCE_DB"; then
      info "runtime db missing, preparing stable WSL-local SQLite database"
      (
        cd "$COLLECTOR_ROOT"
        source "$COLLECTOR_VENV/bin/activate"
        python scripts/prepare_runtime_db.py --force --source "$COLLECTOR_SOURCE_DB" --target "$COLLECTOR_RUNTIME_DB"
      )
    else
      initialize_empty_runtime_db
    fi
  fi

  site_configs_ready || die "failed to load crawler site configuration from $COLLECTOR_SITES_FILE"
  sync_runtime_db_to_source
  ensure_pansou
}

stop_session_if_exists() {
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    info "stopping existing tmux session: $SESSION_NAME"
    tmux kill-session -t "$SESSION_NAME"
  fi
}

cleanup_stray_processes() {
  pkill -f "scripts/serve_api.py" 2>/dev/null || true
  pkill -f "/threat-intelligence-dashboard/node_modules/.bin/vite" 2>/dev/null || true
  pkill -f "darkweb_collector.celery_app:app worker" 2>/dev/null || true
  pkill -f "scripts/crawl.py enqueue-due" 2>/dev/null || true
  pkill -f "scripts/crawl.py sync-public-vulns" 2>/dev/null || true
}

tmux_new_window() {
  local window_name="$1"
  local log_path="$2"
  shift 2
  local command_body="$*"
  local wrapped_command
  wrapped_command="
set +e
exec > >(tee -a $(printf '%q' "$log_path")) 2>&1
$command_body
status=\$?
if [[ \$status -ne 0 ]]; then
  echo
  echo \"[ERROR] process exited with code \$status\"
fi
exec bash
"
  tmux new-window -t "${SESSION_NAME}:" -n "$window_name" "bash -c $(printf '%q' "$wrapped_command")"
}

wait_for_condition() {
  local command_body="$1"
  local timeout_seconds="$2"
  local started_at
  started_at="$(date +%s)"
  while true; do
    if bash -c "$command_body" >/dev/null 2>&1; then
      return 0
    fi
    if (( "$(date +%s)" - started_at >= timeout_seconds )); then
      return 1
    fi
    sleep 1
  done
}

capture_window_logs() {
  local window_name="$1"
  local lines="${2:-120}"
  if tmux list-windows -t "$SESSION_NAME" -F '#{window_name}' 2>/dev/null | grep -qx "$window_name"; then
    printf '\n[INFO] last %s lines from %s:\n' "$lines" "$window_name"
    tmux capture-pane -pt "${SESSION_NAME}:${window_name}" -S "-${lines}" || true
  fi
}

describe_port_owner() {
  local port="$1"
  local details
  details="$(ss -ltnp 2>/dev/null | grep ":${port} " || true)"
  if [[ -n "$details" ]]; then
    warn "port ${port} is currently held by:"
    echo "$details"
  fi
}

api_ready() {
  python3 - "$1" <<'PY'
import json
import sys
from urllib.request import urlopen

try:
    with urlopen(sys.argv[1], timeout=3) as response:
        payload = json.load(response)
except Exception:
    raise SystemExit(1)

site_health = payload.get("site_health")
raise SystemExit(0 if isinstance(site_health, list) and len(site_health) > 0 else 1)
PY
}

frontend_ready() {
  curl -fsS "$FRONTEND_URL" >/dev/null 2>&1 || return 1
  api_ready "$FRONTEND_URL/api/jobs"
}

test_port_bindable() {
  python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("0.0.0.0", port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

find_available_port() {
  local candidate
  for candidate in "$@"; do
    if test_port_bindable "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done

  for candidate in $(seq 18000 18099); do
    if test_port_bindable "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done

  die "no available fallback port found in 18000-18099"
}

ensure_api_port() {
  if test_port_bindable "$API_PORT"; then
    return 0
  fi
  describe_port_owner "$API_PORT"
  warn "api port $API_PORT is unavailable, choosing a fallback port"
  set_api_port "$(find_available_port 18000 18001 18002 18003 18004 18005)"
}

ensure_frontend_port() {
  if test_port_bindable "$FRONTEND_PORT"; then
    return 0
  fi
  describe_port_owner "$FRONTEND_PORT"
  warn "frontend port $FRONTEND_PORT is unavailable, choosing a fallback port"
  set_frontend_port "$(find_available_port 18010 18011 18012 18013 18014 18015)"
}

start_docker_redis_if_available() {
  local redis_port
  local docker_bin
  local container_name="darkweb-redis"

  redis_endpoint_is_local || return 1
  docker_bin="$(command -v docker 2>/dev/null || true)"
  [[ -n "$docker_bin" ]] || return 1

  redis_port="$(get_redis_port)"
  if "$docker_bin" ps --filter "name=^/${container_name}$" --format '{{.Names}}' 2>/dev/null | grep -qx "$container_name"; then
    return 0
  fi

  if "$docker_bin" ps -a --filter "name=^/${container_name}$" --format '{{.Names}}' 2>/dev/null | grep -qx "$container_name"; then
    info "starting Redis Docker container: ${container_name}"
    "$docker_bin" start "$container_name" >/dev/null
  else
    info "creating Redis Docker container: ${container_name}"
    "$docker_bin" run -d --name "$container_name" -p "${redis_port}:6379" redis:7-alpine >/dev/null
  fi
}

ensure_redis_runtime() {
  if redis_ping; then
    return 0
  fi

  if ! redis_endpoint_is_local; then
    die "REDIS_URL points to $REDIS_URL, but it is not reachable."
  fi

  local redis_port
  redis_port="$(get_redis_port)"

  if sudo -n service redis-server start >/dev/null 2>&1 && redis_ping; then
    return 0
  fi

  if redis-server --daemonize yes --port "$redis_port" >/dev/null 2>&1; then
    sleep 1
    if redis_ping; then
      return 0
    fi
  fi

  if start_docker_redis_if_available; then
    sleep 2
    if redis_ping; then
      return 0
    fi
  fi

  die "redis is not reachable at $REDIS_URL"
}

start_services() {
  ensure_environment
  ensure_redis_runtime
  stop_session_if_exists
  cleanup_stray_processes
  ensure_api_port
  ensure_frontend_port
  ensure_directory "$RUNTIME_DIR"
  ensure_directory "$LOG_DIR"
  save_runtime_ports
  register_darkweb_command

  local env_exports
  env_exports="$(build_env_exports)"
  local redis_log="$LOG_DIR/redis.log"
  local api_log="$LOG_DIR/api.log"
  local frontend_log="$LOG_DIR/frontend.log"
  local seed_worker_log="$LOG_DIR/worker-seed.log"
  local detail_worker_log="$LOG_DIR/worker-detail.log"
  local scheduler_log="$LOG_DIR/scheduler.log"
  local vulnerability_sync_log="$LOG_DIR/vuln-sync.log"

  local redis_command
  redis_command="
set -euo pipefail
exec > >(tee -a $(printf '%q' "$redis_log")) 2>&1
if redis-cli -u \"$REDIS_URL\" ping >/dev/null 2>&1; then
  echo 'redis already running'
else
  echo 'redis not reachable'
  exit 1
fi
redis-cli -u \"$REDIS_URL\" ping
tail -f /dev/null
"

  local api_command
  api_command="
set -euo pipefail
cd \"$COLLECTOR_ROOT\"
${env_exports}
source \"$COLLECTOR_VENV/bin/activate\"
python scripts/serve_api.py
"

  local frontend_command
  frontend_command="
set -euo pipefail
cd \"$DASHBOARD_ROOT\"
${env_exports}
./node_modules/.bin/vite --host 0.0.0.0 --port $FRONTEND_PORT --strictPort
"

  local seed_worker_command
  seed_worker_command="
set -euo pipefail
cd \"$COLLECTOR_ROOT\"
${env_exports}
source \"$COLLECTOR_VENV/bin/activate\"
python scripts/crawl.py worker --queue seed_http
"

  local detail_worker_command
  detail_worker_command="
set -euo pipefail
cd \"$COLLECTOR_ROOT\"
${env_exports}
source \"$COLLECTOR_VENV/bin/activate\"
python scripts/crawl.py worker --queue detail_http
"

  local browser_worker_command
  browser_worker_command="
set -euo pipefail
cd \"$COLLECTOR_ROOT\"
${env_exports}
source \"$COLLECTOR_VENV/bin/activate\"
python scripts/crawl.py worker --queue browser_render
"

  local scheduler_command
  scheduler_command="
set -euo pipefail
cd \"$COLLECTOR_ROOT\"
${env_exports}
source \"$COLLECTOR_VENV/bin/activate\"
while true; do
  echo \"[\$(date '+%F %T')] enqueue-due\"
  python scripts/crawl.py enqueue-due || true
  sleep $SCHEDULER_INTERVAL_SECONDS
done
"

  local vulnerability_sync_command
  vulnerability_sync_command="
set -euo pipefail
cd \"$COLLECTOR_ROOT\"
${env_exports}
source \"$COLLECTOR_VENV/bin/activate\"
while true; do
  echo \"[\$(date '+%F %T')] sync-public-vulns --limit $VULN_SYNC_LIMIT\"
  python scripts/crawl.py sync-public-vulns --limit $VULN_SYNC_LIMIT || true
  sleep $VULN_SYNC_INTERVAL_SECONDS
done
"

  tmux new-session -d -s "$SESSION_NAME" -n "redis" "bash -c $(printf '%q' "$redis_command")"
  tmux setw -t "$SESSION_NAME" remain-on-exit on

  tmux_new_window "api" "$api_log" "$api_command"

  sleep 2

  if ! wait_for_condition "python3 - <<'PY'
import json
import sys
from urllib.request import urlopen

with urlopen('$API_JOBS_URL', timeout=3) as response:
    payload = json.load(response)
site_health = payload.get('site_health')
raise SystemExit(0 if isinstance(site_health, list) and len(site_health) > 0 else 1)
PY" "$SERVICE_WAIT_SECONDS"; then
    warn "api health check did not become ready within ${SERVICE_WAIT_SECONDS}s"
    describe_port_owner "$API_PORT"
    capture_window_logs "api" 120
  fi

  tmux_new_window "frontend" "$frontend_log" "$frontend_command"
  tmux_new_window "worker-seed" "$seed_worker_log" "$seed_worker_command"
  tmux_new_window "worker-detail" "$detail_worker_log" "$detail_worker_command"

  local browser_index browser_window
  local service_records=(
    "redis" "$redis_log"
    "api" "$api_log"
    "frontend" "$frontend_log"
    "worker-seed" "$seed_worker_log"
    "worker-detail" "$detail_worker_log"
  )
  for (( browser_index = 1; browser_index <= BROWSER_CONCURRENCY; browser_index++ )); do
    browser_window="worker-browser"
    if (( BROWSER_CONCURRENCY > 1 )); then
      browser_window="worker-browser-${browser_index}"
    fi
    local browser_log="$LOG_DIR/${browser_window}.log"
    tmux_new_window "$browser_window" "$browser_log" "$browser_worker_command"
    service_records+=("$browser_window" "$browser_log")
  done

  tmux_new_window "scheduler" "$scheduler_log" "$scheduler_command"
  tmux_new_window "vuln-sync" "$vulnerability_sync_log" "$vulnerability_sync_command"
  service_records+=(
    "scheduler" "$scheduler_log"
    "vuln-sync" "$vulnerability_sync_log"
  )
  save_service_records "${service_records[@]}"

  if ! wait_for_condition "curl -fsS '$FRONTEND_URL' >/dev/null 2>&1 && python3 - <<'PY'
import json
import sys
from urllib.request import urlopen

with urlopen('$FRONTEND_URL/api/jobs', timeout=3) as response:
    payload = json.load(response)
site_health = payload.get('site_health')
raise SystemExit(0 if isinstance(site_health, list) and len(site_health) > 0 else 1)
PY" "$SERVICE_WAIT_SECONDS"; then
    warn "frontend did not become ready within ${SERVICE_WAIT_SECONDS}s"
    describe_port_owner "$FRONTEND_PORT"
    capture_window_logs "frontend" 120
  fi

  info "tmux session created: $SESSION_NAME"
  info "frontend: $FRONTEND_URL"
  info "api health: $API_HEALTH_URL"
  info "vulnerability sync interval: ${VULN_SYNC_INTERVAL_SECONDS}s (limit=${VULN_SYNC_LIMIT})"
  info "logs: $LOG_DIR"
  info "attach with: tmux attach -t $SESSION_NAME"
  echo
  show_status
}

stop_services() {
  load_runtime_ports
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux kill-session -t "$SESSION_NAME"
  fi
  cleanup_stray_processes
  resolve_source_db
  sync_runtime_db_to_source
  rm -f -- "$SERVICE_STATE_FILE"
  info "tmux session stopped: $SESSION_NAME"
}

attach_session() {
  tmux has-session -t "$SESSION_NAME" 2>/dev/null || die "tmux session not running: $SESSION_NAME"
  exec tmux attach -t "$SESSION_NAME"
}

show_status() {
  load_runtime_ports
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    info "tmux session: $SESSION_NAME"
    tmux list-windows -t "$SESSION_NAME"
  else
    info "tmux session not running: $SESSION_NAME"
  fi

  show_service_records

  if redis_ping; then
    info "redis: up"
  else
    info "redis: down"
  fi

  if api_ready "$API_JOBS_URL"; then
    info "api: up ($API_JOBS_URL)"
  else
    info "api: down"
    describe_port_owner "$API_PORT"
    capture_window_logs "api" 80
  fi

  if frontend_ready; then
    info "frontend: up ($FRONTEND_URL)"
  else
    info "frontend: down"
    describe_port_owner "$FRONTEND_PORT"
    capture_window_logs "frontend" 80
  fi
}

main() {
  local action="${1:-start}"
  sanitize_path_overrides
  case "$action" in
    start)
      start_services
      ;;
    stop)
      stop_services
      ;;
    attach)
      attach_session
      ;;
    status)
      show_status
      ;;
    install)
      ensure_environment
      register_darkweb_command
      info "environment is ready. Run 'darkweb' to start the system."
      ;;
    register)
      register_darkweb_command
      ;;
    *)
      die "unsupported action: $action (use start|stop|attach|status|install|register)"
      ;;
  esac
}

main "${1:-start}"
