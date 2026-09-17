# Architecture

## Responsibility boundaries

The main development bundle owns orchestration, Codex role configuration, work-item state, generic Linux verification, firmware emulation, project generation, and Bitbucket packaging. It does not own the ROS image.

The independently installed `ros2-humble-gazebo-test` bundle owns ROS 2 Humble, Gazebo Fortress, colcon/rosdep behavior, simulation processes, and ROS-specific result formats. Integration occurs only through its stable `ros2-test` command and documented output tree.

## Runtime topology

```text
Host /home/kazwong/codes/agents
|
+-- main-development container
|   +-- Codex CLI
|   +-- agentctl
|   +-- testctl
|   +-- Docker socket
|
+-- generic-test container              (created through host Docker)
+-- firmware-test container             (created through host Docker)
+-- ros2-humble-gazebo-test containers  (owned by external bundle)
```

Every container sees `/home/kazwong/codes/agents` at the same absolute path. Therefore a project path emitted by `agentctl` is valid for the host daemon and the delegated test environment without translation.

## Workflow topology

`agentctl` is a deterministic coordinator, not an autonomous swarm. It selects one role based on the persisted state, writes structured prompts, validates structured results, runs deterministic commands, and records transitions. Only `coder` receives `workspace-write`; all other roles are read-only.

One work item maps to one isolated Git worktree. Multiple work items may run concurrently only in separate worktrees. The coordinator never lets multiple coding agents share one mutable checkout.

## Evidence topology

Agent narratives are secondary evidence. The primary sources are process return codes, command vectors, logs, Git state, test summaries, approval snapshots, and SHA-256 indexes. Every state change is recorded in `trace.jsonl`.
