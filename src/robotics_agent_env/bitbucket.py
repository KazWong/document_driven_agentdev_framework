from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .util import AgentEnvError, git, git_branch
from .workitem import WorkItem


def infer_repository(remote: str) -> tuple[str, str]:
    patterns = [
        r"^git@bitbucket\.org:([^/]+)/(.+?)(?:\.git)?$",
        r"^ssh://git@bitbucket\.org/([^/]+)/(.+?)(?:\.git)?$",
        r"^https?://(?:[^@/]+@)?bitbucket\.org/([^/]+)/(.+?)(?:\.git)?/?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, remote)
        if match:
            return match.group(1), match.group(2).removesuffix(".git")
    raise AgentEnvError(f"cannot infer Bitbucket workspace/repository from remote: {remote}")


def get_origin(repo: Path) -> str:
    completed = git(repo, "remote", "get-url", "origin", check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise AgentEnvError("Git remote 'origin' is not configured")
    return completed.stdout.strip()


def build_pull_request_payload(
    item: WorkItem, *, title: str | None = None, reviewers: list[str] | None = None,
    draft: bool = False, close_source_branch: bool = False,
) -> dict[str, Any]:
    status = item.status
    if status["state"] not in {"PR_READY", "CI_VERIFIED", "MERGE_APPROVED"}:
        raise AgentEnvError(f"pull request preparation requires PR_READY or later, not {status['state']}")
    description_path = item.artifacts_path / "pull-request.md"
    if not description_path.is_file():
        raise AgentEnvError("missing pull-request.md artifact")
    source = status.get("branch") or git_branch(item.repo)
    destination = item.manifest["base_branch"]
    payload: dict[str, Any] = {
        "title": title or f"{item.work_id}: {item.manifest['title']}",
        "summary": {"raw": description_path.read_text(encoding="utf-8")},
        "source": {"branch": {"name": source}},
        "destination": {"branch": {"name": destination}},
        "close_source_branch": close_source_branch,
    }
    if draft:
        payload["draft"] = True
    if reviewers:
        payload["reviewers"] = [{"uuid": value} for value in reviewers]
    return payload


def create_pull_request(item: WorkItem, payload: dict[str, Any]) -> dict[str, Any]:
    if not item.pr_is_approved():
        raise AgentEnvError("pull-request creation requires 'agentctl approve <id> pr'")
    workspace, repository = infer_repository(get_origin(item.repo))
    url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repository}/pullrequests"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": _authorization_header()},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AgentEnvError(f"Bitbucket API rejected the request ({exc.code}): {detail[:2000]}") from exc
    except urllib.error.URLError as exc:
        raise AgentEnvError(f"Bitbucket API request failed: {exc.reason}") from exc
    if not isinstance(data, dict):
        raise AgentEnvError("Bitbucket API returned an unexpected response")
    item.write_artifact("pull-request-created.json", json.dumps(data, indent=2, sort_keys=True))
    return data


def _authorization_header() -> str:
    access_token = os.environ.get("BITBUCKET_ACCESS_TOKEN")
    if access_token:
        return f"Bearer {access_token}"
    api_token = os.environ.get("BITBUCKET_API_TOKEN")
    email = os.environ.get("BITBUCKET_EMAIL")
    if api_token and email:
        encoded = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"
    raise AgentEnvError(
        "set BITBUCKET_ACCESS_TOKEN, or set both BITBUCKET_API_TOKEN and BITBUCKET_EMAIL"
    )
