#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tomllib
from pathlib import Path

import jsonschema
import yaml

REQUIRED = [
    "VERSION", "README.md", "CHANGELOG.md", "AGENTS.md", "Makefile", "compose.yaml",
    "compose.hardware.yaml", ".env.example", ".codex/config.toml",
    ".codex/rules/default.rules", "config/test-environments.yaml",
    "config/workflow.yaml", "config/policies.yaml", "bin/agentctl", "bin/testctl",
    "bin/projectctl", "bin/bitbucket-pr", "bin/hardwarectl", "bin/scmctl", "bin/ros2-docker-compat",
    "docker/main/Dockerfile", "docker/generic/Dockerfile", "docker/firmware/Dockerfile",
    "schemas/work-item.schema.json", "schemas/agent-result.schema.json",
    "docs/source-reconciliation.md", "docs/agent-branching-policy.md", "docs/todo.md",
    "scripts/codex-login.sh", "scripts/github-login.sh", "scripts/codex-bwrap-compat.sh",
]
ROLES = {
    "planner", "coder", "tester", "integration_tester", "debugger",
    "reviewer", "review_requester", "safety_reviewer",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = Path(args.root).resolve()
    errors: list[str] = []
    checks: list[str] = []

    for relative in REQUIRED:
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")
    checks.append("required files")

    if (root / "VERSION").read_text().strip() != "2.0.2":
        errors.append("VERSION must be 2.0.2")

    for path in root.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON {path.relative_to(root)}: {exc}")
    checks.append("JSON parsing")

    for path in list(root.rglob("*.yaml")) + list(root.rglob("*.yml")):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid YAML {path.relative_to(root)}: {exc}")
    checks.append("YAML parsing")

    for path in root.rglob("*.toml"):
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid TOML {path.relative_to(root)}: {exc}")
    checks.append("TOML parsing")

    for schema in (root / "schemas").glob("*.json"):
        try:
            jsonschema.validators.validator_for(json.loads(schema.read_text())).check_schema(json.loads(schema.read_text()))
        except Exception as exc:
            errors.append(f"invalid JSON schema {schema.name}: {exc}")
    checks.append("JSON Schema validation")

    compose = yaml.safe_load((root / "compose.yaml").read_text())
    services = compose.get("services", {})
    for name in ("main-development", "codex-login", "generic-test", "firmware-test"):
        if name not in services:
            errors.append(f"compose service missing: {name}")
            continue
        mounts = services[name].get("volumes", [])
        if not any(isinstance(mount, dict) and mount.get("source") == "/home/kazwong/codes/agents" and mount.get("target") == "/home/kazwong/codes/agents" for mount in mounts):
            errors.append(f"{name} lacks exact workspace bind mount")
    main_mounts = services.get("main-development", {}).get("volumes", [])
    if not any(isinstance(mount, dict) and mount.get("source") == "/var/run/docker.sock" for mount in main_mounts):
        errors.append("main-development lacks Docker socket")
    main = services.get("main-development", {})
    required_caps = {"SYS_ADMIN", "SYS_CHROOT", "SETUID", "SETGID", "SYS_PTRACE", "NET_ADMIN"}
    if set(main.get("cap_add", [])) != required_caps:
        errors.append("main-development nested-sandbox capability profile is incorrect")
    if set(main.get("security_opt", [])) != {"seccomp=unconfined", "apparmor=unconfined"}:
        errors.append("main-development nested-sandbox security profile is incorrect")
    auth = services.get("codex-login", {})
    if auth.get("network_mode") != "host":
        errors.append("codex-login must use host networking for localhost OAuth callback")
    if any(isinstance(mount, dict) and mount.get("source") == "/var/run/docker.sock" for mount in auth.get("volumes", [])):
        errors.append("codex-login must not receive the Docker socket")
    if "auth" not in auth.get("profiles", []):
        errors.append("codex-login must be opt-in through the auth profile")
    for name in ("generic-test", "firmware-test"):
        if services.get(name, {}).get("devices"):
            errors.append(f"default service {name} must not expose devices")
    checks.append("Compose workspace and hardware invariants")

    registry = yaml.safe_load((root / "config/test-environments.yaml").read_text())
    lanes = registry.get("lanes", {})
    humble = lanes.get("ros2-humble", {})
    if humble.get("type") != "external-cli":
        errors.append("ros2-humble must be an external-cli lane")
    if humble.get("contract", {}).get("expected_ros_distro") != "humble":
        errors.append("ROS contract must require Humble")
    active_text = "\n".join([
        (root / "compose.yaml").read_text(),
        (root / "config/test-environments.yaml").read_text(),
        (root / "config/workflow.yaml").read_text(),
    ]).lower()
    if "jazzy" in active_text:
        errors.append("active configuration still references Jazzy")
    workflow = yaml.safe_load((root / "config/workflow.yaml").read_text())
    if "PR_OPEN" not in workflow.get("states", []) or "PR_READY" in workflow.get("states", []):
        errors.append("workflow must use PR_OPEN instead of PR_READY for new work")
    if "PR_READY" in workflow.get("human_gates", {}):
        errors.append("workflow must not require a human PR-creation gate")
    checks.append("ROS 2 Humble and automated PR workflow alignment")

    agent_files = {path.stem for path in (root / ".codex/agents").glob("*.toml")}
    if agent_files != ROLES:
        errors.append(f"Codex role set mismatch: {sorted(agent_files)}")
    for role in ROLES:
        path = root / ".codex/agents" / f"{role}.toml"
        if not path.is_file():
            continue
        data = tomllib.loads(path.read_text())
        expected = "workspace-write" if role == "coder" else "read-only"
        if data.get("sandbox_mode") != expected:
            errors.append(f"role {role} must use {expected}")
    checks.append("Codex role separation")

    executable_candidates = list((root / "bin").glob("*")) + [
        root / "scripts/bootstrap-host.sh", root / "scripts/entrypoint.sh",
        root / "scripts/qa.sh", root / "scripts/package.sh", root / "scripts/codex-login.sh",
        root / "scripts/github-login.sh", root / "scripts/codex-bwrap-compat.sh",
        root / "docker/generic/generic-test", root / "docker/firmware/firmware-test",
    ]
    for path in executable_candidates:
        if path.exists() and not os.access(path, os.X_OK):
            errors.append(f"expected executable mode: {path.relative_to(root)}")
    checks.append("executable modes")

    if (root / ".env").exists():
        errors.append("release tree must not contain .env")
    if any(path.is_symlink() for path in root.rglob("*")):
        errors.append("release tree must not contain symlinks")
    checks.append("release hygiene")

    result = {"root": str(root), "passed": not errors, "checks": checks, "errors": errors}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
