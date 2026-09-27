from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLES = [
    "bin/agentctl", "bin/bitbucket-pr", "bin/hardwarectl", "bin/projectctl",
    "bin/ros2-docker-compat", "bin/scmctl", "bin/testctl",
    "docker/firmware/firmware-test", "docker/generic/generic-test",
    "scripts/bootstrap-host.sh", "scripts/codex-bwrap-compat.sh", "scripts/codex-login.sh",
    "scripts/entrypoint.sh", "scripts/github-login.sh", "scripts/package.sh",
    "scripts/qa.sh", "scripts/sync-codex-config.sh",
]


def _run(*args: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_update_env():
    spec = importlib.util.spec_from_file_location("v203_update_env", ROOT / "scripts" / "update_env.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_git_records_all_operational_entrypoints_as_executable() -> None:
    result = _run("git", "ls-files", "-s", "--", *EXECUTABLES)
    modes = {}
    for line in result.stdout.splitlines():
        mode, _object_id, _stage_and_path = line.split(" ", 2)
        path = _stage_and_path.split("\t", 1)[1]
        modes[path] = mode
    assert set(modes) == set(EXECUTABLES)
    assert all(modes[path] == "100755" for path in EXECUTABLES)
    assert all(os.access(ROOT / path, os.X_OK) for path in EXECUTABLES)


@pytest.mark.parametrize("legacy", ["2.0.0", "2.0.1", "2.0.2"])
def test_env_migration_updates_known_2_0_defaults(legacy: str, tmp_path: Path) -> None:
    module = _load_update_env()
    env = tmp_path / ".env"
    env.write_text(
        "# keep this comment\n"
        "HOST_UID=1\nHOST_GID=2\nDOCKER_GID=3\nDEV_USERNAME=kazwong\nCODEX_VERSION=latest\n"
        f"MAIN_IMAGE=robotics-ai-agent-main:{legacy}\n"
        f"GENERIC_IMAGE=robotics-ai-agent-generic-test:{legacy}\n"
        f"FIRMWARE_IMAGE=robotics-ai-agent-firmware-test:{legacy}\n"
        "CUSTOM_SETTING=preserve-me\n",
        encoding="utf-8",
    )
    module.update_env(env, "1000", "1001", "999", "2.0.3")
    text = env.read_text(encoding="utf-8")
    assert "# keep this comment" in text
    assert "HOST_UID=1000" in text
    assert "HOST_GID=1001" in text
    assert "DOCKER_GID=999" in text
    assert "MAIN_IMAGE=robotics-ai-agent-main:2.0.3" in text
    assert "GENERIC_IMAGE=robotics-ai-agent-generic-test:2.0.3" in text
    assert "FIRMWARE_IMAGE=robotics-ai-agent-firmware-test:2.0.3" in text
    assert "CUSTOM_SETTING=preserve-me" in text


def test_env_migration_preserves_custom_images_and_is_idempotent(tmp_path: Path) -> None:
    module = _load_update_env()
    env = tmp_path / ".env"
    env.write_text(
        "DEV_USERNAME=kazwong\n"
        "MAIN_IMAGE=registry.example/main:custom\n"
        "GENERIC_IMAGE=registry.example/generic:custom\n"
        "FIRMWARE_IMAGE=registry.example/firmware:custom\n",
        encoding="utf-8",
    )
    module.update_env(env, "1000", "1000", "998", "2.0.3")
    once = env.read_text(encoding="utf-8")
    module.update_env(env, "1000", "1000", "998", "2.0.3")
    twice = env.read_text(encoding="utf-8")
    assert once == twice
    assert "MAIN_IMAGE=registry.example/main:custom" in once
    assert "GENERIC_IMAGE=registry.example/generic:custom" in once
    assert "FIRMWARE_IMAGE=registry.example/firmware:custom" in once
    assert "HOST_UID=1000" in once
    assert "HOST_GID=1000" in once
    assert "DOCKER_GID=998" in once


def test_env_migration_adds_missing_framework_defaults(tmp_path: Path) -> None:
    module = _load_update_env()
    env = tmp_path / ".env"
    env.write_text("DEV_USERNAME=kazwong\n", encoding="utf-8")
    module.update_env(env, "1000", "1000", "998", "2.0.3")
    text = env.read_text(encoding="utf-8")
    assert "MAIN_IMAGE=robotics-ai-agent-main:2.0.3" in text
    assert "GENERIC_IMAGE=robotics-ai-agent-generic-test:2.0.3" in text
    assert "FIRMWARE_IMAGE=robotics-ai-agent-firmware-test:2.0.3" in text


def test_package_rejects_dirty_tracked_source(tmp_path: Path) -> None:
    readme = ROOT / "README.md"
    original = readme.read_bytes()
    try:
        readme.write_bytes(original + b"\n")
        result = _run(str(ROOT / "scripts" / "package.sh"), str(tmp_path), check=False)
        assert result.returncode == 2
        assert "uncommitted source changes" in result.stderr
        assert "README.md" in result.stderr
    finally:
        readme.write_bytes(original)


def test_package_is_reproducible_and_excludes_runtime_state(tmp_path: Path) -> None:
    env = ROOT / ".env"
    original_env = env.read_bytes() if env.exists() else None
    state = ROOT / ".agent-state"
    context = ROOT / ".agent-context"
    test_results = ROOT / ".test-results"
    try:
        env.write_text("LOCAL_SECRET=must-not-ship\n", encoding="utf-8")
        (state / "private").mkdir(parents=True, exist_ok=True)
        (state / "private" / "credential.txt").write_text("must-not-ship", encoding="utf-8")
        context.mkdir(exist_ok=True)
        (context / "context.txt").write_text("must-not-ship", encoding="utf-8")
        test_results.mkdir(exist_ok=True)
        (test_results / "evidence.txt").write_text("must-not-ship", encoding="utf-8")

        out1 = tmp_path / "one"
        out2 = tmp_path / "two"
        _run(str(ROOT / "scripts" / "package.sh"), str(out1))
        _run(str(ROOT / "scripts" / "package.sh"), str(out2))

        names = [
            "robotics-ai-agent-dev-env-2.0.3.tar.gz",
            "robotics-ai-agent-dev-env-2.0.3.zip",
            "robotics-ai-agent-dev-env-2.0.3-MANIFEST.txt",
            "robotics-ai-agent-dev-env-2.0.3-PROVENANCE.txt",
            "robotics-ai-agent-dev-env-2.0.3-SHA256SUMS.txt",
        ]
        assert all(_sha(out1 / name) == _sha(out2 / name) for name in names)

        with tarfile.open(out1 / names[0], "r:gz") as archive:
            tar_names = set(archive.getnames())
        with zipfile.ZipFile(out1 / names[1]) as archive:
            zip_names = set(archive.namelist())
        for forbidden in (".env", ".git", ".agent-state", ".agent-context", ".test-results"):
            assert not any(part == forbidden or part.startswith(forbidden + "/") for part in [n.split("/", 1)[1] if "/" in n else n for n in tar_names])
            assert not any(part == forbidden or part.startswith(forbidden + "/") for part in [n.split("/", 1)[1] if "/" in n else n for n in zip_names])

        provenance = (out1 / names[3]).read_text(encoding="utf-8")
        assert "release=2.0.3" in provenance
        assert f"source_commit={_run('git', 'rev-parse', 'HEAD').stdout.strip()}" in provenance
        assert f"source_tree={_run('git', 'rev-parse', 'HEAD^{tree}').stdout.strip()}" in provenance
    finally:
        if original_env is None:
            env.unlink(missing_ok=True)
        else:
            env.write_bytes(original_env)
        shutil.rmtree(state, ignore_errors=True)
        shutil.rmtree(context, ignore_errors=True)
        shutil.rmtree(test_results, ignore_errors=True)
