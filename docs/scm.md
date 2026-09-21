# SCM providers

v2.0.2 supports `github` and `bitbucket` through `scmctl` and the project `.agent/project.yaml` SCM block.

```yaml
scm:
  provider: github
  remote: origin
  base_branch: main
```

GitHub uses the official `gh` CLI. Use `make github-login` / `make github-login-status` for interactive development or `GH_TOKEN` for headless operation. GitHub CLI configuration persists under `.agent-state/github-cli`.

Automatic publication occurs only after candidate/local/integration-when-required/review SHA integrity checks pass. The framework performs a non-force `git push --set-upstream` of the work-item branch, creates the PR, reads the remote PR metadata, and rejects a head/base mismatch. `PR_OPEN` therefore means an actual remote PR exists for the reviewed candidate.

## Post-merge promotion integrity

`MERGE_APPROVED` records human authorization to merge; it is not merge evidence. Promotion is a post-merge operation.

Before `agentctl promote` may transition a work item to `PROMOTED`, the framework re-queries the configured SCM provider and requires all of the following:

- the recorded pull request is in the provider's merged state;
- the provider-reported PR head SHA equals the exact reviewed candidate SHA;
- the provider-reported source branch and destination branch still match the work item and configured base branch;
- the provider repository and recorded PR identity still agree; and
- the provider returns a merge commit SHA and merge timestamp.

Successful reconciliation is retained as `artifacts/merge-verification.json`, copied into `status.json` under `merge`, and the promotion record binds both the reviewed candidate SHA and provider merge SHA. If the PR is still open/closed without merge, its head changed, authentication/network access fails, or provider merge proof is incomplete, promotion fails closed and the work item remains `MERGE_APPROVED`.

This check is provider-neutral. GitHub is reconciled with `gh pr view`; Bitbucket is reconciled with the Pull Requests API.
