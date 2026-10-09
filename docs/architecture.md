# Implemented architecture — v2.1.0

This describes the candidate implementation. It does not certify that the live release gates have passed. The approved ECP and original identities remain under `docs/design/` and `.agent/design/`.

## Authority and storage

The trusted controller owns Git changes, lifecycle transitions, record metadata and human approval entry. Six roles remain: Planner, Coder, Tester, Reviewer, Safety Reviewer and on-demand Debugger. A role output is neither a human approval nor independently authoritative execution evidence.

`src/agent_framework/data/policy.json` owns role permissions, lifecycle transitions, consequence categories and gate counts. `contracts.schema.json` owns structural contracts. Python performs semantic checks: complete requirement coverage, valid lineage, declared path scope, exact revisions and current prerequisites. Root schema/config files and role documents are generated projections.

A private external state directory contains a SQLite WAL ledger, immutable revision records, a hash-chained event log and SHA-256 addressed objects. Writers use transactions, advisory locks and revision compare-and-swap. JSON encoding is deterministic; duplicate keys, nonfinite numbers and ambiguous paths are rejected. Integrity verification checks object bytes, history, event chain and live projections. This is tamper evidence within a trusted operator boundary, not authenticated or encrypted multi-user storage.

Dependencies point from prerequisite to dependent. Replacing a semantic record marks declared descendants stale while preserving their historical bytes. A stale object must be revalidated by its owner or replaced with a new revision. Baselines capture a stable live frontier. Compaction archives obsolete revision payloads in bounded compressed packs; current identities, dependencies, event history and traceability remain. Retired leaf IDs cannot be reused.

## Engineering lifecycle

Planner proposes a Blueprint and separate Plan. The Blueprint retains stable REQ/CMP/IFACE/VER identities, traceability and the final acceptance matrix. The Plan binds tasks, paths, consequence-derived risk, permissions and delivery mode. Provider feasibility, Tester design/testability, Coder feasibility and Planner reconciliation precede implementation approval.

Semantic edits create unapproved revisions and invalidate dependent evidence. Candidate creation runs on a controller-owned feature worktree. The controller checks the actual Git diff against scope and requirement/design/task traces, materializes Tester-owned development tests, checks the prospective tree, then commits. The original source checkout is preserved. A durable candidate intent supports recovery if a process stops after the Git commit but before its ledger record.

Targeted execution stamps candidate SHA, suite digest, generation, immutable image and execution identity. Tester provides the typed verification verdict. Reviewer assesses the exact candidate; R2/R3 also require Safety Reviewer. A distinct final run covers every required environment cell and existing VER obligation. Targeted results cannot stand in for final acceptance. Promotion rechecks current dependencies, exact clean candidate, reviews, matrix and human approvals while holding environment leases. R0/R1 require one release approval; R2/R3 require two distinct identities.

Known failure classes route to their owner. Ambiguous, conflicting or repeated equivalent failures invoke read-only Debugger. Automatic retry budget is zero. Diagnosis grants no approval; an operator explicitly resumes work. Source repair clears the candidate and candidate-bound acceptance rather than relabelling old evidence.

## Isolation and environment contracts

`EnvironmentBackend` supplies build, inspect, execute and remove primitives. Docker is the only installed concrete backend. `ProcessExecutor` runs trusted host commands with bounded output/time, explicit environment variables, no shell expansion and descendant cleanup. Provider code is never imported into the controller process.

Each role sees a candidate snapshot without `.git` or controller state, an explicit context, selected read-only tests and isolated output. Only Coder's implementation stage receives a writable project snapshot. The controller rejects changes outside the Plan and to protected Tester files before copying approved changes back. Each copied file is atomic; a crash across several files can leave a dirty worktree, which blocks subsequent work until inspected and repaired.

Tester owns concrete tests. Development tests become protected repository regression tests. Independent tests remain in external state and are absent from Coder and Planner mounts and contexts. All requirements and acceptance obligations remain public. Allocation is justified by coverage, not a mechanical 70/30 count. Human operators can inspect every artifact.

Docker jobs run by immutable image ID with read-only root, dropped capabilities, no added devices/socket, resource limits and network disabled unless declared. Candidate verification is read-only. Scratch/output volumes provide overlays without mutating a shared image. Named credentials are mounted only for explicitly authorized actions from private registered files. An uncertain cleanup retains its environment lease until operator recovery.

Providers declare capability and requirement schemas, compatibility constraints, bootstrap dependencies, actions, permissions and source-contract references. Feasibility executes the registered compatibility resolver in isolation, records its receipt and rejects attempts to redefine the promoted generation. Pre-approval execution stays within intake permissions. Compatibility is data-driven; core code has no domain/language lanes. Provider-specific result schema references are provenance links; the controller currently enforces its canonical result envelope and approved obligations. Expanding result semantics requires a schema/controller revision.

Environment generations are immutable. A provider/environment change is a separate managed source project: approve its release contract, build its exact candidate, accept the built artifact, complete targeted review/FAS, approve and promote source, then register the generation. An explicit empty-registry seed installs an independently verified trust root; this candidate does not claim to provide one. Missing providers block until that managed-project work is complete. There is no external marketplace or automatic creation of unapproved providers.

Retirement and provider replacement cannot race an active execution/promotion lease. GC removes eligible retired heavy images, retains active/base/shared/leased images, and preserves durable generation/provenance/evidence records. Per-run temporary overlays are normally removed immediately. There is no background disk-pressure daemon.

## Delivery and supported boundary

Artifact delivery records local promotion after the same gates. Optional GitHub delivery uses a trusted `gh` adapter, exact PR-head CI checks and a non-forced fast-forward push of the verified SHA to the declared base. Server-side branch protections remain effective; a protected branch that requires a different merge mechanism will block this adapter. No remote or physical action is automatic. Hardware execution is disabled in the generic backend.

Static bounded graph queries provide JSON, Mermaid and standalone SVG views, including baselines and failure causes. Normal queries use the current frontier rather than loading all archived revisions. The release measurements exercise 1k/10k/100k live nodes and one million total revisions. Full live Docker/agent isolation, image acceptance and framework self-promotion remain release gates to execute on a provisioned host.

Interactive VS Code, public IPC, full asynchronous scheduling, provider catalogs, authenticated/encrypted ledgers, a host broker, HIL redesign and automated self-updates are outside this initial implementation. The accepted previous controller and original v2.0.3 baseline remain the recovery boundary for this delivery.
