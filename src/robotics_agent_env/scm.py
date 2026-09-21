from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .bitbucket import (
    build_pull_request_payload, create_pull_request, get_pull_request as get_bitbucket_pull_request,
    infer_repository as infer_bitbucket_repository,
)
from .util import AgentEnvError, dump_yaml, git, git_common_root, load_yaml, run_capture, state_root
from .workitem import WorkItem

SUPPORTED_PROVIDERS = {"github", "bitbucket"}


def project_scm_config(project_root: Path) -> dict[str, str]:
    project = git_common_root(project_root)
    path = project / ".agent" / "project.yaml"
    data = load_yaml(path)
    raw = data.get("scm")
    if not isinstance(raw, dict):
        raise AgentEnvError(
            f"SCM is not configured in {path}; run 'scmctl configure --provider github|bitbucket'"
        )
    provider = str(raw.get("provider", "")).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise AgentEnvError(f"unsupported SCM provider '{provider}'; expected github or bitbucket")
    remote = str(raw.get("remote") or "origin").strip()
    base_branch = str(raw.get("base_branch") or "main").strip()
    if not remote or not base_branch:
        raise AgentEnvError(f"invalid SCM configuration in {path}")
    return {"provider": provider, "remote": remote, "base_branch": base_branch}


def configure_project_scm(
    project_root: Path, *, provider: str, remote: str = "origin", base_branch: str = "main"
) -> Path:
    project = git_common_root(project_root)
    provider = provider.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise AgentEnvError("provider must be github or bitbucket")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", remote):
        raise AgentEnvError(f"invalid Git remote name: {remote}")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", base_branch):
        raise AgentEnvError(f"invalid base branch: {base_branch}")
    path = project / ".agent" / "project.yaml"
    data = load_yaml(path)
    data["scm"] = {"provider": provider, "remote": remote, "base_branch": base_branch}
    dump_yaml(path, data)
    return path


def remote_url(repo: Path, remote: str) -> str:
    # Read the configured URL rather than `git remote get-url`, which expands
    # url.*.insteadOf rewrites. Provider inference must use the declared remote
    # identity while Git itself remains free to use a local/test transport rewrite.
    completed = git(repo, "config", "--get", f"remote.{remote}.url", check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise AgentEnvError(f"Git remote '{remote}' is not configured")
    return completed.stdout.strip()


def infer_github_repository(remote: str) -> tuple[str, str]:
    patterns = [
        r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+)/(.+?)(?:\.git)?$",
        r"^https?://(?:[^@/]+@)?github\.com/([^/]+)/(.+?)(?:\.git)?/?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, remote)
        if match:
            return match.group(1), match.group(2).removesuffix(".git")
    raise AgentEnvError(f"cannot infer GitHub owner/repository from remote: {remote}")


def github_env() -> dict[str, str]:
    env = os.environ.copy()
    config_dir = Path(env.get("GH_CONFIG_DIR", str(state_root() / "github-cli"))).expanduser().resolve()
    config_dir.mkdir(parents=True, exist_ok=True)
    env["GH_CONFIG_DIR"] = str(config_dir)
    return env


def publish_pull_request(item: WorkItem) -> dict[str, Any]:
    candidate = item.require_publishable_candidate()
    status = item.status
    branch = status.get("branch")
    if not branch:
        raise AgentEnvError("cannot publish without a recorded work-item branch")
    config = project_scm_config(item.project_root)
    if config["base_branch"] != item.manifest["base_branch"]:
        raise AgentEnvError(
            f"SCM base branch {config['base_branch']} does not match work-item base branch {item.manifest['base_branch']}"
        )
    remote = config["remote"]
    url = remote_url(item.repo, remote)

    if config["provider"] == "github":
        # Validate the declared remote before any publication and configure
        # Git's credential helper. This also makes GH_TOKEN usable for
        # headless HTTPS pushes without placing the token in Git arguments.
        infer_github_repository(url)
        env = github_env()
        auth = run_capture(["gh", "auth", "status", "--hostname", "github.com"], env=env, check=False)
        if auth.returncode != 0:
            detail = auth.stderr.strip() or auth.stdout.strip()
            raise AgentEnvError(f"GitHub authentication is not ready: {detail}")
        setup = run_capture(["gh", "auth", "setup-git", "--hostname", "github.com"], env=env, check=False)
        if setup.returncode != 0:
            detail = setup.stderr.strip() or setup.stdout.strip()
            raise AgentEnvError(f"failed to configure GitHub Git authentication: {detail}")

    push = git(item.repo, "push", "--set-upstream", remote, branch, check=False)
    if push.returncode != 0:
        detail = push.stderr.strip() or push.stdout.strip()
        raise AgentEnvError(f"failed to push candidate branch without force: {detail}")

    if config["provider"] == "github":
        normalized = _create_github_pull_request(item, url, candidate, config)
    else:
        normalized = _create_bitbucket_pull_request(item, url, candidate, config)

    if normalized.get("head_sha") != candidate:
        raise AgentEnvError(
            f"remote PR head {normalized.get('head_sha')} does not match reviewed candidate {candidate}"
        )
    if normalized.get("head_branch") != branch:
        raise AgentEnvError(
            f"remote PR head branch {normalized.get('head_branch')} does not match work-item branch {branch}"
        )
    if normalized.get("base_branch") != config["base_branch"]:
        raise AgentEnvError(
            f"remote PR base {normalized.get('base_branch')} does not match configured base {config['base_branch']}"
        )
    item.write_artifact("pull-request-created.json", json.dumps(normalized, indent=2, sort_keys=True))
    item.set_pull_request(normalized)
    return normalized


def _create_github_pull_request(
    item: WorkItem, remote: str, candidate: str, config: dict[str, str]
) -> dict[str, Any]:
    owner, repository = infer_github_repository(remote)
    repo_name = f"{owner}/{repository}"
    body = item.artifacts_path / "pull-request.md"
    if not body.is_file():
        raise AgentEnvError("missing pull-request.md artifact")
    branch = str(item.status["branch"])
    env = github_env()
    create = run_capture(
        [
            "gh", "pr", "create", "--repo", repo_name,
            "--base", config["base_branch"], "--head", branch,
            "--title", f"{item.work_id}: {item.manifest['title']}",
            "--body-file", str(body),
        ],
        cwd=item.repo, env=env, check=False,
    )
    if create.returncode != 0:
        detail = create.stderr.strip() or create.stdout.strip()
        raise AgentEnvError(f"GitHub PR creation failed: {detail}")
    view = run_capture(
        [
            "gh", "pr", "view", branch, "--repo", repo_name,
            "--json", "number,url,state,headRefName,headRefOid,baseRefName,statusCheckRollup",
        ],
        cwd=item.repo, env=env, check=False,
    )
    if view.returncode != 0:
        detail = view.stderr.strip() or view.stdout.strip()
        raise AgentEnvError(f"GitHub PR verification failed: {detail}")
    try:
        data = json.loads(view.stdout)
    except json.JSONDecodeError as exc:
        raise AgentEnvError("GitHub CLI returned invalid PR JSON") from exc
    if not isinstance(data, dict):
        raise AgentEnvError("GitHub CLI returned an unexpected PR response")
    return {
        "provider": "github",
        "repository": repo_name,
        "number": data.get("number"),
        "url": data.get("url") or create.stdout.strip(),
        "state": data.get("state"),
        "head_branch": data.get("headRefName"),
        "head_sha": data.get("headRefOid"),
        "base_branch": data.get("baseRefName"),
        "status_checks": data.get("statusCheckRollup") or [],
        "candidate_sha": candidate,
    }


def _create_bitbucket_pull_request(
    item: WorkItem, remote: str, candidate: str, config: dict[str, str]
) -> dict[str, Any]:
    workspace, repository = infer_bitbucket_repository(remote)
    payload = build_pull_request_payload(item)
    response = create_pull_request(item, payload, remote=remote)
    source = response.get("source") if isinstance(response.get("source"), dict) else {}
    destination = response.get("destination") if isinstance(response.get("destination"), dict) else {}
    source_branch = source.get("branch") if isinstance(source.get("branch"), dict) else {}
    source_commit = source.get("commit") if isinstance(source.get("commit"), dict) else {}
    dest_branch = destination.get("branch") if isinstance(destination.get("branch"), dict) else {}
    links = response.get("links") if isinstance(response.get("links"), dict) else {}
    html = links.get("html") if isinstance(links.get("html"), dict) else {}
    return {
        "provider": "bitbucket",
        "repository": f"{workspace}/{repository}",
        "number": response.get("id"),
        "url": html.get("href"),
        "state": response.get("state"),
        "head_branch": source_branch.get("name"),
        "head_sha": source_commit.get("hash"),
        "base_branch": dest_branch.get("name"),
        "status_checks": [],
        "candidate_sha": candidate,
    }


def verify_pull_request_merged(item: WorkItem) -> dict[str, Any]:
    """Reconcile the recorded PR with the provider and return immutable merge proof.

    Promotion is allowed only when the provider confirms that the exact reviewed
    candidate was the PR head that entered the configured base branch.
    """
    candidate = item.require_publishable_candidate()
    status = item.status
    pr = status.get("pull_request")
    if not isinstance(pr, dict):
        raise AgentEnvError("promotion requires a recorded pull request")
    config = project_scm_config(item.project_root)
    provider = str(pr.get("provider") or "").lower()
    if provider != config["provider"]:
        raise AgentEnvError(
            f"recorded pull-request provider {provider or '<missing>'} does not match configured provider {config['provider']}"
        )
    branch = str(status.get("branch") or "")
    if not branch or pr.get("head_branch") != branch:
        raise AgentEnvError("recorded pull-request head branch no longer matches the work-item branch")
    if pr.get("head_sha") != candidate:
        raise AgentEnvError("recorded pull-request head SHA does not match the reviewed candidate")
    if pr.get("base_branch") != config["base_branch"]:
        raise AgentEnvError("recorded pull-request base branch does not match the configured base branch")
    number = pr.get("number")
    if number is None:
        raise AgentEnvError("recorded pull request is missing its provider id")
    remote = config["remote"]
    url = remote_url(item.repo, remote)

    if provider == "github":
        merged = _verify_github_pull_request_merged(item, url, number, candidate, config)
    elif provider == "bitbucket":
        merged = _verify_bitbucket_pull_request_merged(item, url, number, candidate, config)
    else:  # project_scm_config already validates this; retain a fail-closed guard.
        raise AgentEnvError(f"unsupported SCM provider '{provider}'")

    if str(merged.get("number")) != str(number):
        raise AgentEnvError(
            f"merged PR id {merged.get('number')} does not match recorded pull request {number}"
        )
    if merged["head_branch"] != branch:
        raise AgentEnvError(
            f"merged PR head branch {merged['head_branch']} does not match work-item branch {branch}"
        )
    recorded_repository = pr.get("repository")
    if recorded_repository and merged.get("repository") != recorded_repository:
        raise AgentEnvError(
            f"merged PR repository {merged.get('repository')} does not match recorded repository {recorded_repository}"
        )
    recorded_url = pr.get("url")
    merged_url = merged.get("url")
    if (
        isinstance(recorded_url, str) and recorded_url.strip()
        and isinstance(merged_url, str) and merged_url.strip()
        and merged_url.rstrip("/") != recorded_url.rstrip("/")
    ):
        raise AgentEnvError("merged PR URL does not match the recorded pull request")
    return merged


def _verify_github_pull_request_merged(
    item: WorkItem, remote: str, number: int | str, candidate: str, config: dict[str, str]
) -> dict[str, Any]:
    owner, repository = infer_github_repository(remote)
    repo_name = f"{owner}/{repository}"
    view = run_capture(
        [
            "gh", "pr", "view", str(number), "--repo", repo_name,
            "--json", "number,url,state,mergedAt,mergeCommit,headRefName,headRefOid,baseRefName",
        ],
        cwd=item.repo, env=github_env(), check=False,
    )
    if view.returncode != 0:
        detail = view.stderr.strip() or view.stdout.strip()
        raise AgentEnvError(f"GitHub merged-PR verification failed: {detail}")
    try:
        data = json.loads(view.stdout)
    except json.JSONDecodeError as exc:
        raise AgentEnvError("GitHub CLI returned invalid merged-PR JSON") from exc
    if not isinstance(data, dict):
        raise AgentEnvError("GitHub CLI returned an unexpected merged-PR response")
    if str(data.get("state") or "").upper() != "MERGED":
        raise AgentEnvError(f"pull request is not merged; GitHub state is {data.get('state') or '<missing>'}")
    if data.get("headRefOid") != candidate:
        raise AgentEnvError(
            f"merged PR head {data.get('headRefOid')} does not match reviewed candidate {candidate}"
        )
    if data.get("baseRefName") != config["base_branch"]:
        raise AgentEnvError(
            f"merged PR base {data.get('baseRefName')} does not match configured base {config['base_branch']}"
        )
    merge_commit = data.get("mergeCommit")
    merge_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else merge_commit
    if not isinstance(merge_sha, str) or not merge_sha.strip():
        raise AgentEnvError("GitHub merged pull request did not return a merge commit SHA")
    merged_at = data.get("mergedAt")
    if not isinstance(merged_at, str) or not merged_at.strip():
        raise AgentEnvError("GitHub merged pull request did not return a merge timestamp")
    return {
        "provider": "github",
        "repository": repo_name,
        "number": data.get("number"),
        "url": data.get("url"),
        "state": "MERGED",
        "head_branch": data.get("headRefName"),
        "head_sha": data.get("headRefOid"),
        "base_branch": data.get("baseRefName"),
        "merge_sha": merge_sha.strip(),
        "merged_at": merged_at,
        "candidate_sha": candidate,
        "verification_source": "remote-provider",
    }


def _verify_bitbucket_pull_request_merged(
    item: WorkItem, remote: str, number: int | str, candidate: str, config: dict[str, str]
) -> dict[str, Any]:
    workspace, repository = infer_bitbucket_repository(remote)
    data = get_bitbucket_pull_request(remote, number)
    if str(data.get("state") or "").upper() != "MERGED":
        raise AgentEnvError(f"pull request is not merged; Bitbucket state is {data.get('state') or '<missing>'}")
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    destination = data.get("destination") if isinstance(data.get("destination"), dict) else {}
    source_branch = source.get("branch") if isinstance(source.get("branch"), dict) else {}
    source_commit = source.get("commit") if isinstance(source.get("commit"), dict) else {}
    dest_branch = destination.get("branch") if isinstance(destination.get("branch"), dict) else {}
    head_sha = source_commit.get("hash")
    if head_sha != candidate:
        raise AgentEnvError(f"merged PR head {head_sha} does not match reviewed candidate {candidate}")
    if dest_branch.get("name") != config["base_branch"]:
        raise AgentEnvError(
            f"merged PR base {dest_branch.get('name')} does not match configured base {config['base_branch']}"
        )
    merge_commit = data.get("merge_commit") if isinstance(data.get("merge_commit"), dict) else {}
    merge_sha = merge_commit.get("hash")
    if not isinstance(merge_sha, str) or not merge_sha.strip():
        raise AgentEnvError("Bitbucket merged pull request did not return a merge commit SHA")
    links = data.get("links") if isinstance(data.get("links"), dict) else {}
    html = links.get("html") if isinstance(links.get("html"), dict) else {}
    merged_at = data.get("closed_on") or data.get("updated_on")
    if not isinstance(merged_at, str) or not merged_at.strip():
        raise AgentEnvError("Bitbucket merged pull request did not return a merge timestamp")
    return {
        "provider": "bitbucket",
        "repository": f"{workspace}/{repository}",
        "number": data.get("id"),
        "url": html.get("href"),
        "state": "MERGED",
        "head_branch": source_branch.get("name"),
        "head_sha": head_sha,
        "base_branch": dest_branch.get("name"),
        "merge_sha": merge_sha.strip(),
        "merged_at": merged_at,
        "candidate_sha": candidate,
        "verification_source": "remote-provider",
    }


def scm_doctor(project_root: Path) -> dict[str, Any]:
    project = git_common_root(project_root)
    config = project_scm_config(project)
    url = remote_url(project, config["remote"])
    report: dict[str, Any] = {
        "project": str(project),
        "provider": config["provider"],
        "remote": config["remote"],
        "remote_url": url,
        "base_branch": config["base_branch"],
    }
    if config["provider"] == "github":
        owner, repository = infer_github_repository(url)
        auth = run_capture(["gh", "auth", "status", "--hostname", "github.com"], env=github_env(), check=False)
        report.update({
            "repository": f"{owner}/{repository}",
            "auth_ready": auth.returncode == 0,
            "auth_detail": (auth.stdout or auth.stderr).strip(),
        })
    else:
        workspace, repository = infer_bitbucket_repository(url)
        auth_ready = bool(os.environ.get("BITBUCKET_ACCESS_TOKEN") or (
            os.environ.get("BITBUCKET_API_TOKEN") and os.environ.get("BITBUCKET_EMAIL")
        ))
        report.update({"repository": f"{workspace}/{repository}", "auth_ready": auth_ready})
    report["ready"] = bool(report.get("auth_ready"))
    return report
