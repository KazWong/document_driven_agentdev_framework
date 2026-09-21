from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import init_repo
from robotics_agent_env.agentctl_cli import main as agentctl_main
from robotics_agent_env.util import AgentEnvError
from robotics_agent_env.workitem import WorkItem


def manifest_for(repo: Path, work_id: str = "GATE-1") -> dict:
    return {
        "schema_version": 1,
        "id": work_id,
        "title": "gate integrity",
        "repository": str(repo),
        "base_branch": "main",
        "risk_class": "R1",
        "project_kind": "generic",
        "goal": "verify gate integrity",
        "scope": {"include": ["src/**"], "exclude": []},
        "acceptance_criteria": ["gates remain current"],
        "verification": {
            "local": [{"id": "tests", "command": ["pytest"], "timeout_seconds": 60}],
            "integration": [],
        },
        "isolation": {"strategy": "worktree"},
        "promotion": {"physical_hardware": "prohibited"},
    }


def create_item(workspace: Path, repo: Path, work_id: str = "GATE-1") -> WorkItem:
    path = workspace / f"{work_id}.yaml"
    path.write_text(yaml.safe_dump(manifest_for(repo, work_id)), encoding="utf-8")
    return WorkItem.create(path)


def test_scope_check_includes_committed_changes(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    worktree = item.create_worktree()
    (worktree / "outside.txt").write_text("not approved\n", encoding="utf-8")
    subprocess.run(["git", "add", "outside.txt"], cwd=worktree, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "out of scope"],
        cwd=worktree,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert item.scope_violations() == ["outside.txt"]


def test_plan_approval_becomes_stale_when_plan_changes(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    item.write_plan("# Plan\n\nFirst version")
    item.transition("INTAKE", "PLANNING", event="test")
    item.transition("PLANNING", "PLANNED", event="test")
    item.add_approval("plan", actor="owner")
    assert item.approval_count("plan") == 1
    item.write_plan("# Plan\n\nChanged version")
    assert item.approval_count("plan") == 0


def test_ci_commit_must_match_current_head(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    item.write_artifact("pull-request.md", "# Pull request")
    item.transition("INTAKE", "PR_READY", event="test")
    with pytest.raises(AgentEnvError, match="does not match"):
        item.record_ci("passed", "https://ci.example.invalid/1", commit="0" * 40)


@pytest.mark.parametrize(
    ("kind", "risk", "expected_lanes", "hardware"),
    [
        ("generic", "R1", [], "prohibited"),
        ("generic", "R2", ["generic"], "prohibited"),
        ("ros2", "R1", ["ros2-humble"], "prohibited"),
        ("firmware", "R3", ["firmware-emulation"], "human-approved"),
        ("mixed", "R2", ["ros2-humble", "firmware-emulation"], "prohibited"),
    ],
)
def test_init_manifest_is_kind_aware(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    risk: str,
    expected_lanes: list[str],
    hardware: str,
) -> None:
    output = workspace / f"{kind}-{risk}.yaml"
    result = agentctl_main(
        [
            "init-manifest",
            "--output",
            str(output),
            "--id",
            f"TMP-{kind}-{risk}",
            "--title",
            "Template test",
            "--repository",
            "projects/example",
            "--kind",
            kind,
            "--risk",
            risk,
        ]
    )
    assert result == 0
    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert [entry["lane"] for entry in data["verification"]["integration"]] == expected_lanes
    assert data["promotion"]["physical_hardware"] == hardware
