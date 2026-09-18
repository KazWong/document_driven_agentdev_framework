# Changelog

## 2.0.1 — 2026-09-17

### Fixed

- Refresh host UID/GID and Docker socket GID during bootstrap without overwriting unrelated `.env` settings.
- Add a named Docker-socket group to the main image and pass `DOCKER_GID` as a build argument.
- Include templates, Compose files, and local test Docker assets in the main image.
- Install Bubblewrap in the main image so Codex sandboxing fails closed instead of requiring an unrestricted fallback.
- Accept underscore project names.
- Pass Codex global approval arguments before `exec` and restrict the environment inherited by Codex role processes.
- Support three Codex authentication paths: browser ChatGPT OAuth, ChatGPT device-code login, and API-key login.
- Add a temporary host-networked authentication helper so browser OAuth works for both local Docker and laptop-to-remote-host Docker workflows without changing normal container networking.
- Run the external ROS 2 Humble test contract from its declared environment root.
- Expand `agentctl doctor` to check Codex, Docker, Bubblewrap, and Docker-socket accessibility.

## 2.0.0 — 2026-09-03

### Added

- Agent-Gated Software Development Lifecycle with persisted states, deterministic transitions, and explicit human gates.
- Risk classes R0-R3 with independent safety review for R2/R3 and two-person hardware approval for R3.
- Isolated Git worktrees, single-writer enforcement, committed and uncommitted scope-diff validation, and protected-branch controls.
- Structured Codex role execution for planner, coder, tester, integration tester, debugger, reviewer, review requester, and safety reviewer.
- Gate-context hashing so plan, PR, merge, and hardware approvals become invalid when their underlying evidence changes.
- Deterministic local verification without shell-string evaluation and a registry-driven `testctl` dispatcher.
- Human-only `hardwarectl` path with explicit device validation and host device-group propagation.
- Dry-run-first Bitbucket pull-request helper and evidence-index generation.

### Changed

- ROS 2 verification is delegated to the independent ROS 2 Humble/Gazebo Fortress bundle at `infrastructure/ros2-humble-gazebo-test`.
- `ros2-humble` is the canonical required ROS lane; `ros2-gazebo` remains only as a compatibility alias.
- Prompt-only `agentctl` commands now require registered work-item IDs and valid workflow states.
- Generic Linux and firmware-emulation containers remain local to the main development bundle.

### Removed

- Embedded ROS 2 Jazzy/Gazebo service from the main development Compose project.
- Automatic physical-device exposure and agent-driven firmware flashing paths.
