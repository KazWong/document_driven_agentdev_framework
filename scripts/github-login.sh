#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/compose.yaml")
AUTH_COMPOSE=(docker compose -f "$ROOT/compose.yaml" --profile auth)

usage() {
  echo "Usage: scripts/github-login.sh <login|status|logout>" >&2
  exit 2
}

inside_main_container() {
  [[ -f /.dockerenv ]] && command -v gh >/dev/null 2>&1
}

main_container_running() {
  [[ -n "$(docker compose -f "$ROOT/compose.yaml" ps --status running -q main-development 2>/dev/null || true)" ]]
}

run_gh_interactive() {
  if inside_main_container; then
    gh "$@"
  elif main_container_running; then
    "${COMPOSE[@]}" exec main-development gh "$@"
  else
    "${AUTH_COMPOSE[@]}" run --rm --no-deps codex-login gh "$@"
  fi
}

run_gh_noninteractive() {
  if inside_main_container; then
    gh "$@"
  elif main_container_running; then
    "${COMPOSE[@]}" exec -T main-development gh "$@"
  else
    "${AUTH_COMPOSE[@]}" run --rm --no-deps -T codex-login gh "$@"
  fi
}

case "${1:-}" in
  login)
    run_gh_interactive auth login --hostname github.com --git-protocol https --web
    run_gh_noninteractive auth setup-git --hostname github.com
    ;;
  status)
    run_gh_noninteractive auth status --hostname github.com
    ;;
  logout)
    run_gh_interactive auth logout --hostname github.com
    ;;
  *) usage ;;
esac
