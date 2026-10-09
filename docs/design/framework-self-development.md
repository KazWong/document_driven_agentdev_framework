# Framework Self-Development Policy

Status: **pre-implementation normative design**
Last updated: **2026-09-29**

## Core rule

The framework itself is software produced and maintained by this framework.

Once v2.1.0 implements the ProjectBlueprint/traceability workflow, future framework changes must follow the same requirements -> Blueprint -> feasibility -> approval -> implementation -> verification -> promotion lifecycle required of user projects.

There is no architectural bypass that allows framework code to ignore its own development rules.

## Framework as a managed project

The framework repository must maintain persistent authoritative project knowledge including at least:

- framework product requirements;
- current ProjectBlueprint;
- stable requirement/component/interface/verification IDs;
- architecture diagrams and linked design artifacts;
- provider/environment contracts owned by the framework;
- current verification obligations;
- migration/compatibility requirements;
- traceability matrix/status.

A future framework update starts from this project knowledge rather than reconstructing architecture from code or prior chat history.

The pre-implementation identity baseline is `framework-project-blueprint.md`. Its reserved `REQ-FW-*`, `CMP-FW-*`, `IFACE-FW-*`, and `VER-FW-*` identities must be carried into the eventual canonical machine-readable framework ProjectBlueprint with recorded lineage.

## Architecture-change workflow

If a requested framework change modifies architecture:

1. update/propose the applicable framework requirement or design input;
2. Planner creates a new framework ProjectBlueprint revision;
3. Provider/Tester/Coder feasibility checks run;
4. the approval-ready Engineering Change Package is presented to the human;
5. only after approval may Coder implement the candidate framework;
6. implementation traceability must map code/config/docs to framework requirement/component IDs;
7. candidate framework verification must map evidence to framework `VER-*` obligations;
8. after acceptance/promotion, current-architecture docs are reconciled to implemented behavior.

Future agents must not directly patch core architecture and then retrofit documentation afterward.

## Stable framework updates its candidate

Self-development must avoid a bootstrap paradox where an unverified candidate controls its own promotion.

The currently accepted/stable framework orchestrates the update of a candidate framework in an isolated worktree/environment.

Conceptually:

```text
accepted framework N
       |
       | creates/manages work item
       v
candidate framework N+1
       |
       | isolated validation/self-tests
       v
independent acceptance evidence
       |
       | human promotion approval as required
       v
promoted framework N+1
```

The candidate may execute its own test suite as a verification subject, but it does not get authority to declare itself promoted merely because its own code says it passed.

## Independent recovery boundary

Framework self-development must retain an independent recovery/install path outside the candidate being modified.

The exact updater/rollback implementation is deferred, but future architecture must preserve these properties:

- candidate cannot replace the running stable controller before acceptance;
- failure leaves the last accepted framework usable;
- source/config migration is validated before activation;
- recovery does not depend exclusively on the broken candidate runtime.

## No self-update special cases that weaken policy

Framework self-development may need special bootstrap mechanics, but those mechanics must not weaken:

- human approval requirements;
- requirement traceability;
- scope/candidate SHA binding;
- Provider/Tester/Coder feasibility checks;
- evidence integrity;
- risk/permission policy;
- architecture documentation consistency.

If a special recovery or bootstrap operation is necessary, it is documented as a lower-level trusted mechanism, not implemented as a silent bypass inside normal workflow.

## Documentation consistency invariant

Future framework update work must read, as applicable:

1. `AGENTS.md`;
2. current `docs/architecture.md`;
3. current framework ProjectBlueprint/project knowledge;
4. relevant provider/environment contracts;
5. unresolved design/TODO records;
6. migration/acceptance requirements.

A framework architecture change is incomplete until:

- ProjectBlueprint/project knowledge reflects the accepted design;
- implementation traceability is complete;
- verification evidence is complete;
- `docs/architecture.md` and Mermaid diagrams describe the behavior that actually exists;
- command/operations/migration/QA docs are reconciled where affected;
- superseded design decisions are explicitly retired or incorporated rather than silently forgotten.

## Anti-degradation acceptance requirement

v2.1.0 must add a regression/QA rule proving that a framework architecture change cannot be considered release-ready when it bypasses required project knowledge or traceability updates.

At minimum, framework QA should detect classes of drift such as:

- current architecture references components/interfaces absent from the ProjectBlueprint;
- code/config changes have no approved component/requirement mapping;
- required `VER-*` obligations lack candidate-bound evidence;
- domain-specific hardcoding is reintroduced into generic core where provider abstraction is required;
- architecture docs and ProjectBlueprint materially disagree after release reconciliation.

The exact validator implementation is still an implementation-design task, but the invariant is CONFIRMED.
