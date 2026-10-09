# Minimal Core and Generic Environment Backend

Status: **pre-implementation normative design; core/backend boundaries CONFIRMED**

## Core smallness rule

Framework core contains only technology-neutral capabilities required across software domains. A dependency that exists merely because some projects use a particular language/toolchain/domain belongs in a provider/environment, not permanent core.

A practical inclusion test is:

> Would removing this dependency prevent the framework from functioning across essentially every software domain?

If not, prefer a modular provider/environment.

## `main-development`

`main-development` is the framework **control plane**, not a universal developer workstation. It should contain only what is needed to run the framework and coordinate approved repositories/providers, including conceptually:

- framework runtime and its own runtime dependencies;
- Git/repository/worktree operations;
- basic shell/filesystem/archive/hash/config/schema tooling required by the framework;
- ProjectBlueprint/Plan/work-item/evidence/policy engines;
- provider/capability resolution;
- `ProcessExecutor`;
- generic `EnvironmentBackend` client/orchestration;
- SCM adapters required by the framework.

Toolchains such as C/C++ SDKs, CMake/Ninja, Node.js, Java, Rust, ARM/PlatformIO, ROS/Gazebo, CUDA, browser stacks, and game engines must not remain in permanent core merely for convenience.

Framework-runtime dependencies (for example the Python runtime used to execute the framework) are distinct from project-language toolchains.

## `generic-test`

`generic-test` is the minimal bootstrap/test substrate used to build/start/inspect provider-environment candidates and run framework-owned generic checks. It is not a universal project test image.

It should contain only generic bootstrap/runtime utilities needed by the framework itself, such as a POSIX shell, framework runtime, Git, certificates, basic archive/hash/filesystem/config tooling, and whatever implementation is required to invoke the generic environment backend.

Project/domain toolchains move to providers/environments.

## Two low-level execution primitives

### `ProcessExecutor`

Runs bounded, framework-owned local operations such as Git, hashing, schema validation, SCM commands, and framework integrity checks. It is not a route for provider/domain code to bypass environment isolation.

### `EnvironmentBackend`

Builds and runs isolated environment artifacts. Upper layers depend on this technology-neutral contract rather than Docker/Compose commands.

The first v2.1 implementation may be `DockerBackend`, but provider contracts must not depend on Docker-specific terms or daemon/socket behavior. Future backends may include Podman/rootless containers, VMs, remote workers, or other implementations without changing provider contracts.

## Artifact vs execution

The backend separates an immutable **environment artifact/generation** from a disposable **execution instance**:

```text
Environment project source
        -> backend.build()
immutable environment artifact / generation
        -> backend.create_execution()
isolated execution + overlay
```

One promoted generation may back many concurrent isolated executions.

## Required backend capabilities

The generic contract must support semantics equivalent to:

- build an immutable environment artifact from approved environment-project source;
- inspect/identify artifact and size/digest/provenance;
- create an isolated execution instance from a generation;
- attach approved immutable/read-only inputs;
- allocate isolated writable build/runtime/evidence state;
- apply approved network/device/privilege/resource policy;
- start/execute/stop/destroy bounded executions;
- collect stdout/stderr, exit/result metadata, resource data where available, and declared evidence;
- report artifact/execution/cache storage usage and available storage to the environment manager.

Exact method names/API encoding are implementation details; these semantics are normative.

## Candidate immutability

Authoritative verification receives the candidate project content as read-only input or an equivalent copy-on-write snapshot. Build/install/test outputs go to isolated writable state. A provider/test environment must not silently modify the authoritative candidate worktree.

If a tool requires apparent in-tree writes, the backend may provide a disposable copy-on-write representation; candidate identity remains the approved candidate SHA/content.

## Provider/backend boundary

Providers declare requirements and permissions but do not acquire host/container privileges themselves. Framework policy authorizes the request and `EnvironmentBackend` enforces it. Provider/environment code must not use direct backend escape paths (for example direct privileged Docker invocation) as part of the architecture.

The current Docker socket may remain an implementation/security limitation during migration, but all framework-owned Docker orchestration must be centralized behind the backend so later host-boundary hardening can replace the mechanism without changing provider contracts.

## Inputs, outputs, and evidence

Provider contracts express generic semantics such as:

```text
project input: read-only
build output: writable isolated
runtime/temp: writable isolated
evidence: writable framework-owned destination
```

They do not encode host-specific bind-mount paths. Backend chooses the mechanism. Evidence is collected through a standard outer envelope while provider-specific evidence (JUnit, coverage, traces, screenshots, simulation logs, etc.) remains provider-owned content.

## Network and permissions

Network and other privileges are capability/policy controlled. Environment build may require network while authoritative verification may not. The provider states what is required; framework policy decides what is allowed; backend enforces the resulting execution specification.

## Resource/storage controls

The backend contract must support bounded timeout and should support CPU/memory/storage controls where the implementation can enforce them. It must expose enough storage accounting for the environment manager's space-aware retention policy.

## Authoritative verification rule

Required verification is satisfied only by the provider/environment capability bound in the approved ProjectBlueprint/Engineering Change Package.

Tools incidentally available in `main-development` may be used by Coder for advisory self-tests, exploration, or development feedback, but they **cannot satisfy a required verification obligation** unless that execution itself is the declared provider/environment capability.

This prevents accidental coupling between project evidence and whatever happens to be installed in the framework control plane.
