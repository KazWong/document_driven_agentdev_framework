# v2.1.0 Architecture Design Set

Status: **approved design reference; implementation is a release candidate**
Last updated: **2026-10-01**

## Purpose

This directory preserves the approved architecture decisions for the next framework architecture release. Its purpose is to keep future framework updates consistent across separate development sessions and to prevent implementation from silently reintroducing technology-specific or duplicated framework behavior.

These documents retain the design rationale and stable identities. The user approved ECP-V210-001-r1 and all its resolutions, including a clean rewrite. `../architecture.md` describes implemented candidate behavior; `../verification.md` records the remaining release boundary. Proposal-time wording in individual source documents is historical and is superseded by the approved resolution record.

## Authority and precedence

For work targeting v2.1.0:

1. Explicit user requirements and later approved architecture decisions supersede older entries in this design set.
2. This design set is the authoritative pre-implementation architecture constraint.
3. `docs/architecture.md` describes the currently implemented framework and must not be rewritten to claim v2.1.0 behavior before that behavior exists.
4. Implementation code must not resolve an item marked **OPEN** by silently choosing a design. The planner must surface the open item for design approval first.
5. When v2.1.0 is accepted, the final implemented decisions must be reconciled into `docs/architecture.md`, Mermaid diagrams, command reference, operations guide, schemas, role policies, QA, migration documentation, and release notes.

## Release intent

The v2.1.0 effort is an architecture consolidation rather than another sequence of technology-specific hotfixes. This review targets the uploaded v2.0.3 commit 29c44e74ad6e60dc298adbfa60b7402f5ce1b196. The earlier reference to a v2.0.4 development tree is historical, not the implementation baseline. The next architecture must remove the underlying classes of hardcoded assumptions that caused repeated defects.

Project compatibility is the required backward-compatibility boundary. A project previously created by the framework must remain maintainable by the new framework. Historical work-item data does not require transparent runtime compatibility; an explicit conversion tool is sufficient.

## Design documents

| Document | Purpose |
|---|---|
| `v2.1.0-architecture-specification.md` | Consolidated human-readable architecture specification covering the complete v2.1.0 design baseline. |
| `decision-register.md` | Explicit CONFIRMED/PROVISIONAL decision status for future implementation. |
| `architecture-principles.md` | Confirmed architectural ownership rules and non-negotiable invariants. |
| `project-blueprint.md` | Planner-owned ProjectBlueprint contract, stable IDs, mandatory traceability, verification obligations, and Planner artifact boundary. |
| `framework-project-blueprint.md` | Initial self-applied v2.1 framework requirements/components/interfaces/verification IDs and traceability baseline. |
| `workflow-and-replanning.md` | Planner/provider/tester/coder responsibilities, feasibility checks, targeted replanning, and failure ownership. |
| `role-contracts-and-test-handoff.md` | Role-specific enforcement model, typed artifacts, role-context/permission boundaries, and the confirmed ~70/30 Tester-to-Coder test-information split. |
| `approval-and-change-control.md` | Engineering Change Package, user editing, approval invalidation, and post-approval replanning rules. |
| `provider-contract.md` | Technology-neutral provider responsibilities and contract boundaries. |
| `environment-lifecycle.md` | Environment families, generations, reuse/create/update decisions, promotion, repair, and project bindings. |
| `bootstrap-capability-hierarchy.md` | Minimal core, capability dependency graph, cycle prevention, and provider bootstrap rules. |
| `minimal-core-and-environment-backend.md` | Exact minimal-core/control-plane boundary, generic ProcessExecutor/EnvironmentBackend semantics, candidate immutability, and authoritative provider-bound verification. |
| `artifact-dependency-graph-and-baselines.md` | Typed artifact dependency DAG, targeted invalidation, Project Baselines/savepoints, graph compaction/archive, static visualization, future VS Code projection, and scale/performance verification. |
| `final-acceptance-suite.md` | **CONFIRMED** mandatory final-promotion acceptance suite (D-042; approved in the supplied later discussion). |
| `migration-and-acceptance.md` | Project-compatibility policy, work-item conversion, hardcoding-prevention tests, and release acceptance criteria. |
| `framework-self-development.md` | Mandatory rule that the framework develops/updates itself through the same Blueprint, traceability, approval, and verification lifecycle. |
| `open-decisions.md` | Historical open items and their approved resolution reference. |
| `*.mmd` | Editable Mermaid sources for the main proposed flows. |

## Decision-status vocabulary

- **CONFIRMED** — explicitly agreed and may be used as an implementation constraint.
- **PROVISIONAL** — discussed and internally consistent, but should be reconfirmed before code depends on it.
- **OPEN** — not yet decided; implementation must not invent an answer.
- **DEFERRED** — intentionally outside the first v2.1.0 architecture implementation.

## Required future-update behavior

Any agent or human modifying framework architecture for v2.1.0 must:

1. Read this index and every document referenced by the affected design area.
2. Identify whether the requested change conflicts with a **CONFIRMED** decision.
3. If it conflicts, stop architecture implementation and request an explicit decision change rather than silently overriding the existing design.
4. Keep technology/domain names out of framework core control flow unless the item is explicitly documented as a core invariant.
5. Update these documents when a design decision changes.
6. After implementation, update `docs/architecture.md` to describe only the behavior that actually exists.
7. Preserve stable requirement/component/interface/verification IDs and requirement traceability for every project, including the framework project itself.
8. Framework self-updates must follow `framework-self-development.md`; do not bypass Blueprint, feasibility, human approval, candidate/evidence binding, or traceability because the target is the framework itself.

## Core design test

A recurring architecture test is:

> If support for a new software technology requires adding its name or special-case control flow to framework core, the abstraction is incomplete.

Technology names may appear in provider data, project requirements, user documents, evidence, and provider-owned implementation. They should not be required in generic core lifecycle logic.
