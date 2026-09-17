from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from robotics_agent_env.manifest import validate_manifest_data
from robotics_agent_env.util import AgentEnvError
from conftest import init_repo


def base_manifest(repo: Path) -> dict:
    return {
        "schema_version": 1,
        "id": "RBT-1",
        "title": "test change",
        "repository": str(repo),
        "risk_class": "R1",
        "project_kind": "generic",
        "goal": "make a verified change",
        "scope": {"include": ["src/**"], "exclude": []},
        "acceptance_criteria": ["the test passes"],
        "verification": {"local": [{"id": "verify", "command": ["pytest"], "timeout_seconds": 60}], "integration": []},
        "isolation": {"strategy": "worktree"},
        "promotion": {"physical_hardware": "prohibited"},
    }


def test_normalizes_ros_alias_and_requires_humble(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "robot")
    manifest = base_manifest(repo)
    manifest.update({"risk_class": "R2", "project_kind": "ros2"})
    manifest["verification"]["integration"] = [{"lane": "ros2-gazebo", "action": "test", "args": []}]
    normalized = validate_manifest_data(manifest)
    assert normalized["verification"]["integration"][0]["lane"] == "ros2-humble"


def test_rejects_jazzy_lane(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "robot")
    manifest = base_manifest(repo)
    manifest.update({"risk_class": "R2", "project_kind": "ros2"})
    manifest["verification"]["integration"] = [{"lane": "ros2-jazzy", "action": "test", "args": []}]
    with pytest.raises(AgentEnvError, match="retired"):
        validate_manifest_data(manifest)


def test_r3_requires_human_approved_hardware(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "firmware")
    manifest = base_manifest(repo)
    manifest.update({"risk_class": "R3", "project_kind": "firmware"})
    manifest["verification"]["integration"] = [{"lane": "firmware", "action": "test", "args": []}]
    with pytest.raises(AgentEnvError, match="human-approved"):
        validate_manifest_data(manifest)
