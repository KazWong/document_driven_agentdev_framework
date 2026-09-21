from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import init_repo
from robotics_agent_env import scm
from robotics_agent_env.scm import configure_project_scm, verify_pull_request_merged
from robotics_agent_env.util import AgentEnvError
from robotics_agent_env.workitem import WorkItem


def create_item(workspace: Path, repo: Path, *, provider: str = "github") -> WorkItem:
    manifest = {
        "schema_version": 1,
        "id": "MERGE-1",
        "title": "verify remote merge before promotion",
        "repository": str(repo),
        "base_branch": "main",
        "risk_class": "R1",
        "project_kind": "generic",
        "goal": "verify the merge integrity gate",
        "scope": {"include": ["src/**", "tests/**"], "exclude": []},
        "acceptance_criteria": ["promotion requires immutable remote merge proof"],
        "verification": {
            "local": [{"id": "unit", "command": ["python3", "-c", "print('ok')"], "timeout_seconds": 60}],
            "integration": [],
        },
        "isolation": {"strategy": "worktree"},
        "promotion": {"physical_hardware": "prohibited"},
    }
    path = workspace / "MERGE-1.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    item = WorkItem.create(path)
    item.create_worktree()
    remote = "https://github.com/acme/app.git" if provider == "github" else "git@bitbucket.org:team/app.git"
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=repo, check=True)
    configure_project_scm(repo, provider=provider, remote="origin", base_branch="main")
    target = item.repo / "src" / "feature.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    candidate = item.create_candidate_commit()
    for stage in ("local", "integration", "review"):
        item.record_candidate_stage(stage)
    repository = "acme/app" if provider == "github" else "team/app"
    number = 17 if provider == "github" else 23
    url = (
        "https://github.com/acme/app/pull/17"
        if provider == "github"
        else "https://bitbucket.org/team/app/pull-requests/23"
    )
    item.set_pull_request({
        "provider": provider,
        "repository": repository,
        "number": number,
        "url": url,
        "state": "OPEN",
        "head_branch": item.status["branch"],
        "head_sha": candidate,
        "base_branch": "main",
        "candidate_sha": candidate,
    })
    item.update_status({"state": "PR_OPEN"}, event="test_pr_open")
    return item


def advance_to_merge_approved(item: WorkItem) -> str:
    candidate = item.candidate_sha()
    assert candidate
    item.record_ci("passed", "https://ci.example.invalid/run/1", commit=candidate)
    item.add_approval("merge", actor="reviewer-a", note="verified")
    assert item.status["state"] == "MERGE_APPROVED"
    return candidate


def fake_github_response(item: WorkItem, *, state: str = "MERGED", head_sha: str | None = None):
    candidate = item.candidate_sha()
    payload = {
        "number": 17,
        "url": "https://github.com/acme/app/pull/17",
        "state": state,
        "mergedAt": "2026-09-21T02:00:00Z" if state == "MERGED" else None,
        "mergeCommit": {"oid": "a" * 40} if state == "MERGED" else None,
        "headRefName": item.status["branch"],
        "headRefOid": head_sha or candidate,
        "baseRefName": "main",
    }

    def runner(args, **kwargs):
        assert args[:3] == ["gh", "pr", "view"]
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    return runner


def test_promotion_rejects_github_pr_that_is_not_merged(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    advance_to_merge_approved(item)
    monkeypatch.setattr(scm, "run_capture", fake_github_response(item, state="OPEN"))

    with pytest.raises(AgentEnvError, match="not merged"):
        item.record_promotion("simulation", "simulation evidence", actor="operator")

    assert item.status["state"] == "MERGE_APPROVED"
    assert item.status.get("merge") is None
    assert item.status.get("promotion") is None
    assert not (item.artifacts_path / "merge-verification.json").exists()


def test_promotion_rejects_merged_pr_with_different_head_sha(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    advance_to_merge_approved(item)
    monkeypatch.setattr(scm, "run_capture", fake_github_response(item, head_sha="b" * 40))

    with pytest.raises(AgentEnvError, match="does not match reviewed candidate"):
        item.record_promotion("simulation", "simulation evidence", actor="operator")

    assert item.status["state"] == "MERGE_APPROVED"
    assert item.status.get("merge") is None


def test_promotion_rejects_provider_pr_identity_mismatch(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    advance_to_merge_approved(item)
    candidate = item.candidate_sha()
    assert candidate
    payload = {
        "number": 18,
        "url": "https://github.com/acme/app/pull/18",
        "state": "MERGED",
        "mergedAt": "2026-09-21T02:00:00Z",
        "mergeCommit": {"oid": "a" * 40},
        "headRefName": item.status["branch"],
        "headRefOid": candidate,
        "baseRefName": "main",
    }

    monkeypatch.setattr(
        scm, "run_capture",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, json.dumps(payload), ""),
    )

    with pytest.raises(AgentEnvError, match="does not match recorded pull request"):
        item.record_promotion("simulation", "simulation evidence", actor="operator")

    assert item.status["state"] == "MERGE_APPROVED"
    assert item.status.get("merge") is None
    assert not (item.artifacts_path / "merge-verification.json").exists()


def test_promotion_fails_closed_when_provider_lookup_fails(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    advance_to_merge_approved(item)
    monkeypatch.setattr(
        scm, "run_capture",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", "authentication failed"),
    )

    with pytest.raises(AgentEnvError, match="verification failed"):
        item.record_promotion("simulation", "simulation evidence", actor="operator")

    assert item.status["state"] == "MERGE_APPROVED"
    assert item.status.get("merge") is None
    assert item.status.get("promotion") is None
    assert not (item.artifacts_path / "merge-verification.json").exists()


def test_promotion_records_remote_merge_proof_before_promoted(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    candidate = advance_to_merge_approved(item)
    monkeypatch.setattr(scm, "run_capture", fake_github_response(item))

    item.record_promotion("simulation", "simulation evidence", actor="operator")

    status = item.status
    assert status["state"] == "PROMOTED"
    assert status["merge"] == {
        "provider": "github",
        "repository": "acme/app",
        "number": 17,
        "url": "https://github.com/acme/app/pull/17",
        "state": "MERGED",
        "head_branch": status["branch"],
        "head_sha": candidate,
        "base_branch": "main",
        "merge_sha": "a" * 40,
        "merged_at": "2026-09-21T02:00:00Z",
        "candidate_sha": candidate,
        "verification_source": "remote-provider",
    }
    assert status["promotion"]["git_sha"] == candidate
    assert status["promotion"]["merge_sha"] == "a" * 40
    artifact = json.loads((item.artifacts_path / "merge-verification.json").read_text(encoding="utf-8"))
    assert artifact == status["merge"]


def test_bitbucket_merge_reconciliation_is_candidate_bound(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo, provider="bitbucket")
    candidate = item.candidate_sha()
    assert candidate

    monkeypatch.setattr(scm, "get_bitbucket_pull_request", lambda remote, number: {
        "id": 23,
        "state": "MERGED",
        "updated_on": "2026-09-21T02:10:00+00:00",
        "merge_commit": {"hash": "c" * 40},
        "source": {
            "branch": {"name": item.status["branch"]},
            "commit": {"hash": candidate},
        },
        "destination": {"branch": {"name": "main"}},
        "links": {"html": {"href": "https://bitbucket.org/team/app/pull-requests/23"}},
    })

    merge = verify_pull_request_merged(item)
    assert merge["provider"] == "bitbucket"
    assert merge["head_sha"] == candidate
    assert merge["merge_sha"] == "c" * 40
    assert merge["state"] == "MERGED"


def test_new_ci_result_clears_stale_merge_proof(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    candidate = item.candidate_sha()
    assert candidate
    item.update_status({"merge": {"state": "MERGED", "head_sha": candidate}}, event="seed_stale_merge")
    item.record_ci("passed", "https://ci.example.invalid/run/2", commit=candidate)
    assert item.status["merge"] is None
