from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from robotics_agent_env.util import AgentEnvError
from robotics_agent_env.verification import run_local_verification


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


class CandidateItem:
    def __init__(self, repo: Path, evidence_root: Path, candidate: str) -> None:
        self.work_id = "MODE-001"
        self.repo = repo
        self.path = evidence_root
        self._candidate = candidate
        self.status = {"implementation": {"candidate_sha": candidate}}
        self.manifest = {
            "verification": {
                "local": [
                    {
                        "id": "mode-check",
                        "command": ["python3", "scripts/check_mode.py"],
                        "timeout_seconds": 30,
                    }
                ]
            }
        }
        self.path.mkdir(parents=True, exist_ok=True)

    def assert_candidate_unchanged(self) -> str:
        assert _git(self.repo, "rev-parse", "HEAD") == self._candidate
        assert _git(self.repo, "status", "--porcelain") == ""
        return self._candidate

    def refresh_evidence_index(self) -> None:
        return None


def _make_mode_mismatched_candidate(root: Path) -> tuple[Path, str, Path]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "mode@example.invalid")
    _git(repo, "config", "user.name", "Mode Test")
    scripts = repo / "scripts"
    scripts.mkdir()
    checker = scripts / "check_mode.py"
    checker.write_text(
        "import os, pathlib, stat, sys\n"
        "path = pathlib.Path(__file__)\n"
        "mode = stat.S_IMODE(path.stat().st_mode)\n"
        "sys.exit(0 if not (mode & 0o111) else 23)\n",
        encoding="utf-8",
    )
    checker.chmod(0o644)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "candidate")
    candidate = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "ls-files", "-s", "scripts/check_mode.py").startswith("100644 ")

    # Reproduce the acceptance failure: the backing filesystem presents a
    # Git-100644 Python file as executable while Git ignores the mode mismatch.
    _git(repo, "config", "core.fileMode", "false")
    checker.chmod(0o770)
    assert stat.S_IMODE(checker.stat().st_mode) == 0o770
    assert _git(repo, "status", "--porcelain") == ""
    return repo, candidate, checker


def test_local_verification_materializes_candidate_modes_on_native_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, candidate, source_checker = _make_mode_mismatched_candidate(tmp_path)
    evidence = tmp_path / "work-item"
    verifier_root = tmp_path / "verifier"
    monkeypatch.setenv("AGENT_VERIFIER_ROOT", str(verifier_root))
    item = CandidateItem(repo, evidence, candidate)

    summary = run_local_verification(item)

    assert summary["passed"] is True
    assert summary["candidate_sha"] == candidate
    assert summary["verification_source"] == "detached-candidate-checkout"
    assert summary["commands"][0]["returncode"] == 0
    assert stat.S_IMODE(source_checker.stat().st_mode) == 0o770
    assert list(verifier_root.iterdir()) == []

    recorded = json.loads((evidence / "evidence/local/0001/summary.json").read_text(encoding="utf-8"))
    assert recorded["candidate_sha"] == candidate
    assert recorded["verification_source"] == "detached-candidate-checkout"


def test_local_verification_records_mode_preservation_setup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, candidate, _ = _make_mode_mismatched_candidate(tmp_path)
    evidence = tmp_path / "work-item"
    monkeypatch.setenv("AGENT_VERIFIER_ROOT", str(tmp_path / "verifier"))
    item = CandidateItem(repo, evidence, candidate)

    import robotics_agent_env.verification as verification

    def fail_modes(root: Path) -> None:
        raise AgentEnvError(f"mode preservation unavailable at {root}")

    monkeypatch.setattr(verification, "_assert_mode_preserving_filesystem", fail_modes)
    summary = run_local_verification(item)

    assert summary["passed"] is False
    assert summary["candidate_sha"] == candidate
    assert summary["commands"][0]["id"] == "candidate-checkout"
    assert summary["commands"][0]["returncode"] == 125
    stderr_path = evidence / summary["commands"][0]["stderr_path"]
    assert "mode preservation unavailable" in stderr_path.read_text(encoding="utf-8")


def test_candidate_checkout_recreates_git_executable_bit_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "mode@example.invalid")
    _git(repo, "config", "user.name", "Mode Test")
    script = repo / "tool.py"
    script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    script.chmod(0o755)
    _git(repo, "add", "tool.py")
    _git(repo, "commit", "-qm", "executable")
    candidate = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "ls-files", "-s", "tool.py").startswith("100755 ")

    # The source representation is deliberately wrong in the opposite direction.
    _git(repo, "config", "core.fileMode", "false")
    script.chmod(0o660)
    assert not (stat.S_IMODE(script.stat().st_mode) & 0o111)

    import robotics_agent_env.verification as verification

    monkeypatch.setenv("AGENT_VERIFIER_ROOT", str(tmp_path / "verifier"))
    verification._assert_mode_preserving_filesystem(verification._verifier_root())
    checkout = tmp_path / "manual-checkout"
    verification._clone_candidate_checkout(repo, checkout, candidate)
    verification._assert_checkout_modes(checkout)
    assert stat.S_IMODE((checkout / "tool.py").stat().st_mode) & 0o111


def test_local_verification_clones_exact_candidate_from_linked_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "mode@example.invalid")
    _git(main, "config", "user.name", "Mode Test")
    (main / "README.md").write_text("base\n", encoding="utf-8")
    _git(main, "add", ".")
    _git(main, "commit", "-qm", "base")

    worktree = tmp_path / "linked-worktree"
    _git(main, "worktree", "add", "-q", "-b", "agent/mode-001", str(worktree))
    scripts = worktree / "scripts"
    scripts.mkdir()
    checker = scripts / "check_mode.py"
    checker.write_text(
        "import pathlib, stat, sys\n"
        "mode = stat.S_IMODE(pathlib.Path(__file__).stat().st_mode)\n"
        "sys.exit(0 if not (mode & 0o111) else 23)\n",
        encoding="utf-8",
    )
    checker.chmod(0o644)
    _git(worktree, "add", "scripts/check_mode.py")
    _git(worktree, "commit", "-qm", "candidate")
    candidate = _git(worktree, "rev-parse", "HEAD")

    _git(worktree, "config", "core.fileMode", "false")
    checker.chmod(0o770)
    assert _git(worktree, "status", "--porcelain") == ""

    evidence = tmp_path / "work-item"
    monkeypatch.setenv("AGENT_VERIFIER_ROOT", str(tmp_path / "verifier"))
    item = CandidateItem(worktree, evidence, candidate)
    summary = run_local_verification(item)

    assert summary["passed"] is True
    assert summary["candidate_sha"] == candidate
    assert summary["verification_source"] == "detached-candidate-checkout"
