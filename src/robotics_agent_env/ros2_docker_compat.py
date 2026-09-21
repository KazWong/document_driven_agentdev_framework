from __future__ import annotations

import os
import sys
from pathlib import Path

from .util import AgentEnvError


ROS2_TEST_PROJECT = "ros2-test-project"
ROS2_SETUP_COMMAND = 'source /opt/ros/humble/setup.bash && exec ros2-test-project "$@"'


def rewrite_docker_args(args: list[str]) -> list[str]:
    """Inject ROS setup only into the persistent-container project-test exec.

    Every other Docker/Compose command is forwarded byte-for-byte as argv.
    """
    if not args or args[0] != "compose" or "exec" not in args:
        return list(args)
    try:
        exec_index = args.index("exec")
        command_index = args.index(ROS2_TEST_PROJECT, exec_index + 1)
    except ValueError:
        return list(args)
    return [
        *args[:command_index],
        "/bin/bash",
        "-c",
        ROS2_SETUP_COMMAND,
        "--",
        *args[command_index + 1 :],
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    raw_real = os.environ.get("ROBOTICS_REAL_DOCKER", "").strip()
    if not raw_real:
        raise AgentEnvError("ROBOTICS_REAL_DOCKER is not set for the ROS2 Docker compatibility shim")
    real = Path(raw_real).expanduser().resolve()
    if not real.is_file() or not os.access(real, os.X_OK):
        raise AgentEnvError(f"real Docker executable is not executable: {real}")
    os.execv(str(real), [str(real), *rewrite_docker_args(args)])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
