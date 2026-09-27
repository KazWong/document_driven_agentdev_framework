#!/usr/bin/env python3
"""Conservatively update framework-managed .env values during bootstrap."""
from __future__ import annotations

import argparse
from pathlib import Path

IMAGE_BASES = {
    "MAIN_IMAGE": "robotics-ai-agent-main",
    "GENERIC_IMAGE": "robotics-ai-agent-generic-test",
    "FIRMWARE_IMAGE": "robotics-ai-agent-firmware-test",
}
MIGRATABLE_2_0_VERSIONS = ("2.0.0", "2.0.1", "2.0.2")


def update_env(path: Path, uid: str, gid: str, docker_gid: str, version: str) -> None:
    updates = {"HOST_UID": uid, "HOST_GID": gid, "DOCKER_GID": docker_gid}
    current_images = {key: f"{base}:{version}" for key, base in IMAGE_BASES.items()}
    legacy_images = {
        key: {f"{base}:{old}" for old in MIGRATABLE_2_0_VERSIONS}
        for key, base in IMAGE_BASES.items()
    }

    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
            if key in current_images:
                if value in legacy_images[key]:
                    value = current_images[key]
                out.append(f"{key}={value}")
                seen.add(key)
                continue
        out.append(line)

    for key in ("HOST_UID", "HOST_GID", "DOCKER_GID"):
        if key not in seen:
            out.append(f"{key}={updates[key]}")
    for key, value in current_images.items():
        if key not in seen:
            out.append(f"{key}={value}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("uid")
    parser.add_argument("gid")
    parser.add_argument("docker_gid")
    parser.add_argument("version")
    args = parser.parse_args()
    update_env(args.path, args.uid, args.gid, args.docker_gid, args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
