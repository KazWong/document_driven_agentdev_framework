from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import init_repo
from robotics_agent_env import verification, workflow
from robotics_agent_env.test_registry import TestResult
from robotics_agent_env.workitem import WorkItem


def _manifest(repo: Path, work_id: str, *, risk: str = "R2") -> dict:
    return {
        "schema_version": 1,
        "id": work_id,
        "title": "consolidated acceptance",
        "repository": str(repo),
        "base_branch": "main",
        "risk_class": risk,
        "project_kind": "ros2" if risk == "R2" else "generic",
        "goal": "implement imported documents",
        "scope": {"include": ["src/**", "tests/**", "scripts/**"], "exclude": []},
        "acceptance_criteria": ["exact candidate is verified"],
        "verification": {
            "local": [{"id": "local", "command": ["python3", "-c", "print('ok')"], "timeout_seconds": 60}],
            "integration": ([{"lane": "ros2-humble", "action": "test", "args": ["--clean"]}] if risk == "R2" else []),
        },
        "isolation": {"strategy": "worktree"},
        "promotion": {"physical_hardware": "prohibited"},
    }


def _item(workspace: Path, repo: Path, work_id: str = "ACC-1", *, risk: str = "R2") -> WorkItem:
    path = workspace / f"{work_id}.yaml"
    path.write_text(yaml.safe_dump(_manifest(repo, work_id, risk=risk)), encoding="utf-8")
    item = WorkItem.create(path)
    item.create_worktree()
    return item


def _candidate(item: WorkItem, value: int = 1) -> str:
    target = item.repo / "src" / "value.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"VALUE = {value}\n", encoding="utf-8")
    return item.create_candidate_commit()


def test_implementation_route_clears_current_candidate_and_downstream_bindings(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = _item(workspace, repo)
    old = _candidate(item)
    item.record_candidate_stage("local", old)
    item.record_candidate_stage("integration", old)
    item.record_candidate_stage("review", old)
    item.set_pull_request({
        "provider": "github", "url": "https://example.invalid/pr/1", "head_sha": old,
        "head_branch": item.status["branch"], "base_branch": "main",
    })
    item.update_status({"ci": {"status": "passed", "commit": old}, "state": "DIAGNOSED"}, event="test_diagnosed")

    assert item.invalidate_execution("implementation") == "PLAN_APPROVED"
    status = item.status
    assert status["implementation"] is None
    assert status["pull_request"] is None
    assert status["ci"] is None

    # Historical commit is preserved, but the next implementation becomes a new current candidate.
    assert subprocess.run(["git", "-C", str(item.repo), "cat-file", "-e", f"{old}^{{commit}}"], check=False).returncode == 0
    (item.repo / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
    new = item.create_candidate_commit(expected_head=old)
    assert new != old
    assert item.status["implementation"]["candidate_sha"] == new
    assert item.status["implementation"]["local_test_sha"] is None


def test_local_and_environment_routes_invalidate_only_downstream_fields(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = _item(workspace, repo)
    candidate = _candidate(item)
    item.record_candidate_stage("local", candidate)
    item.record_candidate_stage("integration", candidate)
    item.record_candidate_stage("review", candidate)
    item.update_status({"state": "DIAGNOSED"}, event="test_diagnosed")

    assert item.invalidate_execution("environment") == "LOCALLY_VERIFIED"
    impl = item.status["implementation"]
    assert impl["candidate_sha"] == candidate
    assert impl["local_test_sha"] == candidate
    assert impl["integration_test_sha"] is None
    assert impl["reviewed_sha"] is None

    item.update_status({"state": "DIAGNOSED"}, event="test_diagnosed_again")
    assert item.invalidate_execution("local-test") == "IMPLEMENTED"
    impl = item.status["implementation"]
    assert impl["candidate_sha"] == candidate
    assert impl["local_test_sha"] is None
    assert impl["integration_test_sha"] is None
    assert impl["reviewed_sha"] is None


class _PositiveRosController:
    def run(self, lane, action, project, args, timeout=None):
        project = Path(project)
        # Prove the verifier received a detached candidate checkout, not the development worktree.
        assert ".agent-state/verifiers/integration/" in str(project)
        results = project / ".test-results" / "ros2-humble" / "latest" / "junit"
        results.mkdir(parents=True)
        (results / "results.xml").write_text(
            '<testsuite tests="2"><testcase name="graph"/><testcase name="gui"/></testsuite>',
            encoding="utf-8",
        )
        (project / "build").mkdir()
        (project / "install").mkdir()
        (project / "log").mkdir()
        return TestResult(lane, action, ["ros2-test", "test", str(project), *args], 0, "Summary: 2 tests", "")


class _ZeroRosController:
    def run(self, lane, action, project, args, timeout=None):
        project = Path(project)
        results = project / ".test-results" / "ros2-humble" / "latest" / "junit"
        results.mkdir(parents=True)
        (results / "results.xml").write_text('<testsuite tests="0"></testsuite>', encoding="utf-8")
        return TestResult(lane, action, ["ros2-test", "test", str(project), *args], 0, "Summary: 0 tests, 0 errors", "")


def test_integration_verifier_isolates_candidate_binds_sha_and_cleans_generated_outputs(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = _item(workspace, repo)
    candidate = _candidate(item)
    item.record_candidate_stage("local", candidate)
    monkeypatch.setattr(verification, "TestController", _PositiveRosController)

    summary = verification.run_integration_verification(item)
    assert summary["passed"] is True
    assert summary["candidate_sha"] == candidate
    assert summary["verification_source"] == "detached-candidate-checkout"
    assert summary["lanes"][0]["test_count"] == 2
    assert summary["lanes"][0]["candidate_sha"] == candidate
    assert not (item.repo / "build").exists()
    assert not (item.repo / "install").exists()
    assert not (item.repo / "log").exists()
    assert subprocess.check_output(["git", "-C", str(item.repo), "status", "--porcelain"], text=True).strip() == ""
    verifier_root = item.state_root / "verifiers" / "integration" / item.project_root.name / item.work_id
    assert not (verifier_root / candidate).exists()


def test_required_ros_integration_rejects_zero_test_exit_zero(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = _item(workspace, repo)
    candidate = _candidate(item)
    item.record_candidate_stage("local", candidate)
    monkeypatch.setattr(verification, "TestController", _ZeroRosController)

    summary = verification.run_integration_verification(item)
    assert summary["passed"] is False
    lane = summary["lanes"][0]
    assert lane["test_count"] == 0
    assert lane["returncode"] == 125
    assert "positive executed-test count" in lane["reason"]


def test_workflow_does_not_record_integration_sha_when_zero_tests_run(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = _item(workspace, repo)
    candidate = _candidate(item)
    item.record_candidate_stage("local", candidate)
    item.update_status({"state": "LOCALLY_VERIFIED"}, event="test_locally_verified")
    monkeypatch.setattr(verification, "TestController", _ZeroRosController)
    # workflow imported the function object; patch that reference too.
    monkeypatch.setattr(workflow, "run_integration_verification", verification.run_integration_verification)
    monkeypatch.setattr(workflow, "dispatch_role", lambda *a, **k: {
        "status": "completed", "decision": "pass", "summary": "analysis pass",
        "deliverable_markdown": "", "scope_change": False, "findings": [], "evidence": [],
    })

    assert workflow.run_next(item) == "DIAGNOSING"
    assert item.status["implementation"]["integration_test_sha"] is None

def test_bootstrap_migrates_only_default_v201_image_tags() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "bootstrap-host.sh").read_text(encoding="utf-8")
    assert '"robotics-ai-agent-main:2.0.1", "robotics-ai-agent-main:2.0.2"' in text
    assert 'new_value if value == old_value else value' in text
