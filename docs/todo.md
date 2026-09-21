# Framework TODO

## Deterministic Agent Git Branching Policy Enforcement

Status: planned; intentionally not part of the v2.0.2 GitHub acceptance implementation beyond the safety-critical candidate/publish checks.

Future work:

- Make branch naming format and maximum slug length configurable.
- Validate one active branch per work item across local and remote repositories.
- Make allowed commit types and commit-message format configurable.
- Add a configurable maximum logical commit count per work item.
- Define deterministic rebase/update-base policy before PR publication.
- Forbid automatic history rewriting after a PR is open unless an explicit recovery policy authorizes it.
- Enforce protected-branch rules using both local framework policy and provider-reported branch protection.
- Define remote-branch and local-worktree cleanup after merge/closure.
- Add migration rules for projects with an existing organizational branching standard.

Reference policy for generated projects: `.agent/branching-policy.md`.
