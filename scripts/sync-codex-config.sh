#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${AGENT_WORKSPACE_ROOT:-/home/kazwong/codes/agents}"
CODEX_DIR="${CODEX_HOME:-$WORKSPACE/.agent-state/codex-home}"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1
mkdir -p "$CODEX_DIR/agents" "$CODEX_DIR/rules"
copy_one() {
  local source="$1" target="$2"
  if [[ -e "$target" && "$FORCE" -eq 0 ]]; then
    return
  fi
  if [[ -e "$target" ]]; then
    cp -a "$target" "$target.backup.$(date -u +%Y%m%dT%H%M%SZ)"
  fi
  cp "$source" "$target"
}
copy_one "$ROOT/.codex/config.toml" "$CODEX_DIR/config.toml"
for source in "$ROOT"/.codex/agents/*.toml; do copy_one "$source" "$CODEX_DIR/agents/$(basename "$source")"; done
for source in "$ROOT"/.codex/rules/*.rules; do copy_one "$source" "$CODEX_DIR/rules/$(basename "$source")"; done
printf 'Codex configuration synchronized to %s\n' "$CODEX_DIR"
