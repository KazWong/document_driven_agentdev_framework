# Debugger policy

Generated from `src/agent_framework/data/policy.json`.

Product access: read_only.

Allowed outputs: diagnosis.

Independent test access: read_only_when_needed.

Forbidden operations: product_write, test_write, approve, scm_write.

The controller validates role, stage, input digest and exact candidate. Missing isolation blocks execution. This role grants no human approval and cannot mutate Git or controller state.
