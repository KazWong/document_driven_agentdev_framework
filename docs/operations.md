# Operations — v2.1.0

## State and trust setup

Run as a trusted operator. Give each product a private state directory outside the checkout. Keep the environment registry outside product snapshots too. Do not expose either directory or the host Docker socket to role/provider containers. Back up the state directory with no writer running; preserve ledger, WAL files if present and all objects together.

Start with `agentctl doctor`. Docker must be installed, reachable and able to create the required unprivileged containers. Build definitions with a completed external lock as described in the README. `main-development` is the controller/client image; `generic-test` contains the generic pytest provider. The optional Codex driver requires an authenticated credential and network permission in the action and approved Plan/intake permissions.

The first registry installation is explicit:

```bash
agentctl --state /workspace/state/bootstrap --environments /workspace/environments \
  env-seed /workspace/verified-seed.json --actor operator \
  --digest VERIFIED_PROVIDER_AND_GENERATION_DIGEST \
  --verification-note 'Independent verification record and location'
```

The seed file contains `provider` and `generation` objects. Compute the digest with the framework canonical encoder over exactly those objects. Use the actual immutable image ID, source identity and independently reviewed contract references. The seed is allowed only in an empty registry and verifies the installed image identity. No example seed is an attestation. Later providers/generations must use managed release acceptance and promotion.

Register a credential only when needed:

```bash
chmod 600 /workspace/private/codex-auth.json
agentctl --state /workspace/state/product credential-register codex-auth \
  /workspace/private/codex-auth.json
```

An action requesting `codex-auth` must also be permitted by the intake/Plan. The provider invokes `python /opt/framework/providers/codex/driver.py`. It creates an isolated temporary Codex home; the host profile is not mounted. Its CLI integration remains subject to the live acceptance check for the exact pinned client version. The driver follows the official [Codex CLI reference](https://developers.openai.com/codex/cli/reference).

## One work item

All commands accept the same globals **before** the subcommand: `--project`, `--state`, `--environments`, `--work`, `--json`. Use a shell function to avoid repeating them:

```bash
fw() {
  agentctl --project /workspace/product --state /workspace/state/product \
    --environments /workspace/environments --work WORK-001 "$@"
}
```

1. `fw new 'Approved goal'` starts intake. Add `--permission-file permissions.json` when initial agent planning needs declared network/credentials. Run `fw role planner --generation ENV-AGENT --action role`, then `fw import-planning JOB-ID`. Alternatively, import reviewed semantic files with `fw propose blueprint.json plan.json --consequence ordinary_software`. These create drafts, never approval.
2. Select already promoted generations by requirement ID in a JSON object, for example `{"ENVREQ-001":"ENV-GENERIC"}`, and run `fw provider-preflight selections.json`. Missing or incompatible providers block with an owner action.
3. Run Tester without a suite to author tests, then `fw import-test-design JOB-ID`. Inspect the returned suite. Run Tester again with `--suite SUITE-ID`; import its testability output with `fw tester-preflight SUITE-ID JOB-ID`.
4. Run Coder feasibility and import with `fw coder-preflight JOB-ID`. Run Planner reconciliation and import with `fw reconcile JOB-ID`. Inspect all artifacts using `fw read ARTIFACT-ID` and `fw status`.
5. Approve the current package digest: `fw approve --actor human-name --digest PACKAGE-DIGEST`. Run `fw start`. The controller creates the isolated worktree and reports its location.
6. Run Coder implementation. Inspect its typed change trace and actual files. Save the `changes` array as a JSON trace outside the checkout, then `fw candidate trace.json`. The controller owns the commit. Never edit Git history from a role.
7. For each required environment, run `fw verify ENVREQ-ID --action verify`. Run Tester over the complete results and import with `fw verified JOB-ID`. Run Reviewer, then `fw review JOB-ID`; for R2/R3 also run and import Safety Reviewer.
8. `fw accepting` checks readiness. Execute each required matrix cell again with `fw verify ENVREQ-ID --action verify --final`, then `fw accept`. Inspect the acceptance record. Approve its digest with `fw approve --release --actor human-name --digest ACCEPTANCE-DIGEST`, obtaining distinct identities when required. `fw promote` records artifact promotion; `fw close` closes the work item.

Use returned IDs and digests, not the illustrative placeholders above. Every `role` command returns an execution record whose ID is passed to the corresponding import/verdict command. The controller checks role, stage, input digest and current prerequisites. A role's JSON cannot create a successful execution or approval on its own.

For SCM delivery, the approved Plan must set `delivery: scm`, base branch and exact CI check names. `publish-pr` is an explicit external write. `ci` records checks on the current PR SHA. `promote --authorize-remote` authorizes the final non-forced push after all local gates. The adapter does not bypass repository rules or introduce an untested merge commit.

## Environment releases and cleanup

Use a separate source work item with `environment_release` in its approved Plan. After creating its candidate, build that exact clean source. Fill the provider/generation release object with the resulting image ID, candidate SHA, source-tree digest, approved Plan reference and Tester suite reference. Run `env-accept release.json` **before** targeted candidate verification. This records separate acceptance of the built image and binds its subject to the source candidate. Then finish normal review/FAS, release approval and source promotion. `env-publish release.json` registers only that accepted subject.

Use `env-retire GENERATION` before removing an old generation. `env-gc` previews removals; `env-gc --apply` removes eligible heavy artifacts. These commands retain metadata and evidence. Active generations, bases still in use, shared image IDs and leased executions are protected. A new provider contract version can invalidate old bindings; approve and select the replacement generation deliberately.

## Failures and recovery

`status`, `read`, `evidence` and `explain` expose the failure owner and exact bindings. Infrastructure failure does not establish a candidate defect. Fix the recorded owner problem, then explicitly `resume --actor operator`. A source change requires `--repair-source` and a new candidate/reverification. Architectural changes go through revised proposal, feasibility, reconciliation and approval. Repeated equivalent failures invoke Debugger; there is no automatic retry loop.

If a candidate commit completed but ledger recording was interrupted, run `recover-candidate`. It requires the exact clean controller-owned commit, parent, tree, approved package and durable intent. It refuses unrelated commits.

If container cleanup is uncertain, the lease is retained. Inspect and stop/remove the named container on the Docker host before `env-recover-lease TOKEN --actor operator --verification-note 'Evidence that the execution stopped'`. Never release a lease on assumption. A partial multi-file Coder import leaves a dirty checkout; inspect it, restore or complete the intended changes and rerun the explicit stage. Do not delete historical records to force progress.

Create a baseline only at a stable frontier: `baseline BASE-ID 'label' --compact`. `graph --focus ARTIFACT --format svg --output graph.svg` creates a bounded projection. Historical views accept `--baseline BASE-ID`. `integrity` validates the ledger and content. Logical compaction does not necessarily shrink SQLite's allocated file; offline `VACUUM` is a separate maintenance operation after backup.

## Historical-state migration

Point migration at a legacy **records directory**, excluding credentials, not an entire development checkout. `migrate LEGACY TARGET` is a nonmutating inventory and conversion plan. Review its digest, then `migrate LEGACY TARGET --apply --digest INPUT-DIGEST`. Conversion is copy-on-write, preserves exact source bytes/modes as historical artifacts and creates unresolved DRAFT state. Old approvals and successful results never become current v2.1 authority.

Interrupted imports resume using matching source bytes. Recovery handles an interruption between state-directory rename and controller-pointer write. `rollback TARGET --actor operator` selects the original legacy state and preserves the new history. Reapplying the completed conversion does not undo an explicit rollback. Maintain existing product source with a fresh Blueprint/Plan that reconciles its real tracked files and target requirements; no obsolete language/lane classification is needed.
