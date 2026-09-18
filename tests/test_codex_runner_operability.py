from __future__ import annotations

import os
from pathlib import Path

from robotics_agent_env import codex_runner


def test_codex_global_approval_flag_precedes_exec(monkeypatch, tmp_path):
    captured = {}
    class Dummy:
        returncode = 1
        stdout = ""
        stderr = "expected failure"
    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return Dummy()
    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)
    monkeypatch.setenv("SHOULD_NOT_LEAK", "secret")
    # Assert construction helpers directly through a minimal fake item.
    class FakeItem:
        repo = tmp_path / "repo"
        state_root = tmp_path / ".state"
        path = tmp_path / ".item"
        artifacts_path = path / "artifacts"
        manifest = {}
        status = {}
        def new_run_dir(self, role):
            d = self.path / role
            d.mkdir(parents=True, exist_ok=True)
            self.artifacts_path.mkdir(parents=True, exist_ok=True)
            return d
        def record_role_run(self, *args): pass
        def write_artifact(self, *args): pass
    FakeItem.repo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(codex_runner, "_build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(codex_runner, "_load_role_instructions", lambda role: "instructions")
    codex_runner.dispatch_role(FakeItem(), "planner")
    cmd = captured["command"]
    assert cmd.index("--ask-for-approval") < cmd.index("exec")
    assert "SHOULD_NOT_LEAK" not in captured["env"]
