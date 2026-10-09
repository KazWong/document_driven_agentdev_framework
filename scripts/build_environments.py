#!/usr/bin/env python3
"""Build from approved immutable inputs and capture the resolved image inventory."""
import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_framework.common import FrameworkError, read_json, write_json
from agent_framework.docker_backend import DockerBackend
from agent_framework.scm import Repository


def validate_lock(value):
    for field in ("ubuntu_image", "node_image"):
        if not isinstance(value.get(field), str) or not re.fullmatch(
            r"[A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64}", value[field]
        ):
            raise FrameworkError(
                field + " must be an independently selected repository@sha256 digest"
            )
    if not isinstance(value.get("codex_version"), str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", value["codex_version"]
    ):
        raise FrameworkError(
            "select an exact Codex version; latest/ranges/missing values are not release inputs"
        )
    if value.get("platform") != "linux/amd64":
        raise FrameworkError("v2.1's initial target is linux/amd64")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--lock", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    lock = read_json(a.lock)
    validate_lock(lock)
    root = Path(__file__).resolve().parents[1]
    repo = Repository(root)
    if not repo.clean():
        raise FrameworkError("build the exact committed clean candidate")
    backend = DockerBackend()
    images = {}
    for name in ("main", "generic"):
        args = {"UBUNTU_IMAGE": lock["ubuntu_image"]}
        if name == "main":
            args.update(
                NODE_IMAGE=lock["node_image"], CODEX_VERSION=lock["codex_version"]
            )
        image = backend.build(
            root,
            recipe={
                "file": f"docker/{name}/Dockerfile",
                "build_args": args,
                "platform": lock["platform"],
            },
            network=True,
        )
        images[name] = backend.inspect(image)
    write_json(
        a.output,
        {
            "schema_version": 1,
            "source_sha": repo.head,
            "inputs": lock,
            "images": images,
            "status": "built_requires_independent_acceptance",
        },
        0o644,
    )
    print("Built immutable images. Inventory: " + str(a.output))


if __name__ == "__main__":
    try:
        main()
    except FrameworkError as e:
        raise SystemExit("Blocked: " + str(e))
