from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import yaml

from conftest import init_repo
from robotics_agent_env.workflow import run_until_gate
from robotics_agent_env.workitem import WorkItem


def make_fake_codex(path: Path) -> None:
    path.write_text(r'''#!/usr/bin/env python3
import json, pathlib, sys
args=sys.argv[1:]
out=pathlib.Path(args[args.index("--output-last-message")+1])
repo=pathlib.Path(args[args.index("--cd")+1])
prompt=sys.stdin.read()
role=prompt.split("Execute the '",1)[1].split("'",1)[0]
if role == "coder":
    target=repo/"src"/"value.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("implemented\n")
result={
 "status":"completed", "decision":"pass", "summary":f"{role} passed",
 "deliverable_markdown":f"# {role}\n\nCompleted.", "scope_change":False,
 "findings":[], "evidence":[]
}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result))
print(json.dumps({"type":"result","role":role}))
''', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_full_flow_stops_at_human_gates(workspace: Path, monkeypatch) -> None:
    repo = init_repo(workspace / "projects" / "app")
    (repo / "scripts" / "ci").mkdir(parents=True)
    verify = repo / "scripts" / "ci" / "verify.sh"
    verify.write_text("#!/usr/bin/env bash\nset -euo pipefail\ntest -f src/value.txt\n", encoding="utf-8")
    verify.chmod(0o755)
    os.system(f"git -C {repo} add . && git -C {repo} commit -m add-test >/dev/null")
    fake = workspace / "fake-codex"
    make_fake_codex(fake)
    monkeypatch.setenv("CODEX_BIN", str(fake))
    manifest = {
        "schema_version": 1, "id": "APP-1", "title": "implement value",
        "repository": str(repo), "base_branch": "main", "risk_class": "R1",
        "project_kind": "generic", "goal": "create the value file",
        "scope": {"include": ["src/**"], "exclude": []},
        "acceptance_criteria": ["value exists"],
        "verification": {"local": [{"id": "verify", "command": ["bash", "scripts/ci/verify.sh"], "timeout_seconds": 60}], "integration": []},
        "isolation": {"strategy": "worktree"},
        "promotion": {"physical_hardware": "prohibited"},
    }
    manifest_path = workspace / "item.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    item = WorkItem.create(manifest_path)
    assert run_until_gate(item) == "PLANNED"
    item.add_approval("plan", actor="planner-owner")
    assert item.status["state"] == "PLAN_APPROVED"
    assert run_until_gate(item) == "PR_READY"
    assert (item.artifacts_path / "review.md").is_file()
    assert (item.repo / "src" / "value.txt").read_text() == "implemented\n"
    item.add_approval("pr", actor="maintainer")
    assert item.pr_is_approved()
    item.record_ci("passed", "https://ci.example.invalid/build/1")
    item.add_approval("merge", actor="maintainer")
    assert item.status["state"] == "MERGE_APPROVED"
