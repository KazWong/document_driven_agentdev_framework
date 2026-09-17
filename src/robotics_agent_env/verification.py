from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .safety import validate_local_command
from .test_registry import TestController
from .util import AgentEnvError, atomic_write_json, atomic_write_text, shell_join, utc_now
from .workitem import WorkItem


def run_local_verification(item: WorkItem) -> dict[str, Any]:
    root = _new_evidence_run(item, "local")
    entries: list[dict[str, Any]] = []
    all_passed = True
    commands = item.manifest["verification"]["local"]
    for index, specification in enumerate(commands, start=1):
        command_id = specification["id"]
        command = validate_local_command(specification["command"], item.repo)
        command_dir = root / f"{index:02d}-{_safe_name(command_id)}"
        command_dir.mkdir()
        atomic_write_text(command_dir / "command.txt", shell_join(command) + "\n")
        started = utc_now()
        env = _verification_environment(item)
        try:
            completed = subprocess.run(
                command, cwd=str(item.repo), env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=float(specification["timeout_seconds"]), check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except FileNotFoundError as exc:
            returncode, stdout, stderr = 127, "", str(exc)
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + "\nTimed out.\n"
        atomic_write_text(command_dir / "stdout.log", stdout)
        atomic_write_text(command_dir / "stderr.log", stderr)
        passed = returncode == 0
        all_passed = all_passed and passed
        result = {
            "id": command_id, "command": command, "returncode": returncode,
            "passed": passed, "started_at": started, "finished_at": utc_now(),
            "stdout_path": str((command_dir / "stdout.log").relative_to(item.path)),
            "stderr_path": str((command_dir / "stderr.log").relative_to(item.path)),
        }
        atomic_write_json(command_dir / "result.json", result)
        entries.append(result)
    summary = {
        "schema_version": 1, "kind": "local", "work_item": item.work_id,
        "passed": all_passed, "commands": entries, "generated_at": utc_now(),
        "not_applicable": len(commands) == 0,
    }
    atomic_write_json(root / "summary.json", summary)
    item.refresh_evidence_index()
    return summary


def run_integration_verification(item: WorkItem) -> dict[str, Any]:
    root = _new_evidence_run(item, "integration")
    entries: list[dict[str, Any]] = []
    all_passed = True
    controller = TestController()
    specifications = item.manifest["verification"]["integration"]
    for index, specification in enumerate(specifications, start=1):
        lane = specification["lane"]
        action = specification["action"]
        lane_dir = root / f"{index:02d}-{_safe_name(lane)}-{_safe_name(action)}"
        lane_dir.mkdir()
        try:
            result = controller.run(
                lane, action,
                item.repo if action in {"test", "sim"} else None,
                specification.get("args", []),
                timeout=float(os.environ.get("AGENT_INTEGRATION_TIMEOUT", "3600")),
            )
            command = result.command
            returncode = result.returncode
            stdout, stderr = result.stdout, result.stderr
        except AgentEnvError as exc:
            command = []
            returncode = 125
            stdout, stderr = "", str(exc)
        atomic_write_text(lane_dir / "command.txt", shell_join(command) + "\n" if command else "")
        atomic_write_text(lane_dir / "stdout.log", stdout)
        atomic_write_text(lane_dir / "stderr.log", stderr)
        passed = returncode == 0
        all_passed = all_passed and passed
        entry = {
            "lane": lane, "action": action, "args": specification.get("args", []),
            "command": command, "returncode": returncode, "passed": passed,
            "stdout_path": str((lane_dir / "stdout.log").relative_to(item.path)),
            "stderr_path": str((lane_dir / "stderr.log").relative_to(item.path)),
        }
        atomic_write_json(lane_dir / "result.json", entry)
        entries.append(entry)
    summary = {
        "schema_version": 1, "kind": "integration", "work_item": item.work_id,
        "passed": all_passed, "lanes": entries, "generated_at": utc_now(),
        "not_applicable": len(specifications) == 0,
    }
    atomic_write_json(root / "summary.json", summary)
    item.refresh_evidence_index()
    return summary


def _new_evidence_run(item: WorkItem, kind: str) -> Path:
    parent = item.path / "evidence" / kind
    parent.mkdir(parents=True, exist_ok=True)
    numbers = [int(path.name) for path in parent.iterdir() if path.is_dir() and path.name.isdigit()]
    root = parent / f"{max(numbers, default=0) + 1:04d}"
    root.mkdir()
    return root


def _verification_environment(item: WorkItem) -> dict[str, str]:
    allowed = {
        key: value for key, value in os.environ.items()
        if key in {"HOME", "LANG", "LC_ALL", "PATH", "TERM", "TMPDIR", "CC", "CXX", "CMAKE_PREFIX_PATH", "PYTHONPATH"}
        or key.startswith("ROS_")
    }
    allowed["AGENT_WORK_ITEM"] = item.work_id
    allowed["AGENT_EVIDENCE_ROOT"] = str(item.path)
    allowed["CI"] = "true"
    return allowed


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in value)[:80]
