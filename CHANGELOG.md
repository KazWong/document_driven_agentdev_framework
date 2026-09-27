# Changelog

## 2.0.3 — 2026-09-25

### Added

- Deterministic release packaging from the committed Git tree, with source commit/tree provenance and archive self-verification.
- Source-versus-release validation modes, complete release-manifest verification, and committed executable-mode checks.
- Conservative `.env` migration tests covering the 2.0.0, 2.0.1, and 2.0.2 default image tags while preserving custom image settings.
- Release-integrity regression tests for archive reproducibility, runtime-state exclusion, dirty-source rejection, and executable Git modes.

### Changed

- Release archives use the canonical `robotics-ai-agent-dev-env` name regardless of the checkout directory name.
- `scripts/qa.sh` derives the release number from `VERSION` instead of hard-coding it.
- Packaging excludes the legacy tracked `.env` through Git export attributes and ignores local runtime state by construction.

### Fixed

- Operational entrypoints were recorded as non-executable (`100644`) in Git; all required command/test/bootstrap scripts are now committed as `100755`.
- `scripts/sync-codex-config.sh` is now included in executable-mode validation.
- Release packaging no longer captures `.git`, ignored agent/work-item state, credentials, caches, or other untracked working-tree content.
- ZIP artifacts are reproducible for the same source commit, and TAR packaging no longer uses a hard-coded historical timestamp.
- Bootstrap upgrades known default 2.0.0/2.0.1/2.0.2 image tags to 2.0.3 without changing custom image references.

## 2.0.2 — 2026-09-20

### Added

- Project-local canonical work items under `<project>/.agent/work-items/<id>` with lightweight global discovery under `.agent-state/index`.
- Immutable imported document revisions and `agentctl update`, document-bound immutable plan revisions, and `agentctl plan --retry`.
- `agentctl inspect` for non-blocking code/candidate inspection and `agentctl reclassify` for audited one-way risk escalation.
- Provider-neutral `scmctl`, GitHub support through the official `gh` CLI, persistent GitHub CLI state, and automatic GitHub/Bitbucket PR publication.
- Tracked `.agent/branching-policy.md` reference documents plus a TODO for later configurable deterministic branch-policy enforcement.
- Framework-owned non-empty candidate commits and exact-candidate SHA binding across local verification, integration verification, AI review, CI, and remote PR head.
- Detached mode-preserving local verifier checkouts and disposable shared-workspace integration verifier checkouts.
- ROS Docker exec compatibility shim that sources `/opt/ros/humble/setup.bash` in the actual persistent-container test process.
- Required ROS test-count validation; an exit-zero lane that executes zero tests now fails closed.

### Changed

- Development is document-driven. Imported snapshots are authoritative project inputs; the work-item manifest controls lifecycle/risk/scope/verification/isolation/promotion.
- ROS 2 and mixed work-item manifests default to R2 when risk is not explicitly supplied.
- R2/R3 retain safety review and two distinct merge approvals.
- The framework now owns candidate commit, feature-branch push, and PR creation. Human review normally occurs on the open remote PR; human merge approval remains mandatory.
- New work uses `PR_OPEN` rather than a pre-publication `PR_READY` gate.
- Diagnosis recovery invalidates only current bindings downstream of the selected recovery boundary while preserving historical commits, runs, plans, and evidence.
- Python project local verification scopes pytest to `tests/` and the main image permanently provides pytest and Ruff.
- `codex-login-status`/logout are context-aware: direct inside main, `docker compose exec` when main is running, auth helper otherwise.
- `main-development` receives the bounded outer-container permissions needed for the Codex Bubblewrap sandbox; auth/test services keep their tighter profiles.

### Fixed

- Blocked planner reports can no longer become the current executable plan.
- Codex Bubblewrap namespace and fresh `/proc` failures inside the main Docker container.
- ROS persistent-container exec processes losing the ROS environment.
- Host/FUSE executable-bit artifacts causing Ruff EXE002 false failures.
- Integration build/install/log output contaminating the development worktree.
- Integration evidence missing the tested candidate SHA.
- Exit-zero ROS lanes with zero executed tests being recorded as passed.
- `resolve --route implementation` retaining stale candidate/local/integration/review bindings and preventing a true implementation retry.

### Removed

- Unused lifecycle aliases `code`, `test`, `integrate`, `review`, `prepare-review`, and `debug`; `agentctl run` remains the lifecycle driver.
- The human approval gate before PR creation.

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
