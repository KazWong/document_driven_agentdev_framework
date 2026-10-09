# Framework ProjectBlueprint — v2.1.0 Design Baseline

Status: **pre-implementation framework ProjectBlueprint design baseline**
Last updated: **2026-09-29**

This document applies the ProjectBlueprint model to the framework itself before the final machine-readable v2.1 schema exists.

It is **not** a claim that the current v2.0.x implementation already provides these behaviors. `docs/architecture.md` remains current implementation truth.

The IDs below are reserved as stable framework project-knowledge identities. When the v2.1 machine-readable ProjectBlueprint is implemented, these identities must be migrated into that canonical representation rather than discarded/reinvented without recorded lineage.

## Project intent

Build a technology-neutral, modular AI-agent software-development framework that can create, update, verify, and maintain arbitrary software projects and its own provider/test environments while preserving human authority, requirements traceability, auditable evidence, and safe approval boundaries.

## Framework requirements

| ID | Requirement |
|---|---|
| `REQ-FW-001` | Core must remain technology-neutral; adding a new software technology must not require technology-name branches in generic core lifecycle logic. |
| `REQ-FW-002` | New project creation must be neutral; Planner defines repository architecture from requirements rather than a language/project-type generator. |
| `REQ-FW-003` | Every project must use a Planner-owned ProjectBlueprint separate from the Plan, with stable requirement/component/interface/verification identities and end-to-end requirements traceability. |
| `REQ-FW-004` | Provider must be a thin modular technology contract defining capabilities, compatibility, environment requirements, acceptance, permissions, actions, and normalized outcomes rather than a second lifecycle engine. |
| `REQ-FW-005` | Provider/test environments must be framework-managed projects supporting compatible environment families and immutable verified generations. |
| `REQ-FW-006` | Material deployment/test/runtime target decisions are user-authoritative; Planner may choose only when delegated and must document the exact choice/rationale. |
| `REQ-FW-007` | Provider/Tester/Coder feasibility failures must route to targeted Planner replanning without downstream improvisation; a Planner replan after human approval requires a revised approval package and human reapproval. |
| `REQ-FW-008` | Provider/environment failure must remain distinct from candidate/project failure and must not create false evidence against the candidate. |
| `REQ-FW-009` | Core/bootstrap must remain small, acyclic, and depend on generic environment build/run primitives rather than a technology-specific provider or permanent Docker-specific contract. |
| `REQ-FW-010` | Framework-created projects that remain in service must have an explicit compatibility/migration path; historical work-item data may use a deterministic conversion tool. |
| `REQ-FW-011` | User semantic edits to an approval package/project knowledge must create a new unapproved revision and rerun affected validation/feasibility before approval. |
| `REQ-FW-012` | The framework repository itself must be developed and updated through the same ProjectBlueprint, traceability, feasibility, approval, candidate, verification, and promotion discipline, with an independent recovery boundary. |
| `REQ-FW-013` | Providers originate only from framework/user-managed provider projects; no external provider catalog/store is trusted. A locally promoted provider may be installed/activated automatically for an approved capability requirement, while creating a missing provider requires human-approved architectural work. |
| `REQ-FW-014` | Required verification must run through the approved Blueprint-bound provider/environment capability; incidental tools in the framework control plane may provide advisory self-tests only. |
| `REQ-FW-015` | Shared environment generations are immutable and space-aware: project dependencies execute in approved isolated overlays, heavy artifacts are garbage-collected by policy, and durable generation/evidence identity survives artifact eviction. |
| `REQ-FW-016` | Project/provider execution must use the generic environment backend with immutable/read-only candidate input and isolated writable outputs; provider/domain code must not bypass it to gain undeclared host/container privileges. |
| `REQ-FW-017` | Role behavior must be enforced by role-specific context/permission/output/workflow contracts, and Tester-to-Coder handoff must expose all approved requirements while retaining a meaningful independent verification subset (approximately 30% of concrete test information by default) outside Coder context. |
| `REQ-FW-018` | Artifact validity/traceability must use an explicit typed dependency DAG with targeted stale propagation and immutable historical revisions/evidence; Project Baselines/savepoints must bound the normal active working graph without deleting traceability. |
| `REQ-FW-019` | The framework must make dependency state understandable and scalable through static graph/subgraph visualization in v2.1, future-compatible canonical graph APIs, and measured performance/storage behavior across large synthetic graphs and archived history. |

| `REQ-FW-020` | Tester owns development-facing regression tests materialized into the product repository and independent tests stored in framework-managed project knowledge; unilateral Coder test changes are blocked, and provider/environment acceptance tests remain separate. |
| `REQ-FW-021` | Every promotion requires a project-defined Final Acceptance Suite drawn from existing VER-* obligations, executed for the exact candidate SHA and required environment generations after prerequisite verification and review. |
| `REQ-FW-022` | Debugger is an on-demand read-only diagnosis role for ambiguous, conflicting, or repeated failures; clear ownership routes directly and a diagnosis grants no approval authority. |

## Components

| ID | Responsibility |
|---|---|
| `CMP-FW-PROJECT-KNOWLEDGE` | Maintain requirements, ProjectBlueprint revisions, stable IDs, design artifacts, and project-level authoritative knowledge. |
| `CMP-FW-PLANNING` | Produce/revise Blueprint and Plan, reconcile feasibility findings with requirements, and prepare approval-ready engineering change packages. |
| `CMP-FW-TRACEABILITY` | Maintain requirement -> design -> implementation -> verification -> evidence links and validate trace completeness. |
| `CMP-FW-PROVIDER-SYSTEM` | Discover/resolve locally promoted provider contracts and expose technology capabilities/compatibility without embedding domain control flow in core. |
| `CMP-FW-ENVIRONMENT-MANAGER` | Resolve/reuse/create/update provider environment families, generations, overlays, and environment-project work. |
| `CMP-FW-WORKFLOW` | Own lifecycle state, targeted replanning routing, candidate identity, failure ownership, and resume behavior. |
| `CMP-FW-APPROVAL` | Build/version Engineering Change Packages, invalidate stale approval, present semantic diffs, and enforce human gates. |
| `CMP-FW-EXECUTION-BACKEND` | Provide generic environment build/run/mount/evidence primitives independent of provider technology and initially implementable with Docker. |
| `CMP-FW-EVIDENCE` | Bind normalized verification/environment evidence to candidate and environment identities and preserve audit history. |
| `CMP-FW-MIGRATION` | Convert supported historical work-item/project metadata and preserve/report provenance without inventing ambiguous data. |
| `CMP-FW-SELF-DEVELOPMENT` | Apply the framework lifecycle to the framework repository while preserving stable-controller/recovery separation. |
| `CMP-FW-ARTIFACT-GRAPH` | Maintain typed artifact dependencies, validity state, baseline/savepoint frontiers, historical archive references, graph queries, compaction, and explanatory graph projections. |

## Interfaces

| ID | Contract |
|---|---|
| `IFACE-FW-BLUEPRINT` | Canonical ProjectBlueprint schema plus stable identity/lineage/traceability semantics. |
| `IFACE-FW-APPROVAL-PACKAGE` | Revisioned Engineering Change Package joining requirements, Blueprint, Plan, feasibility, scope, verification and risk/permission facts. |
| `IFACE-FW-PROVIDER` | Versioned provider capability/requirement/compatibility/bootstrap/acceptance/action/result contract. |
| `IFACE-FW-ENVIRONMENT-BACKEND` | Generic build/run/input-mount/output/evidence/artifact identity interface used by environment projects/providers. |
| `IFACE-FW-EVIDENCE` | Normalized candidate/environment/action/result/failure-owner evidence envelope. |
| `IFACE-FW-ROLE-RESULTS` | Role-specific feasibility/artifact/verdict/diagnostic contracts; must not force incompatible roles into one generic pass/fail semantic. |
| `IFACE-FW-ARTIFACT-GRAPH` | Canonical typed graph/query/action contract used by lifecycle logic, CLI/static rendering, and future VS Code visualization/control surfaces. |

## Verification obligations

| ID | Obligation |
|---|---|
| `VER-FW-001` | Synthetic unknown provider works end-to-end without adding its technology name/special-case branch to generic core. |
| `VER-FW-002` | Small project preserves complete `REQ-* -> CMP/IFACE -> implementation -> VER-* -> evidence` traceability. |
| `VER-FW-003` | Multi-component project supports targeted replan/invalidation while preserving unaffected traceable artifacts. |
| `VER-FW-004` | User edit of an approval package makes it unapproved, reruns affected feasibility, preserves managed IDs/lineage, and requires explicit final approval. |
| `VER-FW-005` | Post-approval Coder/Tester/Provider finding that causes Planner replan produces a new approval package revision and blocks implementation until human reapproval. |
| `VER-FW-006` | Missing provider environment can be created as a framework-managed environment project from lower-level bootstrap capabilities and then used for project verification. |
| `VER-FW-007` | Incompatible environment variants coexist as separate families; compatible projects reuse promoted generations without in-place mutation. |
| `VER-FW-008` | Controlled environment failure is classified as environment failure, preserves the application candidate, repairs via environment-project lifecycle, and re-verifies the same candidate where source is unchanged. |
| `VER-FW-009` | Core QA passes with optional technology providers absent and detects reintroduced domain-specific core hardcoding. |
| `VER-FW-010` | Framework self-change follows its own requirements/Blueprint/feasibility/approval/implementation/evidence flow while the accepted framework remains recoverable. |
| `VER-FW-011` | Framework architecture release is rejected when current ProjectBlueprint/traceability and implemented architecture materially disagree. |
| `VER-FW-012` | Supported older framework-created project can be maintained/migrated without requiring obsolete project-type classification. |
| `VER-FW-013` | Project requiring a locally promoted provider automatically activates/installs it and creates/reuses its environment without external provider retrieval; a genuinely missing provider blocks on an approved provider-project change. |
| `VER-FW-014` | Required verification cannot be satisfied by an incidental compatible tool in `main-development`; the bound provider/environment execution and exact environment generation are recorded in evidence. |
| `VER-FW-015` | Disk-pressure cleanup removes overlays/caches/eligible heavy environment artifacts in policy order while preserving promoted active environment integrity and durable generation/provenance/evidence records. |
| `VER-FW-016` | Authoritative verification cannot modify the candidate worktree; writes occur only in isolated backend-managed state and undeclared direct privileged backend escape is rejected/detected. |
| `VER-FW-017` | Role-enforcement acceptance proves Coder cannot access retained independent test artifacts through normal role context, receives all approval-bound acceptance requirements, cannot satisfy a Tester verdict with a Coder artifact, and independent tests remain traceable to existing `VER-*` obligations without introducing hidden requirements. |
| `VER-FW-018` | Targeted invalidation acceptance proves an upstream change stales only declared descendants, preserves unaffected current artifacts, explains the dependency path, and creates/restores a Project Baseline whose compaction/archive preserves historical traceability. |
| `VER-FW-019` | Graph scalability/visualization acceptance exercises approximately 1k/10k/100k-node synthetic graphs plus large archived history, measures traversal/stale/cycle/baseline/archive/render/memory/storage behavior, and verifies static focused views are produced from the canonical graph without requiring all nodes to be rendered at once. |

| `VER-FW-020` | Verify Tester-owned repository test materialization, blocked Coder edits, isolation of independent test source and logs, and separate provider/environment acceptance storage. |
| `VER-FW-021` | Reject promotion with missing, failed, stale, wrong-candidate, wrong-suite, wrong-environment, or incomplete required-matrix Final Acceptance evidence; permit only exact current passing bindings. |
| `VER-FW-022` | Route clear candidate/test/environment/architecture failures directly; invoke Debugger for ambiguous/conflicting/repeated failures; reject diagnosis as a verification or approval artifact. |

## Traceability matrix

| Requirement | Primary components/interfaces | Verification |
|---|---|---|
| `REQ-FW-001` | `CMP-FW-PROVIDER-SYSTEM`, `CMP-FW-WORKFLOW`, `IFACE-FW-PROVIDER` | `VER-FW-001`, `VER-FW-009` |
| `REQ-FW-002` | `CMP-FW-PROJECT-KNOWLEDGE`, `CMP-FW-PLANNING`, `IFACE-FW-BLUEPRINT` | `VER-FW-002`, `VER-FW-003` |
| `REQ-FW-003` | `CMP-FW-PROJECT-KNOWLEDGE`, `CMP-FW-TRACEABILITY`, `IFACE-FW-BLUEPRINT` | `VER-FW-002`, `VER-FW-003`, `VER-FW-011` |
| `REQ-FW-004` | `CMP-FW-PROVIDER-SYSTEM`, `IFACE-FW-PROVIDER` | `VER-FW-001`, `VER-FW-009` |
| `REQ-FW-005` | `CMP-FW-ENVIRONMENT-MANAGER`, `CMP-FW-EXECUTION-BACKEND`, `IFACE-FW-ENVIRONMENT-BACKEND` | `VER-FW-006`, `VER-FW-007`, `VER-FW-008` |
| `REQ-FW-006` | `CMP-FW-PLANNING`, `CMP-FW-APPROVAL`, `IFACE-FW-APPROVAL-PACKAGE` | `VER-FW-004` |
| `REQ-FW-007` | `CMP-FW-WORKFLOW`, `CMP-FW-PLANNING`, `CMP-FW-APPROVAL` | `VER-FW-003`, `VER-FW-005` |
| `REQ-FW-008` | `CMP-FW-WORKFLOW`, `CMP-FW-EVIDENCE`, `IFACE-FW-EVIDENCE` | `VER-FW-008` |
| `REQ-FW-009` | `CMP-FW-EXECUTION-BACKEND`, `CMP-FW-PROVIDER-SYSTEM`, `IFACE-FW-ENVIRONMENT-BACKEND` | `VER-FW-006`, `VER-FW-009` |
| `REQ-FW-010` | `CMP-FW-MIGRATION`, `CMP-FW-PROJECT-KNOWLEDGE` | `VER-FW-012` |
| `REQ-FW-011` | `CMP-FW-APPROVAL`, `CMP-FW-PROJECT-KNOWLEDGE`, `IFACE-FW-APPROVAL-PACKAGE` | `VER-FW-004` |
| `REQ-FW-012` | `CMP-FW-SELF-DEVELOPMENT`, `CMP-FW-TRACEABILITY`, `CMP-FW-APPROVAL` | `VER-FW-010`, `VER-FW-011` |
| `REQ-FW-013` | `CMP-FW-PROVIDER-SYSTEM`, `CMP-FW-APPROVAL`, `IFACE-FW-PROVIDER` | `VER-FW-013` |
| `REQ-FW-014` | `CMP-FW-EXECUTION-BACKEND`, `CMP-FW-EVIDENCE`, `IFACE-FW-ENVIRONMENT-BACKEND` | `VER-FW-014`, `VER-FW-016` |
| `REQ-FW-015` | `CMP-FW-ENVIRONMENT-MANAGER`, `CMP-FW-EVIDENCE`, `IFACE-FW-ENVIRONMENT-BACKEND` | `VER-FW-015` |
| `REQ-FW-016` | `CMP-FW-EXECUTION-BACKEND`, `CMP-FW-WORKFLOW`, `IFACE-FW-ENVIRONMENT-BACKEND` | `VER-FW-016` |
| `REQ-FW-017` | `CMP-FW-WORKFLOW`, `CMP-FW-TRACEABILITY`, `IFACE-FW-ROLE-RESULTS` | `VER-FW-017` |
| `REQ-FW-018` | `CMP-FW-ARTIFACT-GRAPH`, `CMP-FW-TRACEABILITY`, `CMP-FW-WORKFLOW`, `IFACE-FW-ARTIFACT-GRAPH` | `VER-FW-018` |
| `REQ-FW-019` | `CMP-FW-ARTIFACT-GRAPH`, `CMP-FW-EVIDENCE`, `IFACE-FW-ARTIFACT-GRAPH` | `VER-FW-019` |

| `REQ-FW-020` | `CMP-FW-WORKFLOW`, `CMP-FW-PROJECT-KNOWLEDGE`, `CMP-FW-TRACEABILITY`, `IFACE-FW-ROLE-RESULTS` | `VER-FW-020` |
| `REQ-FW-021` | `CMP-FW-WORKFLOW`, `CMP-FW-EVIDENCE`, `IFACE-FW-EVIDENCE` | `VER-FW-021` |
| `REQ-FW-022` | `CMP-FW-WORKFLOW`, `IFACE-FW-ROLE-RESULTS` | `VER-FW-022` |

## Open dependencies

This Blueprint intentionally references design areas that are still OPEN in `open-decisions.md`, especially concrete schema encoding, role-result schemas, lifecycle states, risk/permission metadata, and policy source-of-truth. Provider origin/install, environment retention/overlays, and minimal-core/backend semantics are already confirmed.

Implementation must resolve those design questions without violating the stable requirement/component/interface/verification identities above. If a confirmed requirement itself changes, update this Blueprint through the documented revision/lineage process rather than silently rewriting it.

## Reconciliation provenance — 2026-10-01

The supplied full archive contains only REQ/VER-FW-001 through 019. The later verification report asserts 020–022 exist but does not include their definitions. The three definitions above are explicit reconstructed wording for already-confirmed D-041/D-042/D-043, respectively. Their proposed numeric mapping is part of ECP-V210-001-r1 review, not a claim that the missing original file was recovered. Existing 001–019 IDs and wording are preserved.
