# ECP-AUTO-20261013 — v2.1.0 automation repair

Status: implemented candidate; host regression evidence only. Authority: the user's 13 October 2026 instruction to repair automation, recheck Tester/Coder concurrency, require one human for every risk class, manage remote review branches and support Bitbucket. This supplement supersedes conflicting serial-preflight and two-human rules in the historical v2.1.0 design. Historical acceptance records are not rewritten.

## Requirements and verification

| ID | Requirement | Implementation | Regression evidence |
|---|---|---|---|
| REQ-AUTO-001 | Resume lifecycle without operator role/import command chains | automation.py; CLI run/watch | test_automation_concurrency.py |
| REQ-AUTO-002 | Tester test authoring and Coder feasibility execute concurrently; code follows concrete test handoff | engine.py; roles.py; per-role locks, short apply lock | two-party backend barrier and stale-input rejection |
| REQ-AUTO-003 | One human per approval gate for R0–R3 | canonical policy and generated projection | test_trace_provenance.py; revised R2 gate regression |
| REQ-AUTO-004 | Push the accepted feature-branch SHA and obtain human code review remotely | remote.py; engine approval import | GitHub and Bitbucket approval/CI rejection tests; simulated SCM lifecycle |
| REQ-AUTO-005 | Support Bitbucket Cloud branch publication, PR reuse, CI and review | BitbucketDelivery; bounded authenticated API | test_remote_providers.py |
| REQ-AUTO-006 | Preserve Tester authorship and reject unauthorized Coder claims | separate review context, protected paths, aggregate candidate trace | provenance and role-boundary regressions |
| REQ-AUTO-007 | Integrate demonstrated transport, trace and runtime corrections | Codex transport schema; task union; executable build workspace; optional sandbox profile | transport, trace and runtime profile regressions |

## Execution design

Provider feasibility resolves first. Tester authors concrete development and independent tests while Coder performs a read-only implementation assessment from the same draft. Their output directories, connections and environment leases are separate. The controller imports the suite and Tester feasibility, then obtains Coder's test-handoff assessment. Planner reconciles before one human approves the package.

This is actual overlap of test authoring and implementation assessment. Production implementation waits for the development tests, and authoritative verification waits for the immutable candidate. No claim is made that final verification runs against half-written production code.

Role execution releases the controller lock. Applying edits and accepting a role result rechecks lifecycle state, request/draft/package/candidate references, HEAD, permissions and protected paths under a short controller lock. Coder retains exclusive per-role dispatch and may apply only to a clean checkout. Read-only work uses an immutable Git snapshot, so unrelated uncommitted Coder output does not invalidate its snapshot. Replanning rejects stale pending work.

The controller distinguishes the combined candidate trace from the production-only Coder trace. Test provenance identifies Tester as author and framework as materializer. Reviewer notes have a separate optional field; findings retain unresolved blockers only. No existing review is rewritten or adverse finding silently dropped.

## Orchestration and recovery

`run` drives role dispatch/import, package creation, branch/worktree management, candidate creation, targeted verification, reviews, final verification and acceptance. `--watch` polls approval and remote CI/review gates. It never creates a human approval. Durable role receipts prevent normal reruns of completed model jobs. Completed verification cells are reused only when current candidate/suite/environment bindings match. Candidate commit-intent recovery is automatic. Clean controller candidates can become the continuation point after an approved replan without changing the original trace baseline.

Coder-owned failures receive the recorded failure context and a bounded repair budget (default two in the run configuration). Planner-owned revisions also have a finite budget and require renewed approval of the changed package. Environment, provider, bootstrap and exhausted/ambiguous failures remain explicit blockers. A process interruption during an unrecorded file-application window is not claimed to be automatically recoverable; dirty unknown edits fail closed.

## Remote authority and compatibility

SCM plans name the provider, repository, target branch, required CI checks and allowed human reviewers. Fetch and push URLs must both match that repository. Publication uses the accepted SHA on an `agent/` branch, uses a normal push, and reuses a matching open PR. GitHub credentials and Bitbucket tokens remain in the controller, outside role snapshots.

GitHub approval must be a current non-dismissed human review for that commit. Bitbucket Cloud participant approvals lack an exact commit binding in this adapter's input, so an approved allowed reviewer must also post `APPROVE <full SHA>` in the PR. Change requests block release. Approval and CI are rechecked before promotion; promotion retains the existing non-forced fast-forward delivery model. Server branch rules can refuse it. Bitbucket Data Center is not implemented.

One human is required at each existing approval gate, irrespective of risk. R2/R3 still require automated Safety Reviewer assessment. Physical execution permissions remain a separate supported-capability question; reducing the human threshold does not add a hardware driver.

## Validation boundary

The tests exercise real controller methods, SQLite stores, filesystem locks, Git worktrees and schema validation. Model/container results and remote APIs are simulated in contract tests. Docker, authenticated Codex execution, ROS2/Gazebo and real GitHub/Bitbucket writes must be tested on the target host before claiming live autonomous acceptance.
