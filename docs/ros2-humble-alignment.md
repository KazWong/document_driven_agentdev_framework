# ROS 2 Humble alignment

## Decision

ROS 2 Humble with Gazebo Fortress is the required ROS test baseline. The main development bundle does not build or run a competing ROS 2 Jazzy image.

## Integration contract

The external environment must be installed at:

```text
/home/kazwong/codes/agents/infrastructure/ros2-humble-gazebo-test
```

It must provide an executable:

```text
./ros2-test
```

`testctl` delegates these actions when supported by the external bundle:

- `configure`
- `build`
- `doctor`
- `smoke`
- `test PROJECT ...`
- `sim PROJECT ...`
- `shell`
- `gui-shell`
- `debug-shell`

The process return code is authoritative. Project test summaries are expected below `PROJECT/.test-results/ros2-humble/latest/summary.json`; simulation summaries are expected below `PROJECT/.test-results/ros2-humble/simulation/latest.log.summary.json`.

## Compatibility alias

`ros2-gazebo` and `ros2` resolve to `ros2-humble`. A manifest that explicitly names `ros2-jazzy` is rejected so a migration cannot silently test against the wrong distribution.

## Failure behavior

A missing external bundle produces a deterministic integration failure and routes the work item to diagnosis. The coordinator does not install dependencies, rewrite the path, or fall back to a different ROS distribution.

## v2.0.2 persistent-exec compatibility

Some persistent ROS test containers source `/opt/ros/humble/setup.bash` only in their original entrypoint, while later `docker compose exec` processes start without the resulting shell environment. The main framework places a Docker argv compatibility shim in front of the external `ros2-humble` lane only. The shim rewrites only the `docker compose ... exec ... ros2-test-project` process to source `/opt/ros/humble/setup.bash` in that actual exec process; all other Docker invocations are forwarded unchanged.

The framework also rejects a required Humble test action that reports zero executed tests. Successful build/rosdep stages do not substitute for behavior-test evidence.
