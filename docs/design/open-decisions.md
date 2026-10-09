# v2.1.0 Historical Open Items — Resolved

Status: **resolved by the approved ECP-V210-001-r1**

The user approved all corrections and a clean v2.1.0 implementation. `implementation-resolutions.md` records the adopted resolutions. The original questions below remain for provenance; they are not a new request for approval. Measured budgets and implementation paths are now in the runtime documentation and `.agent/design/implementation-map.json`.

## O-001 — ProjectBlueprint schema encoding

The conceptual ProjectBlueprint contract is CONFIRMED in `project-blueprint.md`. Remaining implementation details are limited to concrete serialization/schema mechanics, including:

- exact field names/types and schema versioning;
- ID allocation/lineage encoding;
- canonical machine-readable file location;
- deterministic dependency/trace-matrix representation;
- how human-edited Markdown/Mermaid proposals reconcile back into the canonical model.

These encoding choices must preserve the confirmed semantics and must not weaken universal requirements traceability.

## O-002 — Legacy/external repository discovery depth

Arbitrary legacy/mixed-repository classification is not a primary v2.1 blocker; the user intends to recreate the small number of such repositories with the new framework where practical.

The remaining requirement is to define the minimum discovery needed to preserve the confirmed project-compatibility boundary for projects that must continue without recreation, without reintroducing `generic/ros2/firmware/mixed` core classification.

## O-003 — RESOLVED: provider origin/availability/install policy

Architecture semantics are CONFIRMED by D-026 and `provider-contract.md`: no external provider catalog/store; providers originate from framework or user, are promoted as managed projects, and available providers may be installed/activated automatically for approved capability requirements. Remaining directory/schema encoding is implementation detail.

## O-004 — Provider contract schema

Convert `provider-contract.md` into concrete versioned schemas/interfaces, including:

- requirement schema;
- capability schema;
- compatibility-resolution response;
- bootstrap dependencies;
- permissions;
- action/result/evidence envelopes;
- failure classifications.

## O-005 — RESOLVED: environment family/generation persistence semantics

Architecture semantics are CONFIRMED by D-011, D-012, D-028 and `environment-lifecycle.md`, including immutable generations, promotion/rollback, evidence separation, space-aware heavy-artifact retention, and concurrent reuse. Concrete storage paths/field names are implementation detail.

## O-006 — RESOLVED: project-specific overlay semantics

Architecture semantics are CONFIRMED by D-013 and D-027: shared promoted bases are immutable, project execution state is isolated, and dependency installation is automatic only when declared/bound by the approved package. Exact overlay backend mechanics are implementation detail.

## O-007 — RESOLVED: minimal core contents boundary

Architecture semantics are CONFIRMED by D-009 and D-029 plus `minimal-core-and-environment-backend.md`: `main-development` is the control plane, `generic-test` is the minimal bootstrap substrate, and domain/toolchain stacks move out of permanent core unless universally required. The implementation audit decides exact package lists under this invariant.

## O-008 — RESOLVED: generic environment backend semantics

Architecture semantics are CONFIRMED by D-015, D-029, D-030, D-031 and `minimal-core-and-environment-backend.md`. Docker may implement the first backend; exact API/method names are implementation detail and may not weaken provider-neutral semantics.

## O-009 — Role contract enforcement and typed results

The architectural direction is defined in `role-contracts-and-test-handoff.md`: role behavior must be enforced through role-specific context, permissions, typed artifacts, and legal workflow transitions rather than prompt wording alone, and incompatible roles must not share one universal semantic pass/fail decision.

Remaining decisions are the exact canonical role-contract source/serialization, schema-composition mechanism, and concrete sandbox/tool mapping. These must align with O-013 single-source-of-truth work.

## O-010 — Tester/coder handoff implementation mechanics

The pre-approval feasibility sequence is CONFIRMED as Provider feasibility -> Tester testability/design -> Coder implementation feasibility -> Planner reconciliation -> human approval-ready package. D-032/D-033 confirm the handoff semantics: Coder sees all requirements/acceptance criteria plus approximately 70% of concrete test information; approximately 30% remains outside Coder context for independent verification, while remaining fully inspectable by the human user. Independent tests may not invent undisclosed requirements.

Remaining implementation decisions are:

- exact Tester artifact/schema;
- how the approximately 70/30 allocation is represented and audited without becoming a brittle mechanical count;
- protected storage/context mechanism for retained independent verification cases;
- whether any preparation/test-design work runs concurrently in the first v2.1 implementation.

## O-011 — RESOLVED: targeted invalidation, baselines, and graph lifecycle

Architecture semantics are CONFIRMED by D-036 through D-040 and `artifact-dependency-graph-and-baselines.md`: typed semantic dependency DAG, targeted `STALE` propagation, immutable history, Project Baselines/savepoints, compaction/archive, static visualization, future VS Code projection, scale/performance verification, and tamper-evident integrity. Exact schema/storage/compression/renderer/API choices are implementation details and may not weaken these semantics.

## O-012 — Lifecycle/state machine changes

Define new states/events for feasibility failures, targeted replanning, provider environment creation/repair, blocked dependencies, and resume behavior.

Determine one canonical ownership source for states/transitions.

## O-013 — Single source of truth for framework policy

Resolve current duplication across Python constants, YAML, JSON Schema, role policy, QA checks, generated project configuration, and provider contracts.

Define which sources are authoritative and which are generated projections.

## O-014 — Risk/permission metadata

Define generic consequence/permission fields used for environment/provider/hardware policy without relying on lane/provider names.

## O-015 — Environment repair/replan loop limits

Define retry/revision limits and escalation policy. Do not hardcode an arbitrary loop count before this is approved.

## O-016 — CLI surface for v2.1

Define normal user commands versus diagnostic/internal primitives, including project creation, provider inspection, environment inspection, work-item migration, and environment maintenance visibility.

## O-017 — RESOLVED: user-selected v2.0.3 baseline and patch delivery

The current user request explicitly selects the uploaded v2.0.3 source and one v2.1.0 patch plus complete environment. Inspection identifies commit 29c44e74ad6e60dc298adbfa60b7402f5ce1b196 and tree c568d386f08e24877251ab69ad47d25309f420e1. This input selection is resolved by the user request; it is not an additional approval request.

## O-018 — Deferred security/lifecycle areas

Confirm exact boundary for items intentionally not solved in the first v2.1 architecture implementation, including Docker-socket/host broker replacement, full physical HIL redesign, remote CI provenance hardening, self-upgrade/rollback, VS Code UI, public IPC/API, and full asynchronous agent execution.

## O-019 — Framework canonical ProjectBlueprint materialization

The self-development rule and initial framework IDs/traceability baseline are CONFIRMED in `framework-project-blueprint.md`. Before v2.1.0 implementation is considered complete, materialize that baseline into the final canonical machine-readable project-knowledge schema/location with preserved identity/lineage.

This is an implementation prerequisite, not permission to bypass the normal approval package.

## O-020 — RESOLVED: Review Requester and Integration Tester roles

D-034/D-035 confirm that v2.1 removes the intelligent `review_requester` and the separate `integration_tester` role. Review/PR material is deterministic framework assembly; Tester owns all `VER-*` verification across approved provider/environment execution.

## O-021 — RESOLVED: Debugger lifecycle status

D-043 is confirmed. Debugger is retained only as an on-demand diagnostic role for ambiguous, conflicting, or repeated failures. Normal failures with clear structured ownership route directly to the responsible owner.

## O-022 — RESOLVED: Final Acceptance Suite

D-042 is confirmed. Every promotable candidate must pass the project-defined Final Acceptance Suite described in `final-acceptance-suite.md`. Remaining implementation details are limited to schema/CLI/execution mechanics and must preserve the confirmed semantics.

Historical questions resolved by D-042 included:

- whether every promotion must run the suite;
- whether it is expressed only as a selected subset of existing `VER-*` obligations;
- the minimum readiness prerequisites;
- required environment-matrix behavior;
- when broader full-suite verification is policy-triggered.

## Concrete proposed resolutions for implementation review

The surrounding `../implementation-decisions.md` and `../proposals/` files propose concrete resolutions for O-001/002/004/009/010/012/013/014/015/016/018/019. These twelve entries remain OPEN until ECP-V210-001-r1 is approved. No current-runtime behavior is claimed by those proposals.
