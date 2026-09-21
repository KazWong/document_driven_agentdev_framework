from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .scm import configure_project_scm, github_env, project_scm_config, scm_doctor
from .util import AgentEnvError, run_capture
from .workitem import WorkItem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scmctl", description="Provider-neutral SCM diagnostics and PR inspection")
    sub = parser.add_subparsers(dest="command", required=True)

    configure = sub.add_parser("configure", help="configure the project SCM provider")
    configure.add_argument("--provider", required=True, choices=["github", "bitbucket"])
    configure.add_argument("--remote", default="origin")
    configure.add_argument("--base-branch", default="main")
    configure.add_argument("--project", default=".")

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--project", default=".")

    auth = sub.add_parser("auth-status")
    auth.add_argument("--project", default=".")

    pr = sub.add_parser("pr")
    pr_sub = pr.add_subparsers(dest="pr_command", required=True)
    for name in ("status", "view"):
        command = pr_sub.add_parser(name)
        command.add_argument("work_item")
        if name == "view":
            command.add_argument("--web", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "configure":
            path = configure_project_scm(
                Path(args.project), provider=args.provider, remote=args.remote, base_branch=args.base_branch
            )
            print(path)
            return 0
        if args.command in {"doctor", "auth-status"}:
            report = scm_doctor(Path(args.project))
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report.get("ready") else 1
        if args.command == "pr":
            item = WorkItem.open(args.work_item)
            pr = item.status.get("pull_request")
            if not isinstance(pr, dict) or not pr.get("url"):
                raise AgentEnvError(f"{item.work_id} has no recorded remote pull request")
            if args.pr_command == "status" or not args.web:
                print(json.dumps(pr, indent=2, sort_keys=True))
                return 0
            config = project_scm_config(item.project_root)
            if config["provider"] == "github":
                number = pr.get("number")
                repository = pr.get("repository")
                completed = run_capture(
                    ["gh", "pr", "view", str(number), "--repo", str(repository), "--web"],
                    cwd=item.repo, env=github_env(), check=False,
                )
                if completed.returncode != 0:
                    raise AgentEnvError(completed.stderr.strip() or "failed to open GitHub PR")
            else:
                print(pr["url"])
            return 0
        raise AgentEnvError(f"unimplemented scmctl command: {args.command}")
    except AgentEnvError as exc:
        print(f"scmctl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
