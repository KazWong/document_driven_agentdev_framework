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
