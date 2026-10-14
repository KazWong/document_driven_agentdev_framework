"""The only module allowed to orchestrate Docker. No provider gets its socket."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
from typing import Any

from .common import FrameworkError, LeaseRetained, contained, decode, safe_relative
from .execution import ExecutionRequest, ExecutionResult, ProcessExecutor


class DockerBackend:
    name = "docker"
    authoritative = True

    def __init__(self, executor: ProcessExecutor | None = None, *, runtime_profile: Path | None = None):
        self.executor = executor or ProcessExecutor()
        self.runtime_profile = runtime_profile

    def _call(self, args: list[str], **kwargs: Any):
        return self.executor.run(["docker", *args], **kwargs)

    def doctor(self) -> dict[str, Any]:
        if shutil.which("docker") is None:
            return {"ready": False, "reason": "Docker executable is unavailable"}
        try:
            result = self._call(
                ["info", "--format", "{{json .ServerVersion}}"], timeout=10
            )
            return {
                "ready": result.returncode == 0 and not result.timed_out,
                "version": result.stdout.strip(),
                "reason": result.stderr.strip(),
            }
        except FrameworkError as exc:
            return {"ready": False, "reason": str(exc)}

    @staticmethod
    def immutable(artifact: str) -> str:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact):
            raise FrameworkError(
                "execution requires an immutable Docker image ID, never a mutable tag"
            )
        return artifact

    def inspect(self, artifact: str) -> dict[str, Any]:
        self.immutable(artifact)
        result = self._call(["image", "inspect", artifact], timeout=20)
        if result.returncode or result.timed_out or result.output_limited:
            raise FrameworkError(
                "environment image is unavailable: " + result.stderr[:300]
            )
        data = decode(result.stdout)
        if (
            not isinstance(data, list)
            or len(data) != 1
            or data[0].get("Id") != artifact
        ):
            raise FrameworkError("backend returned an inconsistent artifact identity")
        return {
            "artifact_digest": artifact,
            "size_bytes": data[0]["Size"],
            "architecture": data[0].get("Architecture"),
            "os": data[0].get("Os"),
        }

    def build(
        self, source: Path, *, recipe: dict[str, Any], network: bool = False
    ) -> str:
        if (
            "file" not in recipe
            or set(recipe) - {"file", "build_args", "platform"}
            or not isinstance(recipe["file"], str)
        ):
            raise FrameworkError("Docker build recipe requires a relative file")
        dockerfile = recipe["file"]
        extra = []
        for key, value in sorted(recipe.get("build_args", {}).items()):
            if (
                not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise FrameworkError("invalid Docker build argument")
            extra += ["--build-arg", key + "=" + value]
        if "platform" in recipe:
            if recipe["platform"] != "linux/amd64":
                raise FrameworkError("v2.1's accepted build target is linux/amd64")
            extra += ["--platform", recipe["platform"]]
        source = source.resolve()
        contained(source, dockerfile)
        with tempfile.TemporaryDirectory(prefix="framework-build-") as tmp:
            iid = Path(tmp) / "image-id"
            result = self._call(
                [
                    "build",
                    "--network",
                    "default" if network else "none",
                    "--iidfile",
                    str(iid),
                    "--file",
                    str(source / dockerfile),
                    *extra,
                    str(source),
                ],
                timeout=7200,
                max_output=8 * 1024 * 1024,
            )
            if (
                result.returncode
                or result.timed_out
                or result.output_limited
                or not iid.is_file()
            ):
                raise FrameworkError(
                    "environment build did not complete: " + result.stderr[-500:]
                )
            artifact = self.immutable(iid.read_text().strip())
            self.inspect(artifact)
            return artifact

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        image = self.immutable(request.image)
        self.inspect(image)
        if (
            request.memory_mb < 32
            or request.memory_mb > 65536
            or not 0 < request.cpus <= 64
        ):
            raise FrameworkError("invalid execution resource bounds")
        if not 1 <= request.timeout_seconds <= 86400 or request.workdir not in {
            "/work",
            "/project",
            "/output",
        }:
            raise FrameworkError("invalid execution timeout or working directory")
        if (
            not request.project.is_dir()
            or request.project.is_symlink()
            or request.output.is_symlink()
        ):
            raise FrameworkError(
                "execution input/output must be real isolated directories"
            )
        for path in [request.project, request.output, *request.read_only.values()]:
            if any(c in str(path.resolve()) for c in (",", "\n", "\r")):
                raise FrameworkError("unsupported backend mount path")
        request.output.mkdir(parents=True, exist_ok=True)
        if request.output.resolve().is_relative_to(
            request.project.resolve()
        ) or request.project.resolve().is_relative_to(request.output.resolve()):
            raise FrameworkError(
                "execution output and candidate input must be disjoint"
            )
        name = "agent-fw-" + uuid.uuid4().hex
        mounts = [
            "--mount",
            f"type=bind,src={request.project.resolve()},dst=/project"
            + ("" if request.writable_project else ",readonly"),
            "--mount",
            f"type=bind,src={request.output.resolve()},dst=/output",
        ]
        used = {"/project", "/output", "/work", "/tmp", "/proc", "/sys", "/dev"}
        for target, path in sorted(request.read_only.items()):
            if (
                not re.fullmatch(
                    r"/(?:context|tests|artifacts|credentials)(?:/[A-Za-z0-9_.-]+)*",
                    target,
                )
                or target in used
            ):
                raise FrameworkError("unapproved read-only mount target")
            used.add(target)
            mounts += [
                "--mount",
                f"type=bind,src={path.resolve()},dst={target},readonly",
            ]
        for rel in request.protected_paths:
            if "," in rel:
                raise FrameworkError("unsupported protected mount path")
            path = contained(request.project, rel)
            if not path.is_file():
                raise FrameworkError("protected repository test is missing")
            mounts += [
                "--mount",
                f"type=bind,src={path},dst=/project/{safe_relative(rel)},readonly",
            ]
        from .runtime_profile import security_options
        profile_options = security_options(self.runtime_profile, request)
        args = [
            "create",
            *profile_options,
            "--name",
            name,
            "--init",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--network",
            "bridge" if request.network else "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "256",
            "--memory",
            f"{request.memory_mb}m",
            "--cpus",
            str(request.cpus),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--tmpfs",
            "/work:rw,exec,nosuid,nodev,size=256m,mode=1777",
            "--workdir",
            request.workdir,
            "--env",
            "HOME=/work",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            *mounts,
            image,
            *request.argv,
        ]
        attempted = False
        try:
            attempted = True
            result = self._call(args, timeout=30)
            if result.returncode or result.timed_out or result.output_limited:
                return ExecutionResult(self.name, name, image, result, False)
            result = self._call(
                ["start", "--attach", name],
                timeout=request.timeout_seconds,
                max_output=8 * 1024 * 1024,
            )
            if not result.timed_out and not result.output_limited:
                state = self._call(
                    ["inspect", "--format", "{{json .State}}", name], timeout=10
                )
                if state.returncode:
                    raise FrameworkError("cannot establish execution completion")
                data = decode(state.stdout)
                if data.get("Running") or data.get("OOMKilled") or data.get("Error"):
                    raise FrameworkError(
                        "environment execution was interrupted or out of memory"
                    )
                from dataclasses import replace

                result = replace(result, returncode=int(data["ExitCode"]))
            return ExecutionResult(self.name, name, image, result, True)
        finally:
            if attempted:
                try:
                    cleanup = self._call(["rm", "--force", name], timeout=20)
                    absent = "no such container" in cleanup.stderr.casefold()
                    uncertain = (
                        cleanup.timed_out
                        or cleanup.output_limited
                        or (cleanup.returncode and not absent)
                    )
                except FrameworkError:
                    uncertain = True
                if uncertain:
                    raise LeaseRetained(
                        "container cleanup failed; execution lease retained until recovery: "
                        + name
                    )

    def remove(self, artifact: str) -> None:
        self.immutable(artifact)
        result = self._call(["image", "rm", artifact], timeout=60)
        if result.returncode:
            raise FrameworkError("image eviction failed: " + result.stderr[:300])

    def storage(self) -> dict[str, Any]:
        result = self._call(["system", "df", "--format", "{{json .}}"], timeout=20)
        if result.returncode:
            raise FrameworkError("backend storage accounting unavailable")
        return {
            "backend": self.name,
            "rows": [
                decode(line) for line in result.stdout.splitlines() if line.strip()
            ],
        }
