#!/usr/bin/env bash
set -euo pipefail
umask 027
WORKSPACE="${AGENT_WORKSPACE_ROOT:-/home/kazwong/codes/agents}"
STATE="${AGENT_STATE_ROOT:-$WORKSPACE/.agent-state}"
CODEX_DIR="${CODEX_HOME:-$STATE/codex-home}"
mkdir -p "$WORKSPACE" "$STATE" "$STATE/work-items" "$STATE/worktrees" \
  "$STATE/cache/ccache" "$STATE/cache/ccache-generic" "$STATE/cache/pip" \
  "$STATE/cache/platformio" "$STATE/cache/uv" "$CODEX_DIR"
if [[ ! -f "$CODEX_DIR/config.toml" ]]; then
  cp /opt/robotics-agent-env/.codex/config.toml "$CODEX_DIR/config.toml"
fi
mkdir -p "$CODEX_DIR/agents" "$CODEX_DIR/rules"
for source in /opt/robotics-agent-env/.codex/agents/*.toml; do
  target="$CODEX_DIR/agents/$(basename "$source")"
  [[ -e "$target" ]] || cp "$source" "$target"
done
for source in /opt/robotics-agent-env/.codex/rules/*.rules; do
  target="$CODEX_DIR/rules/$(basename "$source")"
  [[ -e "$target" ]] || cp "$source" "$target"
done
git config --global --add safe.directory "$WORKSPACE" >/dev/null 2>&1 || true
exec "$@"
