# Source reconciliation record

## Basis

This 2.0.0 tree was reconstructed from the two supplied release descriptions:

1. The 1.0.0 main robotics AI-agent development environment.
2. The independent ROS 2 Humble/Gazebo Fortress testing environment.

The original tar/ZIP source trees referenced by those descriptions were not present in the working filesystem. Consequently, this release is a complete replacement source tree implementing the documented capabilities and contracts; it is not a byte-for-byte patch against the unavailable 1.0.0 files.

## Reconciliation decisions

| Documented 1.0.0 capability | 2.0.0 disposition |
|---|---|
| Ubuntu 24.04 main development image | Retained |
| Exact `/home/kazwong/codes/agents` mount | Retained and validated for all local services |
| Persistent `.agent-state` | Retained and expanded for work items, worktrees, approvals, traces, role runs, and caches |
| Docker-socket sibling orchestration | Retained only in the trusted main container |
| Generic Linux test image | Retained |
| Firmware test image | Retained as emulation/default-no-device lane |
| Embedded ROS 2 Jazzy/Gazebo image | Removed |
| Separate ROS 2 Humble/Fortress bundle | Adopted as the canonical external ROS contract |
| `ros2-gazebo` test name | Preserved only as an alias to `ros2-humble` |
| Seven specialist agents | Retained, plus `safety_reviewer` |
| Prompt-only agent commands | Replaced by state-aware work-item commands |
| Bitbucket PR helper | Retained with dry-run default and explicit PR gate |
| C11, C++20, Python, Bash generators | Retained |
| Opt-in physical hardware | Retained only through the R3/two-approval `hardwarectl` path |

## ROS contract alignment

The main bundle delegates these operations to:

```text
/home/kazwong/codes/agents/infrastructure/ros2-humble-gazebo-test/ros2-test
```

Supported delegated actions are `configure`, `build`, `doctor`, `smoke`, `test`, `sim`, `shell`, `gui-shell`, and `debug-shell`. The delegated process exit status is primary evidence. ROS-specific summaries remain in the test bundle's documented `.test-results/ros2-humble` locations and are indexed by the work-item evidence model.

## Deliberately unsupported inference

No undocumented filenames, implementation details, image layers, or helper behavior from the unavailable 1.0.0 archives were assumed. Where a concrete implementation was necessary, 2.0.0 defines and tests a new explicit contract in this repository.
