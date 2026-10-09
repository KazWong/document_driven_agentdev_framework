# Role Contracts and Tester-to-Coder Handoff

Status: **pre-implementation normative design**
Last updated: **2026-10-01**

## Purpose

The framework must make each agent perform the work of its assigned role through technical controls, not prompt wording alone. Role separation is part of workflow correctness, traceability, independent verification, and prevention of silent architectural substitution.

## v2.1 role set

Confirmed intelligent roles:

- **Planner** — owns ProjectBlueprint, Plan, architecture, requirement reconciliation, and replanning.
- **Coder** — owns implementation inside the approved architecture and implementation traceability.
- **Tester** — owns testability, concrete test design, evidence strategy, and all `VER-*` verification regardless of unit/integration/simulator/provider environment.
- **Reviewer** — evaluates implementation conformance, traceability completeness, evidence completeness, and review findings.
- **Safety Reviewer** — performs consequence/safety review when policy requires it.

Confirmed removals:

- **Review Requester** is removed. Review/PR material is assembled deterministically from structured framework metadata/evidence. Optional wording assistance is non-authoritative.
- **Integration Tester** is removed. Its responsibility is absorbed by Tester.

**Provider is not an intelligent agent role.** It is a technology contract/capability source plus a framework-managed provider project.

**Debugger is retained as an on-demand diagnostic role.** It is invoked only when failure ownership is ambiguous, evidence conflicts, or materially equivalent corrections repeatedly fail; it is not a mandatory pipeline stage.

## Confirmed role ownership

### Planner

Planner creates/revises ProjectBlueprint and Plan and reconciles feasibility findings. Planner owns architectural intent, not production implementation. Planner may propose complete declarative contracts/design artifacts for approval but may not implement production logic, Tester-owned tests, or provider environments before approval.

### Tester

Tester owns testability analysis, concrete test design, verification cases, evidence strategy, and authoritative verification of Blueprint `VER-*` obligations through the approved provider/environment capability. Tester cannot create a hidden requirement through a test.

### Coder

Coder owns implementation inside the approved Blueprint/Plan and produces implementation traceability. Coder must not silently redesign architecture, change approval-bound acceptance criteria, or rewrite Tester-owned independent verification to make a failure pass.

### Reviewer

Reviewer checks implementation conformance to the approved package, scope discipline, maintainability/security findings within review authority, traceability completeness, and evidence completeness. Reviewer does not replace Tester verification.

### Safety Reviewer

Safety Reviewer participates only when consequence/risk policy requires it and produces an independent safety/consequence verdict.

### Debugger

Debugger performs read-only investigation when structured failure ownership is uncertain, evidence conflicts, or materially equivalent corrections repeatedly fail. Debugger produces diagnosis and routing evidence; it does not fix code, rewrite tests, revise Blueprint, repair environments, or approve a candidate. Normal failures with clear ownership bypass Debugger and route directly to the responsible owner.

## Confirmed Tester-to-Coder information split

Coder receives **100% of approved requirements, interfaces, observables, acceptance thresholds, Blueprint `VER-*` obligations, and implementation constraints**. Requirements are never intentionally hidden from Coder.

Tester divides concrete test information into two groups:

1. **Development-facing test information** — approximately **70%** of concrete test design/cases/data by default. Supplied to Coder for feasibility analysis, self-testing, and understanding observable behavior.
2. **Independent verification information** — approximately **30%** retained from Coder context by default and used by Tester for independent verification against the candidate.

The 70/30 split is an engineering target, not a mechanical count. The human user may inspect all test artifacts. Tester is not assumed perfect or exhaustive; independent cases provide meaningful independence, not a claim that all edge cases are known.

Retained independent tests may add undisclosed concrete cases/data/edge-case constructions only within existing approved requirements and `VER-*` obligations. Newly discovered behavior requirements or changed acceptance criteria route to Planner/user reconciliation.

## Concrete test-code ownership

The confirmed ownership model is:

- **Development-facing tests** become maintained product regression tests after approval and are materialized into the product repository. They are Tester-owned/approval-bound artifacts and are protected from unilateral Coder modification. Coder may report a test defect; Tester revises the test if warranted.
- **Independent verification tests** remain versioned framework-managed project knowledge outside normal Coder context. They execute read-only against an exact candidate SHA through the approved provider/environment. They remain inspectable/editable by the human user through controlled framework operations.
- **Provider/environment acceptance tests** remain a third, separate class owned by the provider/environment project and prove the environment capability rather than application behavior.

This model preserves long-term regression maintainability while keeping a meaningful independent verification surface.

## Traceability

```text
REQ-001
   |
   +--> CMP-001 / IFACE-001
             |
             +--> VER-001
                    |
                    +--> TEST-DEV-001   -> development/self-test evidence
                    |
                    +--> TEST-INDEP-001 -> independent Tester evidence

CMP/IFACE -> IMP-* -> candidate SHA
TEST-* + candidate SHA + environment generation -> verification evidence
```

## Agent-enforcement mechanism

Role behavior is enforced through five layers. Exact file/schema names remain implementation details.

### 1. Role contract

A canonical role contract describes responsibility, prohibited substitutions, escalation conditions, required traceability, legal outputs, and legal transitions. Prompts are generated from or validated against this source; prompt text is not the sole policy source.

### 2. Input/context contract

The framework assembles role-specific context. Examples:

- Planner receives requirements, project knowledge, repository facts, provider capability facts, and prior approved architecture.
- Tester receives requirements, Blueprint, interfaces, `VER-*`, provider constraints, and applicable project knowledge.
- Coder receives the approved Engineering Change Package, all acceptance requirements, provider constraints, and development-facing Tester handoff, but not retained independent verification content.
- Reviewer receives approved package, implementation trace, actual diff, candidate identity, and verification evidence.

Independent-test isolation is enforced by context/storage access, not by a prompt request to ignore readable files.

### 3. Permission/tool contract

Roles receive only the write/execute abilities appropriate to their responsibility. Planner cannot mutate product implementation before approval; Coder cannot rewrite framework-managed approval history; Tester cannot silently alter production implementation; Reviewer/Debugger normally have read-only product access plus role-artifact write access.

### 4. Typed output artifact contract

A small common execution envelope may record role, run identity, input hashes, execution success/failure, timestamps, and produced-artifact hashes. Semantic results are role-specific:

- Planner: Blueprint/Plan/replan artifacts.
- Provider feasibility: capability feasibility artifact.
- Tester preflight: testability + test-design artifact.
- Coder preflight: implementation-feasibility artifact.
- Coder implementation: implementation-trace artifact.
- Tester verification: verification verdict + evidence mapping.
- Debugger: diagnosis artifact.
- Reviewer/Safety Reviewer: verdict artifacts.

The framework must not force incompatible roles into a universal `decision=pass/not_applicable` semantic.

### 5. Workflow-transition contract

The state machine accepts only legal artifacts from the expected role at the expected stage. Coder output cannot satisfy a Tester gate; a diagnosis cannot approve a candidate; a Tester test cannot silently define a new requirement.

## Self-tests versus authoritative verification

Coder self-tests are advisory feedback. They do not satisfy required `VER-*` obligations. Authoritative verification requires the exact candidate SHA, approved provider/environment capability, exact environment generation, Tester-owned verification execution/evidence, and traceability back to the applicable `VER-*`.

## Remaining implementation/design questions

- canonical role-contract representation/source and schema generation;
- exact sandbox/tool mapping;
- concurrency/scheduling of Tester design and Coder preparation;
- deterministic review-package rendering format and any optional non-authoritative wording assistance.
