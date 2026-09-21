from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import shutil
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .safety import validate_local_command
from .test_registry import TestController
from .util import AgentEnvError, atomic_write_json, atomic_write_text, git_sha, shell_join, utc_now
from .workitem import WorkItem


LOCAL_VERIFIER_ROOT = Path("/tmp/robotics-agent-verifier")


def run_local_verification(item: WorkItem) -> dict[str, Any]:
    root = _new_evidence_run(item, "local")
    try:
        with _local_verification_checkout(item) as checkout:
            return _run_local_commands(item, root, checkout)
    except AgentEnvError as exc:
        return _record_local_setup_failure(item, root, str(exc))


def _run_local_commands(item: WorkItem, root: Path, checkout: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    all_passed = True
    commands = item.manifest["verification"]["local"]
    verification_repo = Path(checkout["repo"])
    for index, specification in enumerate(commands, start=1):
        command_id = specification["id"]
        command = validate_local_command(specification["command"], verification_repo)
        command_dir = root / f"{index:02d}-{_safe_name(command_id)}"
        command_dir.mkdir()
        atomic_write_text(command_dir / "command.txt", shell_join(command) + "\n")
        started = utc_now()
        env = _verification_environment(item)
        try:
            completed = subprocess.run(
                command, cwd=str(verification_repo), env=env, text=True,
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
            "id": command_id,
            "command": command,
            "declared_command": specification["command"],
            "cwd": str(verification_repo),
            "returncode": returncode,
            "passed": passed,
            "started_at": started,
            "finished_at": utc_now(),
            "stdout_path": str((command_dir / "stdout.log").relative_to(item.path)),
            "stderr_path": str((command_dir / "stderr.log").relative_to(item.path)),
        }
        atomic_write_json(command_dir / "result.json", result)
        entries.append(result)
    summary = {
        "schema_version": 1,
        "kind": "local",
        "work_item": item.work_id,
        "candidate_sha": checkout.get("candidate_sha"),
        "verification_source": checkout["source"],
        "passed": all_passed,
        "commands": entries,
        "generated_at": utc_now(),
        "not_applicable": len(commands) == 0,
    }
    atomic_write_json(root / "summary.json", summary)
    item.refresh_evidence_index()
    return summary


@contextmanager
def _local_verification_checkout(item: WorkItem) -> Iterator[dict[str, Any]]:
    """Yield the repository used for deterministic local verification.

    Current v2.0.2 work items expose ``assert_candidate_unchanged`` after the
    framework-created candidate commit. Those candidates are verified from a
    detached checkout under a mode-preserving container-local filesystem so a
    host/FUSE mount cannot rewrite executable bits. Older work-item objects are
    kept on their historical live-worktree behavior for migration compatibility.
    """
    assert_candidate = getattr(item, "assert_candidate_unchanged", None)
    if not callable(assert_candidate):
        yield {
            "repo": str(item.repo),
            "candidate_sha": None,
            "source": "legacy-worktree",
        }
        return

    candidate = str(assert_candidate())
    verifier_root = _verifier_root()
    _assert_mode_preserving_filesystem(verifier_root)

    prefix = f"{_safe_name(item.work_id)}-{candidate[:12]}-"
    with tempfile.TemporaryDirectory(prefix=prefix, dir=str(verifier_root)) as temp_dir:
        checkout = Path(temp_dir) / "repo"
        _clone_candidate_checkout(item.repo, checkout, candidate)
        _assert_checkout_modes(checkout)
        yield {
            "repo": str(checkout),
            "candidate_sha": candidate,
            "source": "detached-candidate-checkout",
        }


def _verifier_root() -> Path:
    configured = os.environ.get("AGENT_VERIFIER_ROOT")
    root = Path(configured).expanduser() if configured else LOCAL_VERIFIER_ROOT
    try:
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise AgentEnvError(f"cannot prepare local verifier root {root}: {exc}") from exc
    if not root.is_dir():
        raise AgentEnvError(f"local verifier root is not a directory: {root}")
    return root


def _assert_mode_preserving_filesystem(root: Path) -> None:
    """Fail closed unless chmod/readback semantics preserve Unix mode bits."""
    probe_fd: int | None = None
    probe_path: Path | None = None
    try:
        probe_fd, raw_path = tempfile.mkstemp(prefix=".mode-probe-", dir=str(root))
        probe_path = Path(raw_path)
        os.close(probe_fd)
        probe_fd = None
        for expected in (0o644, 0o755):
            os.chmod(probe_path, expected)
            actual = stat.S_IMODE(probe_path.stat().st_mode)
            if actual != expected:
                raise AgentEnvError(
                    f"local verifier filesystem does not preserve Unix modes: "
                    f"chmod {expected:o} read back as {actual:o} under {root}"
                )
    except AgentEnvError:
        raise
    except OSError as exc:
        raise AgentEnvError(f"cannot validate local verifier filesystem modes under {root}: {exc}") from exc
    finally:
        if probe_fd is not None:
            os.close(probe_fd)
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                pass


def _clone_candidate_checkout(source_repo: Path, checkout: Path, candidate: str) -> None:
    clone = subprocess.run(
        [
            "git", "-c", "core.hooksPath=/dev/null", "clone",
            "--quiet", "--no-local", "--no-checkout", str(source_repo), str(checkout),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if clone.returncode != 0:
        detail = clone.stderr.strip() or clone.stdout.strip()
        raise AgentEnvError(f"cannot create detached candidate verifier checkout: {detail}")

    resolved = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--verify", f"{candidate}^{{commit}}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != candidate:
        detail = resolved.stderr.strip() or resolved.stdout.strip()
        raise AgentEnvError(
            f"candidate commit {candidate} is unavailable in verifier checkout"
            + (f": {detail}" if detail else "")
        )

    configured = subprocess.run(
        ["git", "-C", str(checkout), "config", "core.fileMode", "true"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if configured.returncode != 0:
        detail = configured.stderr.strip() or configured.stdout.strip()
        raise AgentEnvError(f"cannot enable file-mode verification in candidate checkout: {detail}")

    checked_out = subprocess.run(
        [
            "git", "-c", "core.hooksPath=/dev/null", "-C", str(checkout),
            "checkout", "--quiet", "--detach", "--force", candidate,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if checked_out.returncode != 0:
        detail = checked_out.stderr.strip() or checked_out.stdout.strip()
        raise AgentEnvError(f"cannot materialize candidate {candidate}: {detail}")

    actual = git_sha(checkout)
    if actual != candidate:
        raise AgentEnvError(f"verifier checkout HEAD {actual} differs from candidate {candidate}")


def _assert_checkout_modes(checkout: Path) -> None:
    listing = subprocess.run(
        ["git", "-C", str(checkout), "ls-files", "-s", "-z"],
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listing.returncode != 0:
        detail = listing.stderr.decode("utf-8", errors="replace").strip()
        raise AgentEnvError(f"cannot inspect candidate checkout file modes: {detail}")

    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        if not separator:
            raise AgentEnvError("cannot parse candidate checkout index mode record")
        fields = metadata.split()
        if not fields:
            raise AgentEnvError("candidate checkout index record is missing a mode")
        mode = fields[0].decode("ascii", errors="strict")
        if mode not in {"100644", "100755"}:
            continue
        path = checkout / raw_path.decode("utf-8", errors="surrogateescape")
        try:
            actual = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            raise AgentEnvError(f"cannot inspect checked-out mode for {path}: {exc}") from exc
        executable = bool(actual & 0o111)
        expected_executable = mode == "100755"
        if executable != expected_executable:
            expectation = "executable" if expected_executable else "non-executable"
            raise AgentEnvError(
                f"candidate checkout mode mismatch for {path.relative_to(checkout)}: "
                f"Git mode {mode} requires {expectation}, filesystem mode is {actual:o}"
            )


def _record_local_setup_failure(item: WorkItem, root: Path, message: str) -> dict[str, Any]:
    command_dir = root / "00-candidate-checkout"
    command_dir.mkdir(exist_ok=True)
    atomic_write_text(command_dir / "command.txt", "")
    atomic_write_text(command_dir / "stdout.log", "")
    atomic_write_text(command_dir / "stderr.log", message + "\n")
    result = {
        "id": "candidate-checkout",
        "command": [],
        "returncode": 125,
        "passed": False,
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "stdout_path": str((command_dir / "stdout.log").relative_to(item.path)),
        "stderr_path": str((command_dir / "stderr.log").relative_to(item.path)),
    }
    atomic_write_json(command_dir / "result.json", result)

    implementation = item.status.get("implementation") if isinstance(item.status, dict) else None
    candidate = implementation.get("candidate_sha") if isinstance(implementation, dict) else None
    summary = {
        "schema_version": 1,
        "kind": "local",
        "work_item": item.work_id,
        "candidate_sha": candidate,
        "verification_source": "detached-candidate-checkout",
        "passed": False,
        "commands": [result],
        "generated_at": utc_now(),
        "not_applicable": False,
    }
    atomic_write_json(root / "summary.json", summary)
    item.refresh_evidence_index()
    return summary


def run_integration_verification(item: WorkItem) -> dict[str, Any]:
    root = _new_evidence_run(item, "integration")
    candidate = item.assert_candidate_unchanged()
    specifications = item.manifest["verification"]["integration"]
    if not specifications:
        summary = {
            "schema_version": 1, "kind": "integration", "work_item": item.work_id,
            "candidate_sha": candidate, "verification_source": "detached-candidate-checkout",
            "passed": True, "lanes": [], "generated_at": utc_now(), "not_applicable": True,
        }
        atomic_write_json(root / "summary.json", summary)
        item.refresh_evidence_index()
        return summary

    try:
        with _integration_verification_checkout(item, candidate) as checkout:
            return _run_integration_lanes(item, root, Path(checkout), candidate, specifications)
    except AgentEnvError as exc:
        lane_dir = root / "00-candidate-checkout"
        lane_dir.mkdir(exist_ok=True)
        atomic_write_text(lane_dir / "stderr.log", str(exc) + "\n")
        entry = {
            "lane": "candidate-checkout", "action": "prepare", "args": [], "command": [],
            "returncode": 125, "passed": False, "test_count": None,
            "stdout_path": None,
            "stderr_path": str((lane_dir / "stderr.log").relative_to(item.path)),
        }
        summary = {
            "schema_version": 1, "kind": "integration", "work_item": item.work_id,
            "candidate_sha": candidate, "verification_source": "detached-candidate-checkout",
            "passed": False, "lanes": [entry], "generated_at": utc_now(), "not_applicable": False,
        }
        atomic_write_json(root / "summary.json", summary)
        item.refresh_evidence_index()
        return summary


def _run_integration_lanes(
    item: WorkItem, root: Path, checkout: Path, candidate: str,
    specifications: list[dict[str, Any]],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    all_passed = True
    controller = TestController()
    for index, specification in enumerate(specifications, start=1):
        lane = specification["lane"]
        action = specification["action"]
        lane_dir = root / f"{index:02d}-{_safe_name(lane)}-{_safe_name(action)}"
        lane_dir.mkdir()
        try:
            result = controller.run(
                lane, action, checkout if action in {"test", "sim"} else None,
                specification.get("args", []),
                timeout=float(os.environ.get("AGENT_INTEGRATION_TIMEOUT", "3600")),
            )
            command = result.command
            returncode = result.returncode
            stdout, stderr = result.stdout, result.stderr
        except AgentEnvError as exc:
            command, returncode, stdout, stderr = [], 125, "", str(exc)
        atomic_write_text(lane_dir / "command.txt", shell_join(command) + "\n" if command else "")
        atomic_write_text(lane_dir / "stdout.log", stdout)
        atomic_write_text(lane_dir / "stderr.log", stderr)

        external_result = _capture_external_results(checkout, lane, lane_dir)
        test_count: int | None = None
        evidence_reason: str | None = None
        if action == "test" and lane == "ros2-humble":
            test_count = _count_ros2_tests(external_result, stdout, stderr)
            if returncode == 0 and (test_count is None or test_count <= 0):
                evidence_reason = "required ros2-humble test lane did not establish a positive executed-test count"
                returncode = 125
                stderr = (stderr.rstrip() + "\n" + evidence_reason + "\n").lstrip("\n")
                atomic_write_text(lane_dir / "stderr.log", stderr)
        passed = returncode == 0
        all_passed = all_passed and passed
        entry = {
            "lane": lane, "action": action, "args": specification.get("args", []),
            "command": command, "returncode": returncode, "passed": passed,
            "test_count": test_count, "candidate_sha": candidate,
            "verification_source": "detached-candidate-checkout",
            "external_results_path": str(external_result.relative_to(item.path)) if external_result else None,
            "reason": evidence_reason,
            "stdout_path": str((lane_dir / "stdout.log").relative_to(item.path)),
            "stderr_path": str((lane_dir / "stderr.log").relative_to(item.path)),
        }
        atomic_write_json(lane_dir / "result.json", entry)
        entries.append(entry)
    summary = {
        "schema_version": 1, "kind": "integration", "work_item": item.work_id,
        "candidate_sha": candidate, "verification_source": "detached-candidate-checkout",
        "passed": all_passed, "lanes": entries, "generated_at": utc_now(),
        "not_applicable": False,
    }
    atomic_write_json(root / "summary.json", summary)
    item.refresh_evidence_index()
    return summary


@contextmanager
def _integration_verification_checkout(item: WorkItem, candidate: str) -> Iterator[str]:
    base = item.state_root / "verifiers" / "integration" / item.project_root.name / item.work_id
    base.mkdir(parents=True, exist_ok=True)
    checkout = base / candidate
    if checkout.exists():
        shutil.rmtree(checkout)
    _clone_candidate_checkout(item.project_root, checkout, candidate)
    try:
        yield str(checkout)
    finally:
        shutil.rmtree(checkout, ignore_errors=True)
        # Empty parents are disposable; never remove .agent-state/verifiers itself.
        for parent in (base, base.parent):
            try:
                parent.rmdir()
            except OSError:
                pass


def _capture_external_results(checkout: Path, lane: str, lane_dir: Path) -> Path | None:
    source = checkout / ".test-results" / lane / "latest"
    if not source.is_dir():
        return None
    destination = lane_dir / "external-results"
    shutil.copytree(source, destination, symlinks=False)
    return destination


def _count_ros2_tests(external_result: Path | None, stdout: str, stderr: str) -> int | None:
    """Return a machine-evidenced executed-test count for ros2-humble.

    JUnit is authoritative when present. A machine-readable summary with an
    explicit count is accepted as a secondary source. Text output is used only
    to recognize an explicit zero-test failure; it never establishes success.
    """
    if external_result is not None:
        junit = external_result / "junit"
        if junit.is_dir():
            count = 0
            xml_seen = False
            for path in junit.rglob("*.xml"):
                try:
                    root = ET.parse(path).getroot()
                except (ET.ParseError, OSError):
                    continue
                xml_seen = True
                if root.tag == "testcase":
                    count += 1
                else:
                    count += sum(1 for _ in root.iter("testcase"))
            if xml_seen:
                return count
        summary_path = external_result / "summary.json"
        if summary_path.is_file():
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            for key in ("test_count", "tests", "tests_run", "total_tests"):
                value = data.get(key) if isinstance(data, dict) else None
                if isinstance(value, int) and value >= 0:
                    return value
    combined = stdout + "\n" + stderr
    if "Summary: 0 tests" in combined or "Ran 0 tests" in combined:
        return 0
    return None

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
