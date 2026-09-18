from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import yaml
from pathlib import Path
from typing import Any

from .codex_runner import dispatch_role
from .manifest import load_and_validate_manifest
from .test_registry import TestController, TestRegistry
from .util import AgentEnvError, command_exists, env_root, state_root, workspace_root
from .workflow import resolve_diagnosis, run_next, run_until_gate
from .workitem import WorkItem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentctl", description="Agent-gated robotics software lifecycle")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-manifest", help="create a work-item manifest template")
    init.add_argument("--output", default="work-item.yaml")
    init.add_argument("--id", default="RBT-001")
    init.add_argument("--title", default="Describe the change")
    init.add_argument("--repository", default="projects/example")
    init.add_argument("--kind", choices=["generic", "ros2", "firmware", "mixed"], default="generic")
    init.add_argument("--risk", choices=["R0", "R1", "R2", "R3"], default="R1")

    new = sub.add_parser("new", help="register a new work item")
    new.add_argument("manifest")
    new.add_argument("--prepare-worktree", action="store_true")

    sub.add_parser("list", help="list work items")
    status = sub.add_parser("status")
    status.add_argument("work_item")
    status.add_argument("--json", action="store_true")

    run = sub.add_parser("run", help="run the authorized workflow until the next gate")
    run.add_argument("work_item")
    run.add_argument("--one-step", action="store_true")

    for name, expected in (
        ("plan", "INTAKE"), ("code", "PLAN_APPROVED"), ("test", "IMPLEMENTED"),
        ("integrate", "LOCALLY_VERIFIED"), ("review", "ENV_VERIFIED"),
        ("prepare-review", "REVIEWED"), ("debug", "DIAGNOSING"),
    ):
        command = sub.add_parser(name, help=f"compatibility alias; requires state {expected}")
        command.add_argument("work_item")
        command.set_defaults(expected_state=expected)

    approve = sub.add_parser("approve", help="record a human gate approval")
    approve.add_argument("work_item")
    approve.add_argument("gate", choices=["plan", "pr", "merge", "hardware"])
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
    scopes = {
        "generic": ["src/**", "include/**", "test/**", "tests/**", "scripts/**"],
        "ros2": ["src/**", "include/**", "test/**", "tests/**", "launch/**", "config/**", "worlds/**", "scripts/**"],
        "firmware": ["src/**", "include/**", "test/**", "tests/**", "scripts/**", "platformio.ini", "CMakeLists.txt"],
        "mixed": ["src/**", "include/**", "test/**", "tests/**", "launch/**", "config/**", "worlds/**", "firmware/**", "scripts/**", "platformio.ini", "CMakeLists.txt"],
    }
    integration: list[dict[str, Any]] = []
    if args.kind == "generic" and args.risk in {"R2", "R3"}:
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
        "risk_class": args.risk,
        "project_kind": args.kind,
        "goal": f"Implement the measurable outcome for: {args.title}",
        "scope": {"include": scopes[args.kind], "exclude": ["deployment/**"]},
        "acceptance_criteria": [
            "The requested behavior is implemented within the approved scope.",
            "All required deterministic verification passes with recorded evidence.",
        ],
        "verification": {
            "local": [{
                "id": "project-verification",
                "command": ["bash", "scripts/ci/verify.sh"],
                "timeout_seconds": 900,
            }],
            "integration": integration,
        },
        "isolation": {"strategy": "worktree"},
        "human_gates": {
            "plan_change": "required",
            "pull_request_creation": "required",
            "merge": "required",
            "physical_execution": "required",
        },
        "promotion": {
            "physical_hardware": "human-approved" if args.risk == "R3" else "prohibited"
        },
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
    if status.get("branch"):
        print(f"branch: {status['branch']}")
    if status.get("last_error"):
        print(f"last error: {status['last_error']}")
    print(f"evidence: {item.evidence_index_path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init-manifest":
            target = Path(args.output)
            if target.exists():
                raise AgentEnvError(f"refusing to overwrite {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                yaml.safe_dump(_manifest_template(args), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            print(target)
            return 0
        if args.command == "new":
            item = WorkItem.create(Path(args.manifest))
            if args.prepare_worktree:
                item.create_worktree()
            _display_status(item)
            return 0
        if args.command == "list":
            root = state_root() / "work-items"
            if not root.is_dir():
                return 0
            for path in sorted(root.iterdir()):
                if path.is_dir() and (path / "status.json").is_file():
                    item = WorkItem.open(path.name)
                    print(f"{path.name:24} {item.status['state']:18} {item.status['title']}")
            return 0
        if args.command == "status":
            _display_status(_open(args.work_item), args.json)
            return 0
        if args.command == "run":
            item = _open(args.work_item)
            run_until_gate(item, one_step=args.one_step)
            _display_status(item)
            return 0
        if args.command in {"plan", "code", "test", "integrate", "review", "prepare-review", "debug"}:
            item = _open(args.work_item)
            if item.status["state"] != args.expected_state:
                raise AgentEnvError(f"'{args.command}' requires {args.expected_state}, current state is {item.status['state']}")
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
            report: dict[str, Any] = {
                "workspace_root": str(workspace_root()),
                "workspace_exists": workspace_root().is_dir(),
                "workspace_writable": os.access(workspace_root(), os.W_OK) if workspace_root().exists() else False,
                "state_root": str(state_root()),
                "commands": {name: command_exists(name) for name in ["codex", "docker", "git", "python3", "bwrap"]},
                "docker_socket": {
                    "path": "/var/run/docker.sock",
                    "exists": Path("/var/run/docker.sock").exists(),
                    "readable": os.access("/var/run/docker.sock", os.R_OK),
                    "writable": os.access("/var/run/docker.sock", os.W_OK),
                },
                "test_lanes": [TestController(TestRegistry()).doctor(name) for name in TestRegistry().names()],
            }
            ready = (
                report["workspace_exists"] and report["workspace_writable"]
                and report["commands"]["git"] and report["commands"]["python3"]
                and report["commands"]["codex"] and report["commands"]["docker"]
                and report["commands"]["bwrap"]
                and report["docker_socket"]["exists"] and report["docker_socket"]["readable"] and report["docker_socket"]["writable"]
            )
            report["ready"] = ready
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if ready else 1
        raise AgentEnvError(f"unimplemented command: {args.command}")
    except AgentEnvError as exc:
        print(f"agentctl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
