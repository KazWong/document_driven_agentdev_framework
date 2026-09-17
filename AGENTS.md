# Repository agent contract

This repository uses the Agent-Gated Software Development Lifecycle.

1. Begin work through `agentctl new` and an approved work-item manifest.
2. Treat the manifest scope and acceptance criteria as authoritative.
3. Use one coding agent per Git worktree. Parallel agents may investigate or review read-only evidence, but must not share write ownership.
4. Never claim a pass without process exit codes and machine-readable evidence.
5. ROS 2 work must use the external `ros2-humble` test lane. `ros2-jazzy` is retired.
6. The coding agent cannot be the final reviewer.
7. Do not push, create pull requests, merge, flash firmware, expose devices, run HIL, or command physical robot motion without the applicable human gate.
8. Preserve `.agent-state/work-items/*/trace.jsonl` and evidence. Do not rewrite or delete workflow history.
9. Route failures through the debugger and a bounded correction; do not make unrelated changes until tests happen to pass.
10. Secrets must stay in the environment or credential store and must never be committed or copied into evidence.
