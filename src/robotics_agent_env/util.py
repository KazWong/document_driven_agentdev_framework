from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import yaml

from .constants import STATE_DIR_NAME, WORKSPACE_DEFAULT


class AgentEnvError(RuntimeError):
    """Expected user-facing failure."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def env_root() -> Path:
    configured = os.environ.get("ROBOTICS_AGENT_ENV_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    return Path(os.environ.get("AGENT_WORKSPACE_ROOT", WORKSPACE_DEFAULT)).expanduser().resolve()


def state_root() -> Path:
    return Path(os.environ.get("AGENT_STATE_ROOT", str(workspace_root() / STATE_DIR_NAME))).expanduser().resolve()


def ensure_within(path: Path, root: Path, label: str = "path") -> Path:
    resolved = path.expanduser().resolve()
    root_resolved = root.expanduser().resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise AgentEnvError(f"{label} must remain under {root_resolved}: {resolved}") from exc
    return resolved


def resolve_workspace_path(value: str | os.PathLike[str]) -> Path:
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else workspace_root() / raw
    return ensure_within(candidate, workspace_root(), "workspace path")


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AgentEnvError(f"file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise AgentEnvError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentEnvError(f"expected a YAML mapping in {path}")
    return data


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AgentEnvError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AgentEnvError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentEnvError(f"expected a JSON object in {path}")
    return value


def atomic_write_text(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temp_path.chmod(mode)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def slugify(value: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "work-item")[:max_length].rstrip("-")


def run_capture(
    argv: Sequence[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
    timeout: float | None = None, stdin_text: str | None = None, check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(argv), cwd=str(cwd) if cwd else None, env=env, input=stdin_text,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise AgentEnvError(f"command not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AgentEnvError(f"command timed out after {timeout}s: {shell_join(argv)}") from exc
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise AgentEnvError(f"command failed ({completed.returncode}): {shell_join(argv)}" + (f"\n{detail}" if detail else ""))
    return completed


def shell_join(argv: Iterable[str]) -> str:
    return shlex.join(list(argv))


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_capture(["git", "-C", str(repo), *args], check=check)


def git_root(path: Path) -> Path:
    completed = git(path, "rev-parse", "--show-toplevel", check=False)
    if completed.returncode != 0:
        raise AgentEnvError(f"not a Git repository: {path}")
    return Path(completed.stdout.strip()).resolve()


def git_branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current", check=True).stdout.strip()


def git_sha(repo: Path, ref: str = "HEAD") -> str | None:
    completed = git(repo, "rev-parse", ref, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_changed_paths(repo: Path, baseline: str | None = None) -> list[str]:
    """Return committed and uncommitted paths changed from an optional baseline."""
    paths: set[str] = set()
    completed = git(repo, "status", "--porcelain=v1", "-z", check=True)
    entries = completed.stdout.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        path = entry[3:]
        if status and (status[0] in {"R", "C"} or status[1] in {"R", "C"}) and index < len(entries):
            # Porcelain -z emits the destination followed by the source for renames/copies.
            paths.add(path)
            paths.add(entries[index])
            index += 1
        else:
            paths.add(path)
    if baseline:
        diff = git(repo, "diff", "--name-only", "-z", baseline, "HEAD", "--", check=False)
        if diff.returncode != 0:
            detail = diff.stderr.strip() or diff.stdout.strip()
            raise AgentEnvError(f"cannot compare worktree against baseline {baseline}: {detail}")
        paths.update(path for path in diff.stdout.split("\0") if path)
    return sorted(paths)


def safe_actor(explicit: str | None = None) -> str:
    actor = explicit or os.environ.get("AGENT_APPROVER") or os.environ.get("USER") or "unknown"
    actor = actor.strip()
    if not actor or not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", actor):
        raise AgentEnvError("approver identity contains unsupported characters")
    return actor


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def interpolate(value: str, variables: dict[str, str]) -> str:
    result = value
    for key, replacement in variables.items():
        result = result.replace(f"${{{key}}}", replacement)
    unresolved = re.findall(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", result)
    if unresolved:
        raise AgentEnvError(f"unresolved variables: {', '.join(unresolved)}")
    return result


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None
