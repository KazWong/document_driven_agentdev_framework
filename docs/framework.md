# Agent-Gated Software Development Lifecycle

## Document-driven inputs

A work item has two input classes. Imported documents are authoritative project inputs; the manifest controls lifecycle, ownership, risk, scope, deterministic verification, isolation, rollback, promotion, and hardware policy. Documents are copied into `.agent/work-items/<id>/documents` as immutable revisions with SHA-256 metadata. Agents use the active snapshots staged under `.agent-context/<id>/documents` and must block rather than invent missing requirements.

## State progression

```text
INTAKE -> PLANNED -> PLAN_APPROVED
                    |
                    v
               IMPLEMENTED
                    |
              exact-candidate local verification
                    v
             LOCALLY_VERIFIED
                    |
             exact-candidate integration verification
                    v
               ENV_VERIFIED
                    |
          safety/code AI review
                    v
                 REVIEWED
                    |
        automatic feature-branch push + PR create
                    v
                  PR_OPEN
                    |
                CI_VERIFIED
                    |
           human merge approval(s)
                    v
             MERGE_APPROVED -> PROMOTED -> CLOSED
```

Transient states are `PLANNING`, `IMPLEMENTING`, `LOCAL_VERIFYING`, `ENV_VERIFYING`, `REVIEWING`, and `PR_CREATING`. Failures route through `DIAGNOSING` to `DIAGNOSED` or `BLOCKED`.

## Candidate integrity

The framework creates the candidate Git commit after the coder succeeds. It refuses an empty change, refuses out-of-scope source changes, and owns staging/commit mechanics. For work requiring integration, publication requires:

```text
candidate_sha == local_test_sha == integration_test_sha == reviewed_sha == pr_head_sha
```

For work without required integration, the integration SHA is not a publication requirement.

Local verification runs from a detached candidate checkout under `/tmp/robotics-agent-verifier`, including filesystem mode probes and Git 100644/100755 validation. Integration verification runs from `.agent-state/verifiers/integration/.../<candidate>` because sibling Docker test environments must see the same host-visible path. That checkout is disposable; retained evidence is copied into the canonical work item before cleanup.

A required `ros2-humble` test action must provide positive machine-readable executed-test evidence. Zero tests, or inability to establish a positive test count, fails the integration gate even when the external command returns zero.

## Diagnosis recovery

`agentctl resolve` invalidates current bindings at the selected boundary without deleting historical evidence:

- `implementation`: preserve the approved plan; clear current candidate and all downstream current bindings; return to `PLAN_APPROVED`.
- `local-test`: preserve candidate; clear local/integration/review/PR/CI bindings; return to `IMPLEMENTED`.
- `environment`: preserve candidate and local SHA; clear integration/review/PR/CI bindings; return to `LOCALLY_VERIFIED`.
- `plan`: clear current plan/candidate/downstream bindings and return to `INTAKE`.
- `blocked`: enter `BLOCKED`.

Risk escalation with `agentctl reclassify` also preserves history while invalidating current plan/execution state and returning to `INTAKE`.

## Roles

- `planner`: read-only document-bound plan.
- `coder`: sole source writer.
- `tester`: read-only assessment of deterministic local evidence.
- `integration_tester`: read-only assessment of deterministic environment evidence and test counts.
- `debugger`: read-only diagnosis and bounded recovery proposal.
- `safety_reviewer`: R2/R3 read-only safety review.
- `reviewer`: independent read-only code review.
- `review_requester`: read-only PR body preparation; the framework publishes after integrity checks.

## Human gates

Human gates remain for plan approval, merge approval, and applicable hardware execution. There is no human gate before PR creation. R2/R3 require two distinct merge approvals; R3 hardware execution additionally requires two distinct hardware approvals.
