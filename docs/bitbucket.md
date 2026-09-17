# Bitbucket integration

The root Pipeline validates the source tree and generated projects, then builds the three images. A custom self-hosted runner pipeline adds live Docker smoke tests and the external ROS 2 Humble smoke test.

`bitbucket-pr` infers the workspace/repository from common Bitbucket SSH and HTTPS remotes. `prepare` prints a dry-run payload. `create --execute` performs the API write only after `agentctl approve WORK-ID pr`.

After Bitbucket Pipelines finishes, record its immutable build URL and commit:

```bash
agentctl record-ci RBT-123 --status passed --url BUILD_URL --commit COMMIT_SHA
```

Branch restrictions, required builds, approval counts, unresolved-task checks, and merge permissions must also be configured in Bitbucket. The local workflow does not replace server-side protection.
