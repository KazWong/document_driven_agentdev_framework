#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE=/home/kazwong/codes/agents
case "$ROOT" in
  "$WORKSPACE"/*) ;;
  *) printf 'bootstrap-host: install this repository under %s before bootstrapping\n' "$WORKSPACE" >&2; exit 2 ;;
esac
mkdir -p "$WORKSPACE" "$WORKSPACE/projects" "$WORKSPACE/infrastructure" \
  "$WORKSPACE/.agent-state/work-items" "$WORKSPACE/.agent-state/worktrees" \
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
  cat > "$ENV_FILE" <<EOF
HOST_UID=$uid
HOST_GID=$gid
DOCKER_GID=$docker_gid
DEV_USERNAME=kazwong
CODEX_VERSION=latest
MAIN_IMAGE=robotics-ai-agent-main:2.0.1
GENERIC_IMAGE=robotics-ai-agent-generic-test:2.0.1
FIRMWARE_IMAGE=robotics-ai-agent-firmware-test:2.0.1
EOF
else
  python3 - "$ENV_FILE" "$uid" "$gid" "$docker_gid" <<'PYENV'
from pathlib import Path
import sys
path = Path(sys.argv[1])
updates = {"HOST_UID": sys.argv[2], "HOST_GID": sys.argv[3], "DOCKER_GID": sys.argv[4]}
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
out = []
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0]
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
    out.append(line)
for key in ("HOST_UID", "HOST_GID", "DOCKER_GID"):
    if key not in seen:
        out.append(f"{key}={updates[key]}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PYENV
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
