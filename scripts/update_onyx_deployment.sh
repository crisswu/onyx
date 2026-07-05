#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOYMENT_DIR="${ONYX_DEPLOYMENT_DIR:-$REPO_ROOT/onyx_data/deployment}"
COMPOSE_FILE="${ONYX_COMPOSE_FILE:-$DEPLOYMENT_DIR/docker-compose.yml}"
LITE_COMPOSE_FILE="${ONYX_LITE_COMPOSE_FILE:-$DEPLOYMENT_DIR/docker-compose.onyx-lite.yml}"
PUBLIC_URL="${ONYX_PUBLIC_URL:-http://100.65.125.67:3000/}"

MODE="web"
DO_GIT_PULL="false"
RESTART_ONLY="false"
NO_CACHE="false"
SKIP_URL_CHECK="false"

usage() {
  cat <<'EOF'
Usage: scripts/update_onyx_deployment.sh [options]

Build and restart the local Docker Compose Onyx deployment.

Default behavior:
  Rebuild and restart only web_server. Use this for frontend changes.

Options:
  --web             Rebuild/restart web_server only. Default.
  --backend         Rebuild/restart backend image users in the lite deployment.
  --all             Rebuild/restart the full active compose stack.
  --restart-only    Restart selected services without building images.
  --pull            Run "git pull --ff-only" before building.
  --no-cache        Build selected images without Docker build cache.
  --skip-url-check  Skip the final HTTP check.
  -h, --help        Show this help.

Environment overrides:
  ONYX_DEPLOYMENT_DIR       Default: <repo>/onyx_data/deployment
  ONYX_COMPOSE_FILE         Default: <deployment>/docker-compose.yml
  ONYX_LITE_COMPOSE_FILE    Default: <deployment>/docker-compose.onyx-lite.yml
  ONYX_PUBLIC_URL           Default: http://100.65.125.67:3000/
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --web)
      MODE="web"
      ;;
    --backend)
      MODE="backend"
      ;;
    --all)
      MODE="all"
      ;;
    --restart-only)
      RESTART_ONLY="true"
      ;;
    --pull)
      DO_GIT_PULL="true"
      ;;
    --no-cache)
      NO_CACHE="true"
      ;;
    --skip-url-check)
      SKIP_URL_CHECK="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Required file not found: $path" >&2
    exit 1
  fi
}

compose() {
  docker compose -f "$COMPOSE_FILE" -f "$LITE_COMPOSE_FILE" "$@"
}

print_step() {
  echo
  echo "==> $*"
}

require_file "$COMPOSE_FILE"
require_file "$LITE_COMPOSE_FILE"

if [[ "$DO_GIT_PULL" == "true" ]]; then
  print_step "Pulling latest code"
  git -C "$REPO_ROOT" pull --ff-only
fi

build_args=()
if [[ "$NO_CACHE" == "true" ]]; then
  build_args+=(--no-cache)
fi

case "$MODE" in
  web)
    build_services=(web_server)
    up_services=(web_server)
    ;;
  backend)
    build_services=(api_server)
    up_services=(api_server onyx_feishu_bot eva_reminder_worker)
    ;;
  all)
    build_services=()
    up_services=()
    ;;
  *)
    echo "Invalid mode: $MODE" >&2
    exit 2
    ;;
esac

print_step "Using deployment directory: $DEPLOYMENT_DIR"
cd "$DEPLOYMENT_DIR"

if [[ "$RESTART_ONLY" != "true" ]]; then
  if [[ "$MODE" == "all" ]]; then
    print_step "Building active compose services"
    compose build "${build_args[@]}"
  else
    print_step "Building: ${build_services[*]}"
    compose build "${build_args[@]}" "${build_services[@]}"
  fi
fi

if [[ "$MODE" == "all" ]]; then
  print_step "Starting active compose stack"
  compose up -d --wait
else
  print_step "Restarting: ${up_services[*]}"
  compose up -d --no-deps --wait "${up_services[@]}"
fi

print_step "Refreshing nginx upstream DNS"
compose restart nginx

print_step "Current service status"
compose ps

if [[ "$SKIP_URL_CHECK" != "true" ]]; then
  print_step "Checking $PUBLIC_URL"
  curl -fsS --max-time 15 "$PUBLIC_URL" >/dev/null
fi

print_step "Update complete"
