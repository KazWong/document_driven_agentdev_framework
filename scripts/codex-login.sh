#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/compose.yaml" --profile auth)

inside_main_container() {
  [[ -f /.dockerenv ]] && command -v codex >/dev/null 2>&1 && [[ -n "${CODEX_HOME:-}" ]]
}

main_container_running() {
  [[ -n "$(docker compose -f "$ROOT/compose.yaml" ps --status running -q main-development 2>/dev/null || true)" ]]
}

run_status_cleanly() {
  local stderr_file rc
  stderr_file="$(mktemp)"
  if "$@" 2>"$stderr_file"; then
    rc=0
  else
    rc=$?
  fi
  grep -v '^WARNING: failed to clean up stale arg0 temp dirs:' "$stderr_file" >&2 || true
  rm -f "$stderr_file"
  return "$rc"
}

usage() {
  cat <<'USAGE'
Usage: scripts/codex-login.sh <chatgpt|device|api-key|status|logout>

Login modes:
  chatgpt  Sign in with ChatGPT using the browser OAuth callback on localhost:1455.
           The helper container uses host networking and the persistent CODEX_HOME.
           Local Docker: open the URL on this host's browser.
           Remote Docker: before running this command, create this tunnel from the laptop:
             ssh -L 1455:127.0.0.1:1455 <user>@<remote-host>
  device   Sign in with ChatGPT using the device-code flow. No callback tunnel required.
  api-key  Sign in using OPENAI_API_KEY from the host environment. The key is sent to
           `codex login --with-api-key` on stdin and is not placed in process arguments.
  status   Show Codex login status using the persistent CODEX_HOME.
  logout   Clear the current Codex login from the persistent CODEX_HOME.
USAGE
}

mode="${1:-}"
case "$mode" in
  chatgpt)
    cat <<'EOF2'
Starting browser-based ChatGPT login.

Local host -> Docker:
  Open the URL printed by Codex in a browser on this host.

Laptop -> remote host -> Docker:
  FIRST run this on the laptop and keep it open:
    ssh -L 1455:127.0.0.1:1455 <user>@<remote-host>
  Then open the URL printed below in the laptop browser.

The temporary auth container uses host networking only for this login command.
The normal main-development container networking is unchanged.
EOF2
    exec "${COMPOSE[@]}" run --rm --no-deps codex-login codex login
    ;;
  device)
    exec "${COMPOSE[@]}" run --rm --no-deps codex-login codex login --device-auth
    ;;
  api-key)
    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
      echo "codex-login: OPENAI_API_KEY is not set" >&2
      exit 2
    fi
    printf '%s\n' "$OPENAI_API_KEY" | "${COMPOSE[@]}" run --rm --no-deps -T codex-login codex login --with-api-key
    ;;
  status)
    if inside_main_container; then
      run_status_cleanly codex login status
    elif main_container_running; then
      run_status_cleanly docker compose -f "$ROOT/compose.yaml" exec -T main-development codex login status
    else
      run_status_cleanly "${COMPOSE[@]}" run --rm --no-deps -T codex-login codex login status
    fi
    ;;
  logout)
    if inside_main_container; then
      exec codex logout
    elif main_container_running; then
      exec docker compose -f "$ROOT/compose.yaml" exec -T main-development codex logout
    else
      exec "${COMPOSE[@]}" run --rm --no-deps -T codex-login codex logout
    fi
    ;;
  -h|--help|help|'')
    usage
    [[ -n "$mode" ]] || exit 2
    ;;
  *)
    echo "codex-login: unknown mode: $mode" >&2
    usage >&2
    exit 2
    ;;
esac
