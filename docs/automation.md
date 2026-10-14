# Running the automation repair

This is a corrected v2.1.0 candidate. Use a new work item and retain the closed ROS2 test-kit records. Do not overwrite their ledger, change recorded verdicts or reuse old acceptance as evidence for this framework build.

## Install and configure

Install this source using the README instructions and rebuild the role/provider images that contain framework code. Register their immutable generations and named credentials through the existing environment commands. `agentctl doctor` must report a usable Docker backend. Source-only installation does not update code baked into an existing image.

Define the usual controller command with your actual paths:

```bash
fw() {
  agentctl --project /absolute/product-repository \
    --state /absolute/private-state \
    --environments /absolute/environment-registry \
    --work WORK-NEW "$@"
}
```

Copy `examples/automation.json` outside the product repository. Replace the generation, requirement and provider action IDs with real promoted IDs. `authorize_remote: true` explicitly enables branch/PR publication and later promotion for a Plan that already authorizes SCM. The repair budget bounds automatic attempts; it never grants permission to broaden scope or edit Tester-owned cases.

For human code review, the Plan must contain `"delivery": "scm"` and an `scm` object like `examples/scm-github.json` or `examples/scm-bitbucket.json`. Set the actual required CI names/keys and human account allowlist. Include this delivery requirement in the original request so Planner emits it. An artifact-delivery package does not silently become an SCM package.

GitHub uses the authenticated `gh` CLI (or controller `GH_TOKEN`/`GITHUB_TOKEN`). Bitbucket Cloud uses controller `BITBUCKET_TOKEN`: use a bearer access token, or also set `BITBUCKET_EMAIL` for API-token Basic authentication. Git transport must authenticate independently through an SSH agent/key or credential helper. Never put tokens in the Plan, request, source repository or agent-visible configuration.

The publishing account should be the automation/service account. The human reviewer is an allowed account able to review its PR. This avoids a platform's prohibition on approving one's own PR.

## Run once and let the controller wait

```bash
fw new 'Implement the requested change; deliver through the specified SCM repository and human reviewers' \
  --permission-file /absolute/intake-permissions.json
fw run --config /absolute/automation.json --watch --timeout 86400
```

At `APPROVAL_READY`, inspect the package using `fw status` and `fw read PACKAGE-ID` from another terminal. One human approves the exact digest:

```bash
fw approve --actor your-identity --digest CURRENT-PACKAGE-DIGEST
```

The watcher resumes, runs implementation and verification, pushes the accepted branch, and opens or updates its PR. Review the current commit on the platform:

- GitHub: submit an approving review as an allowed human.
- Bitbucket Cloud: approve the PR and post a comment exactly `APPROVE FULL-CANDIDATE-SHA` as the same allowed human. Use the full SHA from the PR description/status.

The controller waits for required CI and imports that one human approval. It rechecks remote evidence, attempts a normal fast-forward promotion and records closure. There is no second human requirement at R2/R3.

`fw run --config ...` performs a single resumable pass. `fw sync-review` imports a remote approval explicitly when not using the watcher. A watch timeout leaves recorded progress intact. Neither `run` nor `sync-review` submits a human review on your behalf.

For intentionally local artifact delivery, the release gate remains:

```bash
fw approve --release --actor your-identity --digest CURRENT-ACCEPTANCE-DIGEST
```

## Sandbox compatibility

Build outputs can execute under `/work`; `/tmp` stays non-executable. Docker still uses a read-only root, dropped capabilities, no-new-privileges and protected read-only tests.

Some Linux hosts block Codex's nested Bubblewrap sandbox. The backend accepts an optional global `--docker-runtime-profile /absolute/profile.json`. This replaces kit monkeypatching with a checked deployment input. It applies only to the exact configured image and argv; it cannot select an unconfined profile or add privileges. An administrator must install the named AppArmor policy and generate a passing sandbox probe for that image on that host. This package does not claim that a profile was installed or probed here.

Profile fields: `image`, `argv`, `apparmor` (a named `agent-fw-*` policy), `seccomp_path`, `seccomp_sha256`, `proof_path`, `proof_sha256`. The seccomp policy must deny by default. The proof uses the existing Docker ExecutionResult shape and must contain successful `BWRAP_READ_ONLY_PASS`, `BWRAP_WORKSPACE_WRITE_PASS` and `BWRAP_PROBE_PASS` markers. Keep these trusted deployment files outside writable agent directories. Rebuild/reprobe when the image or security configuration changes.

## Explicit stopping conditions

The controller stops on unavailable environments/credentials, unsupported provider requirements, stale or conflicting state, unknown dirty files, exhausted repair budgets, revoked human reviews, or server branch-policy rejection. It reports the responsible stage instead of fabricating a pass. It does not auto-rebase an accepted candidate; a new SHA requires fresh evidence.

Run the host regression suite before target-host acceptance:

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest -q
python scripts/verify_release.py
python scripts/generate_projection.py --check
```

The delivered test results are host/contract evidence. A fresh target-host run from intake through remote review and closure is still necessary to establish live autonomy.

## Recovery and rejection behavior in repair 20261014-r1

Automation configuration is a strict object. `authorize_remote` must be a JSON boolean: `false` denies remote mutation; the string `"false"` is rejected. Repair budget is an integer from 0 through 10 (default 2). Planner revisions reserve a persistent attempt before dispatch; an invalid revision consumes an attempt, and restarting does not reset the budget. A rejected schema/semantic output is retained with its field-level finding. Fresh revision context contains the failure instead of silently reusing the invalid output. Pre-approval Tester/Coder/reconciliation rejection returns to Planner; any revised engineering package requires a new human approval.

Coder implementations are checked against their exact changed paths, task/requirement/design mappings, scope, protected tests and complete obligations before controller files are copied. File applications have a durable before/after journal. The role job and automation receipt commit in one SQLite transaction. A restart retains a committed application or restores an uncommitted one; an unknown external edit stops recovery.

```bash
fw recover-role
fw recover-candidate
```

Normal automation invokes matching recovery itself. `recover-candidate` accepts only the current work/package and exact intended Git tree; it covers interruption both before and after commit. Do not modify recovery journals to bypass an error. These checks exercise process interruption, not a proof against every filesystem, storage or power-loss failure.

State and environment registry directories must be owner-only (mode 0700) and outside the product checkout. For an existing trusted directory, review its ownership/contents before explicitly correcting permissions; the controller never silently makes an arbitrary directory private. Trusted Git alone receives SSH agent variables; role/provider processes do not. Git delivery permits exactly one approved fetch URL and one approved push URL. Docker client TLS/configuration variables are preserved at the trusted Docker boundary.
