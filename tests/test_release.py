"""Release conformance must detect regressions in modes and source authority."""

from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_release import check
from build_environments import validate_lock
from agent_framework.common import FrameworkError, read_json, write_json


def copy_source(tmp_path):
    source = Path(__file__).resolve().parents[1]
    root = tmp_path / "source"
    shutil.copytree(
        source,
        root,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".pytest_cache",
            "*.egg-info",
            ".venv",
            "build",
            "dist",
        ),
    )
    return root


def test_release_conformance_and_missing_execute_mode(tmp_path):
    root = copy_source(tmp_path)
    assert check(root)["status"] == "passed"
    (root / "bin/agentctl").chmod(0o644)
    with pytest.raises(FrameworkError, match="executable mode"):
        check(root)


def test_policy_projection_drift_is_rejected(tmp_path):
    root = copy_source(tmp_path)
    path = root / "config/policy.json"
    value = read_json(path)
    value["roles"]["integration_tester"] = value["roles"]["tester"]
    write_json(path, value)
    with pytest.raises(FrameworkError, match="projection drift"):
        check(root)


def test_missing_requirement_mapping_is_rejected(tmp_path):
    root = copy_source(tmp_path)
    path = root / ".agent/design/implementation-map.json"
    value = read_json(path)
    value["requirements"].pop()
    write_json(path, value)
    with pytest.raises(FrameworkError, match="implementation mapping"):
        check(root)


def test_build_lock_rejects_unresolved_or_mutable_inputs():
    base = {
        "ubuntu_image": "ubuntu@sha256:" + "a" * 64,
        "node_image": "node@sha256:" + "b" * 64,
        "codex_version": "1.2.3",
        "platform": "linux/amd64",
    }
    validate_lock(base)
    for field, value in (
        ("ubuntu_image", "ubuntu:latest"),
        ("node_image", None),
        ("codex_version", "latest"),
        ("platform", "linux/arm64"),
    ):
        with pytest.raises(FrameworkError):
            validate_lock({**base, field: value})
