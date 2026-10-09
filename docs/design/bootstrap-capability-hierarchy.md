# Bootstrap Capability Hierarchy

Status: **pre-implementation normative design; small-core/acyclic dependency graph/generic backend rules CONFIRMED, exact core contents OPEN**

## Goal

Keep framework core small while ensuring the framework can create, verify, update, and recover modular provider environments without circular dependencies.

## Fundamental rule

A provider environment must be reproducibly creatable using capabilities below itself in an acyclic dependency graph.

It must not require an existing instance of itself, directly or indirectly, as a mandatory bootstrap dependency.

Previous generations may be optional accelerators/caches only.

## Capability graph, not fixed technology layers

The framework should model bootstrap as a directed capability graph rather than hardcoded environment classes.

A useful conceptual hierarchy is:

```text
Host/bootstrap primitives
        |
        v
Minimal framework + generic execution capability
        |
        v
Modular toolchain/provider environments
        |
        v
Domain/runtime/simulation environments
        |
        v
Optional hardware/HIL capabilities
```

This is explanatory, not a requirement that every provider have exactly four levels.

## Minimal host/bootstrap primitives

Core needs only technology-neutral primitives required to operate the framework and construct lower environments, such as:

- framework runtime;
- Git/repository operations;
- filesystem/process execution;
- hashing/archive/evidence primitives;
- provider/capability discovery;
- generic environment build/run abstraction;
- policy/audit machinery.

Direct unrestricted access to a specific container daemon is not the architectural contract. The initial backend may use Docker, but upper layers depend on generic environment operations.

## Main development environment

`main-development` should contain the minimum tooling required to run the framework and interact with approved repositories/providers. Domain stacks should not accumulate there merely for convenience.

## Generic test/bootstrap environment

`generic-test` should contain enough generic capability to build/start/inspect provider environment candidates and run framework-owned bootstrap checks.

It should not become a universal collection of every software toolchain.

A practical inclusion test is:

> Would removing this dependency prevent the framework from functioning across essentially every software domain?

If not, prefer a provider/module.

## Provider dependency declaration

Conceptual provider dependency metadata:

```yaml
bootstrap_dependencies:
  - capability: environment-build
    purpose: build
    required: true
  - capability: generic-environment
    purpose: verification
    required: true
```

The final schema remains **OPEN**.

## Cycle prevention

Registration/resolution must reject direct and indirect cycles before execution.

Examples:

```text
A -> A
A -> B -> A
A -> B -> C -> A
```

These are provider architecture defects, not transient runtime failures.

## Candidate-environment self-acceptance is allowed

A candidate environment may execute acceptance tests inside itself after generic bootstrap successfully builds/starts it.

Example:

```text
generic environment-build
  -> build candidate provider environment
  -> start candidate environment
  -> run provider acceptance inside candidate
```

This is not circular because creation/startup depended only on lower-level capabilities.

What is prohibited is requiring an already-working environment of the same family as a mandatory prerequisite to build the replacement.

## Failure routing by dependency layer

The capability graph enables ownership routing:

```text
application test fails after valid execution
=> application/candidate failure

provider environment acceptance fails
=> environment-project failure

environment cannot be built because lower capability failed
=> bootstrap capability failure

host execution backend unavailable
=> host/bootstrap failure
```

The framework preserves the dependency path in evidence/diagnosis so a higher layer is not blamed for a lower-layer failure.

## Physical/HIL capabilities

Hardware/HIL should depend on lower software/toolchain capabilities, never the reverse.

Automatic software verification must not implicitly escalate into a physical-access capability.

Privilege is represented through generic consequence/permission metadata, not technology names.

## Core smallness invariant

The v2.1 architecture should be considered suspect whenever a domain/toolchain dependency is proposed for permanent core inclusion. The proposer must justify why the framework cannot operate generally without it.
