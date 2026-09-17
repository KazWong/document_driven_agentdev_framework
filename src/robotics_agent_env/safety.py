from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from .constants import ALLOWED_LOCAL_EXECUTABLES, BLOCKED_ARGUMENTS, BLOCKED_EXECUTABLES
from .util import AgentEnvError, ensure_within

SENSITIVE_PREFIXES = ("/dev/", "/proc/", "/sys/", "/boot/", "/etc/")


def validate_local_command(argv: Sequence[str], repo: Path) -> list[str]:
    if not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
        raise AgentEnvError("local verification command must be a non-empty argv list")
    command = list(argv)
    executable_raw = command[0]
    executable = os.path.basename(executable_raw)
    if executable in BLOCKED_EXECUTABLES:
        raise AgentEnvError(f"'{executable}' is not permitted in automatic local verification")
    if any(argument in BLOCKED_ARGUMENTS for argument in command[1:]):
        raise AgentEnvError("privileged host/container arguments are forbidden")
    for argument in command[1:]:
        if argument.startswith(SENSITIVE_PREFIXES):
            raise AgentEnvError(f"automatic local verification cannot access sensitive path: {argument}")

    if executable_raw.startswith(("./", "../", "/")):
        script = Path(executable_raw)
        if not script.is_absolute():
            script = repo / script
        script = ensure_within(script, repo, "verification executable")
        if not script.is_file():
            raise AgentEnvError(f"verification executable does not exist: {script}")
        command[0] = str(script)
        return command

    if executable not in ALLOWED_LOCAL_EXECUTABLES:
        raise AgentEnvError(
            f"local verification executable '{executable}' is not allowlisted; allowed: "
            + ", ".join(sorted(ALLOWED_LOCAL_EXECUTABLES))
        )

    if executable in {"bash", "sh"}:
        if len(command) < 2 or command[1].startswith("-"):
            raise AgentEnvError(f"{executable} must execute a repository script, not inline code")
        command[1] = str(_resolve_repo_script(command[1], repo))
    if executable in {"python", "python3"}:
        if len(command) < 2:
            raise AgentEnvError(f"{executable} must execute a repository script or '-m pytest'")
        if command[1] in {"-c", "-"}:
            raise AgentEnvError("inline Python is forbidden in automatic verification")
        if command[1] == "-m":
            if len(command) < 3 or command[2] not in {"pytest", "unittest"}:
                raise AgentEnvError("only 'python -m pytest' and 'python -m unittest' are allowed")
        elif not command[1].startswith("-"):
            command[1] = str(_resolve_repo_script(command[1], repo))
    return command


def _resolve_repo_script(value: str, repo: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repo / candidate
    candidate = ensure_within(candidate, repo, "verification script")
    if not candidate.is_file():
        raise AgentEnvError(f"verification script does not exist: {candidate}")
    return candidate
