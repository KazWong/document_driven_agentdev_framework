#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/compose.yaml" --profile auth)

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
    exec "${COMPOSE[@]}" run --rm --no-deps -T codex-login codex login status
    ;;
  logout)
    exec "${COMPOSE[@]}" run --rm --no-deps -T codex-login codex logout
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
