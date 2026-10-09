from pathlib import Path
import json
import os
import sys

import pytest

from agent_framework.common import FrameworkError, LeaseRetained
from agent_framework.docker_backend import DockerBackend
from agent_framework.execution import ExecutionRequest, ProcessExecutor, ProcessResult


def test_process_executor_handles_stdin_and_real_exit_status():
    value = ProcessExecutor().run(
        [
            sys.executable,
            "-c",
            "import sys; print(sys.stdin.read().upper()); sys.exit(7)",
        ],
        stdin=b"bounded input",
    )
    assert value.returncode == 7 and value.stdout.strip() == "BOUNDED INPUT"


def test_process_executor_does_not_inherit_undeclared_secrets(monkeypatch):
    monkeypatch.setenv("PRIVATE_SECRET", "must-not-appear")
    result = ProcessExecutor().run(
        [sys.executable, "-c", "import os;print(os.getenv('PRIVATE_SECRET'))"]
    )
    assert result.stdout.strip() == "None"


def test_timeout_kills_descendants(tmp_path):
    marker = tmp_path / "orphan-write"
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(10)"
    child = (
        "import pathlib,time;time.sleep(.5);pathlib.Path("
        + repr(str(marker))
        + ").write_text('orphan')"
    )
    result = ProcessExecutor().run([sys.executable, "-c", code, child], timeout=0.15)
    assert result.timed_out and result.duration_seconds < 2
    import time

    time.sleep(0.6)
    assert not marker.exists()


def test_output_limit_is_enforced():
    result = ProcessExecutor().run(
        [sys.executable, "-c", "print('x'*1000000)"], max_output=128
    )
    assert result.output_limited and len(result.stdout) + len(result.stderr) == 128


class DockerCommands:
    def __init__(self):
        self.calls = []
        self.cleanup_failure = False
        self.oom = False

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return ProcessResult(
                0,
                json.dumps(
                    [
                        {
                            "Id": argv[-1],
                            "Size": 100,
                            "Architecture": "amd64",
                            "Os": "linux",
                        }
                    ]
                ),
                "",
            )
        if argv[1] == "inspect":
            return ProcessResult(
                0,
                json.dumps(
                    {
                        "Running": False,
                        "OOMKilled": self.oom,
                        "Error": "",
                        "ExitCode": 4,
                    }
                ),
                "",
            )
        if argv[1] == "rm" and self.cleanup_failure:
            return ProcessResult(1, "", "busy")
        return ProcessResult(0, "container-id", "")


def request(tmp_path):
    project = tmp_path / "input"
    project.mkdir()
    (project / "owned_test.py").write_text("test")
    return ExecutionRequest(
        "sha256:" + "a" * 64,
        ["python", "-V"],
        project,
        tmp_path / "output",
        30,
        protected_paths=("owned_test.py",),
        writable_project=True,
    )


def test_docker_security_flags_exact_image_and_cleanup(tmp_path):
    executor = DockerCommands()
    backend = DockerBackend(executor)
    value = backend.execute(request(tmp_path))
    assert value.process.returncode == 4
    create = next(c for c in executor.calls if c[1] == "create")
    assert (
        "--read-only" in create
        and "no-new-privileges:true" in create
        and "ALL" in create
    )
    assert create[create.index("--network") + 1] == "none"
    assert not any("docker.sock" in s or "--privileged" in s for s in create)
    assert any("owned_test.py,readonly" in s for s in create)
    assert executor.calls[-1][1:3] == ["rm", "--force"]


@pytest.mark.parametrize(
    "artifact", ["ubuntu:latest", "sha256:short", "ubuntu@sha256:" + "a" * 64]
)
def test_mutable_or_wrong_image_identity_is_rejected(artifact):
    with pytest.raises(FrameworkError):
        DockerBackend.immutable(artifact)


def test_mount_comma_injection_is_rejected(tmp_path):
    r = request(tmp_path)
    (r.project / "x,readonly=false").write_text("x")
    from dataclasses import replace

    with pytest.raises(FrameworkError, match="mount path"):
        DockerBackend(DockerCommands()).execute(
            replace(r, protected_paths=("x,readonly=false",))
        )


def test_cleanup_failure_requires_lease_recovery(tmp_path):
    executor = DockerCommands()
    executor.cleanup_failure = True
    with pytest.raises(LeaseRetained):
        DockerBackend(executor).execute(request(tmp_path))


def test_oom_is_not_reported_as_a_candidate_result(tmp_path):
    executor = DockerCommands()
    executor.oom = True
    with pytest.raises(FrameworkError, match="out of memory"):
        DockerBackend(executor).execute(request(tmp_path))
    assert executor.calls[-1][1] == "rm"


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_create_timeout_still_cleans_up_or_retains_lease(tmp_path, cleanup_fails):
    executor = DockerCommands()
    original = executor.run

    def run(argv, **kwargs):
        result = original(argv, **kwargs)
        return (
            ProcessResult(124, "", "create timeout", timed_out=True)
            if argv[1] == "create"
            else result
        )

    executor.run = run
    executor.cleanup_failure = cleanup_fails
    if cleanup_fails:
        with pytest.raises(LeaseRetained):
            DockerBackend(executor).execute(request(tmp_path))
    else:
        assert not DockerBackend(executor).execute(request(tmp_path)).prepared
    assert executor.calls[-1][1] == "rm"
