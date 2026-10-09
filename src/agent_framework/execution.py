"""Bounded trusted processes and a technology-neutral isolated execution port."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from typing import Any, Protocol

from .common import FrameworkError, LeaseRetained


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_limited: bool = False
    duration_seconds: float = 0.0


class ProcessExecutor:
    """For controller-owned operations only; providers never invoke host commands."""

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 60,
        env: dict[str, str] | None = None,
        stdin: bytes | None = None,
        max_output: int = 4 * 1024 * 1024,
    ) -> ProcessResult:
        if (
            not argv
            or any(not isinstance(x, str) or "\x00" in x for x in argv)
            or not 0 < timeout <= 86400
            or max_output < 1
        ):
            raise FrameworkError("invalid bounded process request")
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k
            in {
                "PATH",
                "HOME",
                "LANG",
                "LC_ALL",
                "USER",
                "TMPDIR",
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
            }
        }
        clean_env.update(env or {})
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=clean_env,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise FrameworkError(f"process unavailable: {argv[0]}: {exc}") from exc
        selector = selectors.DefaultSelector()
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        timed_out = limited = False
        input_view = memoryview(stdin or b"")
        written = 0
        for name in ("stdout", "stderr"):
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        if stdin is not None:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")

        def kill() -> None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        try:
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    timed_out = True
                    kill()
                    break
                for key, _ in selector.select(min(0.1, timeout)):
                    if key.data == "stdin":
                        try:
                            if written < len(input_view):
                                written += os.write(
                                    key.fd, input_view[written : written + 65536]
                                )
                            if written == len(input_view):
                                selector.unregister(key.fileobj)
                                key.fileobj.close()
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        except BlockingIOError:
                            pass
                        continue
                    try:
                        chunk = os.read(key.fd, 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    total = len(buffers["stdout"]) + len(buffers["stderr"])
                    buffers[key.data].extend(chunk[: max(0, max_output - total)])
                    if total + len(chunk) > max_output:
                        limited = True
                        kill()
                        break
                if limited:
                    break
            if process.poll() is None:
                remaining = max(0.01, timeout - (time.monotonic() - started))
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    kill()
            process.wait(timeout=5)
        except BaseException:
            kill()
            process.wait(timeout=5)
            raise
        finally:
            selector.close()
            for name in ("stdin", "stdout", "stderr"):
                stream = getattr(process, name)
                if stream and not stream.closed:
                    stream.close()
        return ProcessResult(
            process.returncode,
            *(
                buffers[n].decode("utf-8", errors="replace")
                for n in ("stdout", "stderr")
            ),
            timed_out,
            limited,
            time.monotonic() - started,
        )


@dataclass(frozen=True)
class ExecutionRequest:
    image: str
    argv: list[str]
    project: Path
    output: Path
    timeout_seconds: int
    network: bool = False
    memory_mb: int = 512
    cpus: float = 1.0
    read_only: dict[str, Path] = field(default_factory=dict)
    writable_project: bool = False
    protected_paths: tuple[str, ...] = ()
    workdir: str = "/work"


@dataclass(frozen=True)
class ExecutionResult:
    backend: str
    execution_id: str
    artifact_digest: str
    process: ProcessResult
    prepared: bool


class EnvironmentBackend(Protocol):
    name: str
    authoritative: bool

    def inspect(self, artifact: str) -> dict[str, Any]: ...
    def build(
        self, source: Path, *, recipe: dict[str, Any], network: bool = False
    ) -> str: ...
    def execute(self, request: ExecutionRequest) -> ExecutionResult: ...
    def remove(self, artifact: str) -> None: ...
    def storage(self) -> dict[str, Any]: ...


def capture_execution(
    backend: EnvironmentBackend, request: ExecutionRequest
) -> ExecutionResult:
    """Normalize infrastructure failures without claiming the candidate ran."""
    try:
        return backend.execute(request)
    except LeaseRetained:
        raise
    except FrameworkError as exc:
        import uuid

        return ExecutionResult(
            backend.name,
            "unprepared-" + uuid.uuid4().hex,
            request.image,
            ProcessResult(125, "", str(exc)),
            False,
        )
