#!/usr/bin/env bash
set -euo pipefail

# Codex normally asks bubblewrap to mount a fresh /proc inside its PID
# namespace. Some outer container runtimes allow the required namespaces but
# deny that one mount operation. Current Codex supports the equivalent
# --no-proc mode for exactly those environments. Keep the real system bwrap
# and remove only the fresh /proc mount request; preserve every other sandbox
# argument unchanged.
real_bwrap="${ROBOTICS_AGENT_REAL_BWRAP:-/usr/bin/bwrap}"

if [[ ! -x "$real_bwrap" ]]; then
  printf 'codex-bwrap-compat: real bubblewrap is not executable: %s\n' "$real_bwrap" >&2
  exit 127
fi

args=()
while (($#)); do
  case "$1" in
    --proc)
      if (($# >= 2)) && [[ "$2" == "/proc" ]]; then
        shift 2
        continue
      fi
      args+=("$1")
      shift
      if (($#)); then
        args+=("$1")
        shift
      fi
      ;;
    --proc=/proc)
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

exec "$real_bwrap" "${args[@]}"
