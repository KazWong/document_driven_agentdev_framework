# Artifact Dependency Graph, Baselines, and Visualization

Status: **pre-implementation normative design**
Last updated: **2026-09-30**

## Purpose

v2.1.0 requires explicit artifact dependency tracking so requirement changes, replanning, implementation changes, environment changes, test changes, approval changes, and evidence changes invalidate only the artifacts that semantically depend on them. The graph must remain understandable and performant over a long-lived project rather than growing forever as one unbounded active working set.

The design therefore combines:

- an explicit artifact dependency DAG;
- typed semantic edges;
- targeted `STALE` propagation;
- immutable historical revisions/evidence;
- Project Baselines / Savepoints;
- active-graph compaction with archived history;
- static graph visualization in v2.1.0;
- a future interactive VS Code projection over the same canonical graph model;
- scale/performance tests before implementation acceptance.

## Canonical graph model

The framework maintains identity, revision, digest, owner, state, and semantic dependencies for engineering artifacts such as:

- `REQ-*` requirements;
- `CMP-*` components;
- `IFACE-*` interfaces;
- `VER-*` verification obligations;
- `TASK-*` plan tasks where materialized;
- `TEST-*` development and independent verification cases;
- implementation-trace artifacts;
- candidate SHAs;
- provider/environment requirements and resolved environment generations;
- verification runs/evidence;
- review/safety-review results;
- Engineering Change Packages and approvals;
- Project Baselines.

Core understands artifact identity and relationships, not technology-specific meaning.

Example trace:

```text
REQ-001
   +--> CMP-002 ----> IMP-007 ----> candidate abc123
   |
   +--> VER-004 ----> TEST-INDEP-006 ----> VR-0088
                                      |
                                      +--> ENV-G-0042
```

## Semantic edges

Edges carry relationship meaning rather than being undifferentiated `depends_on` links. Expected relationship classes include:

- `derived_from`;
- `implements`;
- `verifies`;
- `constrains`;
- `executes_on`;
- `materialized_from`;
- `generated_from`;
- `approved_as_part_of`.

The exact schema names are implementation details, but validity/invalidation direction must be explicit and acyclic. Navigation may expose reverse relationships, but the dependency/invalidation graph itself must reject dependency cycles.

## Artifact states

At minimum, graph lifecycle distinguishes:

- `CURRENT` — all validity dependencies match the artifact's recorded basis;
- `STALE` — one or more dependencies changed and the owning role must reevaluate the artifact;
- `SUPERSEDED` — a newer accepted revision replaced the artifact while history remains valid for its original context;
- `INVALID` — the artifact is structurally invalid or known not to satisfy its contract.

A dependency change normally makes a descendant `STALE`, not automatically `INVALID`. The owning role may revalidate an unchanged artifact against the new upstream revision.

## Targeted invalidation

A changed artifact propagates staleness only through declared semantic dependencies.

Example:

```text
REQ-001 changed
   |
   +--> CMP-A affected
   +--> VER-A affected
             |
             +--> TEST-DEV-A stale
             +--> TEST-INDEP-A stale

REQ-002 / CMP-B / VER-B remain current if no dependency path exists.
```

Planner targeted replan receives both the affected subgraph and an explicit preserve set. Planner must still reconcile the full set of applicable requirements, but unrelated architecture is not redesigned merely because a different subgraph changed.

## Candidate, environment, and test invalidation

Candidate changes invalidate candidate-bound verification evidence but do not invalidate an unchanged approved Blueprint/Plan.

Environment-generation changes invalidate evidence bound to the previous generation but do not invalidate application approval when the approved compatibility requirement is unchanged.

A Tester correction to a concrete independent test under the same `VER-*` obligation invalidates/requires rerun of affected test evidence but does not by itself invalidate the Blueprint approval. A change to the `VER-*` obligation or acceptance criterion is an approved-design change and invalidates the applicable Engineering Change Package.

Development-facing Tester tests that are materialized into the product repository contribute to candidate identity; changing them creates a new candidate SHA.

## Project Baseline / Savepoint

Long-lived projects must not keep every historical node in the active working graph forever. At a stable milestone, the framework can create a Project Baseline / Savepoint representing the complete effective engineering state.

A baseline records at least:

- baseline ID and human label/version;
- project candidate SHA/release identity where applicable;
- current ProjectBlueprint revision;
- current applicable requirement revisions;
- current Plan/Test Design references needed for maintenance;
- the set of current/alive graph heads;
- applicable environment/provider requirements and bindings;
- approval state;
- verification/review summary references;
- graph/archive root digest and provenance.

Exact serialization remains an implementation detail.

### Alive nodes

An **alive node** is the current effective revision required to understand, maintain, verify, or change the project at the baseline frontier.

For example:

```text
REQ-001 r7   alive
REQ-001 r1-r6 historical

CMP-004 r3   alive
CMP-004 r1-r2 historical
```

The baseline captures the current heads rather than flattening them into untraceable prose.

## Graph compaction

Creating a baseline does **not** delete history. Completed historical subgraphs represented by the baseline may move from the normal active working set into an immutable archive pack.

```text
historical revisions/evidence
           |
           v
      BASE-0012
       /      \
      /        \
active change  active change

archived history remains addressable from BASE-0012
```

After compaction, the latest baseline acts as a dependency frontier for normal project operations. Historical trace/audit commands can reload archived subgraphs when needed.

Baseline/compaction should occur only from a stable project state. The framework may suggest a baseline after releases, major milestones, or graph-size thresholds, but must not silently compact an active unresolved work item.

## Archive storage and deduplication

Archived graph metadata should support compressed immutable archive packs. Heavy evidence and binary artifacts should use content-addressed references where practical rather than being duplicated into every archive.

Conceptually:

```text
baseline
  +--> compressed graph metadata/history
  +--> content-addressed evidence references
  +--> immutable manifest/root digest
```

Compression format, storage path, and content-addressed object layout are implementation details. Correctness must not depend on a specific compression algorithm.

## Integrity and future cryptographic protection

v2.1.0 prioritizes integrity semantics before broad encryption:

- schema validation;
- framework-owned write paths for integrity metadata;
- immutable historical records;
- content digests/root digests;
- tamper detection and explicit stale/invalid handling.

Future security work may add authenticated metadata, signatures/MACs, and encryption at rest where confidentiality is required. Encryption is not treated as a substitute for integrity, authorization, or tamper detection.

A Project Baseline is a natural future signing boundary because a signed baseline root can authenticate the accepted engineering state without individually encrypting every graph node.

## v2.1.0 static visualization requirement

v2.1.0 must render a real graph from canonical graph data. The graph is an explanatory projection, not another source of truth.

At minimum, visualization should make these conditions distinguishable:

- current;
- stale;
- failed;
- blocked;
- missing trace/dependency;
- unverified;
- superseded.

The framework should support focused views instead of relying on one unreadable full graph:

- overview;
- requirements/architecture;
- verification;
- current work item;
- failure path;
- environment;
- approval;
- full active graph;
- historical baseline/compare view.

For v2.1.0 a static Mermaid/Graphviz/SVG-style output is sufficient. The canonical data model and graph query API must not depend on that renderer.

## Future VS Code interactive graph

The future VS Code extension should consume the same canonical graph/query/action interface as CLI/static rendering. It must not keep an independent project database.

Expected future read interactions include:

- click a node to inspect details, provenance, evidence, and history;
- click an edge to inspect relationship type and invalidation meaning;
- explain why a node is stale/blocked;
- filter/search/trace affected subgraphs;
- compare a baseline with current state.

Potential edit/control interactions such as approve, reject, propose/change an edge, edit semantic content, create a baseline, or request replan require a separate interaction-policy design. GUI actions must call validated framework operations and cannot directly mutate protected IDs, hashes, candidate/evidence bindings, or audit provenance.

## Scale and performance verification

Do not assume the graph will remain small. v2.1.0 design/implementation verification must include synthetic graph tiers at approximately:

- 1,000 nodes;
- 10,000 nodes;
- 100,000 nodes;
- a large archived-history case around 1,000,000 historical nodes/revisions where practical.

Measure at least:

- graph load/save;
- direct dependency lookup;
- affected-subgraph calculation;
- `STALE` propagation;
- cycle detection;
- baseline creation;
- compaction/archive creation;
- archive restore/query;
- static graph/subgraph generation;
- CLI query latency;
- memory use;
- stored metadata/archive size.

A renderer is never required to draw all 100,000+ nodes at once. Large-project visualization must query/filter a relevant subgraph.

Exact pass/fail latency and memory thresholds are to be set from measured v2.1 implementation baselines before release acceptance; they must not be invented without measurement.

## Normative decisions

1. The artifact dependency model is an explicit typed DAG with stable identities/revisions and framework-managed validity state.
2. Changes propagate `STALE` only through declared semantic dependencies.
3. Historical revisions/evidence remain immutable and addressable.
4. Project Baselines / Savepoints capture the current alive engineering frontier at stable milestones.
5. Baselines permit completed historical subgraphs to leave the active working set without deleting traceability.
6. Archived graph metadata may be compressed and should support content-addressed deduplication of referenced evidence/artifacts.
7. v2.1.0 requires static graph visualization from canonical graph data plus focused explanatory subgraph views.
8. A future interactive VS Code graph is a planned projection/control surface over the same canonical graph model, not a new source of truth.
9. v2.1.0 must benchmark graph logic and storage at increasing synthetic scales before release acceptance.
10. Integrity/tamper-evidence is required before broad encryption; authenticated/encrypted storage is future security work after the graph model is stable.
