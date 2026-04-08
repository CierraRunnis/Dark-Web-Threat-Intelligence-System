#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="bishe-stack"
SCHEDULER_INTERVAL_SECONDS=60
API_HEALTH_URL="http://127.0.0.1:8000/api/health"
FRONTEND_URL="http://127.0.0.1:5173"
SERVICE_WAIT_SECONDS=45
VULN_SYNC_INTERVAL_SECONDS="${VULN_SYNC_INTERVAL_SECONDS:-3600}"
VULN_SYNC_LIMIT="${VULN_SYNC_LIMIT:-20}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DASHBOARD_ROOT="$(cd "$COLLECTOR_ROOT/../threat-intelligence-dashboard" && pwd)"
COLLECTOR_VENV="$COLLECTOR_ROOT/venv"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"

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

build_env_exports() {
  local exports=()
  exports+=("export REDIS_URL=$(printf '%q' "$REDIS_URL")")
  exports+=("export PYTHONPATH=$(printf '%q' "$COLLECTOR_ROOT/src"):\${PYTHONPATH:-}")
  for var_name in TOR_SOCKS_HOST TOR_SOCKS_PORT PROXY_HOST PROXY_PORT; do
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
  [[ -f "$COLLECTOR_ROOT/scripts/serve_api.py" ]] || die "API launcher not found"
  [[ -f "$DASHBOARD_ROOT/package.json" ]] || die "dashboard package.json not found"

  if [[ ! -d "$DASHBOARD_ROOT/node_modules" ]]; then
    info "dashboard dependencies missing, running npm install"
    (
      cd "$DASHBOARD_ROOT"
      npm install
    )
  fi
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
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
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
  frontend_command="
set -euo pipefail
cd \"$DASHBOARD_ROOT\"
npm run dev:wsl
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
  tmux_new_window "scheduler" "$scheduler_command"
  tmux_new_window "vuln-sync" "$vulnerability_sync_command"

  if ! wait_for_http "$FRONTEND_URL" "$SERVICE_WAIT_SECONDS"; then
    warn "frontend did not become ready within ${SERVICE_WAIT_SECONDS}s"
    describe_port_owner 5173
    capture_window_logs "frontend" 120
  fi

  info "tmux session created: $SESSION_NAME"
  info "frontend: http://localhost:5173"
  info "api health: http://127.0.0.1:8000/api/health"
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

  if curl -fsS "$API_HEALTH_URL" >/dev/null 2>&1; then
    info "api: up ($API_HEALTH_URL)"
  else
    info "api: down"
    describe_port_owner 8000
    capture_window_logs "api" 80
  fi

  if curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
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
