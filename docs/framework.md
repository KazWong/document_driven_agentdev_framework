# Agent-Gated Software Development Lifecycle

## State progression

```text
INTAKE -> PLANNED -> PLAN_APPROVED -> IMPLEMENTED
       human plan gate                |
                                      v
LOCALLY_VERIFIED -> ENV_VERIFIED -> REVIEWED -> PR_READY
                                           human PR gate
PR_READY -> CI_VERIFIED -> MERGE_APPROVED -> PROMOTED -> CLOSED
                         human merge gate
```

Operational transient states are `PLANNING`, `IMPLEMENTING`, `LOCAL_VERIFYING`, `ENV_VERIFYING`, `REVIEWING`, and `PR_PREPARING`. A failed activity enters `DIAGNOSING`; the debugger produces `DIAGNOSED`, and a human routes the work back to planning, implementation, local testing, environment testing, or `BLOCKED`.

## Role separation

- `planner`: creates scope-bound planning artifacts.
- `coder`: sole source writer in the worktree.
- `tester`: evaluates deterministic local evidence.
- `integration_tester`: evaluates environment and simulation evidence.
- `debugger`: diagnoses without editing.
- `reviewer`: independent diff and regression review.
- `review_requester`: creates a PR body but does not create the PR.
- `safety_reviewer`: performs R2/R3 hazard review.

The coder cannot satisfy the independent review gate. The reviewer cannot write production code.

## Human gates

Approvals are individual JSON records containing the actor, timestamp, current state, manifest hash, Git SHA, and artifact hashes. Repeating the same actor does not increase the approval count.

- Plan: one approval for every risk class.
- PR API write: one approval.
- Merge: one approval for R0/R1; two for R2/R3.
- Hardware: two distinct approvals for R3.

## Deterministic verification

Local commands are stored as YAML argument lists and invoked with `shell=False`. The coordinator rejects dangerous executables, inline Python/shell code, sensitive host paths, Docker arguments, Git publication, and firmware tools. Container integration is invoked through the registered `testctl` interface, not by arbitrary model-generated commands.
