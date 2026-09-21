# Agent Git Branching Policy

This document is the Git-history reference for humans and agents working in this project. The framework owns Git mechanics; agents provide source changes and review decisions.

## Branch ownership

- One work item owns one active development branch.
- The current branch convention is `agent/<work-item-id-lower>-<short-slug>`.
- Example: `agent/rbt-002-ros2-publisher-subscriber-counter-package`.
- Branch from the work item's recorded base branch and base revision.
- Never implement directly on `main`, `master`, `develop`, `development`, or a release branch.
- Retries and bounded corrections continue on the same work-item branch; do not create `-fix`, `-retry`, or model-specific branches.
- Do not force-push automatically.

## Commit convention

Use Conventional-Commit-style work-item messages:

```text
<type>(<WORK-ITEM-ID>): <summary>
```

Allowed reference types are `feat`, `fix`, `test`, `refactor`, `docs`, `build`, `ci`, and `chore`.

Examples:

```text
feat(RBT-002): implement ROS2 counter publisher and subscriber
fix(RBT-002): correct subscriber timing statistics
test(RBT-002): add publisher subscriber integration coverage
```

The current framework creates the candidate implementation commit deterministically after the coder succeeds. It stages only paths allowed by the work-item scope and refuses empty/no-op candidates.

## Candidate integrity

The commit published to a pull request must be exactly the commit that passed every required gate:

```text
candidate_sha
  == local_test_sha
  == integration_test_sha
  == reviewed_sha
  == pr_head_sha
```

Any tracked change after candidate creation invalidates verification. Generated build/test output must remain untracked and outside the approved source scope.

## Remote publication

- The framework pushes the work-item branch only after deterministic verification and independent AI review pass.
- The framework creates the configured GitHub or Bitbucket pull request automatically.
- `PR_OPEN` means a real remote PR exists and its head SHA matches the reviewed candidate.
- Human code inspection may happen at any time with `agentctl inspect`; the normal human review point is the open remote PR.
- Human merge approval remains mandatory. The framework does not bypass repository branch protection.

## Planned enforcement work

A later framework update will make branch naming, commit-type selection, commit-count limits, rebase policy, post-PR history rewriting, and branch cleanup fully configurable and deterministically enforced. Until then, this document is the required reference policy and the framework enforces the safety-critical subset described above.
