"""Trusted Git operations; role snapshots contain neither Git nor controller data."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

from .common import (
    Conflict,
    FrameworkError,
    atomic_write,
    bytes_digest,
    contained,
    safe_relative,
    sha,
)
from .execution import ProcessExecutor
from .policy import in_scope


class Repository:
    def __init__(self, path: Path, executor: ProcessExecutor | None = None):
        self.path = Path(path).resolve()
        self.executor = executor or ProcessExecutor()
        root = self.git("rev-parse", "--show-toplevel").strip()
        if Path(root).resolve() != self.path:
            raise FrameworkError("project must name the Git repository root")

    def git(self, *args: str, timeout: int = 60) -> str:
        result = self.executor.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                *args,
            ],
            cwd=self.path,
            timeout=timeout,
            env={**{k: os.environ[k] for k in ('SSH_AUTH_SOCK', 'SSH_AGENT_PID') if k in os.environ},
                 'GIT_LITERAL_PATHSPECS': '1', 'GIT_TERMINAL_PROMPT': '0',
                 'GCM_INTERACTIVE': 'never'},
        )
        if result.returncode or result.timed_out or result.output_limited:
            raise FrameworkError("Git operation failed: " + result.stderr[:600])
        return result.stdout

    @property
    def head(self) -> str:
        return sha(self.git("rev-parse", "HEAD").strip())

    def branch(self) -> str:
        return self.git("symbolic-ref", "--quiet", "--short", "HEAD").strip()

    def clean(self) -> bool:
        return not self.git("status", "--porcelain", "--untracked-files=all").strip()

    def files(self, commit: str) -> dict[str, tuple[str, str]]:
        sha(commit)
        records = self.git("ls-tree", "-r", "-z", commit).split("\0")
        result = {}
        for line in filter(None, records):
            info, path = line.split("\t", 1)
            mode, kind, oid = info.split()
            safe_relative(path)
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise FrameworkError(
                    "candidate contains a symlink, submodule or unsupported object: "
                    + path
                )
            result[path] = (mode, oid)
        return result

    def diff(self, before: str, after: str) -> list[str]:
        sha(before)
        sha(after)
        return sorted(
            filter(
                None,
                self.git(
                    "diff", "--no-renames", "--name-only", "-z", before, after, "--"
                ).split("\0"),
            )
        )

    def snapshot(
        self, commit: str, destination: Path, *, hidden: set[str] | None = None
    ) -> dict[str, str]:
        """Stream exact blobs through cat-file, avoiding tar path/link extraction."""
        hidden = hidden or set()
        files = self.files(commit)
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            raise FrameworkError("snapshot destination must be empty")
        inventory = {}
        for path, (mode, oid) in files.items():
            if (
                path in hidden
                or path.startswith(
                    (
                        ".agent/runtime/",
                        ".agent/knowledge/",
                        ".agent/work-items/",
                        ".agent-context/",
                    )
                )
                or path == ".env"
                or path.startswith(".env.")
            ):
                continue
            # No shell, user configuration or checkout filters participate.
            out = contained(destination, path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("xb") as handle:
                result = subprocess.run(
                    ["git", "cat-file", "blob", oid],
                    cwd=self.path,
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    timeout=60,
                    env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                )
            if result.returncode:
                raise FrameworkError("cannot materialize exact candidate blob")
            out.chmod(0o755 if mode == "100755" else 0o644)
            inventory[path] = bytes_digest(out.read_bytes())
        return inventory

    def candidate(
        self,
        base: str,
        expected_head: str,
        scope: dict[str, list[str]],
        protected: dict[str, str],
        message: str,
        validate_tree: Any = None,
    ) -> str:
        sha(base)
        sha(expected_head)
        if self.head != expected_head:
            raise Conflict("checkout HEAD changed")
        branch = self.branch()
        if branch in {"main", "master", "develop", "release"} or not branch.startswith(
            "agent/"
        ):
            raise FrameworkError(
                "candidate commits require an isolated agent/ feature branch"
            )
        changed = set(
            filter(
                None, self.git("diff", "--name-only", "-z", "HEAD", "--").split("\0")
            )
        )
        changed |= set(
            filter(
                None,
                self.git("ls-files", "--others", "--exclude-standard", "-z").split(
                    "\0"
                ),
            )
        )
        if not changed:
            raise FrameworkError("a candidate requires a nonempty source change")
        for path in sorted(changed):
            if not in_scope(path, scope):
                raise FrameworkError("changed path is outside approved scope: " + path)
            contained(self.path, path)
            if path in protected:
                f = self.path / path
                if not f.is_file() or bytes_digest(f.read_bytes()) != protected[path]:
                    raise FrameworkError("Coder changed a Tester-owned file: " + path)
        self.git("diff", "--check", "HEAD", "--")
        # Stage only the reviewed paths; an externally staged path is already in changed.
        self.git("add", "--all", "--", *sorted(changed))
        tree = sha(self.git("write-tree").strip())
        self.files(tree)
        if not self.diff(base, tree):
            raise FrameworkError('candidate has no change relative to its work-item baseline')
        if validate_tree:
            validate_tree(tree)
        if self.head != expected_head:
            raise Conflict("checkout HEAD changed before commit")
        self.git(
            "-c",
            "user.name=Framework Controller",
            "-c",
            "user.email=controller@localhost",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            message,
        )
        result = self.head
        if not self.diff(base, result):
            raise FrameworkError(
                "candidate has no change relative to its work-item baseline"
            )
        return result


def validate_trace(
    repo: Repository,
    base: str,
    candidate: str,
    trace: dict[str, Any],
    bp: dict[str, Any],
    plan: dict[str, Any],
    package_ref: dict[str, Any],
) -> None:
    from .contracts import validate

    validate("ImplementationTrace", trace)
    if (
        trace["candidate_sha"] != candidate
        or trace["package_ref"] != package_ref
        or trace["incomplete_obligations"]
    ):
        raise FrameworkError(
            "implementation trace is incomplete or bound to a different candidate/package"
        )
    changes = trace["changes"]
    paths = [x["path"] for x in changes]
    actual = repo.diff(base, candidate)
    if len(paths) != len(set(paths)) or set(paths) != set(actual) or not actual:
        raise FrameworkError(
            "implementation trace must cover the exact nonempty Git diff"
        )
    validate_changes(changes, actual, plan)


def validate_changes(changes, actual, plan):
    """Validate a role delta before copying it into the trusted worktree."""
    paths = [x['path'] for x in changes]
    if len(paths) != len(set(paths)) or set(paths) != set(actual):
        raise FrameworkError('implementation trace must cover exactly the changed paths')
    tasks = {x["id"]: x for x in plan["tasks"]}
    for change in changes:
        if not in_scope(change["path"], plan["scope"]):
            raise FrameworkError("diff leaves the approved scope")
        allowed_requirements = set()
        allowed_design = set()
        for task_id in change["task_ids"]:
            task = tasks.get(task_id)
            if not task or not in_scope(
                change["path"], {"include": task["paths"], "exclude": []}
            ):
                raise FrameworkError(
                    "trace path does not implement its cited Plan task"
                )
            allowed_requirements.update(task["requirements"])
            allowed_design.update(task["design"])
        if not set(change["requirement_ids"]) <= allowed_requirements or not set(
            change["design_ids"]
        ) <= allowed_design:
            raise FrameworkError(
                "trace requirement/design mapping contradicts the Plan"
            )
