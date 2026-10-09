# v2.1.0 Architecture Principles

Status: **pre-implementation normative design**

## Principle P-001 — Backward compatibility boundary

**Status: CONFIRMED**

Backward compatibility is required at the **project** boundary.

A project previously created by the framework must remain updateable and maintainable by v2.1.0 even if its original language-specific generator no longer exists.

The framework does not need transparent runtime compatibility with every historical work-item state format. Historical work-item data may be converted with an explicit migration/conversion tool.

Consequences:

- Existing project source trees must not be forcibly regenerated or restructured during upgrade.
- Old language-specific project layouts remain valid repository layouts.
- Project discovery must analyze what actually exists instead of requiring an old project-type field.
- Work-item migration must preserve audit/evidence references where possible and report any data that cannot be converted.

## Principle P-002 — Technology-neutral modular core

**Status: CONFIRMED**

Framework core must be capable of supporting arbitrary software creation and maintenance without embedding software-domain-specific control flow.

Core owns generic mechanisms such as:

- repository/project identity;
- work-item lifecycle;
- authoritative documents and revisions;
- planning orchestration;
- approvals and invalidation;
- candidate SHA binding;
- evidence integrity;
- provider discovery/resolution;
- capability dependency resolution;
- generic execution boundaries;
- audit trace;
- policy enforcement;
- promotion/closure orchestration.

Core must not own technology-specific assumptions such as:

- ROS distributions;
- Gazebo versions;
- firmware families;
- C/C++/Python/Node project layouts;
- package-manager-specific behavior;
- game engines;
- CUDA versions;
- toolchain-specific project classification.

Technology-specific knowledge belongs in providers, environment projects, or project documents.

## Principle P-003 — Neutral project creation

**Status: CONFIRMED**

Normal project creation establishes a neutral repository/framework envelope. It must not choose a programming language, build system, software domain, or repository layout before planning.

The planner determines repository architecture from:

- the user request;
- authoritative project documents;
- existing repository state;
- deployment/environment constraints;
- available provider capabilities;
- applicable framework policy.

A new project's technology-specific structure is therefore an approved engineering decision, not a project-creation default.

## Principle P-004 — Planner owns architecture; provider owns technology facts; coder owns implementation

**Status: CONFIRMED**

Responsibility boundaries are:

- **User** — authority for deployment/compatibility constraints and explicit product requirements.
- **Planner** — architectural intent, repository/module structure, interfaces, environment requirements, provider/capability requirements, implementation boundaries, and verification requirements.
- **Provider** — technology capability facts, requirement schemas, compatibility rules, environment requirements, bootstrap dependencies, domain acceptance contract, and domain action contract.
- **Tester** — testability analysis, test design, independent verification requirements, and evidence verdicts.
- **Coder** — implementation within the approved architecture; may reject infeasible plan elements but must not silently redesign them.
- **Framework** — lifecycle transitions, dependency/invalidation graph, approvals, evidence, candidate identity, routing, and promotion.

No downstream actor may silently repair an upstream architectural mistake by improvising a different design.

## Principle P-005 — Environment choice and user authority

**Status: CONFIRMED**

Material deployment/test/runtime environment choices must not be silently defaulted.

Order of authority:

1. existing authoritative project/deployment decision;
2. explicit user constraint;
3. user-delegated planner choice.

If the environment is materially ambiguous and the user has not delegated the choice, the planner asks the user to define it clearly.

If the user states that the choice does not matter, the planner may select a supported option, but must document:

- exact selected target;
- selection rationale;
- assumptions;
- compatibility implications;
- provider requirement used;
- whether the choice was user-specified or planner-selected.

A provider reports available compatibility facts; it does not silently choose the project's deployment target.

## Principle P-006 — Test environments are framework-managed projects

**Status: CONFIRMED**

A test/provider environment is implemented and maintained through the same framework lifecycle as an ordinary software project.

A provider supplies the requirements and acceptance contract. The framework uses normal planning, feasibility checks, coding, testing, candidate binding, evidence, approval, and promotion to create, update, or repair the environment implementation.

This avoids provider-specific mini lifecycle engines.

## Principle P-007 — Small and natural core

**Status: CONFIRMED**

Core remains intentionally small. A dependency belongs permanently in core only when removing it would prevent the framework from functioning across essentially all supported software domains.

Examples of likely core primitives:

- framework runtime;
- Git/repository operations;
- generic filesystem/process primitives;
- document/evidence hashing and indexing;
- provider/capability resolution;
- generic environment build/run abstraction;
- lifecycle/policy/audit machinery.

Project toolchains and domain stacks should be modular whenever practical.

The architecture must depend on generic environment-build/run capabilities, not permanently on a specific container engine API. Docker may be the initial backend implementation without becoming the provider contract.

## Principle P-008 — No hidden technology default in core

**Status: CONFIRMED**

Core must not contain defaults such as "ROS means Humble", "firmware means this container", or "new project means C++".

If a technology-specific default exists, it must belong to a provider or an explicit planner decision and remain visible in the approved project architecture.

## Principle P-009 — Current architecture documentation remains implementation-truth only

**Status: CONFIRMED**

`docs/architecture.md` must continue to describe the framework as actually implemented. Pre-implementation v2.1.0 decisions stay in this design set until implementation and acceptance are complete.

This separation prevents architecture documents from claiming behavior that code does not yet provide.
## Principle P-010 — Requirements traceability is universal

**Status: CONFIRMED**

Every project uses stable requirement/component/interface/verification identities and maintains traceability from requirement through Blueprint, implementation, candidate, verification obligation, and evidence.

Traceability is not optional for small projects; the amount of architecture detail may scale down, but the identity/link model remains.

The framework validates these links mechanically where possible and preserves them as project knowledge for debugging, update planning, review, and certification-oriented evidence generation.

This capability supports auditable engineering but does not claim compliance with any external standard unless a project explicitly maps that standard's requirements and passes its required assessment.

## Principle P-011 — The framework dogfoods its own lifecycle

**Status: CONFIRMED**

The framework repository itself is a managed software project. Future self-updates must use the same ProjectBlueprint, traceability, feasibility, approval, candidate, verification, and promotion discipline required for projects produced by the framework.

A stable accepted framework version orchestrates/isolation-controls a candidate framework update. The candidate does not gain authority to declare itself promoted merely by changing its own lifecycle code. An independent recovery boundary remains available.

See `framework-self-development.md`.

## Identifier authority

D-001 through D-043 are defined only in `decision-register.md`. This document previously reused D-* headings for a different local sequence. Its headings are now P-* principles; wording is unchanged. P-005 maps to D-008; P-006 to D-007; P-007 to D-009/D-015; P-008 to D-002/D-008; P-009 is the implementation-truth documentation rule; P-010 maps to D-018; P-011 to D-023.
