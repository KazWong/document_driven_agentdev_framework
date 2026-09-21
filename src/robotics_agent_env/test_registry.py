from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .util import AgentEnvError, env_root, interpolate, load_yaml, resolve_workspace_path, shell_join, workspace_root


@dataclass(frozen=True)
class Lane:
    name: str
    config: dict[str, Any]

    @property
    def capabilities(self) -> set[str]:
        return set(self.config.get("capabilities", []))


class TestRegistry:
    __test__ = False
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.environ.get("TEST_ENV_REGISTRY", env_root() / "config" / "test-environments.yaml"))
        self.raw = load_yaml(self.path)
        if self.raw.get("schema_version") != 1:
            raise AgentEnvError("unsupported test-environment registry schema")
        lanes = self.raw.get("lanes")
        if not isinstance(lanes, dict) or not lanes:
            raise AgentEnvError("test registry must define lanes")
        self._lanes: dict[str, Lane] = {}
        self._aliases: dict[str, str] = {}
        for name, config in lanes.items():
            if not isinstance(config, dict):
                raise AgentEnvError(f"lane '{name}' must be a mapping")
            lane = Lane(name, self._expanded(config))
            self._lanes[name] = lane
            for alias in config.get("aliases", []):
                if alias in self._aliases or alias in self._lanes:
                    raise AgentEnvError(f"duplicate lane alias: {alias}")
                self._aliases[str(alias)] = name

    def _expanded(self, value: Any) -> Any:
        variables = {"ENV_ROOT": str(env_root()), "WORKSPACE_ROOT": str(workspace_root())}
        if isinstance(value, str):
            return interpolate(value, variables)
        if isinstance(value, list):
            return [self._expanded(item) for item in value]
        if isinstance(value, dict):
            return {key: self._expanded(item) for key, item in value.items()}
        return value

    def names(self) -> list[str]:
        return sorted(self._lanes)

    def get(self, name: str) -> Lane:
        canonical = self._aliases.get(name, name)
        try:
            return self._lanes[canonical]
        except KeyError as exc:
            raise AgentEnvError(f"unknown test lane '{name}'; available: {', '.join(self.names())}") from exc

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "lanes": [
                {"name": lane.name, **lane.config} for lane in (self._lanes[name] for name in self.names())
            ],
        }


@dataclass
class TestResult:
    __test__ = False
    lane: str
    action: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane, "action": self.action, "command": self.command,
            "returncode": self.returncode, "passed": self.passed,
            "stdout": self.stdout, "stderr": self.stderr,
        }


class TestController:
    __test__ = False
    def __init__(self, registry: TestRegistry | None = None) -> None:
        self.registry = registry or TestRegistry()

    def build_command(
        self, lane_name: str, action: str, project: Path | None = None,
        args: Sequence[str] = (), hardware: bool = False,
    ) -> list[str]:
        lane = self.registry.get(lane_name)
        action = action.lower()
        if action not in lane.capabilities:
            raise AgentEnvError(f"lane '{lane.name}' does not support action '{action}'")
        if hardware:
            raise AgentEnvError("automatic lane execution never enables physical hardware")
        if project is not None:
            project = resolve_workspace_path(str(project))
        if action in {"test", "sim"} and project is None:
            raise AgentEnvError(f"action '{action}' requires a project path")

        lane_type = lane.config.get("type")
        if lane_type == "external-cli":
            root = Path(lane.config["root"])
            executable = root / lane.config["executable"]
            command = [str(executable), action]
            if project is not None:
                command.append(str(project))
            command.extend(args)
            return command
        if lane_type == "compose":
            compose_bin = os.environ.get("DOCKER_BIN", "docker")
            command = [compose_bin, "compose"]
            for compose_file in lane.config.get("compose_files", []):
                command.extend(["-f", compose_file])
            command.extend(["--project-name", str(self.registry.raw.get("compose_project", "robotics-agent-tests"))])
            service = str(lane.config["service"])
            if action == "build":
                return command + ["build", service]
            if action == "doctor":
                return command + ["config", "--quiet"]
            if action == "shell":
                return command + ["run", "--rm", service, "bash"]
            runner = str(lane.config["runner"])
            command.extend(["run", "--rm", service, runner, action])
            if project is not None:
                command.append(str(project))
            command.extend(args)
            return command
        raise AgentEnvError(f"unsupported lane type: {lane_type!r}")

    def run(
        self, lane_name: str, action: str, project: Path | None = None,
        args: Sequence[str] = (), timeout: float | None = None,
    ) -> TestResult:
        lane = self.registry.get(lane_name)
        command = self.build_command(lane.name, action, project, args)
        if lane.config.get("type") == "external-cli":
            executable = Path(command[0])
            if not executable.is_file():
                raise AgentEnvError(
                    f"external test environment is not installed: {executable.parent}. "
                    "Install ros2-humble-gazebo-test under the documented infrastructure path."
                )
            if not os.access(executable, os.X_OK):
                raise AgentEnvError(f"external test command is not executable: {executable}")
        run_cwd = None
        run_env = None
        if lane.config.get("type") == "external-cli":
            run_cwd = str(Path(lane.config["root"]))
            if lane.name == "ros2-humble" and action == "test":
                docker_name = os.environ.get("DOCKER_BIN", "docker")
                real_docker = shutil.which(docker_name)
                if real_docker is None:
                    raise AgentEnvError(f"Docker executable not found for ros2-humble lane: {docker_name}")
                compat_executable = env_root() / "bin" / "ros2-docker-compat"
                if not compat_executable.is_file() or not os.access(compat_executable, os.X_OK):
                    raise AgentEnvError(f"ROS2 Docker compatibility shim is missing or not executable: {compat_executable}")
                compat_dir = Path(os.environ.get("AGENT_STATE_ROOT", str(workspace_root() / ".agent-state"))) / "cache" / "ros2-docker-compat"
                compat_dir.mkdir(parents=True, exist_ok=True)
                docker_shim = compat_dir / "docker"
                if docker_shim.is_symlink() or docker_shim.exists():
                    if docker_shim.resolve() != compat_executable.resolve():
                        docker_shim.unlink()
                if not docker_shim.exists():
                    docker_shim.symlink_to(compat_executable)
                run_env = os.environ.copy()
                run_env["ROBOTICS_REAL_DOCKER"] = str(Path(real_docker).resolve())
                run_env["PATH"] = f"{compat_dir}:{run_env.get('PATH', '')}"
        try:
            completed = subprocess.run(
                command, cwd=run_cwd, env=run_env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout, check=False,
            )
        except FileNotFoundError as exc:
            raise AgentEnvError(f"test command not found: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            return TestResult(lane.name, action, command, 124, exc.stdout or "", (exc.stderr or "") + "\nTimed out.\n")
        return TestResult(lane.name, action, command, completed.returncode, completed.stdout, completed.stderr)

    def doctor(self, lane_name: str, execute: bool = False) -> dict[str, Any]:
        lane = self.registry.get(lane_name)
        report: dict[str, Any] = {
            "lane": lane.name,
            "type": lane.config.get("type"),
            "description": lane.config.get("description"),
            "capabilities": sorted(lane.capabilities),
            "ready": True,
            "issues": [],
        }
        if lane.config.get("type") == "external-cli":
            root = Path(lane.config["root"])
            executable = root / lane.config["executable"]
            report["root"] = str(root)
            report["executable"] = str(executable)
            if not root.is_dir():
                report["ready"] = False
                report["issues"].append("environment root is missing")
            if not executable.is_file() or not os.access(executable, os.X_OK):
                report["ready"] = False
                report["issues"].append("ros2-test is missing or not executable")
        else:
            report["compose_files"] = lane.config.get("compose_files", [])
            for path in map(Path, lane.config.get("compose_files", [])):
                if not path.is_file():
                    report["ready"] = False
                    report["issues"].append(f"missing compose file: {path}")
        if execute and report["ready"]:
            result = self.run(lane.name, "doctor", timeout=120)
            report["command"] = shell_join(result.command)
            report["returncode"] = result.returncode
            report["stdout"] = result.stdout
            report["stderr"] = result.stderr
            report["ready"] = result.passed
        return report
