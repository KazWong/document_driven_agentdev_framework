from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from robotics_agent_env.project_cli import main


@pytest.mark.parametrize("kind", ["c", "cpp", "python", "shell"])
def test_generates_project(workspace: Path, kind: str) -> None:
    name = f"sample-{kind}"
    assert main(["create", "--type", kind, "--name", name]) == 0
    project = workspace / "projects" / name
    assert (project / "AGENTS.md").is_file()
    assert (project / ".agent" / "workflow.yaml").is_file()
    assert (project / ".codex" / "agents" / "reviewer.toml").is_file()
    assert (project / "scripts" / "ci" / "verify.sh").is_file()
    completed = subprocess.run(["git", "-C", str(project), "rev-parse", "--verify", "HEAD"], check=False)
    assert completed.returncode == 0


def test_generates_project_with_underscore(workspace: Path) -> None:
    name = "sample_python"
    assert main(["create", "--type", "python", "--name", name]) == 0
    project = workspace / "projects" / name
    assert (project / "src" / name / "core.py").is_file()
