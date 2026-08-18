#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="bishe-stack"
SCHEDULER_INTERVAL_SECONDS=60
API_HEALTH_URL="http://127.0.0.1:8000/api/health"
FRONTEND_URL="http://127.0.0.1:5173"
SERVICE_WAIT_SECONDS=45
VULN_SYNC_INTERVAL_SECONDS="${VULN_SYNC_INTERVAL_SECONDS:-3600}"
VULN_SYNC_LIMIT="${VULN_SYNC_LIMIT:-300}"
NORMALIZER_POLL_SECONDS="${NORMALIZER_POLL_SECONDS:-5}"
NORMALIZER_DEBOUNCE_SECONDS="${NORMALIZER_DEBOUNCE_SECONDS:-60}"
NORMALIZER_MAX_DELAY_SECONDS="${NORMALIZER_MAX_DELAY_SECONDS:-300}"
FRONTEND_MODE="${FRONTEND_MODE:-preview}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DASHBOARD_ROOT="$(cd "$COLLECTOR_ROOT/../threat-intelligence-dashboard" && pwd)"

# Auto-load proxy/Tor routing from .env (PROXY_HOST/PORT, TOR_SOCKS_HOST/PORT,
# HTTP_PROXY/HTTPS_PROXY/NO_PROXY). These are forwarded into every tmux window
# by build_env_exports below.
if [[ -f "$COLLECTOR_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$COLLECTOR_ROOT/.env"
  set +a
fi
COLLECTOR_VENV="$COLLECTOR_ROOT/venv"
REQUIREMENTS_STAMP="$COLLECTOR_VENV/.requirements.sha256"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
DEFAULT_WINDOWS_SOURCE_DB="~/.local/share/bishe/collector.db"
DEFAULT_PROJECT_SOURCE_DB="$COLLECTOR_ROOT/data/collector.db"
COLLECTOR_SOURCE_DB="${DARKWEB_COLLECTOR_SOURCE_DB_PATH:-$DEFAULT_WINDOWS_SOURCE_DB}"
COLLECTOR_RUNTIME_DB="${DARKWEB_COLLECTOR_DB_PATH:-$HOME/.local/share/bishe/collector.db}"
COLLECTOR_RUNTIME_DB_META="${DARKWEB_RUNTIME_DB_META_PATH:-${COLLECTOR_RUNTIME_DB}.meta.json}"

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
  command -v sudo >/dev/null 2>&1 || die "automatic dependency install requires sudo or root privileges"
  sudo "$@"
}

file_sha256() {
  local file_path="$1"
  python3 - "$file_path" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser()
print(sha256(path.read_bytes()).hexdigest() if path.exists() else "")
PY
}

install_remote_browser_system_dependencies() {
  local missing_packages=()
  command -v Xvfb >/dev/null 2>&1 || missing_packages+=("xvfb")
  command -v x11vnc >/dev/null 2>&1 || missing_packages+=("x11vnc")
  command -v openbox >/dev/null 2>&1 || missing_packages+=("openbox")
  (( ${#missing_packages[@]} == 0 )) && return 0
  command -v apt-get >/dev/null 2>&1 || die "missing remote-browser packages (${missing_packages[*]}), and apt-get is unavailable"
  info "installing remote-browser system packages: ${missing_packages[*]}"
  run_as_root apt-get update
  run_as_root apt-get install -y "${missing_packages[@]}"
}

collector_python_dependencies_ready() {
  (
    source "$COLLECTOR_VENV/bin/activate"
    python - <<'PY'
modules = ("jwt", "psutil", "wecom_aibot_sdk")
for module_name in modules:
    __import__(module_name)
PY
  ) >/dev/null 2>&1
}

ensure_collector_python_dependencies() {
  local requirements_hash current_hash
  requirements_hash="$(file_sha256 "$COLLECTOR_ROOT/requirements.txt")"
  current_hash=""
  [[ -f "$REQUIREMENTS_STAMP" ]] && current_hash="$(<"$REQUIREMENTS_STAMP")"
  if [[ -n "$requirements_hash" && "$requirements_hash" == "$current_hash" ]] && collector_python_dependencies_ready; then
    return 0
  fi
  info "installing updated collector Python dependencies"
  (
    cd "$COLLECTOR_ROOT"
    source "$COLLECTOR_VENV/bin/activate"
    python -m pip install -r requirements.txt
  )
  printf '%s' "$requirements_hash" > "$REQUIREMENTS_STAMP"
}

dashboard_build_signature() {
  python3 - "$DASHBOARD_ROOT" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
files = []
for directory_name in ("src", "public"):
    directory = root / directory_name
    if directory.exists():
        files.extend(path for path in directory.rglob("*") if path.is_file())
for filename in ("index.html", "package.json", "package-lock.json", "vite.config.js"):
    path = root / filename
    if path.is_file():
        files.append(path)

digest = sha256()
for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
    relative_path = path.relative_to(root).as_posix().encode("utf-8")
    digest.update(len(relative_path).to_bytes(4, "big"))
    digest.update(relative_path)
    digest.update(path.read_bytes())
print(digest.hexdigest())
PY
}

ensure_dashboard_build() {
  local build_stamp="$DASHBOARD_ROOT/dist/.source.sha256"
  local expected_signature current_signature
  expected_signature="$(dashboard_build_signature)"
  current_signature=""
  [[ -f "$build_stamp" ]] && current_signature="$(<"$build_stamp")"
  if [[ -f "$DASHBOARD_ROOT/dist/index.html" && -n "$expected_signature" && "$expected_signature" == "$current_signature" ]]; then
    info "frontend build is up to date"
    return 0
  fi

  info "building updated frontend assets"
  (
    cd "$DASHBOARD_ROOT"
    npm run build
  )
  printf '%s' "$expected_signature" > "$build_stamp"
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
  if [[ -n "${DARKWEB_COLLECTOR_SOURCE_DB_PATH:-}" ]]; then
    candidates+=("${DARKWEB_COLLECTOR_SOURCE_DB_PATH}")
  else
    candidates+=("$DEFAULT_WINDOWS_SOURCE_DB" "$DEFAULT_PROJECT_SOURCE_DB" "$COLLECTOR_RUNTIME_DB")
  fi

  local best_path=""
  local best_score=-1
  local candidate score
  for candidate in "${candidates[@]}"; do
    score="$(db_score "$candidate")"
    if (( score > best_score )); then
      best_score="$score"
      best_path="$candidate"
    fi
  done

  if [[ -n "$best_path" ]]; then
    COLLECTOR_SOURCE_DB="$best_path"
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
  mkdir -p "$(dirname "$COLLECTOR_SOURCE_DB")"
  cp -f "$COLLECTOR_RUNTIME_DB" "$COLLECTOR_SOURCE_DB"
}

build_env_exports() {
  local exports=()
  exports+=("export REDIS_URL=$(printf '%q' "$REDIS_URL")")
  exports+=("export PYTHONPATH=$(printf '%q' "$COLLECTOR_ROOT/src"):\${PYTHONPATH:-}")
  exports+=("export DARKWEB_COLLECTOR_DB_PATH=$(printf '%q' "$COLLECTOR_RUNTIME_DB")")
  exports+=("export DARKWEB_COLLECTOR_SOURCE_DB_PATH=$(printf '%q' "$COLLECTOR_SOURCE_DB")")
  exports+=("export DARKWEB_RUNTIME_DB_META_PATH=$(printf '%q' "$COLLECTOR_RUNTIME_DB_META")")
  for var_name in TOR_SOCKS_HOST TOR_SOCKS_PORT PROXY_HOST PROXY_PORT HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
    if [[ -n "${!var_name:-}" ]]; then
      exports+=("export ${var_name}=$(printf '%q' "${!var_name}")")
    fi
  done
  printf '%s; ' "${exports[@]}"
}

ensure_environment() {
  require_command tmux
  require_command python3
  require_command npm
  require_command redis-server
  require_command redis-cli
  require_command curl

  [[ -d "$COLLECTOR_VENV" ]] || die "collector venv not found: $COLLECTOR_VENV"
  install_remote_browser_system_dependencies
  ensure_collector_python_dependencies
  [[ -f "$COLLECTOR_ROOT/scripts/serve_api.py" ]] || die "API launcher not found"
  [[ -f "$DASHBOARD_ROOT/package.json" ]] || die "dashboard package.json not found"

  resolve_source_db

  if [[ ! -d "$DASHBOARD_ROOT/node_modules" ]]; then
    info "dashboard dependencies missing, running npm install"
    (
      cd "$DASHBOARD_ROOT"
      npm install
    )
  fi

  if [[ ! -f "$COLLECTOR_RUNTIME_DB" ]] || ! db_has_data "$COLLECTOR_RUNTIME_DB"; then
    info "runtime db missing, preparing stable WSL-local SQLite database"
    (
      cd "$COLLECTOR_ROOT"
      source "$COLLECTOR_VENV/bin/activate"
      python scripts/prepare_runtime_db.py --force --source "$COLLECTOR_SOURCE_DB" --target "$COLLECTOR_RUNTIME_DB"
    )
  fi

  sync_runtime_db_to_source
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
  pkill -f "scripts/crawl.py normalizer" 2>/dev/null || true
}

tmux_new_window() {
  local window_name="$1"
  shift
  local command_body="$*"
  local wrapped_command
  wrapped_command="
set +e
$command_body
status=\$?
if [[ \$status -ne 0 ]]; then
  echo
  echo \"[ERROR] process exited with code \$status\"
fi
exec bash
"
  tmux new-window -t "${SESSION_NAME}:" -n "$window_name" "bash -lc $(printf '%q' "$wrapped_command")"
}

wait_for_http() {
  local url="$1"
  local timeout_seconds="$2"
  local started_at
  started_at="$(date +%s)"
  # --noproxy '*' bypasses HTTP_PROXY/HTTPS_PROXY env vars unconditionally;
  # localhost health checks must never be routed through Clash/Tor.
  while true; do
    if curl --noproxy '*' -fsS "$url" >/dev/null 2>&1; then
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

start_services() {
  ensure_environment
  stop_session_if_exists
  cleanup_stray_processes

  local env_exports
  env_exports="$(build_env_exports)"

  local redis_command
  redis_command="
set -euo pipefail
if redis-cli ping >/dev/null 2>&1; then
  echo 'redis already running'
else
  if sudo -n service redis-server start >/dev/null 2>&1; then
    echo 'redis started via service'
  elif redis-server --daemonize yes >/dev/null 2>&1; then
    echo 'redis started in user mode'
  else
    echo 'failed to start redis'
    exit 1
  fi
fi
redis-cli ping
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
  if [[ "$FRONTEND_MODE" == "dev" ]]; then
    frontend_command="
set -euo pipefail
cd \"$DASHBOARD_ROOT\"
npm run dev:wsl
"
  elif [[ "$FRONTEND_MODE" == "preview" ]]; then
    ensure_dashboard_build
    frontend_command="
set -euo pipefail
cd \"$DASHBOARD_ROOT\"
npm run preview -- --host 0.0.0.0 --port 5173 --strictPort
"
  else
    die "unsupported FRONTEND_MODE: $FRONTEND_MODE (expected preview or dev)"
  fi

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

  local normalizer_command
  normalizer_command="
set -euo pipefail
cd \"$COLLECTOR_ROOT\"
${env_exports}
source \"$COLLECTOR_VENV/bin/activate\"
python scripts/crawl.py normalizer \
  --poll-seconds $NORMALIZER_POLL_SECONDS \
  --debounce-seconds $NORMALIZER_DEBOUNCE_SECONDS \
  --max-delay-seconds $NORMALIZER_MAX_DELAY_SECONDS
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

  tmux new-session -d -s "$SESSION_NAME" -n "redis" "bash -lc $(printf '%q' "$redis_command")"
  tmux setw -t "$SESSION_NAME" remain-on-exit on

  tmux_new_window "api" "$api_command"

  sleep 2

  if ! wait_for_http "$API_HEALTH_URL" "$SERVICE_WAIT_SECONDS"; then
    warn "api health check did not become ready within ${SERVICE_WAIT_SECONDS}s"
    describe_port_owner 8000
    capture_window_logs "api" 120
  fi

  tmux_new_window "frontend" "$frontend_command"
  tmux_new_window "worker-seed" "$seed_worker_command"
  tmux_new_window "worker-detail" "$detail_worker_command"
  tmux_new_window "worker-browser" "$browser_worker_command"
  tmux_new_window "normalizer" "$normalizer_command"
  tmux_new_window "scheduler" "$scheduler_command"
  tmux_new_window "vuln-sync" "$vulnerability_sync_command"

  if ! wait_for_http "$FRONTEND_URL" "$SERVICE_WAIT_SECONDS"; then
    warn "frontend did not become ready within ${SERVICE_WAIT_SECONDS}s"
    describe_port_owner 5173
    capture_window_logs "frontend" 120
  fi

  info "tmux session created: $SESSION_NAME"
  info "frontend: http://localhost:5173 (mode=${FRONTEND_MODE})"
  info "api health: http://127.0.0.1:8000/api/health"
  info "normalizer: poll=${NORMALIZER_POLL_SECONDS}s debounce=${NORMALIZER_DEBOUNCE_SECONDS}s max-delay=${NORMALIZER_MAX_DELAY_SECONDS}s"
  info "vulnerability sync interval: ${VULN_SYNC_INTERVAL_SECONDS}s (limit=${VULN_SYNC_LIMIT})"
  info "attach with: tmux attach -t $SESSION_NAME"
  echo
  show_status
}

stop_services() {
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux kill-session -t "$SESSION_NAME"
  fi
  cleanup_stray_processes
  resolve_source_db
  sync_runtime_db_to_source
  info "tmux session stopped: $SESSION_NAME"
}

attach_session() {
  tmux has-session -t "$SESSION_NAME" 2>/dev/null || die "tmux session not running: $SESSION_NAME"
  exec tmux attach -t "$SESSION_NAME"
}

show_status() {
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    info "tmux session: $SESSION_NAME"
    tmux list-windows -t "$SESSION_NAME"
  else
    info "tmux session not running: $SESSION_NAME"
  fi

  if redis-cli ping >/dev/null 2>&1; then
    info "redis: up"
  else
    info "redis: down"
  fi

  if curl --noproxy '*' -fsS "$API_HEALTH_URL" >/dev/null 2>&1; then
    info "api: up ($API_HEALTH_URL)"
  else
    info "api: down"
    describe_port_owner 8000
    capture_window_logs "api" 80
  fi

  if curl --noproxy '*' -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
    info "frontend: up (http://localhost:5173)"
  else
    info "frontend: down"
    describe_port_owner 5173
    capture_window_logs "frontend" 80
  fi
}

main() {
  local action="${1:-start}"
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
    *)
      die "unsupported action: $action (use start|stop|attach|status)"
      ;;
  esac
}

main "${1:-start}"
