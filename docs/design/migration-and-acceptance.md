# v2.1.0 Migration and Acceptance Plan

Status: **working acceptance plan; compatibility boundary CONFIRMED, detailed acceptance mechanics PROVISIONAL**

## Compatibility policy

The required compatibility boundary is existing framework-created **projects**.

v2.1.0 must be able to maintain projects created by earlier framework versions even when their repository layout reflects old language-specific generators.

It must not require those repositories to be regenerated into a new neutral layout.

## Work-item conversion

Transparent compatibility with old work-item state is not required.

Provide an explicit conversion/migration tool that:

- detects supported historical work-item versions;
- performs a deterministic conversion into the current schema;
- preserves immutable request/document history where possible;
- preserves evidence/audit references where possible;
- records conversion provenance;
- reports fields/artifacts that cannot be converted;
- refuses ambiguous/destructive conversion rather than inventing data;
- can validate conversion before replacing/activating migrated state.

Exact CLI and migration-version support are **OPEN**.

## Existing projects

For an existing repository, v2.1.0 must discover repository facts and available provider capabilities rather than forcing a single language/domain classification.

An intentionally mixed repository is valid. Mixed-language/domain support is a consequence of capability composition rather than a project type named `mixed`.

## Hardcoding-prevention acceptance test

v2.1.0 must include at least one synthetic provider whose technology name is unknown to core source.

The acceptance test must prove that without adding a technology-specific core branch the framework can:

1. discover/register the provider;
2. expose its capability requirements to planning;
3. resolve environment compatibility;
4. create a missing environment project;
5. build and accept an environment generation;
6. bind a project verification action to that generation;
7. execute verification and capture normalized evidence;
8. route a controlled environment failure correctly.

Core QA must also pass with optional ROS/firmware providers absent.

## Environment lifecycle acceptance scenarios

### Missing environment

Start with provider contract available and compatible environment absent.

Expected:

```text
requirement -> environment creation work item -> accepted/promoted generation -> project verification
```

### Outdated environment

Start with an older promoted generation that does not satisfy the latest applicable provider environment contract.

Expected:

```text
new generation created and verified; old generation remains immutable during transition
```

### Damaged environment

Introduce a controlled environment defect.

Expected:

- provider reports environment failure rather than candidate failure;
- candidate is marked not evaluated when appropriate;
- repair/update environment work is created;
- new generation is accepted;
- same application candidate is reverified if project source did not change.

### Incompatible environment families

Create two projects requiring incompatible variants supplied by one provider.

Expected:

- separate environment families coexist;
- adding the second family does not mutate/remove the first;
- each project resolves to a compatible promoted generation.

### User environment authority

Verify:

- explicit deployment constraint is preserved;
- materially ambiguous target causes planner/user clarification unless user delegated choice;
- delegated planner choice is concrete, visible, documented, and approval-bound;
- provider never silently substitutes an incompatible target.

## Replanning acceptance scenarios

Inject a coder feasibility failure in one blueprint element.

Expected:

- coder does not improvise architecture;
- structured targeted replan request is recorded;
- planner revises the affected area;
- dependent artifacts are invalidated;
- unrelated artifacts remain valid where dependency information proves independence;
- changed architecture receives required approval before implementation resumes.

Also inject provider/tester feasibility failures and verify correct routing.

## Evidence acceptance

Every project verification must bind:

- candidate SHA;
- provider identity/version;
- environment family/generation or equivalent immutable environment artifact identity;
- action identity;
- normalized outcome;
- candidate-evaluated flag;
- evidence artifacts;
- failure owner/class when unsuccessful.

## Documentation acceptance

Before v2.1.0 release acceptance:

- reconcile implemented decisions into `docs/architecture.md`;
- update Mermaid architecture/lifecycle/verification/trust diagrams;
- update command reference and operations guide;
- update role policies and schemas;
- update migration documentation;
- update QA maps;
- ensure no design document claims an unimplemented behavior as current architecture;
- preserve unresolved post-v2.1 items in TODO/design docs.
## ProjectBlueprint and traceability acceptance

v2.1.0 acceptance must prove on both a small project and a multi-component project that:

- Planner creates a ProjectBlueprint separate from the implementation Plan;
- stable `REQ-*`, `CMP-*`, `IFACE-*`, and `VER-*` identities survive revisions appropriately;
- Coder implementation trace maps candidate changes to approved Blueprint elements;
- Git-derived changed paths are checked against Coder trace rather than trusting it blindly;
- Tester evidence maps to verification obligations and applicable requirements/components/interfaces;
- missing mandatory trace links block completion;
- targeted replan preserves applicable original requirements and records changed/unchanged elements;
- post-approval Planner replan requires a new human-approved Engineering Change Package.

## User-edit acceptance

Acceptance must prove that a user can modify semantic content in an approval package, directly or through an agent request. The modification must:

- make the package unapproved;
- create/preserve revision history;
- rerun affected validation and Provider/Tester/Coder feasibility;
- preserve framework-managed stable IDs/integrity metadata or update them through controlled lineage operations;
- require explicit human approval of the final revised package before implementation.

## Framework self-development acceptance

Before v2.1.0 is considered complete, the framework repository itself must have and use the same project-knowledge model. Acceptance must demonstrate at least one controlled framework change where:

1. a framework requirement/Blueprint element is identified;
2. Planner creates a traceable change package;
3. Provider/Tester/Coder feasibility completes;
4. human approval gates implementation;
5. Coder trace maps framework code/docs/config changes to approved IDs;
6. verification evidence maps to framework `VER-*` obligations;
7. the candidate framework is tested in isolation while the accepted framework remains recoverable;
8. architecture/project knowledge is reconciled after acceptance.

QA must reject a release candidate that changes framework architecture while leaving its canonical ProjectBlueprint/traceability inconsistent.

## Reconciled confirmed acceptance — D-041/D-042/D-043

Acceptance must demonstrate protected Tester-owned product tests, independent tests outside Coder filesystem/context, and separate provider/environment acceptance artifacts. Every promotable candidate must pass a fresh exact-candidate Final Acceptance Suite on every required environment generation; stale, failed, missing or wrong-bound results must block promotion. Clear failures route directly to their owner; ambiguous, conflicting or repeated failures may use the read-only on-demand Debugger. These are confirmed semantics, not provisional proposals. The concrete scenarios and implementation mechanics are proposed in the surrounding ECP.
