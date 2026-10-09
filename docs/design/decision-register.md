# v2.1.0 Architecture Decision Register

Status: **approved decision authority — D-001 through D-043**
Last updated: **2026-10-01**

All 43 entries below are confirmed. Remaining implementation choices were resolved by the user-approved ECP; see `implementation-resolutions.md`. Architecture principles use P-* and do not duplicate decision IDs.

| ID | Status | Decision |
|---|---|---|
| D-001 | CONFIRMED | Backward compatibility is required for framework-created projects. Historical work-item state may be handled by an explicit conversion tool rather than transparent runtime compatibility. |
| D-002 | CONFIRMED | Framework core is technology-neutral and modular; it must support arbitrary software domains without hardcoded domain branches. |
| D-003 | CONFIRMED | New project creation is neutral. Planner defines the repository architecture based on project requirements rather than a language/project-type generator. |
| D-004 | CONFIRMED | Planner owns architecture, provider supplies technology facts/contracts, tester owns testability/verification design, coder implements approved architecture, and framework owns lifecycle/evidence/gates. |
| D-005 | CONFIRMED | A coder/provider/tester finding that invalidates a plan element causes targeted replanning; downstream roles do not silently improvise a replacement architecture. |
| D-006 | CONFIRMED | Provider/environment failure must be distinguished from candidate failure; an environment failure does not establish a project defect. |
| D-007 | CONFIRMED | Test environments are framework-managed projects. Provider supplies environment requirements/acceptance; normal framework workflow creates, updates, repairs, verifies, and promotes the implementation. |
| D-008 | CONFIRMED | Material deployment/test/runtime target choices are user-authoritative. Planner asks when ambiguous unless user delegates the choice; delegated choices are concrete, documented, and approval-bound. |
| D-009 | CONFIRMED | Keep core small and natural. Domain/toolchain stacks should be modular unless they are genuinely required for framework operation across software domains. |
| D-010 | CONFIRMED | Provider is a thin technology contract, not a second lifecycle engine. It declares capabilities, requirement schema, compatibility, environment requirements, acceptance, actions, permissions, and normalized results. |
| D-011 | CONFIRMED | Provider requirements resolve into compatibility families so incompatible targets can coexist while compatible projects reuse a promoted environment implementation. |
| D-012 | CONFIRMED | Environment implementations are immutable generations within a family; updates create new verified generations instead of mutating a promoted generation in place. |
| D-013 | CONFIRMED | Project-specific dependencies should normally use isolated overlays/runtime state on a reusable environment generation rather than creating permanent environment families per project. |
| D-014 | CONFIRMED | Bootstrap dependencies form an acyclic capability graph. A provider environment must be rebuildable without a mandatory existing instance of itself; previous generations are optional accelerators only. |
| D-015 | CONFIRMED | The permanent core depends on generic environment-build/run capabilities rather than a Docker-specific provider contract, even if Docker is the initial backend. |
| D-016 | CONFIRMED | Artifact dependency relationships should enable targeted invalidation after partial replanning instead of invalidating unrelated work indiscriminately. |
| D-017 | CONFIRMED | ProjectBlueprint and Plan are separate. Planner creates/revises the Blueprint (approved resulting architecture); Plan describes how current state will be changed to reach it. |
| D-018 | CONFIRMED | Stable requirement/component/interface/verification IDs and end-to-end requirements traceability are mandatory for every project, regardless of project size. |
| D-019 | CONFIRMED | Blueprint defines verification/test obligations (what must be proven); Tester defines concrete test design and cases (how it is proven). |
| D-020 | CONFIRMED | Planner may create complete proposed declarative design/contract artifacts for the approval package, but must not implement production logic, Tester-owned tests, provider environments, or mutate the product repository before approval. |
| D-021 | CONFIRMED | Human approval applies to an Engineering Change Package. User semantic edits make the package unapproved and require affected validation/feasibility to rerun. A real Planner replan after approval creates a new package revision and requires human reapproval. |
| D-022 | CONFIRMED | Users may modify any semantic part of project knowledge/approval packages, while stable IDs, hashes, revision/provenance, candidate bindings, and other integrity metadata remain framework-managed. |
| D-023 | CONFIRMED | The framework itself must be maintained as a framework-managed project using the same ProjectBlueprint, traceability, feasibility, approval, candidate, verification, and promotion model, with an independent stable/recovery boundary for self-update. |
| D-024 | CONFIRMED | Planner replanning must explicitly reconcile the new Blueprint/Plan with all applicable original requirements and preserve/report traceability coverage; requirements may not silently disappear during replan. |
| D-025 | CONFIRMED | The v2.1 design set reserves an initial stable ProjectBlueprint/traceability baseline for the framework itself in `framework-project-blueprint.md`; the implemented machine-readable framework Blueprint must migrate these identities with recorded lineage rather than silently replacing them. |
| D-026 | CONFIRMED | v2.1 has no external provider marketplace/catalog or outsourced provider trust path. Providers originate from the framework or the user, are developed/validated as framework-managed projects, and become locally available only after promotion. Existing promoted providers may be installed/activated automatically when an approved project requires them; creating a previously nonexistent provider is an architectural change requiring human approval. |
| D-027 | CONFIRMED | Project dependencies may be installed automatically into isolated project execution overlays only when they are declared/bound by the approved Engineering Change Package. They must not silently mutate the shared promoted environment generation. |
| D-028 | CONFIRMED | Environment storage is space-aware. Heavy artifacts/overlays/caches are garbage-collected by policy while generation identity, provenance, hashes, promotion history, and required evidence are retained independently. The promoted generation is protected; previous known-good generations are retained when practical but may be evicted under disk pressure if not explicitly pinned. |
| D-029 | CONFIRMED | `main-development` is the framework control plane and `generic-test` is the minimal bootstrap/test substrate. Domain/toolchain SDKs do not remain in permanent core merely for convenience. Upper layers use generic `ProcessExecutor` and `EnvironmentBackend` abstractions; Docker may be the initial backend but is not the provider contract. |
| D-030 | CONFIRMED | Required/authoritative project verification must execute through the Blueprint-bound provider/environment capability. Tools incidentally present in `main-development` may be used only for advisory/self-testing and cannot satisfy required verification obligations. |
| D-031 | CONFIRMED | Verification inputs are immutable candidate content. Provider execution receives read-only/copy-on-write project input plus isolated writable build/runtime/evidence state; provider/environment code must not directly bypass the generic environment backend to obtain extra host/container privileges. |
| D-032 | CONFIRMED | Coder receives 100% of approved requirements, interfaces, observables, acceptance thresholds, and `VER-*` obligations, plus approximately 70% of concrete Tester test information by default. Approximately 30% is retained from Coder context for independent verification; the human user may inspect all test artifacts and the split is an engineering target rather than a mechanical count. |
| D-033 | CONFIRMED | Retained independent tests may add undisclosed concrete cases/data/edge-case constructions only within existing approved requirements and `VER-*` obligations. Tester may not introduce a new behavior requirement or acceptance criterion through a hidden/independent test; such discoveries require Planner/user reconciliation. |
| D-034 | CONFIRMED | Remove `review_requester` as an intelligent v2.1 role. Review/PR material is assembled deterministically from structured project/traceability/evidence metadata, with optional wording assistance not treated as a lifecycle decision-maker. |
| D-035 | CONFIRMED | Remove the separate `integration_tester` role in v2.1. Tester owns all `VER-*` verification regardless of whether execution occurs through unit, integration, simulator, provider, or other approved environment capabilities. |
| D-036 | CONFIRMED | Artifact validity is maintained as an explicit typed dependency DAG. Changes propagate `STALE` only through declared semantic dependencies; historical revisions/evidence remain immutable and targeted replan/verification reuses unaffected current artifacts. |
| D-037 | CONFIRMED | Long-lived projects support Project Baselines/Savepoints. A baseline captures the current alive engineering frontier and may compact completed historical subgraphs into immutable compressed archives without deleting traceability; the latest baseline becomes the normal active dependency frontier. |
| D-038 | CONFIRMED | v2.1.0 must provide static artifact-graph visualization with focused explanatory views. A future interactive VS Code graph will consume the same canonical graph/query/action interface and must not become a separate source of truth. |
| D-039 | CONFIRMED | Graph logic/storage performance is an acceptance concern. v2.1 implementation verification must exercise increasing synthetic graph sizes (approximately 1k/10k/100k active/historical nodes plus a large archived-history case) and measure traversal, stale propagation, cycle detection, baseline/compaction, archive/query, rendering, memory, and storage behavior before release thresholds are finalized. |
| D-040 | CONFIRMED | Framework-managed graph/integrity metadata is tamper-evident first (schema validation, content/root digests, immutable history, controlled writes). Compression/content-addressed deduplication are supported for scale; authenticated/encrypted storage is future security work and must not substitute for integrity/authorization semantics. |
| D-041 | CONFIRMED | Tester-created concrete test code is separated by ownership: development-facing tests are materialized into the product repository as maintained regression tests protected from unilateral Coder modification, while independent verification tests remain versioned framework-managed project knowledge outside normal Coder context. Provider/environment acceptance tests remain separate provider/environment-project artifacts. |
| D-042 | CONFIRMED | Every promotable candidate must pass a small project-defined Final Acceptance Suite after required targeted verification and review prerequisites are current. The suite reuses existing `VER-*` obligations, runs against the exact candidate SHA and required environment generation(s), and does not replace full verification. |
| D-043 | CONFIRMED | Debugger remains as an on-demand diagnostic role for ambiguous, conflicting, or repeated failures rather than a mandatory lifecycle hop. Its diagnosis routes work to the proper owner but cannot approve or modify the affected product. Normal failures with clear ownership route directly to the responsible owner. |

## Update rule

When a decision changes status or meaning:

1. update this register;
2. update every affected design document;
3. record the reason in the relevant work item/design artifact;
4. do not rewrite `docs/architecture.md` until the behavior is implemented and accepted.
