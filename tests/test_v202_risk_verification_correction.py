from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from robotics_agent_env.agentctl_cli import _manifest_template
from robotics_agent_env.risk import default_risk_for_kind, reclassify_work_item
from robotics_agent_env.ros2_docker_compat import ROS2_SETUP_COMMAND, rewrite_docker_args
from robotics_agent_env.test_registry import Lane, TestController
from robotics_agent_env.util import AgentEnvError

ROOT = Path(__file__).resolve().parents[1]


class FakeRiskItem:
    def __init__(self, root: Path, manifest: dict, state: str = "DIAGNOSED") -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.work_id = manifest["id"]
        self.manifest_path = root / "work-item.yaml"
        self.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        self._status = {
            "state": state,
            "risk_class": manifest["risk_class"],
            "gate_epochs": {"plan": 0, "merge": 0, "hardware": 0},
            "current_plan": {"id": "plan-0001"},
            "implementation": {"candidate_sha": "deadbeef"},
            "pull_request": None,
            "ci": {"status": "failed"},
            "promotion": {"level": "simulation"},
            "last_error": "test failure",
        }
        self.traces: list[dict] = []
        self.refreshed = 0

    @property
    def manifest(self) -> dict:
        return yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))

    @property
    def status(self) -> dict:
        return dict(self._status)

    def invalidate_gates(self, gates: set[str], *, event: str) -> None:
        epochs = dict(self._status["gate_epochs"])
        for gate in gates:
            epochs[gate] += 1
        self._status["gate_epochs"] = epochs
        self.traces.append({"event": event})

    def update_status(self, updates: dict, *, event: str) -> dict:
        self._status.update(updates)
        self.traces.append({"event": event})
        return self.status

    def _append_trace(self, event, from_state, to_state, metadata=None, actor=None):
        self.traces.append({
            "event": event,
            "from_state": from_state,
            "to_state": to_state,
            "metadata": metadata or {},
            "actor": actor,
        })

    def transition(self, expected, target, *, event, metadata=None, error=None):
        assert self._status["state"] == expected
        self._status["state"] = target
        self._status["last_error"] = error
        self.traces.append({"event": event, "metadata": metadata or {}})
        return self.status

    def refresh_evidence_index(self):
        self.refreshed += 1


def manifest_for(repo: Path, risk: str = "R1") -> dict:
    return {
        "schema_version": 1,
        "id": "RBT-003",
        "title": "ROS2 acceptance",
        "repository": str(repo),
        "base_branch": "main",
        "risk_class": risk,
        "project_kind": "ros2",
        "goal": "develop according to documents",
        "scope": {"include": ["src/**", "tests/**", "scripts/**"], "exclude": []},
        "acceptance_criteria": ["tests pass"],
        "verification": {
            "local": [{"id": "local", "command": ["bash", "scripts/ci/verify.sh"], "timeout_seconds": 60}],
            "integration": [{"lane": "ros2-humble", "action": "test", "args": ["--clean"]}],
        },
        "isolation": {"strategy": "worktree"},
        "human_gates": {"merge": "required"},
        "promotion": {"physical_hardware": "prohibited"},
        "rollback": {"method": "revert_commit"},
    }


def test_ros_and_mixed_default_to_r2_but_explicit_risk_wins() -> None:
    assert default_risk_for_kind("ros2") == "R2"
    assert default_risk_for_kind("mixed") == "R2"
    assert default_risk_for_kind("generic") == "R1"
    assert default_risk_for_kind("firmware") == "R1"
    base = dict(id="RBT-1", title="x", repository="projects/x")
    assert _manifest_template(SimpleNamespace(**base, kind="ros2", risk=None))["risk_class"] == "R2"
    assert _manifest_template(SimpleNamespace(**base, kind="ros2", risk="R1"))["risk_class"] == "R1"


def test_reclassify_escalates_invalidates_current_bindings_and_requires_replan(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    repo = workspace / "projects" / "ros"
    repo.mkdir(parents=True)
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(workspace))
    item = FakeRiskItem(tmp_path, manifest_for(repo))
    old, new = reclassify_work_item(item, "R2", actor="kazwong", note="ROS behavior")
    assert (old, new) == ("R1", "R2")
    assert item.manifest["risk_class"] == "R2"
    assert item.status["risk_class"] == "R2"
    assert item.status["state"] == "INTAKE"
    assert item.status["current_plan"] is None
    assert item.status["implementation"] is None
    assert item.status["ci"] is None
    assert item.status["promotion"] is None
    assert item.status["risk_history"][-1]["actor"] == "kazwong"
    assert item.status["gate_epochs"] == {"plan": 1, "merge": 1, "hardware": 1}
    applied = [entry for entry in item.traces if entry["event"] == "risk_reclassification_applied"][-1]
    assert applied["actor"] == "kazwong"
    assert applied["metadata"]["from"] == "R1"
    assert applied["metadata"]["to"] == "R2"


def test_reclassify_rejects_downgrade_and_inadequate_stricter_controls(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    repo = workspace / "projects" / "ros"
    repo.mkdir(parents=True)
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(workspace))
    item = FakeRiskItem(tmp_path, manifest_for(repo, risk="R2"))
    with pytest.raises(AgentEnvError, match="must escalate"):
        reclassify_work_item(item, "R1", actor="operator")

    weak = manifest_for(repo, risk="R1")
    weak["project_kind"] = "generic"
    weak["verification"]["integration"] = []
    weak_item = FakeRiskItem(tmp_path / "weak", weak)
    with pytest.raises(AgentEnvError, match="requires an integration lane"):
        reclassify_work_item(weak_item, "R2", actor="operator")
    assert weak_item.manifest["risk_class"] == "R1"
    assert weak_item.status["risk_class"] == "R1"


def test_ros2_docker_compat_rewrites_only_project_exec() -> None:
    original = ["compose", "-f", "compose.yaml", "exec", "-T", "ros-test", "ros2-test-project", "/workspace/p", "--clean"]
    rewritten = rewrite_docker_args(original)
    assert rewritten[:6] == original[:6]
    assert rewritten[6:10] == ["/bin/bash", "-c", ROS2_SETUP_COMMAND, "--"]
    assert rewritten[10:] == ["/workspace/p", "--clean"]
    assert rewrite_docker_args(["compose", "ps"]) == ["compose", "ps"]
    assert rewrite_docker_args(["compose", "exec", "svc", "bash"]) == ["compose", "exec", "svc", "bash"]
    assert rewrite_docker_args(["version"]) == ["version"]


def test_external_humble_lane_uses_compat_docker_for_actual_exec(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "projects" / "app"
    project.mkdir(parents=True)
    state = workspace / ".agent-state"
    lane_root = workspace / "infrastructure" / "ros2-humble-gazebo-test"
    lane_root.mkdir(parents=True)
    log = tmp_path / "docker-argv.json"

    real_docker = tmp_path / "real-docker"
    real_docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "open(os.environ['DOCKER_LOG'], 'w').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    real_docker.chmod(0o755)
    ros2_test = lane_root / "ros2-test"
    ros2_test.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "action=$1; shift\n"
        "docker compose -f compose.yaml exec -T ros-test ros2-test-project \"$@\"\n",
        encoding="utf-8",
    )
    ros2_test.chmod(0o755)

    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("AGENT_STATE_ROOT", str(state))
    monkeypatch.setenv("ROBOTICS_AGENT_ENV_ROOT", str(ROOT))
    monkeypatch.setenv("DOCKER_BIN", str(real_docker))
    monkeypatch.setenv("DOCKER_LOG", str(log))

    lane = Lane("ros2-humble", {
        "type": "external-cli",
        "root": str(lane_root),
        "executable": "ros2-test",
        "capabilities": ["test"],
    })

    class Registry:
        raw = {"schema_version": 1}
        def get(self, name):
            assert name == "ros2-humble"
            return lane

    result = TestController(Registry()).run("ros2-humble", "test", project, ["--clean"])
    assert result.returncode == 0
    forwarded = json.loads(log.read_text(encoding="utf-8"))
    assert forwarded[:6] == ["compose", "-f", "compose.yaml", "exec", "-T", "ros-test"]
    assert forwarded[6:10] == ["/bin/bash", "-c", ROS2_SETUP_COMMAND, "--"]
    assert forwarded[-2:] == [str(project), "--clean"]


def test_local_python_template_is_scoped_and_main_image_provisions_tools() -> None:
    verify = (ROOT / "templates/python/scripts/ci/verify.sh").read_text(encoding="utf-8")
    assert "PYTHONPATH=src python3 -m pytest tests" in verify
    assert "PYTHONPATH=src python3 -m pytest\n" not in verify
    dockerfile = (ROOT / "docker/main/Dockerfile").read_text(encoding="utf-8")
    assert "python3-pytest" in dockerfile
    assert "pipx install ruff" in dockerfile
