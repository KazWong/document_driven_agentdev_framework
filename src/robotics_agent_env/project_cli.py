from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .util import AgentEnvError, ensure_within, env_root, workspace_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="projectctl", description="Generate an agent-gated project")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--type", required=True, choices=["c", "cpp", "python", "shell"])
    create.add_argument("--name", required=True)
    create.add_argument("--destination")
    create.add_argument("--no-git", action="store_true")
    create.add_argument("--no-initial-commit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", args.name):
            raise AgentEnvError("project name must be 2-63 lowercase letters, digits, and hyphens")
        destination = Path(args.destination) if args.destination else workspace_root() / "projects" / args.name
        if not destination.is_absolute():
            destination = workspace_root() / destination
        destination = ensure_within(destination, workspace_root(), "project destination")
        if destination.exists():
            raise AgentEnvError(f"destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(env_root() / "templates" / "common", destination)
        shutil.copytree(env_root() / "templates" / args.type, destination, dirs_exist_ok=True)
        module = args.name.replace("-", "_")
        replacements = {
            "__PROJECT_NAME__": args.name,
            "__MODULE_NAME__": module,
            "__HEADER_GUARD__": module.upper(),
        }
        _rename_placeholders(destination, replacements)
        _replace_text(destination, replacements)
        for path in destination.rglob("*.sh"):
            path.chmod(path.stat().st_mode | 0o111)
        for path in destination.glob("bin/*"):
            if path.is_file():
                path.chmod(path.stat().st_mode | 0o111)
        for path in destination.glob("test/*.bats"):
            path.chmod(path.stat().st_mode | 0o111)
        if not args.no_git:
            _run(["git", "init", "-b", "main"], destination)
            _run(["git", "add", "."], destination)
            if not args.no_initial_commit:
                _run([
                    "git", "-c", "user.name=Robotics Project Generator",
                    "-c", "user.email=generator@localhost", "commit", "-m", "chore: initialize project",
                ], destination)
        print(destination)
        return 0
    except AgentEnvError as exc:
        print(f"projectctl: {exc}", file=sys.stderr)
        return 2


def _rename_placeholders(root: Path, replacements: dict[str, str]) -> None:
    paths = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in paths:
        name = path.name
        for source, target in replacements.items():
            name = name.replace(source, target)
        if name != path.name:
            path.rename(path.with_name(name))


def _replace_text(root: Path, replacements: dict[str, str]) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for source, target in replacements.items():
            text = text.replace(source, target)
        path.write_text(text, encoding="utf-8")


def _run(argv: list[str], cwd: Path) -> None:
    try:
        completed = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as exc:
        raise AgentEnvError(f"command not found: {argv[0]}") from exc
    if completed.returncode != 0:
        raise AgentEnvError((completed.stderr or completed.stdout).strip())


if __name__ == "__main__":
    raise SystemExit(main())
