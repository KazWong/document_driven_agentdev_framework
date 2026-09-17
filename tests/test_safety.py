from pathlib import Path

import pytest

from robotics_agent_env.safety import validate_local_command
from robotics_agent_env.util import AgentEnvError


def test_blocks_docker_and_inline_python(tmp_path: Path) -> None:
    with pytest.raises(AgentEnvError):
        validate_local_command(["docker", "run", "x"], tmp_path)
    with pytest.raises(AgentEnvError):
        validate_local_command(["python3", "-c", "print(1)"], tmp_path)


def test_allows_repository_script(tmp_path: Path) -> None:
    script = tmp_path / "verify.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    command = validate_local_command(["bash", "verify.sh"], tmp_path)
    assert command[1] == str(script.resolve())
