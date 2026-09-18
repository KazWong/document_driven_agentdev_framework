# Main robotics AI-agent development environment

Release **2.0.0** implements an **Agent-Gated Software Development Lifecycle** for C, C++, Python, Linux shell, ROS 2, simulation, and firmware work.

The environment is designed for installation below:

```text
/home/kazwong/codes/agents
```

That directory is bind-mounted at the same absolute path in the main development container and every test container. The main container controls sibling test environments through the host Docker daemon.

## What changed from 1.0.0

Version 1.0.0 embedded a ROS 2 Jazzy/Gazebo lane while the independently created robotics test bundle defined a separate ROS 2 Humble/Gazebo Fortress contract. Version 2.0.0 resolves that conflict as follows:

- The embedded Jazzy service is removed.
- `ros2-humble` is the required lane for ROS work.
- The main environment delegates to:

  ```text
  /home/kazwong/codes/agents/infrastructure/ros2-humble-gazebo-test/ros2-test
  ```

- `ros2-gazebo` remains an alias for migration, but resolves to `ros2-humble`.
- The generic Linux and firmware-emulation images remain owned by this main bundle.
- An eighth read-only agent, `safety_reviewer`, is added for R2/R3 changes.
- Prompt-only agent commands are replaced by work-item-aware commands that enforce state, scope, evidence, and human gates.

See [the migration guide](docs/migration-v1-to-v2.md), [the source reconciliation record](docs/source-reconciliation.md), [the changelog](CHANGELOG.md), and [ADR-0001](docs/adr/0001-ros2-humble-baseline.md).

## Architecture

```text
Bitbucket issue / work-item YAML
            |
            v
       agentctl state machine
            |
  +---------+----------+-------------------+
  |                    |                   |
Codex roles       deterministic checks   human gates
  |                    |                   |
planner/coder     local argv commands     plan / PR
reviewers         generic container       merge / hardware
                  firmware emulation
                  external ros2-test
            |
            v
 evidence index + trace.jsonl + PR package
```

The workflow uses one coordinator and one writing agent per worktree. Planning, testing analysis, debugging, review, and safety review are read-only. Agents do not push, create pull requests, merge, flash firmware, expose devices, or command physical motion automatically.

## Included components

- Ubuntu 24.04 main development image.
- Codex CLI and eight role definitions:
  - `planner`
  - `coder`
  - `tester`
  - `integration_tester`
  - `debugger`
  - `reviewer`
  - `review_requester`
  - `safety_reviewer`
- C/C++ compilers, CMake, Ninja, Clang tooling, GDB, LLDB, Valgrind, Cppcheck, ccache, Python tooling, ShellCheck, Bats, Git, Git LFS, Docker CLI, and Docker Compose v2.
- Generic Linux test image.
- Firmware-emulation image with ARM GCC, QEMU, OpenOCD, PlatformIO, DFU, AVR, USB, and serial tools; no device is mapped by default.
- `agentctl` lifecycle coordinator.
- `testctl` test-environment registry and dispatcher.
- `hardwarectl` human-gated device access.
- `bitbucket-pr` dry-run-first pull-request helper.
- C11, C++20, Python, and Bash project generators.
- Bitbucket Pipeline and pull-request templates.
- JSON schemas, append-only transition logs, structured agent results, deterministic test logs, and SHA-256 evidence indexes.

## Directory layout

Recommended host layout:

```text
/home/kazwong/codes/agents/
├── robotics-ai-agent-dev-env/             # this bundle
├── infrastructure/
│   └── ros2-humble-gazebo-test/           # independent testing bundle
│       └── ros2-test
├── projects/
│   └── robot-control/
└── .agent-state/
    ├── codex-home/
    ├── work-items/
    ├── worktrees/
    └── cache/
```

## Installation

Extract this bundle and the independent ROS test bundle beneath the required workspace:

```bash
mkdir -p /home/kazwong/codes/agents/infrastructure

tar -xzf robotics-ai-agent-dev-env-2.0.0.tar.gz \
  -C /home/kazwong/codes/agents

tar -xzf ros2-humble-gazebo-test.tar.gz \
  -C /home/kazwong/codes/agents/infrastructure

cd /home/kazwong/codes/agents/robotics-ai-agent-dev-env
sha256sum -c ARTIFACT-MANIFEST.sha256
./scripts/bootstrap-host.sh
make build
make up
make shell
```

`bootstrap-host.sh` must be run by the non-root user who owns the workspace. It creates `.env`, persistent state/cache directories, and initial Codex configuration. Existing Codex configuration is not overwritten. Apply managed updates explicitly with:

```bash
./scripts/sync-codex-config.sh --force
```

### Codex authentication

The framework supports all three OpenAI Codex CLI authentication paths while keeping credentials in the persistent `CODEX_HOME` under `.agent-state/codex-home`.

**1. Sign in with ChatGPT (browser OAuth)**

For a laptop running Docker locally:

```bash
make codex-login-chatgpt
```

Open the URL printed by Codex in the laptop browser. The temporary `codex-login` service uses host networking so Codex's `localhost:1455` callback is on the Docker host. The normal `main-development` service does not use host networking.

For laptop -> remote host -> Docker, first create an SSH tunnel from the laptop and keep it open:

```bash
ssh -L 1455:127.0.0.1:1455 <user>@<remote-host>
```

Then, on the remote host:

```bash
make codex-login-chatgpt
```

Open the printed URL in the laptop browser. The browser callback to `localhost:1455` crosses the SSH tunnel to the temporary host-networked auth container.

**2. ChatGPT device-code login**

This avoids the localhost callback and is suitable for remote/headless environments:

```bash
make codex-login-device
```

**3. OpenAI API-key login**

Set the API key only in the host shell, then pipe it to Codex on stdin:

```bash
export OPENAI_API_KEY='...'
make codex-login-api-key
unset OPENAI_API_KEY
```

The helper does not place the key in command-line arguments or `.env`.

Check or clear the persistent login with:

```bash
make codex-login-status
make codex-logout
```

## Verify the environments

Inside the main container:

```bash
agentctl doctor
testctl list
testctl doctor generic --execute
testctl doctor firmware --execute
testctl doctor ros2-humble --execute

testctl smoke generic
testctl smoke firmware
testctl smoke ros2-humble
```

For ROS projects, `testctl` delegates without path translation because both environments use the same absolute workspace mount:

```bash
testctl test ros2-humble /home/kazwong/codes/agents/projects/my_robot -- --clean

testctl sim ros2-humble /home/kazwong/codes/agents/projects/my_robot -- \
  --headless --timeout 120 --expect-timeout -- \
  ros2 launch robot_bringup simulation.launch.py gui:=false
```

## Create a project

From the host, after the main container is running:

```bash
make project-c NAME=safety-monitor
make project-cpp NAME=motor-controller
make project-python NAME=telemetry-service
make project-shell NAME=deployment-tools
```

Or inside the main container:

```bash
projectctl create --type cpp --name motor-controller
```

Each generated project contains an initial Git commit, `AGENTS.md`, `.agent` policy files, `.codex` agents and rules, a Bitbucket Pipeline, a pull-request template, tests, and `scripts/ci/verify.sh`.

## Agent-gated workflow

### 1. Create a manifest

```bash
cd /home/kazwong/codes/agents/projects/robot-control
agentctl init-manifest \
  --output work-item.yaml \
  --id RBT-123 \
  --title "Add velocity-command watchdog" \
  --repository projects/robot-control \
  --kind ros2 \
  --risk R2
```

Edit the generated YAML so scope, acceptance criteria, local commands, integration lanes, rollback, and hardware policy are exact.

### 2. Register and plan

```bash
agentctl new work-item.yaml
agentctl run RBT-123
```

The first run invokes the read-only planner and stops at `PLANNED`.

### 3. Approve the plan

```bash
agentctl approve RBT-123 plan \
  --actor kazwong \
  --note "Scope and test matrix approved"
```

The approval snapshots the manifest, current Git SHA, and planning artifacts. Each gate is bound to a context digest; changing the plan, pull-request body, CI commit, or hardware context invalidates prior approvals automatically.

### 4. Implement through PR readiness

```bash
agentctl run RBT-123
```

The coordinator then:

1. Creates an isolated branch and Git worktree.
2. Invokes the single writing `coder` role.
3. Rejects committed or uncommitted changed paths outside the manifest scope.
4. Runs allowlisted local commands directly as argument vectors, never through a shell string.
5. Invokes `tester` against deterministic local evidence.
6. Runs registered integration lanes through `testctl`.
7. Invokes `integration_tester` against process results and summaries.
8. Invokes `safety_reviewer` for R2/R3.
9. Invokes the independent `reviewer`.
10. Invokes `review_requester` and stops at `PR_READY`.

Failures route to `DIAGNOSING`, then the read-only debugger produces a diagnosis. Route it explicitly:

```bash
agentctl resolve RBT-123 --route implementation
# Other routes: plan, local-test, environment, blocked
```

### 5. Authorize and create the pull request

Dry-run payload generation is always allowed:

```bash
bitbucket-pr prepare RBT-123
```

An API write requires a recorded gate and an explicit execution flag:

```bash
agentctl approve RBT-123 pr --actor kazwong
bitbucket-pr create RBT-123 --execute
```

Authentication is read only from environment variables:

- `BITBUCKET_ACCESS_TOKEN`, or
- `BITBUCKET_API_TOKEN` together with `BITBUCKET_EMAIL`.

### 6. Record CI and merge approval

```bash
agentctl record-ci RBT-123 \
  --status passed \
  --url "https://bitbucket.example/build/123"

agentctl approve RBT-123 merge --actor reviewer-a
agentctl approve RBT-123 merge --actor reviewer-b   # required for R2/R3
```

The workflow records approval identities separately and does not count duplicate approvals from one actor.

### 7. Promotion and closure

For non-hardware work:

```bash
agentctl promote RBT-123 \
  --level simulation \
  --evidence "projects/robot-control/.test-results/ros2-humble/simulation/latest.log.summary.json"

agentctl close RBT-123 --actor kazwong --note "Merged and promoted"
```

## Risk classes

| Class | Typical changes | Required controls |
|---|---|---|
| R0 | Documentation, comments, formatting | Plan, optional tests, independent review, one merge approval |
| R1 | Ordinary application code and tools | Local verification, independent review, one merge approval |
| R2 | ROS behavior, control logic, concurrency, safety configuration | Local and integration verification, safety review, two merge approvals |
| R3 | Firmware flashing, actuator interfaces, bootloaders, physical deployment | R2 controls plus two hardware approvals and an explicitly permitted hardware policy |

ROS 2 or mixed projects must include the `ros2-humble` integration lane regardless of risk class.

## Physical hardware

Default services receive no USB or serial device. Physical access is available only for an R3 work item whose manifest contains:

```yaml
promotion:
  physical_hardware: human-approved
```

After CI verification, record two distinct hardware approvals:

```bash
agentctl approve FW-42 hardware --actor hardware-owner-a
agentctl approve FW-42 hardware --actor hardware-owner-b
```

Then a human may open a device-enabled shell:

```bash
hardwarectl shell FW-42 \
  --device /dev/ttyACM0 \
  --actor kazwong \
  --confirm AUTHORIZE-HARDWARE
```

`hardwarectl` records the exact device, command, actor, and exit status in the work-item trace. It is not called by `agentctl run`.

## Evidence model

Every work item is stored under:

```text
/home/kazwong/codes/agents/.agent-state/work-items/WORK-ID/
├── request.yaml
├── status.json
├── trace.jsonl
├── evidence-index.json
├── approvals/
├── artifacts/
├── evidence/
│   ├── local/
│   └── integration/
└── runs/
```

`trace.jsonl` records state changes and explicit operations. `evidence-index.json` contains the path, byte count, and SHA-256 digest of each work-item artifact. External ROS results remain in the ROS test bundle's documented project-local `.test-results/ros2-humble` layout and are referenced by the workflow evidence.

## Security boundary

The main container mounts `/var/run/docker.sock`, which gives it effective control over the host Docker daemon. Use this environment only with trusted repositories and users.

Controls in this release include:

- Non-root development and test users.
- Workspace-only normal Codex writes with network disabled.
- Read-only planning, testing analysis, debugging, review, and safety roles.
- Explicit Codex command rules for Docker, Git publication, destructive Git, privilege escalation, Bitbucket writes, and firmware tools.
- No default hardware devices.
- No shell evaluation of work-item commands.
- An executable allowlist for deterministic local verification.
- Human gates for plans, pull-request writes, merges, hardware access, and physical promotion.
- Dry-run-first Bitbucket API behavior.
- Tokens kept out of `.env`, command arguments, and evidence.

See [security.md](docs/security.md) for residual risks and operational controls.

## QA and packaging

Run source and generated-project validation:

```bash
make qa
```

On a Docker host, include image builds and container smoke tests:

```bash
make qa-docker
```

Create archives after QA:

```bash
make package
```

The preparation environment for this release did not have a Docker daemon, so the delivered QA report distinguishes source/generator tests that were executed from Docker/ROS runtime checks that must be run on the target host. No physical hardware is used by QA.
