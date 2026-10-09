"""Explicit GitHub delivery adapter. No role can call this trusted boundary."""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
from typing import Any

from .common import Conflict, FrameworkError, decode, sha
from .execution import ProcessExecutor
from .scm import Repository


class GitHubDelivery:
    def __init__(self, repo: Repository, executor: ProcessExecutor | None = None):
        self.repo = repo
        self.executor = executor or ProcessExecutor()

    def _gh(self, *argv: str) -> Any:
        result = self.executor.run(["gh", *argv], cwd=self.repo.path, timeout=120)
        if result.returncode or result.timed_out or result.output_limited:
            raise FrameworkError("GitHub operation failed: " + result.stderr[:500])
        return result.stdout

    def head(self, branch: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", branch) or ".." in branch:
            raise FrameworkError("invalid remote branch name")
        value = self.repo.git("ls-remote", "--heads", "origin", "refs/heads/" + branch)
        rows = value.strip().splitlines()
        if len(rows) != 1:
            raise Conflict("remote branch head is unavailable or ambiguous")
        return sha(rows[0].split()[0])

    def publish(
        self, candidate: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        if (
            self.repo.head != candidate
            or not self.repo.clean()
            or not self.repo.branch().startswith("agent/")
        ):
            raise Conflict(
                "pull request must publish the exact clean feature-branch candidate"
            )
        # No force, implicit add, commit, merge, rebase or branch reset.
        self.repo.git(
            "push",
            "origin",
            candidate + ":refs/heads/" + self.repo.branch(),
            timeout=120,
        )
        if self.head(self.repo.branch()) != candidate:
            raise Conflict("remote feature branch changed during publication")
        with tempfile.TemporaryDirectory(prefix="pr-body-") as tmp:
            path = Path(tmp) / "body.txt"
            path.write_text(body)
            self._gh(
                "pr",
                "create",
                "--base",
                base,
                "--head",
                self.repo.branch(),
                "--title",
                title,
                "--body-file",
                str(path),
            )
        value = decode(
            self._gh(
                "pr",
                "view",
                self.repo.branch(),
                "--json",
                "number,url,headRefOid,headRefName,baseRefName",
            )
        )
        if value["headRefOid"] != candidate or value["baseRefName"] != base:
            raise Conflict(
                "created pull request differs from the approved candidate/base"
            )
        return value

    def ci(
        self, pr: dict[str, Any], candidate: str, required: list[str]
    ) -> dict[str, Any]:
        value = decode(
            self._gh(
                "pr",
                "view",
                str(pr["number"]),
                "--json",
                "headRefOid,baseRefName,statusCheckRollup,state",
            )
        )
        if (
            value["headRefOid"] != candidate
            or value["baseRefName"] != pr["baseRefName"]
            or value["state"] != "OPEN"
        ):
            raise Conflict("remote pull request moved or closed")
        checks = {}
        for check in value["statusCheckRollup"] or []:
            name = check.get("name", check.get("context"))
            passed = (
                check.get("conclusion") == "SUCCESS"
                and check.get("status") == "COMPLETED"
                or check.get("state") == "SUCCESS"
            )
            # Duplicate names are ambiguous rather than silently overwritten.
            if name in checks:
                raise Conflict("ambiguous duplicate CI check name")
            checks[name] = passed
        if not required or any(not checks.get(name, False) for name in required):
            raise Conflict("required exact-head CI checks have not passed")
        return {
            "candidate_sha": candidate,
            "required": required,
            "checks": value["statusCheckRollup"],
            "provider": "github",
        }

    def promote(
        self, pr: dict[str, Any], candidate: str, required: list[str]
    ) -> dict[str, Any]:
        self.ci(pr, candidate, required)
        # A new merge result would have an untested tree. Fast-forward only to the
        # accepted SHA; server branch rules can refuse this, with no bypass.
        base = pr["baseRefName"]
        self.repo.git("push", "origin", candidate + ":refs/heads/" + base, timeout=120)
        if self.head(base) != candidate:
            raise Conflict(
                "remote changed after promotion; inspect remote state before retrying"
            )
        return {
            "candidate_sha": candidate,
            "base": base,
            "method": "verified_fast_forward",
            "remote_head": candidate,
        }
