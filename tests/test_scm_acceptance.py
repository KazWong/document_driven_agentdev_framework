from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import init_repo
from robotics_agent_env import workflow
from robotics_agent_env.agentctl_cli import build_parser, main as agentctl_main
from robotics_agent_env.scm import configure_project_scm, infer_github_repository, publish_pull_request
from robotics_agent_env.scm_cli import main as scmctl_main
from robotics_agent_env.util import AgentEnvError, git, git_sha
from robotics_agent_env.workitem import WorkItem

ROOT = Path(__file__).resolve().parents[1]


def create_item(workspace: Path, repo: Path, work_id: str = "SCM-1") -> WorkItem:
    manifest = {
        "schema_version": 1,
        "id": work_id,
        "title": "implement provider neutral publication",
        "repository": str(repo),
        "base_branch": "main",
        "risk_class": "R1",
        "project_kind": "generic",
        "goal": "implement the imported project documents",
        "scope": {"include": ["src/**", "tests/**", "scripts/**"], "exclude": []},
        "acceptance_criteria": ["candidate is verified"],
        "verification": {
            "local": [{"id": "verify", "command": ["python3", "-c", "print('ok')"], "timeout_seconds": 60}],
            "integration": [],
        },
        "isolation": {"strategy": "worktree"},
        "promotion": {"physical_hardware": "prohibited"},
    }
    path = workspace / f"{work_id}.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    item = WorkItem.create(path)
    item.create_worktree()
    return item


def make_candidate(item: WorkItem) -> str:
    target = item.repo / "src" / "feature.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    return item.create_candidate_commit()


def make_fake_gh(path: Path, *, mismatch: bool = False) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        "log = os.environ.get('GH_ARGV_LOG')\n"
        "if log:\n"
        "    with open(log, 'a', encoding='utf-8') as handle:\n"
        "        handle.write(' '.join(args) + '\\n')\n"
        "if args[:2] == ['pr', 'create']:\n"
        "    print('https://github.com/acme/app/pull/17')\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['pr', 'view']:\n"
        "    sha = subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()\n"
        + ("    sha = 'deadbeef'\n" if mismatch else "")
        + "    branch = subprocess.check_output(['git','branch','--show-current'], text=True).strip()\n"
        "    print(json.dumps({'number':17,'url':'https://github.com/acme/app/pull/17','state':'OPEN','headRefName':branch,'headRefOid':sha,'baseRefName':'main','statusCheckRollup':[]}))\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['auth', 'status']:\n"
        "    print('authenticated')\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['auth', 'setup-git']:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def prepare_github_remote(repo: Path, workspace: Path) -> Path:
    bare = workspace / "github-bare.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    github_url = "https://github.com/acme/app.git"
    subprocess.run(["git", "remote", "add", "origin", github_url], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", f"url.file://{bare}.insteadOf", github_url], cwd=repo, check=True
    )
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return bare


@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:acme/app.git",
        "ssh://git@github.com/acme/app.git",
        "https://github.com/acme/app.git",
        "https://user@github.com/acme/app",
    ],
)
def test_infer_github_repository(remote: str) -> None:
    assert infer_github_repository(remote) == ("acme", "app")


def test_candidate_commit_rejects_noop_and_binds_all_verification_stages(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    with pytest.raises(AgentEnvError, match="no implementation changes"):
        item.create_candidate_commit()
    candidate = make_candidate(item)
    assert candidate != item.status["baseline_sha"]
    assert git_sha(item.repo) == candidate
    assert git(item.repo, "status", "--porcelain").stdout == ""
    assert item.record_candidate_stage("local") == candidate
    assert item.record_candidate_stage("integration") == candidate
    assert item.record_candidate_stage("review") == candidate
    assert item.require_publishable_candidate() == candidate
    implementation = item.status["implementation"]
    assert {implementation[key] for key in ("candidate_sha", "local_test_sha", "integration_test_sha", "reviewed_sha")} == {candidate}


def test_candidate_integrity_rejects_post_commit_tracked_change(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    make_candidate(item)
    (item.repo / "src" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(AgentEnvError, match="tracked files changed"):
        item.record_candidate_stage("local")


def test_github_publication_pushes_exact_reviewed_candidate_and_records_pr(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    bare = prepare_github_remote(repo, workspace)
    item = create_item(workspace, repo)
    configure_project_scm(repo, provider="github", remote="origin", base_branch="main")
    candidate = make_candidate(item)
    for stage in ("local", "integration", "review"):
        item.record_candidate_stage(stage)
    item.write_artifact("pull-request.md", "# Pull request\n\nVerified candidate.")
    item.update_status({"state": "PR_CREATING"}, event="test_state")
    fake_bin = workspace / "bin"
    fake_bin.mkdir()
    make_fake_gh(fake_bin / "gh")
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("GH_CONFIG_DIR", str(workspace / "gh-config"))

    pr = publish_pull_request(item)
    assert pr["provider"] == "github"
    assert pr["head_sha"] == candidate
    assert pr["head_branch"] == item.status["branch"]
    remote_sha = subprocess.check_output(
        ["git", "--git-dir", str(bare), "rev-parse", f"refs/heads/{item.status['branch']}"], text=True
    ).strip()
    assert remote_sha == candidate
    assert item.status["pull_request"]["head_sha"] == candidate


def test_github_publication_rejects_remote_head_sha_mismatch(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    prepare_github_remote(repo, workspace)
    item = create_item(workspace, repo)
    configure_project_scm(repo, provider="github", remote="origin", base_branch="main")
    make_candidate(item)
    for stage in ("local", "integration", "review"):
        item.record_candidate_stage(stage)
    item.write_artifact("pull-request.md", "# Pull request\n")
    item.update_status({"state": "PR_CREATING"}, event="test_state")
    fake_bin = workspace / "bin"
    fake_bin.mkdir()
    make_fake_gh(fake_bin / "gh", mismatch=True)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    with pytest.raises(AgentEnvError, match="does not match reviewed candidate"):
        publish_pull_request(item)
    assert item.status.get("pull_request") is None


def test_workflow_commits_verifies_reviews_and_auto_publishes_to_pr_open(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo, "FLOW-1")
    item.update_status({"state": "PLAN_APPROVED"}, event="test_state")

    def fake_role(current: WorkItem, role: str, **kwargs):
        if role == "coder":
            target = current.repo / "src" / "flow.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("READY = True\n", encoding="utf-8")
        if role == "review_requester":
            current.write_artifact("pull-request.md", "# PR\n")
        return {
            "status": "completed", "decision": "pass", "summary": f"{role} passed",
            "deliverable_markdown": "", "scope_change": False, "findings": [], "evidence": [],
        }

    monkeypatch.setattr(workflow, "dispatch_role", fake_role)
    monkeypatch.setattr(workflow, "run_local_verification", lambda current: {"passed": True, "not_applicable": False})
    monkeypatch.setattr(workflow, "run_integration_verification", lambda current: {"passed": True, "not_applicable": True})

    def fake_publish(current: WorkItem):
        candidate = current.require_publishable_candidate()
        pr = {
            "provider": "github", "number": 1, "url": "https://github.com/acme/app/pull/1",
            "state": "OPEN", "head_branch": current.status["branch"], "head_sha": candidate,
            "base_branch": "main", "status_checks": [], "candidate_sha": candidate,
        }
        current.update_status({"pull_request": pr}, event="pull_request_opened")
        return pr

    monkeypatch.setattr(workflow, "publish_pull_request", fake_publish)
    assert workflow.run_until_gate(item) == "PR_OPEN"
    implementation = item.status["implementation"]
    assert len({implementation[k] for k in ("candidate_sha", "local_test_sha", "integration_test_sha", "reviewed_sha")}) == 1
    assert item.status["pull_request"]["head_sha"] == implementation["candidate_sha"]


def test_pr_human_gate_removed_and_branching_policy_propagated(workspace: Path) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo)
    policy = repo / ".agent" / "branching-policy.md"
    assert policy.is_file()
    assert "agent/<work-item-id-lower>-<short-slug>" in policy.read_text(encoding="utf-8")
    parser = build_parser()
    approve_action = None
    subparsers = next(action for action in parser._actions if action.dest == "command")
    approve_parser = subparsers.choices["approve"]
    for action in approve_parser._actions:
        if action.dest == "gate":
            approve_action = action
            break
    assert approve_action is not None
    assert "pr" not in approve_action.choices
    workflow_config = yaml.safe_load((ROOT / "config" / "workflow.yaml").read_text(encoding="utf-8"))
    assert workflow_config["human_gates"] == {
        "PLANNED": "plan", "CI_VERIFIED": "merge", "MERGE_APPROVED": "hardware-when-required"
    }
    assert "PR_OPEN" in workflow_config["states"]


def test_github_cli_and_login_are_installed_and_persistent() -> None:
    dockerfile = (ROOT / "docker" / "main" / "Dockerfile").read_text(encoding="utf-8")
    assert "https://cli.github.com/packages" in dockerfile
    assert "apt-get install -y --no-install-recommends gh" in dockerfile
    assert "GH_CONFIG_DIR=/home/kazwong/codes/agents/.agent-state/github-cli" in dockerfile
    assert "ln -s /opt/robotics-agent-env/bin/scmctl /usr/local/bin/scmctl" in dockerfile
    login = (ROOT / "scripts" / "github-login.sh").read_text(encoding="utf-8")
    assert "run_gh_interactive auth login --hostname github.com --git-protocol https --web" in login
    assert "run_gh_noninteractive auth status --hostname github.com" in login
    assert "--profile auth" in login
    assert "run --rm --no-deps codex-login gh" in login
    assert (ROOT / "docs" / "todo.md").is_file()


def test_bitbucket_provider_publishes_without_pr_human_gate(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from robotics_agent_env import scm

    repo = init_repo(workspace / "projects" / "app")
    bare = workspace / "bitbucket-bare.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    bitbucket_url = "git@bitbucket.org:team/app.git"
    subprocess.run(["git", "remote", "add", "origin", bitbucket_url], cwd=repo, check=True)
    subprocess.run(["git", "config", f"url.file://{bare}.insteadOf", bitbucket_url], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    item = create_item(workspace, repo, "BB-1")
    configure_project_scm(repo, provider="bitbucket", remote="origin", base_branch="main")
    candidate = make_candidate(item)
    for stage in ("local", "integration", "review"):
        item.record_candidate_stage(stage)
    item.write_artifact("pull-request.md", "# Pull request\n")
    item.update_status({"state": "PR_CREATING"}, event="test_state")

    def fake_create(current: WorkItem, payload, remote=None):
        assert remote == bitbucket_url
        return {
            "id": 23,
            "state": "OPEN",
            "links": {"html": {"href": "https://bitbucket.org/team/app/pull-requests/23"}},
            "source": {"branch": {"name": current.status["branch"]}, "commit": {"hash": candidate}},
            "destination": {"branch": {"name": "main"}},
        }

    monkeypatch.setattr(scm, "create_pull_request", fake_create)
    pr = publish_pull_request(item)
    assert pr["provider"] == "bitbucket"
    assert pr["head_sha"] == candidate
    assert pr["number"] == 23
    remote_sha = subprocess.check_output(
        ["git", "--git-dir", str(bare), "rev-parse", f"refs/heads/{item.status['branch']}"], text=True
    ).strip()
    assert remote_sha == candidate



def test_agentctl_inspect_exposes_candidate_for_human_review(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo, "VIEW-1")
    candidate = make_candidate(item)
    monkeypatch.chdir(repo)
    assert agentctl_main(["inspect", item.work_id, "--stat"]) == 0
    output = capsys.readouterr().out
    assert f"candidate: {candidate}" in output
    assert "src/feature.py" in output
    assert str(item.repo) in output


def test_scmctl_configure_and_pr_status_are_provider_neutral(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    item = create_item(workspace, repo, "CTL-1")
    monkeypatch.chdir(repo)
    assert scmctl_main([
        "configure", "--provider", "github", "--remote", "origin",
        "--base-branch", "main", "--project", str(repo),
    ]) == 0
    project = yaml.safe_load((repo / ".agent" / "project.yaml").read_text(encoding="utf-8"))
    assert project["scm"] == {"provider": "github", "remote": "origin", "base_branch": "main"}
    item.update_status({"pull_request": {
        "provider": "github", "repository": "acme/app", "number": 9,
        "url": "https://github.com/acme/app/pull/9", "head_sha": "abc123",
        "head_branch": "agent/ctl-1", "base_branch": "main",
    }}, event="test_pr")
    assert scmctl_main(["pr", "status", item.work_id]) == 0
    output = capsys.readouterr().out
    assert '"provider": "github"' in output
    assert '"number": 9' in output


def test_github_token_stays_in_environment_not_gh_arguments(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(workspace / "projects" / "app")
    prepare_github_remote(repo, workspace)
    item = create_item(workspace, repo, "TOKEN-1")
    configure_project_scm(repo, provider="github", remote="origin", base_branch="main")
    make_candidate(item)
    for stage in ("local", "integration", "review"):
        item.record_candidate_stage(stage)
    item.write_artifact("pull-request.md", "# Pull request\n")
    item.update_status({"state": "PR_CREATING"}, event="test_state")
    fake_bin = workspace / "bin"
    fake_bin.mkdir()
    make_fake_gh(fake_bin / "gh")
    argv_log = workspace / "gh-argv.log"
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("GH_TOKEN", "ghp-test-secret-never-in-argv")
    monkeypatch.setenv("GH_ARGV_LOG", str(argv_log))
    publish_pull_request(item)
    assert "ghp-test-secret-never-in-argv" not in argv_log.read_text(encoding="utf-8")
