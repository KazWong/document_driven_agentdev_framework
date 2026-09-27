#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path

import jsonschema
import yaml

EXPECTED_VERSION = "2.0.3"
REQUIRED = [
    "VERSION", "README.md", "CHANGELOG.md", "AGENTS.md", "Makefile", "compose.yaml",
    "compose.hardware.yaml", ".env.example", ".gitattributes", ".codex/config.toml",
    ".codex/rules/default.rules", "config/test-environments.yaml",
    "config/workflow.yaml", "config/policies.yaml", "bin/agentctl", "bin/testctl",
    "bin/projectctl", "bin/bitbucket-pr", "bin/hardwarectl", "bin/scmctl", "bin/ros2-docker-compat",
    "docker/main/Dockerfile", "docker/generic/Dockerfile", "docker/firmware/Dockerfile",
    "schemas/work-item.schema.json", "schemas/agent-result.schema.json",
    "docs/source-reconciliation.md", "docs/agent-branching-policy.md", "docs/todo.md",
    "scripts/bootstrap-host.sh", "scripts/entrypoint.sh", "scripts/qa.sh", "scripts/package.sh",
    "scripts/update_env.py", "scripts/sync-codex-config.sh", "scripts/codex-login.sh",
    "scripts/github-login.sh", "scripts/codex-bwrap-compat.sh", "ARTIFACT-MANIFEST.sha256",
]
EXECUTABLES = [
    "bin/agentctl", "bin/bitbucket-pr", "bin/hardwarectl", "bin/projectctl",
    "bin/ros2-docker-compat", "bin/scmctl", "bin/testctl",
    "docker/firmware/firmware-test", "docker/generic/generic-test",
    "scripts/bootstrap-host.sh", "scripts/codex-bwrap-compat.sh", "scripts/codex-login.sh",
    "scripts/entrypoint.sh", "scripts/github-login.sh", "scripts/package.sh",
    "scripts/qa.sh", "scripts/sync-codex-config.sh",
]
ROLES = {
    "planner", "coder", "tester", "integration_tester", "debugger",
    "reviewer", "review_requester", "safety_reviewer",
}
FORBIDDEN_RELEASE_PATHS = [
    ".git", ".env", ".agent-state", ".agent-context", ".test-results",
    ".pytest_cache", ".agent/work-items", ".agent/runtime", ".agent/cache",
    ".agent/locks", ".agent/tmp",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_internal_manifest(root: Path, errors: list[str], *, require_complete: bool) -> None:
    manifest = root / "ARTIFACT-MANIFEST.sha256"
    if not manifest.is_file():
        return
    entries: dict[str, str] = {}
    for line_no, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            errors.append(f"invalid artifact manifest line {line_no}")
            continue
        digest, relative = match.groups()
        if relative in entries:
            errors.append(f"duplicate artifact manifest entry: {relative}")
            continue
        entries[relative] = digest
        path = root / relative
        if not path.is_file():
            errors.append(f"artifact manifest path missing: {relative}")
        elif sha256(path) != digest:
            errors.append(f"artifact manifest checksum mismatch: {relative}")

    if require_complete:
        actual = {
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file() and path.name != "ARTIFACT-MANIFEST.sha256"
        }
        listed = set(entries)
        for relative in sorted(actual - listed):
            errors.append(f"artifact manifest missing file: {relative}")
        for relative in sorted(listed - actual):
            errors.append(f"artifact manifest lists non-release file: {relative}")


def check_git_modes(root: Path, errors: list[str]) -> None:
    if not (root / ".git").exists():
        errors.append("source validation requires a Git checkout")
        return
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *EXECUTABLES],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        errors.append(f"unable to inspect committed executable modes: {result.stderr.strip()}")
        return
    modes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"(\d{6}) [0-9a-f]+ \d\t(.+)", line)
        if match:
            modes[match.group(2)] = match.group(1)
    for relative in EXECUTABLES:
        if modes.get(relative) != "100755":
            errors.append(f"Git must record executable mode 100755: {relative}")


def check_version_consistency(root: Path, errors: list[str]) -> None:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if version != EXPECTED_VERSION:
        errors.append(f"VERSION must be {EXPECTED_VERSION}")
        return

    expected_fragments = {
        "src/robotics_agent_env/__init__.py": f'__version__ = "{version}"',
        ".env.example": f"MAIN_IMAGE=robotics-ai-agent-main:{version}",
        "compose.yaml": f"robotics-ai-agent-main:{version}",
        "README.md": f"Release **{version}**",
        "docs/qa-report.md": f"Release: **{version}**",
    }
    for relative, fragment in expected_fragments.items():
        path = root / relative
        if path.is_file() and fragment not in path.read_text(encoding="utf-8"):
            errors.append(f"version mismatch in {relative}: missing {fragment!r}")

    env_text = (root / ".env.example").read_text(encoding="utf-8")
    compose_text = (root / "compose.yaml").read_text(encoding="utf-8")
    for image in (
        "robotics-ai-agent-main", "robotics-ai-agent-generic-test", "robotics-ai-agent-firmware-test",
    ):
        if f"{image}:{version}" not in env_text:
            errors.append(f".env.example image version mismatch: {image}")
        if f"{image}:{version}" not in compose_text:
            errors.append(f"compose image version mismatch: {image}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("source", "release"), default="release")
    parser.add_argument("root", nargs="?", default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = Path(args.root).resolve()
    errors: list[str] = []
    checks: list[str] = []

    for relative in REQUIRED:
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")
    checks.append("required files")

    check_version_consistency(root, errors)
    checks.append("release version consistency")

    for path in root.rglob("*.json"):
        if any(part in {".git", ".agent-state", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON {path.relative_to(root)}: {exc}")
    checks.append("JSON parsing")

    for path in list(root.rglob("*.yaml")) + list(root.rglob("*.yml")):
        if any(part in {".git", ".agent-state", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid YAML {path.relative_to(root)}: {exc}")
    checks.append("YAML parsing")

    for path in root.rglob("*.toml"):
        if any(part in {".git", ".agent-state", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid TOML {path.relative_to(root)}: {exc}")
    checks.append("TOML parsing")

    for schema in (root / "schemas").glob("*.json"):
        try:
            data = json.loads(schema.read_text(encoding="utf-8"))
            jsonschema.validators.validator_for(data).check_schema(data)
        except Exception as exc:
            errors.append(f"invalid JSON schema {schema.name}: {exc}")
    checks.append("JSON Schema validation")

    compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    services = compose.get("services", {})
    for name in ("main-development", "codex-login", "generic-test", "firmware-test"):
        if name not in services:
            errors.append(f"compose service missing: {name}")
            continue
        mounts = services[name].get("volumes", [])
        if not any(
            isinstance(mount, dict)
            and mount.get("source") == "/home/kazwong/codes/agents"
            and mount.get("target") == "/home/kazwong/codes/agents"
            for mount in mounts
        ):
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

    registry = yaml.safe_load((root / "config/test-environments.yaml").read_text(encoding="utf-8"))
    lanes = registry.get("lanes", {})
    humble = lanes.get("ros2-humble", {})
    if humble.get("type") != "external-cli":
        errors.append("ros2-humble must be an external-cli lane")
    if humble.get("contract", {}).get("expected_ros_distro") != "humble":
        errors.append("ROS contract must require Humble")
    active_text = "\n".join([
        (root / "compose.yaml").read_text(encoding="utf-8"),
        (root / "config/test-environments.yaml").read_text(encoding="utf-8"),
        (root / "config/workflow.yaml").read_text(encoding="utf-8"),
    ]).lower()
    if "jazzy" in active_text:
        errors.append("active configuration still references Jazzy")
    workflow = yaml.safe_load((root / "config/workflow.yaml").read_text(encoding="utf-8"))
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
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        expected = "workspace-write" if role == "coder" else "read-only"
        if data.get("sandbox_mode") != expected:
            errors.append(f"role {role} must use {expected}")
    checks.append("Codex role separation")

    for relative in EXECUTABLES:
        path = root / relative
        if not path.is_file():
            continue
        if stat.S_IMODE(path.stat().st_mode) & 0o111 != 0o111:
            errors.append(f"expected executable mode 0755: {relative}")
    if args.mode == "source":
        check_git_modes(root, errors)
    checks.append("filesystem and committed executable modes")

    if args.mode == "release":
        for relative in FORBIDDEN_RELEASE_PATHS:
            if (root / relative).exists():
                errors.append(f"release tree must not contain {relative}")
        for path in root.rglob("*"):
            if path.is_symlink():
                errors.append(f"release tree must not contain symlink: {path.relative_to(root)}")
            if path.is_file() and (path.suffix == ".pyc" or "__pycache__" in path.parts):
                errors.append(f"release tree must not contain Python cache: {path.relative_to(root)}")
        checks.append("release hygiene")
    else:
        checks.append("source-checkout hygiene exceptions")

    check_internal_manifest(root, errors, require_complete=args.mode == "release")
    checks.append("artifact manifest integrity")

    result = {"root": str(root), "mode": args.mode, "passed": not errors, "checks": checks, "errors": errors}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
