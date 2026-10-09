# Provider Environment Lifecycle

Status: **pre-implementation normative design; family/generation/reuse/overlay/retention rules CONFIRMED, exact persistence encoding remains implementation detail**

## Environment as an implementation artifact

A provider environment is a versioned implementation of a provider-defined compatibility specification.

It is not identified merely by provider name, project type, or a mutable container name.

The model separates:

- **provider** — technology contract;
- **environment family** — one compatibility specification;
- **environment generation** — one concrete verified implementation of that family;
- **project overlay/execution state** — project-specific dependencies and disposable runtime state.

## Multiple environment families

Incompatible targets coexist as separate families.

Example concept:

```text
Provider
  |
  +-- Family A
  |     +-- generation A-001
  |     +-- generation A-002 (promoted)
  |
  +-- Family B
        +-- generation B-001 (promoted)
```

A change from one incompatible deployment target to another is not an in-place environment upgrade. It is a different family.

This is required for long-lived project compatibility: supporting a newer environment must not make an older project's target unavailable.

## Family versus generation

Create a **new family** when provider compatibility resolution says the approved project requirement is incompatible with existing families.

Create a **new generation** when the compatibility target remains the same but the environment implementation or provider environment contract changes.

Examples:

```text
Target A -> Target B incompatible
=> new family

Family A environment defect fixed
=> new generation in Family A
```

The provider determines compatibility. Core owns generic family/generation lifecycle.

## Reuse/create/update resolution

Conceptually the provider/framework resolution results in one of:

```text
reuse promoted generation
create new family
create new generation
create project-specific overlay
```

Core does not need to understand why two technology variants are compatible or incompatible.

## Reuse

Projects with compatible requirements should reuse a promoted environment generation where isolation policy permits.

Multiple projects may use the same immutable verified base generation while receiving separate disposable execution state/overlays.

Evidence for each project verification remains separately bound to the project candidate SHA and exact environment generation identity.

## Project-specific overlays

Project-only dependencies should normally be layered on top of a compatible reusable base rather than creating a permanent new environment family for every project.

Provider determines which requirement dimensions affect:

- compatibility family;
- reusable environment generation;
- project-specific overlay;
- disposable runtime state.

Automatic dependency installation into an overlay is allowed only for dependencies already declared/bound by the approved Engineering Change Package. A project/environment execution must not discover an undeclared dependency and silently make it persistent infrastructure.

The backend mechanism for overlays remains an implementation detail, but it must preserve isolation and immutability semantics.

## No in-place mutation of promoted generations

A promoted environment generation must not be modified under running or historical project verification.

Update flow:

```text
Generation N (promoted, still usable)
          |
          +--> Environment project update
                    |
                    v
              Generation N+1 candidate
                    |
                 acceptance
                    |
                    v
               promoted
```

Future jobs use the newly promoted generation. Older generation metadata/artifacts may be retained for rollback and evidence reproducibility subject to retention policy.

## Environment project lifecycle

Environment source/configuration is itself a framework-managed project.

Conceptual relationship:

```text
Environment project source commit A -> generation 004
Environment project source commit B -> generation 005
```

A generation record should bind at least:

- environment project source SHA;
- provider identity/version;
- provider requirement revision/hash;
- compatibility-family identity;
- bootstrap capability identities/versions where relevant;
- built artifact digest/identity;
- acceptance evidence;
- promotion status.

Exact fields/schema are **OPEN**.

## Environment missing

If a required provider is installed/known but no compatible environment generation exists:

```text
project requires capability
  -> provider resolves compatibility specification
  -> no promoted environment satisfies it
  -> create environment-project work item
  -> normal planner/tester/coder lifecycle
  -> provider acceptance
  -> promote generation
  -> resume original project
```

This is a required v2.1 acceptance scenario.

## Environment stale/outdated

If provider requirements change while compatibility family remains the same:

```text
old promoted generation remains immutable
  -> create environment update work item
  -> new candidate generation
  -> acceptance
  -> promote new generation
```

Provider upgrade alone must not automatically rebuild all environment families. Each existing generation is assessed against the new provider contract.

## Environment damaged

If runtime/acceptance evidence establishes that an environment generation is broken:

- preserve the failed evidence;
- mark the generation unusable for new automatic verification if appropriate;
- create environment repair/update work;
- build a new generation rather than mutating the broken promoted artifact in place;
- rerun the original project verification against the same project candidate when project source did not change.

## Project environment choice

Environment requirement is part of project architecture.

If the project already defines a deployment environment, planner preserves it unless the request explicitly changes it.

If the target is materially ambiguous, planner asks the user unless the user has delegated the choice.

If planner chooses, it records the exact concrete requirement and rationale. Provider then resolves that approved requirement into a family/generation.

Therefore:

```text
project target change
=> architecture/replan decision

environment generation change within same compatible target
=> infrastructure lifecycle decision
```

## Historical evidence binding

Verification evidence must bind both:

- application/project candidate SHA; and
- exact environment generation/artifact identity.

This makes later environment upgrades compatible with historical audit and reproduction.

## Environment generation states

A generation lifecycle should distinguish concepts equivalent to:

```text
candidate/building
verifying
verified
promoted
deprecated
retired
```

Exact state names and retention behavior are **OPEN**.

## Space-aware retention and garbage collection

Environment storage must assume the host has finite disk capacity. Correctness and traceability are preserved by separating small durable metadata/evidence from heavy rebuildable artifacts.

Retain long-term where policy requires:

- family/generation identity;
- environment-project source SHA;
- provider identity/version/requirement revision;
- artifact digest even if the artifact is later removed;
- acceptance evidence;
- promotion/deprecation/retirement history;
- project verification references and evidence required by retention policy.

Heavy artifacts are managed under a configurable global storage budget/free-space threshold. Cleanup priority should be approximately:

1. stale disposable execution overlays;
2. expendable caches;
3. failed/unpromoted environment artifacts after diagnosis/evidence capture;
4. retired generation artifacts;
5. deprecated/unreferenced generation artifacts;
6. previous rollback generation artifacts only under stronger disk pressure when not explicitly pinned.

The currently promoted generation for an actively usable family is protected from automatic cleanup. The previous known-good generation should be retained when practical, but limited disk space may justify evicting its heavy artifact after metadata/evidence are retained. Explicit pins or retention policy may require keeping a specific old artifact.

Artifact deletion is not generation-history deletion. A historical generation may remain as metadata with `artifact unavailable`/equivalent state and retain enough provenance to determine whether deterministic rebuild is possible.

Normal successful verification overlays are disposable after evidence collection. Failed overlays may be preserved through diagnosis and then removed unless explicitly pinned. Caches are never authoritative and must be safe to remove.

## Concurrency

Multiple project executions may share the same immutable promoted base generation while using isolated overlays. Lifecycle locking is required for operations such as generation creation/promotion/retirement/garbage collection, not for ordinary independent executions. Concurrent requests for the same missing normalized family should deduplicate to one environment-build/update work item.
