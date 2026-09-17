from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from .util import AgentEnvError, env_root, safe_actor, shell_join
from .workitem import WorkItem

DEVICE_PATTERN = re.compile(r"^/dev/(tty[A-Za-z0-9._-]+|serial/[A-Za-z0-9_./-]+|bus/usb/[0-9]{3}/[0-9]{3})$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hardwarectl", description="Human-gated firmware hardware shell")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("shell", "exec"):
        command = sub.add_parser(name)
        command.add_argument("work_item")
        command.add_argument("--device", required=True)
        command.add_argument("--actor")
        command.add_argument("--confirm", required=True, help="must equal AUTHORIZE-HARDWARE")
        if name == "exec":
            command.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.confirm != "AUTHORIZE-HARDWARE":
            raise AgentEnvError("--confirm must be exactly AUTHORIZE-HARDWARE")
        if not DEVICE_PATTERN.fullmatch(args.device) or ".." in args.device:
            raise AgentEnvError("device must be an explicit tty, /dev/serial, or USB bus path")
        device_path = Path(args.device)
        try:
            device_stat = device_path.stat()
        except FileNotFoundError as exc:
            raise AgentEnvError(f"authorized device does not exist: {device_path}") from exc
        if not stat.S_ISCHR(device_stat.st_mode):
            raise AgentEnvError(f"authorized device is not a character device: {device_path}")
        item = WorkItem.open(args.work_item)
        if item.manifest["risk_class"] != "R3":
            raise AgentEnvError("physical hardware access is available only to R3 work items")
        if item.manifest["promotion"]["physical_hardware"] != "human-approved":
            raise AgentEnvError("the work-item manifest prohibits physical hardware")
        required = int(item.policy["hardware_approvals"])
        if item.approval_count("hardware") < required:
            raise AgentEnvError(f"hardware access requires {required} distinct hardware approvals")
        if item.status["state"] not in {"CI_VERIFIED", "MERGE_APPROVED"}:
            raise AgentEnvError("hardware access requires CI_VERIFIED or MERGE_APPROVED state")
        actor = safe_actor(args.actor)
        base = [
            os.environ.get("DOCKER_BIN", "docker"), "compose",
            "-f", str(env_root() / "compose.yaml"),
            "-f", str(env_root() / "compose.hardware.yaml"),
            "--project-name", "robotics-agent-hardware",
            "run", "--rm", "firmware-test",
        ]
        if args.command == "shell":
            command = base + ["bash"]
        else:
            extra = list(args.argv)
            if extra and extra[0] == "--":
                extra = extra[1:]
            if not extra:
                raise AgentEnvError("exec requires a command after '--'")
            command = base + extra
        env = os.environ.copy()
        env["FIRMWARE_DEVICE"] = args.device
        env["FIRMWARE_DEVICE_GID"] = str(device_stat.st_gid)
        item._append_trace(
            "hardware_command_authorized", item.status["state"], item.status["state"],
            {
                "actor": actor, "device": args.device, "device_gid": device_stat.st_gid,
                "command": shell_join(command),
            },
            actor=actor,
        )
        completed = subprocess.run(command, env=env, check=False)
        item._append_trace(
            "hardware_command_completed", item.status["state"], item.status["state"],
            {"actor": actor, "device": args.device, "returncode": completed.returncode}, actor=actor,
        )
        item.refresh_evidence_index()
        return completed.returncode
    except (AgentEnvError, FileNotFoundError) as exc:
        print(f"hardwarectl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
