# Approval Package and Change-Control Model

Status: **pre-implementation normative design**
Last updated: **2026-09-29**

## Purpose

Human approval applies to an **Engineering Change Package**, not to an isolated prose `plan.md`.

The package makes the actual proposed change reviewable before implementation and binds the approved requirements, architecture, constraints, verification obligations, feasibility findings, and Plan together.

## Approval package contents

At minimum an approval-ready package references immutable/revisioned versions of:

- authoritative request and document set;
- applicable project requirements;
- ProjectBlueprint revision;
- implementation Plan revision;
- provider/environment requirements and selected user/planner decisions;
- Provider feasibility result;
- Tester testability/verification-design result;
- Coder implementation-feasibility result;
- implementation scope;
- verification obligations;
- risk/permission assessment;
- traceability coverage report;
- known assumptions, deviations, and unresolved-but-explicit constraints permitted by policy.

Detailed independent Tester cases may remain withheld from Coder according to the future tester/coder handoff policy, but their existence, coverage obligations, and human-review accessibility must not be hidden from the User authority.

## Pre-approval iteration

Planner, Provider, Tester, and Coder may iterate on draft architecture before human approval.

```text
Draft Blueprint/Plan
      -> validation
      -> Provider feasibility
      -> Tester testability
      -> Coder feasibility
      -> Planner reconciliation
      -> revised draft if needed
      -> approval-ready package
```

The user is not asked to approve every internal draft.

## User modification

The user may modify any **semantic content** of the package either:

- directly through supported document/UI editing; or
- by asking Planner/another authorized agent to revise it.

Any semantic modification means the prior package is **not approved**.

The framework must:

1. create/identify a new package revision;
2. preserve the previous revision and audit history;
3. rerun all validations/feasibility checks affected by the modification;
4. have Planner reconcile the changed package with applicable requirements;
5. present a new approval-ready package.

The framework must not treat a user's edit as an already-approved instruction merely because the user authored it. Editing and approving are separate actions.

## Initial implementation approval

No production implementation begins until the approval-ready package receives the required human approval gate.

Approval is bound to package revisions/hashes and the applicable project knowledge baseline.

## Replanning before approval

Replanning before human approval is part of package preparation and does not require repeated human approval.

The final package must show the resulting architecture/Plan and the feasibility findings that shaped it.

## Replanning after approval

If Coder, Tester, or Provider reports an issue that requires **Planner to revise an approval-bound artifact after approval**, the prior approval becomes stale.

Examples include changes to:

- ProjectBlueprint architecture;
- Plan obligations/procedure that Planner owns;
- environment/deployment target requirement;
- component/interface contract;
- verification obligation;
- implementation scope boundary;
- provider/capability requirement;
- risk/permission facts;
- user-visible architectural assumptions.

Flow:

```text
Approved package
      -> infeasible approved element found
      -> structured replan finding
      -> Planner revision
      -> affected validation/feasibility rerun
      -> new approval-ready package revision
      -> human reapproval
      -> implementation resumes
```

This rule is intentionally simple: **a real Planner replan after approval requires human reapproval**.

Coder does not need human reapproval for ordinary internal implementation choices that remain within the approved Blueprint, Plan, scope, interfaces, constraints, risk/permissions, and verification obligations and therefore do not require a Planner revision.

## Infrastructure/environment repair is not automatically a project replan

Replacing or repairing an environment generation while preserving the project's approved compatibility requirement does not, by itself, revise the application ProjectBlueprint or application approval package.

The environment project follows its own framework-managed change/approval lifecycle. The application candidate may resume verification against the new compatible generation when:

- application source/candidate SHA is unchanged;
- approved environment requirement is unchanged;
- no new project permission/risk escalation is introduced.

A change from one incompatible target/family to another is a project architectural change and requires replanning/reapproval.

A repair that requires new privileged host/device access may require a separate security/hardware approval even when it does not change application architecture.

## Approval invalidation and targeted dependency handling

Human approval is package-level, but downstream work/evidence invalidation should be dependency-aware.

When a package is revised after approval:

- the package approval is stale until human reapproval;
- affected implementation/test/evidence descendants are invalidated according to the artifact dependency graph;
- unrelated historical artifacts remain preserved and may remain reusable after reapproval when their dependency inputs are unchanged.

The framework must show the semantic delta between package revisions so the user can review what changed rather than rereading the entire project blindly.

## Direct file edits and integrity fields

Direct edits to semantic project knowledge are valid inputs for a proposed revision.

Direct edits to framework-managed identity/integrity fields are not accepted as authoritative approval changes. Stable IDs, hashes, provenance, revision sequence, and candidate/evidence bindings are regenerated/validated by the framework.

## Approval package modification as a first-class workflow

Future CLI/VS Code interfaces must support at least these user intents without forcing raw state-file manipulation:

```text
view approval package
edit/propose change to package
ask Planner to revise package
show package diff
rerun feasibility/validation
approve final package
```

Exact command names/UI are deferred.
