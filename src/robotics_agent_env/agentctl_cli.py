from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from .manifest import load_and_validate_manifest
from .risk import default_risk_for_kind, reclassify_work_item
from .test_registry import TestController, TestRegistry
from .util import AgentEnvError, command_exists, git, load_json, state_root, workspace_root
from .workflow import resolve_diagnosis, run_next, run_until_gate
from .workitem import WorkItem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentctl", description="Document-driven agent-gated robotics software lifecycle")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-manifest", help="create the low-level work-item control manifest")
    init.add_argument("--output", default="work-item.yaml")
    init.add_argument("--id", default="RBT-001")
    init.add_argument("--title", default="Describe the change")
    init.add_argument("--repository", default=".")
    init.add_argument("--kind", choices=["generic", "ros2", "firmware", "mixed"], default="generic")
    init.add_argument("--risk", choices=["R0", "R1", "R2", "R3"], default=None)

    new = sub.add_parser("new", help="register a manifest as a project-local work item")
    new.add_argument("manifest")
    new.add_argument("--prepare-worktree", action="store_true")

    update = sub.add_parser("update", help="import or revise authoritative work-item documents")
    update.add_argument("work_item")
    update.add_argument("--document", action="append", required=True)
    update.add_argument("--supersedes")

    sub.add_parser("list", help="list indexed work items")

    status = sub.add_parser("status")
    status.add_argument("work_item")
    status.add_argument("--json", action="store_true")

    inspect = sub.add_parser("inspect", help="show Git/candidate state without changing workflow state")
    inspect.add_argument("work_item")
    inspect.add_argument("--stat", action="store_true", help="show baseline-to-candidate diff stat")

    run = sub.add_parser("run")
    run.add_argument("work_item")
    run.add_argument("--one-step", action="store_true")

    plan = sub.add_parser("plan", help="run document-driven planning for a work item")
    plan.add_argument("work_item")
    plan.add_argument("--retry", action="store_true")

    approve = sub.add_parser("approve")
    approve.add_argument("work_item")
    approve.add_argument("gate", choices=["plan", "merge", "hardware"])
    approve.add_argument("--actor")
    approve.add_argument("--note", default="")

    worktree = sub.add_parser("worktree")
    worktree_sub = worktree.add_subparsers(dest="worktree_command", required=True)
    create = worktree_sub.add_parser("create")
    create.add_argument("work_item")
    create.add_argument("--branch")

    resolve = sub.add_parser("resolve", help="route a completed diagnosis")
    resolve.add_argument("work_item")
    resolve.add_argument("--route", required=True, choices=["implementation", "plan", "local-test", "environment", "blocked"])

    reclassify = sub.add_parser("reclassify", help="escalate work-item risk and require replanning")
    reclassify.add_argument("work_item")
    reclassify.add_argument("--risk", required=True, choices=["R0", "R1", "R2", "R3"])
    reclassify.add_argument("--actor")
    reclassify.add_argument("--note", default="")

    ci = sub.add_parser("record-ci")
    ci.add_argument("work_item")
    ci.add_argument("--status", required=True, choices=["passed", "failed"])
    ci.add_argument("--url", required=True)
    ci.add_argument("--commit")

    promote = sub.add_parser("promote")
    promote.add_argument("work_item")
    promote.add_argument("--level", required=True, choices=["simulation", "hil", "physical"])
    promote.add_argument("--evidence", required=True)
    promote.add_argument("--actor")

    close = sub.add_parser("close")
    close.add_argument("work_item")
    close.add_argument("--actor")
    close.add_argument("--note", default="")

    recover = sub.add_parser("recover")
    recover.add_argument("work_item")
    recover.add_argument("--to", required=True)
    recover.add_argument("--actor")
    recover.add_argument("--note", default="")

    evidence = sub.add_parser("evidence")
    evidence.add_argument("work_item")

    validate = sub.add_parser("validate-manifest")
    validate.add_argument("manifest")

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    return parser


def _manifest_template(args: argparse.Namespace) -> dict[str, Any]:
    risk = args.risk or default_risk_for_kind(args.kind)
    scopes = {
        "generic": ["src/**", "include/**", "test/**", "tests/**", "scripts/**"],
        "ros2": ["src/**", "include/**", "test/**", "tests/**", "launch/**", "config/**", "worlds/**", "scripts/**", "pyproject.toml", "setup.cfg", "setup.py", "package.xml", "CMakeLists.txt"],
        "firmware": ["src/**", "include/**", "test/**", "tests/**", "scripts/**", "platformio.ini", "CMakeLists.txt"],
        "mixed": ["src/**", "include/**", "test/**", "tests/**", "launch/**", "config/**", "worlds/**", "firmware/**", "scripts/**", "platformio.ini", "CMakeLists.txt", "pyproject.toml", "setup.cfg", "setup.py", "package.xml"],
    }
    integration: list[dict[str, Any]] = []
    if args.kind == "generic" and risk in {"R2", "R3"}:
        integration.append({"lane": "generic", "action": "test", "args": []})
    if args.kind in {"ros2", "mixed"}:
        integration.append({"lane": "ros2-humble", "action": "test", "args": ["--clean"]})
    if args.kind in {"firmware", "mixed"}:
        integration.append({"lane": "firmware-emulation", "action": "test", "args": []})
    return {
        "schema_version": 1,
        "id": args.id,
        "title": args.title,
        "repository": args.repository,
        "base_branch": "main",
        "risk_class": risk,
        "project_kind": args.kind,
        "goal": f"Implement the active imported project documents for: {args.title}",
        "scope": {"include": scopes[args.kind], "exclude": ["deployment/**"]},
        "acceptance_criteria": [
            "The behavior defined by the active imported project documents is implemented within the approved scope.",
            "All required deterministic verification passes against the exact candidate commit with recorded evidence.",
        ],
        "verification": {
            "local": [{"id": "project-verification", "command": ["bash", "scripts/ci/verify.sh"], "timeout_seconds": 900}],
            "integration": integration,
        },
        "isolation": {"strategy": "worktree"},
        "human_gates": {
            "plan_change": "required", "pull_request_creation": "automated",
            "merge": "required", "physical_execution": "required",
        },
        "promotion": {"physical_hardware": "human-approved" if risk == "R3" else "prohibited"},
        "rollback": {"method": "revert_commit"},
    }


def _open(work_id: str) -> WorkItem:
    return WorkItem.open(work_id)


def _display_status(item: WorkItem, as_json: bool = False) -> None:
    status = item.status
    if as_json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return
    print(f"{status['id']}: {status['state']} ({status['risk_class']}, {status['project_kind']})")
    print(f"repository: {item.repo}")
    print(f"work item: {item.path}")
    print(f"active documents: {len(item.active_documents())}")
    if status.get("branch"):
        print(f"branch: {status['branch']}")
    current_plan = status.get("current_plan")
    if isinstance(current_plan, dict):
        print(f"current plan: {current_plan.get('id')}")
    implementation = status.get("implementation")
    if isinstance(implementation, dict) and implementation.get("candidate_sha"):
        print(f"candidate: {implementation.get('candidate_sha')}")
        print(
            "verification SHAs: "
            f"local={implementation.get('local_test_sha')} "
            f"integration={implementation.get('integration_test_sha')} "
            f"review={implementation.get('reviewed_sha')}"
        )
    pull_request = status.get("pull_request")
    if isinstance(pull_request, dict) and pull_request.get("url"):
        print(f"pull request: {pull_request.get('url')}")
    print(f"evidence: {item.evidence_index_path}")
    if status.get("last_error"):
        print(f"last error: {status['last_error']}")


def _inspect(item: WorkItem, show_stat: bool = False) -> None:
    status = item.status
    impl = status.get("implementation") if isinstance(status.get("implementation"), dict) else {}
    pr = status.get("pull_request") if isinstance(status.get("pull_request"), dict) else {}
    print(f"project: {item.project_root}")
    print(f"worktree: {item.repo}")
    print(f"branch: {status.get('branch')}")
    print(f"baseline: {status.get('baseline_sha')}")
    print(f"candidate: {impl.get('candidate_sha')}")
    print(f"local test: {impl.get('local_test_sha')}")
    print(f"integration test: {impl.get('integration_test_sha')}")
    print(f"reviewed: {impl.get('reviewed_sha')}")
    print(f"pull request: {pr.get('url')}")
    if show_stat and impl.get("candidate_sha"):
        completed = git(item.repo, "diff", "--stat", f"{status.get('baseline_sha')}...{impl.get('candidate_sha')}", check=False)
        if completed.returncode == 0 and completed.stdout.strip():
            print(completed.stdout.rstrip())


def _list_items() -> None:
    index = state_root() / "index" / "work-items.json"
    if not index.is_file():
        return
    data = load_json(index)
    for work_id in sorted(data.get("work_items", {})):
        try:
            item = WorkItem.open(work_id)
        except AgentEnvError:
            continue
        print(f"{work_id:24} {item.status['state']:18} {item.status['title']}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init-manifest":
            target = Path(args.output)
            if target.exists():
                raise AgentEnvError(f"refusing to overwrite {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(yaml.safe_dump(_manifest_template(args), sort_keys=False, allow_unicode=True), encoding="utf-8")
            print(target)
            return 0
        if args.command == "new":
            item = WorkItem.create(Path(args.manifest))
            if args.prepare_worktree:
                item.create_worktree()
            _display_status(item)
            return 0
        if args.command == "update":
            item = _open(args.work_item)
            imported = item.import_documents([Path(p) for p in args.document], supersedes=args.supersedes)
            for entry in imported:
                print(f"{entry['id']}/{entry['revision']} {entry['sha256']} {entry['filename']}")
            _display_status(item)
            return 0
        if args.command == "list":
            _list_items()
            return 0
        if args.command == "status":
            _display_status(_open(args.work_item), args.json)
            return 0
        if args.command == "inspect":
            _inspect(_open(args.work_item), args.stat)
            return 0
        if args.command == "run":
            item = _open(args.work_item)
            run_until_gate(item, one_step=args.one_step)
            _display_status(item)
            return 0
        if args.command == "plan":
            item = _open(args.work_item)
            if args.retry:
                item.retry_plan()
            if item.status["state"] != "INTAKE":
                raise AgentEnvError(f"'plan' requires INTAKE, current state is {item.status['state']}")
            run_next(item)
            _display_status(item)
            return 0
        if args.command == "approve":
            item = _open(args.work_item)
            count, required = item.add_approval(args.gate, args.actor, args.note)
            print(f"{args.gate} approvals: {count}/{required}")
            _display_status(item)
            return 0
        if args.command == "worktree":
            item = _open(args.work_item)
            print(item.create_worktree(args.branch))
            return 0
        if args.command == "resolve":
            item = _open(args.work_item)
            print(resolve_diagnosis(item, args.route))
            return 0
        if args.command == "reclassify":
            item = _open(args.work_item)
            old, new = reclassify_work_item(item, args.risk, actor=args.actor, note=args.note)
            print(f"{item.work_id}: risk {old} -> {new}; replanning required")
            _display_status(item)
            return 0
        if args.command == "record-ci":
            item = _open(args.work_item)
            item.record_ci(args.status, args.url, args.commit)
            _display_status(item)
            return 0
        if args.command == "promote":
            item = _open(args.work_item)
            item.record_promotion(args.level, args.evidence, args.actor)
            _display_status(item)
            return 0
        if args.command == "close":
            item = _open(args.work_item)
            item.close(args.actor, args.note)
            _display_status(item)
            return 0
        if args.command == "recover":
            item = _open(args.work_item)
            item.recover(args.to, args.actor, args.note)
            _display_status(item)
            return 0
        if args.command == "evidence":
            item = _open(args.work_item)
            item.refresh_evidence_index()
            print(item.evidence_index_path.read_text(encoding="utf-8"), end="")
            return 0
        if args.command == "validate-manifest":
            manifest = load_and_validate_manifest(Path(args.manifest))
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        if args.command == "doctor":
            cwd_project = WorkItem._project_from_cwd()
            tracked_local: list[str] = []
            if cwd_project:
                result = git(cwd_project, "ls-files", ".agent/work-items", ".agent-context", check=False)
                tracked_local = [line for line in result.stdout.splitlines() if line.strip()]
            report: dict[str, Any] = {
                "workspace_root": str(workspace_root()),
                "workspace_exists": workspace_root().is_dir(),
                "workspace_writable": os.access(workspace_root(), os.W_OK) if workspace_root().exists() else False,
                "state_root": str(state_root()),
                "commands": {name: command_exists(name) for name in ["codex", "docker", "git", "python3", "bwrap"]},
                "docker_socket": {
                    "path": "/var/run/docker.sock", "exists": Path("/var/run/docker.sock").exists(),
                    "readable": os.access("/var/run/docker.sock", os.R_OK), "writable": os.access("/var/run/docker.sock", os.W_OK),
                },
                "tracked_local_state": tracked_local,
                "test_lanes": [TestController(TestRegistry()).doctor(name) for name in TestRegistry().names()],
            }
            report["ready"] = bool(
                report["workspace_exists"] and report["workspace_writable"]
                and all(report["commands"].values())
                and report["docker_socket"]["exists"] and report["docker_socket"]["readable"] and report["docker_socket"]["writable"]
                and not tracked_local
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["ready"] else 1
        raise AgentEnvError(f"unimplemented command: {args.command}")
    except AgentEnvError as exc:
        print(f"agentctl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
