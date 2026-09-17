from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .test_registry import TestController, TestRegistry
from .util import AgentEnvError, shell_join


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="testctl", description="Run registered robotics test environments")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--dry-run", action="store_true", help="print commands without executing")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list test lanes")
    doctor = sub.add_parser("doctor", help="check lane configuration")
    doctor.add_argument("lane", nargs="?", default="all")
    doctor.add_argument("--execute", action="store_true", help="run each lane's doctor command")
    for action in ("build", "smoke", "configure"):
        command = sub.add_parser(action)
        command.add_argument("lane", nargs="?", default="all" if action == "smoke" else None)
    for action in ("test", "sim"):
        command = sub.add_parser(action)
        command.add_argument("lane")
        command.add_argument("project")
        command.add_argument("args", nargs=argparse.REMAINDER)
    for action in ("shell", "gui-shell", "debug-shell"):
        command = sub.add_parser(action)
        command.add_argument("lane")
        command.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def _print(value: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = TestRegistry()
        controller = TestController(registry)
        if args.command == "list":
            if args.json:
                _print(registry.as_json(), True)
            else:
                for name in registry.names():
                    lane = registry.get(name)
                    print(f"{name:20} {lane.config.get('type'):12} {lane.config.get('description', '')}")
            return 0
        if args.command == "doctor":
            names = registry.names() if args.lane == "all" else [registry.get(args.lane).name]
            reports = [controller.doctor(name, execute=args.execute and not args.dry_run) for name in names]
            _print({"lanes": reports}, args.json)
            return 0 if all(report["ready"] for report in reports) else 1

        lane_arg = getattr(args, "lane", None)
        if not lane_arg:
            raise AgentEnvError(f"{args.command} requires a lane")
        names = registry.names() if lane_arg == "all" else [registry.get(lane_arg).name]
        results: list[dict[str, object]] = []
        exit_code = 0
        for name in names:
            project = Path(args.project) if hasattr(args, "project") else None
            extra = list(getattr(args, "args", []))
            if extra and extra[0] == "--":
                extra = extra[1:]
            command = controller.build_command(name, args.command, project, extra)
            if args.dry_run:
                result = {"lane": name, "action": args.command, "command": command, "dry_run": True}
            else:
                actual = controller.run(name, args.command, project, extra)
                result = actual.as_dict()
                exit_code = max(exit_code, 0 if actual.passed else actual.returncode or 1)
            results.append(result)
            if not args.json:
                print(shell_join(command))
                if not args.dry_run:
                    if result.get("stdout"):
                        print(result["stdout"], end="" if str(result["stdout"]).endswith("\n") else "\n")
                    if result.get("stderr"):
                        print(result["stderr"], file=sys.stderr, end="" if str(result["stderr"]).endswith("\n") else "\n")
        if args.json:
            _print({"results": results}, True)
        return exit_code
    except AgentEnvError as exc:
        print(f"testctl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
