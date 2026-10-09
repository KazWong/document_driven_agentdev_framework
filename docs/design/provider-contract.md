# Provider Contract Model

Status: **pre-implementation normative design**

## Provider purpose

A provider is a thin technology contract between technology-specific knowledge and technology-neutral framework orchestration.

A provider is not a second workflow engine. It does not own a bespoke create/update/repair lifecycle for its environment. The normal framework lifecycle manages provider projects and environment projects.

## Provider responsibilities

A provider defines:

1. stable provider identity and contract version;
2. capabilities it can satisfy;
3. requirement schema for those capabilities;
4. technology compatibility rules;
5. bootstrap capability dependencies;
6. environment requirements;
7. environment acceptance contract;
8. project-facing action contract;
9. permissions/privilege characteristics;
10. normalized evidence/result contract;
11. deterministic failure classification.

## Provider identity

Conceptual model:

```yaml
provider:
  id: example-provider
  version: 1.0.0
  contract_version: 1
```

Provider version, environment generation, and application/project version are independent identities.

## Capabilities

Providers advertise capabilities rather than creating core project types.

Example only:

```yaml
capabilities:
  - id: domain-build
  - id: domain-test
  - id: domain-runtime
  - id: domain-simulation
```

Core treats capability identifiers as provider data. It must not contain technology-specific branches for them.

## Requirement schema

Provider defines which parameters are material to its capabilities and which are required, optional, mutually incompatible, or defaultable only after planner/user decision.

Provider requirement schemas exist so the planner can identify missing architectural information. A materially significant deployment/environment parameter must not be silently defaulted by core.

## Planner/provider boundary

Provider reports facts and options. Planner makes architecture decisions within user constraints.

Example responsibility split:

```text
Provider: "variants A and B are supported and incompatible."
Planner/User: "this project targets variant A."
Provider: "variant A resolves to compatibility specification X."
```

Provider must not silently switch the project to a different deployment target because it is newer or already installed.

## Compatibility resolution

Provider normalizes an approved requirement into a deterministic environment compatibility specification.

Conceptual response:

```yaml
environment_spec:
  compatibility_key: provider-defined-deterministic-key
  constraints:
    ...
```

The framework uses the compatibility result to determine whether an existing environment family can satisfy the requirement.

Compatibility logic belongs to provider, not core.

Given the same provider version and concrete requirement input, compatibility resolution must be deterministic. Relative concepts such as "latest" must be made concrete by the planner before binding the project architecture.

## Bootstrap dependencies

Provider declares lower-level capabilities required to create and validate its environment.

```yaml
bootstrap:
  requires:
    - generic-environment
    - environment-build
    - environment-run
```

Dependencies form a directed acyclic graph. A provider environment may not directly or indirectly require itself as a mandatory bootstrap dependency.

Previous environment generations may be optional accelerators/caches but must not be mandatory for reproducible bootstrap.

## Environment requirements

Provider specifies what an implementation must satisfy, not necessarily how it must be implemented.

Conceptual example:

```yaml
environment_requirements:
  required_capabilities:
    - build
    - test
  interfaces:
    project_input: required
    evidence_output: required
  restrictions:
    physical_hardware: false
```

These requirements become authoritative inputs to the environment project's planner.

## Acceptance contract

Provider defines how a candidate environment proves it supplies the claimed capabilities.

Acceptance may include:

- structural validation;
- startup/readiness checks;
- building a known sample;
- executing known behavior;
- transport/API checks;
- simulation/runtime checks;
- normalized evidence-output checks.

Provider acceptance validates the candidate environment generation. It must not require an existing instance of the same environment as a mandatory prerequisite.

## Runtime action contract

After an environment generation is promoted, the provider describes the project-facing actions it supports.

Conceptual action:

```yaml
actions:
  test:
    inputs:
      project_path: required
      candidate_sha: required
    evidence: required
```

Technology-specific commands remain provider/environment implementation details. Core handles authorization, candidate binding, invocation boundary, result envelope, and evidence persistence.

## Normalized outer result

All providers return a common outer result envelope. Provider-specific details may exist under provider-owned evidence.

Conceptual result:

```yaml
result:
  status: passed
  provider:
    id: example-provider
    version: 1.0.0
  environment:
    family: family-id
    generation: generation-id
  action: test
  candidate_sha: abc123
  candidate_evaluated: true
  evidence:
    - summary.json
```

Environment failure example:

```yaml
result:
  status: environment_failure
  candidate_evaluated: false
  failure:
    class: environment_corrupted
    stage: preparation
```

## Failure classes

The contract must support deterministic routing for at least:

- candidate/verification failure;
- environment failure;
- unsupported requirement;
- provider contract failure;
- bootstrap failure;
- transient failure.

The exact schema names remain **OPEN** until the provider result schema is designed.

## Privilege metadata

Provider must declare privilege/security characteristics independently of technology names.

Conceptual properties may include:

```yaml
permissions:
  network: required
  host_filesystem: limited
  physical_hardware: false
  privileged_runtime: false
  destructive_operation: false
```

Policy acts on consequences/privileges, not lane/provider names.

## Provider origin, availability, and installation

The v2.1.0 architecture has **no external provider marketplace/catalog and no outsourced provider trust path**. A provider originates from either:

- the framework itself; or
- the user.

Provider source is treated as a framework-managed provider project. Copying or declaring provider source does not make it executable infrastructure. A provider becomes **locally available** only after its provider project passes the applicable Blueprint, feasibility, approval, implementation, verification, and promotion lifecycle.

The framework maintains a local index of promoted/available providers and their immutable identity/provenance metadata. This is an index of locally created/promoted artifacts, not a remote trust store.

Projects request capabilities. They do not retrieve providers from the Internet and cannot silently introduce executable provider infrastructure.

When an approved project requires a capability:

- if a compatible promoted provider is locally available, provider activation/installation and compatible environment creation may proceed automatically under the already-approved permission/risk envelope;
- if no provider exists, the project is blocked on creation of a provider project; creating that new provider is an architectural change requiring human approval;
- if new provider/environment operation requires permissions outside the approved package, the applicable consequence-based approval gate is required.

Provider installation is therefore not itself the primary security gate. Permissions and consequences are. A provider may state what it requires, but framework policy decides what it receives.

Manual user-supplied provider source may be imported as a provider project, but must follow the same promotion lifecycle before it becomes locally available.

Provider upgrades are new promoted provider-project revisions. They must not silently rewrite existing environment generations. Existing generations are assessed for compatibility; affected families produce new environment generations through the normal environment-project lifecycle. Rollback keeps provider identity/provenance and should preserve at least the previously promoted provider revision when practical.

Provider IDs/versions must be bound to immutable source/artifact digests so an identity cannot silently change contents.

## Provider as a managed project

Provider source itself should eventually be maintainable through the framework lifecycle:

```text
provider project
  -> plan
  -> feasibility
  -> implementation
  -> provider-contract validation
  -> candidate
  -> acceptance
  -> promotion
```

This keeps provider maintenance inside the same evidence/gate model rather than creating a parallel update mechanism.

## Core-abstraction test

A provider design fails the v2.1.0 architecture if adding a new software technology requires new technology-specific branches in core lifecycle logic.
