from pathlib import Path

from robotics_agent_env.test_registry import TestController, TestRegistry


def test_external_humble_contract_and_alias(workspace: Path) -> None:
    registry = TestRegistry()
    lane = registry.get("ros2-gazebo")
    assert lane.name == "ros2-humble"
    assert lane.config["contract"]["expected_ros_distro"] == "humble"
    controller = TestController(registry)
    project = workspace / "projects" / "robot"
    project.mkdir(parents=True)
    command = controller.build_command("ros2-humble", "test", project, ["--clean"])
    assert command[0] == str(workspace / "infrastructure" / "ros2-humble-gazebo-test" / "ros2-test")
    assert command[1:] == ["test", str(project), "--clean"]


def test_compose_lane_never_adds_hardware(workspace: Path) -> None:
    project = workspace / "projects" / "app"
    project.mkdir(parents=True)
    command = TestController(TestRegistry()).build_command("firmware", "test", project, [])
    assert "compose.hardware.yaml" not in " ".join(command)
    assert "--device" not in command
