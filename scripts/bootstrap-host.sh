#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE=/home/kazwong/codes/agents
VERSION="$(cat "$ROOT/VERSION")"
case "$ROOT" in
  "$WORKSPACE"/*) ;;
  *) printf 'bootstrap-host: install this repository under %s before bootstrapping\n' "$WORKSPACE" >&2; exit 2 ;;
esac
mkdir -p "$WORKSPACE" "$WORKSPACE/projects" "$WORKSPACE/infrastructure" \
  "$WORKSPACE/.agent-state/index" "$WORKSPACE/.agent-state/worktrees" \
  "$WORKSPACE/.agent-state/verifiers/integration" "$WORKSPACE/.agent-state/github-cli" \
  "$WORKSPACE/.agent-state/cache/ccache" "$WORKSPACE/.agent-state/cache/ccache-generic" \
  "$WORKSPACE/.agent-state/cache/pip" "$WORKSPACE/.agent-state/cache/platformio" \
  "$WORKSPACE/.agent-state/cache/uv" "$WORKSPACE/.test-results"
ENV_FILE="$ROOT/.env"
uid="$(id -u)"
gid="$(id -g)"
if [[ -S /var/run/docker.sock ]]; then
  docker_gid="$(stat -c '%g' /var/run/docker.sock)"
else
  docker_gid="$gid"
fi
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF_ENV
HOST_UID=$uid
HOST_GID=$gid
DOCKER_GID=$docker_gid
DEV_USERNAME=kazwong
CODEX_VERSION=latest
MAIN_IMAGE=robotics-ai-agent-main:$VERSION
GENERIC_IMAGE=robotics-ai-agent-generic-test:$VERSION
FIRMWARE_IMAGE=robotics-ai-agent-firmware-test:$VERSION
EOF_ENV
else
  python3 "$ROOT/scripts/update_env.py" "$ENV_FILE" "$uid" "$gid" "$docker_gid" "$VERSION"
fi
chmod 600 "$ENV_FILE"
AGENT_WORKSPACE_ROOT="$WORKSPACE" CODEX_HOME="$WORKSPACE/.agent-state/codex-home" "$ROOT/scripts/sync-codex-config.sh"
printf '\nBootstrap complete.\n'
printf 'Main source: %s\n' "$ROOT"
printf 'Workspace:   %s\n' "$WORKSPACE"
if [[ -x "$WORKSPACE/infrastructure/ros2-humble-gazebo-test/ros2-test" ]]; then
  printf 'ROS lane:    ready\n'
else
  printf 'ROS lane:    not installed; extract ros2-humble-gazebo-test under %s/infrastructure\n' "$WORKSPACE"
fi
