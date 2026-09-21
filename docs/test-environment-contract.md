# Test-environment registry contract

`config/test-environments.yaml` is the single registry consumed by `testctl` and `agentctl`.

A lane declares:

- canonical name and aliases;
- execution type (`compose` or `external-cli`);
- supported capabilities;
- service/runner or external executable;
- evidence pattern;
- any distribution-specific contract fields.

Adding a simulator requires a new lane rather than editing agent prompts. The lane must mount `/home/kazwong/codes/agents` at the same path, return a non-zero status on failure, write machine-readable summaries, avoid physical devices by default, and document supported actions. R2/R3 manifests select required lanes explicitly.

## v2.0.2 exact-candidate integration contract

The coordinator never delegates a required integration lane against the writable development worktree. It creates a detached candidate checkout under `.agent-state/verifiers/integration/<project>/<work-item>/<candidate>`, delegates the lane against that host-visible path, copies retained results into the canonical work-item evidence directory, and removes the verifier checkout. This isolates `build/`, `install/`, `log/`, and `.test-results/` products from development state.

Every integration summary records `candidate_sha` and `verification_source`. For the `ros2-humble` `test` action, return code zero is necessary but insufficient: the framework requires a positive executed-test count from retained JUnit or another explicit machine-readable summary. Explicit zero or missing positive evidence fails closed.
