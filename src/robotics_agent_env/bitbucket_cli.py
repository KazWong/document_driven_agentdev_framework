from __future__ import annotations

import argparse
import json
import sys

from .bitbucket import build_pull_request_payload, create_pull_request, get_origin, infer_repository
from .util import AgentEnvError
from .workitem import WorkItem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bitbucket-pr")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "create"):
        command = sub.add_parser(name)
        command.add_argument("work_item")
        command.add_argument("--title")
        command.add_argument("--reviewer", action="append", default=[])
        command.add_argument("--draft", action="store_true")
        command.add_argument("--close-source-branch", action="store_true")
        if name == "create":
            command.add_argument("--execute", action="store_true", help="perform the API write; default is dry-run")
    infer = sub.add_parser("infer")
    infer.add_argument("remote")
    args = parser.parse_args(argv)
    try:
        if args.command == "infer":
            print(json.dumps(dict(zip(("workspace", "repository"), infer_repository(args.remote))), indent=2))
            return 0
        item = WorkItem.open(args.work_item)
        payload = build_pull_request_payload(
            item, title=args.title, reviewers=args.reviewer, draft=args.draft,
            close_source_branch=args.close_source_branch,
        )
        if args.command == "create" and args.execute:
            response = create_pull_request(item, payload)
            print(json.dumps(response, indent=2, sort_keys=True))
        else:
            workspace, repository = infer_repository(get_origin(item.repo))
            print(json.dumps({"workspace": workspace, "repository": repository, "payload": payload, "dry_run": True}, indent=2, sort_keys=True))
        return 0
    except AgentEnvError as exc:
        print(f"bitbucket-pr: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
