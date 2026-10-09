# Final Acceptance Suite

Status: **CONFIRMED pre-implementation normative design**
Last updated: **2026-10-01**

## Purpose

Targeted invalidation avoids rerunning verification that is provably unaffected by a change. A final promotion gate is still useful because individually current component evidence may miss an integration/regression failure in the complete candidate.

The Final Acceptance Suite is a small project-defined mandatory gate executed on a promotable candidate after required targeted verification and review prerequisites are current. It complements, rather than replaces, detailed verification.

## Three-layer verification model

1. **Coder self-tests** — fast advisory implementation feedback.
2. **Targeted authoritative verification** — Tester reruns/reuses `VER-*` evidence according to the artifact dependency DAG.
3. **Final Acceptance Suite** — a small final product-level acceptance set run on the exact candidate before promotion.

A broader **full verification suite** remains distinct and may be policy-triggered for major releases, high-risk changes, architecture changes, environment migrations, periodic validation, or explicit user request.

## Reuse existing `VER-*` obligations

Do not create a competing acceptance-requirement namespace unless later evidence proves it necessary. The Final Acceptance Suite should select existing Blueprint `VER-*` obligations that are required on every promotion.

Planner/Blueprint owns **what must always be demonstrated**. Tester owns **the concrete acceptance tests and evidence strategy**.

Conceptually:

```yaml
final_acceptance:
  obligations:
    - VER-001
    - VER-004
    - VER-009
```

Exact schema/field names remain open.

## Suite content

The suite should be intentionally small and project-specific. It normally covers:

- basic product viability/startup;
- one or more critical end-to-end paths across major components/interfaces;
- high-consequence requirements identified by the project risk model;
- deployment/runtime sanity in required supported environments;
- selected historically fragile critical behavior where continued promotion-time coverage is justified.

Core must not hardcode commands such as `pytest`, `cmake`, ROS smoke tests, or any other domain/toolchain-specific check.

## Exact candidate binding

A Final Acceptance result is valid only for the exact candidate SHA evaluated. Any repository change that creates a new candidate SHA requires a new Final Acceptance run for that candidate, even if targeted analysis suggests the change is small.

## Environment binding and matrix

Acceptance evidence records the exact required environment generation(s). Where the approved project supports multiple required environments/targets, the suite may form a required matrix. Optional environments do not block promotion unless the approved Blueprint says they are required.

An environment/backend failure means **acceptance not evaluated**, not candidate failure. The environment is repaired through its own lifecycle and the same unchanged candidate is retried when possible.

## Readiness gate

Before executing Final Acceptance, the framework should deterministically confirm that:

- the applicable Engineering Change Package is approved;
- candidate SHA matches implementation trace and approved scope;
- all required prerequisite `VER-*` evidence is current;
- required provider/environment capabilities are available;
- no blocking stale graph nodes remain;
- required Reviewer/Safety Reviewer gates are complete;
- mandatory traceability is complete.

## Test ownership and independence

Tester owns concrete final-acceptance tests. All requirements/acceptance obligations remain visible to Coder. Concrete acceptance cases may include both development-facing and retained independent Tester material according to the confirmed 70/30 handoff semantics; at least some acceptance execution should remain independent of Coder.

## Failure routing

- clear candidate implementation defect -> Coder;
- test implementation defect -> Tester;
- architecture/requirement defect -> Planner and, after approval-bound change, human reapproval;
- environment/backend defect -> environment capability owner;
- ambiguous/conflicting failure -> on-demand Debugger.

If Final Acceptance exposes a relationship that targeted invalidation failed to model, the framework must also record a traceability/dependency finding so the artifact DAG is corrected rather than merely fixing the immediate code symptom.

## Relationship to Project Baselines

A successful promotion is a natural baseline/savepoint opportunity. A release baseline may bind:

- approved Blueprint/requirements;
- exact candidate SHA;
- current targeted verification evidence;
- Final Acceptance result;
- review/safety results;
- exact environment generation identities;
- archive/root digest references.

## Promotion flow

```text
Approved Engineering Change Package
              |
              v
           Coder
              |
              v
         Candidate SHA
              |
              v
     Targeted Verification
              |
              v
      Reviewer / Safety gates
              |
              v
       Readiness validation
              |
              v
    FINAL ACCEPTANCE SUITE
              |
        +-----+-----+
        |           |
      PASS         FAIL/BLOCKED
        |           |
        v           v
     Promote      Route owner
        |
        v
  Baseline/savepoint
  when policy/user requires
```

## Confirmed decision

> Every promotable project candidate must pass a small project-defined Final Acceptance Suite after required targeted verification and review prerequisites are current. The suite selects existing Blueprint `VER-*` obligations, runs against the exact candidate SHA and exact required environment generation(s), remains distinct from full-suite verification, and preserves failure ownership semantics.
