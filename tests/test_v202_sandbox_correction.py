from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from robotics_agent_env import codex_runner, workflow

ROOT = Path(__file__).resolve().parents[1]


def test_main_container_has_nested_bwrap_runtime_profile() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    main = compose["services"]["main-development"]
    assert set(main["cap_add"]) == {
        "SYS_ADMIN", "SYS_CHROOT", "SETUID", "SETGID", "SYS_PTRACE", "NET_ADMIN"
    }
    assert set(main["security_opt"]) == {"seccomp=unconfined", "apparmor=unconfined"}
    dockerfile = (ROOT / "docker/main/Dockerfile").read_text(encoding="utf-8")
    assert "chmod u+s /usr/bin/bwrap" in dockerfile


def test_blocked_planner_deliverable_is_not_published_as_plan(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    state_root = tmp_path / "state"
    state_root.mkdir()
    calls = {"write_plan": 0, "write_artifact": 0}

    class FakeItem:
        def __init__(self):
            self.work_id = "RBT-TEST"
            self.manifest = {}
            self.status = {}
            self.artifacts_path = artifacts
            self.repo = repo
            self.state_root = state_root

        def new_run_dir(self, role):
            return run_dir

        def record_role_run(self, *args):
            pass

        def write_plan(self, text):
            calls["write_plan"] += 1

        def write_artifact(self, name, text):
            calls["write_artifact"] += 1

    result = {
        "status": "blocked",
        "decision": "blocked",
        "summary": "sandbox unavailable",
        "deliverable_markdown": "# Blocked planner report",
        "scope_change": False,
        "findings": [],
        "evidence": [],
    }

    monkeypatch.setattr(codex_runner, "_build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(codex_runner, "_load_role_instructions", lambda role: "instructions")

    def fake_run(command, **kwargs):
        result_path = Path(command[command.index("--output-last-message") + 1])
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)
    returned = codex_runner.dispatch_role(FakeItem(), "planner")
    assert returned["status"] == "blocked"
    assert calls == {"write_plan": 0, "write_artifact": 1}


def test_workflow_only_records_successful_planner_result(tmp_path, monkeypatch) -> None:
    class FakeItem:
        work_id = "RBT-TEST"

        manifest = {"isolation": {"strategy": "worktree"}}

        def __init__(self):
            self.artifacts_path = tmp_path / f"artifacts-{id(self)}"
            self.artifacts_path.mkdir()
            self.status = {"state": "INTAKE", "worktree": "ready", "current_plan": None}
            self.plan_writes = []

        def active_documents(self):
            return [{"id": "DOC-001"}]

        def prepare_agent_context(self):
            return {}

        def create_worktree(self):
            self.status["worktree"] = "ready"

        def transition(self, current, target, **kwargs):
            assert self.status["state"] == current
            self.status["state"] = target

        def update_status(self, values, **kwargs):
            self.status.update(values)

        def write_plan(self, text):
            self.plan_writes.append(text)
            self.status["current_plan"] = {"id": "plan-0001"}

    blocked = FakeItem()
    monkeypatch.setattr(workflow, "dispatch_role", lambda *args, **kwargs: {
        "status": "blocked", "decision": "blocked", "summary": "blocked",
        "deliverable_markdown": "# blocked report", "scope_change": False,
        "findings": [], "evidence": [],
    })
    assert workflow.run_next(blocked) == "BLOCKED"
    assert blocked.plan_writes == []
    assert blocked.status.get("current_plan") is None

    passed = FakeItem()
    def passed_role(current, *args, **kwargs):
        current.write_plan("# executable plan")
        return {
            "status": "completed", "decision": "pass", "summary": "ok",
            "deliverable_markdown": "# executable plan", "scope_change": False,
            "findings": [], "evidence": [],
        }
    monkeypatch.setattr(workflow, "dispatch_role", passed_role)
    assert workflow.run_next(passed) == "PLANNED"
    assert passed.plan_writes == ["# executable plan"]


def test_codex_bwrap_compat_strips_only_fresh_proc_mount(tmp_path) -> None:
    import os
    import subprocess

    wrapper = ROOT / "scripts/codex-bwrap-compat.sh"
    assert wrapper.is_file()
    assert os.access(wrapper, os.X_OK)

    argv_log = tmp_path / "argv.log"
    fake = tmp_path / "real-bwrap"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' \"$@\" > {argv_log!s}\n"
        "for ((i=1; i <= $#; i++)); do\n"
        "  if [[ ${!i} == --proc ]]; then\n"
        "    j=$((i+1))\n"
        "    if ((j <= $#)) && [[ ${!j} == /proc ]]; then\n"
        "      echo \"bwrap: Can't mount proc on /newroot/proc: Operation not permitted\" >&2\n"
        "      exit 1\n"
        "    fi\n"
        "  fi\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["ROBOTICS_AGENT_REAL_BWRAP"] = str(fake)
    command = [
        str(wrapper),
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-net",
        "--ro-bind", "/", "/",
        "--proc", "/proc",
        "--dev", "/dev",
        "/bin/true",
    ]
    completed = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    forwarded = argv_log.read_text(encoding="utf-8").splitlines()
    assert forwarded == [
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-net",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "/bin/true",
    ]


def test_codex_bwrap_compat_preserves_other_proc_targets_and_exit_status(tmp_path) -> None:
    import os
    import subprocess

    wrapper = ROOT / "scripts/codex-bwrap-compat.sh"
    argv_log = tmp_path / "argv.log"
    fake = tmp_path / "real-bwrap"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {argv_log!s}\n"
        "exit 23\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["ROBOTICS_AGENT_REAL_BWRAP"] = str(fake)
    completed = subprocess.run(
        [str(wrapper), "--proc", "/alternate-proc", "--ro-bind", "/", "/", "/bin/false"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 23
    assert argv_log.read_text(encoding="utf-8").splitlines() == [
        "--proc", "/alternate-proc", "--ro-bind", "/", "/", "/bin/false"
    ]


def test_main_image_installs_codex_bwrap_compat_before_system_bwrap() -> None:
    dockerfile = (ROOT / "docker/main/Dockerfile").read_text(encoding="utf-8")
    assert "chmod u+s /usr/bin/bwrap" in dockerfile
    assert "COPY scripts/codex-bwrap-compat.sh /usr/local/bin/bwrap" in dockerfile
    assert "chmod 0755 /usr/local/bin/bwrap" in dockerfile
